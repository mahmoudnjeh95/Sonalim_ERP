CREATE TABLE IF NOT EXISTS warehouse.locations (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, code)
);

-- Backfill only matters for a DB with pre-existing stock history; a fresh dev DB has
-- none, so seed_dev.py creates the demo tenant's locations explicitly instead.
INSERT INTO warehouse.locations (id, tenant_id, code, name)
SELECT DISTINCT 'default-' || tenant_id, tenant_id, 'raw-materials', 'Matières premières'
FROM warehouse.stock_items
ON CONFLICT (tenant_id, code) DO NOTHING;

ALTER TABLE warehouse.stock_items ADD COLUMN IF NOT EXISTS location_id TEXT;
UPDATE warehouse.stock_items SET location_id = 'default-' || tenant_id WHERE location_id IS NULL;
ALTER TABLE warehouse.stock_items ALTER COLUMN location_id SET NOT NULL;
ALTER TABLE warehouse.stock_items DROP CONSTRAINT IF EXISTS stock_items_pkey;
ALTER TABLE warehouse.stock_items ADD PRIMARY KEY (tenant_id, location_id, product_id);

ALTER TABLE warehouse.stock_moves ADD COLUMN IF NOT EXISTS location_id TEXT;
UPDATE warehouse.stock_moves SET location_id = 'default-' || tenant_id WHERE location_id IS NULL;
ALTER TABLE warehouse.stock_moves ALTER COLUMN location_id SET NOT NULL;
