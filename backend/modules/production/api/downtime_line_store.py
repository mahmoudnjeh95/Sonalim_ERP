from __future__ import annotations

import psycopg
from ulid import ULID

from modules.production.domain.production_report import DowntimeLine

_COLUMNS = "motif, downtime_type, classification, minutes, note, line_order"


def load_downtime_lines(
    connection: psycopg.Connection, *, tenant_id: str, report_id: str
) -> tuple[DowntimeLine, ...]:
    """A report's arrêt list, in the order the shift entered it."""
    rows = connection.execute(
        f"""
        SELECT {_COLUMNS} FROM production.report_downtime_lines
        WHERE tenant_id = %s AND report_id = %s
        ORDER BY line_order, id
        """,
        (tenant_id, report_id),
    ).fetchall()
    return tuple(
        DowntimeLine(
            motif=row[0],
            downtime_type=row[1],
            classification=row[2],
            minutes=int(row[3]),
            note=row[4],
            line_order=int(row[5]),
        )
        for row in rows
    )


def replace_downtime_lines(
    connection: psycopg.Connection, *, tenant_id: str, report_id: str, lines: tuple[DowntimeLine, ...]
) -> None:
    """Make the stored list match the one given, wholesale.

    Delete-then-insert, same reasoning as replace_waste_lines: an arrêt list is
    a handful of rows written as one edit, and nothing references a line's id.

    Empty lines are dropped on the way in: a form with a blank row recorded no
    stoppage, and storing a zero with no motif would put an arrêt with no cause
    into the report.
    """
    connection.execute(
        "DELETE FROM production.report_downtime_lines WHERE tenant_id = %s AND report_id = %s",
        (tenant_id, report_id),
    )
    for order, line in enumerate(_meaningful(lines)):
        connection.execute(
            f"""
            INSERT INTO production.report_downtime_lines (id, tenant_id, report_id, {_COLUMNS})
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                str(ULID()),
                tenant_id,
                report_id,
                (line.motif or None),
                (line.downtime_type or None),
                (line.classification or None),
                line.minutes,
                (line.note or None),
                order,
            ),
        )


def delete_downtime_lines(connection: psycopg.Connection, *, tenant_id: str, report_id: str) -> None:
    connection.execute(
        "DELETE FROM production.report_downtime_lines WHERE tenant_id = %s AND report_id = %s",
        (tenant_id, report_id),
    )


def _meaningful(lines: tuple[DowntimeLine, ...]) -> list[DowntimeLine]:
    """Lines that record something: minutes above zero, or a note explaining one."""
    return [line for line in lines if line.minutes > 0 or (line.note or "").strip()]
