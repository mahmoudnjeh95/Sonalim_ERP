CREATE SCHEMA IF NOT EXISTS hr;

CREATE TABLE IF NOT EXISTS hr.departments (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    name TEXT NOT NULL,
    code TEXT NOT NULL,
    manager_employee_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, code)
);

CREATE TABLE IF NOT EXISTS hr.employees (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    employee_no TEXT NOT NULL,
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    email TEXT,
    phone TEXT,
    department_id TEXT REFERENCES hr.departments (id),
    job_title TEXT,
    hire_date DATE NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'on_leave', 'inactive')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, employee_no)
);

ALTER TABLE hr.departments DROP CONSTRAINT IF EXISTS departments_manager_employee_id_fkey;
ALTER TABLE hr.departments ADD CONSTRAINT departments_manager_employee_id_fkey FOREIGN KEY (manager_employee_id) REFERENCES hr.employees (id);

CREATE TABLE IF NOT EXISTS hr.contracts (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    employee_id TEXT NOT NULL REFERENCES hr.employees (id),
    contract_type TEXT NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE,
    salary NUMERIC NOT NULL DEFAULT 0,
    currency TEXT NOT NULL DEFAULT 'USD',
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('draft', 'active', 'expired', 'terminated')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS hr.leave_requests (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    employee_id TEXT NOT NULL REFERENCES hr.employees (id),
    leave_type TEXT NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    reason TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected', 'cancelled')),
    reviewed_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS hr_employees_department_idx ON hr.employees (tenant_id, department_id);
CREATE INDEX IF NOT EXISTS hr_contracts_employee_idx ON hr.contracts (tenant_id, employee_id);
CREATE INDEX IF NOT EXISTS hr_leave_employee_idx ON hr.leave_requests (tenant_id, employee_id);
