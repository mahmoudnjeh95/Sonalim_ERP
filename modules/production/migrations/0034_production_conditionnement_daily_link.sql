-- A conditionnement report packages what a daily report produced, but nothing
-- has ever said which daily report that was -- the two sat as siblings under
-- the same OF, matched only by report_date/shift coinciding. Nullable rather
-- than NOT NULL: a team may file conditionnement before that day's daily
-- report exists, so completeness is enforced at submit time (see
-- validate_conditionnement_stock_targets), the same way packaging stock
-- targets already are.
ALTER TABLE production.conditionnement_reports
    ADD COLUMN IF NOT EXISTS daily_report_id TEXT REFERENCES production.production_reports (id);

CREATE INDEX IF NOT EXISTS conditionnement_reports_daily_report_idx
    ON production.conditionnement_reports (tenant_id, daily_report_id);
