-- Variant support: a variant is just a core.products row with a parent, so stock,
-- purchase-order lines, and every other product_id reference keep working unchanged.
ALTER TABLE core.products ADD COLUMN IF NOT EXISTS parent_product_id TEXT REFERENCES core.products (id);
CREATE INDEX IF NOT EXISTS products_parent_idx ON core.products (tenant_id, parent_product_id) WHERE parent_product_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS core.product_attributes (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, name)
);

CREATE TABLE IF NOT EXISTS core.product_attribute_values (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    attribute_id TEXT NOT NULL REFERENCES core.product_attributes (id),
    value TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (attribute_id, value)
);

-- Which specific attribute-value combination a variant product represents.
CREATE TABLE IF NOT EXISTS core.product_variant_values (
    product_id TEXT NOT NULL REFERENCES core.products (id),
    attribute_value_id TEXT NOT NULL REFERENCES core.product_attribute_values (id),
    PRIMARY KEY (product_id, attribute_value_id)
);
