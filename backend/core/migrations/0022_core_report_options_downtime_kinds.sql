-- Arrêt (downtime) type, classification and motif become admin-managed lists.
--
-- They were fixed arrays in the frontend, so a plant that met a stoppage cause
-- nobody had listed could only pick "Autre". They join shift and team in
-- core.report_options, which already carries what they need: per-tenant lists,
-- retire-instead-of-delete, an audit trail, and a settings screen.
--
-- The built-in values (format_change, preventive, pneumatic, ...) stay in the
-- frontend and are not rows here: report lines store them as codes that the
-- interface translates. Rows added here are the plant's own, and a line filed
-- under one stores its label, exactly as a shift or team does.
DO $$
DECLARE
    existing RECORD;
BEGIN
    -- The original CHECK was declared inline, so it carries a generated name.
    FOR existing IN
        SELECT conname FROM pg_constraint
        WHERE conrelid = 'core.report_options'::regclass
          AND contype = 'c'
          AND pg_get_constraintdef(oid) LIKE '%kind%'
    LOOP
        EXECUTE format('ALTER TABLE core.report_options DROP CONSTRAINT %I', existing.conname);
    END LOOP;
END
$$;

ALTER TABLE core.report_options
    ADD CONSTRAINT report_options_kind_check
    CHECK (kind IN ('shift', 'team', 'downtime_type', 'downtime_classification', 'downtime_motif'));
