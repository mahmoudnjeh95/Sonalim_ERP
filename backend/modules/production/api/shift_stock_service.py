from __future__ import annotations

import psycopg

from core.domain.result import Err, Ok, Result
from modules.warehouse.api.service import StockService


class ShiftStockService:
    """What validating a shift's runs and packing rows moves in stock.

    Ported from ReportStockService/ProductionReportService onto the shift tables
    directly: a shift_runs row plays the role the old daily_reports row played,
    a shift_packing_rows row plays the role conditionnement_reports played. The
    rules themselves are unchanged -- see the docstrings on post_run/post_packing
    for the same "why" ReportStockService carried.
    """

    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection
        self._stock = StockService(connection)

    @staticmethod
    def _run_lines(run: dict) -> list[tuple[float, str, str]]:
        """Everything a run takes out of stock: semoule and rebroyat alike.

        Mirrors ReportStockService._daily_lines: each semoule line carries its
        own location; rebroyat still draws from the run's one
        raw_material_location_id.
        """
        lines = [
            (float(line["quantity"]), line["product_id"], line["location_id"])
            for line in run.get("semolina_lines", [])
        ]
        if run.get("raw_material_location_id"):
            lines.append(
                (
                    float(run.get("regrind_input_quantity") or 0),
                    run.get("regrind_input_product_id"),
                    run["raw_material_location_id"],
                )
            )
        return [
            (quantity, product_id, location_id)
            for quantity, product_id, location_id in lines
            if quantity > 0 and product_id and location_id
        ]

    def run_shortfalls(self, *, tenant_id: str, run: dict) -> list[dict]:
        """Withdrawals this run would drive below zero."""
        shortfalls: list[dict] = []
        for quantity, product_id, location_id in self._run_lines(run):
            if self._stock.would_go_negative(
                tenant_id=tenant_id, product_id=product_id, location_id=location_id, quantity=quantity
            ):
                shortfalls.append({"product_id": product_id, "location_id": location_id, "quantity": quantity})
        return shortfalls

    def post_run(
        self, *, tenant_id: str, actor_id: str, run: dict, correlation_id: str, reverse: bool = False
    ) -> Result[dict]:
        """Raw material out. The run's finished_product_quantity posts nothing --
        the packing row owns that tonnage, exactly as the old daily report did.

        With reverse=True the same lines post inward, undoing a validated run's
        effect before it is corrected or deleted.
        """
        direction = "in" if reverse else "out"
        movements: list[dict] = []
        for quantity, product_id, location_id in self._run_lines(run):
            posted = self._stock.post_production_movement(
                tenant_id=tenant_id,
                product_id=product_id,
                location_id=location_id,
                quantity=quantity,
                direction=direction,
                correlation_id=correlation_id,
                reference=f"shift_run:{run['id']}",
                move_type="production_consumption",
                actor_id=actor_id,
                source_type="production.shift_run",
                source_id=run["id"],
                of_id=run["of_id"],
            )
            if isinstance(posted, Err):
                return posted
            movements.append({"direction": direction, "product_id": product_id, "location_id": location_id, "quantity": quantity})
        return Ok({"movements": movements})

    def record_regrind(
        self, *, tenant_id: str, actor_id: str, run: dict, regrind_work_center_id: str | None = None,
        quantity_override: float | None = None,
    ) -> Result[dict]:
        """Turn a run's rebroyat figure into a scrap record, and open the rebroyat
        OF it calls for. Ports ProductionReportService._record_regrind_scrap +
        _open_regrind_order combined -- same rule: the scrap product is always the
        tenant's one rebroyat default (never the run's own regrind_product_id,
        which is informational only), because every regrind batch resolves to
        that single product regardless of what fed it.
        """
        from modules.production.api.regrind_service import RegrindDefaultsService, RegrindService, ScrapService

        quantity = quantity_override if quantity_override is not None else float(run.get("regrind_quantity") or 0)
        if quantity <= 0:
            return Ok({"scrap_record_id": None, "regrind_work_order_id": None})

        scrap_product_id = RegrindDefaultsService(self._connection).resolve_output_product(
            tenant_id=tenant_id, input_product_id=None
        )
        if scrap_product_id is None:
            return Err(
                "REGRIND_DEFAULT_MISSING",
                "no regrind output product is configured — set one in Production Settings before regrinding",
            )

        work_center_id = regrind_work_center_id or run.get("work_center_id")
        if work_center_id is None:
            row = self._connection.execute(
                "SELECT work_center_id FROM production.work_orders WHERE id = %s AND tenant_id = %s",
                (run["of_id"], tenant_id),
            ).fetchone()
            work_center_id = row[0] if row is not None else None
        if work_center_id is None:
            return Err("MISSING_WORK_CENTER", "cannot open a regrind order without a work center")

        scrap = ScrapService(self._connection).record_scrap(
            tenant_id=tenant_id, actor_id=actor_id, work_order_id=run["of_id"], work_center_id=work_center_id,
            scrap_type="shift_run", product_id=scrap_product_id, quantity=quantity,
            source_note=f"shift run {run['id']}",
        )
        if isinstance(scrap, Err):
            return scrap

        batch = RegrindService(self._connection).create_regrind_batch(
            tenant_id=tenant_id, actor_id=actor_id, scrap_record_ids=[scrap.value.id], work_center_id=work_center_id,
        )
        if isinstance(batch, Err):
            return batch
        return Ok({"scrap_record_id": scrap.value.id, "regrind_work_order_id": batch.value["work_order"].id})
