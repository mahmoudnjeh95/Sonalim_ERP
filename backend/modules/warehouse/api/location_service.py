from __future__ import annotations

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.warehouse.domain.entities import Location


class LocationService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def create_location(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        code: str,
        name: str,
        is_blocked: bool = False,
        blocked_reason: str | None = None,
    ) -> Location:
        """Create a location, optionally a blocked one.

        Quarantine is the reason this flag exists: non-conforming product has to
        go somewhere it stays on the books but cannot be sold, and without a way
        to mark a location blocked there is nowhere for it to go.
        """
        location_id = str(ULID())
        self._connection.execute(
            """
            INSERT INTO warehouse.locations (id, tenant_id, code, name, is_blocked, blocked_reason)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (location_id, tenant_id, code, name, is_blocked, blocked_reason),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="location.created",
            entity_type="location",
            entity_id=location_id,
            payload={"code": code, "name": name, "is_blocked": is_blocked},
        )
        return Location(
            id=location_id, code=code, name=name, is_blocked=is_blocked, blocked_reason=blocked_reason
        )

    def list_locations(self, *, tenant_id: str) -> list[Location]:
        rows = self._connection.execute(
            """
            SELECT id, code, name, is_blocked, blocked_reason FROM warehouse.locations
            WHERE tenant_id = %s ORDER BY created_at
            """,
            (tenant_id,),
        ).fetchall()
        return [Location(id=r[0], code=r[1], name=r[2], is_blocked=r[3], blocked_reason=r[4]) for r in rows]

    def update_location(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        location_id: str,
        code: str | None = None,
        name: str | None = None,
        is_blocked: bool | None = None,
        blocked_reason: str | None = None,
    ) -> Result[Location]:
        row = self._connection.execute(
            """
            SELECT id, code, name, is_blocked, blocked_reason FROM warehouse.locations
            WHERE id = %s AND tenant_id = %s
            """,
            (location_id, tenant_id),
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"location {location_id} not found", f"emplacement {location_id} introuvable")

        updated_code = code if code is not None else row[1]
        updated_name = name if name is not None else row[2]
        if not updated_code.strip():
            return Err("INVALID_CODE", "code is required", "le code est obligatoire")
        if not updated_name.strip():
            return Err("INVALID_NAME", "name is required", "le nom est obligatoire")

        updated_blocked = is_blocked if is_blocked is not None else row[3]
        updated_reason = blocked_reason if blocked_reason is not None else row[4]
        self._connection.execute(
            """
            UPDATE warehouse.locations SET code = %s, name = %s, is_blocked = %s, blocked_reason = %s
            WHERE id = %s AND tenant_id = %s
            """,
            (updated_code, updated_name, updated_blocked, updated_reason, location_id, tenant_id),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="location.updated",
            entity_type="location",
            entity_id=location_id,
            payload={"code": updated_code, "name": updated_name},
        )
        return Ok(
            Location(
                id=location_id,
                code=updated_code,
                name=updated_name,
                is_blocked=updated_blocked,
                blocked_reason=updated_reason,
            )
        )
