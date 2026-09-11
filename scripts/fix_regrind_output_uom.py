"""One-off data fix: the tenant-wide regrind output product (rebroyat -- see
production.regrind_defaults, the row with input_product_id IS NULL) is registered
with the "ea" (pièce) unit of measure instead of "kg".

Rebroyat is reclaimed semolina weighed on a scale, not a countable item.
scripts/audit_uom_quantity_integrity.py section 1 already flags the symptom --
this product's stock_items and stock_moves carry fractional "ea" quantities
(e.g. on_hand=0.49 "ea") -- and the "Terminer le lot de rebroyat" dialog showed
its quantity in "pièce" instead of "kg".

This repoints the product at the tenant's "kg" UOM. The numbers already on its
stock_items/stock_moves rows are left untouched -- they were always kilograms,
just mislabelled.

Usage:
    DATABASE_URL=... python -m scripts.fix_regrind_output_uom --tenant demo
"""

from __future__ import annotations

import argparse

from core.db import get_connection


def run(tenant_id: str) -> None:
    with get_connection() as connection:
        default_row = connection.execute(
            "SELECT output_product_id FROM production.regrind_defaults WHERE tenant_id = %s AND input_product_id IS NULL",
            (tenant_id,),
        ).fetchone()
        if default_row is None:
            raise RuntimeError(f"tenant {tenant_id!r} has no default regrind output product configured")
        output_product_id = default_row[0]

        kg_uom = connection.execute(
            "SELECT id FROM core.uoms WHERE tenant_id = %s AND code = 'kg'", (tenant_id,)
        ).fetchone()
        if kg_uom is None:
            raise RuntimeError(f"tenant {tenant_id!r} has no 'kg' unit of measure -- run scripts.seed_dev first")
        kg_uom_id = kg_uom[0]

        product = connection.execute(
            "SELECT sku, name, uom_id FROM core.products WHERE tenant_id = %s AND id = %s",
            (tenant_id, output_product_id),
        ).fetchone()
        if product is None:
            raise RuntimeError(f"regrind output product {output_product_id!r} not found in core.products")
        sku, name, current_uom_id = product

        if current_uom_id == kg_uom_id:
            print(f"{sku} ({name}) is already tracked in kg -- nothing to do.")
            connection.rollback()
            return

        connection.execute(
            "UPDATE core.products SET uom_id = %s WHERE tenant_id = %s AND id = %s",
            (kg_uom_id, tenant_id, output_product_id),
        )
        connection.commit()

    print(f"Repointed {sku} ({name}) from its previous UOM to kg.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tenant", default="demo")
    args = parser.parse_args()
    run(args.tenant)


if __name__ == "__main__":
    main()
