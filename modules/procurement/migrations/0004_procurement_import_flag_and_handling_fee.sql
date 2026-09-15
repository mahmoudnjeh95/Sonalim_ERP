-- Point 1 of the MP cost-tracking plan: whether an order requires importation is decided
-- once, at order creation, and drives which landed-cost fees are even legal at receiving
-- time (see validate_receipt_fees) -- a local CFA purchase should never carry customs duty.
ALTER TABLE procurement.purchase_orders
    ADD COLUMN IF NOT EXISTS is_import BOOLEAN NOT NULL DEFAULT false;

-- "Cout de manutention" in the BD MP sheet -- handling is incurred on local and imported
-- purchases alike (unlike license/insurance/transit/customs, which are import-only), so it
-- lives alongside transport_fee rather than behind the is_import gate.
ALTER TABLE procurement.purchase_order_receipts
    ADD COLUMN IF NOT EXISTS handling_fee NUMERIC NOT NULL DEFAULT 0;
