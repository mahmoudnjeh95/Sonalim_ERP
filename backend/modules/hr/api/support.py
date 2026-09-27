"""Shared by the hr services: guarded writes, audit payloads and reference checks."""
from __future__ import annotations

import datetime
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, is_dataclass
from decimal import Decimal

import psycopg

from core.domain.result import Err


def execute_guarded(
    connection: psycopg.Connection, query: str, params: Sequence[object], refusals: Mapping[str, Err]
) -> Err | None:
    """Run one write inside a savepoint. A unique or exclusion constraint named in `refusals`
    becomes that refusal and leaves the transaction usable; any other failure is raised.

    The savepoint is plain SQL rather than connection.transaction(): on a connection with no
    transaction open yet, transaction() would begin one and commit it on exit, behind the
    router's back and past the test fixture's rollback."""
    connection.execute("SAVEPOINT hr_guarded_write")
    try:
        connection.execute(query, params)
    except (psycopg.errors.UniqueViolation, psycopg.errors.ExclusionViolation) as error:
        connection.execute("ROLLBACK TO SAVEPOINT hr_guarded_write")
        refusal = refusals.get(error.diag.constraint_name or "")
        if refusal is None:
            raise
        return refusal
    connection.execute("RELEASE SAVEPOINT hr_guarded_write")
    return None


def iso_dates(value):
    """Dates as ISO strings, recursively; everything else as it is (Decimals stay Decimals)."""
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {key: iso_dates(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [iso_dates(item) for item in value]
    return value


def json_safe(value):
    """What the audit log's JSON can hold: dataclasses as dicts, dates as ISO, Decimals as strings."""
    if is_dataclass(value) and not isinstance(value, type):
        value = asdict(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    return value


def change_payload(before: Mapping[str, object], after: Mapping[str, object], sensitive: Iterable[str] = ()) -> dict:
    """What an edit changed, for the audit trail: the new value of each ordinary field, only the
    name of each sensitive one (the audit log is readable without hr.view_sensitive)."""
    hidden = set(sensitive)
    changed = [key for key in after if before.get(key) != after.get(key)]
    return {
        "changed": {key: json_safe(after[key]) for key in changed if key not in hidden},
        "sensitive_changed": [key for key in changed if key in hidden],
    }


def missing_reference(
    connection: psycopg.Connection, table: str, tenant_id: str, row_id: str | None, label_en: str, label_fr: str
) -> Err | None:
    """NOT_FOUND when `row_id` names no row of `table` in this tenant; None when it does or is None.
    `table` is always a literal from the calling service, never user input."""
    if row_id is None:
        return None
    found = connection.execute(f"SELECT 1 FROM {table} WHERE id = %s AND tenant_id = %s", (row_id, tenant_id)).fetchone()
    return None if found else Err("NOT_FOUND", f"{label_en} not found", f"{label_fr} introuvable")
