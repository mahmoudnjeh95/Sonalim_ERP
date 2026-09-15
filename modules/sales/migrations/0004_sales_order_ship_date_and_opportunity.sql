-- requested_ship_date: when the customer wants the order delivered — surfaced by
-- production planning to prioritize which OF to start first.
-- opportunity_id: opaque reference to the CRM opportunity this order was created
-- from (nullable — orders can also be created directly). No FK: per the
-- architecture's hard rule, modules never reference another module's tables.
ALTER TABLE sales.orders ADD COLUMN IF NOT EXISTS requested_ship_date DATE;
ALTER TABLE sales.orders ADD COLUMN IF NOT EXISTS opportunity_id TEXT;
