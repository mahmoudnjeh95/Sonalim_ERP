from __future__ import annotations

from dataclasses import replace

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.maintenance.domain.equipment import (
    PRODUCTION_STAGES,
    Equipment,
    transition_equipment,
    validate_equipment_code,
    validate_production_stage,
)

__all__ = ["PRODUCTION_STAGES", "UNSET", "EquipmentService"]

_COLUMNS = "id, work_center_id, code, name, status, production_stage, archived_at"


class _Unset:
    """Marks a field the caller did not mention, so that None can mean "clear it"."""

    def __repr__(self) -> str:
        return "UNSET"


UNSET = _Unset()


def _equipment(row) -> Equipment:
    return Equipment(
        id=row[0], work_center_id=row[1], code=row[2], name=row[3], status=row[4], production_stage=row[5], archived_at=row[6]
    )


class EquipmentService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def create_equipment(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        work_center_id: str,
        code: str,
        name: str,
        production_stage: str | None = None,
    ) -> Result[Equipment]:
        for validation in (validate_equipment_code(code), validate_production_stage(production_stage)):
            if isinstance(validation, Err):
                return validation

        equipment_id = str(ULID())
        self._connection.execute(
            """
            INSERT INTO maintenance.equipment (id, tenant_id, work_center_id, code, name, status, production_stage)
            VALUES (%s, %s, %s, %s, %s, 'operational', %s)
            """,
            (equipment_id, tenant_id, work_center_id, code, name, production_stage),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="equipment.created",
            entity_type="equipment",
            entity_id=equipment_id,
            payload={"work_center_id": work_center_id, "code": code, "name": name, "production_stage": production_stage},
        )
        return Ok(
            Equipment(
                id=equipment_id,
                work_center_id=work_center_id,
                code=code,
                name=name,
                status="operational",
                production_stage=production_stage,
            )
        )

    def update_equipment(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        equipment_id: str,
        work_center_id: str | None = None,
        code: str | None = None,
        name: str | None = None,
        production_stage: str | None | _Unset = UNSET,
    ) -> Result[Equipment]:
        """None leaves a field as it is, except the stage: it can be cleared, so
        there None clears it and UNSET (the default) leaves it as it is."""
        row = self._connection.execute(
            f"SELECT {_COLUMNS} FROM maintenance.equipment WHERE id = %s AND tenant_id = %s FOR UPDATE",
            (equipment_id, tenant_id),
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"equipment {equipment_id} not found")

        current = _equipment(row)
        updated_work_center_id = work_center_id if work_center_id is not None else current.work_center_id
        updated_code = code if code is not None else current.code
        updated_name = name if name is not None else current.name
        updated_stage = current.production_stage if isinstance(production_stage, _Unset) else production_stage
        for validation in (validate_equipment_code(updated_code), validate_production_stage(updated_stage)):
            if isinstance(validation, Err):
                return validation

        self._connection.execute(
            "UPDATE maintenance.equipment SET work_center_id = %s, code = %s, name = %s, production_stage = %s WHERE id = %s",
            (updated_work_center_id, updated_code, updated_name, updated_stage, equipment_id),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="equipment.updated",
            entity_type="equipment",
            entity_id=equipment_id,
            payload={
                "work_center_id": updated_work_center_id,
                "code": updated_code,
                "name": updated_name,
                "production_stage": updated_stage,
            },
        )
        return Ok(
            Equipment(
                id=equipment_id,
                work_center_id=updated_work_center_id,
                code=updated_code,
                name=updated_name,
                status=current.status,
                production_stage=updated_stage,
            )
        )

    def list_equipment(
        self, *, tenant_id: str, work_center_id: str | None = None, include_archived: bool = False
    ) -> list[Equipment]:
        archived_clause = "" if include_archived else "AND archived_at IS NULL"
        if work_center_id is not None:
            rows = self._connection.execute(
                f"""
                SELECT {_COLUMNS} FROM maintenance.equipment
                WHERE tenant_id = %s AND work_center_id = %s {archived_clause} ORDER BY created_at DESC
                """,
                (tenant_id, work_center_id),
            ).fetchall()
        else:
            rows = self._connection.execute(
                f"""
                SELECT {_COLUMNS} FROM maintenance.equipment
                WHERE tenant_id = %s {archived_clause} ORDER BY created_at DESC
                """,
                (tenant_id,),
            ).fetchall()
        return [_equipment(r) for r in rows]

    def transition_status(self, *, tenant_id: str, actor_id: str, equipment_id: str, new_status: str) -> Result[Equipment]:
        row = self._connection.execute(
            f"""
            SELECT {_COLUMNS} FROM maintenance.equipment
            WHERE id = %s AND tenant_id = %s FOR UPDATE
            """,
            (equipment_id, tenant_id),
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"equipment {equipment_id} not found")

        equipment = _equipment(row)
        result = transition_equipment(equipment, new_status)
        if isinstance(result, Err):
            return result

        self._connection.execute("UPDATE maintenance.equipment SET status = %s WHERE id = %s", (new_status, equipment_id))
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="equipment.status_changed",
            entity_type="equipment",
            entity_id=equipment_id,
            payload={"from_status": equipment.status, "to_status": new_status},
        )
        return result

    def archive_equipment(self, *, tenant_id: str, actor_id: str, equipment_id: str) -> Result[Equipment]:
        return self._set_archived(
            tenant_id=tenant_id, actor_id=actor_id, equipment_id=equipment_id, archive=True, action="equipment.archived"
        )

    def unarchive_equipment(self, *, tenant_id: str, actor_id: str, equipment_id: str) -> Result[Equipment]:
        return self._set_archived(
            tenant_id=tenant_id, actor_id=actor_id, equipment_id=equipment_id, archive=False, action="equipment.unarchived"
        )

    def _set_archived(
        self, *, tenant_id: str, actor_id: str, equipment_id: str, archive: bool, action: str
    ) -> Result[Equipment]:
        row = self._connection.execute(
            f"SELECT {_COLUMNS} FROM maintenance.equipment WHERE id = %s AND tenant_id = %s FOR UPDATE",
            (equipment_id, tenant_id),
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"equipment {equipment_id} not found")

        current = _equipment(row)
        if archive and current.archived_at is not None:
            return Err("ALREADY_ARCHIVED", f"equipment {equipment_id} is already archived")
        if not archive and current.archived_at is None:
            return Err("NOT_ARCHIVED", f"equipment {equipment_id} is not archived")

        if archive:
            archived_at = self._connection.execute(
                "UPDATE maintenance.equipment SET archived_at = NOW() WHERE id = %s RETURNING archived_at",
                (equipment_id,),
            ).fetchone()[0]
        else:
            self._connection.execute("UPDATE maintenance.equipment SET archived_at = NULL WHERE id = %s", (equipment_id,))
            archived_at = None
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action=action,
            entity_type="equipment",
            entity_id=equipment_id,
            payload={"archived_at": archived_at.isoformat() if archived_at is not None else None},
        )
        return Ok(replace(current, archived_at=archived_at))
