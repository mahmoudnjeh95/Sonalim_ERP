"""Payroll runs: one regular run per month, any number of off-cycle runs (final settlements,
corrections). draft -> calculated -> approved -> paid, or reversed from approved/paid.

hr is reached only through its api services (contract), injected so tests pass fakes.
"""
from __future__ import annotations

import datetime
from dataclasses import asdict
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.types.json import Jsonb
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.hr.api.payroll_snapshot_service import PayrollSnapshotService
from modules.hr.api.presence_service import PresenceService
from modules.payroll.api.input_service import InputService
from modules.payroll.api.rows import fetch_all, fetch_one, jsonable
from modules.payroll.api.rule_set_service import RuleSetService
from modules.payroll.api.run_state import EDITABLE, invalidate, lock_run, locked, not_found
from modules.payroll.domain.earnings import monthly_equivalent, period_end
from modules.payroll.domain.engine import PayslipResult, calculate_payslip
from modules.payroll.domain.inputs import EmployeeInput, OneOffInput, SettlementInput
from modules.payroll.domain.rules import RuleSet
from modules.payroll.domain.settlement import reference_salary, years_of_service
from modules.payroll.domain.snapshot_mapping import employee_input, presence_input

RUN_TYPES = ("regular", "off_cycle")
RUN_SELECT = """
    SELECT r.id, r.period, r.run_type, r.label, r.employee_ids, r.rule_set_id, rs.status AS rule_set_status, r.status,
           r.created_by, r.created_at, r.calculated_by, r.calculated_at, r.approved_by, r.approved_at,
           r.paid_by, r.paid_at, r.reversed_by, r.reversed_at, r.reversal_reason,
           COUNT(p.id) AS payslip_count, COALESCE(SUM(p.gross), 0) AS gross, COALESCE(SUM(p.net), 0) AS net,
           COALESCE(SUM(p.employer_cost), 0) AS employer_cost,
           COUNT(p.id) FILTER (WHERE jsonb_array_length(p.warnings) > 0) AS warning_count
    FROM payroll.runs r
    LEFT JOIN payroll.rule_sets rs ON rs.id = r.rule_set_id
    LEFT JOIN payroll.payslips p ON p.run_id = r.id
"""
RUN_GROUP = " GROUP BY r.id, rs.status"


def _run_problem(period: datetime.date, run_type: str, employee_ids: list[str] | None) -> Err | None:
    if period.day != 1:
        return Err("RUN_INVALID", "the period is the first day of a month", "la période est le premier jour d'un mois")
    if run_type not in RUN_TYPES:
        return Err("RUN_INVALID", "a run is regular or off_cycle", "une paie est normale (regular) ou hors cycle (off_cycle)")
    if run_type == "regular" and employee_ids:
        return Err("RUN_INVALID", "a regular run pays everyone; choose employees on an off-cycle run",
                   "une paie normale paie tout le monde ; choisissez des employés sur une paie hors cycle")
    return None


def _ids(employee_ids: list[str] | None) -> list[str] | None:
    return sorted(set(employee_ids)) if employee_ids else None


class RunService:
    def __init__(self, connection: psycopg.Connection, *, snapshots: Any = None, presence: Any = None) -> None:
        self.connection = connection
        self.snapshots = snapshots if snapshots is not None else PayrollSnapshotService(connection)
        self.presence = presence if presence is not None else PresenceService(connection)

    def list_runs(self, *, tenant_id: str, status: str | None = None) -> list[dict[str, Any]]:
        clauses, params = ["r.tenant_id = %s"], [tenant_id]
        if status:
            clauses.append("r.status = %s")
            params.append(status)
        sql = RUN_SELECT + " WHERE " + " AND ".join(clauses) + RUN_GROUP + " ORDER BY r.period DESC, r.created_at DESC"
        return jsonable(fetch_all(self.connection, sql, params))

    def get_run(self, *, tenant_id: str, run_id: str) -> dict[str, Any] | None:
        row = fetch_one(self.connection, RUN_SELECT + " WHERE r.tenant_id = %s AND r.id = %s" + RUN_GROUP, (tenant_id, run_id))
        if row is None:
            return None
        document = jsonable(row)
        document["presence_closed"] = (
            self.presence.is_month_closed(tenant_id=tenant_id, period=row["period"]) if row["run_type"] == "regular" else None
        )
        in_force = RuleSetService(self.connection).in_force(tenant_id=tenant_id, period=row["period"])
        document["rule_set_in_force"] = None if isinstance(in_force, Err) else {
            "id": in_force.value["id"], "name": in_force.value["name"], "status": in_force.value["status"]}
        return document

    def create_run(self, *, tenant_id: str, actor_id: str, period: datetime.date, run_type: str,
                   label: str | None = None, employee_ids: list[str] | None = None) -> Result[dict[str, Any]]:
        problem = _run_problem(period, run_type, employee_ids)
        if problem is not None:
            return problem
        run_id = str(ULID())
        try:
            with self.connection.transaction():
                self.connection.execute(
                    "INSERT INTO payroll.runs (id, tenant_id, period, run_type, label, employee_ids, created_by) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (run_id, tenant_id, period, run_type, label, _ids(employee_ids), actor_id),
                )
        except psycopg.errors.UniqueViolation:
            return Err("DUPLICATE_RUN", f"a regular run already exists for {period:%Y-%m}",
                       f"une paie normale existe déjà pour {period:%m/%Y}")
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="payroll_run.created",
                     entity_type="payroll_run", entity_id=run_id,
                     payload={"period": period.isoformat(), "run_type": run_type, "label": label, "employee_ids": _ids(employee_ids)})
        return Ok(self.get_run(tenant_id=tenant_id, run_id=run_id))

    def update_run(self, *, tenant_id: str, actor_id: str, run_id: str, changes: dict[str, Any]) -> Result[dict[str, Any]]:
        run = lock_run(self.connection, tenant_id, run_id)
        if run is None:
            return not_found()
        if run["status"] not in EDITABLE:
            return locked(run["status"])
        unknown = sorted(set(changes) - {"label", "employee_ids"})
        if unknown:
            return Err("RUN_INVALID", f"unknown fields: {', '.join(unknown)}", f"champs inconnus : {', '.join(unknown)}")
        label = changes.get("label", run["label"])
        employee_ids = changes.get("employee_ids", run["employee_ids"])
        problem = _run_problem(run["period"], run["run_type"], employee_ids)
        if problem is not None:
            return problem
        self.connection.execute("UPDATE payroll.runs SET label = %s, employee_ids = %s WHERE id = %s", (label, _ids(employee_ids), run_id))
        if "employee_ids" in changes:
            invalidate(self.connection, run_id)
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="payroll_run.updated",
                     entity_type="payroll_run", entity_id=run_id, payload={"changes": jsonable(changes)})
        return Ok(self.get_run(tenant_id=tenant_id, run_id=run_id))

    def delete_run(self, *, tenant_id: str, actor_id: str, run_id: str) -> Result[dict[str, Any]]:
        run = lock_run(self.connection, tenant_id, run_id)
        if run is None:
            return not_found()
        if run["status"] not in EDITABLE:
            return locked(run["status"])
        self.connection.execute("DELETE FROM payroll.runs WHERE id = %s", (run_id,))
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="payroll_run.deleted",
                     entity_type="payroll_run", entity_id=run_id,
                     payload={"period": run["period"].isoformat(), "run_type": run["run_type"], "status": run["status"]})
        return Ok({"id": run_id})

    # -- final settlements ---------------------------------------------------------------------
    _SETTLEMENT_COLUMNS = "id, run_id, employee_id, employee_no, full_name, unused_leave_days, notice_months, created_by, created_at"

    def list_final_settlements(self, *, tenant_id: str, run_id: str) -> list[dict[str, Any]]:
        return jsonable(fetch_all(self.connection,
                                  f"SELECT {self._SETTLEMENT_COLUMNS} FROM payroll.final_settlements WHERE tenant_id = %s AND run_id = %s ORDER BY full_name",
                                  (tenant_id, run_id)))

    def _settlement(self, tenant_id: str, run_id: str, settlement_id: str) -> dict[str, Any] | None:
        return fetch_one(self.connection,
                         f"SELECT {self._SETTLEMENT_COLUMNS} FROM payroll.final_settlements WHERE tenant_id = %s AND run_id = %s AND id = %s",
                         (tenant_id, run_id, settlement_id))

    @staticmethod
    def _settlement_problem(unused_leave_days: Decimal, notice_months: Decimal) -> Err | None:
        if unused_leave_days is None or notice_months is None or unused_leave_days < 0 or notice_months < 0:
            return Err("SETTLEMENT_INVALID", "leave days and notice months are zero or more",
                       "les jours de congé et les mois de préavis sont positifs ou nuls")
        return None

    def _open_off_cycle(self, tenant_id: str, run_id: str) -> Result[dict[str, Any]]:
        run = lock_run(self.connection, tenant_id, run_id)
        if run is None:
            return not_found()
        if run["status"] not in EDITABLE:
            return locked(run["status"])
        if run["run_type"] != "off_cycle":
            return Err("SETTLEMENT_INVALID", "a final settlement goes on an off-cycle run", "un solde de tout compte se fait sur une paie hors cycle")
        return Ok(run)

    def add_final_settlement(self, *, tenant_id: str, actor_id: str, run_id: str, employee_id: str,
                             unused_leave_days: Decimal = Decimal(0), notice_months: Decimal = Decimal(0)) -> Result[dict[str, Any]]:
        opened = self._open_off_cycle(tenant_id, run_id)
        if isinstance(opened, Err):
            return opened
        run = opened.value
        problem = self._settlement_problem(unused_leave_days, notice_months)
        if problem is not None:
            return problem
        period = run["period"]
        found = self.snapshots.employees_for_period(tenant_id=tenant_id, period=period, employee_ids=[employee_id])
        if not found:
            return Err("NOT_FOUND", f"this employee has no contract in {period:%Y-%m}", f"cet employé n'a pas de contrat en {period:%m/%Y}")
        employee = found[0]
        termination = employee.get("termination_date")
        if termination is None or not period <= termination <= period_end(period):
            return Err("SETTLEMENT_INVALID",
                       f"{employee['full_name']} has no exit date in {period:%Y-%m}; record the termination in HR first",
                       f"{employee['full_name']} n'a pas de date de sortie en {period:%m/%Y} ; enregistrez d'abord la sortie dans RH")
        settlement_id = str(ULID())
        try:
            with self.connection.transaction():
                self.connection.execute(
                    "INSERT INTO payroll.final_settlements (id, tenant_id, run_id, employee_id, employee_no, full_name, unused_leave_days, notice_months, created_by) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (settlement_id, tenant_id, run_id, employee_id, employee["employee_no"], employee["full_name"], unused_leave_days, notice_months, actor_id),
                )
        except psycopg.errors.UniqueViolation:
            return Err("DUPLICATE_SETTLEMENT", "this employee is already settled in this run", "cet employé a déjà un solde dans cette paie")
        self.connection.execute("UPDATE payroll.runs SET employee_ids = %s WHERE id = %s",
                                (sorted(set(run["employee_ids"] or []) | {employee_id}), run_id))
        invalidate(self.connection, run_id)
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="final_settlement.created",
                     entity_type="final_settlement", entity_id=settlement_id,
                     payload=jsonable({"run_id": run_id, "employee_id": employee_id, "unused_leave_days": unused_leave_days,
                                       "notice_months": notice_months, "termination_date": termination}))
        return Ok(jsonable(self._settlement(tenant_id, run_id, settlement_id)))

    def update_final_settlement(self, *, tenant_id: str, actor_id: str, run_id: str, settlement_id: str,
                                changes: dict[str, Any]) -> Result[dict[str, Any]]:
        opened = self._open_off_cycle(tenant_id, run_id)
        if isinstance(opened, Err):
            return opened
        current = self._settlement(tenant_id, run_id, settlement_id)
        if current is None:
            return Err("NOT_FOUND", "final settlement not found", "solde de tout compte introuvable")
        unknown = sorted(set(changes) - {"unused_leave_days", "notice_months"})
        if unknown:
            return Err("SETTLEMENT_INVALID", f"unknown fields: {', '.join(unknown)}", f"champs inconnus : {', '.join(unknown)}")
        merged = {key: current[key] for key in ("unused_leave_days", "notice_months")} | changes
        problem = self._settlement_problem(merged["unused_leave_days"], merged["notice_months"])
        if problem is not None:
            return problem
        self.connection.execute("UPDATE payroll.final_settlements SET unused_leave_days = %s, notice_months = %s WHERE id = %s",
                                (merged["unused_leave_days"], merged["notice_months"], settlement_id))
        invalidate(self.connection, run_id)
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="final_settlement.updated",
                     entity_type="final_settlement", entity_id=settlement_id, payload={"changes": jsonable(changes)})
        return Ok(jsonable(self._settlement(tenant_id, run_id, settlement_id)))

    def remove_final_settlement(self, *, tenant_id: str, actor_id: str, run_id: str, settlement_id: str) -> Result[dict[str, Any]]:
        opened = self._open_off_cycle(tenant_id, run_id)
        if isinstance(opened, Err):
            return opened
        current = self._settlement(tenant_id, run_id, settlement_id)
        if current is None:
            return Err("NOT_FOUND", "final settlement not found", "solde de tout compte introuvable")
        self.connection.execute("DELETE FROM payroll.final_settlements WHERE id = %s", (settlement_id,))
        invalidate(self.connection, run_id)
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="final_settlement.deleted",
                     entity_type="final_settlement", entity_id=settlement_id,
                     payload=jsonable({key: current[key] for key in ("run_id", "employee_id", "unused_leave_days", "notice_months")}))
        return Ok({"id": settlement_id})

    # -- calculation -----------------------------------------------------------------------------
    def calculate(self, *, tenant_id: str, actor_id: str, run_id: str) -> Result[dict[str, Any]]:
        run = lock_run(self.connection, tenant_id, run_id)
        if run is None:
            return not_found()
        if run["status"] not in EDITABLE:
            return locked(run["status"])
        period = run["period"]
        regular = run["run_type"] == "regular"
        if regular and not self.presence.is_month_closed(tenant_id=tenant_id, period=period):
            return Err("PRESENCE_NOT_CLOSED", f"presence for {period:%Y-%m} is not closed; close the month in HR first",
                       f"la présence de {period:%m/%Y} n'est pas clôturée ; clôturez d'abord le mois dans RH")
        rule_sets = RuleSetService(self.connection)
        in_force = rule_sets.in_force(tenant_id=tenant_id, period=period)
        if isinstance(in_force, Err):
            return in_force
        rules = rule_sets.load(tenant_id=tenant_id, rule_set_id=in_force.value["id"])

        settlements = self._settlements(tenant_id, run_id)
        scope = None if regular else sorted(set(run["employee_ids"] or []) | set(settlements))
        if scope == []:
            return Err("RUN_EMPTY", "choose at least one employee for an off-cycle run", "choisissez au moins un employé pour une paie hors cycle")
        snapshots = self.snapshots.employees_for_period(tenant_id=tenant_id, period=period, employee_ids=scope)
        if regular:
            settled = self._settled_elsewhere(tenant_id, period, run_id)
            snapshots = [item for item in snapshots if item["employee_id"] not in settled]
        ids = [item["employee_id"] for item in snapshots]
        summaries = ({row["employee_id"]: row for row in self.presence.month_summary(tenant_id=tenant_id, period=period, employee_ids=ids)}
                     if ids else {})

        self.connection.execute("DELETE FROM payroll.payslips WHERE run_id = %s", (run_id,))
        inputs = InputService(self.connection, snapshots=self.snapshots)
        typed = inputs.run_inputs_by_employee(tenant_id=tenant_id, run_id=run_id)
        salaried = set(ids) if regular else set(settlements) & set(ids)
        deductions = inputs.due_deductions(tenant_id=tenant_id, period=period, employee_ids=sorted(salaried), settle_ids=set(settlements))

        written = 0
        for item in snapshots:
            employee_id = item["employee_id"]
            one_offs = typed.get(employee_id, []) + deductions.get(employee_id, [])
            include_salary = employee_id in salaried
            if not include_salary and not one_offs:
                continue
            employee = employee_input(item)
            settlement = self._settlement_input(tenant_id, rules, employee, settlements.get(employee_id), period)
            result = calculate_payslip(employee=employee, presence=presence_input(summaries.get(employee_id)), rules=rules,
                                       period=period, inputs=one_offs, settlement=settlement, include_salary=include_salary)
            if isinstance(result, Err):
                return Err(result.code, f"{item['full_name']}: {result.message}", f"{item['full_name']} : {result.message_fr}")
            self._write_payslip(tenant_id, run_id, rules, item, summaries.get(employee_id), one_offs, settlement, result.value)
            written += 1

        self.connection.execute(
            "UPDATE payroll.runs SET status = 'calculated', rule_set_id = %s, calculated_by = %s, calculated_at = clock_timestamp() WHERE id = %s",
            (rules.id, actor_id, run_id),
        )
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="payroll_run.calculated",
                     entity_type="payroll_run", entity_id=run_id,
                     payload={"from_status": run["status"], "to_status": "calculated", "rule_set_id": rules.id,
                              "rule_set_status": rules.status, "payslips": written})
        return Ok(self.get_run(tenant_id=tenant_id, run_id=run_id))

    def _write_payslip(self, tenant_id: str, run_id: str, rules: RuleSet, employee: dict[str, Any], summary: dict[str, Any] | None,
                       one_offs: list[OneOffInput], settlement: SettlementInput | None, result: PayslipResult) -> str:
        payslip_id = str(ULID())
        totals = result.totals
        document = {
            "employee": jsonable({key: value for key, value in employee.items() if key != "payment_methods"}),
            "presence": jsonable(summary or {}),
            "inputs": [jsonable(asdict(item)) for item in one_offs],
            "settlement": None if settlement is None else jsonable(asdict(settlement)),
            "payment_methods": jsonable(employee.get("payment_methods") or []),
            "rule_set": {"id": rules.id, "status": rules.status, "valid_from": rules.valid_from.isoformat()},
        }
        self.connection.execute(
            """
            INSERT INTO payroll.payslips (id, tenant_id, run_id, employee_id, employee_no, full_name, department_id, rule_set_id,
                rule_set_status, snapshot, gross, contributable, taxable, employee_contrib, employer_contrib, employer_charges,
                its, deductions, net, employer_cost, warnings)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (payslip_id, tenant_id, run_id, employee["employee_id"], employee["employee_no"], employee["full_name"],
             employee.get("department_id"), rules.id, rules.status, Jsonb(document), totals.gross, totals.contributable,
             totals.taxable, totals.employee_contrib, totals.employer_contrib, totals.employer_charges, totals.tax,
             totals.deductions, totals.net, totals.employer_cost, Jsonb(list(result.warnings))),
        )
        for number, line in enumerate(result.lines, start=1):
            self.connection.execute(
                """
                INSERT INTO payroll.payslip_lines (id, tenant_id, payslip_id, line_no, section, code, name_en, name_fr, base, qty,
                    rate, amount, taxable, contributable, declaration_code, source_kind, source_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (str(ULID()), tenant_id, payslip_id, number, line.section, line.code, line.name_en, line.name_fr, line.base,
                 line.qty, line.rate, line.amount, line.taxable, line.contributable, line.declaration_code, line.source_kind, line.source_id),
            )
        for carry in result.carry_forwards:
            self.connection.execute(
                "INSERT INTO payroll.carry_forwards (id, tenant_id, employee_id, component_code, amount, source_kind, source_id, source_payslip_id) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (str(ULID()), tenant_id, employee["employee_id"], carry.component_code, carry.amount, carry.source_kind, carry.source_id, payslip_id),
            )
        # Every advance / instalment / carried amount offered to the engine is settled by this payslip:
        # deducted in full, cut with the rest carried, or carried whole (the new carry row holds what is owed).
        marks = {"advance": "UPDATE payroll.advances SET deducted_payslip_id = %s WHERE id = %s",
                 "loan_instalment": "UPDATE payroll.loan_instalments SET payslip_id = %s WHERE id = %s",
                 "carry_forward": "UPDATE payroll.carry_forwards SET consumed_by_payslip_id = %s WHERE id = %s"}
        for item in one_offs:
            if item.source_kind in marks and item.source_id:
                self.connection.execute(marks[item.source_kind], (payslip_id, item.source_id))
        return payslip_id

    def _settlements(self, tenant_id: str, run_id: str) -> dict[str, dict[str, Any]]:
        rows = fetch_all(self.connection,
                         "SELECT id, employee_id, employee_no, full_name, unused_leave_days, notice_months FROM payroll.final_settlements "
                         "WHERE tenant_id = %s AND run_id = %s", (tenant_id, run_id))
        return {row["employee_id"]: row for row in rows}

    def _settled_elsewhere(self, tenant_id: str, period: datetime.date, run_id: str) -> set[str]:
        rows = self.connection.execute(
            """
            SELECT fs.employee_id FROM payroll.final_settlements fs JOIN payroll.runs r ON r.id = fs.run_id
            WHERE r.tenant_id = %s AND r.period = %s AND r.status <> 'reversed' AND r.id <> %s
            """,
            (tenant_id, period, run_id),
        ).fetchall()
        return {row[0] for row in rows}

    def _settlement_input(self, tenant_id: str, rules: RuleSet, employee: EmployeeInput, row: dict[str, Any] | None,
                          period: datetime.date) -> SettlementInput | None:
        if row is None:
            return None
        history = self.connection.execute(
            """
            SELECT p.gross FROM payroll.payslips p JOIN payroll.runs r ON r.id = p.run_id
            WHERE p.tenant_id = %s AND p.employee_id = %s AND r.run_type = 'regular' AND r.status IN ('approved', 'paid') AND r.period < %s
            ORDER BY r.period DESC LIMIT %s
            """,
            (tenant_id, employee.employee_id, period, rules.settlement_reference_months),
        ).fetchall()
        reference = reference_salary([gross for (gross,) in history], months=rules.settlement_reference_months,
                                     fallback=monthly_equivalent(employee, rules))
        end = employee.termination_date or period_end(period)
        return SettlementInput(reference_salary=reference, years_of_service=years_of_service(employee.hire_date, end),
                               unused_leave_days=row["unused_leave_days"], notice_months=row["notice_months"])
