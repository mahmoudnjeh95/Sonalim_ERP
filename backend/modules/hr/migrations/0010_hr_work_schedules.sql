-- Phase 2 (presence & leave): work schedules, weekly rotations and who works which.
-- A schedule day whose end is not after its start crosses midnight and belongs to the
-- day it starts on. weekday follows Python's date.weekday(): Monday = 0 ... Sunday = 6.
CREATE TABLE IF NOT EXISTS hr.work_schedules (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    is_night BOOLEAN NOT NULL DEFAULT FALSE,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, code)
);

CREATE TABLE IF NOT EXISTS hr.work_schedule_days (
    schedule_id TEXT NOT NULL REFERENCES hr.work_schedules (id) ON DELETE CASCADE,
    tenant_id TEXT NOT NULL,
    weekday SMALLINT NOT NULL CHECK (weekday BETWEEN 0 AND 6),
    start_minute SMALLINT NOT NULL CHECK (start_minute BETWEEN 0 AND 1439),
    end_minute SMALLINT NOT NULL CHECK (end_minute BETWEEN 0 AND 1439),
    break_minutes SMALLINT NOT NULL DEFAULT 0 CHECK (break_minutes >= 0),
    PRIMARY KEY (schedule_id, weekday)
);

-- Week 1 of a rotation starts on anchor_date (a Monday); each step lasts one week.
CREATE TABLE IF NOT EXISTS hr.rotation_patterns (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    anchor_date DATE NOT NULL CHECK (EXTRACT(ISODOW FROM anchor_date) = 1),
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, code)
);

CREATE TABLE IF NOT EXISTS hr.rotation_pattern_steps (
    pattern_id TEXT NOT NULL REFERENCES hr.rotation_patterns (id) ON DELETE CASCADE,
    tenant_id TEXT NOT NULL,
    position SMALLINT NOT NULL CHECK (position >= 0),
    schedule_id TEXT NOT NULL REFERENCES hr.work_schedules (id),
    PRIMARY KEY (pattern_id, position)
);

CREATE TABLE IF NOT EXISTS hr.schedule_assignments (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    employee_id TEXT NOT NULL REFERENCES hr.employees (id),
    schedule_id TEXT REFERENCES hr.work_schedules (id),
    rotation_pattern_id TEXT REFERENCES hr.rotation_patterns (id),
    rotation_offset_weeks SMALLINT NOT NULL DEFAULT 0 CHECK (rotation_offset_weeks >= 0),
    valid_from DATE NOT NULL,
    valid_to DATE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK ((schedule_id IS NULL) <> (rotation_pattern_id IS NULL)),
    CHECK (valid_to IS NULL OR valid_to >= valid_from)
);

CREATE INDEX IF NOT EXISTS hr_schedule_assignments_employee_idx
    ON hr.schedule_assignments (tenant_id, employee_id, valid_from);
