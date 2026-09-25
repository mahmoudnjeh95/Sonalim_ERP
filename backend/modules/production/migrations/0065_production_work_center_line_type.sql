-- What a work center is for: a 'production' line (OFs and shift reports run on
-- it) or a 'grinder' line (rebroyat runs — the OFRs — run on it). Pickers filter
-- on it instead of guessing from the name.
--
-- Backfill mirrors the rule the shift form used until now: a name starting with
-- "line" is a production line, anything else (e.g. rebroyat_01) a grinder.
ALTER TABLE production.work_centers
    ADD COLUMN IF NOT EXISTS line_type TEXT NOT NULL DEFAULT 'production'
    CHECK (line_type IN ('production', 'grinder'));

UPDATE production.work_centers SET line_type = 'grinder' WHERE name !~* '^line';
