"""What payroll (phase 3) reads from hr for one month. Server-side, so nothing is masked.
Contract with phase 3: docs/superpowers/plans/2026-09-25-hr-payroll-finance-interfaces.md."""
from __future__ import annotations

import datetime

import psycopg

from modules.hr.domain.dependant import Dependant, count_tax_dependants
from modules.hr.domain.payment import set_in_force
from modules.hr.domain.snapshot import month_bounds, pick_contract


class PayrollSnapshotService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    def employees_for_period(
        self, *, tenant_id: str, period: datetime.date, employee_ids: list[str] | None = None
    ) -> list[dict]:
        """Employees with an active contract on any day of the period."""
        first, last = month_bounds(period)
        params: list[object] = [tenant_id, last, first]
        narrow = ""
        if employee_ids is not None:
            narrow = " AND employee_id = ANY(%s)"
            params.append(list(employee_ids))
        rows = self.connection.execute(
            f"""
            SELECT id, employee_id, contract_type, base_salary, weekly_hours, pay_frequency, start_date, end_date
            FROM hr.contracts
            WHERE tenant_id = %s AND status <> 'draft' AND currency = 'XOF'
              AND start_date <= %s AND (end_date IS NULL OR end_date >= %s){narrow}
            """,
            params,
        ).fetchall()
        by_employee: dict[str, list[dict]] = {}
        for r in rows:
            by_employee.setdefault(r[1], []).append(
                {"id": r[0], "contract_type": r[2], "base_salary": r[3], "weekly_hours": r[4], "pay_frequency": r[5], "start_date": r[6], "end_date": r[7]}
            )
        chosen = {employee_id: pick_contract(contracts, first, last) for employee_id, contracts in by_employee.items()}
        if not chosen:
            return []
        ids = list(chosen)
        components = self._components([contract["id"] for contract in chosen.values()])
        dependants = self._dependants(tenant_id, ids)
        payments = self._payment_methods(tenant_id, ids, last)
        employees = self.connection.execute(
            """
            SELECT id, employee_no, first_name, last_name, department_id, position_id, grade_id, hire_date, termination_date, termination_reason, inps_no, amo_no
            FROM hr.employees WHERE tenant_id = %s AND id = ANY(%s) ORDER BY employee_no
            """,
            (tenant_id, ids),
        ).fetchall()
        return [
            {
                "employee_id": e[0],
                "employee_no": e[1],
                "full_name": f"{e[2]} {e[3]}",
                "department_id": e[4],
                "position_id": e[5],
                "grade_id": e[6],
                "hire_date": e[7],
                "termination_date": e[8],
                "termination_reason": e[9],
                "inps_no": e[10],
                "amo_no": e[11],
                "tax_dependants": count_tax_dependants(dependants.get(e[0], []), last),
                "contract": {**chosen[e[0]], "components": components.get(chosen[e[0]]["id"], [])},
                "payment_methods": payments.get(e[0], []),
            }
            for e in employees
        ]

    def _components(self, contract_ids: list[str]) -> dict[str, list[dict]]:
        rows = self.connection.execute(
            "SELECT contract_id, component_code, amount, rate FROM hr.contract_components WHERE contract_id = ANY(%s) ORDER BY component_code",
            (contract_ids,),
        ).fetchall()
        found: dict[str, list[dict]] = {}
        for contract_id, code, amount, rate in rows:
            found.setdefault(contract_id, []).append({"component_code": code, "amount": amount, "rate": rate})
        return found

    def _dependants(self, tenant_id: str, employee_ids: list[str]) -> dict[str, list[Dependant]]:
        rows = self.connection.execute(
            "SELECT employee_id, kind, name, valid_from, birth_date, dependent_for_tax, valid_to FROM hr.dependants "
            "WHERE tenant_id = %s AND employee_id = ANY(%s)",
            (tenant_id, employee_ids),
        ).fetchall()
        found: dict[str, list[Dependant]] = {}
        for row in rows:
            found.setdefault(row[0], []).append(Dependant(*row[1:]))
        return found

    def _payment_methods(self, tenant_id: str, employee_ids: list[str], last: datetime.date) -> dict[str, list[dict]]:
        """The arrangement in force on the last day of the month."""
        rows = self.connection.execute(
            """
            SELECT employee_id, valid_from, method, bank_name, account_no, mobile_operator, mobile_number, share_percent, is_primary
            FROM hr.payment_methods
            WHERE tenant_id = %s AND employee_id = ANY(%s) AND valid_from <= %s
            ORDER BY employee_id, sort_order
            """,
            (tenant_id, employee_ids, last),
        ).fetchall()
        starts: dict[str, list[datetime.date]] = {}
        for row in rows:
            starts.setdefault(row[0], []).append(row[1])
        in_force = {employee_id: set_in_force(days, last) for employee_id, days in starts.items()}
        found: dict[str, list[dict]] = {}
        for row in rows:
            if row[1] != in_force[row[0]]:
                continue
            found.setdefault(row[0], []).append(
                {
                    "method": row[2],
                    "bank_name": row[3],
                    "account_no": row[4],
                    "mobile_operator": row[5],
                    "mobile_number": row[6],
                    "share_percent": row[7],
                    "is_primary": row[8],
                }
            )
        return found
