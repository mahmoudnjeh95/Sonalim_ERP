-- A bounced cheque takes its amount back off the invoices it paid; this records how much of each
-- allocation has already been taken back so a second bounce never over-reverses.
ALTER TABLE treasury.document_allocations ADD COLUMN IF NOT EXISTS reversed NUMERIC(18, 2) NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS treasury.deposit_slips (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    number TEXT NOT NULL,
    account_id TEXT NOT NULL REFERENCES treasury.accounts (id),
    slip_date DATE NOT NULL,
    note TEXT,
    created_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS deposit_slips_number_uq ON treasury.deposit_slips (tenant_id, number);

CREATE TABLE IF NOT EXISTS treasury.deposit_slip_items (
    slip_id TEXT NOT NULL REFERENCES treasury.deposit_slips (id),
    instrument_id TEXT NOT NULL REFERENCES treasury.instruments (id),
    outcome TEXT NOT NULL CHECK (outcome IN ('collected', 'unpaid')),
    PRIMARY KEY (slip_id, instrument_id)
);

