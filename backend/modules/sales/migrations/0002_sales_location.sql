-- No FK to warehouse.locations: per the architecture's hard rule, modules never
-- reference another module's tables directly (locations is not shared-kernel data).
-- Validity is enforced at the application layer when stock is reserved on confirm.
ALTER TABLE sales.orders ADD COLUMN IF NOT EXISTS location_id TEXT NOT NULL DEFAULT '';
ALTER TABLE sales.orders ALTER COLUMN location_id DROP DEFAULT;
