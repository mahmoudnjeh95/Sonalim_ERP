"""One-off data fix: scrap_records rows auto-created from a validated daily
report (scrap_type = 'daily_report') were linked to whatever raw material the
report's own `regrind_product_id` named -- in every existing case, one of the
purchased semolina brands ("Semoule Blé Dur SALEM", "... SALEM TN") rather
than the tenant's own rebroyat product. `_record_regrind_scrap`
(production_report_service.py) no longer does this -- it now always resolves
the tenant's regrind output product (production.regrind_defaults,
input_product_id IS NULL) -- but that fix only applies to reports validated
after it shipped. This repoints the rows it already created.

Repointing product_id alone would silently corrupt the figure: these rows are
denominated in their *original* product's unit (a purchased semolina bought by
the tonne), and the rebroyat product is tracked in kg. So each row's quantity
is rescaled by the ratio between the two units' ratio_to_base -- the same
weight-category conversion RegrindService.create_regrind_batch already applies
when it sums scrap into a batch (see regrind_service.py), just applied here
directly to the stored row instead of only at read time.

Every row this script touches already has is_reground = TRUE in every case
seen so far -- the batches built from them (regrind_batches.input_quantity_total,
actual_output_quantity, and any stock they posted) were already corrected by
scripts/fix_regrind_batch_scale.py / fix_regrind_batch_scale_closed.py and are
NOT re-touched here: those are their own stored figures, not recomputed from
scrap_records at read time, so this is a traceability-only correction with no
effect on stock or batch totals.

A row whose product's own unit isn't weight-category (so no honest conversion
factor exists) is skipped and printed instead of guessed at, per the read-only-
audit convention in scripts/audit_uom_quantity_integrity.py.

Usage:
    DATABASE_URL=... python -m scripts.fix_daily_report_scrap_product --tenant demo
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

        output_uom = connection.execute(
            """
            SELECT u.category, u.ratio_to_base FROM core.products p
            JOIN core.uoms u ON u.id = p.uom_id AND u.tenant_id = p.tenant_id
            WHERE p.tenant_id = %s AND p.id = %s
            """,
            (tenant_id, output_product_id),
        ).fetchone()
        if output_uom is None:
            raise RuntimeError(f"regrind output product {output_product_id!r} has no resolvable unit")
        output_category, output_ratio = output_uom

        rows = connection.execute(
            """
            SELECT s.id, s.product_id, s.quantity, p.sku, p.name, u.category, u.ratio_to_base
            FROM production.scrap_records s
            JOIN core.products p ON p.id = s.product_id AND p.tenant_id = s.tenant_id
            JOIN core.uoms u ON u.id = p.uom_id AND u.tenant_id = p.tenant_id
            WHERE s.tenant_id = %s AND s.scrap_type = 'daily_report' AND s.product_id != %s
            ORDER BY s.created_at
            """,
            (tenant_id, output_product_id),
        ).fetchall()

        fixed = 0
        for scrap_id, old_product_id, quantity, sku, name, category, ratio in rows:
            if category != output_category:
                print(f"  skip {scrap_id}: {sku} ({name}) is category {category!r}, not {output_category!r} -- no honest conversion, needs manual review")
                continue
            new_quantity = float(quantity) * (float(ratio) / float(output_ratio))
            connection.execute(
                "UPDATE production.scrap_records SET product_id = %s, quantity = %s WHERE id = %s AND tenant_id = %s",
                (output_product_id, new_quantity, scrap_id, tenant_id),
            )
            print(f"  {scrap_id}: {sku} ({name}) {quantity} -> rebroyat {new_quantity}")
            fixed += 1
        connection.commit()

    print(f"Repointed {fixed} of {len(rows)} daily-report scrap record(s) onto the rebroyat product.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tenant", default="demo")
    args = parser.parse_args()
    run(args.tenant)


if __name__ == "__main__":
    main()
