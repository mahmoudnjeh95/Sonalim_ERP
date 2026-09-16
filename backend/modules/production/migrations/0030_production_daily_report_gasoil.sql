-- The plant runs two distinct fuels on the line, fioul (fuel_quantity) and
-- gasoil (diesel) -- the original daily report form only ever had a place for
-- one of them, so gasoil consumption was never recorded at all.
ALTER TABLE production.daily_reports ADD COLUMN IF NOT EXISTS gasoil_quantity NUMERIC NOT NULL DEFAULT 0;

COMMENT ON COLUMN production.daily_reports.gasoil_quantity IS
    'Gasoil (diesel) consumed this shift, litres. Recorded alongside fuel_quantity (fioul) -- two separate fuels, two separate figures.';
