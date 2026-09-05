-- Phase 3: the conditionnement (packing) report. It reuses the shared header in
-- production.production_reports — one row per report of type 'conditionnement' —
-- so status, revision, validation trail and the revision snapshots all work
-- exactly as they do for the daily report.
--
-- This is the report that owns the finished product. From Phase 5, validating it
-- is what brings the finished product INTO stock and takes film, cartons and tape
-- OUT; the daily report's own finished-product figure stays a recorded number.
CREATE TABLE IF NOT EXISTS production.conditionnement_reports (
    report_id TEXT PRIMARY KEY REFERENCES production.production_reports (id),
    tenant_id TEXT NOT NULL,

    -- The tonnage that actually becomes sellable stock.
    finished_product_quantity NUMERIC NOT NULL DEFAULT 0,

    -- Packaging consumed. Deducted once, here — never again when quality strips a
    -- rejected packet back down into its components.
    film_quantity NUMERIC NOT NULL DEFAULT 0,
    carton_quantity NUMERIC NOT NULL DEFAULT 0,
    tape_quantity NUMERIC NOT NULL DEFAULT 0,

    product_waste_quantity NUMERIC NOT NULL DEFAULT 0,
    film_waste_quantity NUMERIC NOT NULL DEFAULT 0,
    carton_waste_quantity NUMERIC NOT NULL DEFAULT 0,

    machine_speed NUMERIC,
    production_minutes INTEGER NOT NULL DEFAULT 0,
    downtime_minutes INTEGER NOT NULL DEFAULT 0,
    downtime_reason TEXT,

    -- DLC. On validation these become a real warehouse.lots row with an expiry
    -- date, written through the warehouse service — production never touches that
    -- table itself.
    lot_number TEXT,
    dlc_date DATE
);
