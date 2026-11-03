-- Receipts (direction 'in') and disbursements (direction 'out') share one shape: a partner,
-- one or more payments in different methods, and an optional allocation to invoices. One set of
-- tables keeps the posting, cancellation and event logic in one place; the API exposes them
-- separately as /receipts and /disbursements.
CREATE TABLE IF NOT EXISTS treasury.documents (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    direction TEXT NOT NULL CHECK (direction IN ('in', 'out')),
    number TEXT NOT NULL,
    partner_id TEXT NOT NULL REFERENCES core.partners (id),
    doc_date DATE NOT NULL,
    reason TEXT NOT NULL DEFAULT 'full' CHECK (reason IN ('full', 'advance')),
    with_details BOOLEAN NOT NULL DEFAULT TRUE,
    currency TEXT NOT NULL REFERENCES core.currencies (code),
    total NUMERIC(18, 2) NOT NULL CHECK (total > 0),
    unallocated NUMERIC(18, 2) NOT NULL DEFAULT 0 CHECK (unallocated >= 0),
    status TEXT NOT NULL DEFAULT 'posted' CHECK (status IN ('posted', 'cancelled')),
    note TEXT,
    created_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    cancelled_at TIMESTAMPTZ
);
CREATE UNIQUE INDEX IF NOT EXISTS documents_number_uq ON treasury.documents (tenant_id, number);
CREATE INDEX IF NOT EXISTS documents_partner_idx ON treasury.documents (tenant_id, direction, partner_id);

CREATE TABLE IF NOT EXISTS treasury.document_allocations (
    document_id TEXT NOT NULL REFERENCES treasury.documents (id),
    invoice_id TEXT NOT NULL,
    amount NUMERIC(18, 2) NOT NULL CHECK (amount > 0),
    PRIMARY KEY (document_id, invoice_id)
);

CREATE TABLE IF NOT EXISTS treasury.document_payments (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES treasury.documents (id),
    method TEXT NOT NULL CHECK (method IN ('cash', 'cheque', 'draft', 'transfer', 'mobile_money')),
    amount NUMERIC(18, 2) NOT NULL CHECK (amount > 0),
    account_id TEXT REFERENCES treasury.accounts (id),
    reference TEXT
);
CREATE INDEX IF NOT EXISTS document_payments_document_idx ON treasury.document_payments (document_id);

-- A cheque or draft waits here until a deposit slip collects it (plan B4); only then does it
-- move an account balance.
CREATE TABLE IF NOT EXISTS treasury.instruments (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    direction TEXT NOT NULL CHECK (direction IN ('in', 'out')),
    method TEXT NOT NULL CHECK (method IN ('cheque', 'draft')),
    number TEXT NOT NULL,
    bank_name TEXT NOT NULL,
    due_date DATE NOT NULL,
    amount NUMERIC(18, 2) NOT NULL CHECK (amount > 0),
    currency TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'collected', 'unpaid', 'cancelled')),
    payment_id TEXT NOT NULL REFERENCES treasury.document_payments (id),
    document_id TEXT NOT NULL REFERENCES treasury.documents (id),
    account_id TEXT REFERENCES treasury.accounts (id),
    collected_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS instruments_status_due_idx ON treasury.instruments (tenant_id, status, due_date);

CREATE TABLE IF NOT EXISTS treasury.document_counters (
    tenant_id TEXT NOT NULL,
    direction TEXT NOT NULL,
    year INT NOT NULL,
    last_number INT NOT NULL DEFAULT 0,
    PRIMARY KEY (tenant_id, direction, year)
);
