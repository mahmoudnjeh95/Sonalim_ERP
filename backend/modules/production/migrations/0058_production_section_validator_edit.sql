-- Allow validators to edit an already-submitted shift section and track that this happened.
-- This adds the `edited_by_validator` flag to shift report section revisions, enabling
-- the validator-edit feature per the lifecycle spec section 3. Once a revision is marked
-- `edited_by_validator = TRUE`, the next client-side validation baseline refresh will
-- ignore CHANGED_SINCE_OPENED, allowing the reviewer to re-edit without forcing a new
-- version bump (the revision stays marked as `edited_by_validator = TRUE` for audit).
ALTER TABLE production.section_revisions ADD COLUMN edited_by_validator BOOLEAN NOT NULL DEFAULT FALSE;
