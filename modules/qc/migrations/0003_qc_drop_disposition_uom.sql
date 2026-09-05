-- The free-text `uom` a user typed on a disposition line never resolved
-- against core.uoms/core.products and was never read back for anything --
-- 0 live rows carried a value at the time this was dropped. The unit shown
-- for a disposition line is now resolved instead: the non-conformity's own
-- product for a "product" line, a fixed label for film/carton/tape (see
-- modules/qc/api/router.py's _serialize_disposition).
ALTER TABLE qc.nc_dispositions DROP COLUMN IF EXISTS uom;
