-- The plant's organisation beyond departments: the positions people hold and the
-- collective-agreement grid (categorie / echelon) their pay is anchored to.
CREATE TABLE IF NOT EXISTS hr.positions (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    code TEXT NOT NULL,
    title TEXT NOT NULL,
    department_id TEXT REFERENCES hr.departments (id),
    -- How many people the position is budgeted for; NULL until HR records one.
    headcount_budget INTEGER CONSTRAINT hr_positions_budget_check CHECK (headcount_budget IS NULL OR headcount_budget >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT hr_positions_code_key UNIQUE (tenant_id, code)
);

-- One row per grade and per revision of the grid: a new minimum from a later date is a new
-- row with the same code, so a contract signed under the old grid keeps pointing at its row.
CREATE TABLE IF NOT EXISTS hr.grades (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    code TEXT NOT NULL,
    category TEXT NOT NULL,
    echelon TEXT NOT NULL,
    -- Monthly minimum for the grade, in whole F CFA.
    base_salary NUMERIC(18,0) NOT NULL CONSTRAINT hr_grades_base_salary_check CHECK (base_salary >= 0),
    valid_from DATE NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT hr_grades_code_valid_from_key UNIQUE (tenant_id, code, valid_from)
);

-- Where each person sits; the rest of the employee file comes in 0004.
ALTER TABLE hr.employees
    ADD COLUMN IF NOT EXISTS position_id TEXT REFERENCES hr.positions (id),
    ADD COLUMN IF NOT EXISTS grade_id TEXT REFERENCES hr.grades (id);

CREATE INDEX IF NOT EXISTS hr_positions_department_idx ON hr.positions (tenant_id, department_id);
CREATE INDEX IF NOT EXISTS hr_employees_position_idx ON hr.employees (tenant_id, position_id);
