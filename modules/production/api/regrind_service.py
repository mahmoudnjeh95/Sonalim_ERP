from __future__ import annotations

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.production.api.product_classification_service import ProductClassificationService
from modules.production.api.service import WorkOrderService
from modules.production.domain.entities import WorkOrder
from modules.production.domain.regrind import ScrapRecord, validate_scrap


class ScrapService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def record_scrap(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        scrap_type: str,
        product_id: str,
        quantity: float,
        work_order_id: str | None = None,
        work_center_id: str | None = None,
        source_note: str | None = None,
        operation_step_id: str | None = None,
    ) -> Result[ScrapRecord]:
        validation = validate_scrap(
            scrap_type=scrap_type, quantity=quantity, work_order_id=work_order_id, source_note=source_note
        )
        if isinstance(validation, Err):
            return validation

        scrap_id = str(ULID())
        self._connection.execute(
            """
            INSERT INTO production.scrap_records
                (id, tenant_id, work_order_id, operation_step_id, scrap_type, product_id, quantity, is_reground, work_center_id, source_note)
            VALUES (%s, %s, %s, %s, %s, %s, %s, FALSE, %s, %s)
            """,
            (scrap_id, tenant_id, work_order_id, operation_step_id, scrap_type, product_id, quantity, work_center_id, source_note),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="scrap_record.created",
            entity_type="scrap_record",
            entity_id=scrap_id,
            payload={"work_order_id": work_order_id, "work_center_id": work_center_id, "scrap_type": scrap_type, "quantity": quantity},
        )
        return Ok(
            ScrapRecord(
                id=scrap_id,
                work_order_id=work_order_id,
                operation_step_id=operation_step_id,
                scrap_type=scrap_type,
                product_id=product_id,
                quantity=quantity,
                is_reground=False,
                work_center_id=work_center_id,
                source_note=source_note,
            )
        )

    def list_scrap(
        self, *, tenant_id: str, work_order_id: str | None = None, is_reground: bool | None = None
    ) -> list[ScrapRecord]:
        clauses = ["tenant_id = %s"]
        params: list[object] = [tenant_id]
        if work_order_id is not None:
            clauses.append("work_order_id = %s")
            params.append(work_order_id)
        if is_reground is not None:
            clauses.append("is_reground = %s")
            params.append(is_reground)

        rows = self._connection.execute(
            f"""
            SELECT id, work_order_id, operation_step_id, scrap_type, product_id, quantity, is_reground, work_center_id, source_note
            FROM production.scrap_records WHERE {' AND '.join(clauses)} ORDER BY created_at DESC
            """,
            params,
        ).fetchall()
        return [
            ScrapRecord(
                id=r[0],
                work_order_id=r[1],
                operation_step_id=r[2],
                scrap_type=r[3],
                product_id=r[4],
                quantity=float(r[5]),
                is_reground=r[6],
                work_center_id=r[7],
                source_note=r[8],
            )
            for r in rows
        ]


class RegrindService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def create_regrind_batch(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        scrap_record_ids: list[str],
        output_product_id: str,
        output_quantity: float,
        work_center_id: str | None = None,
    ) -> Result[dict]:
        if not scrap_record_ids:
            return Err("NO_SCRAP_INPUTS", "a regrind batch needs at least one scrap input")

        # Lock every input scrap row up front so a concurrent regrind batch can't
        # consume the same scrap twice.
        rows = self._connection.execute(
            """
            SELECT id, is_reground, quantity FROM production.scrap_records
            WHERE tenant_id = %s AND id = ANY(%s)
            FOR UPDATE
            """,
            (tenant_id, scrap_record_ids),
        ).fetchall()
        found_by_id = {r[0]: (r[1], float(r[2])) for r in rows}
        for scrap_id in scrap_record_ids:
            if scrap_id not in found_by_id:
                return Err("NOT_FOUND", f"scrap record {scrap_id} not found")
            if found_by_id[scrap_id][0]:
                return Err("ALREADY_REGROUND", f"scrap record {scrap_id} was already reground")
        input_quantity_total = sum(found_by_id[scrap_id][1] for scrap_id in scrap_record_ids)

        # A regrind run is just a distinct, simple work order — reuse WorkOrderService
        # directly rather than duplicating order-creation logic. It never pours
        # inputs, so create_work_order cannot actually fail here.
        work_order_result = WorkOrderService(self._connection).create_work_order(
            tenant_id=tenant_id,
            actor_id=actor_id,
            product_id=output_product_id,
            quantity=output_quantity,
            work_center_id=work_center_id,
        )
        assert isinstance(work_order_result, Ok)
        work_order = work_order_result.value

        self._connection.execute(
            "INSERT INTO production.regrind_batches (work_order_id, tenant_id, input_quantity_total) VALUES (%s, %s, %s)",
            (work_order.id, tenant_id, input_quantity_total),
        )
        for scrap_id in scrap_record_ids:
            self._connection.execute(
                """
                INSERT INTO production.regrind_batch_inputs (id, regrind_batch_work_order_id, scrap_record_id)
                VALUES (%s, %s, %s)
                """,
                (str(ULID()), work_order.id, scrap_id),
            )
        self._connection.execute(
            "UPDATE production.scrap_records SET is_reground = TRUE WHERE id = ANY(%s)",
            (scrap_record_ids,),
        )

        # The output of a regrind run is always ground raw material fed back into
        # production — classify it automatically so it shows up correctly
        # everywhere (Product Classifications, regrind-aware reporting) without
        # relying on someone remembering a separate manual step.
        ProductClassificationService(self._connection).set_classification(
            tenant_id=tenant_id,
            actor_id=actor_id,
            product_id=output_product_id,
            category="raw_material",
            is_regrind=True,
        )

        loss_quantity = input_quantity_total - output_quantity
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="regrind_batch.created",
            entity_type="work_order",
            entity_id=work_order.id,
            payload={
                "scrap_record_ids": scrap_record_ids,
                "output_product_id": output_product_id,
                "input_quantity_total": input_quantity_total,
                "output_quantity": output_quantity,
                "loss_quantity": loss_quantity,
            },
        )

        return Ok(
            {
                "work_order": work_order,
                "scrap_record_ids": scrap_record_ids,
                "input_quantity_total": input_quantity_total,
                "loss_quantity": loss_quantity,
            }
        )

    def get_regrind_batch(self, *, tenant_id: str, work_order_id: str) -> dict | None:
        batch_row = self._connection.execute(
            "SELECT work_order_id, input_quantity_total FROM production.regrind_batches WHERE work_order_id = %s AND tenant_id = %s",
            (work_order_id, tenant_id),
        ).fetchone()
        if batch_row is None:
            return None
        input_quantity_total = float(batch_row[1])

        order_row = self._connection.execute(
            """
            SELECT id, reference, product_id, quantity, status, work_center_id, recipe_id, packaging_bom_id
            FROM production.work_orders WHERE id = %s AND tenant_id = %s
            """,
            (work_order_id, tenant_id),
        ).fetchone()
        work_order = WorkOrder(
            id=order_row[0],
            reference=order_row[1],
            product_id=order_row[2],
            quantity=float(order_row[3]),
            status=order_row[4],
            work_center_id=order_row[5],
            recipe_id=order_row[6],
            packaging_bom_id=order_row[7],
        )

        input_rows = self._connection.execute(
            """
            SELECT scrap_record_id FROM production.regrind_batch_inputs
            WHERE regrind_batch_work_order_id = %s
            """,
            (work_order_id,),
        ).fetchall()
        return {
            "work_order": work_order,
            "scrap_record_ids": [r[0] for r in input_rows],
            "input_quantity_total": input_quantity_total,
            "loss_quantity": input_quantity_total - work_order.quantity,
        }

    def list_regrind_batches(self, *, tenant_id: str) -> list[dict]:
        rows = self._connection.execute(
            """
            SELECT wo.id, wo.product_id, wo.quantity, wo.status, wo.work_center_id, rb.input_quantity_total, wo.created_at
            FROM production.regrind_batches rb
            JOIN production.work_orders wo ON wo.id = rb.work_order_id
            WHERE rb.tenant_id = %s
            ORDER BY wo.created_at DESC
            """,
            (tenant_id,),
        ).fetchall()
        return [
            {
                "work_order_id": r[0],
                "output_product_id": r[1],
                "output_quantity": float(r[2]),
                "status": r[3],
                "work_center_id": r[4],
                "input_quantity_total": float(r[5]),
                "loss_quantity": float(r[5]) - float(r[2]),
                "created_at": r[6].isoformat(),
            }
            for r in rows
        ]
