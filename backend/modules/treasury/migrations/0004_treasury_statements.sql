CREATE TABLE IF NOT EXISTS treasury.statement_imports (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    account_id TEXT NOT NULL REFERENCES treasury.accounts (id),
    filename TEXT NOT NULL,
    imported_by TEXT,
    imported_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    row_count INT NOT NULL DEFAULT 0,
    skipped_count INT NOT NULL DEFAULT 0
);

-- debit > 0 is money in (a customer), credit > 0 is money out (a supplier), as in the bank's
-- own statement. A line is matched to at most one recorded payment; matching changes no balance
-- (the movement already exists), it only marks both sides as reconciled.
CREATE TABLE IF NOT EXISTS treasury.bank_statement_lines (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    import_id TEXT NOT NULL REFERENCES treasury.statement_imports (id),
    account_id TEXT NOT NULL REFERENCES treasury.accounts (id),
    seq INT NOT NULL,
    line_date DATE NOT NULL,
    label TEXT NOT NULL DEFAULT '',
    debit NUMERIC(18, 2) NOT NULL DEFAULT 0 CHECK (debit >= 0),
    credit NUMERIC(18, 2) NOT NULL DEFAULT 0 CHECK (credit >= 0),
    balance NUMERIC(18, 2),
    partner_id TEXT REFERENCES core.partners (id),
    matched_payment_id TEXT REFERENCES treasury.document_payments (id),
    reconciled_at TIMESTAMPTZ,
    CHECK ((debit > 0) <> (credit > 0))
);
CREATE INDEX IF NOT EXISTS statement_lines_account_idx ON treasury.bank_statement_lines (account_id, line_date, seq);
CREATE UNIQUE INDEX IF NOT EXISTS statement_lines_payment_uq
    ON treasury.bank_statement_lines (matched_payment_id) WHERE matched_payment_id IS NOT NULL;

-- Per-account column mapping and formats for a bank whose export differs from the default layout.
CREATE TABLE IF NOT EXISTS treasury.statement_profiles (
    account_id TEXT PRIMARY KEY REFERENCES treasury.accounts (id),
    tenant_id TEXT NOT NULL,
    profile_json JSONB NOT NULL
);
