ALTER TABLE warehouse.stock_moves ADD COLUMN IF NOT EXISTS actor_id TEXT;
ALTER TABLE warehouse.stock_moves ADD COLUMN IF NOT EXISTS reason TEXT;

CREATE INDEX IF NOT EXISTS stock_moves_lookup_idx ON warehouse.stock_moves (tenant_id, location_id, product_id, created_at DESC);
