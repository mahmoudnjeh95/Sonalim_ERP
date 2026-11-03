CREATE SCHEMA IF NOT EXISTS treasury;

CREATE TABLE IF NOT EXISTS treasury.banks (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    name TEXT NOT NULL,
    code TEXT,
    swift TEXT,
    country TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS banks_name_uq ON treasury.banks (tenant_id, lower(name));

CREATE TABLE IF NOT EXISTS treasury.bank_branches (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    bank_id TEXT NOT NULL REFERENCES treasury.banks (id),
    name TEXT NOT NULL,
    city TEXT,
    address TEXT,
    phone TEXT
);
CREATE INDEX IF NOT EXISTS bank_branches_bank_idx ON treasury.bank_branches (bank_id);

-- One table for every place money sits: a bank account, a cash register or a mobile-money
-- wallet. Receipts and disbursements point at an account without caring which kind it is.
CREATE TABLE IF NOT EXISTS treasury.accounts (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('bank', 'cash', 'mobile_money')),
    name TEXT NOT NULL,
    currency TEXT NOT NULL REFERENCES core.currencies (code),
    account_number TEXT,
    iban TEXT,
    branch_id TEXT REFERENCES treasury.bank_branches (id),
    operator TEXT,
    phone TEXT,
    opening_balance NUMERIC(18, 2) NOT NULL DEFAULT 0,
    balance NUMERIC(18, 2) NOT NULL DEFAULT 0,
    allow_overdraft BOOLEAN NOT NULL DEFAULT FALSE,
    ledger_account_code TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS accounts_number_uq
    ON treasury.accounts (tenant_id, account_number) WHERE account_number IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS accounts_iban_uq
    ON treasury.accounts (tenant_id, iban) WHERE iban IS NOT NULL;

CREATE TABLE IF NOT EXISTS treasury.account_movements (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    account_id TEXT NOT NULL REFERENCES treasury.accounts (id),
    amount NUMERIC(18, 2) NOT NULL CHECK (amount <> 0),
    balance_after NUMERIC(18, 2) NOT NULL,
    source_type TEXT NOT NULL,
    source_id TEXT,
    occurred_on DATE NOT NULL,
    note TEXT,
    created_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS account_movements_account_idx
    ON treasury.account_movements (account_id, occurred_on);

CREATE TABLE IF NOT EXISTS treasury.settings (
    tenant_id TEXT NOT NULL,
    key TEXT NOT NULL,
    value_json JSONB,
    PRIMARY KEY (tenant_id, key)
);

-- Offsets are in days relative to the due date: positive = after, negative = before.
CREATE TABLE IF NOT EXISTS treasury.alert_rules (
    tenant_id TEXT NOT NULL,
    direction TEXT NOT NULL CHECK (direction IN ('in', 'out')),
    method TEXT NOT NULL CHECK (method IN ('cheque', 'draft')),
    offset_days INT NOT NULL,
    PRIMARY KEY (tenant_id, direction, method)
);

CREATE TABLE IF NOT EXISTS treasury.account_format_rules (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('bank', 'cash', 'mobile_money')),
    country TEXT,
    regex TEXT NOT NULL,
    hint_en TEXT,
    hint_fr TEXT
);
