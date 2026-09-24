from __future__ import annotations

import psycopg


def list_validated_report_dates(connection: psycopg.Connection, *, tenant_id: str, date_from: str, date_to: str) -> list[str]:
    """Every distinct date with at least one validated shift in the range. Used to build
    one "CP <date>" sheet per day that actually had production in a week/month recap
    export, instead of a blank sheet for every calendar day regardless of whether the
    plant ran that day."""
    rows = connection.execute(
        """
        SELECT DISTINCT report_date FROM production.shift_reports
        WHERE tenant_id = %s AND status = 'validated' AND report_date BETWEEN %s AND %s
        ORDER BY report_date
        """,
        (tenant_id, date_from, date_to),
    ).fetchall()
    return [d.isoformat() for (d,) in rows]
