-- Contracts carry the terms payroll pays from: type, trial period, hours, pay and how often it
-- is paid, position and grade, amendments, and why they ended. Money is whole F CFA (XOF).

-- The old screen typed the contract type freely ('permanent' by default). Map it onto the
-- closed list: a known value keeps its meaning, otherwise an end date means fixed-term.
UPDATE hr.contracts SET contract_type = CASE
    WHEN lower(contract_type) IN ('cdi', 'cdd', 'apprentice', 'daily', 'intern') THEN lower(contract_type)
    WHEN end_date IS NULL THEN 'cdi'
    ELSE 'cdd'
END;

ALTER TABLE hr.contracts
    ADD COLUMN IF NOT EXISTS trial_end_date DATE,
    ADD COLUMN IF NOT EXISTS weekly_hours NUMERIC(5,2) NOT NULL DEFAULT 40,
    ADD COLUMN IF NOT EXISTS base_salary NUMERIC(18,0) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS pay_frequency TEXT NOT NULL DEFAULT 'monthly',
    ADD COLUMN IF NOT EXISTS position_id TEXT REFERENCES hr.positions (id),
    ADD COLUMN IF NOT EXISTS grade_id TEXT REFERENCES hr.grades (id),
    ADD COLUMN IF NOT EXISTS amends_contract_id TEXT REFERENCES hr.contracts (id),
    ADD COLUMN IF NOT EXISTS end_reason TEXT;

-- base_salary takes over from salary. salary keeps being written (same value) for the legacy
-- payroll screen until phase 3 retires it; a later migration drops it.
UPDATE hr.contracts SET base_salary = ROUND(salary) WHERE base_salary = 0 AND salary > 0;
ALTER TABLE hr.contracts ALTER COLUMN currency SET DEFAULT 'XOF';

ALTER TABLE hr.contracts ADD CONSTRAINT hr_contracts_type_check
    CHECK (contract_type IN ('cdi', 'cdd', 'apprentice', 'daily', 'intern'));
ALTER TABLE hr.contracts ADD CONSTRAINT hr_contracts_pay_frequency_check
    CHECK (pay_frequency IN ('monthly', 'daily'));
ALTER TABLE hr.contracts ADD CONSTRAINT hr_contracts_amounts_check
    CHECK (base_salary >= 0 AND weekly_hours > 0 AND weekly_hours <= 168);
ALTER TABLE hr.contracts ADD CONSTRAINT hr_contracts_dates_check
    CHECK (end_date IS NULL OR end_date >= start_date);
ALTER TABLE hr.contracts ADD CONSTRAINT hr_contracts_end_reason_check
    CHECK (end_reason IS NULL OR end_reason IN
           ('term_reached', 'resignation', 'dismissal', 'trial_termination', 'mutual_agreement', 'retirement', 'death', 'amended', 'other'));

-- Fixed recurring allowances written on the contract (transport, housing...). The code is the
-- payroll component code (phase 3). The value is either a monthly amount in whole F CFA or a
-- rate in percent (10 = 10 %) of the base payroll applies it to.
CREATE TABLE IF NOT EXISTS hr.contract_components (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    contract_id TEXT NOT NULL REFERENCES hr.contracts (id),
    component_code TEXT NOT NULL,
    amount NUMERIC(18,0),
    rate NUMERIC(9,4),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT hr_contract_components_code_key UNIQUE (contract_id, component_code),
    CONSTRAINT hr_contract_components_value_check
        CHECK ((amount IS NULL) <> (rate IS NULL) AND COALESCE(amount, 0) >= 0 AND COALESCE(rate, 0) >= 0)
);
CREATE INDEX IF NOT EXISTS hr_contract_components_contract_idx ON hr.contract_components (tenant_id, contract_id);
