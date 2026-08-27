from __future__ import annotations

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from core.domain.sequences import next_sequence_value
from core.events.outbox import publish_event
from modules.production.domain.entities import WorkOrder, transition
from modules.warehouse.api.service import StockService


class WorkOrderService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def create_work_order(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        product_id: str,
        quantity: float,
        work_center_id: str | None = None,
        recipe_id: str | None = None,
        packaging_bom_id: str | None = None,
        poured_inputs: list[tuple[str, float]] | None = None,
        poured_inputs_location_id: str | None = None,
    ) -> Result[WorkOrder]:
        poured_inputs = poured_inputs or []
        if poured_inputs and not poured_inputs_location_id:
            return Err("MISSING_POURED_INPUTS_LOCATION", "poured_inputs_location_id is required when poured_inputs is provided")

        work_order_id = str(ULID())
        reference = next_sequence_value(self._connection, tenant_id=tenant_id, name="production.work_orders", prefix="OF-")
        self._connection.execute(
            """
            INSERT INTO production.work_orders
                (id, tenant_id, reference, product_id, quantity, status, work_center_id, recipe_id, packaging_bom_id)
            VALUES (%s, %s, %s, %s, %s, 'draft', %s, %s, %s)
            """,
            (work_order_id, tenant_id, reference, product_id, quantity, work_center_id, recipe_id, packaging_bom_id),
        )

        # Resolve each poured input's recipe line server-side (never trust a
        # client-supplied recipe_line_id), so the yield calculation can later
        # trace an actual poured quantity back to the formula line it fulfills.
        recipe_line_by_product: dict[str, str] = {}
        if recipe_id is not None and poured_inputs:
            line_rows = self._connection.execute(
                "SELECT id, component_product_id FROM production.recipe_lines WHERE recipe_id = %s AND tenant_id = %s",
                (recipe_id, tenant_id),
            ).fetchall()
            recipe_line_by_product = {component_product_id: line_id for line_id, component_product_id in line_rows}

        # Every poured raw material is soft-reserved (stays on-hand, blocks other
        # orders from using it) the moment the OF is created as a draft. It only
        # actually leaves on-hand into "en production" when the order starts —
        # see start_work_order below. Same sequential-Err pattern as
        # complete_work_order: on any failure, return Err and let the caller roll
        # back the whole transaction, including the work_orders insert above.
        stock_service = StockService(self._connection)
        for input_product_id, input_quantity in poured_inputs:
            poured = stock_service.reserve_stock(
                tenant_id=tenant_id,
                product_id=input_product_id,
                location_id=poured_inputs_location_id,  # type: ignore[arg-type]
                quantity=input_quantity,
                correlation_id=str(ULID()),
                reference=f"work_order:{work_order_id}",
                actor_id=actor_id,
            )
            if isinstance(poured, Err):
                return poured
            self._connection.execute(
                """
                INSERT INTO production.work_order_inputs (id, tenant_id, work_order_id, product_id, quantity, location_id, recipe_line_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    str(ULID()),
                    tenant_id,
                    work_order_id,
                    input_product_id,
                    input_quantity,
                    poured_inputs_location_id,
                    recipe_line_by_product.get(input_product_id),
                ),
            )

        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="work_order.created",
            entity_type="work_order",
            entity_id=work_order_id,
            payload={
                "product_id": product_id,
                "quantity": quantity,
                "poured_inputs": [{"product_id": p, "quantity": q} for p, q in poured_inputs],
            },
        )
        return Ok(
            WorkOrder(
                id=work_order_id,
                product_id=product_id,
                quantity=quantity,
                status="draft",
                reference=reference,
                work_center_id=work_center_id,
                recipe_id=recipe_id,
                packaging_bom_id=packaging_bom_id,
            )
        )

    def list_work_order_inputs(self, tenant_id: str, work_order_id: str) -> list[dict]:
        rows = self._connection.execute(
            """
            SELECT id, product_id, quantity, location_id, recipe_line_id
            FROM production.work_order_inputs
            WHERE tenant_id = %s AND work_order_id = %s
            ORDER BY created_at
            """,
            (tenant_id, work_order_id),
        ).fetchall()
        return [
            {"id": row_id, "product_id": product_id, "quantity": float(quantity), "location_id": location_id, "recipe_line_id": recipe_line_id}
            for row_id, product_id, quantity, location_id, recipe_line_id in rows
        ]

    def list_work_orders(self, tenant_id: str, status: str | None = None) -> list[WorkOrder]:
        if status is not None:
            rows = self._connection.execute(
                """
                SELECT id, reference, product_id, quantity, status, work_center_id, recipe_id, packaging_bom_id, actual_output_quantity
                FROM production.work_orders
                WHERE tenant_id = %s AND status = %s
                ORDER BY created_at DESC
                """,
                (tenant_id, status),
            ).fetchall()
        else:
            rows = self._connection.execute(
                """
                SELECT id, reference, product_id, quantity, status, work_center_id, recipe_id, packaging_bom_id, actual_output_quantity
                FROM production.work_orders
                WHERE tenant_id = %s
                ORDER BY created_at DESC
                """,
                (tenant_id,),
            ).fetchall()
        return [
            WorkOrder(
                id=order_id,
                product_id=product_id,
                quantity=float(quantity),
                status=order_status,
                reference=reference,
                work_center_id=work_center_id,
                recipe_id=recipe_id,
                packaging_bom_id=packaging_bom_id,
                actual_output_quantity=float(actual_output_quantity) if actual_output_quantity is not None else None,
            )
            for order_id, reference, product_id, quantity, order_status, work_center_id, recipe_id, packaging_bom_id, actual_output_quantity in rows
        ]

    def admin_update_work_order(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        work_order_id: str,
        quantity: float | None = None,
        work_center_id: str | None = None,
        recipe_id: str | None = None,
        packaging_bom_id: str | None = None,
    ) -> Result[WorkOrder]:
        row = self._connection.execute(
            """
            SELECT product_id, reference, quantity, status, work_center_id, recipe_id, packaging_bom_id, actual_output_quantity
            FROM production.work_orders WHERE id = %s AND tenant_id = %s FOR UPDATE
            """,
            (work_order_id, tenant_id),
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"work order {work_order_id} not found")

        product_id, reference, current_quantity, status, current_work_center_id, current_recipe_id, current_packaging_bom_id, actual_output_quantity = row
        updated_quantity = quantity if quantity is not None else float(current_quantity)
        if updated_quantity <= 0:
            return Err("INVALID_QUANTITY", "quantity must be positive")
        updated_work_center_id = work_center_id if work_center_id is not None else current_work_center_id
        updated_recipe_id = recipe_id if recipe_id is not None else current_recipe_id
        updated_packaging_bom_id = packaging_bom_id if packaging_bom_id is not None else current_packaging_bom_id

        self._connection.execute(
            "UPDATE production.work_orders SET quantity = %s, work_center_id = %s, recipe_id = %s, packaging_bom_id = %s WHERE id = %s",
            (updated_quantity, updated_work_center_id, updated_recipe_id, updated_packaging_bom_id, work_order_id),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="work_order.updated",
            entity_type="work_order",
            entity_id=work_order_id,
            payload={"quantity": updated_quantity, "work_center_id": updated_work_center_id, "recipe_id": updated_recipe_id, "packaging_bom_id": updated_packaging_bom_id},
        )
        return Ok(
            WorkOrder(
                id=work_order_id,
                product_id=product_id,
                quantity=updated_quantity,
                status=status,
                reference=reference,
                work_center_id=updated_work_center_id,
                recipe_id=updated_recipe_id,
                packaging_bom_id=updated_packaging_bom_id,
                actual_output_quantity=float(actual_output_quantity) if actual_output_quantity is not None else None,
            )
        )

    def start_work_order(self, *, tenant_id: str, actor_id: str, work_order_id: str) -> Result[WorkOrder]:
        row = self._connection.execute(
            """
            SELECT product_id, reference, quantity, status, work_center_id, recipe_id, packaging_bom_id, actual_output_quantity
            FROM production.work_orders
            WHERE id = %s AND tenant_id = %s
            FOR UPDATE
            """,
            (work_order_id, tenant_id),
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"work order {work_order_id} not found")

        product_id, reference, quantity, status, work_center_id, recipe_id, packaging_bom_id, actual_output_quantity = row
        current = WorkOrder(
            id=work_order_id,
            product_id=product_id,
            quantity=float(quantity),
            status=status,
            reference=reference,
            work_center_id=work_center_id,
            recipe_id=recipe_id,
            packaging_bom_id=packaging_bom_id,
            actual_output_quantity=float(actual_output_quantity) if actual_output_quantity is not None else None,
        )

        result = transition(current, "in_progress")
        if isinstance(result, Err):
            return result

        self._connection.execute(
            "UPDATE production.work_orders SET status = 'in_progress' WHERE id = %s",
            (work_order_id,),
        )

        # Convert each poured input's draft-time reservation into an actual
        # "en production" allocation now that the order is really starting —
        # the mirror image of the reserve() call in create_work_order above.
        stock_service = StockService(self._connection)
        poured_rows = self._connection.execute(
            "SELECT product_id, quantity, location_id FROM production.work_order_inputs WHERE tenant_id = %s AND work_order_id = %s",
            (tenant_id, work_order_id),
        ).fetchall()
        for input_product_id, input_quantity, input_location_id in poured_rows:
            released = stock_service.release_stock_reservation(
                tenant_id=tenant_id,
                product_id=input_product_id,
                location_id=input_location_id,
                quantity=float(input_quantity),
                reference=f"work_order:{work_order_id}",
                actor_id=actor_id,
            )
            if isinstance(released, Err):
                return released
            allocated = stock_service.send_to_production_stock(
                tenant_id=tenant_id,
                product_id=input_product_id,
                location_id=input_location_id,
                quantity=float(input_quantity),
                reference=f"work_order:{work_order_id}",
                actor_id=actor_id,
            )
            if isinstance(allocated, Err):
                return allocated

        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="work_order.started",
            entity_type="work_order",
            entity_id=work_order_id,
            payload={},
        )
        return result

    def complete_work_order(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        work_order_id: str,
        correlation_id: str,
        location_id: str,
        actual_output_quantity: float | None = None,
        materials_used: list[tuple[str, float]] | None = None,
        materials_location_id: str | None = None,
        scrap_entries: list[tuple[str, str, float]] | None = None,
    ) -> Result[WorkOrder]:
        if materials_used and not materials_location_id:
            return Err("MISSING_MATERIALS_LOCATION", "materials_location_id is required when materials_used is provided")

        row = self._connection.execute(
            """
            SELECT product_id, reference, quantity, status, work_center_id, recipe_id, packaging_bom_id
            FROM production.work_orders
            WHERE id = %s AND tenant_id = %s
            FOR UPDATE
            """,
            (work_order_id, tenant_id),
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"work order {work_order_id} not found")

        product_id, reference, quantity, status, work_center_id, recipe_id, packaging_bom_id = row
        current = WorkOrder(
            id=work_order_id,
            product_id=product_id,
            quantity=float(quantity),
            status=status,
            reference=reference,
            work_center_id=work_center_id,
            recipe_id=recipe_id,
            packaging_bom_id=packaging_bom_id,
        )

        result = transition(current, "completed")
        if isinstance(result, Err):
            return result

        received_quantity = actual_output_quantity if actual_output_quantity is not None else float(quantity)
        if received_quantity <= 0:
            return Err("INVALID_QUANTITY", "actual output quantity must be positive")

        self._connection.execute(
            "UPDATE production.work_orders SET status = 'completed', completed_at = NOW(), actual_output_quantity = %s WHERE id = %s",
            (actual_output_quantity, work_order_id),
        )

        stock_service = StockService(self._connection)

        # Every work order's output — a finished good or a regrind batch alike —
        # lands in stock the moment it's marked complete, at whichever location
        # the person completing it names. This is the only place production
        # output becomes real stock; nothing else writes to warehouse.stock_items
        # on behalf of a work order.
        received = stock_service.receive_stock(
            tenant_id=tenant_id,
            product_id=product_id,
            location_id=location_id,
            quantity=received_quantity,
            correlation_id=correlation_id,
            reference=f"work_order:{work_order_id}",
            actor_id=actor_id,
            move_type="production",
        )
        if isinstance(received, Err):
            return received

        # Fully consume this OF's own poured raw materials out of "en production"
        # — they already left on-hand stock at creation time (send_to_production),
        # so this is final consumption of that WIP bucket, derived entirely from
        # what was recorded then. No new input needed here.
        poured_rows = self._connection.execute(
            "SELECT product_id, quantity, location_id FROM production.work_order_inputs WHERE tenant_id = %s AND work_order_id = %s",
            (tenant_id, work_order_id),
        ).fetchall()
        for input_product_id, input_quantity, input_location_id in poured_rows:
            consumed = stock_service.consume_in_production_stock(
                tenant_id=tenant_id,
                product_id=input_product_id,
                location_id=input_location_id,
                quantity=float(input_quantity),
                reference=f"work_order:{work_order_id}",
                actor_id=actor_id,
            )
            if isinstance(consumed, Err):
                return consumed

        # Ad hoc materials (e.g. packaging) issued directly from on-hand — separate
        # from the poured-at-creation raw materials consumed automatically above.
        for material_product_id, material_quantity in materials_used or []:
            issued = stock_service.issue_stock(
                tenant_id=tenant_id,
                product_id=material_product_id,
                location_id=materials_location_id,  # type: ignore[arg-type]
                quantity=material_quantity,
                reference=f"work_order:{work_order_id}",
                actor_id=actor_id,
            )
            if isinstance(issued, Err):
                return issued

        # Scrap generated during this run, recorded per stage ("versement"/dosing
        # and "découpe"/cutting — VALID_SCRAP_TYPES already models exactly these
        # two as filling_dosing/cutting). Logged through the same ScrapService as
        # a manual "Record scrap" entry, so it shows up in the regrind (rebroyat)
        # workflow immediately — no separate step.
        for entry_scrap_type, entry_product_id, entry_quantity in scrap_entries or []:
            if entry_quantity <= 0:
                continue
            from modules.production.api.regrind_service import ScrapService

            scrap_result = ScrapService(self._connection).record_scrap(
                tenant_id=tenant_id,
                actor_id=actor_id,
                work_order_id=work_order_id,
                work_center_id=work_center_id,
                scrap_type=entry_scrap_type,
                product_id=entry_product_id,
                quantity=entry_quantity,
            )
            if isinstance(scrap_result, Err):
                return scrap_result

        publish_event(
            self._connection,
            event_type="production.work_order.completed",
            producer="production",
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            payload={"work_order_id": work_order_id, "product_id": product_id, "quantity": received_quantity},
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="work_order.completed",
            entity_type="work_order",
            entity_id=work_order_id,
            payload={
                "actual_output_quantity": actual_output_quantity,
                "materials_used": [{"product_id": p, "quantity": q} for p, q in (materials_used or [])],
                "scrap_entries": [{"scrap_type": t, "product_id": p, "quantity": q} for t, p, q in (scrap_entries or [])],
            },
        )
        return Ok(
            WorkOrder(
                id=work_order_id,
                product_id=product_id,
                quantity=float(quantity),
                status="completed",
                reference=reference,
                work_center_id=work_center_id,
                recipe_id=recipe_id,
                packaging_bom_id=packaging_bom_id,
                actual_output_quantity=actual_output_quantity,
            )
        )
