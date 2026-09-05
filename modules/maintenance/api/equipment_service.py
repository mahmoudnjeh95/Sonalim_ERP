from __future__ import annotations

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.maintenance.domain.equipment import Equipment, transition_equipment, validate_equipment_code


class EquipmentService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def create_equipment(self, *, tenant_id: str, actor_id: str, work_center_id: str, code: str, name: str) -> Result[Equipment]:
        validation = validate_equipment_code(code)
        if isinstance(validation, Err):
            return validation

        equipment_id = str(ULID())
        self._connection.execute(
            """
            INSERT INTO maintenance.equipment (id, tenant_id, work_center_id, code, name, status)
            VALUES (%s, %s, %s, %s, %s, 'operational')
            """,
            (equipment_id, tenant_id, work_center_id, code, name),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="equipment.created",
            entity_type="equipment",
            entity_id=equipment_id,
            payload={"work_center_id": work_center_id, "code": code, "name": name},
        )
        return Ok(Equipment(id=equipment_id, work_center_id=work_center_id, code=code, name=name, status="operational"))

    def update_equipment(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        equipment_id: str,
        work_center_id: str | None = None,
        code: str | None = None,
        name: str | None = None,
    ) -> Result[Equipment]:
        row = self._connection.execute(
            "SELECT id, work_center_id, code, name, status FROM maintenance.equipment WHERE id = %s AND tenant_id = %s FOR UPDATE",
            (equipment_id, tenant_id),
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"equipment {equipment_id} not found")

        current = Equipment(id=row[0], work_center_id=row[1], code=row[2], name=row[3], status=row[4])
        updated_work_center_id = work_center_id if work_center_id is not None else current.work_center_id
        updated_code = code if code is not None else current.code
        updated_name = name if name is not None else current.name
        validation = validate_equipment_code(updated_code)
        if isinstance(validation, Err):
            return validation

        self._connection.execute(
            "UPDATE maintenance.equipment SET work_center_id = %s, code = %s, name = %s WHERE id = %s",
            (updated_work_center_id, updated_code, updated_name, equipment_id),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="equipment.updated",
            entity_type="equipment",
            entity_id=equipment_id,
            payload={"work_center_id": updated_work_center_id, "code": updated_code, "name": updated_name},
        )
        return Ok(
            Equipment(id=equipment_id, work_center_id=updated_work_center_id, code=updated_code, name=updated_name, status=current.status)
        )

    def list_equipment(self, *, tenant_id: str, work_center_id: str | None = None) -> list[Equipment]:
        if work_center_id is not None:
            rows = self._connection.execute(
                """
                SELECT id, work_center_id, code, name, status FROM maintenance.equipment
                WHERE tenant_id = %s AND work_center_id = %s ORDER BY created_at DESC
                """,
                (tenant_id, work_center_id),
            ).fetchall()
        else:
            rows = self._connection.execute(
                """
                SELECT id, work_center_id, code, name, status FROM maintenance.equipment
                WHERE tenant_id = %s ORDER BY created_at DESC
                """,
                (tenant_id,),
            ).fetchall()
        return [Equipment(id=r[0], work_center_id=r[1], code=r[2], name=r[3], status=r[4]) for r in rows]

    def transition_status(self, *, tenant_id: str, actor_id: str, equipment_id: str, new_status: str) -> Result[Equipment]:
        row = self._connection.execute(
            """
            SELECT id, work_center_id, code, name, status FROM maintenance.equipment
            WHERE id = %s AND tenant_id = %s FOR UPDATE
            """,
            (equipment_id, tenant_id),
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"equipment {equipment_id} not found")

        equipment = Equipment(id=row[0], work_center_id=row[1], code=row[2], name=row[3], status=row[4])
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
