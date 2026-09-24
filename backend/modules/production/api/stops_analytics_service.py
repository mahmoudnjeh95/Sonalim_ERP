from __future__ import annotations

import psycopg


class StopsAnalyticsService:
    """Machine stops of validated shifts, at full detail -- classification, motif,
    and how the stop was captured (live / added after / manual / migrated).

    Unlike MachinePerformanceService (which sums minutes per machine+period for a
    productivity view), this returns one row per stop so the caller can pivot by
    classification, motif, or capture source -- none of which survive an
    aggregate sum. A stop with no equipment_id is still returned (equipment_id
    null), never dropped, so a caller can show it as its own "unattributed"
    figure instead of silently excluding it from every total.
    """

    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def list_stops(
        self,
        *,
        tenant_id: str,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> list[dict]:
        clauses = ["s.tenant_id = %s", "s.status = 'validated'", "ms.ended_at IS NOT NULL"]
        params: list[object] = [tenant_id]
        if date_from is not None:
            clauses.append("s.report_date >= %s")
            params.append(date_from)
        if date_to is not None:
            clauses.append("s.report_date <= %s")
            params.append(date_to)
        where = " AND ".join(clauses)

        rows = self._connection.execute(
            f"""
            SELECT
                ms.equipment_id, s.work_center_id, s.team, s.report_date,
                ms.started_at, ms.ended_at,
                ROUND(EXTRACT(EPOCH FROM (ms.ended_at - ms.started_at)) / 60) AS minutes,
                ms.downtime_type, ms.classification, ms.motif, ms.source
            FROM production.machine_stops ms
            JOIN production.shift_reports s ON s.id = ms.shift_report_id AND s.tenant_id = ms.tenant_id
            WHERE {where}
            ORDER BY ms.started_at
            """,
            params,
        ).fetchall()
        return [
            {
                "equipment_id": equipment_id,
                "work_center_id": work_center_id,
                "team": team,
                "report_date": report_date.isoformat(),
                "started_at": started_at.isoformat(),
                "ended_at": ended_at.isoformat(),
                "minutes": int(minutes),
                "downtime_type": downtime_type,
                "classification": classification,
                "motif": motif,
                "source": source,
            }
            for (
                equipment_id, work_center_id, team, report_date, started_at, ended_at,
                minutes, downtime_type, classification, motif, source,
            ) in rows
        ]
