-- Phase 5: a report has to say exactly what it moved and where.
--
-- The figures alone are not enough to post stock — "semolina 1000" names no
-- product and no store. Rather than infer them from the OF's recipe and BOM, each
-- report names them explicitly: a shift that substitutes a material reports what
-- it actually used, and the record cannot silently drift from the formula.
--
-- All of these are plain TEXT with no foreign key into warehouse: production may
-- not reference another module's tables. They are resolved through the warehouse
-- service when the report is validated.

-- Daily report: semolina is the only figure here that leaves stock. Water, fuel
-- and electricity are metered utilities, not inventory, and the finished-product
-- figure is recorded for yield only — the conditionnement report owns that tonnage.
ALTER TABLE production.daily_reports ADD COLUMN IF NOT EXISTS semolina_product_id TEXT;
ALTER TABLE production.daily_reports ADD COLUMN IF NOT EXISTS raw_material_location_id TEXT;

-- Conditionnement: packaging leaves stock, finished product enters it. The
-- finished product itself is the OF's product and is not repeated here — naming it
-- again would let a report contradict the order it belongs to.
ALTER TABLE production.conditionnement_reports ADD COLUMN IF NOT EXISTS film_product_id TEXT;
ALTER TABLE production.conditionnement_reports ADD COLUMN IF NOT EXISTS carton_product_id TEXT;
ALTER TABLE production.conditionnement_reports ADD COLUMN IF NOT EXISTS tape_product_id TEXT;
ALTER TABLE production.conditionnement_reports ADD COLUMN IF NOT EXISTS packaging_location_id TEXT;
ALTER TABLE production.conditionnement_reports ADD COLUMN IF NOT EXISTS finished_goods_location_id TEXT;

-- A raw-material shortfall never blocks validation, but it does have to be
-- explained: the movement posts, the balance may go negative, and this is the
-- validator's account of why. Null on every report that balanced.
ALTER TABLE production.production_reports ADD COLUMN IF NOT EXISTS shortfall_comment TEXT;
