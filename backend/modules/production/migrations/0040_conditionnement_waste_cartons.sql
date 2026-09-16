-- Cartons the line counted that never held sellable product -- empty or
-- damaged, swept into carton_quantity the same as a good one today, with no
-- way to tell the two apart afterwards. That silently did two things wrong:
-- finished_product_quantity/stock posting (decision 24) treated every counted
-- carton as a full one, overstating what actually moved into finished goods,
-- and the packaging ecart (Phase 9, decisions 17-23) read the same cartons
-- back as unaccounted product because nothing netted them out.
--
-- A subset of carton_quantity, not a separate consumption: the carton blanks
-- themselves were already deducted from packaging stock through
-- carton_quantity, so this column carries no product_id/supplier_id of its
-- own -- see the domain comment on ConditionnementReportDetail.waste_carton_quantity.
ALTER TABLE production.conditionnement_reports
    ADD COLUMN IF NOT EXISTS waste_carton_quantity NUMERIC NOT NULL DEFAULT 0;

COMMENT ON COLUMN production.conditionnement_reports.waste_carton_quantity IS
    'Part of carton_quantity that held no sellable product (empty/damaged cartons). Subtracted from carton_quantity wherever that count feeds finished-goods stock or the packaging ecart.';
