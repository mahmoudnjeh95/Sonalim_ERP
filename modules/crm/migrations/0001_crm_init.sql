CREATE TABLE IF NOT EXISTS crm.leads (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    contact_name TEXT NOT NULL,
    email TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'new',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
