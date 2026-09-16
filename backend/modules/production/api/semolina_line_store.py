from __future__ import annotations

import psycopg
from ulid import ULID

from modules.production.domain.production_report import SemolinaLine

_COLUMNS = "product_id, quantity, location_id, line_order"


def load_semolina_lines(
    connection: psycopg.Connection, *, tenant_id: str, report_id: str
) -> tuple[SemolinaLine, ...]:
    """A report's semoule list, in the order the shift entered it."""
    rows = connection.execute(
        f"""
        SELECT {_COLUMNS} FROM production.report_semolina_lines
        WHERE tenant_id = %s AND report_id = %s
        ORDER BY line_order, id
        """,
        (tenant_id, report_id),
    ).fetchall()
    return tuple(
        SemolinaLine(
            product_id=row[0],
            quantity=float(row[1]),
            location_id=row[2],
            line_order=int(row[3]),
        )
        for row in rows
    )


def replace_semolina_lines(
    connection: psycopg.Connection, *, tenant_id: str, report_id: str, lines: tuple[SemolinaLine, ...]
) -> None:
    """Make the stored list match the one given, wholesale.

    Delete-then-insert, same reasoning as replace_waste_lines: a semoule list is
    a handful of rows written as one edit, and nothing references a line's id.

    Empty lines are dropped on the way in: a form with a blank row poured
    nothing, and storing a zero with no product would put a line with no unit
    into the OF's raw-material total.
    """
    connection.execute(
        "DELETE FROM production.report_semolina_lines WHERE tenant_id = %s AND report_id = %s",
        (tenant_id, report_id),
    )
    for order, line in enumerate(_meaningful(lines)):
        connection.execute(
            f"""
            INSERT INTO production.report_semolina_lines (id, tenant_id, report_id, {_COLUMNS})
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                str(ULID()),
                tenant_id,
                report_id,
                (line.product_id or None),
                line.quantity,
                (line.location_id or None),
                order,
            ),
        )


def delete_semolina_lines(connection: psycopg.Connection, *, tenant_id: str, report_id: str) -> None:
    connection.execute(
        "DELETE FROM production.report_semolina_lines WHERE tenant_id = %s AND report_id = %s",
        (tenant_id, report_id),
    )


def _meaningful(lines: tuple[SemolinaLine, ...]) -> list[SemolinaLine]:
    """Lines that record something: a quantity above zero."""
    return [line for line in lines if line.quantity > 0]
