-- Tax codes on sales invoice and credit-note lines (a snapshot of core.tax_codes.code, like vat_rate), and the
-- VAT register the VAT return is read from.
ALTER TABLE finance.invoice_lines ADD COLUMN IF NOT EXISTS tax_code TEXT;
ALTER TABLE finance.credit_note_lines ADD COLUMN IF NOT EXISTS tax_code TEXT;

-- One row per (document posting, tax code, rate), written in the same transaction as the journal entry that
-- books the VAT: what the VAT return declares. Amounts are F CFA and signed: a credit note, or the reversal of a
-- cancelled purchase invoice, is negative. Exempt and 0 % bases are recorded too.
CREATE TABLE IF NOT EXISTS finance.tax_entries (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    entry_date DATE NOT NULL,
    direction TEXT NOT NULL CHECK (direction IN ('collected', 'deductible')),
    tax_code TEXT,
    rate NUMERIC(5, 2),
    base NUMERIC(18, 2) NOT NULL,
    vat NUMERIC(18, 2) NOT NULL,
    account_code TEXT,
    partner_id TEXT,
    reference TEXT,
    source_module TEXT NOT NULL,
    source_id TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    journal_entry_id TEXT REFERENCES finance.journal_entries (id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS tax_entries_period_idx ON finance.tax_entries (tenant_id, entry_date);
CREATE INDEX IF NOT EXISTS tax_entries_source_idx ON finance.tax_entries (tenant_id, source_module, source_id, source_kind);
