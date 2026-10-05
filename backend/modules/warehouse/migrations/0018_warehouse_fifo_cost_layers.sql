-- Phase 6B: FIFO valuation. Stock value was on-hand x the catalog purchase
-- price -- one number per product, whatever each batch actually cost. This
-- keeps a cost layer per inflow (a receipt at its real landed cost, a
-- production output, a positive correction) and draws outflows from the
-- oldest layers first, recording each draw so the cost of any movement --
-- a shipment's cost of goods sold above all -- can be read back.
--
-- Per product, not per location: a transfer between bins doesn't change what
-- the goods cost. The quantity valued is what the plant owns -- on hand plus
-- in production -- so sending stock to the line is neutral and it is the
-- line's consumption that draws layers down. All costs are XOF.

CREATE TABLE warehouse.cost_layers (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    product_id TEXT NOT NULL REFERENCES core.products (id),
    reference TEXT NOT NULL,
    move_type TEXT NOT NULL,
    quantity_in NUMERIC NOT NULL CHECK (quantity_in > 0),
    quantity_remaining NUMERIC NOT NULL CHECK (quantity_remaining >= 0),
    -- NULL: nothing was known at receipt (no landed cost, no catalog price).
    unit_cost NUMERIC CHECK (unit_cost >= 0),
    received_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX cost_layers_open_idx
    ON warehouse.cost_layers (tenant_id, product_id, received_at, id) WHERE quantity_remaining > 0;

CREATE TABLE warehouse.cost_layer_consumptions (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    product_id TEXT NOT NULL REFERENCES core.products (id),
    -- NULL for the part of an outflow no layer covered (production may drive
    -- stock negative); it is recorded, unvalued, rather than dropped.
    layer_id TEXT REFERENCES warehouse.cost_layers (id),
    reference TEXT NOT NULL,
    move_type TEXT NOT NULL,
    quantity NUMERIC NOT NULL CHECK (quantity > 0),
    unit_cost NUMERIC,
    consumed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX cost_layer_consumptions_reference_idx ON warehouse.cost_layer_consumptions (tenant_id, reference);
CREATE INDEX cost_layer_consumptions_product_idx ON warehouse.cost_layer_consumptions (tenant_id, product_id, consumed_at);

-- Opening balance: whatever the plant owns today becomes one layer per
-- product at the catalog purchase price (the only cost there is for stock
-- that predates this table), or unvalued when there is none. Negative
-- balances open nothing.
INSERT INTO warehouse.cost_layers (id, tenant_id, product_id, reference, move_type, quantity_in, quantity_remaining, unit_cost)
SELECT
    'opening-' || md5(owned.tenant_id || '|' || owned.product_id),
    owned.tenant_id, owned.product_id, 'opening_balance', 'opening_balance', owned.quantity, owned.quantity,
    CASE WHEN p.purchase_price > 0 THEN p.purchase_price END
FROM (
    SELECT tenant_id, product_id, SUM(quantity_on_hand + quantity_in_production) AS quantity
    FROM warehouse.stock_items
    GROUP BY tenant_id, product_id
) owned
JOIN core.products p ON p.id = owned.product_id
WHERE owned.quantity > 0;
