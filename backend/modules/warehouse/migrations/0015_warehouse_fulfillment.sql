-- Phase 4: outbound fulfillment. Confirming a sales order already reserves
-- its stock (synchronously, in sales' own transaction); this adds what the
-- warehouse does next: a pick list per confirmed order, a shipment once it is
-- picked and packed, and the actual stock issue when the shipment leaves.
--
-- The pick list is created by the warehouse.sales_order_confirmed consumer,
-- so source_type/source_id are an opaque pointer into sales -- no FK, sales
-- owns that row. UNIQUE on the source is the consumer's second line of
-- idempotency behind events.processed_events.
--
-- "Picked" is a physical state, not a book state: stock stays on hand (and
-- reserved) in its location until the shipment is shipped, which is when the
-- reservation is released and the picked quantity issued in one transaction.

CREATE TABLE warehouse.pick_lists (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    number TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    partner_id TEXT REFERENCES core.partners (id),
    -- Where the stock was reserved and is picked from.
    location_id TEXT NOT NULL REFERENCES warehouse.locations (id),
    -- The reservation reference the source used, so shipping/cancelling can
    -- release exactly what was reserved.
    reservation_reference TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'picking', 'picked', 'shipped', 'cancelled')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    picked_at TIMESTAMPTZ,
    cancelled_at TIMESTAMPTZ,
    UNIQUE (tenant_id, number),
    UNIQUE (tenant_id, source_type, source_id)
);

CREATE INDEX pick_lists_status_idx ON warehouse.pick_lists (tenant_id, status);

CREATE TABLE warehouse.pick_list_lines (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    pick_list_id TEXT NOT NULL REFERENCES warehouse.pick_lists (id),
    product_id TEXT NOT NULL REFERENCES core.products (id),
    quantity_requested NUMERIC NOT NULL CHECK (quantity_requested > 0),
    quantity_picked NUMERIC CHECK (quantity_picked >= 0),
    picked_by TEXT,
    picked_at TIMESTAMPTZ,
    UNIQUE (tenant_id, pick_list_id, product_id)
);

CREATE INDEX pick_list_lines_pick_list_idx ON warehouse.pick_list_lines (tenant_id, pick_list_id);

CREATE TABLE warehouse.shipments (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    number TEXT NOT NULL,
    pick_list_id TEXT NOT NULL REFERENCES warehouse.pick_lists (id),
    status TEXT NOT NULL DEFAULT 'packed' CHECK (status IN ('packed', 'shipped')),
    package_count INT NOT NULL CHECK (package_count > 0),
    total_weight_kg NUMERIC CHECK (total_weight_kg >= 0),
    carrier TEXT,
    tracking_reference TEXT,
    packed_by TEXT NOT NULL,
    packed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    shipped_by TEXT,
    shipped_at TIMESTAMPTZ,
    UNIQUE (tenant_id, number),
    -- One shipment per pick list: split shipments are out of scope until a
    -- real partial-delivery need shows up.
    UNIQUE (tenant_id, pick_list_id)
);

CREATE INDEX shipments_status_idx ON warehouse.shipments (tenant_id, status);
