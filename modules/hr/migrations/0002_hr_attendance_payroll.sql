CREATE TABLE IF NOT EXISTS hr.attendance_records (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    employee_id TEXT NOT NULL REFERENCES hr.employees (id),
    attendance_date DATE NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('present', 'absent', 'late', 'remote', 'half_day', 'leave')),
    hours_worked NUMERIC NOT NULL DEFAULT 0,
    note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, employee_id, attendance_date)
);

CREATE TABLE IF NOT EXISTS hr.payroll_runs (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    period_month DATE NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'calculated', 'approved', 'paid')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, period_month)
);

CREATE TABLE IF NOT EXISTS hr.payroll_items (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    payroll_run_id TEXT NOT NULL REFERENCES hr.payroll_runs (id),
    employee_id TEXT NOT NULL REFERENCES hr.employees (id),
    base_salary NUMERIC NOT NULL DEFAULT 0,
    bonuses NUMERIC NOT NULL DEFAULT 0,
    deductions NUMERIC NOT NULL DEFAULT 0,
    taxes NUMERIC NOT NULL DEFAULT 0,
    net_salary NUMERIC NOT NULL DEFAULT 0,
    currency TEXT NOT NULL DEFAULT 'USD',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (payroll_run_id, employee_id)
);

CREATE INDEX IF NOT EXISTS hr_attendance_date_idx ON hr.attendance_records (tenant_id, attendance_date);
CREATE INDEX IF NOT EXISTS hr_payroll_period_idx ON hr.payroll_runs (tenant_id, period_month);
