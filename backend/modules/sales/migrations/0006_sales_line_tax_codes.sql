-- The tax code (core.tax_codes.code) each order and quote line was given, a snapshot like vat_rate.
-- Lines written before tax codes have none; their rate still says what they bear.
ALTER TABLE sales.order_lines ADD COLUMN IF NOT EXISTS tax_code TEXT;
ALTER TABLE sales.quote_lines ADD COLUMN IF NOT EXISTS tax_code TEXT;
