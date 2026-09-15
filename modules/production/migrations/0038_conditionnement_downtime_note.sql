-- Add downtime_note to conditionnement reports, matching the structure of downtime_lines
-- in daily reports: motif (standardized) + note (free text). Until now, downtime_reason
-- was a single free-text field. This migration keeps downtime_reason as the motif,
-- and adds downtime_note for additional context.
ALTER TABLE production.conditionnement_reports ADD COLUMN IF NOT EXISTS downtime_note TEXT;
