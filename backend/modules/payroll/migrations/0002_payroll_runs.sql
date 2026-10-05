-- Payroll runs and payslips. employee_id is hr's id kept as opaque text (no cross-module FK);
-- employee_no / full_name are copies taken at calculation time so a payslip reads on its own.
CREATE TABLE IF NOT EXISTS payroll.runs (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    period DATE NOT NULL CHECK (EXTRACT(DAY FROM period) = 1),
    run_type TEXT NOT NULL CHECK (run_type IN ('regular', 'off_cycle')),
    label TEXT,
    employee_ids TEXT[],
    rule_set_id TEXT REFERENCES payroll.rule_sets (id),
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'calculated', 'approved', 'paid', 'reversed')),
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    calculated_by TEXT,
    calculated_at TIMESTAMPTZ,
    approved_by TEXT,
    approved_at TIMESTAMPTZ,
    paid_by TEXT,
    paid_at TIMESTAMPTZ,
    reversed_by TEXT,
    reversed_at TIMESTAMPTZ,
    reversal_reason TEXT,
    CHECK (run_type = 'off_cycle' OR employee_ids IS NULL)
);
-- One regular run per month; a reversed one frees the month.
CREATE UNIQUE INDEX IF NOT EXISTS payroll_runs_one_regular_per_period
    ON payroll.runs (tenant_id, period) WHERE run_type = 'regular' AND status <> 'reversed';
CREATE INDEX IF NOT EXISTS payroll_runs_period_idx ON payroll.runs (tenant_id, period DESC);

CREATE TABLE IF NOT EXISTS payroll.run_inputs (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    run_id TEXT NOT NULL REFERENCES payroll.runs (id) ON DELETE CASCADE,
    employee_id TEXT NOT NULL,
    employee_no TEXT NOT NULL,
    full_name TEXT NOT NULL,
    component_code TEXT NOT NULL,
    qty NUMERIC(12, 2) CHECK (qty >= 0),
    amount NUMERIC(18, 0) CHECK (amount >= 0),
    note TEXT,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (qty IS NOT NULL OR amount IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS payroll_run_inputs_run_idx ON payroll.run_inputs (run_id, employee_id);

CREATE TABLE IF NOT EXISTS payroll.final_settlements (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    run_id TEXT NOT NULL REFERENCES payroll.runs (id) ON DELETE CASCADE,
    employee_id TEXT NOT NULL,
    employee_no TEXT NOT NULL,
    full_name TEXT NOT NULL,
    unused_leave_days NUMERIC(6, 2) NOT NULL DEFAULT 0 CHECK (unused_leave_days >= 0),
    notice_months NUMERIC(5, 2) NOT NULL DEFAULT 0 CHECK (notice_months >= 0),
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (run_id, employee_id)
);

CREATE TABLE IF NOT EXISTS payroll.payslips (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    run_id TEXT NOT NULL REFERENCES payroll.runs (id) ON DELETE CASCADE,
    employee_id TEXT NOT NULL,
    employee_no TEXT NOT NULL,
    full_name TEXT NOT NULL,
    department_id TEXT,
    rule_set_id TEXT NOT NULL REFERENCES payroll.rule_sets (id),
    rule_set_status TEXT NOT NULL CHECK (rule_set_status IN ('draft', 'confirmed')),
    snapshot JSONB NOT NULL,
    gross NUMERIC(18, 0) NOT NULL,
    contributable NUMERIC(18, 0) NOT NULL,
    taxable NUMERIC(18, 0) NOT NULL,
    employee_contrib NUMERIC(18, 0) NOT NULL,
    employer_contrib NUMERIC(18, 0) NOT NULL,
    employer_charges NUMERIC(18, 0) NOT NULL,
    its NUMERIC(18, 0) NOT NULL,
    deductions NUMERIC(18, 0) NOT NULL,
    net NUMERIC(18, 0) NOT NULL CHECK (net >= 0),
    employer_cost NUMERIC(18, 0) NOT NULL,
    warnings JSONB NOT NULL DEFAULT '[]'::jsonb,
    note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (run_id, employee_id)
);
CREATE INDEX IF NOT EXISTS payroll_payslips_employee_idx ON payroll.payslips (tenant_id, employee_id);

CREATE TABLE IF NOT EXISTS payroll.payslip_lines (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    payslip_id TEXT NOT NULL REFERENCES payroll.payslips (id) ON DELETE CASCADE,
    line_no INTEGER NOT NULL,
    section TEXT NOT NULL CHECK (section IN ('earning', 'employee_contribution', 'relief', 'tax', 'deduction',
                                             'employer_contribution', 'employer_charge')),
    code TEXT NOT NULL,
    name_en TEXT NOT NULL,
    name_fr TEXT NOT NULL,
    base NUMERIC(18, 0),
    qty NUMERIC(12, 2),
    rate NUMERIC(9, 4),
    amount NUMERIC(18, 0) NOT NULL,
    taxable BOOLEAN NOT NULL DEFAULT FALSE,
    contributable BOOLEAN NOT NULL DEFAULT FALSE,
    declaration_code TEXT,
    source_kind TEXT,
    source_id TEXT,
    UNIQUE (payslip_id, line_no)
);

-- A deduction the net could not cover, owed on a later payslip. Deleted with the payslip that
-- produced it (recalculation); released when the payslip that took it is deleted.
CREATE TABLE IF NOT EXISTS payroll.carry_forwards (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    employee_id TEXT NOT NULL,
    component_code TEXT NOT NULL,
    amount NUMERIC(18, 0) NOT NULL CHECK (amount > 0),
    source_kind TEXT NOT NULL CHECK (source_kind IN ('carry_forward', 'loan_instalment', 'advance', 'input')),
    source_id TEXT,
    source_payslip_id TEXT NOT NULL REFERENCES payroll.payslips (id) ON DELETE CASCADE,
    consumed_by_payslip_id TEXT REFERENCES payroll.payslips (id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS payroll_carry_forwards_open_idx ON payroll.carry_forwards (tenant_id, employee_id) WHERE consumed_by_payslip_id IS NULL;
