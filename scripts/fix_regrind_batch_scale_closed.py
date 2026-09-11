"""One-off data fix, companion to scripts/fix_regrind_batch_scale.py: two
*closed* regrind batches (OF-000011, OF-000007) were also created while
create_regrind_batch summed scrap quantities without converting units first
(fixed alongside this script -- see modules/production/api/regrind_service.py).
Both consumed scrap recorded correctly in tonnes against a raw semolina
product, but had it summed as if already in the rebroyat product's own unit
(kg) -- and unlike the batches fix_regrind_batch_scale.py corrects, these two
were already completed: their actual_output_quantity was weighed, entered,
and posted to stock at the wrong (1000x too small) scale.

This corrects, for each of the two work orders:
  - work_orders.planned_quantity        (the batch's estimate)
  - regrind_batches.input_quantity_total (the scrap consumed)
  - regrind_batches.actual_output_quantity (the weighed output)
and posts a compensating stock adjustment at the same location the batch's
completion originally posted to, through StockService.adjust_stock (so it goes
through the normal validated path and lands its own audited "adjustment" stock
move) -- bringing on-hand up by the difference between the corrected and
original actual_output_quantity, not just overwriting it, since other stock
activity may have happened at that location since.

Usage:
    DATABASE_URL=... python -m scripts.fix_regrind_batch_scale_closed --tenant demo
"""

from __future__ import annotations

import argparse

from core.db import get_connection
from core.domain.result import Err
from modules.warehouse.api.service import StockService

# (work order reference, correction factor)
CORRECTIONS = [
    ("OF-000011", 1000),
    ("OF-000007", 1000),
]


def run(tenant_id: str) -> None:
    with get_connection() as connection:
        actor_row = connection.execute(
            "SELECT id FROM core.users WHERE tenant_id = %s AND email = %s", (tenant_id, f"{tenant_id}@sonalim-erp.local")
        ).fetchone()
        if actor_row is None:
            raise RuntimeError(f"tenant {tenant_id!r} has no {tenant_id}@sonalim-erp.local user to attribute this correction to")
        actor_id = actor_row[0]

        fixed: list[str] = []
        for reference, factor in CORRECTIONS:
            row = connection.execute(
                """
                SELECT wo.id, wo.product_id, wo.planned_quantity, rb.input_quantity_total, rb.actual_output_quantity
                FROM production.work_orders wo
                JOIN production.regrind_batches rb ON rb.work_order_id = wo.id
                WHERE wo.tenant_id = %s AND wo.reference = %s
                """,
                (tenant_id, reference),
            ).fetchone()
            if row is None:
                print(f"  {reference}: no such regrind batch -- skipped (already fixed or renumbered?)")
                continue
            work_order_id, product_id, planned_quantity, input_quantity_total, actual_output_quantity = row
            if actual_output_quantity is None:
                print(f"  {reference}: not completed yet -- use fix_regrind_batch_scale.py instead, skipped")
                continue

            move_row = connection.execute(
                """
                SELECT location_id, quantity FROM warehouse.stock_moves
                WHERE tenant_id = %s AND product_id = %s AND reference = %s AND move_type = 'production'
                ORDER BY created_at DESC LIMIT 1
                """,
                (tenant_id, product_id, f"work_order:{work_order_id}"),
            ).fetchone()
            if move_row is None:
                print(f"  {reference}: no posted production stock move found -- skipped, needs manual review")
                continue
            location_id, posted_quantity = move_row

            corrected_output = float(actual_output_quantity) * factor
            delta = corrected_output - float(posted_quantity)

            connection.execute(
                "UPDATE production.work_orders SET planned_quantity = planned_quantity * %s WHERE id = %s AND tenant_id = %s",
                (factor, work_order_id, tenant_id),
            )
            connection.execute(
                """
                UPDATE production.regrind_batches
                SET input_quantity_total = input_quantity_total * %s, actual_output_quantity = actual_output_quantity * %s
                WHERE work_order_id = %s AND tenant_id = %s
                """,
                (factor, factor, work_order_id, tenant_id),
            )
            adjustment = StockService(connection).adjust_stock(
                tenant_id=tenant_id,
                product_id=product_id,
                location_id=location_id,
                delta=delta,
                reason=(
                    f"Unit-mixing correction for {reference}: its regrind scrap was recorded in tonnes and "
                    f"summed into input_quantity_total/actual_output_quantity as kg, understating both {factor}x. "
                    f"actual_output_quantity {actual_output_quantity} -> {corrected_output}; stock adjusted by +{delta}."
                ),
                actor_id=actor_id,
            )
            if isinstance(adjustment, Err):
                raise RuntimeError(f"{reference}: stock adjustment failed -- {adjustment.code}: {adjustment.message}")

            print(
                f"  {reference}: planned {planned_quantity} -> {planned_quantity * factor}, "
                f"actual_output_quantity {actual_output_quantity} -> {corrected_output}, "
                f"stock at {location_id} adjusted by +{delta} (now {adjustment.value.quantity_on_hand})"
            )
            fixed.append(reference)
        connection.commit()

    print(f"Fixed {len(fixed)} of {len(CORRECTIONS)} closed regrind batch(es).")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tenant", default="demo")
    args = parser.parse_args()
    run(args.tenant)


if __name__ == "__main__":
    main()
