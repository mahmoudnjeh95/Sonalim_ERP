-- Shift report core (shift-report program, project 1, milestone 1).
--
-- One report per line, date and shift replaces the two report types (Daily and
-- Conditionnement) a team filed separately. This migration only ADDS the core:
-- nothing here changes or reads the old report tables, and the running app is
-- unaffected until the cutover milestone.
--
-- Section state lives only in shift_report_sections. section_key has no CHECK on
-- purpose: a new section (bobines, paramètres) is a new key plus its own data
-- table, never a change to this schema.
CREATE TABLE IF NOT EXISTS production.shift_reports (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    work_center_id TEXT NOT NULL REFERENCES production.work_centers (id),
    report_date DATE NOT NULL,
    shift TEXT NOT NULL,
    team TEXT,
    -- The people on the paper header. Free text, not linked to user accounts.
    conducteur TEXT,
    agent_fabrication TEXT,
    machiniste TEXT,
    aide_machiniste TEXT,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'submitted', 'validated', 'returned')),
    revision INTEGER NOT NULL DEFAULT 1,
    created_by TEXT,
    submitted_at TIMESTAMPTZ,
    validated_by TEXT,
    validated_at TIMESTAMPTZ,
    rejection_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, work_center_id, report_date, shift)
);

CREATE INDEX IF NOT EXISTS shift_reports_tenant_date_idx
    ON production.shift_reports (tenant_id, report_date DESC);

CREATE TABLE IF NOT EXISTS production.shift_report_sections (
    shift_report_id TEXT NOT NULL REFERENCES production.shift_reports (id) ON DELETE CASCADE,
    tenant_id TEXT NOT NULL,
    section_key TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'empty'
        CHECK (status IN ('empty', 'draft', 'submitted', 'nothing_to_report', 'returned')),
    -- How many revisions have been frozen for this section.
    revision INTEGER NOT NULL DEFAULT 0,
    -- Set when a submitted section is edited; cleared at validation.
    revised_after_submit BOOLEAN NOT NULL DEFAULT FALSE,
    submitted_by TEXT,
    submitted_at TIMESTAMPTZ,
    return_reason TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (shift_report_id, section_key)
);

CREATE TABLE IF NOT EXISTS production.shift_section_revisions (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    shift_report_id TEXT NOT NULL REFERENCES production.shift_reports (id) ON DELETE CASCADE,
    -- '*' is the whole-shift snapshot frozen at validation.
    section_key TEXT NOT NULL,
    revision INTEGER NOT NULL,
    snapshot JSONB NOT NULL,
    reason TEXT,
    actor_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (shift_report_id, section_key, revision)
);
