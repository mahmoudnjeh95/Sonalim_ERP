-- Validator in-place edit (shift-report-lifecycle spec §3): tags a revision as
-- written by the validator during review, not by the team. Recorded at write
-- time so history stays correct if permissions change afterwards.
ALTER TABLE production.shift_section_revisions
    ADD COLUMN IF NOT EXISTS edited_by_validator BOOLEAN NOT NULL DEFAULT FALSE;
