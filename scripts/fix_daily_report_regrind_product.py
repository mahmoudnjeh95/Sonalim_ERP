"""One-off data fix: production.daily_reports.regrind_product_id was, before
production_report_service.py was fixed to always force the tenant's one
rebroyat product, a free pick the report author made -- in every existing case,
one of the purchased semolina brands ("Semoule Blé Dur SALEM", "... SALEM TN")
rather than the tenant's own rebroyat product (see production.regrind_defaults,
the row with input_product_id IS NULL). scripts/fix_daily_report_scrap_product.py
already fixed the same symptom on production.scrap_records; this is the sibling
fix for the field on daily_reports itself.

The field is purely informational (production_report_service.py resolves the
real regrind output product dynamically for every stock posting and never
reads it back) -- see the DailyReportDialog / ValidationCenterTab frontend,
which use it only to look up a unit for the "Rebroyat" figure. That is exactly
the bug this fixes: a report whose regrind_product_id names a tonne-denominated
semoule product makes the UI print "88 t" for a value that was always weighed
in kg on the rebroyat scale. No rescaling is needed (unlike the scrap_records
fix) -- regrind_quantity was never interpreted through this field for any
calculation, so repointing it changes only the displayed unit, not the number.

Usage:
    DATABASE_URL=... python -m scripts.fix_daily_report_regrind_product --tenant demo
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

        rows = connection.execute(
            """
            SELECT dr.report_id, p.sku, p.name, dr.regrind_quantity
            FROM production.daily_reports dr
            JOIN core.products p ON p.id = dr.regrind_product_id AND p.tenant_id = dr.tenant_id
            WHERE dr.tenant_id = %s AND dr.regrind_product_id IS NOT NULL AND dr.regrind_product_id != %s
            ORDER BY dr.report_id
            """,
            (tenant_id, output_product_id),
        ).fetchall()

        for report_id, sku, name, quantity in rows:
            connection.execute(
                "UPDATE production.daily_reports SET regrind_product_id = %s WHERE report_id = %s AND tenant_id = %s",
                (output_product_id, report_id, tenant_id),
            )
            print(f"  {report_id}: {sku} ({name}) -> rebroyat, quantity {quantity} unchanged")
        connection.commit()

    print(f"Repointed {len(rows)} daily report(s) onto the rebroyat product.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tenant", default="demo")
    args = parser.parse_args()
    run(args.tenant)


if __name__ == "__main__":
    main()
