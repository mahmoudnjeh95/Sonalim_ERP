from __future__ import annotations

import psycopg


class WorkOrderYieldService:
    """Rendement (yield) = finished product / material poured in.

    Every term now comes from the OF's **validated** shift runs rather than
    from columns cached on the order:

    * finished product — the sum of the shift runs' own Produit fini figure,
      the tonnage off the scale at the press. Not the packing rows' tonnage
      — packaging can lag the press by days, and a yield that waits on it
      tells the plant nothing while the shift can still act;
    * material poured in — the shift runs' semoule figures (one term per
      run — semoule_x + semoule_y + ... across every validated shift) plus
      the rebroyat poured back into the mix. That is everything that went into
      the line, fresh or recycled.

    Semoule's own raw stored number needs no restating: it's already the basis
    `finished_product_quantity` implicitly uses (tonnes, for this tenant).
    Rebroyat poured back in is a different story: it is normally stocked in
    kg, but a report can name a raw material bought in a different unit
    instead, and summing that raw number alongside semoule inflated old OFs'
    yield denominator by up to 1000x. Restated against the OF's own semoule
    unit before it joins the sum -- not a fixed unit, since a test fixture and
    this tenant's real data don't agree on one; see regrind_service
    .create_regrind_batch's scrap intake for the same anchor-to-a-reference-
    product fix applied earlier to the batch side of the same chain.

    Nothing is persisted, matching the convention already used for regrind's
    loss_quantity. Yield is available while an OF is still running — it simply
    reflects the shifts validated so far, which is what a cockpit wants; a yield
    that only appears after closure tells the plant nothing while it can still act.
    """

    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def _totals_by_work_order(
        self, tenant_id: str, work_order_ids: list[str] | None = None
    ) -> dict[str, dict[str, float]]:
        """Semoule in, rebroyat and finished product out, per OF, validated only."""
        clauses = ["r.tenant_id = %s", "s.status = 'validated'"]
        params: list[object] = [tenant_id]
        if work_order_ids is not None:
            if not work_order_ids:
                return {}
            clauses.append("r.of_id = ANY(%s)")
            params.append(work_order_ids)

        rows = self._connection.execute(
            f"""
            WITH sem_ratio AS (
                -- Each OF's own semoule unit, when its qualities agree on one --
                -- null otherwise, which leaves rebroyat unconverted below, same
                -- as before this fix. Anchoring to what this OF actually bought
                -- rather than to a fixed unit is what keeps a kg-uniform test
                -- fixture and a tonne-buying real tenant both correct.
                SELECT r2.of_id,
                       CASE WHEN COUNT(DISTINCT u2.ratio_to_base) = 1 THEN MIN(u2.ratio_to_base) END AS ratio_to_base
                FROM production.shift_run_semolina_lines sl2
                JOIN production.shift_runs r2 ON r2.id = sl2.run_id AND r2.tenant_id = sl2.tenant_id
                JOIN production.shift_reports s2 ON s2.id = r2.shift_report_id AND s2.tenant_id = r2.tenant_id
                LEFT JOIN core.products p2 ON p2.id = sl2.product_id AND p2.tenant_id = r2.tenant_id
                LEFT JOIN core.uoms u2 ON u2.id = p2.uom_id AND u2.tenant_id = p2.tenant_id
                WHERE r2.tenant_id = %s AND s2.status = 'validated'
                GROUP BY r2.of_id
            )
            SELECT r.of_id,
                   COALESCE(SUM(sl.total_quantity), 0)
                       + COALESCE(SUM(
                           r.regrind_input_quantity
                           * COALESCE(riu.ratio_to_base, COALESCE(sr.ratio_to_base, 1))
                           / COALESCE(sr.ratio_to_base, 1)
                       ), 0),
                   COALESCE(SUM(r.regrind_quantity), 0),
                   COALESCE(SUM(r.finished_product_quantity), 0)
            FROM production.shift_runs r
            JOIN production.shift_reports s ON s.id = r.shift_report_id AND s.tenant_id = r.tenant_id
            -- Rebroyat poured back in is weighed against whatever product the
            -- run names for it -- the dedicated rebroyat product most of the
            -- time, but a run can name a raw material bought in a different
            -- unit instead. Restated against this OF's own semoule unit
            -- (sem_ratio, joined below) so material_input adds like with like.
            -- Same fix as regrind_service.create_regrind_batch's scrap intake,
            -- which anchors to the output product instead.
            LEFT JOIN core.products rip
                   ON rip.id = r.regrind_input_product_id AND rip.tenant_id = r.tenant_id
            LEFT JOIN core.uoms riu
                   ON riu.id = rip.uom_id AND riu.tenant_id = rip.tenant_id
            LEFT JOIN sem_ratio sr ON sr.of_id = r.of_id
            -- Pre-aggregated per run before joining: a run can carry several
            -- semoule lines, and joining that many-rows table straight in
            -- would multiply every other summed column by the line count.
            LEFT JOIN (
                SELECT run_id, tenant_id, SUM(quantity) AS total_quantity
                FROM production.shift_run_semolina_lines
                GROUP BY run_id, tenant_id
            ) sl ON sl.run_id = r.id AND sl.tenant_id = r.tenant_id
            WHERE {' AND '.join(clauses)}
            GROUP BY r.of_id, sr.ratio_to_base
            """,
            [tenant_id, *params],
        ).fetchall()
        return {
            of_id: {
                "semoule_quantity_total": float(semoule),
                "rebroyat_quantity": float(rebroyat),
                "produced_quantity": float(produced),
            }
            for of_id, semoule, rebroyat, produced in rows
        }

    @staticmethod
    def _yield_ratio(produced_quantity: float, material_input: float) -> float:
        return produced_quantity / material_input

    @staticmethod
    def _to_result(work_order_id: str, totals: dict[str, float]) -> dict | None:
        semoule_total = totals["semoule_quantity_total"]
        if semoule_total <= 0:
            # No validated semolina means there is nothing to divide by — an
            # undefined yield, not a zero one.
            return None
        return {
            "work_order_id": work_order_id,
            "produced_quantity": totals["produced_quantity"],
            "rebroyat_quantity": totals["rebroyat_quantity"],
            "semoule_quantity_total": semoule_total,
            "yield_ratio": WorkOrderYieldService._yield_ratio(totals["produced_quantity"], semoule_total),
        }

    def get_work_order_yield(self, *, tenant_id: str, work_order_id: str) -> dict | None:
        totals = self._totals_by_work_order(tenant_id, [work_order_id]).get(work_order_id)
        if totals is None:
            return None
        return self._to_result(work_order_id, totals)

    def list_work_order_yields(self, tenant_id: str) -> list[dict]:
        results = []
        for work_order_id, totals in self._totals_by_work_order(tenant_id).items():
            computed = self._to_result(work_order_id, totals)
            if computed is not None:
                results.append(computed)
        return results

    def list_recipe_correlation(self, *, tenant_id: str) -> list[dict]:
        """Each shift's water dosage and flow rate, against its OF's yield.

        Deliberately coarse: water_percentage and semolina_flow_rate are
        shift-level inputs, but yield is only ever computed per OF (Phase 6) —
        there is no per-shift output to divide by. Pairing a shift's inputs
        with its own OF's yield is the correlation the data actually supports;
        a finer one would need a new per-shift output figure that does not
        exist. Rows with nothing dosed or metered yet are left out, same as a
        yield with no semoule poured.

        Also carries the OF's recipe's own water line (min/max/default %),
        when it has one classified is_water, so a caller can flag a shift
        whose water_percentage drifted from what the formula actually calls
        for — recipe_check_service never covers this: it compares poured
        *quantities* against the mix, and water is dosed as a bare percentage
        with no quantity of its own to compare.
        """
        rows = self._connection.execute(
            """
            WITH water_line AS (
                SELECT rl.recipe_id,
                       MIN(rl.min_percentage) AS min_percentage,
                       MIN(rl.max_percentage) AS max_percentage,
                       MIN(rl.default_percentage) AS default_percentage
                FROM production.recipe_lines rl
                JOIN production.product_classifications pc
                     ON pc.product_id = rl.component_product_id AND pc.tenant_id = rl.tenant_id AND pc.is_water
                WHERE rl.tenant_id = %s
                GROUP BY rl.recipe_id
            )
            SELECT r.id, r.of_id, w.product_id, s.report_date, s.team,
                   r.water_percentage, r.semolina_flow_rate,
                   wl.min_percentage, wl.max_percentage, wl.default_percentage
            FROM production.shift_runs r
            JOIN production.shift_reports s ON s.id = r.shift_report_id AND s.tenant_id = r.tenant_id
            JOIN production.work_orders w ON w.id = r.of_id AND w.tenant_id = r.tenant_id
            LEFT JOIN water_line wl ON wl.recipe_id = w.recipe_id
            WHERE r.tenant_id = %s AND s.status = 'validated'
              AND (r.water_percentage > 0 OR r.semolina_flow_rate > 0)
            """,
            (tenant_id, tenant_id),
        ).fetchall()
        if not rows:
            return []

        of_ids = list({row[1] for row in rows})
        totals = self._totals_by_work_order(tenant_id, of_ids)

        results = []
        for report_id, of_id, product_id, report_date, team, water_percentage, semolina_flow_rate, water_min, water_max, water_default in rows:
            computed = self._to_result(of_id, totals[of_id]) if of_id in totals else None
            if computed is None:
                continue
            results.append(
                {
                    "report_id": report_id,
                    "of_id": of_id,
                    "product_id": product_id,
                    "report_date": report_date.isoformat(),
                    "team": team,
                    "water_percentage": float(water_percentage) if water_percentage is not None else None,
                    "semolina_flow_rate": float(semolina_flow_rate) if semolina_flow_rate is not None else None,
                    "yield_ratio": computed["yield_ratio"],
                    "water_target_min": float(water_min) if water_min is not None else None,
                    "water_target_max": float(water_max) if water_max is not None else None,
                    "water_target_default": float(water_default) if water_default is not None else None,
                }
            )
        return results

    def get_recipe_yield_summary(self, *, tenant_id: str, recipe_id: str) -> dict:
        work_order_ids = [
            row[0]
            for row in self._connection.execute(
                "SELECT id FROM production.work_orders WHERE tenant_id = %s AND recipe_id = %s",
                (tenant_id, recipe_id),
            ).fetchall()
        ]
        ratios = [
            computed["yield_ratio"]
            for work_order_id, totals in self._totals_by_work_order(tenant_id, work_order_ids).items()
            if (computed := self._to_result(work_order_id, totals)) is not None
        ]
        return {
            "recipe_id": recipe_id,
            "work_order_count": len(ratios),
            "average_yield_ratio": sum(ratios) / len(ratios) if ratios else None,
        }
