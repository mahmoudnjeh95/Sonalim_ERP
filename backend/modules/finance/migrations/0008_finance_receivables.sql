-- Receivables: when each invoice falls due, how much credit a customer gets, and how late payers are chased.

-- The schedule an invoice was given from its customer's payment terms. The rule is kept on the invoice, so
-- changing the customer's terms or the catalog later never redates it.
ALTER TABLE finance.invoices ADD COLUMN IF NOT EXISTS due_date DATE;
ALTER TABLE finance.invoices ADD COLUMN IF NOT EXISTS payment_term_code TEXT;
ALTER TABLE finance.invoices ADD COLUMN IF NOT EXISTS payment_term_rule JSONB;
-- Invoices issued before terms existed fall due on their invoice date (paid on delivery).
UPDATE finance.invoices SET due_date = COALESCE(invoice_date, created_at::date) WHERE due_date IS NULL;

CREATE TABLE IF NOT EXISTS finance.invoice_installments (
    invoice_id TEXT NOT NULL REFERENCES finance.invoices (id),
    seq INT NOT NULL,
    due_date DATE NOT NULL,
    amount NUMERIC(18, 2) NOT NULL,
    PRIMARY KEY (invoice_id, seq)
);

CREATE TABLE IF NOT EXISTS finance.customer_credit (
    tenant_id TEXT NOT NULL,
    partner_id TEXT NOT NULL,
    -- NULL: no limit
    credit_limit NUMERIC(18, 2) CHECK (credit_limit IS NULL OR credit_limit >= 0),
    note TEXT,
    updated_by TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (tenant_id, partner_id)
);

CREATE TABLE IF NOT EXISTS finance.receivables_settings (
    tenant_id TEXT PRIMARY KEY,
    -- An order is refused when the customer has an invoice overdue by more than this; NULL turns the rule off.
    block_overdue_days INT CHECK (block_overdue_days IS NULL OR block_overdue_days >= 0),
    -- Confirming an order that brings the exposure above this share of the limit warns.
    warn_ratio NUMERIC(4, 2) NOT NULL DEFAULT 0.90 CHECK (warn_ratio > 0 AND warn_ratio <= 1),
    company_name TEXT,
    company_address TEXT,
    company_phone TEXT,
    signatory TEXT,
    updated_by TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS finance.dunning_levels (
    tenant_id TEXT NOT NULL,
    level INT NOT NULL CHECK (level BETWEEN 1 AND 9),
    days_after_due INT NOT NULL CHECK (days_after_due >= 0),
    name_fr TEXT NOT NULL,
    name_en TEXT NOT NULL,
    letter_fr TEXT NOT NULL,
    letter_en TEXT NOT NULL,
    blocks_orders BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (tenant_id, level)
);

CREATE TABLE IF NOT EXISTS finance.dunning_actions (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    partner_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('letter', 'call', 'email', 'promise', 'note')),
    level INT,
    note TEXT,
    invoice_ids JSONB NOT NULL DEFAULT '[]',
    amount_due NUMERIC(18, 2),
    promise_date DATE,
    promise_amount NUMERIC(18, 2),
    promise_status TEXT CHECK (promise_status IS NULL OR promise_status IN ('open', 'kept', 'broken')),
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CHECK ((kind = 'promise') = (promise_date IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS dunning_actions_partner_idx ON finance.dunning_actions (tenant_id, partner_id, created_at);

-- Who was told that a customer reached a level, once per level and per run of lateness.
CREATE TABLE IF NOT EXISTS finance.dunning_notices (
    tenant_id TEXT NOT NULL,
    partner_id TEXT NOT NULL,
    level INT NOT NULL,
    since DATE NOT NULL,
    notified_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (tenant_id, partner_id, level, since)
);
