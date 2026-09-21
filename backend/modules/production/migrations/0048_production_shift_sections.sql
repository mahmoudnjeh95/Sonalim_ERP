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
