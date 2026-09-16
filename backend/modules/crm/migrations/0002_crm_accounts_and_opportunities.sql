CREATE TABLE IF NOT EXISTS crm.accounts (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    name TEXT NOT NULL,
    industry TEXT,
    website TEXT,
    phone TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS crm.opportunities (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    account_id TEXT NOT NULL REFERENCES crm.accounts (id),
    name TEXT NOT NULL,
    stage TEXT NOT NULL DEFAULT 'prospecting',
    amount NUMERIC NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS opportunities_account_id_idx ON crm.opportunities (account_id);

ALTER TABLE crm.leads ADD COLUMN IF NOT EXISTS converted_account_id TEXT REFERENCES crm.accounts (id);
ALTER TABLE crm.leads ADD COLUMN IF NOT EXISTS converted_opportunity_id TEXT REFERENCES crm.opportunities (id);
