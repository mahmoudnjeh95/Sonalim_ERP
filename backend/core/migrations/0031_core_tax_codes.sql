-- Tax codes (WP-1.1): a tenant's names for its VAT rates and exemptions. Sales, finance and procurement all
-- apply them, so the catalog is in the shared kernel, like payment terms. It is filled with the defaults the
-- first time it is read (core/tax_codes.py); nothing is inserted here.
CREATE TABLE IF NOT EXISTS core.tax_codes (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    -- immutable: lines, events and posting rules (invoice / vat / <code>) refer to it
    code TEXT NOT NULL,
    name_fr TEXT NOT NULL,
    name_en TEXT NOT NULL,
    rate NUMERIC(5, 2) NOT NULL CHECK (rate >= 0 AND rate <= 100),
    scope TEXT NOT NULL DEFAULT 'both' CHECK (scope IN ('sales', 'purchases', 'both')),
    exempt BOOLEAN NOT NULL DEFAULT FALSE,
    -- the sentence an invoice under this code must carry, e.g. the article of the exemption
    legal_mention TEXT,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, code),
    CHECK (NOT exempt OR rate = 0)
);

-- The code a product is sold and bought under; a partner's code (an exemption, an export customer) overrides it.
ALTER TABLE core.products ADD COLUMN IF NOT EXISTS sales_tax_code_id TEXT REFERENCES core.tax_codes (id);
ALTER TABLE core.products ADD COLUMN IF NOT EXISTS purchase_tax_code_id TEXT REFERENCES core.tax_codes (id);
ALTER TABLE core.partners ADD COLUMN IF NOT EXISTS customer_tax_code_id TEXT REFERENCES core.tax_codes (id);
ALTER TABLE core.partners ADD COLUMN IF NOT EXISTS supplier_tax_code_id TEXT REFERENCES core.tax_codes (id);

-- Tenants with existing default roles never receive new codes (ensure_default_roles() runs only from the
-- seed scripts): the Administrateur gets core.manage_tax_codes here. Inserts only.
INSERT INTO core.role_permissions (role_id, permission)
SELECT r.id, 'core.manage_tax_codes' FROM core.roles r WHERE r.code = 'administrateur'
ON CONFLICT (role_id, permission) DO NOTHING;
