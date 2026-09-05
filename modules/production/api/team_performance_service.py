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
        params: list[object] = [grain, tenant_id]
        if date_from is not None:
            clauses.append("r.report_date >= %s")
            params.append(date_from)
        if date_to is not None:
            clauses.append("r.report_date <= %s")
            params.append(date_to)
        where = " AND ".join(clauses)

        totals = self._connection.execute(
            f"""
            SELECT
                r.team,
                date_trunc(%s, r.report_date)::date AS period,
                count(*) AS report_count,
                COALESCE(SUM(sl.total_quantity), 0) AS semolina_quantity,
                COALESCE(SUM(d.regrind_input_quantity), 0) AS regrind_input_quantity,
                COALESCE(SUM(c.finished_product_quantity), 0) AS produced_quantity,
                COALESCE(SUM(d.production_minutes), 0) + COALESCE(SUM(c.production_minutes), 0) AS production_minutes,
                COALESCE(SUM(d.downtime_minutes), 0) + COALESCE(SUM(c.downtime_minutes), 0) AS downtime_minutes
            FROM production.production_reports r
            LEFT JOIN production.daily_reports d
                   ON d.report_id = r.id AND d.tenant_id = r.tenant_id
            LEFT JOIN production.conditionnement_reports c
                   ON c.report_id = r.id AND c.tenant_id = r.tenant_id
            -- Pre-aggregated per report before joining, same reason as the
            -- yield service: a report can carry several semoule lines, and
            -- joining that many-rows table straight in would multiply every
            -- other summed column by the line count.
            LEFT JOIN (
                SELECT report_id, tenant_id, SUM(quantity) AS total_quantity
                FROM production.report_semolina_lines
                GROUP BY report_id, tenant_id
            ) sl ON sl.report_id = r.id AND sl.tenant_id = r.tenant_id
            WHERE {where}
            GROUP BY r.team, period
            """,
            params,
        ).fetchall()

        waste_rows = self._connection.execute(
            f"""
            SELECT r.team, date_trunc(%s, r.report_date)::date AS period, w.product_id, COALESCE(SUM(w.quantity), 0)
            FROM production.report_waste_lines w
            JOIN production.production_reports r ON r.id = w.report_id AND r.tenant_id = w.tenant_id
            WHERE {where} AND w.product_id IS NOT NULL
            GROUP BY r.team, period, w.product_id
            """,
            params,
        ).fetchall()
        waste_by_key: dict[tuple[str | None, str], list[dict]] = {}
        for team, period, product_id, quantity in waste_rows:
            key = (team, period.isoformat())
            waste_by_key.setdefault(key, []).append({"product_id": product_id, "quantity": float(quantity)})

        return [
            {
                "team": team,
                "period": period.isoformat(),
                "report_count": int(report_count),
                "semolina_quantity": float(semolina_quantity),
                "regrind_input_quantity": float(regrind_input_quantity),
                # What actually went into the mix — fresh semoule plus any
                # rebroyat poured back in, same basis as the yield service.
                "material_input_quantity": float(semolina_quantity) + float(regrind_input_quantity),
                "produced_quantity": float(produced_quantity),
                "production_minutes": int(production_minutes),
                "downtime_minutes": int(downtime_minutes),
                "waste_by_product": waste_by_key.get((team, period.isoformat()), []),
            }
            for team, period, report_count, semolina_quantity, regrind_input_quantity, produced_quantity, production_minutes, downtime_minutes in totals
        ]

    def list_downtime_reasons(
        self,
        *,
        tenant_id: str,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> list[dict]:
        """Minutes lost per stated reason, from validated reports.

        A daily and a conditionnement report each carry their own free-text
        `downtime_reason` column, so the two are coalesced here the same way
        their minutes are summed elsewhere in this class — a report is one
        type or the other, never both, so this never double-counts.
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
            SELECT
                COALESCE(d.downtime_reason, c.downtime_reason) AS reason,
                COALESCE(SUM(d.downtime_minutes), 0) + COALESCE(SUM(c.downtime_minutes), 0) AS minutes,
                count(*) AS report_count
            FROM production.production_reports r
            LEFT JOIN production.daily_reports d
                   ON d.report_id = r.id AND d.tenant_id = r.tenant_id
            LEFT JOIN production.conditionnement_reports c
                   ON c.report_id = r.id AND c.tenant_id = r.tenant_id
            WHERE {where}
              AND (d.downtime_minutes > 0 OR c.downtime_minutes > 0)
              AND COALESCE(d.downtime_reason, c.downtime_reason) IS NOT NULL
            GROUP BY COALESCE(d.downtime_reason, c.downtime_reason)
            ORDER BY minutes DESC
            """,
            params,
        ).fetchall()
        return [
            {"reason": reason, "minutes": int(minutes), "report_count": int(report_count)}
            for reason, minutes, report_count in rows
        ]
