-- VAT on sales invoices and customer credit notes. Lines carry the net price (after the order's line and
-- order discounts) and their VAT rate; the document carries its excluding-tax total and its VAT, and
-- `amount` stays what the customer owes, VAT included. Existing documents had no VAT: their lines get 0 %
-- and their excluding-tax total is their amount, so nothing they say changes.
ALTER TABLE finance.invoice_lines ADD COLUMN IF NOT EXISTS vat_rate NUMERIC(5, 2) NOT NULL DEFAULT 0
    CHECK (vat_rate >= 0 AND vat_rate <= 100);
ALTER TABLE finance.invoice_lines ADD COLUMN IF NOT EXISTS discount_rate NUMERIC(7, 4) NOT NULL DEFAULT 0;
ALTER TABLE finance.invoice_lines ADD COLUMN IF NOT EXISTS list_price NUMERIC(18, 4);
ALTER TABLE finance.credit_note_lines ADD COLUMN IF NOT EXISTS vat_rate NUMERIC(5, 2) NOT NULL DEFAULT 0
    CHECK (vat_rate >= 0 AND vat_rate <= 100);

ALTER TABLE finance.invoices ADD COLUMN IF NOT EXISTS amount_excl_tax NUMERIC(18, 2);
ALTER TABLE finance.invoices ADD COLUMN IF NOT EXISTS vat_amount NUMERIC(18, 2) NOT NULL DEFAULT 0;
UPDATE finance.invoices SET amount_excl_tax = amount WHERE amount_excl_tax IS NULL;

ALTER TABLE finance.credit_notes ADD COLUMN IF NOT EXISTS amount_excl_tax NUMERIC(18, 2);
ALTER TABLE finance.credit_notes ADD COLUMN IF NOT EXISTS vat_amount NUMERIC(18, 2) NOT NULL DEFAULT 0;
UPDATE finance.credit_notes SET amount_excl_tax = amount WHERE amount_excl_tax IS NULL;

-- Collected VAT on sales posts through its own rule (invoice / vat / *), to_confirm like the others;
-- tenants that already ran the finance setup get it here, new ones from the seeded rules.
INSERT INTO finance.posting_rules (id, tenant_id, source, source_kind, code, debit_account_code, credit_account_code, journal_code, status)
SELECT 'PR' || substr(md5(t.tenant_id || ':invoice:vat'), 1, 24), t.tenant_id, 'invoice', 'vat', '*', NULL, '443', NULL, 'to_confirm'
FROM (SELECT DISTINCT tenant_id FROM finance.posting_rules) t
WHERE EXISTS (SELECT 1 FROM finance.accounts a WHERE a.tenant_id = t.tenant_id AND a.code = '443')
ON CONFLICT DO NOTHING;
