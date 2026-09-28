-- Phase 3: guided put-away. When stock lands somewhere provisional, the
-- system suggests where it should actually live -- an explicit rule first,
-- otherwise a bin already holding the same product, otherwise any empty
-- bin -- and the user confirms the move as an ordinary transfer_stock.
--
-- No capacity/priority columns on locations: nothing has capacity data to
-- rank by yet, and ranking on values nobody has entered would be theater.
-- The three signals above are real and already queryable.

CREATE TABLE warehouse.putaway_rules (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    site_id TEXT NOT NULL,
    product_id TEXT NOT NULL REFERENCES core.products (id),
    target_location_id TEXT NOT NULL REFERENCES warehouse.locations (id),
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, site_id, product_id)
);

CREATE INDEX putaway_rules_site_idx ON warehouse.putaway_rules (tenant_id, site_id);
