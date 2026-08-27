CREATE TABLE IF NOT EXISTS finance.invoices (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    partner_id TEXT NOT NULL,
    amount NUMERIC NOT NULL,
    currency TEXT NOT NULL DEFAULT 'USD',
    status TEXT NOT NULL DEFAULT 'draft',
    source_order_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
