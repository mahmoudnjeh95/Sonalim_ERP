ALTER TABLE production.work_orders ADD COLUMN IF NOT EXISTS recipe_id TEXT REFERENCES production.recipes (id);
ALTER TABLE production.work_orders ADD COLUMN IF NOT EXISTS packaging_bom_id TEXT REFERENCES production.packaging_boms (id);
