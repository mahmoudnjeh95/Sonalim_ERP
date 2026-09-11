-- Fuel, gasoil, film, carton and ruban (tape) can each arrive from more than
-- one fournisseur. These columns let a report say which one supplied the
-- batch actually consumed -- informational only, like the rest of this
-- module's product_id-shaped columns: no stock lot behind it, and never
-- required to submit or validate a report.
--
-- Partner is shared-kernel (core.partners), so production may reference it
-- directly, same as procurement.purchase_orders.supplier_id already does.
ALTER TABLE production.daily_reports ADD COLUMN IF NOT EXISTS fuel_supplier_id TEXT REFERENCES core.partners (id);
ALTER TABLE production.daily_reports ADD COLUMN IF NOT EXISTS gasoil_supplier_id TEXT REFERENCES core.partners (id);

ALTER TABLE production.conditionnement_reports ADD COLUMN IF NOT EXISTS film_supplier_id TEXT REFERENCES core.partners (id);
ALTER TABLE production.conditionnement_reports ADD COLUMN IF NOT EXISTS carton_supplier_id TEXT REFERENCES core.partners (id);
ALTER TABLE production.conditionnement_reports ADD COLUMN IF NOT EXISTS tape_supplier_id TEXT REFERENCES core.partners (id);
