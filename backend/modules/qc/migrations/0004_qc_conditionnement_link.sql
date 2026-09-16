-- A quality report has always carried `of_id` and a free-text `team` typed by
-- whoever opened it -- never a link to the specific conditionnement
-- (packaging) run being inspected, and never a team derived from who actually
-- ran that line. The Conformite par equipe dashboard groups by `team`, so a
-- QC inspector's own label (e.g. "QC") could show up as a phantom team next
-- to real production teams.
--
-- conditionnement_report_id is the fix: it names exactly which packaging run
-- this report inspects. Nullable at the DB level so existing rows survive the
-- migration -- see scripts/backfill_qc_conditionnement_links.py -- but the
-- service layer requires it for every new report from here on. `of_id`,
-- `report_date`, `shift` and `team` stay on this table as a denormalized
-- snapshot, same as before: qc keeps its own schema and never joins across
-- the module boundary, it just derives these values instead of accepting
-- them from the caller.
ALTER TABLE qc.quality_reports
    ADD COLUMN IF NOT EXISTS conditionnement_report_id TEXT;

CREATE INDEX IF NOT EXISTS quality_reports_conditionnement_idx
    ON qc.quality_reports (tenant_id, conditionnement_report_id);

-- One QC report per conditionnement run. Partial so legacy rows with no link
-- yet (NULL) don't collide with each other.
CREATE UNIQUE INDEX IF NOT EXISTS quality_reports_one_per_conditionnement
    ON qc.quality_reports (tenant_id, conditionnement_report_id)
    WHERE conditionnement_report_id IS NOT NULL;

-- Superseded by the index above: once every report is linked to a specific
-- conditionnement run, one-per-shift is implied (a conditionnement report
-- already has a unique of_id/report_date/shift) and stops being a separate
-- rule to enforce here.
DROP INDEX IF EXISTS qc.quality_reports_one_per_shift;
