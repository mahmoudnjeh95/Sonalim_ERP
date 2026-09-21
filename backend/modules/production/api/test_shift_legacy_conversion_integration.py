"""The conversion of legacy Daily/Conditionnement reports into shift reports.

Reconciles the converted rows against the old tables that still exist, so a lost
row or a wrong sum shows up as a failing comparison. On a database with no legacy
reports every check passes trivially.
"""
from __future__ import annotations

import pytest


def one(db, sql: str, *params):
    return db.execute(sql, params).fetchone()[0]


# Reports of the original legacy data. Converted shifts get a deterministic id (26 hex characters, from
# md5), while shifts filed through the shift screen get a ULID, so the id's shape says which is which.
# Validation also writes old-shaped copies of new shifts into the legacy tables; those are not "legacy".
CONVERTED = "'^[0-9A-F]{26}$'"
LEGACY_IDS = (
    "(SELECT id FROM production.shift_runs WHERE shift_report_id ~ " + CONVERTED
    + " UNION SELECT id FROM production.shift_packing_rows WHERE shift_report_id ~ " + CONVERTED + ")"
)
# Every report in the legacy tables, whichever way it got there.
ALL_REPORT_IDS = "(SELECT id FROM production.production_reports)"


def test_every_legacy_report_became_a_run_or_a_packing_row(db):
    missing = one(
        db,
        """
        SELECT count(*) FROM production.production_reports r
        WHERE r.work_center_id IS NOT NULL AND r.shift IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM production.shift_runs x WHERE x.id = r.id)
          AND NOT EXISTS (SELECT 1 FROM production.shift_packing_rows x WHERE x.id = r.id)
        """,
    )
    assert missing == 0


def test_dailies_become_runs_and_conditionnements_become_packing_rows(db):
    assert one(db, f"SELECT count(*) FROM production.shift_runs WHERE id IN {ALL_REPORT_IDS}") == one(
        db, "SELECT count(*) FROM production.production_reports WHERE report_type = 'daily'"
    )
    assert one(db, f"SELECT count(*) FROM production.shift_packing_rows WHERE id IN {ALL_REPORT_IDS}") == one(
        db, "SELECT count(*) FROM production.production_reports WHERE report_type = 'conditionnement'"
    )


def test_one_shift_report_per_line_date_and_shift(db):
    groups = one(
        db,
        """
        SELECT count(*) FROM (
            SELECT 1 FROM production.production_reports
            WHERE work_center_id IS NOT NULL AND shift IS NOT NULL
            GROUP BY tenant_id, work_center_id, report_date, shift) g
        """,
    )
    converted = one(
        db,
        f"""
        SELECT count(DISTINCT sr.id) FROM production.shift_reports sr
        WHERE EXISTS (SELECT 1 FROM production.shift_runs x WHERE x.shift_report_id = sr.id AND x.id IN {ALL_REPORT_IDS})
           OR EXISTS (SELECT 1 FROM production.shift_packing_rows x WHERE x.shift_report_id = sr.id AND x.id IN {ALL_REPORT_IDS})
        """,
    )
    assert converted == groups


RECONCILIATIONS = {
    "finished_run_tonnage": (
        f"SELECT coalesce(sum(finished_product_quantity), 0) FROM production.daily_reports WHERE report_id IN {LEGACY_IDS}",
        f"SELECT coalesce(sum(finished_product_quantity), 0) FROM production.shift_runs WHERE id IN {LEGACY_IDS}",
    ),
    "dough": (
        f"SELECT coalesce(sum(dough_quantity), 0) FROM production.daily_reports WHERE report_id IN {LEGACY_IDS}",
        f"SELECT coalesce(sum(dough_quantity), 0) FROM production.shift_runs WHERE id IN {LEGACY_IDS}",
    ),
    "production_minutes": (
        f"SELECT coalesce(sum(production_minutes), 0) FROM production.daily_reports WHERE report_id IN {LEGACY_IDS}",
        f"SELECT coalesce(sum(production_minutes), 0) FROM production.shift_runs WHERE id IN {LEGACY_IDS}",
    ),
    "packed_tonnage": (
        f"SELECT coalesce(sum(finished_product_quantity), 0) FROM production.conditionnement_reports WHERE report_id IN {LEGACY_IDS}",
        f"SELECT coalesce(sum(finished_product_quantity), 0) FROM production.shift_packing_rows WHERE id IN {LEGACY_IDS}",
    ),
    "packets": (
        f"SELECT coalesce(sum(packets_counted), 0) FROM production.conditionnement_reports WHERE report_id IN {LEGACY_IDS}",
        f"SELECT coalesce(sum(packets_counted), 0) FROM production.shift_packing_rows WHERE id IN {LEGACY_IDS}",
    ),
    "film_carton_scotch_ruban": (
        f"SELECT coalesce(sum(film_quantity + carton_quantity + scotch_quantity + ruban_quantity), 0) FROM production.conditionnement_reports WHERE report_id IN {LEGACY_IDS}",
        f"SELECT coalesce(sum(film_quantity + carton_quantity + scotch_quantity + ruban_quantity), 0) FROM production.shift_packing_rows WHERE id IN {LEGACY_IDS}",
    ),
    "semolina": (
        f"SELECT coalesce(sum(quantity), 0) FROM production.report_semolina_lines WHERE report_id IN {LEGACY_IDS}",
        f"SELECT coalesce(sum(quantity), 0) FROM production.shift_run_semolina_lines WHERE run_id IN {LEGACY_IDS}",
    ),
    "waste": (
        f"SELECT coalesce(sum(quantity), 0) FROM production.report_waste_lines WHERE report_id IN {LEGACY_IDS}",
        "SELECT coalesce(sum(quantity), 0) FROM production.shift_waste_lines "
        f"WHERE coalesce(run_id, packing_row_id) IN {LEGACY_IDS}",
    ),
    "waste_line_count": (
        f"SELECT count(*) FROM production.report_waste_lines WHERE report_id IN {LEGACY_IDS}",
        "SELECT count(*) FROM production.shift_waste_lines "
        f"WHERE coalesce(run_id, packing_row_id) IN {LEGACY_IDS}",
    ),
    "downtime_minutes": (
        f"SELECT coalesce(sum(minutes), 0) FROM production.report_downtime_lines WHERE report_id IN {LEGACY_IDS}",
        "SELECT coalesce(sum(round(extract(epoch FROM ended_at - started_at) / 60)), 0) "
        "FROM production.machine_stops WHERE source = 'migrated'",
    ),
    "fuel": (
        f"SELECT coalesce(sum(fuel_quantity), 0) FROM production.daily_reports WHERE report_id IN {LEGACY_IDS}",
        f"SELECT coalesce(sum(fuel_quantity), 0) FROM production.shift_energy WHERE shift_report_id ~ {CONVERTED}",
    ),
    "gasoil": (
        f"SELECT coalesce(sum(gasoil_quantity), 0) FROM production.daily_reports WHERE report_id IN {LEGACY_IDS}",
        f"SELECT coalesce(sum(gasoil_quantity), 0) FROM production.shift_energy WHERE shift_report_id ~ {CONVERTED}",
    ),
    "electricity": (
        f"SELECT coalesce(sum(electricity_quantity), 0) FROM production.daily_reports WHERE report_id IN {LEGACY_IDS}",
        f"SELECT coalesce(sum(electricity_quantity), 0) FROM production.shift_energy WHERE shift_report_id ~ {CONVERTED}",
    ),
    "generator_hours": (
        f"SELECT coalesce(sum(generator_hours), 0) FROM production.daily_reports WHERE report_id IN {LEGACY_IDS}",
        f"SELECT coalesce(sum(generator_hours), 0) FROM production.shift_energy WHERE shift_report_id ~ {CONVERTED}",
    ),
}


@pytest.mark.parametrize("name", sorted(RECONCILIATIONS))
def test_sums_reconcile_with_the_legacy_tables(db, name):
    old_sql, new_sql = RECONCILIATIONS[name]
    assert one(db, new_sql) == one(db, old_sql), name


def test_posted_stock_still_points_at_existing_rows(db):
    # Runs and packing rows reuse the old report ids, so nothing in warehouse
    # needs rewriting. An orphan here would mean a stock move lost its report.
    orphan_daily = one(
        db,
        """
        SELECT count(*) FROM warehouse.stock_moves m
        WHERE m.source_type = 'production.daily_report'
          AND EXISTS (SELECT 1 FROM production.production_reports r WHERE r.id = m.source_id)
          AND NOT EXISTS (SELECT 1 FROM production.shift_runs x WHERE x.id = m.source_id)
        """,
    )
    orphan_packing = one(
        db,
        """
        SELECT count(*) FROM warehouse.stock_moves m
        WHERE m.source_type = 'production.conditionnement_report'
          AND EXISTS (SELECT 1 FROM production.production_reports r WHERE r.id = m.source_id)
          AND NOT EXISTS (SELECT 1 FROM production.shift_packing_rows x WHERE x.id = m.source_id)
        """,
    )
    assert (orphan_daily, orphan_packing) == (0, 0)


def test_every_converted_shift_has_a_state_for_each_converted_section(db):
    incomplete = one(
        db,
        f"""
        SELECT count(*) FROM production.shift_reports sr
        WHERE (EXISTS (SELECT 1 FROM production.shift_runs x WHERE x.shift_report_id = sr.id AND x.id IN {LEGACY_IDS})
            OR EXISTS (SELECT 1 FROM production.shift_packing_rows x WHERE x.shift_report_id = sr.id AND x.id IN {LEGACY_IDS}))
          AND (SELECT count(*) FROM production.shift_report_sections s
               WHERE s.shift_report_id = sr.id
                 AND s.section_key IN ('runs','waste_production','stops','packing','waste_packing','energy')) <> 6
        """,
    )
    assert incomplete == 0


def test_validated_shifts_have_only_submitted_or_nothing_to_report_sections(db):
    bad = one(
        db,
        """
        SELECT count(*) FROM production.shift_report_sections s
        JOIN production.shift_reports sr ON sr.id = s.shift_report_id
        WHERE sr.status = 'validated' AND s.status NOT IN ('submitted', 'nothing_to_report')
          AND s.section_key IN ('runs','waste_production','stops','packing','waste_packing','energy')
        """,
    )
    assert bad == 0


def test_conversion_is_safe_to_run_again(db):
    # Including after validation has copied new shifts into the legacy tables: those copies must not
    # be converted back into the shifts they came from.
    tables = ("shift_reports", "shift_report_sections", "shift_runs", "shift_packing_rows",
              "shift_run_semolina_lines", "shift_waste_lines", "machine_stops", "shift_energy",
              "shift_section_revisions")
    before = {t: one(db, f"SELECT count(*) FROM production.{t}") for t in tables}
    db.execute("SELECT production.convert_legacy_reports()")
    after = {t: one(db, f"SELECT count(*) FROM production.{t}") for t in tables}
    assert after == before


def test_a_rejected_legacy_shift_converts_to_a_returned_one(db):
    row = db.execute(
        "SELECT id, tenant_id, work_center_id, report_date, shift FROM production.shift_reports "
        "WHERE status = 'validated' AND id ~ '^[0-9A-F]{26}$' ORDER BY id LIMIT 1"
    ).fetchone()
    if row is None:
        pytest.skip("no converted shift to exercise")
    shift_id, tenant, wc, day, shift = row
    db.execute(
        "UPDATE production.production_reports SET status = 'rejected', rejection_reason = 'bad figure' "
        "WHERE tenant_id = %s AND work_center_id = %s AND report_date = %s AND shift = %s",
        (tenant, wc, day, shift),
    )
    db.execute("DELETE FROM production.shift_reports WHERE id = %s", (shift_id,))
    db.execute("SELECT production.convert_legacy_reports()")
    status, reason = db.execute(
        "SELECT status, rejection_reason FROM production.shift_reports WHERE id = %s", (shift_id,)
    ).fetchone()
    assert (status, reason) == ("returned", "bad figure")
    states = {
        r[0]
        for r in db.execute(
            "SELECT status FROM production.shift_report_sections "
            "WHERE shift_report_id = %s AND section_key = 'runs'",
            (shift_id,),
        ).fetchall()
    }
    assert states <= {"returned", "empty"}


def test_legacy_revisions_become_section_revisions_with_unique_numbers(db):
    legacy = one(
        db,
        f"SELECT count(*) FROM production.report_revisions rev WHERE rev.report_id IN {LEGACY_IDS}",
    )
    copied = one(
        db,
        "SELECT count(*) FROM production.shift_section_revisions "
        "WHERE section_key IN ('runs', 'packing') AND jsonb_exists(snapshot, 'legacy_report_id')",
    )
    assert copied == legacy
