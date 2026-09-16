from __future__ import annotations

import psycopg
from ulid import ULID

from modules.production.domain.production_report import WasteLine

_COLUMNS = "category, product_id, quantity, note, line_order"


def load_waste_lines(
    connection: psycopg.Connection, *, tenant_id: str, report_id: str
) -> tuple[WasteLine, ...]:
    """A report's déchet list, in the order the shift entered it."""
    rows = connection.execute(
        f"""
        SELECT {_COLUMNS} FROM production.report_waste_lines
        WHERE tenant_id = %s AND report_id = %s
        ORDER BY line_order, category, id
        """,
        (tenant_id, report_id),
    ).fetchall()
    return tuple(
        WasteLine(
            category=row[0],
            product_id=row[1],
            quantity=float(row[2]),
            note=row[3],
            line_order=int(row[4]),
        )
        for row in rows
    )


def replace_waste_lines(
    connection: psycopg.Connection, *, tenant_id: str, report_id: str, lines: tuple[WasteLine, ...]
) -> None:
    """Make the stored list match the one given, wholesale.

    Delete-then-insert rather than a per-line diff, and that is a decision rather
    than laziness. A waste list is a handful of rows written as one edit, and the
    ids are not referenced by anything -- no stock movement, no scrap record, no
    revision points at a line. Diffing would buy stable ids nobody uses and cost a
    matching rule that could quietly drop an edit.

    Empty lines are dropped on the way in: a form with three blank rows has
    recorded no waste, and storing zeroes with no product would put lines with no
    unit into the OF's consolidation.
    """
    connection.execute(
        "DELETE FROM production.report_waste_lines WHERE tenant_id = %s AND report_id = %s",
        (tenant_id, report_id),
    )
    for order, line in enumerate(_meaningful(lines)):
        connection.execute(
            f"""
            INSERT INTO production.report_waste_lines (id, tenant_id, report_id, {_COLUMNS})
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                str(ULID()),
                tenant_id,
                report_id,
                line.category,
                (line.product_id or None),
                line.quantity,
                (line.note or None),
                order,
            ),
        )


def delete_waste_lines(connection: psycopg.Connection, *, tenant_id: str, report_id: str) -> None:
    connection.execute(
        "DELETE FROM production.report_waste_lines WHERE tenant_id = %s AND report_id = %s",
        (tenant_id, report_id),
    )


def _meaningful(lines: tuple[WasteLine, ...]) -> list[WasteLine]:
    """Lines that record something: a quantity, or a note explaining a zero."""
    return [line for line in lines if line.quantity > 0 or (line.note or "").strip()]
