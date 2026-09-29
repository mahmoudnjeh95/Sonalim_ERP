"""Run status rules shared by every service that touches a run."""
from __future__ import annotations

from typing import Any

import psycopg

from core.domain.result import Err
from modules.payroll.api.rows import fetch_one

EDITABLE = ("draft", "calculated")
STATUS_FR = {"draft": "brouillon", "calculated": "calculée", "approved": "approuvée", "paid": "payée", "reversed": "extournée"}
_COLUMNS = ("id, tenant_id, period, run_type, label, employee_ids, rule_set_id, status, created_by, "
            "calculated_by, calculated_at, approved_by, approved_at")


def lock_run(connection: psycopg.Connection, tenant_id: str, run_id: str) -> dict[str, Any] | None:
    return fetch_one(connection, f"SELECT {_COLUMNS} FROM payroll.runs WHERE tenant_id = %s AND id = %s FOR UPDATE", (tenant_id, run_id))


def not_found() -> Err:
    return Err("NOT_FOUND", "payroll run not found", "paie introuvable")


def locked(status: str) -> Err:
    return Err("RUN_LOCKED", f"the run is {status}; it can no longer change",
               f"la paie est {STATUS_FR.get(status, status)} ; elle ne peut plus changer")


def invalidate(connection: psycopg.Connection, run_id: str) -> bool:
    """A calculated run whose inputs changed goes back to draft and loses its payslips; what they
    had deducted (advances, instalments, carried amounts) is released by ON DELETE SET NULL."""
    changed = connection.execute(
        "UPDATE payroll.runs SET status = 'draft', rule_set_id = NULL, calculated_by = NULL, calculated_at = NULL "
        "WHERE id = %s AND status = 'calculated' RETURNING id",
        (run_id,),
    ).fetchone()
    if changed is not None:
        connection.execute("DELETE FROM payroll.payslips WHERE run_id = %s", (run_id,))
    return changed is not None
