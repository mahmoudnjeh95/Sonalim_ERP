"""One-off data fix: three regrind batches (OF-000014, OF-000015, OF-000016)
were created while `create_regrind_batch` summed scrap quantities without
converting units first (fixed alongside this script -- see
modules/production/api/regrind_service.py). Their scrap input was recorded
correctly, in tonnes, against the raw semolina product ("Semoule Blé Dur
SALEM", uom "ton", ratio_to_base 1000) -- 0.043 t, 0.102 t and 0.104 t. But
`input_quantity_total` and the batches' estimated output (`work_orders.
planned_quantity`) took that raw number as if it were already in the rebroyat
product's own unit (kg), landing 1000x too small: 0.043 instead of 43 kg, and
so on. Confirmed against the physical weigh-in for OF-000016 (0.043 -> 43 kg).

This multiplies both figures by 1000 for exactly these three work orders. Each
batch's `actual_output_quantity` is still NULL (none of the three has been
completed/weighed yet), so there is nothing to correct there -- the operator
will enter the real weighed figure directly in kg once the field's unit label
is fixed.

Usage:
    DATABASE_URL=... python -m scripts.fix_regrind_batch_scale --tenant demo
"""

from __future__ import annotations

import argparse

from core.db import get_connection

# (work order reference, correction factor)
CORRECTIONS = [
    ("OF-000014", 1000),
    ("OF-000015", 1000),
    ("OF-000016", 1000),
]


def run(tenant_id: str) -> None:
    with get_connection() as connection:
        fixed: list[str] = []
        for reference, factor in CORRECTIONS:
            row = connection.execute(
                """
                SELECT wo.id, wo.planned_quantity, rb.input_quantity_total, rb.actual_output_quantity
                FROM production.work_orders wo
                JOIN production.regrind_batches rb ON rb.work_order_id = wo.id
                WHERE wo.tenant_id = %s AND wo.reference = %s
                """,
                (tenant_id, reference),
            ).fetchone()
            if row is None:
                print(f"  {reference}: no such regrind batch -- skipped (already fixed or renumbered?)")
                continue
            work_order_id, planned_quantity, input_quantity_total, actual_output_quantity = row

            connection.execute(
                "UPDATE production.work_orders SET planned_quantity = planned_quantity * %s WHERE id = %s AND tenant_id = %s",
                (factor, work_order_id, tenant_id),
            )
            connection.execute(
                "UPDATE production.regrind_batches SET input_quantity_total = input_quantity_total * %s WHERE work_order_id = %s AND tenant_id = %s",
                (factor, work_order_id, tenant_id),
            )
            if actual_output_quantity is not None:
                connection.execute(
                    "UPDATE production.regrind_batches SET actual_output_quantity = actual_output_quantity * %s WHERE work_order_id = %s AND tenant_id = %s",
                    (factor, work_order_id, tenant_id),
                )
            print(
                f"  {reference}: planned {planned_quantity} -> {planned_quantity * factor}, "
                f"input_quantity_total {input_quantity_total} -> {input_quantity_total * factor}"
                + (f", actual_output_quantity {actual_output_quantity} -> {actual_output_quantity * factor}" if actual_output_quantity is not None else "")
            )
            fixed.append(reference)
        connection.commit()

    print(f"Fixed {len(fixed)} of {len(CORRECTIONS)} regrind batch(es).")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tenant", default="demo")
    args = parser.parse_args()
    run(args.tenant)


if __name__ == "__main__":
    main()
