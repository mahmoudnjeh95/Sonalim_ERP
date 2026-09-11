"""One-off data fix: OF-000012's daily report (id 01M25ST3947Q3SVBK89JXWV19E,
validated 2026-09-10) recorded regrind_input_quantity = 2000 kg while testing
the daily-report form after the regrind_product_id fix -- confirmed by the
user to be test data, not a real shift figure, and to be corrected to a
realistic value (131 kg) rather than removed outright.

Why not the app's own "correct a validated report" flow
(ProductionReportService.correct_validated_report): it refuses here.
Correcting a validated report first unwinds the regrind OF it opened
(_unwind_regrind), and this report's own regrind OF (work_order
01M25SV4CYNVMJETECJ50EY707) has already been ground and received into stock --
exactly the case _unwind_regrind explicitly rejects ("REGRIND_ALREADY_COMPLETED"),
since the material physically exists and there is no honest way to unwind it.
That OF is untouched by this script; only the *input* side (rebroyat poured
back into the mix that shift) is test data and is what this corrects.

This is a direct edit rather than a posted reversal + re-post (the correction-
flow's usual shape) because the value is being treated as test data corrected
to what it should have read from the start, not a real mistake needing a
visible audit trail of the wrong figure -- same treatment as
scripts/remove_regrind_seed_adjustment.py. Three things move together so nothing
drifts: the report's own stored figure, the stock move it posted, and the
on-hand balance that move already affected.

Usage:
    DATABASE_URL=... python -m scripts.fix_test_regrind_input_quantity --tenant demo
"""

from __future__ import annotations

import argparse

from core.db import get_connection

REPORT_ID = "01M25ST3947Q3SVBK89JXWV19E"
OLD_QUANTITY = 2000.0
NEW_QUANTITY = 131.0


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
        delta = OLD_QUANTITY - NEW_QUANTITY  # give back the difference that was over-consumed
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
