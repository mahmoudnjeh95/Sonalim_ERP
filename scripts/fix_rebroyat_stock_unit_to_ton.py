"""One-off data fix: switch the tenant's rebroyat product (production.regrind_defaults,
the row with input_product_id IS NULL -- see scripts/fix_regrind_output_uom.py, which
put it in "kg" on 2026-09-10) to "ton" instead.

The plant wants rebroyat always kept in stock by the tonne, matching every other
semoule product (all "ton", ratio_to_base=1000) instead of being the one raw
material still tracked in kg. Unlike the ea -> kg fix, kg -> ton is NOT a
same-scale relabelling (ratio_to_base 1 -> 1000): every number already on record
that is denominated in the product's own unit has to be divided by 1000 (kg -> t)
or it will silently read as 1000x too large the moment the product's uom_id
changes -- the exact bug class scripts/fix_regrind_batch_scale*.py and the
of_consolidation_service.py anchor fix already fought, just in the other
direction this time.

Tables touched, all scoped to this one product id (or work orders/batches whose
output is this product -- every regrind batch resolves to the same tenant-wide
rebroyat product, see RegrindService.create_regrind_batch):
  - warehouse.stock_items (quantity_on_hand, quantity_reserved, quantity_in_production)
  - warehouse.stock_moves (quantity) -- the historical ledger
  - production.work_orders (planned_quantity) -- every "OFR-" regrind order
  - production.regrind_batches (input_quantity_total, actual_output_quantity)
  - production.scrap_records (quantity) -- _record_regrind_scrap always books
    rebroyat scrap against this same product, regardless of what the report's
    regrind_product_id says (see production_report_service.py's
    _record_regrind_scrap docstring)
  - production.daily_reports.regrind_quantity -- same reason: the field is
    always entered in rebroyat's own unit and always becomes scrap against this
    product, whatever regrind_product_id happens to say (kept as an
    informational tag only)
  - production.daily_reports.regrind_input_quantity -- only rows whose
    regrind_input_product_id is actually this product; a handful of older
    reports name a different (non-rebroyat) product there and are correctly
    left alone
  - core.products.stock_alert_threshold on the product itself, if set

core.products.uom_id is repointed last, after every number anchored to it has
already been rescaled.

Usage:
    DATABASE_URL=... python -m scripts.fix_rebroyat_stock_unit_to_ton --tenant demo
    DATABASE_URL=... python -m scripts.fix_rebroyat_stock_unit_to_ton --tenant demo --dry-run
"""

from __future__ import annotations

import argparse

from core.db import get_connection


def run(tenant_id: str, dry_run: bool) -> None:
    with get_connection() as connection:
        default_row = connection.execute(
            "SELECT output_product_id FROM production.regrind_defaults WHERE tenant_id = %s AND input_product_id IS NULL",
            (tenant_id,),
        ).fetchone()
        if default_row is None:
            raise RuntimeError(f"tenant {tenant_id!r} has no default regrind output product configured")
        rebroyat_id = default_row[0]

        product = connection.execute(
            "SELECT sku, name, uom_id FROM core.products WHERE tenant_id = %s AND id = %s",
            (tenant_id, rebroyat_id),
        ).fetchone()
        if product is None:
            raise RuntimeError(f"regrind output product {rebroyat_id!r} not found in core.products")
        sku, name, current_uom_id = product

        current_uom = connection.execute(
            "SELECT code, ratio_to_base FROM core.uoms WHERE tenant_id = %s AND id = %s", (tenant_id, current_uom_id)
        ).fetchone()
        current_code, current_ratio = current_uom[0], float(current_uom[1])

        ton_uom = connection.execute(
            "SELECT id, ratio_to_base FROM core.uoms WHERE tenant_id = %s AND code = 'ton'", (tenant_id,)
        ).fetchone()
        if ton_uom is None:
            raise RuntimeError(f"tenant {tenant_id!r} has no 'ton' unit of measure -- run scripts.seed_sonalim_products first")
        ton_uom_id, ton_ratio = ton_uom[0], float(ton_uom[1])

        if current_uom_id == ton_uom_id:
            print(f"{sku} ({name}) is already tracked in ton -- nothing to do.")
            connection.rollback()
            return

        # old_value (in current_code) * current_ratio / ton_ratio = new_value (in ton)
        factor = current_ratio / ton_ratio
        print(f"{sku} ({name}): {current_code} (ratio {current_ratio:g}) -> ton (ratio {ton_ratio:g}), factor {factor:g}")

        def scale(label: str, sql: str, params: tuple) -> None:
            row = connection.execute(sql, params).fetchone()
            count = row[0] if row else 0
            print(f"  {label}: {count} row(s) rescaled")

        scale(
            "warehouse.stock_items",
            """
            WITH updated AS (
                UPDATE warehouse.stock_items
                SET quantity_on_hand = quantity_on_hand * %s,
                    quantity_reserved = quantity_reserved * %s,
                    quantity_in_production = quantity_in_production * %s
                WHERE tenant_id = %s AND product_id = %s
                RETURNING 1
            )
            SELECT count(*) FROM updated
            """,
            (factor, factor, factor, tenant_id, rebroyat_id),
        )

        scale(
            "warehouse.stock_moves",
            """
            WITH updated AS (
                UPDATE warehouse.stock_moves
                SET quantity = quantity * %s
                WHERE tenant_id = %s AND product_id = %s
                RETURNING 1
            )
            SELECT count(*) FROM updated
            """,
            (factor, tenant_id, rebroyat_id),
        )

        scale(
            "production.work_orders.planned_quantity (regrind orders)",
            """
            WITH updated AS (
                UPDATE production.work_orders
                SET planned_quantity = planned_quantity * %s
                WHERE tenant_id = %s AND product_id = %s
                RETURNING 1
            )
            SELECT count(*) FROM updated
            """,
            (factor, tenant_id, rebroyat_id),
        )

        scale(
            "production.regrind_batches",
            """
            WITH updated AS (
                UPDATE production.regrind_batches rb
                SET input_quantity_total = rb.input_quantity_total * %s,
                    actual_output_quantity = CASE
                        WHEN rb.actual_output_quantity IS NULL THEN NULL
                        ELSE rb.actual_output_quantity * %s
                    END
                FROM production.work_orders wo
                WHERE wo.id = rb.work_order_id AND wo.tenant_id = %s AND wo.product_id = %s
                RETURNING 1
            )
            SELECT count(*) FROM updated
            """,
            (factor, factor, tenant_id, rebroyat_id),
        )

        scale(
            "production.scrap_records",
            """
            WITH updated AS (
                UPDATE production.scrap_records
                SET quantity = quantity * %s
                WHERE tenant_id = %s AND product_id = %s
                RETURNING 1
            )
            SELECT count(*) FROM updated
            """,
            (factor, tenant_id, rebroyat_id),
        )

        scale(
            "production.daily_reports.regrind_quantity",
            """
            WITH updated AS (
                UPDATE production.daily_reports
                SET regrind_quantity = regrind_quantity * %s
                WHERE tenant_id = %s AND regrind_quantity <> 0
                RETURNING 1
            )
            SELECT count(*) FROM updated
            """,
            (factor, tenant_id),
        )

        scale(
            "production.daily_reports.regrind_input_quantity",
            """
            WITH updated AS (
                UPDATE production.daily_reports
                SET regrind_input_quantity = regrind_input_quantity * %s
                WHERE tenant_id = %s AND regrind_input_product_id = %s
                RETURNING 1
            )
            SELECT count(*) FROM updated
            """,
            (factor, tenant_id, rebroyat_id),
        )

        connection.execute(
            """
            UPDATE core.products
            SET stock_alert_threshold = stock_alert_threshold * %s
            WHERE tenant_id = %s AND id = %s AND stock_alert_threshold IS NOT NULL
            """,
            (factor, tenant_id, rebroyat_id),
        )

        connection.execute(
            "UPDATE core.products SET uom_id = %s WHERE tenant_id = %s AND id = %s",
            (ton_uom_id, tenant_id, rebroyat_id),
        )

        if dry_run:
            connection.rollback()
            print("Dry run -- rolled back, nothing written.")
            return

        connection.commit()
    print(f"Repointed {sku} ({name}) from {current_code} to ton, rescaling every stored figure by {factor:g}.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tenant", default="demo")
    parser.add_argument("--dry-run", action="store_true", help="Show what would change without committing")
    args = parser.parse_args()
    run(args.tenant, args.dry_run)


if __name__ == "__main__":
    main()
