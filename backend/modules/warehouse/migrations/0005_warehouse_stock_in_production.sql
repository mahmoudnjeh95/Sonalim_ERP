ALTER TABLE warehouse.stock_items ADD COLUMN IF NOT EXISTS quantity_in_production NUMERIC NOT NULL DEFAULT 0;
