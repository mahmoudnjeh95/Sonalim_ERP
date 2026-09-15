"""One-off data fix: OF-000034's morning daily report for 2026-09-12
(report_id 01M29Z58X44G8MA6H41C611QDN, tenant demo, validated) has a wrong
stored water_quantity, caused by a real bug in DailyReportsTab's water-from-
percentage calculation (now fixed in the frontend): it summed semoule poured
(recorded in tonnes) and rebroyat versé (recorded in kg) as raw numbers with
no unit conversion, then applied the water percentage to that mixed-unit sum.

The report_revisions history shows this happened twice:
  - revision 1: semoule 10.3t + 0.9t, rebroyat versé 1.4 kg -> buggy calc gave
    (11.2 + 1.4) * 34.9% = 4.4 L.
  - revision 2 (reason "coeeztion"): someone tried to fix the obviously-too-
    small 4.4 L by changing rebroyat versé to 1400 kg (confirmed by the user
    to be the real figure) -- but the same unit bug was still live, so it
    computed (11.2 + 1400) * 34.9% = 492.51 L, which is also wrong.

Correct value, with semoule normalized to kg (10300 + 900) and rebroyat versé
1400 kg all summed in kg before applying the percentage:
    34.9% * (10300 + 900 + 1400) = 34.9% * 12600 = 4397.4 L

Why not the app's own ProductionReportService.correct_validated_report: that
path reverses and re-posts every stock movement the report made (semoule,
rebroyat) even though only water -- which is never posted to stock (it is a
metered utility, see the daily_reports migration comment) -- is being
corrected. Re-running that machinery for an unrelated field risks touching
working stock postings for no reason. This script instead updates only the
water_quantity column directly and appends a revision explaining why, which
is what the app's correction flow would do to the audit trail if the change
it made were this narrow.

Usage:
    DATABASE_URL=... python -m scripts.fix_daily_report_water_quantity_of34 --tenant demo
"""

from __future__ import annotations

import argparse
import dataclasses

from core.audit import record_audit
from core.db import get_connection
from modules.production.api.production_report_service import ProductionReportService

REPORT_ID = "01M29Z58X44G8MA6H41C611QDN"
OLD_WATER_QUANTITY = 492.51
NEW_WATER_QUANTITY = 4397.4
REASON = (
    "correcting the water-from-percentage calculation: semoule (t) and rebroyat "
    "versé (kg) were summed as raw numbers with no unit conversion before "
    "applying the 34.9% water dosage -- 34.9% of (10300 + 900 + 1400) kg = 4397.4 L"
)


def run(tenant_id: str) -> None:
    with get_connection() as connection:
        service = ProductionReportService(connection)

        header = service._load_header(tenant_id=tenant_id, report_id=REPORT_ID, for_update=True)
        if header is None:
            print(f"report {REPORT_ID} not found for tenant {tenant_id!r} -- already fixed?")
            connection.rollback()
            return
        if header.status != "validated" or header.report_type != "daily":
            raise RuntimeError(
                f"report {REPORT_ID} is {header.report_type}/{header.status}, not the expected daily/validated -- "
                "refusing to guess"
            )

        detail = service._load_daily_detail(tenant_id=tenant_id, report_id=REPORT_ID)
        if detail is None:
            raise RuntimeError(f"no daily detail found for report {REPORT_ID}")
        if abs(detail.water_quantity - OLD_WATER_QUANTITY) > 1e-6:
            raise RuntimeError(
                f"report's water_quantity is {detail.water_quantity}, not the expected {OLD_WATER_QUANTITY} -- "
                "something else has already touched it, refusing to guess"
            )
        if abs(detail.regrind_input_quantity - 1400.0) > 1e-6:
            raise RuntimeError(
                f"report's regrind_input_quantity is {detail.regrind_input_quantity}, expected 1400 -- "
                "refusing to guess"
            )

        revisions = connection.execute(
            "SELECT COALESCE(MAX(revision), 0) FROM production.report_revisions WHERE report_id = %s AND tenant_id = %s",
            (REPORT_ID, tenant_id),
        ).fetchone()
        new_revision = revisions[0] + 1

        actor_id = connection.execute(
            "SELECT actor_id FROM production.report_revisions WHERE report_id = %s ORDER BY revision DESC LIMIT 1",
            (REPORT_ID,),
        ).fetchone()[0]

        corrected = dataclasses.replace(detail, water_quantity=NEW_WATER_QUANTITY)
        service._update_daily_detail(tenant_id=tenant_id, report_id=REPORT_ID, detail=corrected)
        service._write_revision(
            tenant_id=tenant_id,
            report_id=REPORT_ID,
            revision=new_revision,
            detail=corrected,
            reason=REASON,
            actor_id=actor_id,
        )
        connection.execute(
            "UPDATE production.production_reports SET revision = %s, updated_at = NOW() WHERE id = %s",
            (new_revision, REPORT_ID),
        )
        record_audit(
            connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="production_report.corrected_after_validation",
            entity_type="production_report",
            entity_id=REPORT_ID,
            payload={
                "revision": new_revision,
                "reason": REASON,
                "before": {"water_quantity": OLD_WATER_QUANTITY},
                "after": {"water_quantity": NEW_WATER_QUANTITY},
            },
        )
        connection.commit()

    print(f"Report {REPORT_ID}: water_quantity {OLD_WATER_QUANTITY} -> {NEW_WATER_QUANTITY} (revision {new_revision}).")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tenant", default="demo")
    args = parser.parse_args()
    run(args.tenant)


if __name__ == "__main__":
    main()
