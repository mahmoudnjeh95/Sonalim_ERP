"""One-off data fix for team-name spelling variants across production and QC reports.

`team` (production.production_reports, qc.quality_reports) and
`assigned_team` (production.regrind_batches) are deliberately free text rather
than a foreign key into core.report_options — see team_performance_service.py
and migration 0029 — so a plant can add a team in Production Settings and have
it show up immediately, without a migration. But because they're free text,
nothing stops the same team from being recorded under two spellings, e.g.
"Équipe A" vs "Equipe A" (missing accent). Every aggregate that groups by team
(TeamPerformanceService.list_team_performance, buildTeamSemouleWaste on the
production dashboard, etc.) does a literal string GROUP BY, so two spellings
of the same team silently split into two rows/bars with a fraction each of the
real total instead of one.

This rewrites every team value that matches a configured core.report_options
(kind='team') label once accents/case/whitespace are ignored, to that option's
exact configured spelling — the canonical one shown in the team dropdown. A
value that doesn't match any configured option (e.g. a team since renamed or
retired) is left untouched and reported, since guessing its intended spelling
would risk merging two actually-different teams.

Usage:
    DATABASE_URL=... python -m scripts.fix_team_name_variants --tenant demo
"""

from __future__ import annotations

import argparse
import unicodedata

from core.db import get_connection


def normalize(label: str) -> str:
    stripped = "".join(c for c in unicodedata.normalize("NFKD", label) if not unicodedata.combining(c))
    return " ".join(stripped.split()).casefold()


def canonical_team_labels(connection, tenant_id: str) -> dict[str, str]:
    rows = connection.execute(
        "SELECT label FROM core.report_options WHERE tenant_id = %s AND kind = 'team'",
        (tenant_id,),
    ).fetchall()
    return {normalize(label): label for (label,) in rows}


def fix_column(connection, tenant_id: str, table: str, column: str, canonical: dict[str, str]) -> list[tuple[str, str, int]]:
    rows = connection.execute(
        f"SELECT DISTINCT {column} FROM {table} WHERE tenant_id = %s AND {column} IS NOT NULL",
        (tenant_id,),
    ).fetchall()

    fixed: list[tuple[str, str, int]] = []
    for (value,) in rows:
        target = canonical.get(normalize(value))
        if target is None or target == value:
            continue
        result = connection.execute(
            f"UPDATE {table} SET {column} = %s WHERE tenant_id = %s AND {column} = %s",
            (target, tenant_id, value),
        )
        fixed.append((value, target, result.rowcount))
    return fixed


def run(tenant_id: str) -> None:
    with get_connection() as connection:
        canonical = canonical_team_labels(connection, tenant_id)
        if not canonical:
            print(f"tenant {tenant_id!r} has no configured team options (core.report_options, kind='team') — nothing to match against.")
            return

        changes = {
            ("production.production_reports", "team"): fix_column(
                connection, tenant_id, "production.production_reports", "team", canonical
            ),
            ("production.regrind_batches", "assigned_team"): fix_column(
                connection, tenant_id, "production.regrind_batches", "assigned_team", canonical
            ),
            ("qc.quality_reports", "team"): fix_column(connection, tenant_id, "qc.quality_reports", "team", canonical),
        }
        connection.commit()

    total = 0
    for (table, column), fixed in changes.items():
        for old, new, rowcount in fixed:
            print(f"  {table}.{column}: {old!r} -> {new!r} ({rowcount} row(s))")
            total += rowcount
    print(f"Fixed {total} row(s) across {len(changes)} column(s) for tenant {tenant_id!r}.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tenant", default="demo")
    args = parser.parse_args()
    run(args.tenant)


if __name__ == "__main__":
    main()
