-- Rebroyat gets its own team-assignment workflow: an OF opens new (whether raised
-- automatically from a validated report or created by hand), a responsable assigns
-- it to a team, and only then can the team finish it and weigh in the real output.
--
-- assigned_team is free text, like daily_reports.team (core.report_options
-- kind='team') — not a foreign key, for the same reason: the batch keeps the name
-- it was assigned under even if that team is later renamed or retired.
ALTER TABLE production.regrind_batches ADD COLUMN IF NOT EXISTS assigned_team TEXT;
ALTER TABLE production.regrind_batches ADD COLUMN IF NOT EXISTS assigned_by TEXT;
ALTER TABLE production.regrind_batches ADD COLUMN IF NOT EXISTS assigned_at TIMESTAMPTZ;

COMMENT ON COLUMN production.regrind_batches.assigned_team IS
    'Free-text team label a responsable assigned this batch to. NULL means the batch is still new and unassigned.';
