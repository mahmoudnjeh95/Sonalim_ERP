-- Price lists, discounts, VAT and quotes.
--
-- Existing orders keep their meaning: every new column defaults to 0 (no discount, no VAT), so an order
-- created before this migration totals exactly what it did and is invoiced at the same prices.
-- New orders and quotes take the tenant's default VAT rate (18 %, Mali's standard rate) from sales.settings.

CREATE TABLE IF NOT EXISTS sales.settings (
    tenant_id TEXT PRIMARY KEY,
    default_vat_rate NUMERIC(5, 2) NOT NULL DEFAULT 18 CHECK (default_vat_rate >= 0 AND default_vat_rate <= 100),
    -- the largest discount (line and order combined, in %) a seller may give without sales.admin_discounts
    max_discount_rate NUMERIC(5, 2) NOT NULL DEFAULT 10 CHECK (max_discount_rate >= 0 AND max_discount_rate <= 100),
    quote_validity_days INTEGER NOT NULL DEFAULT 30 CHECK (quote_validity_days > 0),
    updated_by TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE sales.orders ADD COLUMN IF NOT EXISTS discount_rate NUMERIC(5, 2) NOT NULL DEFAULT 0
    CHECK (discount_rate >= 0 AND discount_rate <= 100);
ALTER TABLE sales.orders ADD COLUMN IF NOT EXISTS quote_id TEXT;
ALTER TABLE sales.order_lines ADD COLUMN IF NOT EXISTS discount_rate NUMERIC(5, 2) NOT NULL DEFAULT 0
    CHECK (discount_rate >= 0 AND discount_rate <= 100);
ALTER TABLE sales.order_lines ADD COLUMN IF NOT EXISTS vat_rate NUMERIC(5, 2) NOT NULL DEFAULT 0
    CHECK (vat_rate >= 0 AND vat_rate <= 100);
ALTER TABLE sales.order_lines ADD COLUMN IF NOT EXISTS price_list_id TEXT;

CREATE TABLE IF NOT EXISTS sales.price_lists (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    name TEXT NOT NULL,
    valid_from DATE,
    valid_to DATE,
    is_default BOOLEAN NOT NULL DEFAULT FALSE,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    note TEXT,
    created_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from),
    UNIQUE (tenant_id, name)
);
-- one default list per tenant
CREATE UNIQUE INDEX IF NOT EXISTS price_lists_one_default ON sales.price_lists (tenant_id) WHERE is_default;

CREATE TABLE IF NOT EXISTS sales.price_list_items (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    price_list_id TEXT NOT NULL REFERENCES sales.price_lists (id) ON DELETE CASCADE,
    product_id TEXT NOT NULL REFERENCES core.products (id),
    -- a quantity break: this price applies from this quantity up; 1 is the base price
    min_quantity NUMERIC NOT NULL DEFAULT 1 CHECK (min_quantity > 0),
    unit_price NUMERIC NOT NULL CHECK (unit_price >= 0),
    UNIQUE (price_list_id, product_id, min_quantity)
);
CREATE INDEX IF NOT EXISTS price_list_items_product ON sales.price_list_items (tenant_id, product_id);

-- Which list a customer buys on, and their standing discount. Keyed by the shared-kernel partner id;
-- core.partners itself is not changed.
CREATE TABLE IF NOT EXISTS sales.customer_pricing (
    tenant_id TEXT NOT NULL,
    partner_id TEXT NOT NULL REFERENCES core.partners (id),
    price_list_id TEXT REFERENCES sales.price_lists (id) ON DELETE SET NULL,
    discount_rate NUMERIC(5, 2) NOT NULL DEFAULT 0 CHECK (discount_rate >= 0 AND discount_rate <= 100),
    updated_by TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (tenant_id, partner_id)
);

CREATE TABLE IF NOT EXISTS sales.document_counters (
    tenant_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    year INTEGER NOT NULL,
    last_number INTEGER NOT NULL,
    PRIMARY KEY (tenant_id, kind, year)
);

CREATE TABLE IF NOT EXISTS sales.quotes (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    -- DV-YYYY-000001; a revision keeps the number and shows as DV-YYYY-000001-2
    number TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
    previous_id TEXT REFERENCES sales.quotes (id),
    partner_id TEXT NOT NULL REFERENCES core.partners (id),
    opportunity_id TEXT,
    location_id TEXT,
    quote_date DATE NOT NULL DEFAULT CURRENT_DATE,
    valid_until DATE NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'sent', 'accepted', 'refused', 'expired', 'superseded')),
    discount_rate NUMERIC(5, 2) NOT NULL DEFAULT 0 CHECK (discount_rate >= 0 AND discount_rate <= 100),
    note TEXT,
    refusal_reason TEXT,
    order_id TEXT,
    created_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, number, revision)
);
CREATE INDEX IF NOT EXISTS quotes_status ON sales.quotes (tenant_id, status);

CREATE TABLE IF NOT EXISTS sales.quote_lines (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    quote_id TEXT NOT NULL REFERENCES sales.quotes (id) ON DELETE CASCADE,
    line_no INTEGER NOT NULL,
    product_id TEXT NOT NULL REFERENCES core.products (id),
    quantity NUMERIC NOT NULL CHECK (quantity > 0),
    unit_price NUMERIC NOT NULL CHECK (unit_price >= 0),
    discount_rate NUMERIC(5, 2) NOT NULL DEFAULT 0 CHECK (discount_rate >= 0 AND discount_rate <= 100),
    vat_rate NUMERIC(5, 2) NOT NULL DEFAULT 0 CHECK (vat_rate >= 0 AND vat_rate <= 100),
    price_list_id TEXT
);

-- Tenants with existing default roles never receive new codes (ensure_default_roles() only runs from
-- the seed scripts; see treasury/0008). The Administrateur gets the quote, price-list and discount codes;
-- no other role does. Inserts only.
INSERT INTO core.role_permissions (role_id, permission)
SELECT r.id, granted.permission
FROM core.roles r
CROSS JOIN unnest(ARRAY[
    'sales.view_quotes',
    'sales.manage_quotes',
    'sales.manage_price_lists',
    'sales.admin_discounts'
]) AS granted(permission)
WHERE r.code = 'administrateur'
ON CONFLICT (role_id, permission) DO NOTHING;
