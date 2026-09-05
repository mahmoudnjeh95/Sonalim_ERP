from __future__ import annotations

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.production.domain.resource_type import ResourceType, validate_resource_type


class ResourceTypeService:
    """The metered-resource lookup (water, fuel, electricity, ...).

    It outlived the per-date and per-OF consumption ledgers it used to key: those
    figures now live on the production reports themselves. Whether the Phase 8
    dashboard still wants this table is an open question, so it is kept rather
    than dropped — an empty lookup is reversible, a dropped one is not.
    """

    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def create_resource_type(
        self, *, tenant_id: str, actor_id: str, code: str, name: str, unit: str
    ) -> Result[ResourceType]:
        validation = validate_resource_type(code=code, name=name, unit=unit)
        if isinstance(validation, Err):
            return validation

        existing = self._connection.execute(
            "SELECT 1 FROM production.resource_types WHERE tenant_id = %s AND code = %s", (tenant_id, code)
        ).fetchone()
        if existing is not None:
            return Err("DUPLICATE_CODE", f"a resource type with code {code!r} already exists")

        resource_type_id = str(ULID())
        self._connection.execute(
            "INSERT INTO production.resource_types (id, tenant_id, code, name, unit) VALUES (%s, %s, %s, %s, %s)",
            (resource_type_id, tenant_id, code, name, unit),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="resource_type.created",
            entity_type="resource_type",
            entity_id=resource_type_id,
            payload={"code": code, "name": name, "unit": unit},
        )
        return Ok(ResourceType(id=resource_type_id, code=code, name=name, unit=unit))

    def update_resource_type(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        resource_type_id: str,
        code: str | None = None,
        name: str | None = None,
        unit: str | None = None,
    ) -> Result[ResourceType]:
        row = self._connection.execute(
            "SELECT id, code, name, unit FROM production.resource_types WHERE id = %s AND tenant_id = %s FOR UPDATE",
            (resource_type_id, tenant_id),
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"resource type {resource_type_id} not found")

        current = ResourceType(id=row[0], code=row[1], name=row[2], unit=row[3])
        updated_code = code if code is not None else current.code
        updated_name = name if name is not None else current.name
        updated_unit = unit if unit is not None else current.unit
        validation = validate_resource_type(code=updated_code, name=updated_name, unit=updated_unit)
        if isinstance(validation, Err):
            return validation

        if updated_code != current.code:
            existing = self._connection.execute(
                "SELECT 1 FROM production.resource_types WHERE tenant_id = %s AND code = %s AND id != %s",
                (tenant_id, updated_code, resource_type_id),
            ).fetchone()
            if existing is not None:
                return Err("DUPLICATE_CODE", f"a resource type with code {updated_code!r} already exists")

        self._connection.execute(
            "UPDATE production.resource_types SET code = %s, name = %s, unit = %s WHERE id = %s",
            (updated_code, updated_name, updated_unit, resource_type_id),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="resource_type.updated",
            entity_type="resource_type",
            entity_id=resource_type_id,
            payload={"code": updated_code, "name": updated_name, "unit": updated_unit},
        )
        return Ok(ResourceType(id=resource_type_id, code=updated_code, name=updated_name, unit=updated_unit))

    def list_resource_types(self, tenant_id: str) -> list[ResourceType]:
        rows = self._connection.execute(
            "SELECT id, code, name, unit FROM production.resource_types WHERE tenant_id = %s ORDER BY name",
            (tenant_id,),
        ).fetchall()
        return [ResourceType(id=r[0], code=r[1], name=r[2], unit=r[3]) for r in rows]
