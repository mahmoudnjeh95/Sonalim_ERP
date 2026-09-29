-- SYSCOHADA ledger, master data: chart of accounts, journals, fiscal years with their monthly
-- periods, and the posting rules that turn payroll runs and invoices into entries. All per
-- tenant; the seed rows are written by ChartSetupService (POST /finance/setup), not here.

CREATE TABLE IF NOT EXISTS finance.accounts (
    tenant_id TEXT NOT NULL,
    code TEXT NOT NULL CHECK (code ~ '^[1-9][0-9]{0,9}$'),
    name TEXT NOT NULL CHECK (btrim(name) <> ''),
    class_no SMALLINT NOT NULL CHECK (class_no BETWEEN 1 AND 9),
    account_type TEXT NOT NULL CHECK (account_type IN ('asset', 'liability', 'equity', 'income', 'expense')),
    is_postable BOOLEAN NOT NULL DEFAULT TRUE,
    parent_code TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (tenant_id, code),
    CHECK (class_no = substr(code, 1, 1)::int),
    FOREIGN KEY (tenant_id, parent_code) REFERENCES finance.accounts (tenant_id, code)
);

CREATE TABLE IF NOT EXISTS finance.journals (
    tenant_id TEXT NOT NULL,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    journal_type TEXT NOT NULL CHECK (journal_type IN ('payroll', 'sales', 'purchases', 'bank', 'cash', 'general')),
    PRIMARY KEY (tenant_id, code)
);

-- SYSCOHADA: the fiscal year is the calendar year, cut into twelve monthly periods.
CREATE TABLE IF NOT EXISTS finance.fiscal_years (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    year INTEGER NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, year),
    CHECK (end_date > start_date)
);

CREATE TABLE IF NOT EXISTS finance.periods (
    tenant_id TEXT NOT NULL,
    period DATE NOT NULL CHECK (EXTRACT(DAY FROM period) = 1),
    fiscal_year_id TEXT NOT NULL REFERENCES finance.fiscal_years (id),
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed')),
    closed_by TEXT,
    closed_at TIMESTAMPTZ,
    PRIMARY KEY (tenant_id, period)
);

-- (source, source_kind, code) -> accounts. code '*' is the fallback of its kind. Payment and
-- invoice rules also name the journal their entry goes to.
CREATE TABLE IF NOT EXISTS finance.posting_rules (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    source TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    code TEXT NOT NULL,
    debit_account_code TEXT,
    credit_account_code TEXT,
    journal_code TEXT,
    status TEXT NOT NULL DEFAULT 'to_confirm' CHECK (status IN ('to_confirm', 'confirmed')),
    confirmed_by TEXT,
    confirmed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, source, source_kind, code),
    CHECK (debit_account_code IS NOT NULL OR credit_account_code IS NOT NULL),
    FOREIGN KEY (tenant_id, debit_account_code) REFERENCES finance.accounts (tenant_id, code),
    FOREIGN KEY (tenant_id, credit_account_code) REFERENCES finance.accounts (tenant_id, code),
    FOREIGN KEY (tenant_id, journal_code) REFERENCES finance.journals (tenant_id, code)
);
