-- Invoice lines for what is not a stocked product: a service, a fee, a lump sum. A line then carries a
-- description and no product. Invoices created before lines existed (a single amount, no VAT) get one line
-- with their amount so every invoice is made of lines; their totals do not change.
ALTER TABLE finance.invoice_lines ALTER COLUMN product_id DROP NOT NULL;
ALTER TABLE finance.invoice_lines ADD COLUMN IF NOT EXISTS description TEXT;
-- The order lines were typed in; lines from deliveries have none and keep sorting by id.
ALTER TABLE finance.invoice_lines ADD COLUMN IF NOT EXISTS line_no INTEGER;

INSERT INTO finance.invoice_lines (id, tenant_id, invoice_id, product_id, description, quantity, unit_price, amount, vat_rate)
SELECT 'IL' || substr(md5(i.id || ':single-amount'), 1, 24), i.tenant_id, i.id, NULL,
       'Montant global / Lump sum', 1, ROUND(COALESCE(i.amount_excl_tax, i.amount), 2), ROUND(COALESCE(i.amount_excl_tax, i.amount), 2), 0
FROM finance.invoices i
WHERE NOT EXISTS (SELECT 1 FROM finance.invoice_lines l WHERE l.invoice_id = i.id)
ON CONFLICT DO NOTHING;
