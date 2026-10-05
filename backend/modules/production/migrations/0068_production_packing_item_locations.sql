-- Each packaging item on a packing row now draws from its own default storage location
-- instead of the whole row sharing one. Existing rows keep reading through
-- packaging_location_id (still written as the first item's store, for old readers);
-- these columns are the per-item stores stock is actually issued from.

ALTER TABLE production.shift_packing_rows ADD COLUMN IF NOT EXISTS film_location_id TEXT;
ALTER TABLE production.shift_packing_rows ADD COLUMN IF NOT EXISTS carton_location_id TEXT;
ALTER TABLE production.shift_packing_rows ADD COLUMN IF NOT EXISTS scotch_location_id TEXT;
ALTER TABLE production.shift_packing_rows ADD COLUMN IF NOT EXISTS ruban_location_id TEXT;

UPDATE production.shift_packing_rows
SET film_location_id = COALESCE(film_location_id, packaging_location_id),
    carton_location_id = COALESCE(carton_location_id, packaging_location_id),
    scotch_location_id = COALESCE(scotch_location_id, packaging_location_id),
    ruban_location_id = COALESCE(ruban_location_id, packaging_location_id)
WHERE packaging_location_id IS NOT NULL;
