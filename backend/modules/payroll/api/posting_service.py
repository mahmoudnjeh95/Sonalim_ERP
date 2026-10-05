"""What finance posts for a payroll run (cross-phase contract, phase 3 -> phase 4).

posting_lines: one row per (employee, source_kind, code), amounts positive. An earning line with a
negative amount (unpaid absence) is folded into the same employee's BASE row, so that per employee
sum(earning) = sum(deduction) + sum(employee_contribution) + sum(tax) + net, and employer
contributions / charges are posted on their own (expense against liability).
payment_lines: how the net left the company, from the run's payout lines.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

import psycopg

from modules.payroll.api.rows import fetch_all
from modules.payroll.domain.rules import BASE

ZERO = Decimal(0)


class PayrollPostingService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    def posting_lines(self, *, tenant_id: str, run_id: str) -> list[dict[str, Any]]:
        rows = fetch_all(
            self.connection,
            """
            SELECT p.employee_id, l.section, l.code, SUM(l.amount) AS amount
            FROM payroll.payslip_lines l JOIN payroll.payslips p ON p.id = l.payslip_id
            WHERE p.tenant_id = %s AND p.run_id = %s AND l.section <> 'relief'
            GROUP BY p.employee_id, l.section, l.code
            """,
            (tenant_id, run_id),
        )
        totals: dict[tuple[str, str, str], Decimal] = {}
        for row in rows:
            code = BASE if row["section"] == "earning" and row["amount"] < 0 else row["code"]
            key = (row["employee_id"], row["section"], code)
            totals[key] = totals.get(key, ZERO) + row["amount"]
        nets = fetch_all(self.connection, "SELECT employee_id, net FROM payroll.payslips WHERE tenant_id = %s AND run_id = %s AND net > 0",
                         (tenant_id, run_id))
        for row in nets:
            totals[(row["employee_id"], "net", "NET")] = row["net"]
        return [{"source_kind": kind, "code": code, "amount": amount, "employee_id": employee_id}
                for (employee_id, kind, code), amount in sorted(totals.items()) if amount > 0]

    def payment_lines(self, *, tenant_id: str, run_id: str) -> list[dict[str, Any]]:
        rows = fetch_all(
            self.connection,
            """
            SELECT b.method, l.employee_id, SUM(l.amount) AS amount
            FROM payroll.payout_lines l JOIN payroll.payout_batches b ON b.id = l.batch_id
            WHERE b.tenant_id = %s AND b.run_id = %s
            GROUP BY b.method, l.employee_id
            ORDER BY l.employee_id, b.method
            """,
            (tenant_id, run_id),
        )
        return [{"method": row["method"], "amount": row["amount"], "employee_id": row["employee_id"]} for row in rows]
