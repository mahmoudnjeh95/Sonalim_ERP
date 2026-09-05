from __future__ import annotations

import psycopg


class WorkOrderYieldService:
    """Rendement (yield) = finished product / material poured in.

    Every term now comes from the OF's **validated** reports rather than from
    columns cached on the order:

    * finished product — the sum of the conditionnement reports, which is the
      tonnage that actually became sellable stock. Rebroyat generated during the
      shift is waste recorded separately, not counted as output here;
    * material poured in — the daily reports' semoule figures (one term per
      report — semoule_x + semoule_y + ... across every validated shift) plus
      the rebroyat poured back into the mix. That is everything that went into
      the line, fresh or recycled.

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
        clauses = ["r.tenant_id = %s", "r.status = 'validated'"]
        params: list[object] = [tenant_id]
        if work_order_ids is not None:
            if not work_order_ids:
                return {}
            clauses.append("r.of_id = ANY(%s)")
            params.append(work_order_ids)

        rows = self._connection.execute(
            f"""
            SELECT r.of_id,
                   COALESCE(SUM(sl.total_quantity), 0) + COALESCE(SUM(d.regrind_input_quantity), 0),
                   COALESCE(SUM(d.regrind_quantity), 0),
                   COALESCE(SUM(c.finished_product_quantity), 0)
            FROM production.production_reports r
            LEFT JOIN production.daily_reports d
                   ON d.report_id = r.id AND d.tenant_id = r.tenant_id
            LEFT JOIN production.conditionnement_reports c
                   ON c.report_id = r.id AND c.tenant_id = r.tenant_id
            -- Pre-aggregated per report before joining: a report can carry
            -- several semoule lines, and joining that many-rows table straight
            -- in would multiply every other summed column by the line count.
            LEFT JOIN (
                SELECT report_id, tenant_id, SUM(quantity) AS total_quantity
                FROM production.report_semolina_lines
                GROUP BY report_id, tenant_id
            ) sl ON sl.report_id = r.id AND sl.tenant_id = r.tenant_id
            WHERE {' AND '.join(clauses)}
            GROUP BY r.of_id
            """,
            params,
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
        """
        rows = self._connection.execute(
            """
            SELECT r.id, r.of_id, w.product_id, d.water_percentage, d.semolina_flow_rate
            FROM production.production_reports r
            JOIN production.daily_reports d ON d.report_id = r.id AND d.tenant_id = r.tenant_id
            JOIN production.work_orders w ON w.id = r.of_id AND w.tenant_id = r.tenant_id
            WHERE r.tenant_id = %s AND r.status = 'validated'
              AND (d.water_percentage > 0 OR d.semolina_flow_rate > 0)
            """,
            (tenant_id,),
        ).fetchall()
        if not rows:
            return []

        of_ids = list({of_id for _, of_id, *_rest in rows})
        totals = self._totals_by_work_order(tenant_id, of_ids)

        results = []
        for report_id, of_id, product_id, water_percentage, semolina_flow_rate in rows:
            computed = self._to_result(of_id, totals[of_id]) if of_id in totals else None
            if computed is None:
                continue
            results.append(
                {
                    "report_id": report_id,
                    "of_id": of_id,
                    "product_id": product_id,
                    "water_percentage": float(water_percentage) if water_percentage is not None else None,
                    "semolina_flow_rate": float(semolina_flow_rate) if semolina_flow_rate is not None else None,
                    "yield_ratio": computed["yield_ratio"],
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
