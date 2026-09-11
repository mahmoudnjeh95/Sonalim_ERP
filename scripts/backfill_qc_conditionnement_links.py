"""One-off data fix: link existing qc.quality_reports rows to the specific
production.conditionnement_reports row they inspect.

Before migrations/0004_qc_conditionnement_link.sql, a quality report carried
only of_id + report_date + shift -- which conditionnement (packaging) run it
inspected was matched by convention, never by a real foreign key. This also
means `team` on old rows was whatever the QC inspector typed, not necessarily
the team that ran the conditionnement line -- see that migration's comment for
why this matters (it's what fed a phantom "QC" series into the Conformite par
equipe dashboard).

This backfills conditionnement_report_id for every pre-existing quality
report, by finding the one conditionnement report sharing its of_id,
report_date and shift, and recomputes `team` from it at the same time. A row
with zero or more than one candidate (or whose only candidate is already
claimed by another quality report) is left alone and printed for manual
review -- this never guesses.

Usage:
    DATABASE_URL=... python -m scripts.backfill_qc_conditionnement_links --tenant demo
"""

from __future__ import annotations

import argparse

from core.db import get_connection
from modules.production.api.production_report_service import ProductionReportService


def run(tenant_id: str) -> None:
    with get_connection() as connection:
        unlinked = connection.execute(
            "SELECT id, of_id, report_date, shift FROM qc.quality_reports "
            "WHERE tenant_id = %s AND conditionnement_report_id IS NULL",
            (tenant_id,),
        ).fetchall()

        if not unlinked:
            print(f"tenant {tenant_id!r}: nothing to backfill.")
            return

        already_claimed = {
            row[0]
            for row in connection.execute(
                "SELECT conditionnement_report_id FROM qc.quality_reports "
                "WHERE tenant_id = %s AND conditionnement_report_id IS NOT NULL",
                (tenant_id,),
            ).fetchall()
        }

        reports = ProductionReportService(connection)
        linked = 0
        needs_review: list[tuple[str, str]] = []

        for report_id, of_id, report_date, shift in unlinked:
            candidates = [
                header
                for header in reports.list_reports(tenant_id=tenant_id, of_id=of_id, report_type="conditionnement")
                if header.report_date == report_date and header.shift == shift and header.id not in already_claimed
            ]
            if len(candidates) != 1:
                needs_review.append(
                    (report_id, f"{len(candidates)} candidate(s) for of {of_id}, {report_date}, shift {shift!r}")
                )
                continue

            conditionnement = candidates[0]
            connection.execute(
                "UPDATE qc.quality_reports SET conditionnement_report_id = %s, team = %s, updated_at = NOW() "
                "WHERE id = %s AND tenant_id = %s",
                (conditionnement.id, conditionnement.team, report_id, tenant_id),
            )
            already_claimed.add(conditionnement.id)
            linked += 1

        connection.commit()

    print(f"tenant {tenant_id!r}: linked {linked} report(s).")
    if needs_review:
        print(f"{len(needs_review)} report(s) need manual review:")
        for report_id, reason in needs_review:
            print(f"  {report_id}: {reason}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tenant", default="demo")
    args = parser.parse_args()
    run(args.tenant)


if __name__ == "__main__":
    main()
