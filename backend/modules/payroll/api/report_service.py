"""Payroll figures for the HR dashboard and self-service (cross-phase contract, phase 3 -> phase 5).
Only approved or paid runs count: a calculated run is not final and a reversed one never happened."""
from __future__ import annotations

import datetime
from typing import Any

import psycopg

from modules.payroll.api.rows import fetch_all


class PayrollReportService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    def cost_by_department(self, *, tenant_id: str, period_from: datetime.date, period_to: datetime.date) -> list[dict[str, Any]]:
        return fetch_all(
            self.connection,
            """
            SELECT r.period, p.department_id, COUNT(DISTINCT p.employee_id)::int AS headcount,
                   SUM(p.gross) AS gross, SUM(p.employer_cost) AS employer_cost
            FROM payroll.payslips p JOIN payroll.runs r ON r.id = p.run_id
            WHERE p.tenant_id = %s AND r.status IN ('approved', 'paid') AND r.period BETWEEN %s AND %s
            GROUP BY r.period, p.department_id
            ORDER BY r.period, p.department_id
            """,
            (tenant_id, period_from, period_to),
        )

    def payslips_for_employee(self, *, tenant_id: str, employee_id: str) -> list[dict[str, Any]]:
        return fetch_all(
            self.connection,
            """
            SELECT p.id AS payslip_id, p.run_id, r.period, r.run_type, r.status AS run_status, p.gross, p.net, p.rule_set_status
            FROM payroll.payslips p JOIN payroll.runs r ON r.id = p.run_id
            WHERE p.tenant_id = %s AND p.employee_id = %s AND r.status IN ('approved', 'paid')
            ORDER BY r.period DESC, r.created_at DESC
            """,
            (tenant_id, employee_id),
        )
