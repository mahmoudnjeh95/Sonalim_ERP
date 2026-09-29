"""Payslips as people read them: detail, print data, the work certificate, the admin edit, and the
comparison with last month."""
from __future__ import annotations

import datetime
from dataclasses import asdict
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.payroll.api.company import company_header
from modules.payroll.api.rows import fetch_all, fetch_one, jsonable
from modules.payroll.api.run_state import locked
from modules.payroll.domain.loans import add_months
from modules.payroll.domain.payouts import validate_methods
from modules.payroll.domain.variance import compare

_COLUMNS = ("p.id, p.run_id, p.employee_id, p.employee_no, p.full_name, p.department_id, p.gross, p.contributable, p.taxable, "
            "p.employee_contrib, p.employer_contrib, p.employer_charges, p.its, p.deductions, p.net, p.employer_cost, "
            "p.warnings, p.rule_set_status, p.note")
_DETAIL = f"SELECT {_COLUMNS}, p.snapshot, r.period, r.run_type, r.status AS run_status FROM payroll.payslips p JOIN payroll.runs r ON r.id = p.run_id"
_LINES = "SELECT payslip_id, line_no, section, code, name_en, name_fr, base, qty, rate, amount FROM payroll.payslip_lines"


class PayslipService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    def list_payslips(self, *, tenant_id: str, run_id: str) -> list[dict[str, Any]]:
        return jsonable(fetch_all(self.connection, f"SELECT {_COLUMNS} FROM payroll.payslips p WHERE p.tenant_id = %s AND p.run_id = %s ORDER BY p.full_name",
                                  (tenant_id, run_id)))

    def _with_lines(self, payslips: list[dict[str, Any]], company: dict[str, Any]) -> list[dict[str, Any]]:
        if not payslips:
            return []
        lines = fetch_all(self.connection, _LINES + " WHERE payslip_id = ANY(%s::text[]) ORDER BY payslip_id, line_no",
                          ([payslip["id"] for payslip in payslips],))
        by_payslip: dict[str, list[dict[str, Any]]] = {}
        for line in lines:
            by_payslip.setdefault(line.pop("payslip_id"), []).append(line)
        documents = []
        for payslip in payslips:
            document = jsonable(payslip)
            document["lines"] = jsonable(by_payslip.get(payslip["id"], []))
            document["company"] = company
            documents.append(document)
        return documents

    def get_payslip(self, *, tenant_id: str, payslip_id: str) -> dict[str, Any] | None:
        row = fetch_one(self.connection, _DETAIL + " WHERE p.tenant_id = %s AND p.id = %s", (tenant_id, payslip_id))
        if row is None:
            return None
        return self._with_lines([row], company_header(self.connection, tenant_id))[0]

    def run_print(self, *, tenant_id: str, run_id: str) -> dict[str, Any] | None:
        run = fetch_one(self.connection, "SELECT id, period, run_type, label, status FROM payroll.runs WHERE tenant_id = %s AND id = %s", (tenant_id, run_id))
        if run is None:
            return None
        rows = fetch_all(self.connection, _DETAIL + " WHERE p.tenant_id = %s AND p.run_id = %s ORDER BY p.full_name", (tenant_id, run_id))
        company = company_header(self.connection, tenant_id)
        return {"run": jsonable(run), "company": company, "payslips": self._with_lines(rows, company)}

    def certificate(self, *, tenant_id: str, payslip_id: str) -> Result[dict[str, Any]]:
        payslip = self.get_payslip(tenant_id=tenant_id, payslip_id=payslip_id)
        if payslip is None or not payslip["snapshot"].get("settlement"):
            return Err("NOT_FOUND", "no work certificate: this payslip is not a final settlement",
                       "pas de certificat de travail : ce bulletin n'est pas un solde de tout compte")
        employee = payslip["snapshot"]["employee"]
        return Ok({"company": payslip["company"], "full_name": payslip["full_name"], "employee_no": payslip["employee_no"],
                   "hire_date": employee.get("hire_date"), "termination_date": employee.get("termination_date"),
                   "termination_reason": employee.get("termination_reason"), "position_id": employee.get("position_id"),
                   "contract_type": (employee.get("contract") or {}).get("contract_type"),
                   "issued_on": datetime.date.today().isoformat()})

    def admin_update_payslip(self, *, tenant_id: str, actor_id: str, payslip_id: str, changes: dict[str, Any]) -> Result[dict[str, Any]]:
        row = fetch_one(self.connection, "SELECT p.id, p.run_id, p.snapshot, p.note, r.status FROM payroll.payslips p JOIN payroll.runs r ON r.id = p.run_id "
                                         "WHERE p.tenant_id = %s AND p.id = %s FOR UPDATE OF p", (tenant_id, payslip_id))
        if row is None:
            return Err("NOT_FOUND", "payslip not found", "bulletin introuvable")
        unknown = sorted(set(changes) - {"note", "payment_methods"})
        if unknown:
            return Err("PAYSLIP_INVALID", f"only the note and the payment details can be edited ({', '.join(unknown)})",
                       f"seuls la note et les coordonnées de paiement se modifient ({', '.join(unknown)})")
        if row["status"] in ("paid", "reversed"):
            return locked(row["status"])
        snapshot = dict(row["snapshot"])
        if "payment_methods" in changes:
            checked = validate_methods(changes["payment_methods"] or [])
            if isinstance(checked, Err):
                return checked
            confirmed = self.connection.execute("SELECT 1 FROM payroll.payout_batches WHERE run_id = %s AND status = 'confirmed' LIMIT 1",
                                                (row["run_id"],)).fetchone()
            if confirmed is not None:
                return Err("PAYOUT_CONFIRMED", "a payout batch of this run is confirmed; payment details can no longer change",
                           "un lot de paiement de cette paie est confirmé ; les coordonnées de paiement ne peuvent plus changer")
            snapshot["payment_methods"] = jsonable(checked.value)
            self.connection.execute("DELETE FROM payroll.payout_batches WHERE run_id = %s", (row["run_id"],))
        note = changes.get("note", row["note"])
        self.connection.execute("UPDATE payroll.payslips SET note = %s, snapshot = %s WHERE id = %s", (note, Jsonb(snapshot), payslip_id))
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="payslip.updated", entity_type="payslip",
                     entity_id=payslip_id, payload={"changes": jsonable(changes)})
        return Ok(self.get_payslip(tenant_id=tenant_id, payslip_id=payslip_id))

    def variance(self, *, tenant_id: str, run_id: str) -> dict[str, Any] | None:
        run = fetch_one(self.connection, "SELECT id, period FROM payroll.runs WHERE tenant_id = %s AND id = %s", (tenant_id, run_id))
        if run is None:
            return None
        previous_period = add_months(run["period"], -1)
        previous_run = fetch_one(self.connection, "SELECT id FROM payroll.runs WHERE tenant_id = %s AND period = %s AND run_type = 'regular' "
                                                  "AND status IN ('approved', 'paid') ORDER BY approved_at DESC LIMIT 1", (tenant_id, previous_period))
        figures = "SELECT employee_id, employee_no, full_name, gross, net FROM payroll.payslips WHERE run_id = %s"
        current = fetch_all(self.connection, figures, (run_id,))
        previous = fetch_all(self.connection, figures, (previous_run["id"],)) if previous_run else []
        rows = [{**asdict(row), "delta_gross": row.delta_gross, "delta_net": row.delta_net, "change": row.change}
                for row in compare(current, previous)]
        zero = Decimal(0)
        totals = {"previous_gross": sum((row["gross"] for row in previous), zero), "current_gross": sum((row["gross"] for row in current), zero),
                  "previous_net": sum((row["net"] for row in previous), zero), "current_net": sum((row["net"] for row in current), zero)}
        return jsonable({"previous_run_id": previous_run["id"] if previous_run else None, "previous_period": previous_period,
                         "rows": rows, "totals": totals})
