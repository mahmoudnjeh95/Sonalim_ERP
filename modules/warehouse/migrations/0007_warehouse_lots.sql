CREATE TABLE IF NOT EXISTS warehouse.lots (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    product_id TEXT NOT NULL,
    lot_number TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'consumed', 'expired')),
    expiry_date DATE,
    produced_at TIMESTAMPTZ,
    -- Polymorphic pointer to whatever created this lot (e.g. a procurement goods receipt).
    -- No FK: that data lives in another module's schema.
    source_type TEXT,
    source_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, product_id, lot_number)
);

CREATE INDEX IF NOT EXISTS lots_product_idx ON warehouse.lots (tenant_id, product_id);
CREATE INDEX IF NOT EXISTS lots_expiry_idx ON warehouse.lots (tenant_id, expiry_date) WHERE expiry_date IS NOT NULL;

CREATE TABLE IF NOT EXISTS warehouse.lot_stock (
    tenant_id TEXT NOT NULL,
    lot_id TEXT NOT NULL REFERENCES warehouse.lots (id),
    location_id TEXT NOT NULL REFERENCES warehouse.locations (id),
    quantity_on_hand NUMERIC NOT NULL DEFAULT 0,
    PRIMARY KEY (tenant_id, lot_id, location_id)
);
