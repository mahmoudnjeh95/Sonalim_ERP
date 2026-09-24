-- Shift report core, milestone 2: the small sections that have no old equivalent
-- (état de silo, présence personnel, lavage des moules, vérification d'état de paquet).
-- All four come straight from the paper fiches; none of these figures was recorded
-- anywhere before.

-- État de silo, on both fiches: what was in the silo and what state the line was in
-- at the start and at the end of the shift, once for the production side and once
-- for the packing side.
CREATE TABLE IF NOT EXISTS production.shift_silo_states (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    shift_report_id TEXT NOT NULL REFERENCES production.shift_reports (id) ON DELETE CASCADE,
    side TEXT NOT NULL CHECK (side IN ('production', 'packing')),
    phase TEXT NOT NULL CHECK (phase IN ('start', 'end')),
    format TEXT,
    lot_number TEXT,
    level_percent NUMERIC CHECK (level_percent IS NULL OR (level_percent >= 0 AND level_percent <= 100)),
    line_state TEXT,
    UNIQUE (shift_report_id, side, phase)
);

-- Présence personnel: headcount at the four stations, once per shift.
CREATE TABLE IF NOT EXISTS production.shift_staffing (
    shift_report_id TEXT PRIMARY KEY REFERENCES production.shift_reports (id) ON DELETE CASCADE,
    tenant_id TEXT NOT NULL,
    control_room INTEGER CHECK (control_room IS NULL OR control_room >= 0),
    petrin INTEGER CHECK (petrin IS NULL OR petrin >= 0),
    semoule INTEGER CHECK (semoule IS NULL OR semoule >= 0),
    broyage INTEGER CHECK (broyage IS NULL OR broyage >= 0)
);

-- Lavage des moules: which mold was washed, when, and in what state it was left.
CREATE TABLE IF NOT EXISTS production.shift_mold_washes (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    shift_report_id TEXT NOT NULL REFERENCES production.shift_reports (id) ON DELETE CASCADE,
    mold_id TEXT,
    washed_at TIMESTAMPTZ,
    state TEXT,
    line_order INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS shift_mold_washes_shift_idx ON production.shift_mold_washes (shift_report_id);

-- Vérification d'état de paquet: the hourly check of the packs coming off the line.
CREATE TABLE IF NOT EXISTS production.shift_packet_checks (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    shift_report_id TEXT NOT NULL REFERENCES production.shift_reports (id) ON DELETE CASCADE,
    checked_at TIMESTAMPTZ,
    film_state TEXT,
    packet_weight_grams NUMERIC CHECK (packet_weight_grams IS NULL OR packet_weight_grams >= 0),
    long_weld TEXT,
    vertical_weld TEXT,
    date_print TEXT,
    note TEXT,
    line_order INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS shift_packet_checks_shift_idx ON production.shift_packet_checks (shift_report_id);

-- A waste line stays on the shift when its run is removed; it just loses its run.
ALTER TABLE production.shift_waste_lines DROP CONSTRAINT IF EXISTS shift_waste_lines_run_id_fkey;
ALTER TABLE production.shift_waste_lines
    ADD CONSTRAINT shift_waste_lines_run_id_fkey
    FOREIGN KEY (run_id) REFERENCES production.shift_runs (id) ON DELETE SET NULL;
ALTER TABLE production.shift_waste_lines DROP CONSTRAINT IF EXISTS shift_waste_lines_packing_row_id_fkey;
ALTER TABLE production.shift_waste_lines
    ADD CONSTRAINT shift_waste_lines_packing_row_id_fkey
    FOREIGN KEY (packing_row_id) REFERENCES production.shift_packing_rows (id) ON DELETE SET NULL;

-- The converted shifts had no way to say anything about the new sections. They were
-- filed on paper we never saw, so: nothing to report on a shift already handed in.
INSERT INTO production.shift_report_sections (shift_report_id, tenant_id, section_key, status, submitted_at)
SELECT sr.id, sr.tenant_id, k.section_key,
       CASE WHEN sr.status IN ('submitted', 'validated') THEN 'nothing_to_report' ELSE 'empty' END,
       sr.submitted_at
FROM production.shift_reports sr
CROSS JOIN (VALUES ('silo'), ('staffing'), ('packet_checks')) AS k(section_key)
ON CONFLICT DO NOTHING;
