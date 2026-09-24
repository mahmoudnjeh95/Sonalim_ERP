"""The finished product a packing report is about.

A packing report names its own product because one work order can pack several (a PC mold
change starts a new product on the same order). An old report that names none falls back to its
work order's product. Everything that posts stock or judges a packaging variance asks here
instead of reading `work_orders.product_id` directly.
"""
from __future__ import annotations

import psycopg


def finished_product_of_report(connection: psycopg.Connection, *, tenant_id: str, report_id: str) -> str | None:
    row = connection.execute(
        """
        SELECT COALESCE(c.product_id, w.product_id)
        FROM production.production_reports r
        JOIN production.work_orders w ON w.id = r.of_id AND w.tenant_id = r.tenant_id
        LEFT JOIN production.conditionnement_reports c ON c.report_id = r.id AND c.tenant_id = r.tenant_id
        WHERE r.id = %s AND r.tenant_id = %s
        """,
        (report_id, tenant_id),
    ).fetchone()
    return row[0] if row else None


def finished_products_of_reports(
    connection: psycopg.Connection, *, tenant_id: str, report_ids: list[str]
) -> dict[str, str | None]:
    """Batch form of finished_product_of_report, for callers listing many reports at once."""
    if not report_ids:
        return {}
    rows = connection.execute(
        """
        SELECT r.id, COALESCE(c.product_id, w.product_id)
        FROM production.production_reports r
        JOIN production.work_orders w ON w.id = r.of_id AND w.tenant_id = r.tenant_id
        LEFT JOIN production.conditionnement_reports c ON c.report_id = r.id AND c.tenant_id = r.tenant_id
        WHERE r.tenant_id = %s AND r.id = ANY(%s)
        """,
        (tenant_id, report_ids),
    ).fetchall()
    return {row[0]: row[1] for row in rows}


def packing_row_packets_per_carton(
    connection: psycopg.Connection, *, tenant_id: str, shift_packing_row_ids: list[str]
) -> dict[str, tuple[float | None, str | None]]:
    """Each packing row's own frozen packets-per-carton snapshot and its current product, for a
    caller converting a carton count against that row to pieces without re-reading the product's
    current (possibly since-changed) setting. A packets-per-carton of None means no carton tier (a
    sac), counted one by one. A row id missing from the result no longer exists, or belongs to a
    shift that is no longer validated (reversed and awaiting correction); a product that differs
    from the caller's copy means the row was corrected since the caller looked at it."""
    if not shift_packing_row_ids:
        return {}
    rows = connection.execute(
        "SELECT p.id, p.snapshot_packets_per_carton, p.product_id FROM production.shift_packing_rows p "
        "JOIN production.shift_reports s ON s.id = p.shift_report_id AND s.tenant_id = p.tenant_id "
        "WHERE p.tenant_id = %s AND p.id = ANY(%s) AND s.status = 'validated'",
        (tenant_id, shift_packing_row_ids),
    ).fetchall()
    return {
        row_id: (float(per_carton) if per_carton else None, product_id)
        for row_id, per_carton, product_id in rows
    }


def stamp_order_products(connection: psycopg.Connection, *, tenant_id: str, shift_report_id: str) -> None:
    """An order with no product yet takes the product of its first packing row in this shift.

    Set only when empty and never changed afterwards: the order's own product is the "primary"
    one for readers that still need exactly one. The products it really packed are the rows'.
    """
    connection.execute(
        """
        UPDATE production.work_orders w
        SET product_id = first_row.product_id
        FROM (
            SELECT DISTINCT ON (p.of_id) p.of_id, p.product_id
            FROM production.shift_packing_rows p
            WHERE p.tenant_id = %s AND p.shift_report_id = %s AND p.product_id IS NOT NULL
            ORDER BY p.of_id, p.line_order, p.id
        ) first_row
        WHERE w.id = first_row.of_id AND w.tenant_id = %s AND w.product_id IS NULL
        """,
        (tenant_id, shift_report_id, tenant_id),
    )
