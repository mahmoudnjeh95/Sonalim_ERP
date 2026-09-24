from __future__ import annotations

import psycopg


# Whatever a report can be filed under, from Production Settings — never
# validated against a fixed enum here, so a new team the plant adds shows up
# the moment it appears on a validated report.
GRAINS = ("day", "week", "month", "year")


class TeamPerformanceService:
    """Output, time and waste, bucketed by team and by period.

    Only validated reports count, matching every other aggregate in this
    module — a draft or rejected report is a team's working notes, not a
    result to hold anyone to.

    Grouped by team *and* period in one pass rather than one query per team:
    the set of teams is open-ended (Production Settings lets the plant add one
    any time), so there is no fixed list to loop over — whatever `team` values
    appear on validated reports in the window are exactly the rows returned.
    """

    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def list_team_performance(
        self,
        *,
        tenant_id: str,
        grain: str,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> list[dict]:
        if grain not in GRAINS:
            raise ValueError(f"grain must be one of {GRAINS}")

        clauses = ["r.tenant_id = %s", "r.status = 'validated'"]
        clauses2 = ["r2.tenant_id = %s", "r2.status = 'validated'"]
        params: list[object] = [grain, tenant_id]
        if date_from is not None:
            clauses.append("r.report_date >= %s")
            clauses2.append("r2.report_date >= %s")
            params.append(date_from)
        if date_to is not None:
            clauses.append("r.report_date <= %s")
            clauses2.append("r2.report_date <= %s")
            params.append(date_to)
        where = " AND ".join(clauses)
        where2 = " AND ".join(clauses2)

        totals = self._connection.execute(
            f"""
            WITH sem_ratio AS (
                -- Each team+period bucket's own semoule unit, when its
                -- qualities agree on one -- null otherwise, which leaves
                -- rebroyat unconverted below. Same fix as
                -- WorkOrderYieldService's sem_ratio, keyed by (team, period)
                -- instead of of_id since this aggregate folds several OFs
                -- into one bucket.
                SELECT r2.team, date_trunc(%s, r2.report_date)::date AS period,
                       CASE WHEN COUNT(DISTINCT u2.ratio_to_base) = 1 THEN MIN(u2.ratio_to_base) END AS ratio_to_base
                FROM production.report_semolina_lines sl2
                JOIN production.production_reports r2 ON r2.id = sl2.report_id AND r2.tenant_id = sl2.tenant_id
                LEFT JOIN core.products p2 ON p2.id = sl2.product_id AND p2.tenant_id = r2.tenant_id
                LEFT JOIN core.uoms u2 ON u2.id = p2.uom_id AND u2.tenant_id = p2.tenant_id
                WHERE {where2}
                GROUP BY r2.team, period
            ),
            report_periods AS (
                SELECT r.*, date_trunc(%s, r.report_date)::date AS period
                FROM production.production_reports r
                WHERE {where}
            )
            SELECT
                r.team,
                r.period,
                count(*) AS report_count,
                COALESCE(SUM(sl.total_quantity), 0) AS semolina_quantity,
                COALESCE(SUM(d.regrind_input_quantity), 0) AS regrind_input_quantity,
                -- Rebroyat poured back in is weighed against whatever product
                -- the report names for it -- normally the dedicated rebroyat
                -- product, but a report can name a raw material bought in a
                -- different unit instead. Restated against this bucket's own
                -- semoule unit (sem_ratio, joined below) before it joins the
                -- sum -- summing the raw figure alongside semoule inflated
                -- material_input_quantity by up to 1000x whenever rebroyat
                -- was recorded in kg against semoule bought by the tonne.
                -- Same fix as WorkOrderYieldService/OfConsolidationService.
                COALESCE(SUM(
                    d.regrind_input_quantity
                    * COALESCE(riu.ratio_to_base, COALESCE(sr.ratio_to_base, 1))
                    / COALESCE(sr.ratio_to_base, 1)
                ), 0) AS regrind_input_quantity_normalized,
                COALESCE(SUM(d.regrind_quantity), 0) AS regrind_quantity,
                -- The daily report's own Produit fini -- the tonnage off the
                -- scale at the press, available before packaging catches up.
                -- See WorkOrderYieldService for the same choice.
                COALESCE(SUM(d.finished_product_quantity), 0) AS produced_quantity,
                COALESCE(SUM(d.production_minutes), 0) + COALESCE(SUM(c.production_minutes), 0) AS production_minutes,
                COALESCE(SUM(dl.total_minutes), 0) + COALESCE(SUM(c.downtime_minutes), 0) AS downtime_minutes
            FROM report_periods r
            LEFT JOIN production.daily_reports d
                   ON d.report_id = r.id AND d.tenant_id = r.tenant_id
            LEFT JOIN production.conditionnement_reports c
                   ON c.report_id = r.id AND c.tenant_id = r.tenant_id
            LEFT JOIN core.products rip ON rip.id = d.regrind_input_product_id AND rip.tenant_id = r.tenant_id
            LEFT JOIN core.uoms riu ON riu.id = rip.uom_id AND riu.tenant_id = rip.tenant_id
            LEFT JOIN sem_ratio sr ON sr.team IS NOT DISTINCT FROM r.team AND sr.period = r.period
            -- Pre-aggregated per report before joining, same reason as the
            -- yield service: a report can carry several semoule lines, and
            -- joining that many-rows table straight in would multiply every
            -- other summed column by the line count.
            LEFT JOIN (
                SELECT report_id, tenant_id, SUM(quantity) AS total_quantity
                FROM production.report_semolina_lines
                GROUP BY report_id, tenant_id
            ) sl ON sl.report_id = r.id AND sl.tenant_id = r.tenant_id
            -- Same pre-aggregation, now that a daily report's downtime is a
            -- list rather than one column: a report can carry several arrêts.
            LEFT JOIN (
                SELECT report_id, tenant_id, SUM(minutes) AS total_minutes
                FROM production.report_downtime_lines
                GROUP BY report_id, tenant_id
            ) dl ON dl.report_id = r.id AND dl.tenant_id = r.tenant_id
            GROUP BY r.team, r.period
            """,
            params + params,
        ).fetchall()

        # A daily report's déchet is always weighed in kg on the form
        # (WasteLinesField's fixedUnit), regardless of the item's own declared
        # unit — a semoule bought and poured by the tonne is still spilled by
        # the kilo. Restated here into each item's own unit so `waste_by_product`
        # agrees with `semolina_quantity` and everything else that reads a
        # product's own UOM; a packing report's product/packaging categories
        # are already weighed in whatever the item is actually stocked in and
        # pass through unchanged. A product with no honest kg->its-unit path
        # (not weight-category, or no product named) is left in raw kilos.
        waste_rows = self._connection.execute(
            f"""
            SELECT
                r.team, date_trunc(%s, r.report_date)::date AS period, w.product_id,
                COALESCE(SUM(
                    CASE
                        WHEN r.report_type = 'daily' AND u.category = 'weight' AND u.ratio_to_base > 0
                            THEN w.quantity / u.ratio_to_base
                        ELSE w.quantity
                    END
                ), 0)
            FROM production.report_waste_lines w
            JOIN production.production_reports r ON r.id = w.report_id AND r.tenant_id = w.tenant_id
            LEFT JOIN core.products p ON p.id = w.product_id AND p.tenant_id = r.tenant_id
            LEFT JOIN core.uoms u ON u.id = p.uom_id AND u.tenant_id = p.tenant_id
            WHERE {where} AND w.product_id IS NOT NULL
            GROUP BY r.team, period, w.product_id
            """,
            params,
        ).fetchall()
        waste_by_key: dict[tuple[str | None, str], list[dict]] = {}
        for team, period, product_id, quantity in waste_rows:
            key = (team, period.isoformat())
            waste_by_key.setdefault(key, []).append({"product_id": product_id, "quantity": float(quantity)})

        # Semoule-side déchet only (raw_material through finished_product_conditioning,
        # the daily report's own categories) — a conditionnement report's product/
        # packaging waste is packaging waste, not semoule, so it never belongs in
        # the écart this powers. Grouped by category, not by product like above,
        # because the point here is which *stage* lost the material, not which item.
        #
        # Deliberately raw kilos, the form's own basis (WasteLinesField's
        # fixedUnit) — never each item's own unit. `finished_product_conditioning`
        # is routinely logged against a finished-goods item stocked in kg while
        # the other five stages use bulk semoule stocked in tonnes; converting
        # each to its own unit before this dict is built made one category's
        # figure look ~1000x the others once several stages are stacked and
        # compared side by side (e.g. on the team-performance dashboard's
        # semoule-waste chart) — a 12 kg category rendering as a bigger bar
        # than a 119 kg one. `net_semoule_waste` below already nets on this
        # same raw-kg basis for exactly that reason; this dict now matches it,
        # so every stage stays comparable and the parts sum to the whole.
        category_waste_rows = self._connection.execute(
            f"""
            SELECT
                r.team, date_trunc(%s, r.report_date)::date AS period, w.category,
                COALESCE(SUM(w.quantity), 0)
            FROM production.report_waste_lines w
            JOIN production.production_reports r ON r.id = w.report_id AND r.tenant_id = w.tenant_id
            WHERE {where} AND r.report_type = 'daily'
            GROUP BY r.team, period, w.category
            """,
            params,
        ).fetchall()
        category_waste_by_key: dict[tuple[str | None, str], dict[str, float]] = {}
        raw_kg_by_key: dict[tuple[str | None, str], float] = {}
        for team, period, category, raw_quantity in category_waste_rows:
            key = (team, period.isoformat())
            category_waste_by_key.setdefault(key, {})[category] = float(raw_quantity)
            raw_kg_by_key[key] = raw_kg_by_key.get(key, 0.0) + float(raw_quantity)

        rows = []
        for (
            team, period, report_count, semolina_quantity, regrind_input_quantity,
            regrind_input_quantity_normalized, regrind_quantity,
            produced_quantity, production_minutes, downtime_minutes,
        ) in totals:
            key = (team, period.isoformat())
            waste_by_category = category_waste_by_key.get(key, {})
            rows.append(
                {
                    "team": team,
                    "period": period.isoformat(),
                    "report_count": int(report_count),
                    "semolina_quantity": float(semolina_quantity),
                    # Native figure, left alone for display.
                    "regrind_input_quantity": float(regrind_input_quantity),
                    # What actually went into the mix — fresh semoule plus any
                    # rebroyat poured back in, restated against semoule's own
                    # unit (regrind_input_quantity_normalized) so material_input
                    # adds like with like — same basis as the yield service.
                    "material_input_quantity": float(semolina_quantity) + float(regrind_input_quantity_normalized),
                    "produced_quantity": float(produced_quantity),
                    "production_minutes": int(production_minutes),
                    "downtime_minutes": int(downtime_minutes),
                    "waste_by_product": waste_by_key.get(key, []),
                    # Semoule déchet by stage, and the net of it once rebroyat is
                    # taken out — what the shift declared as recoverable that
                    # period, not what a regrind batch later actually yielded (see
                    # ScrapService/regrind_service for that separate, slower
                    # figure). This is the écart the plant wants to minimise:
                    # material that is genuinely gone, never coming back into a mix.
                    "daily_waste_by_category": waste_by_category,
                    "regrind_quantity": float(regrind_quantity),
                    "net_semoule_waste": raw_kg_by_key.get(key, 0.0) - float(regrind_quantity),
                }
            )
        return rows

    def list_downtime_reasons(
        self,
        *,
        tenant_id: str,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> list[dict]:
        """Minutes lost per stated reason, from validated reports.

        A daily report can now carry several arrêts (report_downtime_lines,
        one motif each) while a conditionnement report still carries exactly
        one downtime_reason column, so the two are read differently and
        combined with a UNION ALL rather than a single COALESCE the way this
        used to work when both were one column each. `report_count` now counts
        arrêt occurrences rather than distinct reports for the daily side of
        the union -- the whole point of this change is that one report can
        contribute more than one.
        """
        clauses = ["r.tenant_id = %s", "r.status = 'validated'"]
        params: list[object] = [tenant_id]
        if date_from is not None:
            clauses.append("r.report_date >= %s")
            params.append(date_from)
        if date_to is not None:
            clauses.append("r.report_date <= %s")
            params.append(date_to)
        where = " AND ".join(clauses)

        rows = self._connection.execute(
            f"""
            WITH combined AS (
                SELECT dl.motif AS reason, dl.minutes AS minutes
                FROM production.report_downtime_lines dl
                JOIN production.production_reports r ON r.id = dl.report_id AND r.tenant_id = dl.tenant_id
                WHERE {where} AND dl.minutes > 0 AND dl.motif IS NOT NULL
                UNION ALL
                SELECT c.downtime_reason AS reason, c.downtime_minutes AS minutes
                FROM production.conditionnement_reports c
                JOIN production.production_reports r ON r.id = c.report_id AND r.tenant_id = c.tenant_id
                WHERE {where} AND c.downtime_minutes > 0 AND c.downtime_reason IS NOT NULL
            )
            SELECT reason, SUM(minutes) AS minutes, count(*) AS report_count
            FROM combined
            GROUP BY reason
            ORDER BY minutes DESC
            """,
            params + params,
        ).fetchall()
        return [
            {"reason": reason, "minutes": int(minutes), "report_count": int(report_count)}
            for reason, minutes, report_count in rows
        ]

    def list_downtime_breakdown(
        self,
        *,
        tenant_id: str,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> list[dict]:
        """Minutes lost per reason, team and machine, from validated reports.

        Same union as list_downtime_reasons, with the reporting header's own
        team and equipment_id carried onto each row instead of being folded
        away -- this is the full-granularity version a caller re-aggregates
        by whichever dimension it needs (team, machine, or reason alone),
        rather than three separate queries for three separate slices.
        """
        clauses = ["r.tenant_id = %s", "r.status = 'validated'"]
        params: list[object] = [tenant_id]
        if date_from is not None:
            clauses.append("r.report_date >= %s")
            params.append(date_from)
        if date_to is not None:
            clauses.append("r.report_date <= %s")
            params.append(date_to)
        where = " AND ".join(clauses)

        rows = self._connection.execute(
            f"""
            WITH combined AS (
                SELECT dl.motif AS reason, dl.minutes AS minutes, r.team AS team, r.equipment_id AS equipment_id
                FROM production.report_downtime_lines dl
                JOIN production.production_reports r ON r.id = dl.report_id AND r.tenant_id = dl.tenant_id
                WHERE {where} AND dl.minutes > 0 AND dl.motif IS NOT NULL
                UNION ALL
                SELECT c.downtime_reason AS reason, c.downtime_minutes AS minutes, r.team AS team, r.equipment_id AS equipment_id
                FROM production.conditionnement_reports c
                JOIN production.production_reports r ON r.id = c.report_id AND r.tenant_id = c.tenant_id
                WHERE {where} AND c.downtime_minutes > 0 AND c.downtime_reason IS NOT NULL
            )
            SELECT reason, team, equipment_id, SUM(minutes) AS minutes, count(*) AS report_count
            FROM combined
            GROUP BY reason, team, equipment_id
            ORDER BY minutes DESC
            """,
            params + params,
        ).fetchall()
        return [
            {
                "reason": reason,
                "team": team,
                "equipment_id": equipment_id,
                "minutes": int(minutes),
                "report_count": int(report_count),
            }
            for reason, team, equipment_id, minutes, report_count in rows
        ]
