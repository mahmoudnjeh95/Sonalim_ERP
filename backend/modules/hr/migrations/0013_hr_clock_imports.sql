-- How to read each clock model's CSV export.
CREATE TABLE IF NOT EXISTS hr.clock_profiles (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    delimiter TEXT NOT NULL CHECK (char_length(delimiter) = 1),
    has_header BOOLEAN NOT NULL,
    badge_column TEXT NOT NULL,
    timestamp_column TEXT NOT NULL,
    time_column TEXT,
    timestamp_format TEXT NOT NULL,
    direction_column TEXT,
    in_values TEXT[] NOT NULL DEFAULT '{}',
    out_values TEXT[] NOT NULL DEFAULT '{}',
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, code)
);

-- An uploaded file: staged for review, then committed or discarded. Rows stay for history.
CREATE TABLE IF NOT EXISTS hr.clock_imports (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    profile_id TEXT NOT NULL REFERENCES hr.clock_profiles (id),
    file_name TEXT NOT NULL,
    date_from DATE NOT NULL,
    date_to DATE NOT NULL,
    status TEXT NOT NULL DEFAULT 'staged' CHECK (status IN ('staged', 'committed', 'discarded')),
    total_rows INTEGER NOT NULL DEFAULT 0,
    valid_rows INTEGER NOT NULL DEFAULT 0,
    error_rows INTEGER NOT NULL DEFAULT 0,
    uploaded_by TEXT NOT NULL,
    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    decided_by TEXT,
    decided_at TIMESTAMPTZ,
    result JSONB,
    CHECK (date_to >= date_from)
);

CREATE TABLE IF NOT EXISTS hr.clock_import_rows (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    import_id TEXT NOT NULL REFERENCES hr.clock_imports (id) ON DELETE CASCADE,
    line_no INTEGER NOT NULL,
    raw TEXT NOT NULL,
    badge_no TEXT,
    employee_id TEXT REFERENCES hr.employees (id),
    punched_at TIMESTAMP,
    direction TEXT NOT NULL DEFAULT 'unknown' CHECK (direction IN ('in', 'out', 'unknown')),
    error_code TEXT,
    UNIQUE (import_id, line_no)
);

-- The device's wall-clock time (no time zone): what the clock printed is what counts.
CREATE TABLE IF NOT EXISTS hr.clock_punches (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    employee_id TEXT NOT NULL REFERENCES hr.employees (id),
    badge_no TEXT NOT NULL,
    punched_at TIMESTAMP NOT NULL,
    direction TEXT NOT NULL CHECK (direction IN ('in', 'out', 'unknown')),
    import_id TEXT NOT NULL REFERENCES hr.clock_imports (id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, badge_no, punched_at)
);

CREATE INDEX IF NOT EXISTS hr_clock_punches_employee_idx ON hr.clock_punches (tenant_id, employee_id, punched_at);

ALTER TABLE hr.presence_days DROP CONSTRAINT IF EXISTS presence_days_clock_import_id_fkey;
ALTER TABLE hr.presence_days ADD CONSTRAINT presence_days_clock_import_id_fkey
    FOREIGN KEY (clock_import_id) REFERENCES hr.clock_imports (id);
