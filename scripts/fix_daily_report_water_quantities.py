"""One-off data fix: every validated daily report's stored water_quantity was
computed by the same buggy formula DailyReportsTab used before the unit-
conversion fix (see git history) -- semoule poured (recorded in tonnes) and
rebroyat versé (recorded in kg) were summed as raw numbers with no unit
conversion, then the water percentage was applied to that mixed-unit sum.
scripts/fix_daily_report_water_quantity_of34.py fixed the first instance
found (OF-000034, 2026-09-12 morning); this script re-derives and corrects
water_quantity for every other daily report the same way, confirmed by the
user to cover all rapports.

For each daily report this recomputes:
    water_quantity = round(water_percentage / 100 * mixed_kg, 2)
where mixed_kg sums every semoule line's quantity and the rebroyat versé
quantity, each converted to kg via its own product's uom ratio_to_base --
never the raw stored numbers. The other figures on each report (semoule
lines, rebroyat versé, percentage) are left exactly as currently stored;
only the derived water_quantity is corrected, since that is the only field
this bug touched.

Water is a metered utility, never posted to stock (see the daily_reports
migration comment), so this updates the column directly rather than going
through ProductionReportService.correct_validated_report -- that path
reverses and re-posts every stock movement the report made (semoule,
rebroyat), which would touch working stock postings for a field that never
had any. A revision is still appended for each report so the correction
shows up in its own audit trail, same treatment as the OF-000034 fix.

A report already within 0.02 L of the recomputed figure is left untouched
and reported as already-correct (this is what makes the script idempotent --
re-running it after a partial run only touches what's still wrong).

Usage:
    DATABASE_URL=... python -m scripts.fix_daily_report_water_quantities --tenant demo
    DATABASE_URL=... python -m scripts.fix_daily_report_water_quantities --tenant demo --dry-run
"""

from __future__ import annotations

import argparse
import dataclasses

from core.audit import record_audit
from core.db import get_connection
from modules.production.api.production_report_service import ProductionReportService

REASON = (
    "correcting the water-from-percentage calculation: semoule (t) and rebroyat "
    "versé (kg) were summed as raw numbers with no unit conversion before "
    "applying the water dosage percentage -- water_quantity re-derived with "
    "every quantity converted to kg via its own product's uom first"
)


def _mixed_input_kg(connection, tenant_id: str, report_id: str, regrind_quantity: float, regrind_product_id: str | None) -> float:
    semoule_rows = connection.execute(
        """
        SELECT rsl.quantity, u.ratio_to_base
        FROM production.report_semolina_lines rsl
        JOIN core.products p ON p.id = rsl.product_id
        JOIN core.uoms u ON u.id = p.uom_id
        WHERE rsl.report_id = %s AND rsl.tenant_id = %s
        """,
        (report_id, tenant_id),
    ).fetchall()
    semoule_kg = sum(float(quantity) * float(ratio) for quantity, ratio in semoule_rows)

    regrind_ratio = 1.0
    if regrind_product_id and regrind_quantity:
        row = connection.execute(
            "SELECT u.ratio_to_base FROM core.products p JOIN core.uoms u ON u.id = p.uom_id WHERE p.id = %s",
            (regrind_product_id,),
        ).fetchone()
        if row is None:
            raise RuntimeError(f"report {report_id}: regrind product {regrind_product_id} has no resolvable uom")
        regrind_ratio = float(row[0])
    regrind_kg = float(regrind_quantity) * regrind_ratio

    return semoule_kg + regrind_kg


def run(tenant_id: str, dry_run: bool) -> None:
    with get_connection() as connection:
        service = ProductionReportService(connection)

        reports = connection.execute(
            """
            SELECT pr.id, pr.report_date, pr.shift, wo.reference
            FROM production.production_reports pr
            LEFT JOIN production.work_orders wo ON wo.id = pr.of_id
            WHERE pr.report_type = 'daily' AND pr.tenant_id = %s AND pr.status = 'validated'
            ORDER BY pr.report_date, pr.shift
            """,
            (tenant_id,),
        ).fetchall()

        fixed, already_ok = 0, 0
        for report_id, report_date, shift, of_ref in reports:
            detail = service._load_daily_detail(tenant_id=tenant_id, report_id=report_id)
            if detail is None:
                continue

            mixed_kg = _mixed_input_kg(
                connection, tenant_id, report_id, detail.regrind_input_quantity, detail.regrind_input_product_id
            )
            correct_water = round(detail.water_percentage / 100 * mixed_kg + 1e-9, 2)
            label = f"{report_date} {shift:9s} {of_ref or '?':10s}"

            if abs(correct_water - detail.water_quantity) < 0.02:
                print(f"{label} already correct: {detail.water_quantity}")
                already_ok += 1
                continue

            print(f"{label} water_quantity {detail.water_quantity} -> {correct_water}")
            if dry_run:
                fixed += 1
                continue

            header = service._load_header(tenant_id=tenant_id, report_id=report_id, for_update=True)
            revision_row = connection.execute(
                "SELECT COALESCE(MAX(revision), 0), (ARRAY_AGG(actor_id ORDER BY revision DESC))[1] "
                "FROM production.report_revisions WHERE report_id = %s AND tenant_id = %s",
                (report_id, tenant_id),
            ).fetchone()
            new_revision = revision_row[0] + 1
            actor_id = revision_row[1]

            corrected = dataclasses.replace(detail, water_quantity=correct_water)
            service._update_daily_detail(tenant_id=tenant_id, report_id=report_id, detail=corrected)
            service._write_revision(
                tenant_id=tenant_id, report_id=report_id, revision=new_revision,
                detail=corrected, reason=REASON, actor_id=actor_id,
            )
            connection.execute(
                "UPDATE production.production_reports SET revision = %s, updated_at = NOW() WHERE id = %s",
                (new_revision, report_id),
            )
            record_audit(
                connection, tenant_id=tenant_id, actor_id=actor_id,
                action="production_report.corrected_after_validation",
                entity_type="production_report", entity_id=report_id,
                payload={
                    "revision": new_revision, "reason": REASON,
                    "before": {"water_quantity": detail.water_quantity},
                    "after": {"water_quantity": correct_water},
                },
            )
            fixed += 1

        if dry_run:
            connection.rollback()
            print(f"\n[dry run] {fixed} report(s) would be fixed, {already_ok} already correct. No changes written.")
        else:
            connection.commit()
            print(f"\n{fixed} report(s) fixed, {already_ok} already correct.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tenant", default="demo")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run(args.tenant, args.dry_run)


if __name__ == "__main__":
    main()
