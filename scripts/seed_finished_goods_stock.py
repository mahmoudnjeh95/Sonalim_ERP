"""Ensures every sellable (finished-goods) product has a stock row in the
"Entrepôt Produits Finis" warehouse location, at 0 if it isn't tracked yet.

The Produits > Liste screen (Vendables tab) lists every product with
is_sellable = true -- these are the finished pasta SKUs, as opposed to raw
materials/packaging/consumables which are purchasable but not sellable. Many
of them had no warehouse.stock_items row at all, so they were invisible in
the Entrepôt > Produits Finis view even at zero. This creates the missing
rows; it never touches a row that already exists, so real stock levels are
left untouched.

Usage:
    DATABASE_URL=... python -m scripts.seed_finished_goods_stock --tenant demo
"""

from __future__ import annotations

import argparse

from core.db import get_connection

FINISHED_GOODS_LOCATION_CODE = "produits-finis"


def seed_finished_goods_stock(connection, tenant_id: str) -> list[str]:
    location_row = connection.execute(
        "SELECT id FROM warehouse.locations WHERE tenant_id = %s AND code = %s",
        (tenant_id, FINISHED_GOODS_LOCATION_CODE),
    ).fetchone()
    if location_row is None:
        raise RuntimeError(
            f"tenant {tenant_id!r} has no {FINISHED_GOODS_LOCATION_CODE!r} warehouse location — "
            "run scripts.fix_product_classifications first"
        )
    location_id = location_row[0]

    products = connection.execute(
        "SELECT id, sku FROM core.products WHERE tenant_id = %s AND is_sellable = TRUE ORDER BY sku",
        (tenant_id,),
    ).fetchall()

    created: list[str] = []
    for product_id, sku in products:
        cursor = connection.execute(
            """
            INSERT INTO warehouse.stock_items (tenant_id, location_id, product_id, quantity_on_hand, quantity_reserved)
            VALUES (%s, %s, %s, 0, 0)
            ON CONFLICT (tenant_id, location_id, product_id) DO NOTHING
            """,
            (tenant_id, location_id, product_id),
        )
        if cursor.rowcount:
            created.append(sku)
    return created


def run(tenant_id: str) -> None:
    with get_connection() as connection:
        created = seed_finished_goods_stock(connection, tenant_id)
        connection.commit()

    if created:
        for sku in created:
            print(f"  added to {FINISHED_GOODS_LOCATION_CODE} at 0: {sku}")
    print(f"Added {len(created)} product(s) to '{FINISHED_GOODS_LOCATION_CODE}' at 0 stock.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tenant", default="demo")
    args = parser.parse_args()
    run(args.tenant)


if __name__ == "__main__":
    main()
