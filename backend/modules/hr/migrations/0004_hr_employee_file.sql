-- The full employee file: identity, social-security numbers, clock badge, site, the core
-- user the person signs in as (self-service), and how the employment ended.
ALTER TABLE hr.employees
    ADD COLUMN IF NOT EXISTS user_id TEXT REFERENCES core.users (id),
    ADD COLUMN IF NOT EXISTS gender TEXT,
    ADD COLUMN IF NOT EXISTS birth_date DATE,
    ADD COLUMN IF NOT EXISTS birth_place TEXT,
    ADD COLUMN IF NOT EXISTS nationality TEXT,
    ADD COLUMN IF NOT EXISTS national_id TEXT,
    ADD COLUMN IF NOT EXISTS inps_no TEXT,
    ADD COLUMN IF NOT EXISTS amo_no TEXT,
    ADD COLUMN IF NOT EXISTS marital_status TEXT,
    ADD COLUMN IF NOT EXISTS address TEXT,
    ADD COLUMN IF NOT EXISTS emergency_contact TEXT,
    ADD COLUMN IF NOT EXISTS badge_no TEXT,
    ADD COLUMN IF NOT EXISTS site TEXT,
    ADD COLUMN IF NOT EXISTS termination_date DATE,
    ADD COLUMN IF NOT EXISTS termination_reason TEXT;

ALTER TABLE hr.employees DROP CONSTRAINT IF EXISTS employees_status_check;
ALTER TABLE hr.employees ADD CONSTRAINT employees_status_check
    CHECK (status IN ('active', 'on_leave', 'inactive', 'terminated'));
ALTER TABLE hr.employees ADD CONSTRAINT hr_employees_gender_check
    CHECK (gender IS NULL OR gender IN ('male', 'female'));
ALTER TABLE hr.employees ADD CONSTRAINT hr_employees_marital_status_check
    CHECK (marital_status IS NULL OR marital_status IN ('single', 'married', 'divorced', 'widowed'));
ALTER TABLE hr.employees ADD CONSTRAINT hr_employees_termination_reason_check
    CHECK (termination_reason IS NULL OR termination_reason IN
           ('term_reached', 'resignation', 'dismissal', 'trial_termination', 'mutual_agreement', 'retirement', 'death', 'other'));
-- That a terminated employee has an exit date and reason (and only they do) is a domain rule
-- (modules/hr/domain/employee.py); later phases' tests insert exit dates directly.

-- A badge identifies one person at the clock; a sign-in belongs to one employee file.
CREATE UNIQUE INDEX IF NOT EXISTS hr_employees_badge_key ON hr.employees (tenant_id, badge_no) WHERE badge_no IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS hr_employees_user_key ON hr.employees (tenant_id, user_id) WHERE user_id IS NOT NULL;
