-- Actual final output weight, recorded manually at completion. Nullable so regrind
-- batches (completed through this same endpoint) keep working unchanged.
ALTER TABLE production.work_orders ADD COLUMN IF NOT EXISTS actual_output_quantity NUMERIC;

-- Distinguishes water/humidity raw materials from fresh semoule for yield purposes,
-- the same way is_regrind already distinguishes rebroyat.
ALTER TABLE production.product_classifications ADD COLUMN IF NOT EXISTS is_water BOOLEAN NOT NULL DEFAULT FALSE;

-- One row per raw-material line poured into a work order at creation time (semoule,
-- rebroyat, water/humidity — however many lines a given batch has). location_id is
-- stored per-row so completion can consume exactly where each line was poured from.
CREATE TABLE IF NOT EXISTS production.work_order_inputs (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    work_order_id TEXT NOT NULL REFERENCES production.work_orders (id),
    product_id TEXT NOT NULL,
    quantity NUMERIC NOT NULL,
    location_id TEXT NOT NULL,
    recipe_line_id TEXT REFERENCES production.recipe_lines (id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS work_order_inputs_work_order_idx ON production.work_order_inputs (tenant_id, work_order_id);

-- Per-OF utility consumption (fuel, scotch, film, ...) — a sibling of
-- daily_consumption, scoped by work_order_id instead of a calendar date, since
-- daily_consumption's UNIQUE(tenant_id, consumption_date, resource_type_id) makes it
-- incompatible with also being scoped per work order. Reuses production.resource_types
-- as-is. No cost aggregation columns — recording only, cost/ton and cost/packet
-- calculations are a later phase.
CREATE TABLE IF NOT EXISTS production.work_order_consumption (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    work_order_id TEXT NOT NULL REFERENCES production.work_orders (id),
    resource_type_id TEXT NOT NULL REFERENCES production.resource_types (id),
    quantity NUMERIC NOT NULL,
    note TEXT,
    actor_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS work_order_consumption_work_order_idx ON production.work_order_consumption (tenant_id, work_order_id);
