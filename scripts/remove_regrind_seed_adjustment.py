"""One-off data fix: remove the bogus +60,000 kg opening-balance adjustment
seeded against the rebroyat product ("Rebroyat Semoule", formerly "Semoule de
blé dur") at the raw-materials location (reference "manual_adjustment", reason
"demo seed", 2026-09-02). It is the very first stock move this product ever
had and the only thing behind its whole on-hand balance -- confirmed before
running this: quantity_on_hand at that (product, location) is exactly 60000,
so nothing else has touched that row since.

warehouse.stock_items.quantity_on_hand is a stored running balance (see
StockService.receive_stock/adjust_stock in modules/warehouse/api/service.py),
not derived from stock_moves at read time -- deleting the move alone would
leave the balance overstated by 60000. This zeroes it out in the same
transaction.

Usage:
    DATABASE_URL=... python -m scripts.remove_regrind_seed_adjustment --tenant demo
"""

from __future__ import annotations

import argparse

from core.db import get_connection

MOVE_ID = "01M1HEAT2ZXNJMFQVAM1P8FMNF"


def run(tenant_id: str) -> None:
    with get_connection() as connection:
        move = connection.execute(
            "SELECT product_id, location_id, quantity, move_type FROM warehouse.stock_moves WHERE id = %s AND tenant_id = %s",
            (MOVE_ID, tenant_id),
        ).fetchone()
        if move is None:
            print(f"move {MOVE_ID} not found for tenant {tenant_id!r} -- already removed?")
            connection.rollback()
            return
        product_id, location_id, quantity, move_type = move
        if move_type != "adjustment":
            raise RuntimeError(f"move {MOVE_ID} is a {move_type!r}, not an adjustment -- refusing, this script targets one specific row")

        item = connection.execute(
            "SELECT quantity_on_hand FROM warehouse.stock_items WHERE tenant_id = %s AND product_id = %s AND location_id = %s FOR UPDATE",
            (tenant_id, product_id, location_id),
        ).fetchone()
        if item is None:
            raise RuntimeError("stock_items row not found -- nothing to reconcile, refusing to delete the move blind")
        on_hand = item[0]
        if on_hand != quantity:
            raise RuntimeError(
                f"on_hand ({on_hand}) no longer equals this move's own quantity ({quantity}) -- other activity has "
                "touched this row since, so a plain delete would corrupt the balance. Needs manual review."
            )

        connection.execute("DELETE FROM warehouse.stock_moves WHERE id = %s AND tenant_id = %s", (MOVE_ID, tenant_id))
        connection.execute(
            "UPDATE warehouse.stock_items SET quantity_on_hand = 0 WHERE tenant_id = %s AND product_id = %s AND location_id = %s",
            (tenant_id, product_id, location_id),
        )
        connection.commit()

    print(f"Removed move {MOVE_ID} (+{quantity} kg) and reset on-hand to 0 at that location.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tenant", default="demo")
    args = parser.parse_args()
    run(args.tenant)


if __name__ == "__main__":
    main()
