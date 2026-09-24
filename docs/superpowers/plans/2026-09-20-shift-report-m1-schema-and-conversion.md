# Shift report core — Milestone 1: schema and conversion

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the shift-report tables next to the existing report tables and convert every existing Daily/Conditionnement report into them, with no behaviour change to the running app.

**Architecture:** Three additive SQL migrations create the core, the section tables, and a re-runnable SQL function `production.convert_legacy_reports()` that copies legacy data into them (deterministic ids, `ON CONFLICT DO NOTHING`). A migrated run reuses its old Daily report id and a migrated packing row its old Conditionnement report id, so posted `warehouse.stock_moves` / `warehouse.lots` (`source_id`) stay valid. Old tables are untouched; cutover to views is milestone 3.

**Tech Stack:** PostgreSQL (plain-SQL migrations run by `core/migrations/runner.py`), Python 3 + psycopg 3, pytest with the `db` fixture in `backend/conftest.py` (real dev database, every test rolls back).

**Spec:** `docs/superpowers/specs/2026-09-20-shift-report-core-design.md` (sections 4, 5.5, 6).

**Later plans** (written when the previous milestone lands): M2 section tables + services + permissions; M3 validate/reject/reverse + cutover; M4 shift screen; M5 Validation Center; M6 readers moved, views dropped.

## Global Constraints

- New migrations continue after `0046`: `0047`, `0048`, `0049` in `backend/modules/production/migrations/`.
- Migrations are plain SQL, additive, and idempotent (`CREATE TABLE IF NOT EXISTS`, `CREATE OR REPLACE FUNCTION`). They run in one connection with no bind parameters.
- No foreign key to `maintenance.*` and no read of it: `equipment_id` is an opaque text id (maintenance migrates after production).
- Do not touch the `warehouse` schema or any old report table.
- Section keys are not constrained by a CHECK (new sections must not need a schema change): `runs`, `waste_production`, `stops`, `packing`, `waste_packing`, `energy` in this milestone.
- Tests use the `db` fixture only (rolled back); no test may commit.
- Git: the branch carries a lot of uncommitted work from earlier sessions. **Do not commit** unless the owner asks; the "checkpoint" steps below only run tests.
- Working directory for commands: `D:/mahmoud repo/Sonalim_ERP/backend`. Python: `.venv/Scripts/python.exe`. DB: `postgresql://erp:erp@localhost:5432/erp`.

---

### Task 1: Core tables (`shift_reports`, sections, revisions)

**Files:**
- Create: `backend/modules/production/migrations/0047_production_shift_reports.sql`
- Test: `backend/modules/production/api/test_shift_schema_integration.py`

**Produces:** tables `production.shift_reports`, `production.shift_report_sections`, `production.shift_section_revisions` exactly as below (later tasks and milestones rely on the names).

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest modules/production/api/test_shift_schema_integration.py -v`
Expected: FAIL — `relation "production.shift_reports" does not exist` (or tests error at insert).

- [ ] **Step 3: Write the migration**

```sql
-- Shift report core (shift-report program, project 1, milestone 1).
--
-- One report per line, date and shift replaces the two report types (Daily and
-- Conditionnement) a team filed separately. This migration only ADDS the core:
-- nothing here changes or reads the old report tables, and the running app is
-- unaffected until the cutover milestone.
--
-- Section state lives only in shift_report_sections. section_key has no CHECK on
-- purpose: a new section (bobines, paramètres) is a new key plus its own data
-- table, never a change to this schema.
CREATE TABLE IF NOT EXISTS production.shift_reports (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    work_center_id TEXT NOT NULL REFERENCES production.work_centers (id),
    report_date DATE NOT NULL,
    shift TEXT NOT NULL,
    team TEXT,
    -- The people on the paper header. Free text, not linked to user accounts.
    conducteur TEXT,
    agent_fabrication TEXT,
    machiniste TEXT,
    aide_machiniste TEXT,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'submitted', 'validated', 'returned')),
    revision INTEGER NOT NULL DEFAULT 1,
    created_by TEXT,
    submitted_at TIMESTAMPTZ,
    validated_by TEXT,
    validated_at TIMESTAMPTZ,
    rejection_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, work_center_id, report_date, shift)
);

CREATE INDEX IF NOT EXISTS shift_reports_tenant_date_idx
    ON production.shift_reports (tenant_id, report_date DESC);

CREATE TABLE IF NOT EXISTS production.shift_report_sections (
    shift_report_id TEXT NOT NULL REFERENCES production.shift_reports (id) ON DELETE CASCADE,
    tenant_id TEXT NOT NULL,
    section_key TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'empty'
        CHECK (status IN ('empty', 'draft', 'submitted', 'nothing_to_report', 'returned')),
    -- How many revisions have been frozen for this section.
    revision INTEGER NOT NULL DEFAULT 0,
    -- Set when a submitted section is edited; cleared at validation.
    revised_after_submit BOOLEAN NOT NULL DEFAULT FALSE,
    submitted_by TEXT,
    submitted_at TIMESTAMPTZ,
    return_reason TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (shift_report_id, section_key)
);

CREATE TABLE IF NOT EXISTS production.shift_section_revisions (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    shift_report_id TEXT NOT NULL REFERENCES production.shift_reports (id) ON DELETE CASCADE,
    -- '*' is the whole-shift snapshot frozen at validation.
    section_key TEXT NOT NULL,
    revision INTEGER NOT NULL,
    snapshot JSONB NOT NULL,
    reason TEXT,
    actor_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (shift_report_id, section_key, revision)
);
```

- [ ] **Step 4: Apply the migration and run the test to verify it passes**

Run:
```
DATABASE_URL=postgresql://erp:erp@localhost:5432/erp .venv/Scripts/python.exe -c "from core.migrations.runner import apply_all_migrations; apply_all_migrations()"
.venv/Scripts/python.exe -m pytest modules/production/api/test_shift_schema_integration.py -v
```
Expected: 5 passed.

- [ ] **Step 5: Checkpoint** — no commit (see Global Constraints). Confirm `git status` lists only the two new files for this task.

---

### Task 2: Section tables (runs, packing, semoule, waste, stops, energy)

**Files:**
- Create: `backend/modules/production/migrations/0048_production_shift_sections.sql`
- Test: `backend/modules/production/api/test_shift_schema_integration.py` (append)

**Consumes:** `production.shift_reports(id)` from Task 1.
**Produces:** `production.shift_runs`, `shift_packing_rows`, `shift_run_semolina_lines`, `shift_waste_lines`, `machine_stops`, `shift_energy` with the columns below. `shift_runs.id` / `shift_packing_rows.id` are caller-supplied text ids (migrated rows reuse the old report id).

- [ ] **Step 1: Append the failing tests**

```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest modules/production/api/test_shift_schema_integration.py -v`
Expected: the six new tests FAIL (`relation ... does not exist`); the first five still pass.

- [ ] **Step 3: Write the migration**

```sql
-- Shift report core, milestone 1 (part 2): the typed section tables.
--
-- A migrated run reuses its old Daily report id and a migrated packing row its old
-- Conditionnement report id. Posted warehouse stock moves and lots carry that id
-- as source_id, so they stay valid without any write into the warehouse module.
--
-- equipment_id is an opaque reference into maintenance.equipment. It is not a
-- foreign key: maintenance owns that table and migrates after production.
CREATE TABLE IF NOT EXISTS production.shift_runs (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    shift_report_id TEXT NOT NULL REFERENCES production.shift_reports (id) ON DELETE CASCADE,
    of_id TEXT NOT NULL REFERENCES production.work_orders (id),
    equipment_id TEXT,
    mold_id TEXT,
    lot_number TEXT,
    start_time TIME,
    end_time TIME,
    production_minutes INTEGER NOT NULL DEFAULT 0,
    dough_quantity NUMERIC NOT NULL DEFAULT 0,
    finished_product_quantity NUMERIC NOT NULL DEFAULT 0,
    regrind_quantity NUMERIC NOT NULL DEFAULT 0,
    regrind_input_quantity NUMERIC NOT NULL DEFAULT 0,
    regrind_input_product_id TEXT,
    regrind_product_id TEXT,
    raw_material_location_id TEXT,
    water_quantity NUMERIC NOT NULL DEFAULT 0,
    water_percentage NUMERIC NOT NULL DEFAULT 0,
    -- New: the dough humidity the team measures on the paper fiche.
    humidity_percentage NUMERIC,
    semolina_flow_rate NUMERIC NOT NULL DEFAULT 0,
    shortfall_comment TEXT,
    line_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS shift_runs_shift_idx ON production.shift_runs (shift_report_id);
CREATE INDEX IF NOT EXISTS shift_runs_of_idx ON production.shift_runs (tenant_id, of_id);

CREATE TABLE IF NOT EXISTS production.shift_packing_rows (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    shift_report_id TEXT NOT NULL REFERENCES production.shift_reports (id) ON DELETE CASCADE,
    of_id TEXT NOT NULL REFERENCES production.work_orders (id),
    -- The run this packing draws from (old conditionnement_reports.daily_report_id).
    run_id TEXT REFERENCES production.shift_runs (id) ON DELETE SET NULL,
    equipment_id TEXT,
    -- New: "type de conditionnement" and "type film" from the paper fiche.
    packing_type TEXT,
    film_type TEXT,
    finished_product_quantity NUMERIC NOT NULL DEFAULT 0,
    packets_counted NUMERIC NOT NULL DEFAULT 0,
    film_quantity NUMERIC NOT NULL DEFAULT 0,
    carton_quantity NUMERIC NOT NULL DEFAULT 0,
    tape_quantity NUMERIC NOT NULL DEFAULT 0,
    scotch_quantity NUMERIC NOT NULL DEFAULT 0,
    ruban_quantity NUMERIC NOT NULL DEFAULT 0,
    waste_carton_quantity NUMERIC NOT NULL DEFAULT 0,
    machine_speed NUMERIC,
    production_minutes INTEGER NOT NULL DEFAULT 0,
    -- Kept as-is from the old report: the summary arrêt fields pre-date arrêt lines.
    downtime_minutes INTEGER NOT NULL DEFAULT 0,
    downtime_reason TEXT,
    downtime_note TEXT,
    lot_number TEXT,
    dlc_date DATE,
    film_product_id TEXT,
    carton_product_id TEXT,
    tape_product_id TEXT,
    scotch_product_id TEXT,
    ruban_product_id TEXT,
    film_supplier_id TEXT,
    carton_supplier_id TEXT,
    tape_supplier_id TEXT,
    scotch_supplier_id TEXT,
    ruban_supplier_id TEXT,
    packaging_location_id TEXT,
    finished_goods_location_id TEXT,
    snapshot_net_weight_grams NUMERIC,
    snapshot_packets_per_carton NUMERIC,
    shortfall_comment TEXT,
    line_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS shift_packing_rows_shift_idx ON production.shift_packing_rows (shift_report_id);
CREATE INDEX IF NOT EXISTS shift_packing_rows_of_idx ON production.shift_packing_rows (tenant_id, of_id);

CREATE TABLE IF NOT EXISTS production.shift_run_semolina_lines (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    run_id TEXT NOT NULL REFERENCES production.shift_runs (id) ON DELETE CASCADE,
    product_id TEXT,
    quantity NUMERIC NOT NULL DEFAULT 0,
    location_id TEXT,
    -- New: what the paper fiche also records for each semoule row.
    bag_count NUMERIC,
    lot_number TEXT,
    line_order INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS shift_run_semolina_lines_run_idx ON production.shift_run_semolina_lines (run_id);

CREATE TABLE IF NOT EXISTS production.shift_waste_lines (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    shift_report_id TEXT NOT NULL REFERENCES production.shift_reports (id) ON DELETE CASCADE,
    -- 'waste_production' or 'waste_packing': which section the row was entered in.
    section_key TEXT NOT NULL,
    run_id TEXT REFERENCES production.shift_runs (id) ON DELETE CASCADE,
    packing_row_id TEXT REFERENCES production.shift_packing_rows (id) ON DELETE CASCADE,
    category TEXT NOT NULL,
    product_id TEXT,
    quantity NUMERIC NOT NULL DEFAULT 0,
    note TEXT,
    -- New: the paper fiche records when the waste happened and which lot.
    occurred_at TIMESTAMPTZ,
    lot_number TEXT,
    line_order INTEGER NOT NULL DEFAULT 0,
    CONSTRAINT shift_waste_lines_one_owner CHECK (num_nonnulls(run_id, packing_row_id) <= 1)
);
CREATE INDEX IF NOT EXISTS shift_waste_lines_shift_idx ON production.shift_waste_lines (shift_report_id);

CREATE TABLE IF NOT EXISTS production.machine_stops (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    shift_report_id TEXT NOT NULL REFERENCES production.shift_reports (id) ON DELETE CASCADE,
    run_id TEXT REFERENCES production.shift_runs (id) ON DELETE SET NULL,
    packing_row_id TEXT REFERENCES production.shift_packing_rows (id) ON DELETE SET NULL,
    -- Opaque id into maintenance.equipment; NULL when the machine is unknown.
    equipment_id TEXT,
    started_at TIMESTAMPTZ NOT NULL,
    -- NULL while the stop is ongoing.
    ended_at TIMESTAMPTZ,
    downtime_type TEXT,
    classification TEXT,
    motif TEXT,
    note TEXT,
    corrective_action TEXT,
    -- live: pressed Stop in the moment; added_after: typed in after the fact;
    -- manual: entered in the shift screen; migrated: converted from minutes-only lines.
    source TEXT NOT NULL DEFAULT 'manual' CHECK (source IN ('live', 'added_after', 'manual', 'migrated')),
    line_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT machine_stops_end_after_start CHECK (ended_at IS NULL OR ended_at >= started_at)
);
CREATE INDEX IF NOT EXISTS machine_stops_shift_idx ON production.machine_stops (shift_report_id);
CREATE INDEX IF NOT EXISTS machine_stops_open_idx ON production.machine_stops (tenant_id, equipment_id) WHERE ended_at IS NULL;

-- Energy is typed once for the shift. Per-run shares are derived at read time.
CREATE TABLE IF NOT EXISTS production.shift_energy (
    shift_report_id TEXT PRIMARY KEY REFERENCES production.shift_reports (id) ON DELETE CASCADE,
    tenant_id TEXT NOT NULL,
    fuel_quantity NUMERIC NOT NULL DEFAULT 0,
    fuel_supplier_id TEXT,
    gasoil_quantity NUMERIC NOT NULL DEFAULT 0,
    gasoil_supplier_id TEXT,
    gasoil_flow_rate NUMERIC NOT NULL DEFAULT 0,
    generator_hours NUMERIC NOT NULL DEFAULT 0,
    electricity_quantity NUMERIC NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

- [ ] **Step 4: Apply and run**

Run:
```
DATABASE_URL=postgresql://erp:erp@localhost:5432/erp .venv/Scripts/python.exe -c "from core.migrations.runner import apply_all_migrations; apply_all_migrations()"
.venv/Scripts/python.exe -m pytest modules/production/api/test_shift_schema_integration.py -v
```
Expected: 11 passed. If `test_run_carries_every_daily_figure...` names a missing column, add it to `shift_runs` in the migration (the migration is not yet in production use, so edit `0048` and re-apply after `DROP TABLE production.shift_runs CASCADE` on the dev DB).

- [ ] **Step 5: Checkpoint** — no commit.

---

### Task 3: Convert existing reports

**Files:**
- Create: `backend/modules/production/migrations/0049_production_convert_legacy_reports.sql`
- Test: `backend/modules/production/api/test_shift_legacy_conversion_integration.py`

**Consumes:** every table from Tasks 1-2 and the old tables `production_reports`, `daily_reports`, `conditionnement_reports`, `report_semolina_lines`, `report_waste_lines`, `report_downtime_lines`, `report_revisions`, `shift_windows`.
**Produces:** SQL function `production.convert_legacy_reports() RETURNS INTEGER` (total shift reports afterwards). Idempotent. Section rows created here: `runs`, `waste_production`, `stops`, `packing`, `waste_packing`, `energy` (M2 adds the other section rows).

Rules: group by (tenant, work center, date, shift), skipping legacy rows with a NULL work center or shift; shift status = validated if all validated, else returned if any rejected, else open if any draft, else submitted; a section with data takes the shift's state (open→draft, returned→returned, else submitted); a section without data is `nothing_to_report` on submitted/validated shifts and `empty` otherwise; arrêt lines become `machine_stops` (`source = 'migrated'`) laid out sequentially from the shift window's start; energy is summed per shift; old revisions become section revisions of `runs` / `packing`.

- [ ] **Step 1: Write the failing tests**

```python
"""The conversion of legacy Daily/Conditionnement reports into shift reports.

Reconciles the converted rows against the old tables that still exist, so a lost
row or a wrong sum shows up as a failing comparison. On a database with no legacy
reports every check passes trivially.
"""
from __future__ import annotations

import pytest


def one(db, sql: str, *params):
    return db.execute(sql, params).fetchone()[0]


LEGACY_IDS = "(SELECT id FROM production.production_reports)"


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
    assert one(db, f"SELECT count(*) FROM production.shift_runs WHERE id IN {LEGACY_IDS}") == one(
        db, "SELECT count(*) FROM production.production_reports WHERE report_type = 'daily'"
    )
    assert one(db, f"SELECT count(*) FROM production.shift_packing_rows WHERE id IN {LEGACY_IDS}") == one(
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
        """
        SELECT count(DISTINCT sr.id) FROM production.shift_reports sr
        WHERE EXISTS (SELECT 1 FROM production.shift_runs x WHERE x.shift_report_id = sr.id AND x.id IN (SELECT id FROM production.production_reports))
           OR EXISTS (SELECT 1 FROM production.shift_packing_rows x WHERE x.shift_report_id = sr.id AND x.id IN (SELECT id FROM production.production_reports))
        """,
    )
    assert converted == groups


RECONCILIATIONS = {
    "finished_run_tonnage": (
        "SELECT coalesce(sum(finished_product_quantity), 0) FROM production.daily_reports",
        f"SELECT coalesce(sum(finished_product_quantity), 0) FROM production.shift_runs WHERE id IN {LEGACY_IDS}",
    ),
    "dough": (
        "SELECT coalesce(sum(dough_quantity), 0) FROM production.daily_reports",
        f"SELECT coalesce(sum(dough_quantity), 0) FROM production.shift_runs WHERE id IN {LEGACY_IDS}",
    ),
    "production_minutes": (
        "SELECT coalesce(sum(production_minutes), 0) FROM production.daily_reports",
        f"SELECT coalesce(sum(production_minutes), 0) FROM production.shift_runs WHERE id IN {LEGACY_IDS}",
    ),
    "packed_tonnage": (
        "SELECT coalesce(sum(finished_product_quantity), 0) FROM production.conditionnement_reports",
        f"SELECT coalesce(sum(finished_product_quantity), 0) FROM production.shift_packing_rows WHERE id IN {LEGACY_IDS}",
    ),
    "packets": (
        "SELECT coalesce(sum(packets_counted), 0) FROM production.conditionnement_reports",
        f"SELECT coalesce(sum(packets_counted), 0) FROM production.shift_packing_rows WHERE id IN {LEGACY_IDS}",
    ),
    "film_carton_scotch_ruban": (
        "SELECT coalesce(sum(film_quantity + carton_quantity + scotch_quantity + ruban_quantity), 0) FROM production.conditionnement_reports",
        f"SELECT coalesce(sum(film_quantity + carton_quantity + scotch_quantity + ruban_quantity), 0) FROM production.shift_packing_rows WHERE id IN {LEGACY_IDS}",
    ),
    "semolina": (
        "SELECT coalesce(sum(quantity), 0) FROM production.report_semolina_lines",
        f"SELECT coalesce(sum(quantity), 0) FROM production.shift_run_semolina_lines WHERE run_id IN {LEGACY_IDS}",
    ),
    "waste": (
        "SELECT coalesce(sum(quantity), 0) FROM production.report_waste_lines",
        "SELECT coalesce(sum(quantity), 0) FROM production.shift_waste_lines "
        f"WHERE coalesce(run_id, packing_row_id) IN {LEGACY_IDS}",
    ),
    "waste_line_count": (
        "SELECT count(*) FROM production.report_waste_lines",
        "SELECT count(*) FROM production.shift_waste_lines "
        f"WHERE coalesce(run_id, packing_row_id) IN {LEGACY_IDS}",
    ),
    "downtime_minutes": (
        "SELECT coalesce(sum(minutes), 0) FROM production.report_downtime_lines",
        "SELECT coalesce(sum(round(extract(epoch FROM ended_at - started_at) / 60)), 0) "
        "FROM production.machine_stops WHERE source = 'migrated'",
    ),
    "fuel": (
        "SELECT coalesce(sum(fuel_quantity), 0) FROM production.daily_reports",
        "SELECT coalesce(sum(fuel_quantity), 0) FROM production.shift_energy",
    ),
    "gasoil": (
        "SELECT coalesce(sum(gasoil_quantity), 0) FROM production.daily_reports",
        "SELECT coalesce(sum(gasoil_quantity), 0) FROM production.shift_energy",
    ),
    "electricity": (
        "SELECT coalesce(sum(electricity_quantity), 0) FROM production.daily_reports",
        "SELECT coalesce(sum(electricity_quantity), 0) FROM production.shift_energy",
    ),
    "generator_hours": (
        "SELECT coalesce(sum(generator_hours), 0) FROM production.daily_reports",
        "SELECT coalesce(sum(generator_hours), 0) FROM production.shift_energy",
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
        "WHERE status = 'validated' ORDER BY id LIMIT 1"
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
        "SELECT count(*) FROM production.report_revisions rev "
        "WHERE rev.report_id IN (SELECT id FROM production.shift_runs UNION SELECT id FROM production.shift_packing_rows)",
    )
    copied = one(db, "SELECT count(*) FROM production.shift_section_revisions WHERE section_key IN ('runs', 'packing')")
    assert copied == legacy
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest modules/production/api/test_shift_legacy_conversion_integration.py -v`
Expected: FAIL — most tests fail because the tables are empty (`shift_runs` count 0 vs legacy count) and `production.convert_legacy_reports()` does not exist for the re-run tests.

- [ ] **Step 3: Write the migration**

```sql
-- Shift report core, milestone 1 (part 3): convert existing reports.
--
-- A SQL function so tests can re-run it; safe to call repeatedly (deterministic ids
-- and ON CONFLICT DO NOTHING). It reads only production tables. It is dropped at
-- cutover, when the old tables become compatibility views.
--
-- A run reuses its old Daily report id and a packing row its old Conditionnement
-- report id, which is why posted warehouse stock needs no rewriting.
CREATE OR REPLACE FUNCTION production.convert_legacy_reports() RETURNS INTEGER
LANGUAGE plpgsql AS $$
DECLARE
    total INTEGER;
BEGIN
    -- 1. One shift report per (tenant, line, date, shift). Legacy rows with no line
    --    or no shift cannot be grouped and are left behind.
    INSERT INTO production.shift_reports (
        id, tenant_id, work_center_id, report_date, shift, team, status, revision,
        created_by, submitted_at, validated_by, validated_at, rejection_reason, created_at, updated_at
    )
    SELECT
        upper(substr(md5(r.tenant_id || '|' || r.work_center_id || '|' || r.report_date::text || '|' || r.shift), 1, 26)),
        r.tenant_id, r.work_center_id, r.report_date, r.shift,
        min(r.team),
        CASE
            WHEN bool_and(r.status = 'validated') THEN 'validated'
            WHEN bool_or(r.status = 'rejected') THEN 'returned'
            WHEN bool_or(r.status = 'draft') THEN 'open'
            ELSE 'submitted'
        END,
        1,
        min(r.created_by),
        max(r.submitted_at),
        CASE WHEN bool_and(r.status = 'validated') THEN max(r.validated_by) END,
        CASE WHEN bool_and(r.status = 'validated') THEN max(r.validated_at) END,
        max(r.rejection_reason) FILTER (WHERE r.status = 'rejected'),
        min(r.created_at),
        max(r.updated_at)
    FROM production.production_reports r
    WHERE r.work_center_id IS NOT NULL AND r.shift IS NOT NULL
    GROUP BY r.tenant_id, r.work_center_id, r.report_date, r.shift
    ON CONFLICT DO NOTHING;

    -- 2. Runs (old Daily reports).
    INSERT INTO production.shift_runs (
        id, tenant_id, shift_report_id, of_id, equipment_id, mold_id, start_time, end_time,
        production_minutes, dough_quantity, finished_product_quantity, regrind_quantity,
        regrind_input_quantity, regrind_input_product_id, regrind_product_id, raw_material_location_id,
        water_quantity, water_percentage, semolina_flow_rate, shortfall_comment, line_order,
        created_at, updated_at
    )
    SELECT
        r.id, r.tenant_id, sr.id, r.of_id, r.equipment_id, d.mold_id, d.start_time, d.end_time,
        d.production_minutes, d.dough_quantity, d.finished_product_quantity, d.regrind_quantity,
        d.regrind_input_quantity, d.regrind_input_product_id, d.regrind_product_id, d.raw_material_location_id,
        d.water_quantity, d.water_percentage, d.semolina_flow_rate, r.shortfall_comment,
        (row_number() OVER (PARTITION BY sr.id ORDER BY d.start_time NULLS LAST, r.created_at, r.id) - 1)::int,
        r.created_at, r.updated_at
    FROM production.production_reports r
    JOIN production.daily_reports d ON d.report_id = r.id AND d.tenant_id = r.tenant_id
    JOIN production.shift_reports sr
        ON sr.tenant_id = r.tenant_id AND sr.work_center_id = r.work_center_id
       AND sr.report_date = r.report_date AND sr.shift = r.shift
    WHERE r.report_type = 'daily'
    ON CONFLICT DO NOTHING;

    -- 3. Packing rows (old Conditionnement reports). run_id is the linked Daily
    --    report only when that Daily was itself converted.
    INSERT INTO production.shift_packing_rows (
        id, tenant_id, shift_report_id, of_id, run_id, equipment_id,
        finished_product_quantity, packets_counted, film_quantity, carton_quantity, tape_quantity,
        scotch_quantity, ruban_quantity, waste_carton_quantity, machine_speed, production_minutes,
        downtime_minutes, downtime_reason, downtime_note, lot_number, dlc_date,
        film_product_id, carton_product_id, tape_product_id, scotch_product_id, ruban_product_id,
        film_supplier_id, carton_supplier_id, tape_supplier_id, scotch_supplier_id, ruban_supplier_id,
        packaging_location_id, finished_goods_location_id, snapshot_net_weight_grams,
        snapshot_packets_per_carton, shortfall_comment, line_order, created_at, updated_at
    )
    SELECT
        r.id, r.tenant_id, sr.id, r.of_id, run.id, r.equipment_id,
        c.finished_product_quantity, c.packets_counted, c.film_quantity, c.carton_quantity, c.tape_quantity,
        c.scotch_quantity, c.ruban_quantity, c.waste_carton_quantity, c.machine_speed, c.production_minutes,
        c.downtime_minutes, c.downtime_reason, c.downtime_note, c.lot_number, c.dlc_date,
        c.film_product_id, c.carton_product_id, c.tape_product_id, c.scotch_product_id, c.ruban_product_id,
        c.film_supplier_id, c.carton_supplier_id, c.tape_supplier_id, c.scotch_supplier_id, c.ruban_supplier_id,
        c.packaging_location_id, c.finished_goods_location_id, c.snapshot_net_weight_grams,
        c.snapshot_packets_per_carton, r.shortfall_comment,
        (row_number() OVER (PARTITION BY sr.id ORDER BY r.created_at, r.id) - 1)::int,
        r.created_at, r.updated_at
    FROM production.production_reports r
    JOIN production.conditionnement_reports c ON c.report_id = r.id AND c.tenant_id = r.tenant_id
    JOIN production.shift_reports sr
        ON sr.tenant_id = r.tenant_id AND sr.work_center_id = r.work_center_id
       AND sr.report_date = r.report_date AND sr.shift = r.shift
    LEFT JOIN production.shift_runs run ON run.id = c.daily_report_id
    WHERE r.report_type = 'conditionnement'
    ON CONFLICT DO NOTHING;

    -- 4. Semoule lines.
    INSERT INTO production.shift_run_semolina_lines (id, tenant_id, run_id, product_id, quantity, location_id, line_order)
    SELECT l.id, l.tenant_id, l.report_id, l.product_id, l.quantity, l.location_id, l.line_order
    FROM production.report_semolina_lines l
    JOIN production.shift_runs run ON run.id = l.report_id
    ON CONFLICT DO NOTHING;

    -- 5. Waste lines: a line of a Daily report belongs to a run, of a Conditionnement to a packing row.
    INSERT INTO production.shift_waste_lines (
        id, tenant_id, shift_report_id, section_key, run_id, packing_row_id,
        category, product_id, quantity, note, line_order
    )
    SELECT
        w.id, w.tenant_id, COALESCE(run.shift_report_id, pk.shift_report_id),
        CASE WHEN run.id IS NOT NULL THEN 'waste_production' ELSE 'waste_packing' END,
        run.id, pk.id, w.category, w.product_id, w.quantity, w.note, w.line_order
    FROM production.report_waste_lines w
    LEFT JOIN production.shift_runs run ON run.id = w.report_id
    LEFT JOIN production.shift_packing_rows pk ON pk.id = w.report_id
    WHERE run.id IS NOT NULL OR pk.id IS NOT NULL
    ON CONFLICT DO NOTHING;

    -- 6. Arrêts: minutes-only lines become stop events laid out one after another
    --    from the start of the shift window. The machine is the report's own
    --    equipment when it had one, otherwise unknown.
    INSERT INTO production.machine_stops (
        id, tenant_id, shift_report_id, run_id, packing_row_id, equipment_id,
        started_at, ended_at, downtime_type, classification, motif, note, source, line_order
    )
    SELECT
        x.id, x.tenant_id, x.shift_report_id, x.run_id, x.packing_row_id, x.equipment_id,
        x.shift_start + make_interval(mins => x.offset_minutes),
        x.shift_start + make_interval(mins => x.offset_minutes + x.minutes),
        x.downtime_type, x.classification, x.motif, x.note, 'migrated', x.line_order
    FROM (
        SELECT
            l.id, l.tenant_id, sr.id AS shift_report_id, run.id AS run_id, pk.id AS packing_row_id,
            r.equipment_id, l.minutes, l.downtime_type, l.classification, l.motif, l.note, l.line_order,
            (sr.report_date + COALESCE(sw.start_time, TIME '00:00'))::timestamptz AS shift_start,
            COALESCE(
                SUM(l.minutes) OVER (
                    PARTITION BY sr.id
                    ORDER BY (pk.id IS NOT NULL), l.report_id, l.line_order, l.id
                    ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                ), 0
            )::int AS offset_minutes
        FROM production.report_downtime_lines l
        JOIN production.production_reports r ON r.id = l.report_id
        LEFT JOIN production.shift_runs run ON run.id = l.report_id
        LEFT JOIN production.shift_packing_rows pk ON pk.id = l.report_id
        JOIN production.shift_reports sr ON sr.id = COALESCE(run.shift_report_id, pk.shift_report_id)
        LEFT JOIN production.shift_windows sw ON sw.tenant_id = sr.tenant_id AND sw.shift = sr.shift
    ) x
    ON CONFLICT DO NOTHING;

    -- 7. Energy: one row per shift, the sum of its Daily reports' figures.
    INSERT INTO production.shift_energy (
        shift_report_id, tenant_id, fuel_quantity, fuel_supplier_id, gasoil_quantity,
        gasoil_supplier_id, gasoil_flow_rate, generator_hours, electricity_quantity
    )
    SELECT
        run.shift_report_id, run.tenant_id, sum(d.fuel_quantity), min(d.fuel_supplier_id),
        sum(d.gasoil_quantity), min(d.gasoil_supplier_id), max(d.gasoil_flow_rate),
        sum(d.generator_hours), sum(d.electricity_quantity)
    FROM production.daily_reports d
    JOIN production.shift_runs run ON run.id = d.report_id
    GROUP BY run.shift_report_id, run.tenant_id
    ON CONFLICT DO NOTHING;

    -- 8. Section states for the sections converted here.
    INSERT INTO production.shift_report_sections (shift_report_id, tenant_id, section_key, status, submitted_at)
    SELECT
        sr.id, sr.tenant_id, k.section_key,
        CASE
            WHEN d.has_data THEN
                CASE sr.status WHEN 'open' THEN 'draft' WHEN 'returned' THEN 'returned' ELSE 'submitted' END
            WHEN sr.status IN ('submitted', 'validated') THEN 'nothing_to_report'
            ELSE 'empty'
        END,
        sr.submitted_at
    FROM production.shift_reports sr
    CROSS JOIN (VALUES ('runs'), ('waste_production'), ('stops'), ('packing'), ('waste_packing'), ('energy'))
        AS k(section_key)
    CROSS JOIN LATERAL (
        SELECT CASE k.section_key
            WHEN 'runs' THEN EXISTS (SELECT 1 FROM production.shift_runs x WHERE x.shift_report_id = sr.id)
            WHEN 'waste_production' THEN EXISTS (
                SELECT 1 FROM production.shift_waste_lines x
                WHERE x.shift_report_id = sr.id AND x.section_key = 'waste_production')
            WHEN 'stops' THEN EXISTS (SELECT 1 FROM production.machine_stops x WHERE x.shift_report_id = sr.id)
            WHEN 'packing' THEN EXISTS (SELECT 1 FROM production.shift_packing_rows x WHERE x.shift_report_id = sr.id)
            WHEN 'waste_packing' THEN EXISTS (
                SELECT 1 FROM production.shift_waste_lines x
                WHERE x.shift_report_id = sr.id AND x.section_key = 'waste_packing')
            WHEN 'energy' THEN EXISTS (
                SELECT 1 FROM production.shift_energy x
                WHERE x.shift_report_id = sr.id
                  AND (x.fuel_quantity > 0 OR x.gasoil_quantity > 0 OR x.electricity_quantity > 0 OR x.generator_hours > 0))
        END AS has_data
    ) d
    ON CONFLICT DO NOTHING;

    -- 9. Old revisions become revisions of the runs / packing section, renumbered
    --    per (shift, section) because two Dailies of one shift each started at 1.
    INSERT INTO production.shift_section_revisions (
        id, tenant_id, shift_report_id, section_key, revision, snapshot, reason, actor_id, created_at
    )
    SELECT
        rev.id, rev.tenant_id, owner.shift_report_id, owner.section_key,
        (row_number() OVER (PARTITION BY owner.shift_report_id, owner.section_key ORDER BY rev.created_at, rev.id))::int,
        jsonb_build_object('legacy_report_id', rev.report_id, 'legacy_revision', rev.revision, 'detail', rev.detail),
        rev.reason, rev.actor_id, rev.created_at
    FROM production.report_revisions rev
    JOIN (
        SELECT id AS report_id, shift_report_id, 'runs' AS section_key FROM production.shift_runs
        UNION ALL
        SELECT id, shift_report_id, 'packing' FROM production.shift_packing_rows
    ) owner ON owner.report_id = rev.report_id
    ON CONFLICT DO NOTHING;

    UPDATE production.shift_report_sections s
    SET revision = c.n
    FROM (
        SELECT shift_report_id, section_key, count(*)::int AS n
        FROM production.shift_section_revisions
        GROUP BY shift_report_id, section_key
    ) c
    WHERE c.shift_report_id = s.shift_report_id AND c.section_key = s.section_key AND s.revision <> c.n;

    SELECT count(*) INTO total FROM production.shift_reports;
    RETURN total;
END;
$$;

SELECT production.convert_legacy_reports();
```

- [ ] **Step 4: Apply and run**

Run:
```
DATABASE_URL=postgresql://erp:erp@localhost:5432/erp .venv/Scripts/python.exe -c "from core.migrations.runner import apply_all_migrations; apply_all_migrations()"
.venv/Scripts/python.exe -m pytest modules/production/api/test_shift_legacy_conversion_integration.py modules/production/api/test_shift_schema_integration.py -v
```
Expected: all pass. If a reconciliation fails, the assertion message names the check (`name`); fix the matching `INSERT` in `0049`, then reapply with `DROP FUNCTION production.convert_legacy_reports(); DELETE FROM core.module_migrations WHERE version = '0049_production_convert_legacy_reports.sql';` plus `TRUNCATE production.shift_reports CASCADE;` on the dev DB and re-run the runner. (Test data only.)

- [ ] **Step 5: Checkpoint** — no commit.

---

### Task 4: Regression check and manifest

**Files:**
- Modify: `backend/modules/production/module.json` (version)

- [ ] **Step 1: Run the whole production and warehouse suites**

Run: `.venv/Scripts/python.exe -m pytest modules/production modules/warehouse modules/qc -q`
Expected: same pass/fail set as before this milestone (the old tables are untouched). Record any failures that pre-exist by running `git stash`-free comparison: run the same command on the failing test file names only and confirm they do not reference `shift_`.

- [ ] **Step 2: Bump the module version**

In `module.json` change `"version": "0.14.0"` to `"version": "0.15.0"`.

- [ ] **Step 3: Report** — list the tests run, counts, and anything that failed before/after. Do not commit.
