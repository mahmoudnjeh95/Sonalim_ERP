"""Schema contract of the shift report core (milestone 1).

Runs against the migrated development database inside a transaction that is
always rolled back, like every other integration test.
"""
from __future__ import annotations

import psycopg
import pytest


@pytest.fixture
def work_center_id(db) -> str:
    row = db.execute("SELECT id FROM production.work_centers LIMIT 1").fetchone()
    if row is None:
        pytest.skip("no work center in the test database")
    return row[0]


def _insert_shift(db, work_center_id: str, *, shift: str = "morning", status: str = "open") -> None:
    db.execute(
        """
        INSERT INTO production.shift_reports (id, tenant_id, work_center_id, report_date, shift, status)
        VALUES (%s, 't-test', %s, DATE '2030-01-01', %s, %s)
        """,
        (f"SR-{shift}-{status}", work_center_id, shift, status),
    )


def test_one_shift_report_per_line_date_and_shift(db, work_center_id):
    _insert_shift(db, work_center_id)
    with pytest.raises(psycopg.errors.UniqueViolation):
        db.execute(
            """
            INSERT INTO production.shift_reports (id, tenant_id, work_center_id, report_date, shift)
            VALUES ('SR-dup', 't-test', %s, DATE '2030-01-01', 'morning')
            """,
            (work_center_id,),
        )


def test_shift_status_is_restricted(db, work_center_id):
    with pytest.raises(psycopg.errors.CheckViolation):
        _insert_shift(db, work_center_id, status="draft")


def test_section_defaults_and_open_ended_keys(db, work_center_id):
    _insert_shift(db, work_center_id)
    # 'reels' is a future section: adding one must not need a schema change.
    db.execute(
        "INSERT INTO production.shift_report_sections (shift_report_id, tenant_id, section_key) "
        "VALUES ('SR-morning-open', 't-test', 'reels')"
    )
    status, revision, revised = db.execute(
        "SELECT status, revision, revised_after_submit FROM production.shift_report_sections "
        "WHERE shift_report_id = 'SR-morning-open'"
    ).fetchone()
    assert (status, revision, revised) == ("empty", 0, False)


def test_section_status_is_restricted(db, work_center_id):
    _insert_shift(db, work_center_id)
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(
            "INSERT INTO production.shift_report_sections (shift_report_id, tenant_id, section_key, status) "
            "VALUES ('SR-morning-open', 't-test', 'runs', 'validated')"
        )


def test_section_revision_numbers_are_unique_per_section(db, work_center_id):
    _insert_shift(db, work_center_id)
    insert = (
        "INSERT INTO production.shift_section_revisions "
        "(id, tenant_id, shift_report_id, section_key, revision, snapshot) "
        "VALUES (%s, 't-test', 'SR-morning-open', 'runs', 1, '{}'::jsonb)"
    )
    db.execute(insert, ("rev-1",))
    with pytest.raises(psycopg.errors.UniqueViolation):
        db.execute(insert, ("rev-2",))


def _columns(db, table: str) -> set[str]:
    rows = db.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'production' AND table_name = %s",
        (table,),
    ).fetchall()
    return {r[0] for r in rows}


def test_run_carries_every_daily_figure_plus_the_new_fields(db):
    cols = _columns(db, "shift_runs")
    daily = _columns(db, "daily_reports")
    # Energy moved to shift_energy; report_id becomes id; the rest carries over.
    energy = {"fuel_quantity", "electricity_quantity", "gasoil_quantity", "fuel_supplier_id",
              "gasoil_supplier_id", "gasoil_flow_rate", "generator_hours"}
    carried = daily - {"report_id", "tenant_id"} - energy
    assert carried <= cols, sorted(carried - cols)
    assert {"lot_number", "humidity_percentage", "shift_report_id", "of_id", "equipment_id"} <= cols


def test_packing_row_carries_every_conditionnement_figure(db):
    cols = _columns(db, "shift_packing_rows")
    legacy = _columns(db, "conditionnement_reports")
    carried = legacy - {"report_id", "tenant_id", "daily_report_id"}
    assert carried <= cols, sorted(carried - cols)
    assert {"run_id", "packing_type", "film_type", "shift_report_id", "of_id", "equipment_id"} <= cols


def test_energy_is_one_row_per_shift(db):
    assert {"shift_report_id", "fuel_quantity", "gasoil_quantity", "electricity_quantity",
            "generator_hours", "gasoil_flow_rate"} <= _columns(db, "shift_energy")
    pk = db.execute(
        "SELECT a.attname FROM pg_index i JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey) "
        "WHERE i.indrelid = 'production.shift_energy'::regclass AND i.indisprimary"
    ).fetchall()
    assert [r[0] for r in pk] == ["shift_report_id"]


def test_machine_stop_rejects_an_end_before_its_start(db, work_center_id):
    _insert_shift(db, work_center_id)
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(
            "INSERT INTO production.machine_stops (id, tenant_id, shift_report_id, started_at, ended_at) "
            "VALUES ('st-1', 't-test', 'SR-morning-open', '2030-01-01 10:00+00', '2030-01-01 09:00+00')"
        )


def test_machine_stop_allows_an_open_stop_and_names_its_source(db, work_center_id):
    _insert_shift(db, work_center_id)
    db.execute(
        "INSERT INTO production.machine_stops (id, tenant_id, shift_report_id, started_at) "
        "VALUES ('st-2', 't-test', 'SR-morning-open', '2030-01-01 10:00+00')"
    )
    assert db.execute("SELECT source, ended_at FROM production.machine_stops WHERE id = 'st-2'").fetchone() == ("manual", None)
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(
            "INSERT INTO production.machine_stops (id, tenant_id, shift_report_id, started_at, source) "
            "VALUES ('st-3', 't-test', 'SR-morning-open', '2030-01-01 10:00+00', 'guess')"
        )


def test_waste_line_belongs_to_at_most_one_owner(db):
    checks = db.execute(
        "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
        "WHERE conrelid = 'production.shift_waste_lines'::regclass AND contype = 'c'"
    ).fetchall()
    assert any("num_nonnulls" in c[0] for c in checks)


# ---- migration 0050: the small sections ------------------------------------


@pytest.mark.parametrize(
    "table", ["shift_silo_states", "shift_staffing", "shift_mold_washes", "shift_packet_checks"]
)
def test_small_section_tables_exist(db, table):
    assert _columns(db, table), table


def test_silo_state_is_unique_per_side_and_phase(db, work_center_id):
    _insert_shift(db, work_center_id)
    insert = (
        "INSERT INTO production.shift_silo_states (id, tenant_id, shift_report_id, side, phase) "
        "VALUES (%s, 't-test', 'SR-morning-open', 'production', 'start')"
    )
    db.execute(insert, ("silo-1",))
    with pytest.raises(psycopg.errors.UniqueViolation):
        db.execute(insert, ("silo-2",))


def test_silo_level_is_a_percentage(db, work_center_id):
    _insert_shift(db, work_center_id)
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(
            "INSERT INTO production.shift_silo_states (id, tenant_id, shift_report_id, side, phase, level_percent) "
            "VALUES ('silo-3', 't-test', 'SR-morning-open', 'packing', 'end', 130)"
        )


def test_deleting_a_run_keeps_its_waste_line(db, work_center_id):
    row = db.execute("SELECT id FROM production.work_orders LIMIT 1").fetchone()
    if row is None:
        pytest.skip("no work order in the test database")
    _insert_shift(db, work_center_id)
    db.execute(
        "INSERT INTO production.shift_runs (id, tenant_id, shift_report_id, of_id) "
        "VALUES ('run-1', 't-test', 'SR-morning-open', %s)",
        (row[0],),
    )
    db.execute(
        "INSERT INTO production.shift_waste_lines (id, tenant_id, shift_report_id, section_key, run_id, category) "
        "VALUES ('w-1', 't-test', 'SR-morning-open', 'waste_production', 'run-1', 'x')"
    )
    db.execute("DELETE FROM production.shift_runs WHERE id = 'run-1'")
    assert db.execute("SELECT run_id FROM production.shift_waste_lines WHERE id = 'w-1'").fetchone() == (None,)


def test_existing_shifts_have_the_three_new_section_rows(db):
    missing = db.execute(
        """
        SELECT count(*) FROM production.shift_reports sr
        CROSS JOIN (VALUES ('silo'), ('staffing'), ('packet_checks')) k(section_key)
        WHERE sr.id IN (SELECT shift_report_id FROM production.shift_runs)
          AND NOT EXISTS (SELECT 1 FROM production.shift_report_sections s
                          WHERE s.shift_report_id = sr.id AND s.section_key = k.section_key)
        """
    ).fetchone()[0]
    assert missing == 0
