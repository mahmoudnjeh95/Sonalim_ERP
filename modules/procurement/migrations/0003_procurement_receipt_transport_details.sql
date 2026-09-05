-- Carrier alone doesn't identify who actually showed up with the goods. These two
-- optional fields record the transport company and the individual driver for a receipt,
-- independent of (and alongside) the existing carrier field.
ALTER TABLE procurement.purchase_order_receipts
    ADD COLUMN IF NOT EXISTS transport_company_name TEXT,
    ADD COLUMN IF NOT EXISTS driver_name TEXT;
