ALTER TABLE crm.opportunities ADD COLUMN IF NOT EXISTS expected_close_date DATE;

CREATE TABLE IF NOT EXISTS crm.activities (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    subject_type TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    note TEXT NOT NULL,
    due_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS activities_subject_idx ON crm.activities (tenant_id, subject_type, subject_id);
CREATE INDEX IF NOT EXISTS activities_created_at_idx ON crm.activities (tenant_id, created_at DESC);
