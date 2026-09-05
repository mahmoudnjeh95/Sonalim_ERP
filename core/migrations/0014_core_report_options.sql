-- Shift and team names, configurable per tenant.
--
-- Every production, conditionnement and quality report is filed by a team on a
-- shift. Those were free text, so "Matin", "matin" and "MATIN" all filed against
-- the same real shift and none of them grouped together. They live in `core`
-- rather than in `production` because qc files reports against the same shifts,
-- and qc must never read production's tables.
--
-- Nothing here is referenced by a foreign key: a report keeps the label it was
-- filed under. Renaming or retiring an option changes what the next report may
-- choose, never what an old one says it was.
CREATE TABLE IF NOT EXISTS core.report_options (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('shift', 'team')),
    label TEXT NOT NULL,
    -- The order the plant thinks in: morning, afternoon, night — not alphabetical.
    sort_order INTEGER NOT NULL DEFAULT 0,
    -- Retired options stay in the table so old reports remain explicable; they
    -- are simply no longer offered when filing a new one.
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Two shifts with the same name are the same shift; the whole point of the table
-- is that the name is the identity a report is grouped by.
CREATE UNIQUE INDEX IF NOT EXISTS report_options_unique_label
    ON core.report_options (tenant_id, kind, lower(label));

CREATE INDEX IF NOT EXISTS report_options_kind_idx
    ON core.report_options (tenant_id, kind, sort_order);
