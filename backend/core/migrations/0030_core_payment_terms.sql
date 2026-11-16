-- Payment terms belong to the partner, like its name: sales invoices use a customer's terms and purchase
-- invoices a supplier's, so they live in the shared kernel where finance and procurement both read them.
-- The catalog is per tenant and filled with the defaults the first time it is read (core/payment_terms.py).
CREATE TABLE IF NOT EXISTS core.payment_terms (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    code TEXT NOT NULL,
    name_fr TEXT NOT NULL,
    name_en TEXT NOT NULL,
    -- [{"percent": "100", "days": 30, "end_of_month": true, "day_of_month": 10}, ...]
    installments JSONB NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, code)
);

ALTER TABLE core.partners ADD COLUMN IF NOT EXISTS customer_payment_term_id TEXT REFERENCES core.payment_terms (id);
ALTER TABLE core.partners ADD COLUMN IF NOT EXISTS supplier_payment_term_id TEXT REFERENCES core.payment_terms (id);
