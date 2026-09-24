-- An old-shaped report written from a shift report says which shift it came from.
--
-- `production_reports_one_per_shift` kept a team from filing the same OF twice in a shift under
-- the old flow. A shift report is unique per (line, date, shift) on its own, and it can hold
-- several rows for one OF (a mold change starts a second product on the same OF), so its rows
-- must not be held to the old rule. The rule stays for reports that no shift owns.
ALTER TABLE production.production_reports ADD COLUMN IF NOT EXISTS shift_report_id TEXT;

UPDATE production.production_reports r
SET shift_report_id = x.shift_report_id
FROM (
    SELECT id, shift_report_id FROM production.shift_runs
    UNION ALL
    SELECT id, shift_report_id FROM production.shift_packing_rows
) x
WHERE x.id = r.id AND r.shift_report_id IS NULL;

DROP INDEX IF EXISTS production.production_reports_one_per_shift;
CREATE UNIQUE INDEX IF NOT EXISTS production_reports_one_per_shift
    ON production.production_reports (tenant_id, of_id, report_type, report_date, shift)
    NULLS NOT DISTINCT
    WHERE shift_report_id IS NULL;

CREATE INDEX IF NOT EXISTS production_reports_shift_report_idx
    ON production.production_reports (tenant_id, shift_report_id);
