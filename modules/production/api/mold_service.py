from __future__ import annotations

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.production.domain.mold import Mold, validate_mold


class MoldService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def create_mold(self, *, tenant_id: str, actor_id: str, code: str, name: str, type: str) -> Result[Mold]:
        validation = validate_mold(code=code, type=type)
        if isinstance(validation, Err):
            return validation

        mold_id = str(ULID())
        self._connection.execute(
            "INSERT INTO production.molds (id, tenant_id, code, name, type) VALUES (%s, %s, %s, %s, %s)",
            (mold_id, tenant_id, code, name, type),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="mold.created",
            entity_type="mold",
            entity_id=mold_id,
            payload={"code": code, "name": name, "type": type},
        )
        return Ok(Mold(id=mold_id, code=code, name=name, type=type))

    def update_mold(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        mold_id: str,
        code: str | None = None,
        name: str | None = None,
        type: str | None = None,
    ) -> Result[Mold]:
        row = self._connection.execute(
            "SELECT id, code, name, type FROM production.molds WHERE id = %s AND tenant_id = %s FOR UPDATE",
            (mold_id, tenant_id),
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"mold {mold_id} not found")

        current = Mold(id=row[0], code=row[1], name=row[2], type=row[3])
        updated_code = code if code is not None else current.code
        updated_name = name if name is not None else current.name
        updated_type = type if type is not None else current.type
        validation = validate_mold(code=updated_code, type=updated_type)
        if isinstance(validation, Err):
            return validation

        self._connection.execute(
            "UPDATE production.molds SET code = %s, name = %s, type = %s WHERE id = %s",
            (updated_code, updated_name, updated_type, mold_id),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="mold.updated",
            entity_type="mold",
            entity_id=mold_id,
            payload={"code": updated_code, "name": updated_name, "type": updated_type},
        )
        return Ok(Mold(id=mold_id, code=updated_code, name=updated_name, type=updated_type))

    def list_molds(self, *, tenant_id: str) -> list[Mold]:
        rows = self._connection.execute(
            "SELECT id, code, name, type FROM production.molds WHERE tenant_id = %s ORDER BY created_at DESC",
            (tenant_id,),
        ).fetchall()
        return [Mold(id=r[0], code=r[1], name=r[2], type=r[3]) for r in rows]
