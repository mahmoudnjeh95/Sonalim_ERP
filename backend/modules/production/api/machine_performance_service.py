from __future__ import annotations

import psycopg

# Same grains as team performance, and the same reasoning: never a fixed enum,
# whatever grain the caller asks for is what date_trunc computes.
GRAINS = ("day", "week", "month", "year")


class MachinePerformanceService:
    """Output, time and downtime, bucketed by machine and by period.

    A work center like Line_1_PL can carry more than one machine running at
    once (see maintenance.equipment); team performance groups by who ran the
    shift, this groups by what they ran it on. Only validated shifts count,
    same as team performance -- a draft or returned shift is not a result to
    hold a machine to.

    Rows come back keyed by the opaque `equipment_id` production stores, not a
    machine name or code: production does not hold a live reference into
    maintenance's schema, so resolving that id to a name is the caller's job
    (see the /work-centers/{id}/machines and /maintenance/equipment
    endpoints), exactly like of_id-style cross-module references elsewhere.
    """

    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def list_machine_performance(
        self,
        *,
        tenant_id: str,
        grain: str,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> list[dict]:
        if grain not in GRAINS:
            raise ValueError(f"grain must be one of {GRAINS}")

        # A run/packing row that names no machine takes the line's own machine at its
        # stage, when the line has exactly one there -- same fallback
        # legacy_report_ledger.materialize_shift used to apply when it faked the old
        # report rows (see pick_stage_machine); resolved here at read time instead,
        # since the shift row itself is never written back with it.
        stage_machine = (
            "(SELECT MIN(eq.id) FROM maintenance.equipment eq WHERE eq.tenant_id = {alias}.tenant_id "
            "AND eq.work_center_id = {wc} AND eq.production_stage = '{stage}' AND eq.archived_at IS NULL "
            "HAVING count(*) = 1)"
        )
        run_equipment = f"COALESCE(r.equipment_id, {stage_machine.format(alias='r', wc='s.work_center_id', stage='extrusion')})"
        run_equipment2 = f"COALESCE(r2.equipment_id, {stage_machine.format(alias='r2', wc='s2.work_center_id', stage='extrusion')})"
        packing_equipment = f"COALESCE(p.equipment_id, {stage_machine.format(alias='p', wc='s.work_center_id', stage='conditionnement')})"

        clauses = ["r.tenant_id = %s", "s.status = 'validated'"]
        clauses2 = ["r2.tenant_id = %s", "s2.status = 'validated'"]
        params: list[object] = [grain, tenant_id]
        if date_from is not None:
            clauses.append("s.report_date >= %s")
            clauses2.append("s2.report_date >= %s")
            params.append(date_from)
        if date_to is not None:
            clauses.append("s.report_date <= %s")
            clauses2.append("s2.report_date <= %s")
            params.append(date_to)
        where = " AND ".join(clauses)
        where2 = " AND ".join(clauses2)

        rows = self._connection.execute(
            f"""
            WITH resolved_runs2 AS (
                SELECT r2.id, r2.tenant_id, {run_equipment2} AS resolved_equipment_id,
                       date_trunc(%s, s2.report_date)::date AS period
                FROM production.shift_runs r2
                JOIN production.shift_reports s2 ON s2.id = r2.shift_report_id AND s2.tenant_id = r2.tenant_id
                WHERE {where2}
            ),
            sem_ratio AS (
                -- Each equipment+period bucket's own semoule unit -- same fix
                -- as team performance's sem_ratio, keyed by equipment_id
                -- instead of team.
                SELECT r2.resolved_equipment_id AS equipment_id, r2.period,
                       CASE WHEN COUNT(DISTINCT u2.ratio_to_base) = 1 THEN MIN(u2.ratio_to_base) END AS ratio_to_base
                FROM production.shift_run_semolina_lines sl2
                JOIN resolved_runs2 r2 ON r2.id = sl2.run_id AND r2.tenant_id = sl2.tenant_id
                LEFT JOIN core.products p2 ON p2.id = sl2.product_id AND p2.tenant_id = r2.tenant_id
                LEFT JOIN core.uoms u2 ON u2.id = p2.uom_id AND u2.tenant_id = p2.tenant_id
                GROUP BY r2.resolved_equipment_id, r2.period
            ),
            run_periods AS (
                SELECT r.*, s.report_date, s.work_center_id, date_trunc(%s, s.report_date)::date AS period,
                       {run_equipment} AS resolved_equipment_id
                FROM production.shift_runs r
                JOIN production.shift_reports s ON s.id = r.shift_report_id AND s.tenant_id = r.tenant_id
                WHERE {where}
            ),
            -- A run and its packing can sit on different machines (extrusion vs.
            -- conditionnement) -- each contributes its own report_count/minutes
            -- bucket, same as the old system's two report rows.
            run_side AS (
                SELECT
                    r.resolved_equipment_id AS equipment_id,
                    r.period,
                    count(*) AS report_count,
                    COALESCE(SUM(sl.total_quantity), 0) AS semolina_quantity,
                    -- Restated against this bucket's own semoule unit before it
                    -- joins the sum -- same fix as team performance's sem_ratio
                    -- join, and for the same reason: the raw figure can be
                    -- recorded in a different unit (typically kg) than semoule
                    -- (typically tonnes), which used to inflate material_input
                    -- by up to 1000x.
                    COALESCE(SUM(
                        r.regrind_input_quantity
                        * COALESCE(riu.ratio_to_base, COALESCE(sr.ratio_to_base, 1))
                        / COALESCE(sr.ratio_to_base, 1)
                    ), 0) AS regrind_input_quantity_normalized,
                    -- The run's own Produit fini -- the tonnage off the scale at
                    -- the press, available before packaging catches up. See
                    -- WorkOrderYieldService for the same choice.
                    COALESCE(SUM(r.finished_product_quantity), 0) AS produced_quantity,
                    COALESCE(SUM(r.production_minutes), 0) AS production_minutes
                FROM run_periods r
                LEFT JOIN core.products rip ON rip.id = r.regrind_input_product_id AND rip.tenant_id = r.tenant_id
                LEFT JOIN core.uoms riu ON riu.id = rip.uom_id AND riu.tenant_id = rip.tenant_id
                LEFT JOIN sem_ratio sr ON sr.equipment_id = r.resolved_equipment_id AND sr.period = r.period
                -- Pre-aggregated before joining, same reason as team
                -- performance: a run can carry several semoule lines, and
                -- joining them straight in would multiply every other summed
                -- column.
                LEFT JOIN (
                    SELECT run_id, tenant_id, SUM(quantity) AS total_quantity
                    FROM production.shift_run_semolina_lines
                    GROUP BY run_id, tenant_id
                ) sl ON sl.run_id = r.id AND sl.tenant_id = r.tenant_id
                WHERE r.resolved_equipment_id IS NOT NULL
                GROUP BY r.resolved_equipment_id, r.period
            ),
            packing_periods AS (
                SELECT p.*, s.report_date, date_trunc(%s, s.report_date)::date AS period,
                       {packing_equipment} AS resolved_equipment_id
                FROM production.shift_packing_rows p
                JOIN production.shift_reports s ON s.id = p.shift_report_id AND s.tenant_id = p.tenant_id
                WHERE p.tenant_id = %s AND s.status = 'validated'
                {"AND s.report_date >= %s" if date_from is not None else ""}
                {"AND s.report_date <= %s" if date_to is not None else ""}
            ),
            packing_side AS (
                SELECT resolved_equipment_id AS equipment_id, period,
                       count(*) AS report_count, 0 AS semolina_quantity, 0 AS regrind_input_quantity_normalized,
                       0 AS produced_quantity, COALESCE(SUM(production_minutes), 0) AS production_minutes
                FROM packing_periods
                WHERE resolved_equipment_id IS NOT NULL
                GROUP BY resolved_equipment_id, period
            )
            SELECT equipment_id, period, report_count, semolina_quantity, regrind_input_quantity_normalized, produced_quantity, production_minutes
            FROM run_side
            UNION ALL
            SELECT equipment_id, period, report_count, semolina_quantity, regrind_input_quantity_normalized, produced_quantity, production_minutes
            FROM packing_side
            ORDER BY period
            """,
            params + params + [grain, tenant_id] + ([date_from] if date_from is not None else []) + ([date_to] if date_to is not None else []),
        ).fetchall()

        merged: dict[tuple[str, object], dict] = {}
        for equipment_id, period, report_count, semolina_quantity, regrind_input_quantity_normalized, produced_quantity, production_minutes in rows:
            key = (equipment_id, period)
            entry = merged.setdefault(key, {
                "equipment_id": equipment_id, "period": period, "report_count": 0,
                "semolina_quantity": 0.0, "regrind_input_quantity_normalized": 0.0,
                "produced_quantity": 0.0, "production_minutes": 0,
            })
            entry["report_count"] += int(report_count)
            entry["semolina_quantity"] += float(semolina_quantity)
            entry["regrind_input_quantity_normalized"] += float(regrind_input_quantity_normalized)
            entry["produced_quantity"] += float(produced_quantity)
            entry["production_minutes"] += int(production_minutes)
        rows = [
            (e["equipment_id"], e["period"], e["report_count"], e["semolina_quantity"],
             e["regrind_input_quantity_normalized"], e["produced_quantity"], e["production_minutes"])
            for e in merged.values()
        ]

        result = {
            (equipment_id, period.isoformat()): {
                "equipment_id": equipment_id,
                "period": period.isoformat(),
                "report_count": int(report_count),
                "material_input_quantity": float(semolina_quantity) + float(regrind_input_quantity_normalized),
                "produced_quantity": float(produced_quantity),
                "production_minutes": int(production_minutes),
                "downtime_minutes": 0,
            }
            for (
                equipment_id, period, report_count, semolina_quantity, regrind_input_quantity_normalized,
                produced_quantity, production_minutes,
            ) in rows
        }

        # Stops of validated shifts, each on the machine that stopped (a stop that names no machine
        # cannot be given one, so it is not attributed). A machine that only stopped, with no report
        # filed under it, still gets its row.
        stop_where, stop_params = ["s.tenant_id = %s", "s.status = 'validated'"], [grain, tenant_id]
        if date_from is not None:
            stop_where.append("s.report_date >= %s")
            stop_params.append(date_from)
        if date_to is not None:
            stop_where.append("s.report_date <= %s")
            stop_params.append(date_to)
        for equipment_id, period, minutes in self._connection.execute(
            f"""
            SELECT ms.equipment_id, date_trunc(%s, s.report_date)::date AS period,
                   SUM(ROUND(EXTRACT(EPOCH FROM (ms.ended_at - ms.started_at)) / 60))
            FROM production.machine_stops ms
            JOIN production.shift_reports s ON s.id = ms.shift_report_id AND s.tenant_id = ms.tenant_id
            WHERE {' AND '.join(stop_where)} AND ms.ended_at IS NOT NULL AND ms.equipment_id IS NOT NULL
            GROUP BY ms.equipment_id, period
            """,
            stop_params,
        ).fetchall():
            key = (equipment_id, period.isoformat())
            row = result.setdefault(
                key,
                {
                    "equipment_id": equipment_id, "period": period.isoformat(), "report_count": 0,
                    "material_input_quantity": 0.0, "produced_quantity": 0.0, "production_minutes": 0, "downtime_minutes": 0,
                },
            )
            row["downtime_minutes"] += int(minutes)
        return sorted(result.values(), key=lambda r: (r["period"], r["equipment_id"]))
