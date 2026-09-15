"""One-off cleanup: 8 orphaned stock_moves rows left over from a demo dataset
that was wiped when the current work-order dataset was seeded on 2026-09-02.

Found while investigating garbage in Entrepot > Analyse Produits Finis (fractional
"paquets" on the earliest dates -- 0.75, 1.32, 1 046.2 -- and an inflated lifetime
total). Every one of these rows' `reference` names a `work_order:<id>` that no
longer exists in production.work_orders -- every work order currently in the
database was created on or after 2026-09-02 17:13, so these six 'production'
moves (Aug 24-27) and the matched 'rebalnce' transfer_in/transfer_out pair
predate the real dataset entirely and have no report or OF left to audit them
against.

Safe to delete, verified two ways before writing this script:
1. warehouse.stock_items.quantity_on_hand is maintained incrementally by
   StockService (read-modify-write on post), never re-derived by summing
   stock_moves -- so removing old rows from the ledger does not change any
   current balance.
2. The three affected finished goods (doman-pl-500g, doman-pc-500g,
   doman-pc-4540g-sac) were all independently reset to physically-verified
   counts via admin_set_stock on 2026-09-14 09:41 (the OF double-post bug
   fix), which already absorbed whatever these rows had contributed.

This only removes the 8 specific rows below -- it does not generically sweep
"any move referencing a missing work order", since a work order could in
principle be deleted for other reasons in normal operation and this script has
no business touching that. Each row's product/type/quantity is re-verified
before deletion; if any has changed since this script was written, it is
skipped and reported rather than deleted.

Usage:
    DATABASE_URL=... python -m scripts.remove_orphaned_pre_reset_stock_moves --tenant demo
    DATABASE_URL=... python -m scripts.remove_orphaned_pre_reset_stock_moves --tenant demo --dry-run
"""

from __future__ import annotations

import argparse

from core.db import get_connection

# (move id, expected sku, expected move_type, expected quantity) -- the exact
# rows identified during investigation, so a mismatch means the data has moved
# on since and this script should refuse rather than guess.
_ORPHANED_MOVES: tuple[tuple[str, str, str, str], ...] = (
    ("01M0TW9D0510VS38PWBHYQ5Z3C", "doman-pc-500g", "production", "0.75"),
    ("01M0V1XVX69SQE9FS6RF2DCEBN", "doman-pc-500g", "production", "0.09"),
    ("01M0V8EQZS1XTQ59BQVKBS4AWB", "doman-pc-500g", "production", "0.75"),
    ("01M0VABENPT8MC1X9DGCAG4WD2", "doman-pc-500g", "production", "0.48"),
    ("01M0Y4NVMN38N7EQ7WDHGEP2GD", "doman-pl-500g", "production", "1046.2"),
    ("01M10C55KTS0KEK0W5G3DQVT69", "doman-pc-4540g-sac", "production", "1000.2"),
    ("01M0ZN52PM3VV82F4QM3JW2XT2", "doman-pc-500g", "transfer_out", "1.48"),
    ("01M0ZN52PMTRAHTA7FGMGZWPXA", "doman-pc-500g", "transfer_in", "1.48"),
)


def find_deletable(connection, tenant_id: str) -> tuple[list[str], list[str]]:
    """Re-verifies each row against the ledger before it is allowed to be deleted.

    Returns (deletable_ids, skipped_descriptions).
    """
    deletable: list[str] = []
    skipped: list[str] = []
    for move_id, expected_sku, expected_type, expected_quantity in _ORPHANED_MOVES:
        row = connection.execute(
            """
            SELECT p.sku, m.move_type, m.quantity, m.reference
            FROM warehouse.stock_moves m
            JOIN core.products p ON p.id = m.product_id AND p.tenant_id = m.tenant_id
            WHERE m.id = %s AND m.tenant_id = %s
            """,
            (move_id, tenant_id),
        ).fetchone()
        if row is None:
            skipped.append(f"{move_id}: no longer exists (already cleaned up?)")
            continue
        sku, move_type, quantity, reference = row
        if sku != expected_sku or move_type != expected_type or f"{quantity:g}" != f"{float(expected_quantity):g}":
            skipped.append(
                f"{move_id}: does not match expected ({expected_sku}/{expected_type}/{expected_quantity}) "
                f"-- found ({sku}/{move_type}/{quantity})"
            )
            continue
        of_id = reference.removeprefix("work_order:") if reference and reference.startswith("work_order:") else None
        if of_id is not None:
            wo = connection.execute(
                "SELECT 1 FROM production.work_orders WHERE id = %s AND tenant_id = %s", (of_id, tenant_id)
            ).fetchone()
            if wo is not None:
                skipped.append(f"{move_id}: its work order {of_id} exists again -- not orphaned, leaving it alone")
                continue
        deletable.append(move_id)
    return deletable, skipped


def run(tenant_id: str, *, dry_run: bool) -> None:
    with get_connection() as connection:
        deletable, skipped = find_deletable(connection, tenant_id)
        if deletable and not dry_run:
            connection.execute(
                "DELETE FROM warehouse.stock_moves WHERE tenant_id = %s AND id = ANY(%s)",
                (tenant_id, deletable),
            )
            connection.commit()

    verb = "would delete" if dry_run else "deleted"
    print(f"{verb.capitalize()} {len(deletable)} orphaned stock move(s):")
    for move_id in deletable:
        print(f"  {move_id}")
    if skipped:
        print(f"Skipped {len(skipped)} row(s):")
        for line in skipped:
            print(f"  {line}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tenant", default="demo")
    parser.add_argument("--dry-run", action="store_true", help="Report what would be deleted without writing.")
    args = parser.parse_args()
    run(args.tenant, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
