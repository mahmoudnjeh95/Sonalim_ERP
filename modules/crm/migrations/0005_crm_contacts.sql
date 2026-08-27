CREATE TABLE IF NOT EXISTS crm.contacts (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    partner_id TEXT NOT NULL,
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    job_title TEXT,
    email TEXT,
    phone TEXT,
    is_primary BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS contacts_partner_idx ON crm.contacts (tenant_id, partner_id);
CREATE UNIQUE INDEX IF NOT EXISTS contacts_primary_partner_idx ON crm.contacts (tenant_id, partner_id) WHERE is_primary;
