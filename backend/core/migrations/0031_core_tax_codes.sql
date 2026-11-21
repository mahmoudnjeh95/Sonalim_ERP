-- Tax codes: a named VAT rate per tenant, applied to sales and purchase lines. Lines keep their own rate
-- (a snapshot), so changing a code never rewrites an issued document. The catalogue is filled with the
-- defaults the first time it is read (core/tax_codes.py).
CREATE TABLE IF NOT EXISTS core.tax_codes (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    code TEXT NOT NULL,
    name_fr TEXT NOT NULL,
    name_en TEXT NOT NULL,
    rate NUMERIC(5, 2) NOT NULL CHECK (rate >= 0 AND rate <= 100),
    applies_to TEXT NOT NULL DEFAULT 'both' CHECK (applies_to IN ('sales', 'purchase', 'both')),
    exempt BOOLEAN NOT NULL DEFAULT FALSE CHECK (NOT exempt OR rate = 0),
    active BOOLEAN NOT NULL DEFAULT TRUE,
    is_default_sales BOOLEAN NOT NULL DEFAULT FALSE,
    is_default_purchase BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, code)
);
-- At most one default per side and tenant.
CREATE UNIQUE INDEX IF NOT EXISTS tax_codes_default_sales_idx ON core.tax_codes (tenant_id) WHERE is_default_sales;
CREATE UNIQUE INDEX IF NOT EXISTS tax_codes_default_purchase_idx ON core.tax_codes (tenant_id) WHERE is_default_purchase;
