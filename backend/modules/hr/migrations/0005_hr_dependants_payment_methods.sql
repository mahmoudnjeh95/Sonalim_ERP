-- The people an employee supports (ITS family relief counts the tax dependants valid on the
-- last day of the pay period) and how their net pay reaches them.
CREATE TABLE IF NOT EXISTS hr.dependants (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    employee_id TEXT NOT NULL REFERENCES hr.employees (id),
    kind TEXT NOT NULL CONSTRAINT hr_dependants_kind_check CHECK (kind IN ('spouse', 'child')),
    name TEXT NOT NULL,
    birth_date DATE,
    dependent_for_tax BOOLEAN NOT NULL DEFAULT FALSE,
    valid_from DATE NOT NULL,
    valid_to DATE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT hr_dependants_validity_check CHECK (valid_to IS NULL OR valid_to >= valid_from)
);
CREATE INDEX IF NOT EXISTS hr_dependants_employee_idx ON hr.dependants (tenant_id, employee_id);

-- Payment methods come in arrangements: the arrangement in force on a date is the one with the
-- latest valid_from on or before it; its shares add up to 100 % and one method is primary.
CREATE TABLE IF NOT EXISTS hr.payment_methods (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    employee_id TEXT NOT NULL REFERENCES hr.employees (id),
    method TEXT NOT NULL CONSTRAINT hr_payment_methods_method_check CHECK (method IN ('bank', 'mobile_money', 'cash')),
    bank_name TEXT,
    account_no TEXT,
    mobile_operator TEXT CONSTRAINT hr_payment_methods_operator_check
        CHECK (mobile_operator IS NULL OR mobile_operator IN ('orange_money', 'moov_money')),
    mobile_number TEXT,
    share_percent NUMERIC(5,2) NOT NULL CONSTRAINT hr_payment_methods_share_check CHECK (share_percent > 0 AND share_percent <= 100),
    is_primary BOOLEAN NOT NULL DEFAULT FALSE,
    valid_from DATE NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS hr_payment_methods_employee_idx ON hr.payment_methods (tenant_id, employee_id, valid_from);
CREATE UNIQUE INDEX IF NOT EXISTS hr_payment_methods_one_primary
    ON hr.payment_methods (tenant_id, employee_id, valid_from) WHERE is_primary;
