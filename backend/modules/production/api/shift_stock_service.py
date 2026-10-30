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

    def shift_shortfalls(self, *, tenant_id: str, runs: list[dict], packing_rows: list[dict]) -> list[dict]:
        """Items the whole shift would drive below zero, each store's withdrawals added up.

        Judged on the shift's total per item and store, not line by line: the semoule
        poured is shared out across the runs, and several packing rows draw on the same
        cartons, so lines that each fit on their own can together take more than the
        shelf holds. The stock rows are locked, in a fixed order, until the posting that
        follows in the same transaction.
        """
        totals: dict[tuple[str, str], float] = {}
        lines = [line for run in runs for line in self._run_lines(run)]
        lines += [line for row in packing_rows for line in self._packing_lines(row) if line[2]]
        for quantity, product_id, location_id in lines:
            totals[(product_id, location_id)] = totals.get((product_id, location_id), 0.0) + quantity
        return [
            {"product_id": product_id, "location_id": location_id, "quantity": quantity}
            for (product_id, location_id), quantity in sorted(totals.items())
            if self._stock.would_go_negative(
                tenant_id=tenant_id, product_id=product_id, location_id=location_id, quantity=quantity, lock=True
            )
        ]

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
                "aucun produit de sortie de rebroyat n'est configuré — définissez-en un dans les paramètres de"
                " production avant de rebroyer",
            )

        work_center_id = regrind_work_center_id or run.get("work_center_id")
        if work_center_id is None:
            row = self._connection.execute(
                "SELECT work_center_id FROM production.work_orders WHERE id = %s AND tenant_id = %s",
                (run["of_id"], tenant_id),
            ).fetchone()
            work_center_id = row[0] if row is not None else None
        if work_center_id is None:
            return Err(
                "MISSING_WORK_CENTER",
                "cannot open a regrind order without a work center",
                "impossible d'ouvrir un OF de rebroyat sans poste de charge",
            )

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

    @staticmethod
    def _packing_lines(packing_row: dict) -> list[tuple[float, str, str | None]]:
        """Everything a packing row's packaging takes out of stock, one line per item.

        Each item draws from its own default store (film/carton/scotch/ruban may each sit
        in a different warehouse); a line with no store of its own falls back to the row's
        shared packaging_location_id, kept for rows saved before items had their own.
        """
        shared = packing_row.get("packaging_location_id")
        lines = [
            (float(packing_row.get("film_quantity") or 0), packing_row.get("film_product_id"), packing_row.get("film_location_id") or shared),
            (float(packing_row.get("carton_quantity") or 0), packing_row.get("carton_product_id"), packing_row.get("carton_location_id") or shared),
            (float(packing_row.get("scotch_quantity") or 0), packing_row.get("scotch_product_id"), packing_row.get("scotch_location_id") or shared),
            (float(packing_row.get("ruban_quantity") or 0), packing_row.get("ruban_product_id"), packing_row.get("ruban_location_id") or shared),
        ]
        return [(quantity, product_id, location_id) for quantity, product_id, location_id in lines if quantity > 0 and product_id]

    def finished_goods_store(self, *, tenant_id: str, packing_row: dict, finished_product_id: str | None) -> str | None:
        """Where a packing row's finished goods are posted.

        Packed goods wait in the line store until they are released. A row filled in before the line
        store was set carries the product's own store (the screen filled it in), so an empty store or
        the product's own store is read as "not chosen" and follows the line store. Any other store
        was chosen on purpose and is kept.
        """
        from core.api.service import CoreService
        from modules.production.api.dashboard_settings_service import DashboardSettingsService

        stored = packing_row.get("finished_goods_location_id")
        line_store = DashboardSettingsService(self._connection).line_store_id(tenant_id=tenant_id)
        if line_store is None:
            return stored
        if not stored:
            return line_store
        product = CoreService(self._connection).get_product(tenant_id, finished_product_id) if finished_product_id else None
        return line_store if product is not None and stored == product.default_location_id else stored

    def freeze_packing_snapshot(
        self, *, tenant_id: str, packing_row: dict, finished_product_id: str, frozen: tuple | None = None
    ) -> dict:
        """Pin the packaging parameters a packing row is judged on, once, at
        validation. Ports conditionnement_service.freeze_packaging_parameters.

        `frozen` is (net_weight_grams, packets_per_carton) already pinned by an earlier
        validation of the same row: a correction after validation keeps them, so a
        catalog change since does not quietly change what the row posts.
        """
        from core.api.service import CoreService
        from modules.production.domain.packaging_estimate import tonnage_from_count

        if frozen is not None:
            net_weight_grams, packets_per_carton = frozen
        else:
            product = CoreService(self._connection).get_product(tenant_id, finished_product_id)
            net_weight_grams = product.net_weight_grams if product else None
            packets_per_carton = product.packets_per_carton if product else None
        finished_product_quantity = tonnage_from_count(
            net_weight_grams=net_weight_grams, packets_per_carton=packets_per_carton,
            carton_quantity=float(packing_row.get("carton_quantity") or 0),
            packets_counted=float(packing_row.get("packets_counted") or 0),
            waste_carton_quantity=float(packing_row.get("waste_carton_quantity") or 0),
        )
        self._connection.execute(
            "UPDATE production.shift_packing_rows SET snapshot_net_weight_grams = %s, "
            "snapshot_packets_per_carton = %s, finished_product_quantity = %s WHERE id = %s AND tenant_id = %s",
            (net_weight_grams, packets_per_carton, finished_product_quantity, packing_row["id"], tenant_id),
        )
        return {"net_weight_grams": net_weight_grams, "packets_per_carton": packets_per_carton}

    def post_packing(
        self, *, tenant_id: str, actor_id: str, packing_row: dict, finished_product_id: str,
        correlation_id: str, reverse: bool = False,
    ) -> Result[dict]:
        """Finished product in, packaging out. Ports ReportStockService.post_conditionnement_report.

        packets_per_carton comes from the row's own frozen snapshot (set by
        freeze_packing_snapshot at validation), never the product's current
        value, so reversing or correcting an old row always posts the same
        quantity it originally did.
        """
        from modules.production.domain.packaging_estimate import finished_quantity_from_count

        direction_in = "in" if not reverse else "out"
        direction_out = "out" if not reverse else "in"
        movements: list[dict] = []

        per_carton = packing_row.get("snapshot_packets_per_carton")
        finished_quantity = finished_quantity_from_count(
            packets_per_carton=float(per_carton) if per_carton is not None else None,
            carton_quantity=float(packing_row.get("carton_quantity") or 0),
            packets_counted=float(packing_row.get("packets_counted") or 0),
            waste_carton_quantity=float(packing_row.get("waste_carton_quantity") or 0),
        )
        if finished_quantity > 0:
            received = self._stock.post_production_movement(
                tenant_id=tenant_id, product_id=finished_product_id,
                location_id=packing_row["finished_goods_location_id"], quantity=finished_quantity,
                direction=direction_in, correlation_id=correlation_id,
                reference=f"shift_packing_row:{packing_row['id']}", move_type="production", actor_id=actor_id,
                source_type="production.shift_packing_row", source_id=packing_row["id"], of_id=packing_row["of_id"],
            )
            if isinstance(received, Err):
                return received
            movements.append({"direction": direction_in, "product_id": finished_product_id, "location_id": packing_row["finished_goods_location_id"], "quantity": finished_quantity})

        for quantity, product_id, location_id in self._packing_lines(packing_row):
            issued = self._stock.post_production_movement(
                tenant_id=tenant_id, product_id=product_id, location_id=location_id,
                quantity=quantity, direction=direction_out, correlation_id=correlation_id,
                reference=f"shift_packing_row:{packing_row['id']}", move_type="production_consumption", actor_id=actor_id,
                source_type="production.shift_packing_row", source_id=packing_row["id"], of_id=packing_row["of_id"],
            )
            if isinstance(issued, Err):
                return issued
            movements.append({"direction": direction_out, "product_id": product_id, "location_id": location_id, "quantity": quantity})

        return Ok({"movements": movements})

    def register_lot(
        self, *, tenant_id: str, actor_id: str, packing_row: dict, finished_product_id: str, report_date,
    ) -> Result[str | None]:
        """Ports conditionnement_service.register_dlc_lot."""
        import datetime as _dt

        from modules.warehouse.api.lot_service import LotService

        lot_number = packing_row.get("lot_number")
        if not lot_number:
            return Ok(None)
        lot = LotService(self._connection).register_lot(
            tenant_id=tenant_id, product_id=finished_product_id, lot_number=lot_number, actor_id=actor_id,
            expiry_date=packing_row.get("dlc_date"), produced_at=_dt.datetime.combine(report_date, _dt.time.min),
            source_type="production.shift_packing_row", source_id=packing_row["id"],
        )
        if isinstance(lot, Err):
            return lot
        return Ok(lot.value.id)

    def reverse_run(
        self, *, tenant_id: str, actor_id: str, run: dict, correlation_id: str, force: bool = False,
        new_regrind_quantity: float | None = None, reason: str | None = None,
    ) -> Result[dict]:
        """Undo everything validating this run caused. Ports
        ProductionReportService._reverse_validated_effects (daily branch).
        """
        undone = self.post_run(tenant_id=tenant_id, actor_id=actor_id, run=run, correlation_id=correlation_id, reverse=True)
        if isinstance(undone, Err):
            return undone

        unwound = self._unwind_regrind(
            tenant_id=tenant_id, actor_id=actor_id, run=run, correlation_id=correlation_id, force=force,
            new_regrind_quantity=new_regrind_quantity, reason=reason,
        )
        if isinstance(unwound, Err):
            return unwound

        return Ok({
            "reversed_movements": undone.value,
            "removed_scrap_records": unwound.value["removed_scrap_records"],
            "reversed_regrind_stock": unwound.value["reversed_regrind_stock"],
            "skip_regrind_rebuild": unwound.value.get("skip_regrind_rebuild", False),
        })

    def reverse_packing(
        self, *, tenant_id: str, actor_id: str, packing_row: dict, finished_product_id: str, correlation_id: str,
    ) -> Result[dict]:
        undone = self.post_packing(
            tenant_id=tenant_id, actor_id=actor_id, packing_row=packing_row,
            finished_product_id=finished_product_id, correlation_id=correlation_id, reverse=True,
        )
        if isinstance(undone, Err):
            return undone
        return Ok({"reversed_movements": undone.value})

    def _unwind_regrind(
        self, *, tenant_id: str, actor_id: str, run: dict, correlation_id: str, force: bool = False,
        new_regrind_quantity: float | None = None, reason: str | None = None,
    ) -> Result[dict]:
        """Remove the scrap and regrind OF this run's validation created.

        A batch already ground and received into stock is refused unless force
        is set -- its output physically exists, so silently deleting the order
        underneath it would leave stock nobody can explain. force posts the
        mirror movement that undoes the receipt before removing the batch, its
        inputs and the work order itself.

        new_regrind_quantity marks the "correct a validated run" caller: there,
        a closed batch isn't refused outright -- it's reconciled against the
        corrected figure instead. reverse_run never passes it, so its behavior
        here is unchanged from a plain reversal.
        """
        scrap_rows = self._connection.execute(
            """
            SELECT id FROM production.scrap_records
            WHERE tenant_id = %s AND work_order_id = %s AND scrap_type = 'shift_run'
              AND source_note LIKE %s
            """,
            (tenant_id, run["of_id"], f"shift run {run['id']}%"),
        ).fetchall()
        if not scrap_rows:
            return Ok({"removed_scrap_records": 0, "reversed_regrind_stock": [], "skip_regrind_rebuild": False})
        scrap_ids = [row[0] for row in scrap_rows]

        batch_rows = self._connection.execute(
            """
            SELECT DISTINCT rbi.regrind_batch_work_order_id, wo.status, wo.product_id, rb.actual_output_quantity,
                   rb.input_quantity_total
            FROM production.regrind_batch_inputs rbi
            JOIN production.work_orders wo ON wo.id = rbi.regrind_batch_work_order_id
            JOIN production.regrind_batches rb ON rb.work_order_id = rbi.regrind_batch_work_order_id
            WHERE rbi.scrap_record_id = ANY(%s)
            """,
            (scrap_ids,),
        ).fetchall()

        if new_regrind_quantity is not None:
            return self._reconcile_closed_regrind_batch(
                tenant_id=tenant_id, actor_id=actor_id, run=run, force=force, reason=reason,
                new_regrind_quantity=new_regrind_quantity, batch_rows=batch_rows,
            )

        if not force:
            for _, batch_status, _, _, _ in batch_rows:
                if batch_status == "closed":
                    return Err(
                        "REGRIND_ALREADY_COMPLETED",
                        "the rebroyat order this run opened has already been ground and received into stock;"
                        " it cannot be unwound automatically",
                        "l'OF de rebroyat que ce passage a ouvert a déjà été broyé et reçu en stock ;"
                        " il ne peut pas être annulé automatiquement",
                    )

        stock = self._stock
        reversed_regrind_stock: list[dict] = []
        for batch_of_id, batch_status, product_id, actual_output_quantity, _ in batch_rows:
            if batch_status != "closed" or actual_output_quantity is None or float(actual_output_quantity) <= 0:
                continue
            receipt = stock.list_stock_moves(
                tenant_id=tenant_id, product_id=product_id, move_type="production",
                reference=f"work_order:{batch_of_id}", limit=1,
            )
            if not receipt:
                return Err(
                    "REGRIND_STOCK_MOVE_NOT_FOUND",
                    f"no stock receipt found for regrind order {batch_of_id}; refusing to force-delete blind",
                    f"aucune réception de stock trouvée pour l'OF de rebroyat {batch_of_id} ; suppression forcée refusée à l'aveugle",
                )
            location_id = receipt[0]["location_id"]
            quantity = float(actual_output_quantity)
            reversed_move = stock.post_production_movement(
                tenant_id=tenant_id, product_id=product_id, location_id=location_id, quantity=quantity,
                direction="out", correlation_id=correlation_id, reference=f"work_order:{batch_of_id}:reversed",
                move_type="production_reversal", actor_id=actor_id,
                source_type="production.regrind_batch", source_id=batch_of_id, of_id=batch_of_id,
            )
            if isinstance(reversed_move, Err):
                return reversed_move
            reversed_regrind_stock.append({"work_order_id": batch_of_id, "product_id": product_id, "location_id": location_id, "quantity": quantity})

        for batch_of_id, _, _, _, _ in batch_rows:
            self._connection.execute("DELETE FROM production.regrind_batch_inputs WHERE regrind_batch_work_order_id = %s", (batch_of_id,))
            self._connection.execute("DELETE FROM production.regrind_batches WHERE work_order_id = %s AND tenant_id = %s", (batch_of_id, tenant_id))
            self._connection.execute("DELETE FROM production.work_orders WHERE id = %s AND tenant_id = %s", (batch_of_id, tenant_id))

        self._connection.execute("DELETE FROM production.scrap_records WHERE id = ANY(%s)", (scrap_ids,))
        return Ok({"removed_scrap_records": len(scrap_ids), "reversed_regrind_stock": reversed_regrind_stock, "skip_regrind_rebuild": False})

    def _reconcile_closed_regrind_batch(
        self, *, tenant_id: str, actor_id: str, run: dict, force: bool, reason: str | None,
        new_regrind_quantity: float, batch_rows: list,
    ) -> Result[dict]:
        """Compare a correction's rebroyat figure against a closed batch instead
        of refusing it outright. Only a closed batch needs this: an open one
        never received stock, so it can still be unwound and rebuilt exactly
        like the normal path. A closed one's output physically exists, so the
        three ways the figure can move are handled instead of blocked:
          - unchanged: leave the batch alone.
          - higher: a second, independent order is opened for just the
            difference -- confirmed first via force.
          - lower: on-hand is reduced by the difference instead, carrying the
            correction's own reason for the audit trail.
        """
        closed = [row for row in batch_rows if row[1] == "closed"]
        other = [row for row in batch_rows if row[1] != "closed"]

        if len(closed) > 1:
            return Err(
                "REGRIND_MULTIPLE_CLOSED_BATCHES",
                "more than one closed rebroyat order is tied to this run; resolve manually",
                "plus d'un OF de rebroyat clôturé est lié à ce passage ; résolvez manuellement",
            )

        removed_scrap = 0
        if other:
            other_scrap_rows = self._connection.execute(
                "SELECT scrap_record_id FROM production.regrind_batch_inputs WHERE regrind_batch_work_order_id = ANY(%s)",
                ([row[0] for row in other],),
            ).fetchall()
            other_scrap_ids = [row[0] for row in other_scrap_rows]
            for batch_of_id, _, _, _, _ in other:
                self._connection.execute("DELETE FROM production.regrind_batch_inputs WHERE regrind_batch_work_order_id = %s", (batch_of_id,))
                self._connection.execute("DELETE FROM production.regrind_batches WHERE work_order_id = %s AND tenant_id = %s", (batch_of_id, tenant_id))
                self._connection.execute("DELETE FROM production.work_orders WHERE id = %s AND tenant_id = %s", (batch_of_id, tenant_id))
            if other_scrap_ids:
                self._connection.execute("DELETE FROM production.scrap_records WHERE id = ANY(%s)", (other_scrap_ids,))
            removed_scrap = len(other_scrap_ids)

        if not closed:
            return Ok({"removed_scrap_records": removed_scrap, "reversed_regrind_stock": [], "skip_regrind_rebuild": False})

        batch_of_id, _, product_id, _, input_quantity_total = closed[0]
        input_quantity_total = float(input_quantity_total)
        delta = new_regrind_quantity - input_quantity_total

        if abs(delta) < 1e-6:
            return Ok({"removed_scrap_records": removed_scrap, "reversed_regrind_stock": [], "skip_regrind_rebuild": True})

        if delta > 0:
            if not force:
                return Err(
                    "REGRIND_DELTA_REQUIRES_NEW_ORDER",
                    f"the rebroyat order this run opened already ground {input_quantity_total:g} kg and is"
                    f" closed; the corrected {new_regrind_quantity:g} kg is {delta:g} kg more — confirm to open a"
                    " new rebroyat order for the difference",
                    f"l'OF de rebroyat que ce passage a ouvert a déjà broyé {input_quantity_total:g} kg et est"
                    f" clôturé ; le chiffre corrigé de {new_regrind_quantity:g} kg est {delta:g} kg de plus — confirmez pour ouvrir un"
                    " nouvel OF de rebroyat pour la différence",
                )
            scrap = self.record_regrind(tenant_id=tenant_id, actor_id=actor_id, run=run, regrind_work_center_id=None, quantity_override=delta)
            if isinstance(scrap, Err):
                return scrap
            return Ok({"removed_scrap_records": removed_scrap, "reversed_regrind_stock": [], "skip_regrind_rebuild": True})

        stock = self._stock
        receipt = stock.list_stock_moves(tenant_id=tenant_id, product_id=product_id, move_type="production", reference=f"work_order:{batch_of_id}", limit=1)
        if not receipt:
            return Err(
                "REGRIND_STOCK_MOVE_NOT_FOUND",
                f"no stock receipt found for regrind order {batch_of_id}; refusing to adjust stock blind",
                f"aucune réception de stock trouvée pour l'OF de rebroyat {batch_of_id} ; ajustement de stock refusé à l'aveugle",
            )
        location_id = receipt[0]["location_id"]
        adjusted = stock.adjust_stock(
            tenant_id=tenant_id, product_id=product_id, location_id=location_id, delta=delta,
            reason=reason or "shift run correction", actor_id=actor_id,
            reference=f"work_order:{batch_of_id}:shift_run_correction:{run['id']}",
        )
        if isinstance(adjusted, Err):
            return adjusted
        return Ok({
            "removed_scrap_records": removed_scrap,
            "reversed_regrind_stock": [{"work_order_id": batch_of_id, "product_id": product_id, "location_id": location_id, "quantity": delta}],
            "skip_regrind_rebuild": True,
        })
