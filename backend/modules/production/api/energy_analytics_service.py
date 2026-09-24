from __future__ import annotations

import psycopg


def _figure(value) -> float | None:
    """A recorded figure; a blank field stays None -- "not recorded" is not zero."""
    return float(value) if value is not None else None


class EnergyAnalyticsService:
    """Fuel, gasoil, generator and electricity, one row per validated shift.

    shift_energy is typed once per shift (not per run), so this stays at the
    shift grain -- no per-run/per-product energy split exists to read.
    produced_quantity is joined in from the shift's own runs (same basis
    TeamPerformanceService uses for produced_quantity) so a caller can divide
    without a second request, but the two figures are read from the same
    shift_report_id in one query, so they can never drift out of the same window.
    """

    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def list_energy(
        self,
        *,
        tenant_id: str,
        date_from: str | None = None,
        date_to: str | None = None,
        work_center_id: str | None = None,
    ) -> list[dict]:
        clauses = ["s.tenant_id = %s", "s.status = 'validated'"]
        params: list[object] = [tenant_id]
        if date_from is not None:
            clauses.append("s.report_date >= %s")
            params.append(date_from)
        if date_to is not None:
            clauses.append("s.report_date <= %s")
            params.append(date_to)
        if work_center_id is not None:
            clauses.append("s.work_center_id = %s")
            params.append(work_center_id)
        where = " AND ".join(clauses)

        rows = self._connection.execute(
            f"""
            SELECT
                s.report_date, s.work_center_id, s.team,
                e.fuel_quantity, e.gasoil_quantity, e.gasoil_flow_rate, e.generator_hours, e.electricity_quantity,
                COALESCE(r.produced_quantity, 0) AS produced_quantity
            FROM production.shift_energy e
            JOIN production.shift_reports s ON s.id = e.shift_report_id AND s.tenant_id = e.tenant_id
            LEFT JOIN (
                SELECT shift_report_id, SUM(finished_product_quantity) AS produced_quantity
                FROM production.shift_runs
                WHERE tenant_id = %s
                GROUP BY shift_report_id
            ) r ON r.shift_report_id = s.id
            WHERE {where}
            ORDER BY s.report_date
            """,
            [tenant_id, *params],
        ).fetchall()
        return [
            {
                "report_date": report_date.isoformat(),
                "work_center_id": work_center_id,
                "team": team,
                "fuel_quantity": _figure(fuel_quantity),
                "gasoil_quantity": _figure(gasoil_quantity),
                "gasoil_flow_rate": _figure(gasoil_flow_rate),
                "generator_hours": _figure(generator_hours),
                "electricity_quantity": _figure(electricity_quantity),
                "produced_quantity": float(produced_quantity),
            }
            for (
                report_date, work_center_id, team, fuel_quantity, gasoil_quantity,
                gasoil_flow_rate, generator_hours, electricity_quantity, produced_quantity,
            ) in rows
        ]
