-- Rebroyat poured back in.
--
-- The daily report recorded rebroyat *generated* as waste, but nothing recorded
-- rebroyat *consumed* — so recycled material re-entered production untracked, and
-- any ratio measured against "what was poured in" understated the input. This is
-- the missing half: semoule and rebroyat are both raw material going into the mix,
-- and both leave stock when the report is validated.
ALTER TABLE production.daily_reports ADD COLUMN IF NOT EXISTS regrind_input_quantity NUMERIC NOT NULL DEFAULT 0;
ALTER TABLE production.daily_reports ADD COLUMN IF NOT EXISTS regrind_input_product_id TEXT;

COMMENT ON COLUMN production.daily_reports.regrind_input_quantity IS
    'Rebroyat poured into the mix this shift. Deducted from stock on validation, alongside semolina. Not to be confused with regrind_quantity, which is the rebroyat this shift produced.';
