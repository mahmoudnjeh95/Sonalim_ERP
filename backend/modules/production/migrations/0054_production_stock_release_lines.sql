-- What has been released from the line store, remembered against the day the goods were packed.
-- The release list is built from that day's packing reports, so without this the same
-- products would be offered again after they moved. One row per product per release; the
-- stock itself moves through ordinary warehouse transfers that share `release_id` as their
-- correlation id. Location ids are opaque references into warehouse.
CREATE TABLE IF NOT EXISTS production.stock_release_lines (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    release_id TEXT NOT NULL,
    packed_on DATE NOT NULL,
    product_id TEXT NOT NULL REFERENCES core.products (id),
    quantity NUMERIC NOT NULL CHECK (quantity > 0),
    from_location_id TEXT NOT NULL,
    to_location_id TEXT NOT NULL,
    released_by TEXT,
    released_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS stock_release_lines_day_idx
    ON production.stock_release_lines (tenant_id, packed_on, product_id);
