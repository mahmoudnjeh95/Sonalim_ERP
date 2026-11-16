-- A count that disagrees with the books must be confirmed: two equal counts settle the line, two
-- different ones need a third. counted_quantity stays the settled figure; the raw entries live here.
ALTER TABLE warehouse.cycle_count_lines ADD COLUMN IF NOT EXISTS count_1 NUMERIC;
ALTER TABLE warehouse.cycle_count_lines ADD COLUMN IF NOT EXISTS count_2 NUMERIC;
ALTER TABLE warehouse.cycle_count_lines ADD COLUMN IF NOT EXISTS count_3 NUMERIC;
