from __future__ import annotations

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.production.domain.daily_consumption import WorkOrderConsumption, validate_consumption


class WorkOrderConsumptionService:
    """Utility consumption (fuel, scotch, film, ...) tied to a specific work order —
    recording only. Cost-per-ton/cost-per-packet aggregation is a later phase."""

    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def record_consumption(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        work_order_id: str,
        resource_type_id: str,
        quantity: float,
        note: str | None = None,
    ) -> Result[WorkOrderConsumption]:
        validation = validate_consumption(quantity=quantity)
        if isinstance(validation, Err):
            return validation

        work_order = self._connection.execute(
            "SELECT 1 FROM production.work_orders WHERE id = %s AND tenant_id = %s", (work_order_id, tenant_id)
        ).fetchone()
        if work_order is None:
            return Err("NOT_FOUND", f"work order {work_order_id} not found")

        resource_type = self._connection.execute(
            "SELECT 1 FROM production.resource_types WHERE id = %s AND tenant_id = %s", (resource_type_id, tenant_id)
        ).fetchone()
        if resource_type is None:
            return Err("NOT_FOUND", f"resource type {resource_type_id} not found")

        entry_id = str(ULID())
        self._connection.execute(
            """
            INSERT INTO production.work_order_consumption (id, tenant_id, work_order_id, resource_type_id, quantity, note, actor_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (entry_id, tenant_id, work_order_id, resource_type_id, quantity, note, actor_id),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="work_order_consumption.recorded",
            entity_type="work_order_consumption",
            entity_id=entry_id,
            payload={"work_order_id": work_order_id, "resource_type_id": resource_type_id, "quantity": quantity},
        )
        return Ok(WorkOrderConsumption(id=entry_id, work_order_id=work_order_id, resource_type_id=resource_type_id, quantity=quantity, note=note))

    def list_consumption(self, *, tenant_id: str, work_order_id: str | None = None) -> list[WorkOrderConsumption]:
        clauses = ["tenant_id = %s"]
        params: list[object] = [tenant_id]
        if work_order_id is not None:
            clauses.append("work_order_id = %s")
            params.append(work_order_id)
        rows = self._connection.execute(
            f"SELECT id, work_order_id, resource_type_id, quantity, note FROM production.work_order_consumption WHERE {' AND '.join(clauses)} ORDER BY created_at DESC",
            params,
        ).fetchall()
        return [
            WorkOrderConsumption(id=r[0], work_order_id=r[1], resource_type_id=r[2], quantity=float(r[3]), note=r[4]) for r in rows
        ]
