-- Phase 1 of the OF-centred production rebuild: the OF becomes a planning and
-- closure record only. Stock stops following the work order lifecycle and starts
-- following report validation (Phase 5), so nothing here posts inventory.

-- Existing OF data is deleted rather than migrated. There is no honest mapping
-- from an in_progress order that already reserved, moved and consumed stock onto
-- a `planned` OF that posts nothing, so everything keyed off a work order goes
-- with it. CASCADE covers the child tables listed here and any other referent.
TRUNCATE TABLE
    production.regrind_batch_inputs,
    production.regrind_batches,
    production.scrap_records,
    production.work_order_consumption,
    production.work_order_inputs,
    production.work_orders
CASCADE;

-- Restart OF- numbering from scratch now that no order survives to collide with.
-- next_sequence_value re-seeds the row lazily on the first create.
DELETE FROM core.sequences WHERE name = 'production.work_orders';

-- `quantity` was ambiguous the moment reports started carrying produced figures:
-- this column is what was planned, never what came out of the line.
ALTER TABLE production.work_orders RENAME COLUMN quantity TO planned_quantity;

-- Closing an OF is an archival act — nothing is deleted, nothing moves — rather
-- than a completion that receives output, so `completed_at` takes the name the
-- new lifecycle actually uses.
ALTER TABLE production.work_orders RENAME COLUMN completed_at TO closed_at;

-- Planning fields captured when the OF is opened, and the closure trail. The OF's
-- "machine" is its existing work_center_id — no new column, no new entity.
ALTER TABLE production.work_orders ADD COLUMN IF NOT EXISTS start_date DATE;
ALTER TABLE production.work_orders ADD COLUMN IF NOT EXISTS product_type TEXT;
ALTER TABLE production.work_orders ADD COLUMN IF NOT EXISTS notes TEXT;
ALTER TABLE production.work_orders ADD COLUMN IF NOT EXISTS created_by TEXT;
ALTER TABLE production.work_orders ADD COLUMN IF NOT EXISTS closed_by TEXT;

-- Five-value vocabulary replacing draft/in_progress/completed. The transition map
-- itself lives in domain/entities.py; this constraint only keeps the table from
-- holding a status the domain has no rule for.
ALTER TABLE production.work_orders ALTER COLUMN status SET DEFAULT 'planned';
ALTER TABLE production.work_orders DROP CONSTRAINT IF EXISTS work_orders_status_check;
ALTER TABLE production.work_orders ADD CONSTRAINT work_orders_status_check
    CHECK (status IN ('planned', 'ongoing', 'suspended', 'closed', 'cancelled'));

CREATE INDEX IF NOT EXISTS work_orders_tenant_status_idx ON production.work_orders (tenant_id, status);
