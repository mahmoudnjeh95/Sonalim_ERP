-- Phase 2 of the OF-centred production rebuild: the report becomes the operational
-- record. One header shape is shared by every production report type; the per-type
-- figures live in their own detail table (daily_reports here, conditionnement in
-- Phase 3). Quality reports deliberately do NOT live here — they belong to the qc
-- module, which may not be read across the module boundary.
--
-- Nothing in this migration posts stock. Validation becomes the only door stock
-- moves through in Phase 5; until then a validated report is a record, not a move.
CREATE TABLE IF NOT EXISTS production.production_reports (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    -- The OF the report belongs to. Captured once when the report is opened and
    -- never re-asked inside the form.
    of_id TEXT NOT NULL REFERENCES production.work_orders (id),
    report_type TEXT NOT NULL CHECK (report_type IN ('daily', 'conditionnement')),
    team TEXT,
    work_center_id TEXT REFERENCES production.work_centers (id),
    report_date DATE NOT NULL,
    shift TEXT,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'submitted', 'validated', 'rejected')),
    -- Which revision the working figures currently represent. Bumped by a
    -- validator's correction and by re-opening a rejected report; every value it
    -- has ever held is frozen in report_revisions below.
    revision INTEGER NOT NULL DEFAULT 1,
    created_by TEXT,
    submitted_at TIMESTAMPTZ,
    validated_by TEXT,
    validated_at TIMESTAMPTZ,
    rejection_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS production_reports_of_idx ON production.production_reports (tenant_id, of_id);
CREATE INDEX IF NOT EXISTS production_reports_status_idx ON production.production_reports (tenant_id, status);
CREATE INDEX IF NOT EXISTS production_reports_date_idx ON production.production_reports (tenant_id, report_date);

-- The control that makes a supervisor's correction distinguishable from an
-- operator's entry. Submitting freezes the team's figures at revision 1; every
-- later correction appends a new revision with its reason. The UNIQUE below is
-- what enforces "never overwritten" at the database level rather than by
-- convention in the service.
CREATE TABLE IF NOT EXISTS production.report_revisions (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    report_id TEXT NOT NULL REFERENCES production.production_reports (id),
    revision INTEGER NOT NULL,
    detail JSONB NOT NULL,
    reason TEXT,
    actor_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (report_id, revision)
);

CREATE INDEX IF NOT EXISTS report_revisions_report_idx ON production.report_revisions (tenant_id, report_id);
