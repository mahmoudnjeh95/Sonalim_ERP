-- "découpe" is renamed to "Cross" -- the plant's own name for the stage, not a
-- translation -- and two more daily-report stages join it: pétrin (kneading)
-- and PF cdt (finished product at conditioning). Existing rows are relabelled
-- rather than left behind, same as any other rename: a category is a name for
-- a stage, and the stage a 'cutting' row described still happened.
--
-- The constraint is dropped before the rename, not after: the old constraint
-- still only allows 'cutting', and would reject the very UPDATE that renames
-- rows away from it.
ALTER TABLE production.report_waste_lines DROP CONSTRAINT IF EXISTS report_waste_lines_category_check;

UPDATE production.report_waste_lines SET category = 'cross' WHERE category = 'cutting';

ALTER TABLE production.report_waste_lines
    ADD CONSTRAINT report_waste_lines_category_check
    CHECK (category IN ('raw_material', 'press', 'pouring', 'cross', 'kneading', 'finished_product_conditioning', 'product', 'packaging'));
