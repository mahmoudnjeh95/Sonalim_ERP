"""One-off data fix: rename the tenant-wide regrind output product (rebroyat --
see production.regrind_defaults, the row with input_product_id IS NULL) from
"Semoule de blé dur" (SKU SEM-DUR-01) to something that cannot be mistaken for
a purchased raw material.

The plant buys several branded semolina products ("Semoule Blé Dur SALEM",
"Semoule Fine SALEM", "Semoule Blé Dur SALEM TN", ...). The regrind output's
old name sat in the same "Semoule ..." family with no visual distinction, even
though it is a different thing entirely: reclaimed, ground scrap that always
lands on this one product regardless of which semolina fed the batch it came
from (see RegrindService.create_regrind_batch). This is confirmed by the user
after seeing the raw-material name show up in the "Rebuts et rebroyat" table
next to rows already marked "Rebroyé".

Paired with scripts/fix_daily_report_scrap_product.py, which repoints the
scrap_records rows a validated daily report already created against a raw
semolina product onto this (renamed) product instead.

Usage:
    DATABASE_URL=... python -m scripts.rename_regrind_output_product --tenant demo
"""

from __future__ import annotations

import argparse

from core.db import get_connection

NEW_NAME = "Rebroyat Semoule"
NEW_SKU = "REBROYAT-SEMOULE"


def run(tenant_id: str) -> None:
    with get_connection() as connection:
        default_row = connection.execute(
            "SELECT output_product_id FROM production.regrind_defaults WHERE tenant_id = %s AND input_product_id IS NULL",
            (tenant_id,),
        ).fetchone()
        if default_row is None:
            raise RuntimeError(f"tenant {tenant_id!r} has no default regrind output product configured")
        output_product_id = default_row[0]

        product = connection.execute(
            "SELECT sku, name FROM core.products WHERE tenant_id = %s AND id = %s",
            (tenant_id, output_product_id),
        ).fetchone()
        if product is None:
            raise RuntimeError(f"regrind output product {output_product_id!r} not found in core.products")
        old_sku, old_name = product

        if old_sku == NEW_SKU and old_name == NEW_NAME:
            print(f"{old_sku} ({old_name}) is already renamed -- nothing to do.")
            connection.rollback()
            return

        connection.execute(
            "UPDATE core.products SET sku = %s, name = %s WHERE tenant_id = %s AND id = %s",
            (NEW_SKU, NEW_NAME, tenant_id, output_product_id),
        )
        connection.commit()

    print(f"Renamed {old_sku} ({old_name}) -> {NEW_SKU} ({NEW_NAME}).")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tenant", default="demo")
    args = parser.parse_args()
    run(args.tenant)


if __name__ == "__main__":
    main()
