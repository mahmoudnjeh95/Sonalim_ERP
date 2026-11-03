-- Salary advances and loans. Deduction is recorded by the payslip that took it (ON DELETE SET NULL
-- releases it when that payslip is recalculated away).
CREATE TABLE IF NOT EXISTS payroll.advances (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    employee_id TEXT NOT NULL,
    employee_no TEXT NOT NULL,
    full_name TEXT NOT NULL,
    amount NUMERIC(18, 0) NOT NULL CHECK (amount > 0),
    requested_on DATE NOT NULL,
    deduct_period DATE NOT NULL CHECK (EXTRACT(DAY FROM deduct_period) = 1),
    status TEXT NOT NULL DEFAULT 'requested' CHECK (status IN ('requested', 'approved', 'cancelled')),
    approved_by TEXT,
    approved_at TIMESTAMPTZ,
    note TEXT,
    deducted_payslip_id TEXT REFERENCES payroll.payslips (id) ON DELETE SET NULL,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS payroll_advances_employee_idx ON payroll.advances (tenant_id, employee_id);

CREATE TABLE IF NOT EXISTS payroll.loans (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    employee_id TEXT NOT NULL,
    employee_no TEXT NOT NULL,
    full_name TEXT NOT NULL,
    principal NUMERIC(18, 0) NOT NULL CHECK (principal > 0),
    instalment_count INTEGER NOT NULL CHECK (instalment_count >= 1),
    first_period DATE NOT NULL CHECK (EXTRACT(DAY FROM first_period) = 1),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'cancelled')),
    note TEXT,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS payroll.loan_instalments (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    loan_id TEXT NOT NULL REFERENCES payroll.loans (id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    period DATE NOT NULL,
    amount NUMERIC(18, 0) NOT NULL CHECK (amount > 0),
    payslip_id TEXT REFERENCES payroll.payslips (id) ON DELETE SET NULL,
    UNIQUE (loan_id, seq)
);
