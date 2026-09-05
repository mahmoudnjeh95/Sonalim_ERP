-- Two decisions settled after Phase 3, both cheaper to enforce now than once the
-- plant's real OFs and reports exist.

-- Locked decision 3 said the OF's machine is required; the column stayed nullable
-- through Phase 1 only because regrind batches passed it as optional. They now
-- name their work center like any other OF, so the schema can say what the
-- decision always did. Safe as an unconditional NOT NULL because 0013 emptied
-- this table and nothing has been created against it in anger yet.
ALTER TABLE production.work_orders ALTER COLUMN work_center_id SET NOT NULL;

-- A shift reports once. Without this, a team that submits twice double-counts its
-- tonnage and its rebroyat the moment both reports are validated — and from
-- Phase 5 that is double-posted stock, not just a double-counted figure.
--
-- NULLS NOT DISTINCT is the point: `shift` is optional, and the default
-- NULL-is-always-unique behaviour would let unlimited shift-less duplicates
-- through, which is exactly the case a tired operator hits.
CREATE UNIQUE INDEX IF NOT EXISTS production_reports_one_per_shift
    ON production.production_reports (tenant_id, of_id, report_type, report_date, shift)
    NULLS NOT DISTINCT;
