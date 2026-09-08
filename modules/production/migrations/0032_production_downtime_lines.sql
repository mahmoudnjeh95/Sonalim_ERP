-- Arrêts stop being one minutes/reason pair and become a list, the same move
-- 0022 made for déchets and 0027 for semoule: a shift can stop more than once,
-- for more than one reason, and a single field could only ever hold the last one.
--
-- Each line names its own motif and minutes, so a shift with three stoppages
-- for three different reasons can finally say so instead of picking one reason
-- to report and folding the rest into it.
CREATE TABLE IF NOT EXISTS production.report_downtime_lines (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    report_id TEXT NOT NULL REFERENCES production.production_reports (id) ON DELETE CASCADE,

    -- Free text, like the column it replaces -- the plant has not asked for a
    -- controlled vocabulary here yet.
    motif TEXT,
    minutes INTEGER NOT NULL DEFAULT 0 CHECK (minutes >= 0),
    note TEXT,
    -- Preserves the order the shift entered them in; nothing else depends on it.
    line_order INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS report_downtime_lines_report_idx
    ON production.report_downtime_lines (tenant_id, report_id);

-- Backfill. Only reports that actually recorded a stoppage become a line: a
-- report with downtime_minutes = 0 stopped for nothing, and turning that into
-- an empty line would invent an arrêt that never happened.
INSERT INTO production.report_downtime_lines (id, tenant_id, report_id, motif, minutes, line_order)
SELECT gen_random_uuid()::text, d.tenant_id, d.report_id, d.downtime_reason, d.downtime_minutes, 0
FROM production.daily_reports d
WHERE d.downtime_minutes > 0;

-- The columns go. Keeping them beside the list would give every report's
-- downtime two homes that can disagree, same reasoning as 0022 dropping the
-- old fixed waste columns once report_waste_lines existed.
ALTER TABLE production.daily_reports DROP COLUMN IF EXISTS downtime_minutes;
ALTER TABLE production.daily_reports DROP COLUMN IF EXISTS downtime_reason;
