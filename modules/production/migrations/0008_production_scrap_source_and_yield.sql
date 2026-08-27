ALTER TABLE production.scrap_records ALTER COLUMN work_order_id DROP NOT NULL;
ALTER TABLE production.scrap_records ADD COLUMN IF NOT EXISTS work_center_id TEXT REFERENCES production.work_centers (id);
ALTER TABLE production.scrap_records ADD COLUMN IF NOT EXISTS source_note TEXT;

ALTER TABLE production.regrind_batches ADD COLUMN IF NOT EXISTS input_quantity_total NUMERIC NOT NULL DEFAULT 0;
