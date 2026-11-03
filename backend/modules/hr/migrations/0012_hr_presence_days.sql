-- One row per employee and date. New code writes here; hr.attendance_records stays as it is.
-- clock_import_id gets its foreign key in 0013, once hr.clock_imports exists.
CREATE TABLE IF NOT EXISTS hr.presence_days (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    employee_id TEXT NOT NULL REFERENCES hr.employees (id),
    work_date DATE NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('present', 'absent', 'late', 'leave', 'holiday', 'rest', 'sick', 'mission', 'suspended')),
    schedule_id TEXT REFERENCES hr.work_schedules (id),
    scheduled_minutes INTEGER NOT NULL DEFAULT 0 CHECK (scheduled_minutes >= 0),
    worked_minutes INTEGER NOT NULL DEFAULT 0 CHECK (worked_minutes >= 0),
    late_minutes INTEGER NOT NULL DEFAULT 0 CHECK (late_minutes >= 0),
    ot_minutes_day INTEGER NOT NULL DEFAULT 0 CHECK (ot_minutes_day >= 0),
    ot_minutes_night INTEGER NOT NULL DEFAULT 0 CHECK (ot_minutes_night >= 0),
    ot_minutes_rest_holiday INTEGER NOT NULL DEFAULT 0 CHECK (ot_minutes_rest_holiday >= 0),
    night_minutes INTEGER NOT NULL DEFAULT 0 CHECK (night_minutes >= 0),
    source TEXT NOT NULL CHECK (source IN ('manual', 'clock', 'leave', 'holiday')),
    justified BOOLEAN NOT NULL DEFAULT FALSE,
    note TEXT,
    leave_request_id TEXT REFERENCES hr.leave_requests (id),
    clock_import_id TEXT,
    locked BOOLEAN NOT NULL DEFAULT FALSE,
    updated_by TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, employee_id, work_date)
);

CREATE INDEX IF NOT EXISTS hr_presence_days_date_idx ON hr.presence_days (tenant_id, work_date);
CREATE INDEX IF NOT EXISTS hr_presence_days_leave_idx ON hr.presence_days (leave_request_id) WHERE leave_request_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS hr.presence_months (
    tenant_id TEXT NOT NULL,
    period DATE NOT NULL CHECK (EXTRACT(DAY FROM period) = 1),
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed')),
    closed_by TEXT,
    closed_at TIMESTAMPTZ,
    reopened_by TEXT,
    reopened_at TIMESTAMPTZ,
    PRIMARY KEY (tenant_id, period)
);

-- Written by the consumers of payroll.run.approved / payroll.run.reversed (Task 9): while a
-- row exists for a period, that month's presence cannot be reopened.
CREATE TABLE IF NOT EXISTS hr.presence_month_payroll_locks (
    tenant_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    period DATE NOT NULL,
    locked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (tenant_id, run_id)
);
