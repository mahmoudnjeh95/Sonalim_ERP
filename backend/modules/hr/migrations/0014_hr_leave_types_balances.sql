-- Leave types carry statutory values (accrual per month, carry-over cap): seed data flagged
-- confirmed = FALSE until HR checks them, never constants in code.
CREATE TABLE IF NOT EXISTS hr.leave_types (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    code TEXT NOT NULL,
    name_en TEXT NOT NULL,
    name_fr TEXT NOT NULL,
    paid BOOLEAN NOT NULL,
    accrual_days_per_month NUMERIC(5, 2) NOT NULL CHECK (accrual_days_per_month >= 0),
    max_carry_over NUMERIC(6, 2) CHECK (max_carry_over IS NULL OR max_carry_over >= 0),
    counts_days TEXT NOT NULL CHECK (counts_days IN ('calendar', 'working')),
    requires_document BOOLEAN NOT NULL DEFAULT FALSE,
    presence_status TEXT NOT NULL CHECK (presence_status IN ('leave', 'sick')),
    confirmed BOOLEAN NOT NULL DEFAULT FALSE,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, code)
);

CREATE TABLE IF NOT EXISTS hr.leave_balances (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    employee_id TEXT NOT NULL REFERENCES hr.employees (id),
    leave_type_id TEXT NOT NULL REFERENCES hr.leave_types (id),
    year SMALLINT NOT NULL,
    accrued NUMERIC(6, 2) NOT NULL DEFAULT 0,
    taken NUMERIC(6, 2) NOT NULL DEFAULT 0,
    adjusted NUMERIC(6, 2) NOT NULL DEFAULT 0,
    UNIQUE (tenant_id, employee_id, leave_type_id, year)
);

-- One posting per employee, type and closed month; leave_balances.accrued is their yearly sum,
-- so closing a month twice (after a reopen) posts the same value again, not twice.
CREATE TABLE IF NOT EXISTS hr.leave_accruals (
    tenant_id TEXT NOT NULL,
    employee_id TEXT NOT NULL REFERENCES hr.employees (id),
    leave_type_id TEXT NOT NULL REFERENCES hr.leave_types (id),
    period DATE NOT NULL CHECK (EXTRACT(DAY FROM period) = 1),
    days NUMERIC(6, 2) NOT NULL,
    posted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (tenant_id, employee_id, leave_type_id, period)
);

-- Old rows keep their free-text leave_type and get no leave_type_id: they are listed as
-- "old request" and must be given a type before being decided through the new flow.
ALTER TABLE hr.leave_requests ADD COLUMN IF NOT EXISTS leave_type_id TEXT REFERENCES hr.leave_types (id);
ALTER TABLE hr.leave_requests ADD COLUMN IF NOT EXISTS days NUMERIC(5, 1);
ALTER TABLE hr.leave_requests ADD COLUMN IF NOT EXISTS half_day BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE hr.leave_requests ADD COLUMN IF NOT EXISTS document_ref TEXT;
ALTER TABLE hr.leave_requests ADD COLUMN IF NOT EXISTS balance_year SMALLINT;
ALTER TABLE hr.leave_requests ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMPTZ;
ALTER TABLE hr.leave_requests ADD COLUMN IF NOT EXISTS review_note TEXT;
