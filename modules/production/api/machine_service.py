from __future__ import annotations

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.production.domain.machine import Machine, transition_machine, validate_machine_code


class MachineService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def create_machine(self, *, tenant_id: str, actor_id: str, work_center_id: str, code: str, name: str) -> Result[Machine]:
        validation = validate_machine_code(code)
        if isinstance(validation, Err):
            return validation

        machine_id = str(ULID())
        self._connection.execute(
            """
            INSERT INTO production.machines (id, tenant_id, work_center_id, code, name, status)
            VALUES (%s, %s, %s, %s, %s, 'operational')
            """,
            (machine_id, tenant_id, work_center_id, code, name),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="machine.created",
            entity_type="machine",
            entity_id=machine_id,
            payload={"work_center_id": work_center_id, "code": code, "name": name},
        )
        return Ok(Machine(id=machine_id, work_center_id=work_center_id, code=code, name=name, status="operational"))

    def update_machine(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        machine_id: str,
        work_center_id: str | None = None,
        code: str | None = None,
        name: str | None = None,
    ) -> Result[Machine]:
        row = self._connection.execute(
            "SELECT id, work_center_id, code, name, status FROM production.machines WHERE id = %s AND tenant_id = %s FOR UPDATE",
            (machine_id, tenant_id),
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"machine {machine_id} not found")

        current = Machine(id=row[0], work_center_id=row[1], code=row[2], name=row[3], status=row[4])
        updated_work_center_id = work_center_id if work_center_id is not None else current.work_center_id
        updated_code = code if code is not None else current.code
        updated_name = name if name is not None else current.name
        validation = validate_machine_code(updated_code)
        if isinstance(validation, Err):
            return validation

        self._connection.execute(
            "UPDATE production.machines SET work_center_id = %s, code = %s, name = %s WHERE id = %s",
            (updated_work_center_id, updated_code, updated_name, machine_id),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="machine.updated",
            entity_type="machine",
            entity_id=machine_id,
            payload={"work_center_id": updated_work_center_id, "code": updated_code, "name": updated_name},
        )
        return Ok(Machine(id=machine_id, work_center_id=updated_work_center_id, code=updated_code, name=updated_name, status=current.status))

    def list_machines(self, *, tenant_id: str, work_center_id: str | None = None) -> list[Machine]:
        if work_center_id is not None:
            rows = self._connection.execute(
                """
                SELECT id, work_center_id, code, name, status FROM production.machines
                WHERE tenant_id = %s AND work_center_id = %s ORDER BY created_at DESC
                """,
                (tenant_id, work_center_id),
            ).fetchall()
        else:
            rows = self._connection.execute(
                """
                SELECT id, work_center_id, code, name, status FROM production.machines
                WHERE tenant_id = %s ORDER BY created_at DESC
                """,
                (tenant_id,),
            ).fetchall()
        return [Machine(id=r[0], work_center_id=r[1], code=r[2], name=r[3], status=r[4]) for r in rows]

    def transition_status(self, *, tenant_id: str, actor_id: str, machine_id: str, new_status: str) -> Result[Machine]:
        row = self._connection.execute(
            """
            SELECT id, work_center_id, code, name, status FROM production.machines
            WHERE id = %s AND tenant_id = %s FOR UPDATE
            """,
            (machine_id, tenant_id),
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"machine {machine_id} not found")

        machine = Machine(id=row[0], work_center_id=row[1], code=row[2], name=row[3], status=row[4])
        result = transition_machine(machine, new_status)
        if isinstance(result, Err):
            return result

        self._connection.execute("UPDATE production.machines SET status = %s WHERE id = %s", (new_status, machine_id))
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="machine.status_changed",
            entity_type="machine",
            entity_id=machine_id,
            payload={"from_status": machine.status, "to_status": new_status},
        )
        return result
