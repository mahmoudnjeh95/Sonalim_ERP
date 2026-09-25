from __future__ import annotations

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.production.domain.work_center import (
    WorkCenter,
    block_work_center,
    unblock_work_center,
    validate_work_center_code,
)


class WorkCenterService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def create_work_center(
        self, *, tenant_id: str, actor_id: str, code: str, name: str, hourly_rate: float = 0
    ) -> Result[WorkCenter]:
        validation = validate_work_center_code(code)
        if isinstance(validation, Err):
            return validation

        work_center_id = str(ULID())
        self._connection.execute(
            """
            INSERT INTO production.work_centers (id, tenant_id, code, name, hourly_rate, is_blocked)
            VALUES (%s, %s, %s, %s, %s, FALSE)
            """,
            (work_center_id, tenant_id, code, name, hourly_rate),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="work_center.created",
            entity_type="work_center",
            entity_id=work_center_id,
            payload={"code": code, "name": name},
        )
        return Ok(
            WorkCenter(id=work_center_id, code=code, name=name, hourly_rate=hourly_rate, is_blocked=False, blocked_reason=None)
        )

    def update_work_center(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        work_center_id: str,
        code: str | None = None,
        name: str | None = None,
        hourly_rate: float | None = None,
    ) -> Result[WorkCenter]:
        row = self._connection.execute(
            """
            SELECT id, code, name, hourly_rate, is_blocked, blocked_reason
            FROM production.work_centers WHERE id = %s AND tenant_id = %s FOR UPDATE
            """,
            (work_center_id, tenant_id),
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"work center {work_center_id} not found", f"poste de charge {work_center_id} introuvable")

        current = WorkCenter(id=row[0], code=row[1], name=row[2], hourly_rate=float(row[3]), is_blocked=row[4], blocked_reason=row[5])
        updated_code = code if code is not None else current.code
        updated_name = name if name is not None else current.name
        updated_rate = hourly_rate if hourly_rate is not None else current.hourly_rate
        validation = validate_work_center_code(updated_code)
        if isinstance(validation, Err):
            return validation

        self._connection.execute(
            "UPDATE production.work_centers SET code = %s, name = %s, hourly_rate = %s WHERE id = %s",
            (updated_code, updated_name, updated_rate, work_center_id),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="work_center.updated",
            entity_type="work_center",
            entity_id=work_center_id,
            payload={"code": updated_code, "name": updated_name, "hourly_rate": updated_rate},
        )
        return Ok(WorkCenter(id=work_center_id, code=updated_code, name=updated_name, hourly_rate=updated_rate, is_blocked=current.is_blocked, blocked_reason=current.blocked_reason))

    def list_work_centers(self, *, tenant_id: str) -> list[WorkCenter]:
        rows = self._connection.execute(
            """
            SELECT id, code, name, hourly_rate, is_blocked, blocked_reason
            FROM production.work_centers WHERE tenant_id = %s ORDER BY created_at DESC
            """,
            (tenant_id,),
        ).fetchall()
        return [
            WorkCenter(id=r[0], code=r[1], name=r[2], hourly_rate=float(r[3]), is_blocked=r[4], blocked_reason=r[5])
            for r in rows
        ]

    def block_work_center(self, *, tenant_id: str, actor_id: str, work_center_id: str, reason: str) -> Result[WorkCenter]:
        row = self._connection.execute(
            """
            SELECT id, code, name, hourly_rate, is_blocked, blocked_reason
            FROM production.work_centers WHERE id = %s AND tenant_id = %s FOR UPDATE
            """,
            (work_center_id, tenant_id),
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"work center {work_center_id} not found", f"poste de charge {work_center_id} introuvable")

        work_center = WorkCenter(id=row[0], code=row[1], name=row[2], hourly_rate=float(row[3]), is_blocked=row[4], blocked_reason=row[5])
        result = block_work_center(work_center, reason)
        if isinstance(result, Err):
            return result

        self._connection.execute(
            "UPDATE production.work_centers SET is_blocked = TRUE, blocked_reason = %s WHERE id = %s",
            (reason, work_center_id),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="work_center.blocked",
            entity_type="work_center",
            entity_id=work_center_id,
            payload={"reason": reason},
        )
        return result

    def unblock_work_center(self, *, tenant_id: str, actor_id: str, work_center_id: str) -> Result[WorkCenter]:
        row = self._connection.execute(
            """
            SELECT id, code, name, hourly_rate, is_blocked, blocked_reason
            FROM production.work_centers WHERE id = %s AND tenant_id = %s FOR UPDATE
            """,
            (work_center_id, tenant_id),
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"work center {work_center_id} not found", f"poste de charge {work_center_id} introuvable")

        work_center = WorkCenter(id=row[0], code=row[1], name=row[2], hourly_rate=float(row[3]), is_blocked=row[4], blocked_reason=row[5])
        result = unblock_work_center(work_center)
        if isinstance(result, Err):
            return result

        self._connection.execute(
            "UPDATE production.work_centers SET is_blocked = FALSE, blocked_reason = NULL WHERE id = %s",
            (work_center_id,),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="work_center.unblocked",
            entity_type="work_center",
            entity_id=work_center_id,
            payload={},
        )
        return result
