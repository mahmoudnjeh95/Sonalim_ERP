-- OF creation no longer names a product up front: Conditionnement backfills
-- work_orders.product_id the moment the first packaging report is filed
-- against it. Every downstream reader of this column (packaging variance,
-- validation/posting) only ever runs once a conditionnement report exists,
-- so the invariant holds without their own null-handling.
ALTER TABLE production.work_orders ALTER COLUMN product_id DROP NOT NULL;

-- Mold reference moves off the OF and onto the daily report: a shift names
-- which mold it ran that day, not the OF as a whole. The work_center_id
-- resolution that used the OF's mold no longer applies -- the OF's work
-- center is asked for directly at creation again.
ALTER TABLE production.work_orders DROP COLUMN IF EXISTS mold_id;
ALTER TABLE production.molds DROP COLUMN IF EXISTS work_center_id;
ALTER TABLE production.daily_reports ADD COLUMN IF NOT EXISTS mold_id TEXT REFERENCES production.molds (id);
