-- XOF (F CFA) is the project's default currency. Order lines defaulted to 'EUR' although the
-- New Order dialog never enters a price (it comes from the receipt's landed cost): zero-priced
-- lines only carry that hidden default, so they are relabelled XOF. Priced lines and receipts
-- keep their real currency -- relabelling those would silently change their meaning.
ALTER TABLE procurement.purchase_order_lines ALTER COLUMN unit_price_currency SET DEFAULT 'XOF';
UPDATE procurement.purchase_order_lines SET unit_price_currency = 'XOF'
WHERE unit_price_currency <> 'XOF' AND unit_price = 0;
