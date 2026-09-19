from __future__ import annotations

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.production.api.product_classification_service import ProductClassificationService
from modules.production.api.service import WorkOrderService
from modules.production.domain.entities import WorkOrder
from modules.production.domain.regrind import ScrapRecord, validate_scrap, validate_team_assignment
from modules.warehouse.api.service import StockService


def regrind_stage(*, work_order_status: str, assigned_team: str | None) -> str:
    """The rebroyat-specific workflow label shown in the UI.

    Layered on top of the OF's generic five-value status rather than a second
    status column: `assigned_team` is the only extra fact needed to tell a
    freshly opened batch from one a responsable has handed to a team, and the
    OF's own status already distinguishes running from finished.
    """
    if work_order_status == "closed":
        return "finished"
    if work_order_status in ("cancelled", "suspended"):
        return work_order_status
    return "assigned" if assigned_team else "new"


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

        # product_id reaches here as a caller-supplied string (the scrap dialog
        # used to allow free text) with no format guarantee. Without this check
        # a typo or made-up SKU trips the FK constraint on scrap_records as a
        # raw psycopg IntegrityError -- an unhandled 500 that also drops the
        # response's CORS headers (Starlette's ServerErrorMiddleware sits
        # outside CORSMiddleware), which the browser then misreports as a CORS
        # failure instead of the real "no such product" problem.
        product_row = self._connection.execute(
            "SELECT 1 FROM core.products WHERE tenant_id = %s AND id = %s", (tenant_id, product_id)
        ).fetchone()
        if product_row is None:
            return Err("PRODUCT_NOT_FOUND", f"product {product_id} not found")

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
            SELECT id, work_order_id, operation_step_id, scrap_type, product_id, quantity, is_reground, work_center_id, source_note,
                   (SELECT rbi.regrind_batch_work_order_id FROM production.regrind_batch_inputs rbi
                    WHERE rbi.scrap_record_id = scrap_records.id LIMIT 1)
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
                regrind_work_order_id=r[9],
            )
            for r in rows
        ]


class RegrindDefaultsService:
    """Which product the regrind of a given input yields.

    Decision 11 says a daily report validating with rebroyat above zero opens its
    regrind OF automatically — which is impossible without knowing what that OF
    produces. A tenant-wide default with an optional per-input override, the same
    shape as qc's follow-up policies.
    """

    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def resolve_output_product(self, *, tenant_id: str, input_product_id: str | None) -> str | None:
        if input_product_id is not None:
            row = self._connection.execute(
                "SELECT output_product_id FROM production.regrind_defaults WHERE tenant_id = %s AND input_product_id = %s",
                (tenant_id, input_product_id),
            ).fetchone()
            if row is not None:
                return row[0]

        row = self._connection.execute(
            "SELECT output_product_id FROM production.regrind_defaults WHERE tenant_id = %s AND input_product_id IS NULL",
            (tenant_id,),
        ).fetchone()
        return row[0] if row is not None else None

    def set_default(
        self, *, tenant_id: str, actor_id: str, output_product_id: str, input_product_id: str | None = None
    ) -> Result[dict]:
        if not output_product_id.strip():
            return Err("MISSING_OUTPUT_PRODUCT", "a regrind default must name the product the regrind yields")

        self._connection.execute(
            """
            INSERT INTO production.regrind_defaults (id, tenant_id, input_product_id, output_product_id)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (tenant_id, input_product_id) DO UPDATE
                SET output_product_id = EXCLUDED.output_product_id, updated_at = NOW()
            """,
            (str(ULID()), tenant_id, input_product_id, output_product_id),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="regrind_default.updated",
            entity_type="regrind_default",
            entity_id=input_product_id or "tenant-default",
            payload={"input_product_id": input_product_id, "output_product_id": output_product_id},
        )
        return Ok({"input_product_id": input_product_id, "output_product_id": output_product_id})

    def list_defaults(self, *, tenant_id: str) -> list[dict]:
        rows = self._connection.execute(
            """
            SELECT input_product_id, output_product_id FROM production.regrind_defaults
            WHERE tenant_id = %s ORDER BY input_product_id NULLS FIRST
            """,
            (tenant_id,),
        ).fetchall()
        return [{"input_product_id": r[0], "output_product_id": r[1]} for r in rows]


class RegrindService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def create_regrind_batch(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        scrap_record_ids: list[str],
        # The manual "create batch" screen always sends its own estimate, already
        # typed in the output product's unit. Left unset, it defaults to the
        # converted input_quantity_total below -- the automatic path's best
        # estimate, and the only one it has.
        output_quantity: float | None = None,
        # A regrind run names its line like any other OF. Phase 5's automatic
        # creation passes the validating report's work center.
        work_center_id: str,
    ) -> Result[dict]:
        """Every regrind batch, manual or automatic, becomes stock of the same
        single product — never a caller-chosen one.

        Before this, the manual "create batch" screen let an operator pick any
        existing product or mint a new one on the spot, and two people regrinding
        the same kind of scrap on different days would routinely end up on two
        different "rebroyat" products, fragmenting what should be one warehouse
        line. Resolving the output here, from the tenant-wide regrind default
        only (never a per-input override), makes it structurally impossible for
        a batch to land anywhere else — the same rule decision 11 already applies
        to the automatic path now applies to both.
        """
        if not scrap_record_ids:
            return Err("NO_SCRAP_INPUTS", "a regrind batch needs at least one scrap input")

        output_product_id = RegrindDefaultsService(self._connection).resolve_output_product(
            tenant_id=tenant_id, input_product_id=None
        )
        if output_product_id is None:
            return Err(
                "REGRIND_DEFAULT_MISSING",
                "no regrind output product is configured — set one in Production Settings before regrinding",
            )

        # Lock every input scrap row up front so a concurrent regrind batch can't
        # consume the same scrap twice.
        rows = self._connection.execute(
            """
            SELECT id, is_reground, quantity, product_id FROM production.scrap_records
            WHERE tenant_id = %s AND id = ANY(%s)
            FOR UPDATE
            """,
            (tenant_id, scrap_record_ids),
        ).fetchall()
        found_by_id = {r[0]: (r[1], float(r[2]), r[3]) for r in rows}
        for scrap_id in scrap_record_ids:
            if scrap_id not in found_by_id:
                return Err("NOT_FOUND", f"scrap record {scrap_id} not found")
            if found_by_id[scrap_id][0]:
                return Err("ALREADY_REGROUND", f"scrap record {scrap_id} was already reground")

        # Scrap is weighed in whatever unit its own product is stocked in — a
        # dough scrap tallied against a raw semolina bought by the tonne isn't
        # the same number of units as the rebroyat it becomes. Summing the raw
        # `quantity` values regardless of unit produced exactly the thousandfold
        # error the dashboard's waste ratio already guards against (see
        # ProductionDashboardTab.tsx): 0.043 t of scrap became "0.043" of
        # input_quantity_total instead of the 43 kg it actually is. Every input
        # is restated in the output product's own unit before summing.
        uom_by_product = {
            r[0]: (r[1], float(r[2]))
            for r in self._connection.execute(
                """
                SELECT p.id, u.category, u.ratio_to_base
                FROM core.products p JOIN core.uoms u ON u.id = p.uom_id AND u.tenant_id = p.tenant_id
                WHERE p.tenant_id = %s AND p.id = ANY(%s)
                """,
                (tenant_id, list({output_product_id, *(found_by_id[sid][2] for sid in scrap_record_ids)})),
            ).fetchall()
        }
        # A scrap product outside the output's own category (a carton count
        # feeding a kg rebroyat product, say) has no honest conversion — same
        # as convertQuantity() on the frontend, that quantity is taken as-is
        # rather than guessed at. This is the one pre-existing fallback path
        # (an old report with no regrind_product_id lands on the OF's own,
        # often piece-counted, finished good -- see _open_regrind_order) that
        # this leaves exactly as it already behaved.
        output_category, output_ratio = uom_by_product[output_product_id]
        input_quantity_total = 0.0
        for scrap_id in scrap_record_ids:
            quantity, scrap_product_id = found_by_id[scrap_id][1], found_by_id[scrap_id][2]
            scrap_category, scrap_ratio = uom_by_product[scrap_product_id]
            input_quantity_total += quantity * (scrap_ratio / output_ratio if scrap_category == output_category else 1)

        if output_quantity is None:
            output_quantity = input_quantity_total

        # A regrind run is just a distinct, simple work order — reuse WorkOrderService
        # directly rather than duplicating order-creation logic. It pours no inputs,
        # so the only way creation fails is a non-positive output quantity.
        # Its own "OFR-" series, counted separately from "production.work_orders",
        # keeps a rebroyat run from being numbered indistinguishably from the
        # production OF that fed it (both used to read "OF-000045").
        work_order_result = WorkOrderService(self._connection).create_work_order(
            tenant_id=tenant_id,
            actor_id=actor_id,
            product_id=output_product_id,
            planned_quantity=output_quantity,
            work_center_id=work_center_id,
            reference_sequence="production.regrind_orders",
            reference_prefix="OFR-",
        )
        if isinstance(work_order_result, Err):
            return work_order_result
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

        return Ok(self.get_regrind_batch(tenant_id=tenant_id, work_order_id=work_order.id))

    def assign_batch(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        work_order_id: str,
        team: str,
    ) -> Result[dict]:
        """Hand a newly opened regrind batch to a team.

        This is the one workflow step a responsable, not the grinding team,
        performs: it starts the OF (`planned` -> `ongoing`) and records who it
        was handed to. `complete_batch` refuses to finish a batch that skipped
        this step — a regrind run should never be closed without anyone having
        been made responsible for it first.
        """
        validation = validate_team_assignment(team)
        if isinstance(validation, Err):
            return validation
        team = team.strip()

        batch_row = self._connection.execute(
            "SELECT work_order_id FROM production.regrind_batches WHERE work_order_id = %s AND tenant_id = %s FOR UPDATE",
            (work_order_id, tenant_id),
        ).fetchone()
        if batch_row is None:
            return Err("NOT_FOUND", f"regrind batch {work_order_id} not found")

        work_order_service = WorkOrderService(self._connection)
        order = work_order_service.get_work_order(tenant_id=tenant_id, work_order_id=work_order_id)
        if order is None:
            return Err("NOT_FOUND", f"work order {work_order_id} not found")
        if order.status != "planned":
            return Err("ALREADY_ASSIGNED", f"this regrind batch is {order.status}, not new")

        started = work_order_service.start_work_order(
            tenant_id=tenant_id, actor_id=actor_id, work_order_id=work_order_id
        )
        if isinstance(started, Err):
            return started

        self._connection.execute(
            """
            UPDATE production.regrind_batches
            SET assigned_team = %s, assigned_by = %s, assigned_at = NOW()
            WHERE work_order_id = %s AND tenant_id = %s
            """,
            (team, actor_id, work_order_id, tenant_id),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="regrind_batch.assigned",
            entity_type="work_order",
            entity_id=work_order_id,
            payload={"assigned_team": team},
        )
        return Ok(self.get_regrind_batch(tenant_id=tenant_id, work_order_id=work_order_id))

    def complete_batch(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        work_order_id: str,
        correlation_id: str,
        location_id: str,
        actual_output_quantity: float | None = None,
    ) -> Result[dict]:
        """Finish grinding a regrind batch and receive what it yielded into stock.

        Rebroyat is the one production output that still becomes stock on its own
        work order rather than through a validated report: a regrind batch has no
        daily or conditionnement report behind it, only the scrap records it was
        built from. So the receive that used to happen in complete_work_order
        lives here, and the OF lifecycle itself stays inert. There is nothing to
        consume — a batch's inputs are scrap records, which never were stock.
        """
        batch_row = self._connection.execute(
            """
            SELECT input_quantity_total FROM production.regrind_batches
            WHERE work_order_id = %s AND tenant_id = %s
            FOR UPDATE
            """,
            (work_order_id, tenant_id),
        ).fetchone()
        if batch_row is None:
            return Err("NOT_FOUND", f"regrind batch {work_order_id} not found")
        input_quantity_total = float(batch_row[0])

        work_order_service = WorkOrderService(self._connection)
        order = work_order_service.get_work_order(tenant_id=tenant_id, work_order_id=work_order_id)
        if order is None:
            return Err("NOT_FOUND", f"work order {work_order_id} not found")

        received_quantity = actual_output_quantity if actual_output_quantity is not None else order.planned_quantity
        if received_quantity <= 0:
            return Err("INVALID_QUANTITY", "actual output quantity must be positive")

        # A batch must be assigned to a team before it can be finished — that is
        # what moves it out of `planned` in the first place, so still finding it
        # there means nobody was ever made responsible for grinding it.
        if order.status == "planned":
            return Err("NOT_ASSIGNED", "assign this regrind batch to a team before finishing it")
        if order.status != "ongoing":
            return Err("INVALID_STATUS", f"cannot finish a regrind batch that is {order.status}")

        received = StockService(self._connection).receive_stock(
            tenant_id=tenant_id,
            product_id=order.product_id,
            location_id=location_id,
            quantity=received_quantity,
            correlation_id=correlation_id,
            reference=f"work_order:{work_order_id}",
            actor_id=actor_id,
            move_type="production",
        )
        if isinstance(received, Err):
            return received

        self._connection.execute(
            "UPDATE production.regrind_batches SET actual_output_quantity = %s WHERE work_order_id = %s AND tenant_id = %s",
            (received_quantity, work_order_id, tenant_id),
        )

        closed = work_order_service.close_work_order(
            tenant_id=tenant_id, actor_id=actor_id, work_order_id=work_order_id, correlation_id=correlation_id
        )
        if isinstance(closed, Err):
            return closed

        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="regrind_batch.finished",
            entity_type="work_order",
            entity_id=work_order_id,
            payload={
                "output_product_id": order.product_id,
                "output_quantity": received_quantity,
                "location_id": location_id,
                "input_quantity_total": input_quantity_total,
                "loss_quantity": input_quantity_total - received_quantity,
            },
        )
        return Ok(
            {
                "work_order": closed.value,
                "input_quantity_total": input_quantity_total,
                "output_quantity": received_quantity,
                "loss_quantity": input_quantity_total - received_quantity,
            }
        )

    def get_regrind_batch(self, *, tenant_id: str, work_order_id: str) -> dict | None:
        batch_row = self._connection.execute(
            """
            SELECT work_order_id, input_quantity_total, actual_output_quantity,
                   assigned_team, assigned_by, assigned_at
            FROM production.regrind_batches WHERE work_order_id = %s AND tenant_id = %s
            """,
            (work_order_id, tenant_id),
        ).fetchone()
        if batch_row is None:
            return None
        input_quantity_total = float(batch_row[1])
        actual_output_quantity = float(batch_row[2]) if batch_row[2] is not None else None
        assigned_team = batch_row[3]

        order_row = self._connection.execute(
            """
            SELECT id, reference, product_id, planned_quantity, status, work_center_id, recipe_id,
                   packaging_bom_id
            FROM production.work_orders WHERE id = %s AND tenant_id = %s
            """,
            (work_order_id, tenant_id),
        ).fetchone()
        work_order = WorkOrder(
            id=order_row[0],
            reference=order_row[1],
            product_id=order_row[2],
            planned_quantity=float(order_row[3]),
            status=order_row[4],
            work_center_id=order_row[5],
            recipe_id=order_row[6],
            packaging_bom_id=order_row[7],
            is_regrind=True,
        )

        # Joined through to the scrap records themselves (not just their ids) so
        # a caller can trace this batch's output back to the production OF each
        # input scrap came from -- the ids alone were never enough to answer
        # "where did this rebroyat come from" without a second round trip per id.
        input_rows = self._connection.execute(
            """
            SELECT s.id, s.work_order_id, s.product_id, s.scrap_type, s.quantity
            FROM production.regrind_batch_inputs rbi
            JOIN production.scrap_records s ON s.id = rbi.scrap_record_id
            WHERE rbi.regrind_batch_work_order_id = %s
            ORDER BY s.created_at
            """,
            (work_order_id,),
        ).fetchall()
        scrap_inputs = [
            {
                "id": r[0],
                "work_order_id": r[1],
                "product_id": r[2],
                "scrap_type": r[3],
                "quantity": float(r[4]),
            }
            for r in input_rows
        ]
        return {
            "work_order": work_order,
            "scrap_record_ids": [r["id"] for r in scrap_inputs],
            "scrap_inputs": scrap_inputs,
            "input_quantity_total": input_quantity_total,
            "actual_output_quantity": actual_output_quantity,
            # The écart is only real once the team has weighed the output — before
            # that, "planned minus input" is a target, not a measured loss, and
            # showing it as one would overstate what is actually known.
            "loss_quantity": input_quantity_total - actual_output_quantity if actual_output_quantity is not None else None,
            "stage": regrind_stage(work_order_status=work_order.status, assigned_team=assigned_team),
            "assigned_team": assigned_team,
            "assigned_by": batch_row[4],
            "assigned_at": batch_row[5].isoformat() if batch_row[5] is not None else None,
        }

    def list_regrind_batches(self, *, tenant_id: str) -> list[dict]:
        rows = self._connection.execute(
            """
            SELECT wo.id, wo.product_id, wo.planned_quantity, wo.status, wo.work_center_id,
                   rb.input_quantity_total, wo.created_at, rb.actual_output_quantity, rb.assigned_team
            FROM production.regrind_batches rb
            JOIN production.work_orders wo ON wo.id = rb.work_order_id
            WHERE rb.tenant_id = %s
            ORDER BY wo.created_at DESC
            """,
            (tenant_id,),
        ).fetchall()
        batches = []
        for r in rows:
            status_, input_quantity_total, actual_output_quantity, assigned_team = r[3], float(r[5]), r[7], r[8]
            actual_output_quantity = float(actual_output_quantity) if actual_output_quantity is not None else None
            batches.append(
                {
                    "work_order_id": r[0],
                    "output_product_id": r[1],
                    "output_quantity": float(r[2]),
                    "actual_output_quantity": actual_output_quantity,
                    "status": status_,
                    "work_center_id": r[4],
                    "input_quantity_total": input_quantity_total,
                    "loss_quantity": input_quantity_total - actual_output_quantity if actual_output_quantity is not None else None,
                    "stage": regrind_stage(work_order_status=status_, assigned_team=assigned_team),
                    "assigned_team": assigned_team,
                    "created_at": r[6].isoformat(),
                }
            )
        return batches
