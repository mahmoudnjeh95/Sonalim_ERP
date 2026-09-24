-- Admin override (shift-report-lifecycle spec addendum): tags a revision as an
-- edit made after the shift was already validated, distinct from a validator's
-- in-review edit (edited_by_validator). Recorded at write time so history
-- stays correct if permissions change afterwards.
ALTER TABLE production.shift_section_revisions
    ADD COLUMN IF NOT EXISTS edited_after_validation BOOLEAN NOT NULL DEFAULT FALSE;
