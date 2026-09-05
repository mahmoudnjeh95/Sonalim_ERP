from __future__ import annotations

import datetime
from dataclasses import replace

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from core.domain.sequences import next_sequence_value
from core.events.outbox import publish_event
from modules.production.domain.entities import VALID_TRANSITIONS, WorkOrder, transition

_WORK_ORDER_COLUMNS = """
    id, reference, product_id, planned_quantity, status, work_center_id, recipe_id,
    packaging_bom_id, start_date, product_type, notes, created_by, closed_at, closed_by
"""


def _row_to_work_order(row: tuple) -> WorkOrder:
    (
        order_id,
        reference,
        product_id,
        planned_quantity,
        status,
        work_center_id,
        recipe_id,
        packaging_bom_id,
        start_date,
        product_type,
        notes,
        created_by,
        closed_at,
        closed_by,
    ) = row
    return WorkOrder(
        id=order_id,
        reference=reference,
        product_id=product_id,
        planned_quantity=float(planned_quantity) if planned_quantity is not None else None,
        status=status,
        work_center_id=work_center_id,
        recipe_id=recipe_id,
        packaging_bom_id=packaging_bom_id,
        start_date=start_date,
        product_type=product_type,
        notes=notes,
        created_by=created_by,
        closed_at=closed_at,
        closed_by=closed_by,
    )


class WorkOrderService:
    """The OF: what was planned, and the record that it ran.

    Nothing in this service touches inventory. Stock is posted only when a
    production report is validated, or when quality moves non-conforming product
    — see the report and qc services. An OF that is created, started, suspended,
    resumed, cancelled or closed moves no stock at all.
    """

    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def create_work_order(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        # Nullable: creation names the work center, PC/PL and start date —
        # not the product. Conditionnement backfills product_id the moment
        # the first packaging report is filed against this order.
        product_id: str | None = None,
        # Nullable: the quantity is assigned later, once known, via update.
        planned_quantity: float | None = None,
        # Decision 15: the OF's work center is required and always asked for
        # directly — no other field on this order resolves it implicitly.
        work_center_id: str | None = None,
        recipe_id: str | None = None,
        packaging_bom_id: str | None = None,
        start_date: datetime.date | None = None,
        product_type: str | None = None,
        notes: str | None = None,
        poured_inputs: list[tuple[str, float]] | None = None,
        poured_inputs_location_id: str | None = None,
    ) -> Result[WorkOrder]:
        if planned_quantity is not None and planned_quantity <= 0:
            return Err("INVALID_QUANTITY", "planned quantity must be positive")
        if not (work_center_id or "").strip():
            return Err("MISSING_WORK_CENTER", "a work order must name the work center it runs on")

        poured_inputs = poured_inputs or []
        if poured_inputs and not poured_inputs_location_id:
            return Err("MISSING_POURED_INPUTS_LOCATION", "poured_inputs_location_id is required when poured_inputs is provided")

        work_order_id = str(ULID())
        reference = next_sequence_value(self._connection, tenant_id=tenant_id, name="production.work_orders", prefix="OF-")
        self._connection.execute(
            """
            INSERT INTO production.work_orders
                (id, tenant_id, reference, product_id, planned_quantity, status, work_center_id,
                 recipe_id, packaging_bom_id, start_date, product_type, notes, created_by)
            VALUES (%s, %s, %s, %s, %s, 'planned', %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                work_order_id,
                tenant_id,
                reference,
                product_id,
                planned_quantity,
                work_center_id,
                recipe_id,
                packaging_bom_id,
                start_date,
                product_type,
                notes,
                actor_id,
            ),
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

        # Poured inputs are recorded, not reserved. What a line actually consumed
        # is declared on the daily report and posted when a supervisor validates
        # it; these rows only say which materials the OF was planned around, and
        # from where.
        for input_product_id, input_quantity in poured_inputs:
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
                "planned_quantity": planned_quantity,
                "work_center_id": work_center_id,
                "start_date": start_date.isoformat() if start_date is not None else None,
                "product_type": product_type,
                "poured_inputs": [{"product_id": p, "quantity": q} for p, q in poured_inputs],
            },
        )
        return Ok(
            WorkOrder(
                id=work_order_id,
                product_id=product_id,
                planned_quantity=planned_quantity,
                status="planned",
                reference=reference,
                work_center_id=work_center_id,
                recipe_id=recipe_id,
                packaging_bom_id=packaging_bom_id,
                start_date=start_date,
                product_type=product_type,
                notes=notes,
                created_by=actor_id,
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
                f"""
                SELECT {_WORK_ORDER_COLUMNS}
                FROM production.work_orders
                WHERE tenant_id = %s AND status = %s
                ORDER BY created_at DESC
                """,
                (tenant_id, status),
            ).fetchall()
        else:
            rows = self._connection.execute(
                f"""
                SELECT {_WORK_ORDER_COLUMNS}
                FROM production.work_orders
                WHERE tenant_id = %s
                ORDER BY created_at DESC
                """,
                (tenant_id,),
            ).fetchall()
        return [_row_to_work_order(row) for row in rows]

    def get_work_order(self, *, tenant_id: str, work_order_id: str) -> WorkOrder | None:
        row = self._connection.execute(
            f"SELECT {_WORK_ORDER_COLUMNS} FROM production.work_orders WHERE id = %s AND tenant_id = %s",
            (work_order_id, tenant_id),
        ).fetchone()
        return _row_to_work_order(row) if row is not None else None

    def _load_for_update(self, *, tenant_id: str, work_order_id: str) -> WorkOrder | None:
        row = self._connection.execute(
            f"SELECT {_WORK_ORDER_COLUMNS} FROM production.work_orders WHERE id = %s AND tenant_id = %s FOR UPDATE",
            (work_order_id, tenant_id),
        ).fetchone()
        return _row_to_work_order(row) if row is not None else None

    def _apply_transition(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        work_order_id: str,
        new_status: str,
        action: str,
        payload: dict | None = None,
    ) -> Result[WorkOrder]:
        """Move one OF to a new status under a row lock. Posts no stock, by design."""
        current = self._load_for_update(tenant_id=tenant_id, work_order_id=work_order_id)
        if current is None:
            return Err("NOT_FOUND", f"work order {work_order_id} not found")

        result = transition(current, new_status)
        if isinstance(result, Err):
            return result

        self._connection.execute(
            "UPDATE production.work_orders SET status = %s WHERE id = %s",
            (new_status, work_order_id),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action=action,
            entity_type="work_order",
            entity_id=work_order_id,
            payload=payload or {},
        )
        return result

    def admin_update_work_order(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        work_order_id: str,
        # Manual correction only — the normal way this gets set is the first
        # Conditionnement report filed against the order.
        product_id: str | None = None,
        planned_quantity: float | None = None,
        work_center_id: str | None = None,
        recipe_id: str | None = None,
        packaging_bom_id: str | None = None,
        start_date: datetime.date | None = None,
        product_type: str | None = None,
        notes: str | None = None,
    ) -> Result[WorkOrder]:
        current = self._load_for_update(tenant_id=tenant_id, work_order_id=work_order_id)
        if current is None:
            return Err("NOT_FOUND", f"work order {work_order_id} not found")

        updated_product_id = product_id if product_id is not None else current.product_id
        updated_quantity = planned_quantity if planned_quantity is not None else current.planned_quantity
        if updated_quantity is not None and updated_quantity <= 0:
            return Err("INVALID_QUANTITY", "planned quantity must be positive")
        updated_work_center_id = work_center_id if work_center_id is not None else current.work_center_id
        updated_recipe_id = recipe_id if recipe_id is not None else current.recipe_id
        updated_packaging_bom_id = packaging_bom_id if packaging_bom_id is not None else current.packaging_bom_id
        updated_start_date = start_date if start_date is not None else current.start_date
        updated_product_type = product_type if product_type is not None else current.product_type
        updated_notes = notes if notes is not None else current.notes

        self._connection.execute(
            """
            UPDATE production.work_orders
            SET product_id = %s, planned_quantity = %s, work_center_id = %s, recipe_id = %s, packaging_bom_id = %s,
                start_date = %s, product_type = %s, notes = %s
            WHERE id = %s
            """,
            (
                updated_product_id,
                updated_quantity,
                updated_work_center_id,
                updated_recipe_id,
                updated_packaging_bom_id,
                updated_start_date,
                updated_product_type,
                updated_notes,
                work_order_id,
            ),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="work_order.updated",
            entity_type="work_order",
            entity_id=work_order_id,
            payload={
                "product_id": updated_product_id,
                "planned_quantity": updated_quantity,
                "work_center_id": updated_work_center_id,
                "recipe_id": updated_recipe_id,
                "packaging_bom_id": updated_packaging_bom_id,
                "start_date": updated_start_date.isoformat() if updated_start_date is not None else None,
                "product_type": updated_product_type,
            },
        )
        return Ok(
            WorkOrder(
                id=work_order_id,
                product_id=updated_product_id,
                planned_quantity=updated_quantity,
                status=current.status,
                reference=current.reference,
                work_center_id=updated_work_center_id,
                recipe_id=updated_recipe_id,
                packaging_bom_id=updated_packaging_bom_id,
                start_date=updated_start_date,
                product_type=updated_product_type,
                notes=updated_notes,
                created_by=current.created_by,
                closed_at=current.closed_at,
                closed_by=current.closed_by,
            )
        )

    def start_work_order(self, *, tenant_id: str, actor_id: str, work_order_id: str) -> Result[WorkOrder]:
        return self._apply_transition(
            tenant_id=tenant_id,
            actor_id=actor_id,
            work_order_id=work_order_id,
            new_status="ongoing",
            action="work_order.started",
        )

    def suspend_work_order(
        self, *, tenant_id: str, actor_id: str, work_order_id: str, reason: str | None = None
    ) -> Result[WorkOrder]:
        return self._apply_transition(
            tenant_id=tenant_id,
            actor_id=actor_id,
            work_order_id=work_order_id,
            new_status="suspended",
            action="work_order.suspended",
            payload={"reason": reason},
        )

    def resume_work_order(self, *, tenant_id: str, actor_id: str, work_order_id: str) -> Result[WorkOrder]:
        return self._apply_transition(
            tenant_id=tenant_id,
            actor_id=actor_id,
            work_order_id=work_order_id,
            new_status="ongoing",
            action="work_order.resumed",
        )

    def cancel_work_order(
        self, *, tenant_id: str, actor_id: str, work_order_id: str, reason: str | None = None
    ) -> Result[WorkOrder]:
        return self._apply_transition(
            tenant_id=tenant_id,
            actor_id=actor_id,
            work_order_id=work_order_id,
            new_status="cancelled",
            action="work_order.cancelled",
            payload={"reason": reason},
        )

    def pre_close_check(self, *, tenant_id: str, work_order_id: str) -> Result[dict]:
        """What still stands between this OF and closure.

        Two kinds of finding, and the difference matters:

        * **Blockers** are unfinished production work — reports that are still
          drafts, still waiting at the validation desk, or rejected and never
          revised. Closing over them would strand figures that were never
          consolidated and, for submitted reports, stock that was never posted.
        * **Warnings** are things worth seeing but which must never hold an order
          open. Quality is the important case: the follow-up window deliberately
          outlives production, so refusing to close until it expires would keep
          every OF open for weeks and make the closure state meaningless.
        """
        order = self.get_work_order(tenant_id=tenant_id, work_order_id=work_order_id)
        if order is None:
            return Err("NOT_FOUND", f"work order {work_order_id} not found")

        counts = dict(
            self._connection.execute(
                """
                SELECT status, count(*) FROM production.production_reports
                WHERE tenant_id = %s AND of_id = %s GROUP BY status
                """,
                (tenant_id, work_order_id),
            ).fetchall()
        )

        blockers: list[dict] = []
        for status, code, message in (
            ("draft", "DRAFT_REPORTS", "a team still has a report open as a draft"),
            ("submitted", "UNVALIDATED_REPORTS", "a report is still waiting at the validation desk"),
            ("rejected", "REJECTED_REPORTS", "a rejected report has not been revised or abandoned"),
        ):
            count = int(counts.get(status, 0))
            if count:
                blockers.append({"code": code, "count": count, "message": message})

        warnings: list[dict] = []
        validated = int(counts.get("validated", 0))
        if validated == 0:
            warnings.append(
                {
                    "code": "NO_VALIDATED_REPORTS",
                    "count": 0,
                    "message": "this order has no validated reports, so it will consolidate to nothing",
                }
            )
        if order.start_date is None:
            warnings.append(
                {"code": "MISSING_START_DATE", "count": 0, "message": "the order never recorded a start date"}
            )

        quality = self._open_quality_work(tenant_id=tenant_id, work_order_id=work_order_id)
        if quality["open_follow_ups"]:
            warnings.append(
                {
                    "code": "OPEN_QUALITY_FOLLOW_UPS",
                    "count": quality["open_follow_ups"],
                    "message": "quality follow-up is still running; it outlives the order and does not block closure",
                }
            )
        if quality["open_non_conformities"]:
            warnings.append(
                {
                    "code": "OPEN_NON_CONFORMITIES",
                    "count": quality["open_non_conformities"],
                    "message": "a non-conformity is still open; it can be worked on after closure",
                }
            )

        return Ok(
            {
                "of_id": work_order_id,
                "reference": order.reference,
                "status": order.status,
                # Closable means both "nothing unfinished" and "the lifecycle
                # allows it from here" — only an ongoing order can be closed.
                "can_close": not blockers and "closed" in VALID_TRANSITIONS.get(order.status, set()),
                "blockers": blockers,
                "warnings": warnings,
                "validated_report_count": validated,
            }
        )

    def _open_quality_work(self, *, tenant_id: str, work_order_id: str) -> dict:
        """Quality's outstanding work, asked of qc rather than read from its tables."""
        from modules.qc.api.non_conformity_service import NonConformityService
        from modules.qc.api.quality_service import FollowUpService

        return {
            "open_follow_ups": FollowUpService(self._connection).count_open_for_of(
                tenant_id=tenant_id, of_id=work_order_id
            ),
            "open_non_conformities": NonConformityService(self._connection).count_open_for_of(
                tenant_id=tenant_id, of_id=work_order_id
            ),
        }

    def close_work_order(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        work_order_id: str,
        correlation_id: str,
        force: bool = False,
        force_reason: str | None = None,
        # When it actually finished, picked by whoever closes it — defaults to
        # now when not given, but a shift closed the next morning needs to say
        # so rather than borrow the moment someone got around to clicking close.
        closed_at: datetime.datetime | None = None,
    ) -> Result[WorkOrder]:
        """Close an OF. Historical only: nothing is deleted and no stock moves.

        Everything hanging off the order — reports, validations, stock movements
        already posted by those validations, and quality history — stays readable
        afterwards, and quality may still raise a non-conformity against it. That
        is the point of closure being archival rather than a lock.

        Unfinished production work blocks it (see pre_close_check). `force` exists
        because an order can otherwise be held open forever by a draft nobody will
        ever finish — but it demands a reason, and that reason lands in the audit
        trail next to the blockers it overrode.
        """
        check = self.pre_close_check(tenant_id=tenant_id, work_order_id=work_order_id)
        if isinstance(check, Err):
            return check
        blockers = check.value["blockers"]
        if blockers and not force:
            return Err(
                "OF_HAS_BLOCKERS",
                "this order still has unfinished reports: "
                + ", ".join(f"{b['count']} {b['code'].lower().replace('_', ' ')}" for b in blockers),
            )
        if blockers and force and not (force_reason or "").strip():
            return Err("MISSING_REASON", "closing over unfinished reports must record why")

        result = self._apply_transition(
            tenant_id=tenant_id,
            actor_id=actor_id,
            work_order_id=work_order_id,
            new_status="closed",
            action="work_order.closed",
        )
        if isinstance(result, Err):
            return result

        recorded_closed_at = self._connection.execute(
            "UPDATE production.work_orders SET closed_at = COALESCE(%s, NOW()), closed_by = %s WHERE id = %s RETURNING closed_at",
            (closed_at, actor_id, work_order_id),
        ).fetchone()[0]
        order = replace(result.value, closed_at=recorded_closed_at, closed_by=actor_id)

        if blockers:
            record_audit(
                self._connection,
                tenant_id=tenant_id,
                actor_id=actor_id,
                action="work_order.closed_over_blockers",
                entity_type="work_order",
                entity_id=work_order_id,
                payload={"blockers": blockers, "reason": force_reason},
            )

        publish_event(
            self._connection,
            event_type="production.work_order.closed",
            producer="production",
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            payload={
                "work_order_id": work_order_id,
                "product_id": order.product_id,
                "planned_quantity": order.planned_quantity,
            },
        )
        return Ok(order)
