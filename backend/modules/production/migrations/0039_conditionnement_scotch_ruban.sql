-- Splits the old single "tape" figure into two real, independent consumables:
-- scotch (carton sealing tape) and ruban (printer ribbon -- TB200/Videojet are
-- just different products a shift can pick, not a separate field). Until now
-- both were recorded through one tape_quantity/tape_product_id/tape_supplier_id
-- trio, and the RUBAN product tag matched both "ruban" and "scotch" by name --
-- so a shift using both in the same run could only record one of them, and
-- monthly consumption-by-supplier reporting could not tell them apart.
--
-- tape_* columns are left in place, undropped and no longer written by new
-- reports -- see the platform's no-drop-while-still-referenced migration rule.
ALTER TABLE production.conditionnement_reports ADD COLUMN IF NOT EXISTS scotch_quantity NUMERIC NOT NULL DEFAULT 0;
ALTER TABLE production.conditionnement_reports ADD COLUMN IF NOT EXISTS scotch_product_id TEXT REFERENCES core.products (id);
ALTER TABLE production.conditionnement_reports ADD COLUMN IF NOT EXISTS scotch_supplier_id TEXT REFERENCES core.partners (id);

ALTER TABLE production.conditionnement_reports ADD COLUMN IF NOT EXISTS ruban_quantity NUMERIC NOT NULL DEFAULT 0;
ALTER TABLE production.conditionnement_reports ADD COLUMN IF NOT EXISTS ruban_product_id TEXT REFERENCES core.products (id);
ALTER TABLE production.conditionnement_reports ADD COLUMN IF NOT EXISTS ruban_supplier_id TEXT REFERENCES core.partners (id);

-- One-time reclassification of history: everything recorded under the old
-- shared "tape" bucket becomes Scotch by default (the more generic of the two
-- original uses). A historical row that was actually ribbon will show under
-- Scotch rather than Ruban -- there is no way to tell the two apart
-- retroactively from a single figure, so this is a documented approximation,
-- not a correction.
UPDATE production.conditionnement_reports
SET scotch_quantity = tape_quantity,
    scotch_product_id = tape_product_id,
    scotch_supplier_id = tape_supplier_id
WHERE tape_quantity > 0;

COMMENT ON COLUMN production.conditionnement_reports.tape_quantity IS
    'Deprecated: superseded by scotch_quantity and ruban_quantity. No longer written by new reports; kept for historical reads only.';
COMMENT ON COLUMN production.conditionnement_reports.tape_product_id IS
    'Deprecated: superseded by scotch_product_id and ruban_product_id.';
COMMENT ON COLUMN production.conditionnement_reports.tape_supplier_id IS
    'Deprecated: superseded by scotch_supplier_id and ruban_supplier_id.';
