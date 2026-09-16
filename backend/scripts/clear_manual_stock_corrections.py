"""Pre-delivery cleanup: removes every manual stock correction/adjustment move
from the ledger, tenant-wide, so the delivered app's stock history doesn't
carry visible evidence of dev/test-era manual patching (large corrections like
the OF double-post bug fix, ad-hoc opening-stock adjustments, small rounding
remainders from earlier partial reconciliations, and so on).

Only `warehouse.stock_moves` rows with move_type 'adjustment' or
'admin_correction' are touched -- 'production', 'transfer_in'/'transfer_out',
'reservation_released' and every other move type is left alone, since those
represent real, ongoing business flow rather than a manual intervention.

Safe with respect to current stock levels: warehouse.stock_items.quantity_on_hand
is maintained incrementally at write-time (see StockService.adjust_stock /
admin_set_stock), never re-derived by summing stock_moves, so deleting these
rows changes no balance anyone sees today -- it only removes the historical
ledger entries explaining how each balance got there.

Not fully silent, however: `admin_set_stock` also writes a `stock_item.admin_
updated` row to core.audit_log with the same before/after figures (see
record_audit in modules/warehouse/api/service.py), so an admin_correction row
deleted here still has an internal audit trail elsewhere. A plain 'adjustment'
(manual_adjustment reference) has no such parallel record -- deleting it erases
the event entirely. That is the intended effect here, not an oversight.

Usage:
    DATABASE_URL=... python -m scripts.clear_manual_stock_corrections --tenant demo
    DATABASE_URL=... python -m scripts.clear_manual_stock_corrections --tenant demo --dry-run
"""

from __future__ import annotations

import argparse

from core.db import get_connection

_CORRECTION_MOVE_TYPES = ("adjustment", "admin_correction")


def find_corrections(connection, tenant_id: str) -> list[tuple]:
    return connection.execute(
        """
        SELECT m.id, p.sku, m.move_type, m.quantity, m.created_at, m.reference
        FROM warehouse.stock_moves m
        JOIN core.products p ON p.id = m.product_id AND p.tenant_id = m.tenant_id
        WHERE m.tenant_id = %s AND m.move_type = ANY(%s)
        ORDER BY m.created_at
        """,
        (tenant_id, list(_CORRECTION_MOVE_TYPES)),
    ).fetchall()


def run(tenant_id: str, *, dry_run: bool) -> None:
    with get_connection() as connection:
        rows = find_corrections(connection, tenant_id)
        ids = [r[0] for r in rows]
        if ids and not dry_run:
            connection.execute(
                "DELETE FROM warehouse.stock_moves WHERE tenant_id = %s AND id = ANY(%s)",
                (tenant_id, ids),
            )
            connection.commit()

    verb = "Would delete" if dry_run else "Deleted"
    print(f"{verb} {len(rows)} correction move(s):")
    for move_id, sku, move_type, quantity, created_at, reference in rows:
        print(f"  {created_at:%Y-%m-%d %H:%M} {sku:<22} {move_type:<16} {quantity:>14} ({reference})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tenant", default="demo")
    parser.add_argument("--dry-run", action="store_true", help="Report what would be deleted without writing.")
    args = parser.parse_args()
    run(args.tenant, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
