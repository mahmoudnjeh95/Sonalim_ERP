-- The plant wants each arrêt to say what kind of intervention it was
-- (préventive, corrective, ...) and which system it hit (pneumatique,
-- électrique, ...), on top of the motif it already names. Free text, same as
-- motif itself: no controlled vocabulary has been asked for here either.
ALTER TABLE production.report_downtime_lines ADD COLUMN IF NOT EXISTS downtime_type TEXT;
ALTER TABLE production.report_downtime_lines ADD COLUMN IF NOT EXISTS classification TEXT;
