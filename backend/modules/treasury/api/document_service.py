from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from core.events.outbox import publish_event
from modules.treasury.api.service import AccountMovementService, AccountService, SettingsService
from modules.treasury.domain.allocation import (
    ACCOUNT_KIND_FOR_METHOD,
    INSTRUMENT_METHODS,
    check_allocations,
    check_invoice_target,
    check_payments,
    check_prior_year,
)

NOUN = {"in": "receipt", "out": "disbursement"}
PREFIX = {"in": "ENC", "out": "DEC"}


def _not_found(document_id: str) -> Err:
    return Err("NOT_FOUND", f"document {document_id} not found", f"document {document_id} introuvable")


class DocumentService:
    """Receipts (direction 'in') and disbursements (direction 'out'). Callers commit."""

    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    # ---- reads ------------------------------------------------------------------------------

    def get(self, *, tenant_id: str, document_id: str, direction: str | None = None) -> Result[dict[str, Any]]:
        row = self._connection.execute(
            "SELECT id, direction, number, partner_id, doc_date, reason, with_details, currency, total, unallocated, "
            "status, note, created_at FROM treasury.documents WHERE id = %s AND tenant_id = %s",
            (document_id, tenant_id),
        ).fetchone()
        if row is None or (direction is not None and row[1] != direction):
            return _not_found(document_id)
        keys = ["id", "direction", "number", "partner_id", "doc_date", "reason", "with_details", "currency", "total",
                "unallocated", "status", "note", "created_at"]
        document = dict(zip(keys, row, strict=True))
        document["allocations"] = [
            {"invoice_id": r[0], "amount": r[1]}
            for r in self._connection.execute(
                "SELECT invoice_id, amount FROM treasury.document_allocations WHERE document_id = %s ORDER BY invoice_id",
                (document_id,),
            ).fetchall()
        ]
        document["payments"] = [
            {"id": r[0], "method": r[1], "amount": r[2], "account_id": r[3], "reference": r[4]}
            for r in self._connection.execute(
                "SELECT id, method, amount, account_id, reference FROM treasury.document_payments "
                "WHERE document_id = %s ORDER BY id",
                (document_id,),
            ).fetchall()
        ]
        document["instruments"] = [
            {"id": r[0], "method": r[1], "number": r[2], "bank_name": r[3], "due_date": r[4], "amount": r[5],
             "status": r[6], "payment_id": r[7]}
            for r in self._connection.execute(
                "SELECT id, method, number, bank_name, due_date, amount, status, payment_id "
                "FROM treasury.instruments WHERE document_id = %s ORDER BY due_date, id",
                (document_id,),
            ).fetchall()
        ]
        return Ok(document)

    def list(self, *, tenant_id: str, direction: str, partner_id: str | None = None, status: str | None = None,
             date_from: datetime.date | None = None, date_to: datetime.date | None = None) -> list[dict[str, Any]]:
        clauses, params = ["tenant_id = %s", "direction = %s"], [tenant_id, direction]
        for column, value, op in (("partner_id", partner_id, "="), ("status", status, "="),
                                  ("doc_date", date_from, ">="), ("doc_date", date_to, "<=")):
            if value:
                clauses.append(f"{column} {op} %s")
                params.append(value)
        rows = self._connection.execute(
            "SELECT id, number, partner_id, doc_date, reason, currency, total, unallocated, status "
            f"FROM treasury.documents WHERE {' AND '.join(clauses)} ORDER BY doc_date DESC, number DESC",
            params,
        ).fetchall()
        keys = ["id", "number", "partner_id", "doc_date", "reason", "currency", "total", "unallocated", "status"]
        return [dict(zip(keys, r, strict=True)) for r in rows]

    # ---- writes -----------------------------------------------------------------------------

    def create_and_post(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        direction: str,
        partner_id: str,
        doc_date: datetime.date,
        currency: str,
        payments: list[dict[str, Any]],
        allocations: list[dict[str, Any]] | None = None,
        reason: str = "full",
        with_details: bool = True,
        note: str | None = None,
        can_add_prior_year: bool = False,
        correlation_id: str,
    ) -> Result[dict[str, Any]]:
        allocations = allocations or []
        limit = SettingsService(self._connection).get_settings(tenant_id=tenant_id)["cash_payment_limit"]
        total = check_payments(Decimal("0"), payments, Decimal(str(limit)) if limit is not None else None)
        if isinstance(total, Err):
            return total
        pairs = [(a["invoice_id"], Decimal(str(a["amount"]))) for a in allocations]
        unallocated = check_allocations(total.value, pairs, with_details=with_details, reason=reason)
        if isinstance(unallocated, Err):
            return unallocated

        for invoice_id, amount in pairs:
            invoice = self._invoice(tenant_id, direction, invoice_id)
            if isinstance(invoice, Err):
                return invoice
            checked = check_invoice_target(invoice.value, amount, direction=direction, document_currency=currency, partner_id=partner_id)
            if isinstance(checked, Err):
                return checked
            prior = check_prior_year(invoice.value["invoice_date"], doc_date, allowed=can_add_prior_year)
            if isinstance(prior, Err):
                return prior

        accounts = AccountService(self._connection)
        for payment in payments:
            kind = ACCOUNT_KIND_FOR_METHOD.get(payment["method"])
            if kind is None:
                continue
            if not payment.get("account_id"):
                return Err("ACCOUNT_REQUIRED", f"a {payment['method']} payment needs an account", f"un paiement {payment['method']} exige un compte")
            account = accounts.get_account(tenant_id=tenant_id, account_id=payment["account_id"])
            if isinstance(account, Err):
                return account
            if account.value["kind"] != kind:
                return Err("ACCOUNT_KIND_MISMATCH", f"a {payment['method']} payment needs a {kind} account",
                           f"un paiement {payment['method']} exige un compte de type {kind}")
            if account.value["currency"] != currency:
                return Err("CURRENCY_MISMATCH", "the account is in another currency than the payment",
                           "le compte est dans une autre devise que le paiement")

        document_id = str(ULID())
        number = self._next_number(tenant_id, direction, doc_date.year)
        self._connection.execute(
            "INSERT INTO treasury.documents (id, tenant_id, direction, number, partner_id, doc_date, reason, with_details, "
            "currency, total, unallocated, note, created_by) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (document_id, tenant_id, direction, number, partner_id, doc_date, reason, with_details, currency,
             total.value, unallocated.value, note, actor_id),
        )
        for invoice_id, amount in pairs:
            self._connection.execute(
                "INSERT INTO treasury.document_allocations (document_id, invoice_id, amount) VALUES (%s, %s, %s)",
                (document_id, invoice_id, amount),
            )

        movements = AccountMovementService(self._connection)
        sign = Decimal("1") if direction == "in" else Decimal("-1")
        for payment in payments:
            payment_id = str(ULID())
            amount = Decimal(str(payment["amount"]))
            method = payment["method"]
            account_id = payment.get("account_id") if method not in INSTRUMENT_METHODS else None
            self._connection.execute(
                "INSERT INTO treasury.document_payments (id, document_id, method, amount, account_id, reference) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (payment_id, document_id, method, amount, account_id, payment.get("reference")),
            )
            if method in INSTRUMENT_METHODS:
                self._connection.execute(
                    "INSERT INTO treasury.instruments (id, tenant_id, direction, method, number, bank_name, due_date, amount, "
                    "currency, payment_id, document_id, account_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (str(ULID()), tenant_id, direction, method, payment["number"], payment["bank_name"],
                     payment["due_date"], amount, currency, payment_id, document_id, payment.get("account_id")),
                )
                continue
            moved = movements.post(
                tenant_id=tenant_id, actor_id=actor_id, account_id=account_id, signed_amount=sign * amount,
                source_type=NOUN[direction], source_id=document_id, occurred_on=doc_date, note=number,
            )
            if isinstance(moved, Err):
                return moved

        self._publish(tenant_id, correlation_id, direction, "posted", document_id, partner_id, pairs, total.value, currency)
        record_audit(self._connection, tenant_id=tenant_id, actor_id=actor_id, action=f"treasury.{NOUN[direction]}.posted",
                     entity_type=NOUN[direction], entity_id=document_id,
                     payload={"number": number, "total": str(total.value), "partner_id": partner_id})
        return self.get(tenant_id=tenant_id, document_id=document_id)

    def cancel(self, *, tenant_id: str, actor_id: str, document_id: str, direction: str, correlation_id: str) -> Result[dict[str, Any]]:
        row = self._connection.execute(
            "SELECT status, number, partner_id, doc_date, currency, total FROM treasury.documents "
            "WHERE id = %s AND tenant_id = %s AND direction = %s FOR UPDATE",
            (document_id, tenant_id, direction),
        ).fetchone()
        if row is None:
            return _not_found(document_id)
        status, number, partner_id, doc_date, currency, total = row
        if status != "posted":
            return Err("DOCUMENT_NOT_POSTED", "only a posted document can be cancelled", "seul un document comptabilisé peut être annulé")
        processed = self._connection.execute(
            "SELECT 1 FROM treasury.instruments WHERE document_id = %s AND status IN ('collected', 'unpaid') LIMIT 1",
            (document_id,),
        ).fetchone()
        if processed:
            return Err("INSTRUMENT_ALREADY_PROCESSED", "a cheque or draft of this document was already collected or rejected",
                       "un chèque ou une traite de ce document a déjà été encaissé ou rejeté")

        movements = AccountMovementService(self._connection)
        reverse = Decimal("-1") if direction == "in" else Decimal("1")
        payments = self._connection.execute(
            "SELECT method, amount, account_id FROM treasury.document_payments WHERE document_id = %s", (document_id,)
        ).fetchall()
        for method, amount, account_id in payments:
            if method in INSTRUMENT_METHODS:
                continue
            moved = movements.post(
                tenant_id=tenant_id, actor_id=actor_id, account_id=account_id, signed_amount=reverse * amount,
                source_type=f"{NOUN[direction]}_cancelled", source_id=document_id, occurred_on=datetime.date.today(),
                note=number,
            )
            if isinstance(moved, Err):
                return moved
        self._connection.execute("UPDATE treasury.instruments SET status = 'cancelled' WHERE document_id = %s", (document_id,))
        self._connection.execute(
            "UPDATE treasury.documents SET status = 'cancelled', cancelled_at = NOW() WHERE id = %s", (document_id,)
        )
        allocations = [(r[0], r[1]) for r in self._connection.execute(
            "SELECT invoice_id, amount FROM treasury.document_allocations WHERE document_id = %s", (document_id,)).fetchall()]
        self._publish(tenant_id, correlation_id, direction, "cancelled", document_id, partner_id, allocations, total, currency)
        record_audit(self._connection, tenant_id=tenant_id, actor_id=actor_id, action=f"treasury.{NOUN[direction]}.cancelled",
                     entity_type=NOUN[direction], entity_id=document_id, payload={"number": number})
        return self.get(tenant_id=tenant_id, document_id=document_id)

    # ---- helpers ----------------------------------------------------------------------------

    def _invoice(self, tenant_id: str, direction: str, invoice_id: str) -> Result[dict[str, Any]]:
        if direction == "in":
            from modules.finance.api.service import InvoiceService

            return InvoiceService(self._connection).get_invoice(tenant_id=tenant_id, invoice_id=invoice_id)
        from modules.procurement.api.invoice_service import PurchaseInvoiceService

        return PurchaseInvoiceService(self._connection).get_invoice(tenant_id=tenant_id, invoice_id=invoice_id)

    def _next_number(self, tenant_id: str, direction: str, year: int) -> str:
        row = self._connection.execute(
            """
            INSERT INTO treasury.document_counters (tenant_id, direction, year, last_number) VALUES (%s, %s, %s, 1)
            ON CONFLICT (tenant_id, direction, year)
            DO UPDATE SET last_number = treasury.document_counters.last_number + 1
            RETURNING last_number
            """,
            (tenant_id, direction, year),
        ).fetchone()
        return f"{PREFIX[direction]}-{year}-{row[0]:06d}"

    def _publish(self, tenant_id: str, correlation_id: str, direction: str, verb: str, document_id: str,
                 partner_id: str, allocations: list[tuple[str, Decimal]], total: Decimal, currency: str) -> None:
        noun = NOUN[direction]
        payload: dict[str, Any] = {
            f"{noun}_id": document_id,
            "allocations": [{"invoice_id": invoice_id, "amount": str(amount)} for invoice_id, amount in allocations],
        }
        if verb == "posted":
            payload.update({"partner_id": partner_id, "total": str(total), "currency": currency})
        publish_event(self._connection, event_type=f"treasury.{noun}.{verb}", producer="treasury",
                      tenant_id=tenant_id, correlation_id=correlation_id, payload=payload)
