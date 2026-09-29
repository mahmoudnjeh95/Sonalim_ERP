-- Payroll rule tables. Every statutory number (rate, ceiling, bracket, relief, scale) lives in
-- these rows, never in code. Rates are percent as written by the accountant (3.6 = 3.6 %).
CREATE SCHEMA IF NOT EXISTS payroll;

-- One row per tenant: which country's rule sets apply, and the employer identifiers printed on
-- payslips and declarations. The company name itself is core.companies.name.
CREATE TABLE IF NOT EXISTS payroll.settings (
    tenant_id TEXT PRIMARY KEY,
    country TEXT NOT NULL CHECK (country ~ '^[A-Z]{2}$'),
    company_address TEXT,
    employer_inps_no TEXT,
    employer_tax_id TEXT,
    updated_by TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS payroll.rule_sets (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    country TEXT NOT NULL CHECK (country ~ '^[A-Z]{2}$'),
    name TEXT NOT NULL,
    valid_from DATE NOT NULL CHECK (EXTRACT(DAY FROM valid_from) = 1),
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'confirmed')),
    confirmed_by TEXT,
    confirmed_at TIMESTAMPTZ,
    round_to INTEGER NOT NULL DEFAULT 1 CHECK (round_to >= 1),
    round_mode TEXT NOT NULL DEFAULT 'half_up' CHECK (round_mode IN ('half_up', 'down', 'up')),
    tax_round_to INTEGER NOT NULL DEFAULT 1 CHECK (tax_round_to >= 1),
    tax_round_mode TEXT NOT NULL DEFAULT 'half_up' CHECK (tax_round_mode IN ('half_up', 'down', 'up')),
    working_days_per_month NUMERIC(5, 2) NOT NULL CHECK (working_days_per_month > 0),
    working_hours_per_month NUMERIC(6, 2) NOT NULL CHECK (working_hours_per_month > 0),
    -- months of gross averaged into the final-settlement reference salary: a rule value like the
    -- others (the default is only a starting point; the accountant confirms it with the set)
    settlement_reference_months INTEGER NOT NULL DEFAULT 12 CHECK (settlement_reference_months >= 1),
    notes TEXT,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, country, valid_from),
    CHECK ((status = 'confirmed') = (confirmed_at IS NOT NULL AND confirmed_by IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS payroll_rule_sets_lookup_idx ON payroll.rule_sets (tenant_id, country, valid_from DESC);

CREATE TABLE IF NOT EXISTS payroll.components (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    rule_set_id TEXT NOT NULL REFERENCES payroll.rule_sets (id) ON DELETE CASCADE,
    code TEXT NOT NULL,
    name_en TEXT NOT NULL,
    name_fr TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('earning', 'deduction', 'employer_charge')),
    taxable BOOLEAN NOT NULL DEFAULT FALSE,
    contributable BOOLEAN NOT NULL DEFAULT FALSE,
    formula_type TEXT NOT NULL CHECK (formula_type IN ('fixed', 'rate_x_base', 'qty_x_rate', 'per_day')),
    base_ref TEXT CHECK (base_ref IN ('base_salary', 'earned_base', 'gross', 'contributable')),
    default_amount NUMERIC(18, 0),
    default_rate NUMERIC(9, 4),
    display_order INTEGER NOT NULL DEFAULT 100,
    payslip_section TEXT NOT NULL DEFAULT 'earnings' CHECK (payslip_section IN ('earnings', 'deductions', 'employer')),
    declaration_code TEXT,
    UNIQUE (rule_set_id, code)
);

CREATE TABLE IF NOT EXISTS payroll.contributions (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    rule_set_id TEXT NOT NULL REFERENCES payroll.rule_sets (id) ON DELETE CASCADE,
    code TEXT NOT NULL,
    name_en TEXT NOT NULL,
    name_fr TEXT NOT NULL,
    base TEXT NOT NULL CHECK (base IN ('gross', 'contributable')),
    employee_rate NUMERIC(7, 4) NOT NULL DEFAULT 0 CHECK (employee_rate BETWEEN 0 AND 100),
    employer_rate NUMERIC(7, 4) NOT NULL DEFAULT 0 CHECK (employer_rate BETWEEN 0 AND 100),
    ceiling_monthly NUMERIC(18, 0) CHECK (ceiling_monthly > 0),
    deductible_from_taxable BOOLEAN NOT NULL DEFAULT TRUE,
    declaration_code TEXT NOT NULL,
    liability_account_code TEXT,
    display_order INTEGER NOT NULL DEFAULT 100,
    UNIQUE (rule_set_id, code)
);

CREATE TABLE IF NOT EXISTS payroll.tax_brackets (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    rule_set_id TEXT NOT NULL REFERENCES payroll.rule_sets (id) ON DELETE CASCADE,
    tax_code TEXT NOT NULL,
    lower_bound NUMERIC(18, 0) NOT NULL CHECK (lower_bound >= 0),
    upper_bound NUMERIC(18, 0) CHECK (upper_bound > lower_bound),
    rate NUMERIC(7, 4) NOT NULL CHECK (rate BETWEEN 0 AND 100),
    annualised BOOLEAN NOT NULL DEFAULT FALSE,
    UNIQUE (rule_set_id, tax_code, lower_bound)
);

-- parameters (JSON, decimals as strings):
--   family:                {"mode": "percent_of_tax"|"amount", "steps": [{"dependants": 1, "value": "10"}], "cap_monthly": null|"..."}
--   professional_expenses: {"percent": "10", "cap_monthly": null|"..."}
CREATE TABLE IF NOT EXISTS payroll.tax_reliefs (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    rule_set_id TEXT NOT NULL REFERENCES payroll.rule_sets (id) ON DELETE CASCADE,
    tax_code TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('family', 'professional_expenses')),
    parameters JSONB NOT NULL,
    UNIQUE (rule_set_id, tax_code, kind)
);

CREATE TABLE IF NOT EXISTS payroll.seniority_scale (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    rule_set_id TEXT NOT NULL REFERENCES payroll.rule_sets (id) ON DELETE CASCADE,
    years_from INTEGER NOT NULL CHECK (years_from >= 0),
    percent NUMERIC(7, 4) NOT NULL CHECK (percent BETWEEN 0 AND 100),
    UNIQUE (rule_set_id, years_from)
);

CREATE TABLE IF NOT EXISTS payroll.overtime_rates (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    rule_set_id TEXT NOT NULL REFERENCES payroll.rule_sets (id) ON DELETE CASCADE,
    band_code TEXT NOT NULL CHECK (band_code IN ('day', 'night', 'rest_holiday')),
    multiplier NUMERIC(6, 4) NOT NULL CHECK (multiplier >= 1),
    UNIQUE (rule_set_id, band_code)
);

-- Severance is tiered: each year of service inside [years_from, next years_from) earns
-- percent_per_year % of the reference monthly salary.
CREATE TABLE IF NOT EXISTS payroll.severance_scale (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    rule_set_id TEXT NOT NULL REFERENCES payroll.rule_sets (id) ON DELETE CASCADE,
    years_from INTEGER NOT NULL CHECK (years_from >= 0),
    percent_per_year NUMERIC(7, 4) NOT NULL CHECK (percent_per_year BETWEEN 0 AND 100),
    UNIQUE (rule_set_id, years_from)
);
