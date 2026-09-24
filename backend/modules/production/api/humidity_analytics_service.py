from __future__ import annotations

import psycopg


def list_humidity(
    connection: psycopg.Connection,
    *,
    tenant_id: str,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict]:
    """Dough humidity per validated run, for the Yield & Waste humidity trend.

    Skips runs with no recorded humidity_percentage -- not every run's team
    measures it, and a null is "not measured," never treated as 0.
    """
    clauses = ["s.tenant_id = %s", "s.status = 'validated'", "r.humidity_percentage IS NOT NULL"]
    params: list[object] = [tenant_id]
    if date_from is not None:
        clauses.append("s.report_date >= %s")
        params.append(date_from)
    if date_to is not None:
        clauses.append("s.report_date <= %s")
        params.append(date_to)
    where = " AND ".join(clauses)
    rows = connection.execute(
        f"""
        SELECT s.report_date, s.work_center_id, r.humidity_percentage
        FROM production.shift_runs r
        JOIN production.shift_reports s ON s.id = r.shift_report_id AND s.tenant_id = r.tenant_id
        WHERE {where}
        ORDER BY s.report_date
        """,
        params,
    ).fetchall()
    return [
        {"report_date": report_date.isoformat(), "work_center_id": work_center_id, "humidity_percentage": float(humidity)}
        for report_date, work_center_id, humidity in rows
    ]
