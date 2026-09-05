-- Two new figures a shift records for later recipe statistics (not built yet --
-- see PRODUCTION_RECIPE_STATISTICS_PLAN.md), plus two more déchet stages.
--
-- Water is dosed on the mixer as a percentage of the semoule poured, not read
-- off a meter in litres -- that is how the plant actually sets it, so that is
-- what the form should capture. `water_percentage` is the operator's real
-- input; `water_quantity` stays the stored litre figure (every downstream
-- reader -- consolidation, the cockpit -- already expects it) and the
-- frontend derives it from the percentage. Nullable-by-zero, like every other
-- quantity on this table: 0 means "not entered," not "measured at zero."
ALTER TABLE production.daily_reports ADD COLUMN IF NOT EXISTS water_percentage NUMERIC NOT NULL DEFAULT 0;

-- Débit de semoule: how fast semoule was fed into the line, in tonnes/hour.
-- Recorded only -- nothing downstream reads it yet.
ALTER TABLE production.daily_reports ADD COLUMN IF NOT EXISTS semolina_flow_rate NUMERIC NOT NULL DEFAULT 0;

COMMENT ON COLUMN production.daily_reports.water_percentage IS
    'Water dosed as a percentage of the semoule poured this shift. The operator''s real input; water_quantity is derived from it and kept in sync by the frontend.';
COMMENT ON COLUMN production.daily_reports.semolina_flow_rate IS
    'Semoule feed rate in tonnes/hour. Recorded for future recipe statistics only -- see PRODUCTION_RECIPE_STATISTICS_PLAN.md.';

-- Déchet can also be lost pouring the mix (versement) or at cutting (découpe),
-- not only at raw material intake and the press. Same table, same rule as
-- 0022: a stage belongs to one report type, and both are daily-report stages.
ALTER TABLE production.report_waste_lines DROP CONSTRAINT IF EXISTS report_waste_lines_category_check;
ALTER TABLE production.report_waste_lines
    ADD CONSTRAINT report_waste_lines_category_check
    CHECK (category IN ('raw_material', 'press', 'pouring', 'cutting', 'product', 'packaging'));
