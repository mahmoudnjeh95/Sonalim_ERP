-- QC reports move off the retired legacy conditionnement report onto the shift
-- report the team actually files today (huge_production_migration cutover).
-- No real QC data exists yet (client decision, 2026-09-24), so this truncates
-- rather than converts.

TRUNCATE TABLE qc.nc_dispositions CASCADE;
TRUNCATE TABLE qc.non_conformities CASCADE;
TRUNCATE TABLE qc.quality_follow_ups CASCADE;
TRUNCATE TABLE qc.quality_report_details CASCADE;
TRUNCATE TABLE qc.quality_reports CASCADE;

-- ---- quality_reports: drop the legacy link and per-report of_id, add shift_report_id ----

DROP INDEX IF EXISTS qc.quality_reports_conditionnement_idx;
DROP INDEX IF EXISTS qc.quality_reports_one_per_conditionnement;
DROP INDEX IF EXISTS qc.quality_reports_of_idx;

ALTER TABLE qc.quality_reports
    DROP COLUMN IF EXISTS conditionnement_report_id,
    DROP COLUMN IF EXISTS of_id,
    ADD COLUMN shift_report_id TEXT NOT NULL;

CREATE UNIQUE INDEX quality_reports_one_per_shift_report
    ON qc.quality_reports (tenant_id, shift_report_id);

-- ---- quality_report_details: keep only the report-wide notes ----

ALTER TABLE qc.quality_report_details
    DROP COLUMN IF EXISTS pre_dryer_index,
    DROP COLUMN IF EXISTS humidity_percentage,
    DROP COLUMN IF EXISTS cooling_index,
    DROP COLUMN IF EXISTS pf_index,
    DROP COLUMN IF EXISTS sumo_index,
    DROP COLUMN IF EXISTS conforming_cartons,
    DROP COLUMN IF EXISTS non_conforming_cartons,
    DROP COLUMN IF EXISTS defect_details;

-- ---- quality_conformity_lines: one row per product packed that shift ----

CREATE TABLE qc.quality_conformity_lines (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    report_id TEXT NOT NULL REFERENCES qc.quality_reports (id),
    -- Opaque reference into production.shift_packing_rows -- no cross-module FK.
    shift_packing_row_id TEXT NOT NULL,
    of_id TEXT NOT NULL,
    product_id TEXT NOT NULL,
    conforming_cartons NUMERIC NOT NULL DEFAULT 0,
    non_conforming_cartons NUMERIC NOT NULL DEFAULT 0,
    defect_details TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX quality_conformity_lines_one_per_row
    ON qc.quality_conformity_lines (tenant_id, shift_packing_row_id);
CREATE INDEX quality_conformity_lines_report_idx
    ON qc.quality_conformity_lines (tenant_id, report_id);
CREATE INDEX quality_conformity_lines_of_idx
    ON qc.quality_conformity_lines (tenant_id, of_id);

-- ---- quality_follow_ups: line-scoped, so a multi-product shift opens one window per product ----

ALTER TABLE qc.quality_follow_ups
    ADD COLUMN conformity_line_id TEXT REFERENCES qc.quality_conformity_lines (id);
