-- Phase 5 groundwork: make a stock movement say what caused it, and give the
-- plant somewhere to put product that must not be sold.

-- Until now a movement's origin was a free-text `reference` of the form
-- `work_order:{id}`. Once validation is what posts stock, every movement has to
-- name the report that caused it and the OF it belongs to, so consolidation and
-- an audit can both work backwards from a number in inventory to the shift that
-- produced it. No foreign keys: production and qc own those rows, and a warehouse
-- table may not reference another module's schema.
ALTER TABLE warehouse.stock_moves ADD COLUMN IF NOT EXISTS source_type TEXT;
ALTER TABLE warehouse.stock_moves ADD COLUMN IF NOT EXISTS source_id TEXT;
ALTER TABLE warehouse.stock_moves ADD COLUMN IF NOT EXISTS of_id TEXT;

CREATE INDEX IF NOT EXISTS stock_moves_source_idx
    ON warehouse.stock_moves (tenant_id, source_type, source_id);
CREATE INDEX IF NOT EXISTS stock_moves_of_idx
    ON warehouse.stock_moves (tenant_id, of_id) WHERE of_id IS NOT NULL;

-- Quarantine. Between quality pulling a rejected packet and someone deciding its
-- fate, the goods physically exist and must not be sellable — a blocked location
-- represents that honestly and keeps both movements auditable. Stock sitting in a
-- blocked location is excluded from available quantity, so no other module can
-- promise it, but it stays on the books at value because it has not been written
-- off yet: it is awaiting a decision.
ALTER TABLE warehouse.locations ADD COLUMN IF NOT EXISTS is_blocked BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE warehouse.locations ADD COLUMN IF NOT EXISTS blocked_reason TEXT;

CREATE INDEX IF NOT EXISTS locations_blocked_idx
    ON warehouse.locations (tenant_id) WHERE is_blocked;
