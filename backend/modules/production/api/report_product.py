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
