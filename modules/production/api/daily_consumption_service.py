from __future__ import annotations

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.production.domain.daily_consumption import (
    DailyConsumption,
    ResourceType,
    validate_consumption,
    validate_resource_type,
)


class ResourceTypeService:
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


class DailyConsumptionService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def record_consumption(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        consumption_date: str,
        resource_type_id: str,
        quantity: float,
        note: str | None = None,
    ) -> Result[DailyConsumption]:
        validation = validate_consumption(quantity=quantity)
        if isinstance(validation, Err):
            return validation

        resource_type = self._connection.execute(
            "SELECT 1 FROM production.resource_types WHERE id = %s AND tenant_id = %s", (resource_type_id, tenant_id)
        ).fetchone()
        if resource_type is None:
            return Err("NOT_FOUND", f"resource type {resource_type_id} not found")

        entry_id = str(ULID())
        self._connection.execute(
            """
            INSERT INTO production.daily_consumption (id, tenant_id, consumption_date, resource_type_id, quantity, note, actor_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id, consumption_date, resource_type_id)
            DO UPDATE SET quantity = EXCLUDED.quantity, note = EXCLUDED.note, actor_id = EXCLUDED.actor_id, updated_at = NOW()
            """,
            (entry_id, tenant_id, consumption_date, resource_type_id, quantity, note, actor_id),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="daily_consumption.recorded",
            entity_type="daily_consumption",
            entity_id=f"{consumption_date}:{resource_type_id}",
            payload={"consumption_date": consumption_date, "resource_type_id": resource_type_id, "quantity": quantity},
        )
        return Ok(DailyConsumption(id=entry_id, consumption_date=consumption_date, resource_type_id=resource_type_id, quantity=quantity, note=note))

    def list_consumption(
        self, *, tenant_id: str, date_from: str | None = None, date_to: str | None = None
    ) -> list[DailyConsumption]:
        clauses = ["tenant_id = %s"]
        params: list[object] = [tenant_id]
        if date_from is not None:
            clauses.append("consumption_date >= %s")
            params.append(date_from)
        if date_to is not None:
            clauses.append("consumption_date <= %s")
            params.append(date_to)

        rows = self._connection.execute(
            f"""
            SELECT id, consumption_date, resource_type_id, quantity, note
            FROM production.daily_consumption
            WHERE {' AND '.join(clauses)}
            ORDER BY consumption_date DESC
            """,
            params,
        ).fetchall()
        return [
            DailyConsumption(id=r[0], consumption_date=r[1].isoformat(), resource_type_id=r[2], quantity=float(r[3]), note=r[4])
            for r in rows
        ]
