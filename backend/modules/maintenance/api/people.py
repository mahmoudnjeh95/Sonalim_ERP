"""Name resolution for the maintenance module's two kinds of "who": `core.users`
(chefs, reviewers, requesters -- the shared kernel, reading it directly is allowed)
and HR employees (team members, performers -- reached only through
`modules.hr.api.employee_service.EmployeeService`, never SQL on `hr.*`).

Every `*_name` field in the API contract is resolved server-side through these
helpers so the frontend never has to join people data itself.
"""
from __future__ import annotations

from collections.abc import Iterable

import psycopg

from modules.hr.api.employee_service import EmployeeService


def user_names(connection: psycopg.Connection, tenant_id: str, user_ids: Iterable[str]) -> dict[str, str]:
    """`full_name` falling back to `email`, for each distinct, non-empty id. Unknown ids are omitted."""
    distinct_ids = [uid for uid in {u for u in user_ids if u}]
    if not distinct_ids:
        return {}
    rows = connection.execute(
        "SELECT id, full_name, email FROM core.users WHERE tenant_id = %s AND id = ANY(%s)",
        (tenant_id, distinct_ids),
    ).fetchall()
    return {row[0]: (row[1] or row[2]) for row in rows}


def employee_names(connection: psycopg.Connection, tenant_id: str, employee_ids: Iterable[str]) -> dict[str, str]:
    """`first_name last_name` for each distinct, non-empty employee id. Unknown ids are omitted."""
    distinct_ids = {e for e in employee_ids if e}
    if not distinct_ids:
        return {}
    service = EmployeeService(connection)
    names: dict[str, str] = {}
    for employee_id in distinct_ids:
        employee = service.get_employee(tenant_id=tenant_id, employee_id=employee_id)
        if employee is not None:
            names[employee_id] = employee["full_name"]
    return names


def active_employees(connection: psycopg.Connection, tenant_id: str) -> list[dict]:
    """Every active HR employee of the tenant, as `{id, name}` -- the pool `/team-candidates` picks from."""
    employees = EmployeeService(connection).list_employees(tenant_id, "active")
    return [{"id": e["id"], "name": e["full_name"]} for e in employees]
