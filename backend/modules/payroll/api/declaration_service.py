"""Monthly declarations (INPS, AMO, ITS, employer taxes — codes come from the rule set) and the
annual recap, built from the payslips of approved or paid runs."""
from __future__ import annotations

import datetime
from typing import Any

import psycopg

from core.domain.result import Err, Ok, Result
from modules.payroll.api.rows import fetch_all, jsonable
from modules.payroll.domain.declarations import Declaration, annual_recap, available_codes, build_declaration


def declaration_json(declaration: Declaration, **extra: Any) -> dict[str, Any]:
    return jsonable({"code": declaration.code, "columns": list(declaration.columns), "rows": list(declaration.rows),
                     "totals": declaration.totals, **extra})


class DeclarationService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    def _payslips(self, tenant_id: str, where: str, params: tuple) -> list[dict[str, Any]]:
        payslips = fetch_all(
            self.connection,
            f"""
            SELECT p.id, p.employee_id, p.employee_no, p.full_name, p.snapshot->'employee' AS employee, r.period,
                   p.gross, p.employee_contrib, p.employer_contrib, p.its, p.net
            FROM payroll.payslips p JOIN payroll.runs r ON r.id = p.run_id
            WHERE p.tenant_id = %s AND r.status IN ('approved', 'paid') AND {where}
            ORDER BY p.employee_no
            """,
            (tenant_id, *params),
        )
        lines = fetch_all(self.connection, "SELECT payslip_id, section, code, base, amount, declaration_code FROM payroll.payslip_lines "
                                           "WHERE payslip_id = ANY(%s::text[])", ([payslip["id"] for payslip in payslips],)) if payslips else []
        by_payslip: dict[str, list[dict[str, Any]]] = {}
        for line in lines:
            by_payslip.setdefault(line.pop("payslip_id"), []).append(line)
        for payslip in payslips:
            employee = payslip.pop("employee") or {}
            payslip["identifiers"] = {"inps_no": employee.get("inps_no"), "amo_no": employee.get("amo_no")}
            payslip["lines"] = by_payslip.get(payslip["id"], [])
        return payslips

    def codes(self, *, tenant_id: str, period: datetime.date) -> list[str]:
        return available_codes(self._payslips(tenant_id, "r.period = %s", (period,)))

    def declaration(self, *, tenant_id: str, period: datetime.date, code: str) -> Result[Declaration]:
        built = build_declaration(code, self._payslips(tenant_id, "r.period = %s", (period,)))
        if built is None:
            return Err("NOT_FOUND", f"nothing to declare for {code} in {period:%Y-%m}", f"rien à déclarer pour {code} en {period:%m/%Y}")
        return Ok(built)

    def annual(self, *, tenant_id: str, year: int) -> Declaration:
        return annual_recap(self._payslips(tenant_id, "r.period >= %s AND r.period < %s",
                                           (datetime.date(year, 1, 1), datetime.date(year + 1, 1, 1))))
