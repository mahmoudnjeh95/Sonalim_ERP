CREATE TABLE IF NOT EXISTS payroll.bank_file_templates (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    bank_name TEXT NOT NULL,           -- upper-case, matched against the payout batch's group_key
    delimiter TEXT NOT NULL DEFAULT ';',
    include_header BOOLEAN NOT NULL DEFAULT TRUE,
    columns JSONB NOT NULL,            -- [{"header": "...", "field": "account_no" | "amount" | ...}]
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, bank_name)
);

CREATE TABLE IF NOT EXISTS payroll.payout_batches (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    run_id TEXT NOT NULL REFERENCES payroll.runs (id),
    method TEXT NOT NULL CHECK (method IN ('bank', 'mobile_money', 'cash')),
    group_key TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'generated' CHECK (status IN ('generated', 'confirmed')),
    file_name TEXT NOT NULL,
    total NUMERIC(18, 0) NOT NULL,
    line_count INTEGER NOT NULL,
    generated_by TEXT NOT NULL,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    confirmed_by TEXT,
    confirmed_at TIMESTAMPTZ,
    UNIQUE (run_id, method, group_key)
);

CREATE TABLE IF NOT EXISTS payroll.payout_lines (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    batch_id TEXT NOT NULL REFERENCES payroll.payout_batches (id) ON DELETE CASCADE,
    payslip_id TEXT NOT NULL REFERENCES payroll.payslips (id),
    employee_id TEXT NOT NULL,
    employee_no TEXT NOT NULL,
    full_name TEXT NOT NULL,
    details JSONB NOT NULL,
    amount NUMERIC(18, 0) NOT NULL CHECK (amount > 0)
);
CREATE INDEX IF NOT EXISTS payroll_payout_lines_batch_idx ON payroll.payout_lines (batch_id);
