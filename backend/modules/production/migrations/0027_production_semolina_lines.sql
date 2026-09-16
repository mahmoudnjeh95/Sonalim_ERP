-- Semoule stops being one column and becomes a list of what was actually poured.
--
-- The plant runs more than one quality of semoule (semoule extra, semoule
-- courante, and so on), and a shift can pour a mix of them into the same run.
-- One `semolina_quantity` / `semolina_product_id` pair per report could only
-- ever name one, so a mixed pour had nowhere honest to go -- exactly the same
-- problem `report_waste_lines` (0022) solved for déchets, and the same fix
-- applies here.
--
-- Each line also names its own store: unlike rebroyat, which still shares
-- `raw_material_location_id`, different semoule qualities are routinely kept
-- in different silos, and a single report-wide location would have forced a
-- lie onto whichever quality wasn't stored there.
--
-- Rebroyat poured back into the mix (regrind_input_quantity/product_id) is
-- deliberately left alone: there is only ever one rebroyat product tenant-wide
-- now (0027 companion change in regrind_service.py), so a list would have
-- nothing to enumerate.
CREATE TABLE IF NOT EXISTS production.report_semolina_lines (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    report_id TEXT NOT NULL REFERENCES production.production_reports (id) ON DELETE CASCADE,

    -- Nullable while a draft is still being typed, same as report_waste_lines:
    -- a team must be able to save a quantity before deciding which quality it
    -- was. Required to submit -- see validate_daily_stock_targets.
    product_id TEXT,
    quantity NUMERIC NOT NULL DEFAULT 0 CHECK (quantity >= 0),

    -- Per line, not per report -- see the comment above.
    location_id TEXT,

    -- Preserves the order the shift entered them in; nothing else depends on it.
    line_order INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS report_semolina_lines_report_idx
    ON production.report_semolina_lines (tenant_id, report_id);

ALTER TABLE production.report_semolina_lines
    ADD CONSTRAINT report_semolina_lines_product_id_fkey FOREIGN KEY (product_id) REFERENCES core.products (id);

-- Backfill. Only figures above zero become lines, matching 0022: a column left
-- at zero recorded nothing, and turning it into a line would invent a pour.
-- A report with a quantity but no product (never legal past draft, per
-- validate_daily_stock_targets) is skipped rather than guessed at.
INSERT INTO production.report_semolina_lines (id, tenant_id, report_id, product_id, quantity, location_id, line_order)
SELECT gen_random_uuid()::text, d.tenant_id, d.report_id, d.semolina_product_id, d.semolina_quantity, d.raw_material_location_id, 0
FROM production.daily_reports d
WHERE d.semolina_quantity > 0 AND d.semolina_product_id IS NOT NULL;

-- The columns go. Keeping them beside the lines would give the semoule figure
-- two homes that can disagree, which is the failure this rebuild keeps removing.
-- `raw_material_location_id` stays: rebroyat still uses it.
ALTER TABLE production.daily_reports DROP COLUMN IF EXISTS semolina_quantity;
ALTER TABLE production.daily_reports DROP COLUMN IF EXISTS semolina_product_id;

COMMENT ON COLUMN production.daily_reports.raw_material_location_id IS
    'Rebroyat''s store only, now that semoule carries its own per-line location in report_semolina_lines.';
