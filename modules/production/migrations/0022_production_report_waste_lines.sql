-- Waste stops being six columns and becomes a list of what was actually thrown out.
--
-- The old shape had one column per category the plant happened to name first:
-- déchet matière, déchet presse, déchet produit, déchet film, déchet carton. It
-- could not record scotch at all, and worse, none of the figures said what item
-- they counted -- so the screens borrowed the unit of whatever product seemed
-- closest and reported five broken cartons as "5 t" of semoule. A category is not
-- an item, and only an item has a unit.
--
-- Each line now names its product, so the quantity is finally in a unit the
-- warehouse would recognise, and a shift can record as many kinds of waste as it
-- had. The category survives because the plant genuinely distinguishes semoule
-- spilt before the press from dough lost at it, and both may be the same product.
--
-- These lines move no stock, and that is deliberate rather than unfinished:
-- semoule was deducted when it was poured, packaging when it was consumed, and
-- the finished product only ever enters stock at the good quantity. Deducting
-- waste as well would take the same material out twice. Naming a product here is
-- about saying what was lost and in what unit, not about moving it.
CREATE TABLE IF NOT EXISTS production.report_waste_lines (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    report_id TEXT NOT NULL REFERENCES production.production_reports (id) ON DELETE CASCADE,

    -- Where in the process it was lost. Constrained rather than free text: these
    -- are the stages the plant's own paper form has, and a typo would silently
    -- split a category in the OF's consolidation.
    category TEXT NOT NULL CHECK (category IN ('raw_material', 'press', 'product', 'packaging')),

    -- The item lost. TEXT with no foreign key, like every other product reference
    -- in this module -- production may not reference core's tables directly.
    --
    -- Nullable only so the backfill below can be honest about figures recorded
    -- before anyone was asked which item they counted. New lines must name one;
    -- the service enforces that, because a quantity with no item has no unit.
    product_id TEXT,

    quantity NUMERIC NOT NULL DEFAULT 0 CHECK (quantity >= 0),
    note TEXT,
    -- Preserves the order the shift entered them in; nothing else depends on it.
    line_order INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS report_waste_lines_report_idx
    ON production.report_waste_lines (tenant_id, report_id);

-- Backfill. Only figures above zero become lines: a column that was left at zero
-- recorded nothing, and turning it into a line would invent a waste event.
--
-- Déchet matière is semoule by definition, so it takes the report's own semoule
-- product. Déchet presse is dough, which no product on the report names -- it is
-- left unattributed rather than labelled semoule, because the whole point of this
-- change is to stop guessing which item a figure counted. The same applies to
-- déchet produit, which becomes the OF's finished product because that is exactly
-- what packing scraps.
INSERT INTO production.report_waste_lines (id, tenant_id, report_id, category, product_id, quantity, line_order)
SELECT gen_random_uuid()::text, d.tenant_id, d.report_id, 'raw_material', d.semolina_product_id,
       d.raw_material_waste_quantity, 0
FROM production.daily_reports d
WHERE d.raw_material_waste_quantity > 0;

INSERT INTO production.report_waste_lines (id, tenant_id, report_id, category, product_id, quantity, line_order)
SELECT gen_random_uuid()::text, d.tenant_id, d.report_id, 'press', NULL, d.press_waste_quantity, 1
FROM production.daily_reports d
WHERE d.press_waste_quantity > 0;

INSERT INTO production.report_waste_lines (id, tenant_id, report_id, category, product_id, quantity, line_order)
SELECT gen_random_uuid()::text, c.tenant_id, c.report_id, 'product', w.product_id, c.product_waste_quantity, 0
FROM production.conditionnement_reports c
JOIN production.production_reports r ON r.id = c.report_id AND r.tenant_id = c.tenant_id
JOIN production.work_orders w ON w.id = r.of_id AND w.tenant_id = r.tenant_id
WHERE c.product_waste_quantity > 0;

INSERT INTO production.report_waste_lines (id, tenant_id, report_id, category, product_id, quantity, line_order)
SELECT gen_random_uuid()::text, c.tenant_id, c.report_id, 'packaging', c.film_product_id, c.film_waste_quantity, 1
FROM production.conditionnement_reports c
WHERE c.film_waste_quantity > 0;

INSERT INTO production.report_waste_lines (id, tenant_id, report_id, category, product_id, quantity, line_order)
SELECT gen_random_uuid()::text, c.tenant_id, c.report_id, 'packaging', c.carton_product_id, c.carton_waste_quantity, 2
FROM production.conditionnement_reports c
WHERE c.carton_waste_quantity > 0;

-- The columns go. Keeping them beside the lines would give every waste figure two
-- homes that can disagree, which is the failure this rebuild has been removing
-- everywhere else.
ALTER TABLE production.daily_reports DROP COLUMN IF EXISTS raw_material_waste_quantity;
ALTER TABLE production.daily_reports DROP COLUMN IF EXISTS press_waste_quantity;
ALTER TABLE production.conditionnement_reports DROP COLUMN IF EXISTS product_waste_quantity;
ALTER TABLE production.conditionnement_reports DROP COLUMN IF EXISTS film_waste_quantity;
ALTER TABLE production.conditionnement_reports DROP COLUMN IF EXISTS carton_waste_quantity;

-- Rebroyat is not waste and does not join the list: it is recovered material that
-- opens its own OF and goes back into a mix. But it was the other figure with no
-- item behind it -- the scrap record it creates borrowed the OF's finished
-- product, which is why a shift's rebroyat was reported in packets rather than in
-- the kilos it is actually weighed in.
--
-- Left NULL on existing rows on purpose. The service still falls back to the OF's
-- product when it is unset, so nothing that already validated changes meaning;
-- what changes is that a shift can now say what the rebroyat really is.
ALTER TABLE production.daily_reports ADD COLUMN IF NOT EXISTS regrind_product_id TEXT;

COMMENT ON COLUMN production.daily_reports.regrind_product_id IS
    'The item this shift''s rebroyat is, and what the scrap record and regrind OF are opened against. NULL falls back to the OF''s finished product, which is what happened before this column existed.';
