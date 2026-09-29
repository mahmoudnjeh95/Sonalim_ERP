"""The people an employee supports: add, list, correct."""
from __future__ import annotations

import datetime
from collections.abc import Mapping
from dataclasses import asdict, replace

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.hr.api.support import change_payload, iso_dates, json_safe, missing_reference
from modules.hr.domain.dependant import Dependant, is_tax_dependant_on, validate_dependant

# Dependant's field order, which is also the column order used below.
_COLUMNS = ("kind", "name", "valid_from", "birth_date", "dependent_for_tax", "valid_to")
_SELECT = f"SELECT id, employee_id, {', '.join(_COLUMNS)} FROM hr.dependants"
_INSERT = f"INSERT INTO hr.dependants (id, tenant_id, employee_id, {', '.join(_COLUMNS)}) VALUES ({', '.join(['%s'] * (len(_COLUMNS) + 3))})"
_UPDATE = "UPDATE hr.dependants SET " + ", ".join(f"{name} = %s" for name in _COLUMNS) + " WHERE id = %s AND tenant_id = %s"


def _record(row, today: datetime.date) -> dict:
    dependant = Dependant(*row[2:])
    return {
        "id": row[0],
        "employee_id": row[1],
        **iso_dates(asdict(dependant)),
        "counts_for_tax_today": is_tax_dependant_on(dependant, today),
    }


class DependantService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    def list_dependants(self, *, tenant_id: str, employee_id: str, today: datetime.date | None = None) -> list[dict]:
        day = today or datetime.date.today()
        rows = self.connection.execute(
            f"{_SELECT} WHERE tenant_id = %s AND employee_id = %s ORDER BY kind DESC, birth_date NULLS FIRST, name",
            (tenant_id, employee_id),
        ).fetchall()
        return [_record(row, day) for row in rows]

    def get_dependant(self, *, tenant_id: str, dependant_id: str) -> dict | None:
        row = self.connection.execute(f"{_SELECT} WHERE tenant_id = %s AND id = %s", (tenant_id, dependant_id)).fetchone()
        return None if row is None else _record(row, datetime.date.today())

    def create_dependant(self, *, tenant_id: str, actor_id: str, employee_id: str, dependant: Dependant) -> Result[dict]:
        refused = missing_reference(self.connection, "hr.employees", tenant_id, employee_id, "employee", "employé")
        if refused:
            return refused
        validated = validate_dependant(dependant)
        if isinstance(validated, Err):
            return validated
        clean = validated.value
        dependant_id = str(ULID())
        self.connection.execute(_INSERT, (dependant_id, tenant_id, employee_id, *(getattr(clean, name) for name in _COLUMNS)))
        record_audit(
            self.connection, tenant_id=tenant_id, actor_id=actor_id, action="dependant.created",
            entity_type="dependant", entity_id=dependant_id, payload={"employee_id": employee_id, **json_safe(clean)},
        )
        return Ok(self.get_dependant(tenant_id=tenant_id, dependant_id=dependant_id))

    def update_dependant(self, *, tenant_id: str, actor_id: str, dependant_id: str, changes: Mapping[str, object]) -> Result[dict]:
        row = self.connection.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM hr.dependants WHERE id = %s AND tenant_id = %s FOR UPDATE", (dependant_id, tenant_id)
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", "dependant not found", "personne à charge introuvable")
        current = Dependant(*row)
        validated = validate_dependant(replace(current, **changes))
        if isinstance(validated, Err):
            return validated
        clean = validated.value
        self.connection.execute(_UPDATE, (*(getattr(clean, name) for name in _COLUMNS), dependant_id, tenant_id))
        record_audit(
            self.connection, tenant_id=tenant_id, actor_id=actor_id, action="dependant.updated",
            entity_type="dependant", entity_id=dependant_id, payload=change_payload(asdict(current), asdict(clean)),
        )
        return Ok(self.get_dependant(tenant_id=tenant_id, dependant_id=dependant_id))
