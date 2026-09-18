-- The groupe électrogène's consumption used to be typed straight in as a
-- litre total. The plant instead reads a rate off it (L/h) and how many
-- hours it ran, so those become the real inputs -- gasoil_quantity is now
-- derived from them on the frontend, the same way water_quantity is already
-- derived from water_percentage. Kept as its own column (rather than
-- replacing gasoil_quantity) because every downstream reader -- consolidation,
-- consumption reports -- already expects a litre total there.
ALTER TABLE production.daily_reports ADD COLUMN IF NOT EXISTS gasoil_flow_rate NUMERIC NOT NULL DEFAULT 0;
ALTER TABLE production.daily_reports ADD COLUMN IF NOT EXISTS generator_hours NUMERIC NOT NULL DEFAULT 0;

COMMENT ON COLUMN production.daily_reports.gasoil_flow_rate IS
    'Groupe électrogène consumption rate this shift, litres/hour. gasoil_quantity = this x generator_hours.';
COMMENT ON COLUMN production.daily_reports.generator_hours IS
    'Hours the groupe électrogène ran this shift.';
