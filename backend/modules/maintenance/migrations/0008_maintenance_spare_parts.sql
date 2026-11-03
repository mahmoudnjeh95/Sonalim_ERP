-- Spare parts on checkpoints.
--
-- `settings` holds one row per tenant: the warehouse location spare parts are
-- kept in (its sub-locations -- shelves, bins -- count as part of it). The id is
-- a warehouse location's, read and checked through the warehouse's public
-- LocationService, so there is no foreign key into the warehouse schema.
--
-- `checkpoint_parts` lists the parts a checkpoint's work needs, in the product's
-- own unit. A job's check reads them live through its checkpoint_id, so a job
-- raised ahead of time by a program shows the point's current list.
CREATE TABLE IF NOT EXISTS maintenance.settings (
    tenant_id TEXT PRIMARY KEY,
    spare_parts_location_id TEXT,
    updated_by TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS maintenance.checkpoint_parts (
    checkpoint_id TEXT NOT NULL REFERENCES maintenance.checkpoints (id) ON DELETE CASCADE,
    tenant_id TEXT NOT NULL,
    product_id TEXT NOT NULL REFERENCES core.products (id),
    quantity NUMERIC NOT NULL CHECK (quantity > 0),
    sort_order INT NOT NULL DEFAULT 0,
    PRIMARY KEY (checkpoint_id, product_id)
);

CREATE INDEX IF NOT EXISTS maintenance_checkpoint_parts_product_id_idx
    ON maintenance.checkpoint_parts (tenant_id, product_id);
