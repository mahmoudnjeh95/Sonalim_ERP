"""Payment arrangements: dated sets of methods, always written as a whole so their shares add up."""
from __future__ import annotations

import datetime
from collections.abc import Sequence

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.hr.domain.payment import PaymentMethod, set_in_force, validate_payment_set


class PaymentMethodService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    def list_sets(self, *, tenant_id: str, employee_id: str, today: datetime.date | None = None) -> list[dict]:
        """Every arrangement of the employee, newest first, flagging the one in force on `today`."""
        day = today or datetime.date.today()
        rows = self.connection.execute(
            """
            SELECT id, method, bank_name, account_no, mobile_operator, mobile_number, share_percent, is_primary, valid_from
            FROM hr.payment_methods
            WHERE tenant_id = %s AND employee_id = %s
            ORDER BY valid_from DESC, sort_order
            """,
            (tenant_id, employee_id),
        ).fetchall()
        in_force = set_in_force((row[8] for row in rows), day)
        sets: dict[datetime.date, dict] = {}
        for row in rows:
            entry = sets.setdefault(row[8], {"valid_from": row[8].isoformat(), "in_force": row[8] == in_force, "methods": []})
            entry["methods"].append(
                {
                    "id": row[0],
                    "method": row[1],
                    "bank_name": row[2],
                    "account_no": row[3],
                    "mobile_operator": row[4],
                    "mobile_number": row[5],
                    "share_percent": row[6],
                    "is_primary": row[7],
                }
            )
        return list(sets.values())

    def set_exists(self, *, tenant_id: str, employee_id: str, valid_from: datetime.date) -> bool:
        row = self.connection.execute(
            "SELECT 1 FROM hr.payment_methods WHERE tenant_id = %s AND employee_id = %s AND valid_from = %s LIMIT 1",
            (tenant_id, employee_id, valid_from),
        ).fetchone()
        return row is not None

    def set_holds_numbers(self, *, tenant_id: str, employee_id: str, valid_from: datetime.date) -> bool:
        """Whether the set starting on `valid_from` carries a bank account or mobile number today,
        before a replace or a remove is about to overwrite or delete it."""
        row = self.connection.execute(
            """
            SELECT 1 FROM hr.payment_methods
            WHERE tenant_id = %s AND employee_id = %s AND valid_from = %s
              AND (account_no IS NOT NULL OR mobile_number IS NOT NULL)
            LIMIT 1
            """,
            (tenant_id, employee_id, valid_from),
        ).fetchone()
        return row is not None

    def replace_set(
        self, *, tenant_id: str, actor_id: str, employee_id: str, valid_from: datetime.date, methods: Sequence[PaymentMethod]
    ) -> Result[list[dict]]:
        """Write the arrangement starting on `valid_from` as a whole; an empty list removes it."""
        employee = self.connection.execute(
            "SELECT 1 FROM hr.employees WHERE id = %s AND tenant_id = %s FOR UPDATE", (employee_id, tenant_id)
        ).fetchone()
        if employee is None:
            return Err("NOT_FOUND", "employee not found", "employé introuvable")
        existed = self.set_exists(tenant_id=tenant_id, employee_id=employee_id, valid_from=valid_from)
        if not methods:
            if not existed:
                return Err("NOT_FOUND", "no payment arrangement starts on that date", "aucun mode de paiement ne commence à cette date")
            lines: tuple[PaymentMethod, ...] = ()
        else:
            validated = validate_payment_set(methods)
            if isinstance(validated, Err):
                return validated
            lines = validated.value
        self.connection.execute(
            "DELETE FROM hr.payment_methods WHERE tenant_id = %s AND employee_id = %s AND valid_from = %s", (tenant_id, employee_id, valid_from)
        )
        for order, line in enumerate(lines):
            self.connection.execute(
                """
                INSERT INTO hr.payment_methods (id, tenant_id, employee_id, method, bank_name, account_no, mobile_operator,
                                                mobile_number, share_percent, is_primary, valid_from, sort_order)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    str(ULID()), tenant_id, employee_id, line.method, line.bank_name, line.account_no, line.mobile_operator,
                    line.mobile_number, line.share_percent, line.is_primary, valid_from, order,
                ),
            )
        action = "payment_methods.removed" if not lines else "payment_methods.replaced" if existed else "payment_methods.created"
        record_audit(
            self.connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action=action,
            entity_type="employee",
            entity_id=employee_id,
            # Kinds and shares only: account and phone numbers stay out of the audit log.
            payload={
                "valid_from": valid_from.isoformat(),
                "methods": [{"method": line.method, "share_percent": str(line.share_percent), "is_primary": line.is_primary} for line in lines],
            },
        )
        return Ok(self.list_sets(tenant_id=tenant_id, employee_id=employee_id))
