"""One-off data fix, companion to scripts/fix_test_regrind_input_quantity.py:
OF-000010's afternoon daily report (id 01M25W2HCZBJ1Q6BXW5NQ04D74, validated
2026-09-10) recorded regrind_input_quantity = 1000 kg while testing the same
daily-report flow -- confirmed by the user as test data, to get the same
treatment as OF-000012's report (corrected to a realistic figure, not
removed). No specific value was given for this one, so this picks 95 kg --
a plausible per-shift rebroyat reuse figure, distinct from OF-000012's 131 so
the two don't read as an obviously copy-pasted number. Adjust NEW_QUANTITY
and re-run if a different figure is wanted.

The app's own "correct a validated report" flow is refused here for the same
reason as OF-000012: this report's own regrind OF (work_order
01M25W3E8TQX8JHCN272XFKVPD) has already been ground and received into stock,
which ProductionReportService._unwind_regrind explicitly won't unwind. That OF
is untouched; only the input-side test figure is corrected, the same direct
edit of report + move + on-hand balance as the companion script.

Usage:
    DATABASE_URL=... python -m scripts.fix_test_regrind_input_quantity_2 --tenant demo
"""

from __future__ import annotations

import argparse

from core.db import get_connection

REPORT_ID = "01M25W2HCZBJ1Q6BXW5NQ04D74"
OLD_QUANTITY = 1000.0
NEW_QUANTITY = 95.0


def run(tenant_id: str) -> None:
    with get_connection() as connection:
        report = connection.execute(
            """
            SELECT d.regrind_input_quantity, d.regrind_input_product_id, d.raw_material_location_id
            FROM production.daily_reports d
            JOIN production.production_reports pr ON pr.id = d.report_id AND pr.tenant_id = d.tenant_id
            WHERE d.report_id = %s AND d.tenant_id = %s AND pr.status = 'validated'
            """,
            (REPORT_ID, tenant_id),
        ).fetchone()
        if report is None:
            print(f"report {REPORT_ID} not found (or not validated) for tenant {tenant_id!r} -- already fixed?")
            connection.rollback()
            return
        regrind_input_quantity, product_id, location_id = report
        if float(regrind_input_quantity) != OLD_QUANTITY:
            raise RuntimeError(
                f"report's regrind_input_quantity is {regrind_input_quantity}, not the expected {OLD_QUANTITY} -- "
                "something else has already touched it, refusing to guess"
            )

        move = connection.execute(
            """
            SELECT id, quantity FROM warehouse.stock_moves
            WHERE tenant_id = %s AND product_id = %s AND location_id = %s
              AND move_type = 'production_consumption' AND reference = %s
            """,
            (tenant_id, product_id, location_id, f"production_report:{REPORT_ID}"),
        ).fetchone()
        if move is None:
            raise RuntimeError("no matching production_consumption move found -- refusing to guess")
        move_id, move_quantity = move
        if float(move_quantity) != OLD_QUANTITY:
            raise RuntimeError(f"move {move_id} quantity is {move_quantity}, not the expected {OLD_QUANTITY} -- refusing to guess")

        item = connection.execute(
            "SELECT quantity_on_hand FROM warehouse.stock_items WHERE tenant_id = %s AND product_id = %s AND location_id = %s FOR UPDATE",
            (tenant_id, product_id, location_id),
        ).fetchone()
        if item is None:
            raise RuntimeError("stock_items row not found -- nothing to reconcile, refusing to edit blind")
        on_hand = float(item[0])
        delta = OLD_QUANTITY - NEW_QUANTITY
        new_on_hand = on_hand + delta

        connection.execute(
            "UPDATE production.daily_reports SET regrind_input_quantity = %s WHERE report_id = %s AND tenant_id = %s",
            (NEW_QUANTITY, REPORT_ID, tenant_id),
        )
        connection.execute(
            "UPDATE warehouse.stock_moves SET quantity = %s WHERE id = %s AND tenant_id = %s",
            (NEW_QUANTITY, move_id, tenant_id),
        )
        connection.execute(
            "UPDATE warehouse.stock_items SET quantity_on_hand = %s WHERE tenant_id = %s AND product_id = %s AND location_id = %s",
            (new_on_hand, tenant_id, product_id, location_id),
        )
        connection.commit()

    print(f"Report {REPORT_ID}: regrind_input_quantity {OLD_QUANTITY} -> {NEW_QUANTITY}.")
    print(f"Move {move_id}: quantity {OLD_QUANTITY} -> {NEW_QUANTITY}.")
    print(f"On-hand at that location: {on_hand} -> {new_on_hand} (+{delta} given back).")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tenant", default="demo")
    args = parser.parse_args()
    run(args.tenant)


if __name__ == "__main__":
    main()
