-- The tax code (core.tax_codes.code) each purchase invoice line was given, a snapshot like vat_rate. Lines written
-- before tax codes have none. A credit-note line takes its invoice line's code while it keeps that line's rate.
ALTER TABLE procurement.purchase_invoice_lines ADD COLUMN IF NOT EXISTS tax_code TEXT;
