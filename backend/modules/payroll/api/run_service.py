"""Payroll runs: one regular run per month, any number of off-cycle runs (final settlements,
corrections). draft -> calculated -> approved -> paid, or reversed from approved/paid.

hr is reached only through its api services (contract), injected so tests pass fakes.
"""
from __future__ import annotations

import datetime
from typing import Any

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.hr.api.payroll_snapshot_service import PayrollSnapshotService
from modules.hr.api.presence_service import PresenceService
from modules.payroll.api.rows import fetch_all, fetch_one, jsonable
from modules.payroll.api.rule_set_service import RuleSetService
from modules.payroll.api.run_state import EDITABLE, invalidate, lock_run, locked, not_found

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
