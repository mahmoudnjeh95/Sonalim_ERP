from __future__ import annotations

import psycopg

# Same grains as team performance, and the same reasoning: never a fixed enum,
# whatever grain the caller asks for is what date_trunc computes.
GRAINS = ("day", "week", "month", "year")


class MachinePerformanceService:
    """Output, time and downtime, bucketed by machine and by period.

    A work center like Line_1_PL can carry more than one machine running at
    once (see maintenance.equipment); team performance groups by who ran the
    shift, this groups by what they ran it on. Only validated reports count,
    same as team performance -- a draft or rejected report is not a result to
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

        clauses = ["r.tenant_id = %s", "r.status = 'validated'", "r.equipment_id IS NOT NULL"]
        clauses2 = ["r2.tenant_id = %s", "r2.status = 'validated'", "r2.equipment_id IS NOT NULL"]
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

        rows = self._connection.execute(
            f"""
            WITH sem_ratio AS (
                -- Each equipment+period bucket's own semoule unit -- same fix
                -- as team performance's sem_ratio, keyed by equipment_id
                -- instead of team.
                SELECT r2.equipment_id, date_trunc(%s, r2.report_date)::date AS period,
                       CASE WHEN COUNT(DISTINCT u2.ratio_to_base) = 1 THEN MIN(u2.ratio_to_base) END AS ratio_to_base
                FROM production.report_semolina_lines sl2
                JOIN production.production_reports r2 ON r2.id = sl2.report_id AND r2.tenant_id = sl2.tenant_id
                LEFT JOIN core.products p2 ON p2.id = sl2.product_id AND p2.tenant_id = r2.tenant_id
                LEFT JOIN core.uoms u2 ON u2.id = p2.uom_id AND u2.tenant_id = p2.tenant_id
                WHERE {where2}
                GROUP BY r2.equipment_id, period
            ),
            report_periods AS (
                SELECT r.*, date_trunc(%s, r.report_date)::date AS period
                FROM production.production_reports r
                WHERE {where}
            )
            SELECT
                r.equipment_id,
                r.period,
                count(*) AS report_count,
                COALESCE(SUM(sl.total_quantity), 0) AS semolina_quantity,
                -- Restated against this bucket's own semoule unit before it
                -- joins the sum -- same fix as team performance's sem_ratio
                -- join, and for the same reason: the raw figure can be
                -- recorded in a different unit (typically kg) than semoule
                -- (typically tonnes), which used to inflate material_input by
                -- up to 1000x.
                COALESCE(SUM(
                    d.regrind_input_quantity
                    * COALESCE(riu.ratio_to_base, COALESCE(sr.ratio_to_base, 1))
                    / COALESCE(sr.ratio_to_base, 1)
                ), 0) AS regrind_input_quantity_normalized,
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
            LEFT JOIN sem_ratio sr ON sr.equipment_id = r.equipment_id AND sr.period = r.period
            -- Pre-aggregated before joining, same reason as team performance: a
            -- report can carry several semoule lines or arrêts, and joining
            -- either straight in would multiply every other summed column.
            LEFT JOIN (
                SELECT report_id, tenant_id, SUM(quantity) AS total_quantity
                FROM production.report_semolina_lines
                GROUP BY report_id, tenant_id
            ) sl ON sl.report_id = r.id AND sl.tenant_id = r.tenant_id
            LEFT JOIN (
                SELECT report_id, tenant_id, SUM(minutes) AS total_minutes
                FROM production.report_downtime_lines
                GROUP BY report_id, tenant_id
            ) dl ON dl.report_id = r.id AND dl.tenant_id = r.tenant_id
            GROUP BY r.equipment_id, r.period
            ORDER BY r.period
            """,
            params + params,
        ).fetchall()

        return [
            {
                "equipment_id": equipment_id,
                "period": period.isoformat(),
                "report_count": int(report_count),
                "material_input_quantity": float(semolina_quantity) + float(regrind_input_quantity_normalized),
                "produced_quantity": float(produced_quantity),
                "production_minutes": int(production_minutes),
                "downtime_minutes": int(downtime_minutes),
            }
            for (
                equipment_id, period, report_count, semolina_quantity, regrind_input_quantity_normalized,
                produced_quantity, production_minutes, downtime_minutes,
            ) in rows
        ]
