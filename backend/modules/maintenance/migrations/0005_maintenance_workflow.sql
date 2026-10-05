-- Maintenance workflow: teams, checkpoint maps, jobs with their guided-execution
-- trail, recurring preventive programs, and parts requests.
--
-- user ids (chef_user_id, recorded_by, reviewer_id, created_by, closed_by,
-- requested_by, decided_by), HR employee ids (team_members.employee_id,
-- job_checks/check_entries.*_employee_id), product/uom/location ids
-- (part_request_lines) and actor_id on job_events are opaque TEXT references
-- into other modules or the shared kernel -- no FK, same rule as
-- equipment.work_center_id (see 0001_maintenance_init.sql).

CREATE TABLE IF NOT EXISTS maintenance.teams (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    name TEXT NOT NULL,
    chef_user_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    archived_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS maintenance.team_members (
    team_id TEXT NOT NULL REFERENCES maintenance.teams (id),
    tenant_id TEXT NOT NULL,
    employee_id TEXT NOT NULL,
    PRIMARY KEY (team_id, employee_id)
);

CREATE TABLE IF NOT EXISTS maintenance.equipment_views (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    equipment_id TEXT NOT NULL REFERENCES maintenance.equipment (id),
    label TEXT NOT NULL,
    sort_order INT NOT NULL DEFAULT 0,
    image BYTEA,
    image_mime TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS maintenance_equipment_views_equipment_id_idx
    ON maintenance.equipment_views (equipment_id);

CREATE TABLE IF NOT EXISTS maintenance.checkpoints (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    view_id TEXT NOT NULL REFERENCES maintenance.equipment_views (id) ON DELETE CASCADE,
    x_pct NUMERIC(5, 2) NOT NULL CHECK (x_pct BETWEEN 0 AND 100),
    y_pct NUMERIC(5, 2) NOT NULL CHECK (y_pct BETWEEN 0 AND 100),
    label TEXT NOT NULL,
    action TEXT NOT NULL
        CHECK (action IN ('inspect', 'lubricate', 'tighten', 'clean', 'replace', 'measure', 'other')),
    instructions TEXT,
    measure_unit TEXT,
    requires_photo BOOLEAN NOT NULL DEFAULT false,
    sort_order INT NOT NULL DEFAULT 0,
    archived_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS maintenance_checkpoints_view_id_idx ON maintenance.checkpoints (view_id);

CREATE TABLE IF NOT EXISTS maintenance.programs (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    equipment_id TEXT NOT NULL REFERENCES maintenance.equipment (id),
    name TEXT NOT NULL,
    description TEXT,
    interval_value INT NOT NULL CHECK (interval_value > 0),
    interval_unit TEXT NOT NULL CHECK (interval_unit IN ('day', 'week', 'month')),
    start_date DATE NOT NULL,
    lead_days INT NOT NULL CHECK (lead_days >= 0),
    estimated_minutes INT,
    default_team_id TEXT REFERENCES maintenance.teams (id),
    stops_machine BOOLEAN NOT NULL DEFAULT false,
    active BOOLEAN NOT NULL DEFAULT true,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS maintenance_programs_tenant_id_active_idx ON maintenance.programs (tenant_id, active);

-- An empty checkpoint set means "every active checkpoint of the machine at
-- occurrence time" -- the service resolves that at job-creation time, not here.
CREATE TABLE IF NOT EXISTS maintenance.program_checkpoints (
    program_id TEXT NOT NULL REFERENCES maintenance.programs (id),
    checkpoint_id TEXT NOT NULL REFERENCES maintenance.checkpoints (id),
    PRIMARY KEY (program_id, checkpoint_id)
);

CREATE TABLE IF NOT EXISTS maintenance.jobs (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    number TEXT NOT NULL,
    equipment_id TEXT NOT NULL REFERENCES maintenance.equipment (id),
    kind TEXT NOT NULL CHECK (kind IN ('preventive', 'corrective')),
    priority TEXT NOT NULL CHECK (priority IN ('normal', 'urgent')),
    title TEXT NOT NULL,
    description TEXT,
    program_id TEXT REFERENCES maintenance.programs (id),
    occurrence_date DATE,
    due_date DATE NOT NULL,
    stops_machine BOOLEAN NOT NULL DEFAULT false,
    status TEXT NOT NULL
        CHECK (status IN ('planned', 'assigned', 'in_progress', 'submitted', 'rework', 'closed', 'cancelled')),
    team_id TEXT REFERENCES maintenance.teams (id),
    chef_user_id TEXT,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    assigned_at TIMESTAMPTZ,
    started_at TIMESTAMPTZ,
    submitted_at TIMESTAMPTZ,
    -- Set once a program sweep has already notified supervisors this job's due
    -- date is overdue, so the worker does not send the same notification twice.
    overdue_notified_at TIMESTAMPTZ,
    closed_at TIMESTAMPTZ,
    closed_by TEXT,
    cancelled_at TIMESTAMPTZ,
    cancel_reason TEXT,
    UNIQUE (tenant_id, number),
    UNIQUE (program_id, occurrence_date)
);

CREATE INDEX IF NOT EXISTS maintenance_jobs_tenant_id_status_idx ON maintenance.jobs (tenant_id, status);
CREATE INDEX IF NOT EXISTS maintenance_jobs_tenant_id_due_date_idx ON maintenance.jobs (tenant_id, due_date);
CREATE INDEX IF NOT EXISTS maintenance_jobs_equipment_id_idx ON maintenance.jobs (equipment_id);

-- checkpoint_id/view_id/x_pct/y_pct are a snapshot taken when the job was
-- created: editing or deleting a machine's map later never rewrites past jobs.
-- NULL for an ad-hoc task that was typed on the job instead of picked from the map.
CREATE TABLE IF NOT EXISTS maintenance.job_checks (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    job_id TEXT NOT NULL REFERENCES maintenance.jobs (id),
    sort_order INT NOT NULL DEFAULT 0,
    checkpoint_id TEXT,
    view_id TEXT,
    x_pct NUMERIC(5, 2),
    y_pct NUMERIC(5, 2),
    label TEXT NOT NULL,
    action TEXT NOT NULL
        CHECK (action IN ('inspect', 'lubricate', 'tighten', 'clean', 'replace', 'measure', 'other')),
    instructions TEXT,
    measure_unit TEXT,
    requires_photo BOOLEAN NOT NULL DEFAULT false,
    assignee_employee_id TEXT,
    -- Current state, derived on write from this check's latest entry/review.
    -- "rejected" never rests here: a reject immediately resets the row to
    -- pending with attempt + 1 (see domain/jobs.py apply_review).
    state TEXT NOT NULL DEFAULT 'pending' CHECK (state IN ('pending', 'done', 'accepted', 'rejected')),
    attempt INT NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS maintenance_job_checks_job_id_idx ON maintenance.job_checks (job_id);

-- Append-only: one row per attempt. A rework never edits or deletes a past
-- entry -- it adds a new one under the bumped attempt, so every attempt's
-- entry stays visible in history.
CREATE TABLE IF NOT EXISTS maintenance.check_entries (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    check_id TEXT NOT NULL REFERENCES maintenance.job_checks (id),
    attempt INT NOT NULL,
    performer_employee_id TEXT NOT NULL,
    recorded_by TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ NOT NULL,
    duration_seconds INT NOT NULL CHECK (duration_seconds > 0),
    duration_source TEXT NOT NULL CHECK (duration_source IN ('timer', 'manual')),
    outcome TEXT NOT NULL CHECK (outcome IN ('ok', 'issue', 'not_done')),
    note TEXT,
    measured_value NUMERIC,
    photo BYTEA,
    photo_mime TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS maintenance_check_entries_check_id_idx ON maintenance.check_entries (check_id);

CREATE TABLE IF NOT EXISTS maintenance.check_reviews (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    check_id TEXT NOT NULL REFERENCES maintenance.job_checks (id),
    attempt INT NOT NULL,
    verdict TEXT NOT NULL CHECK (verdict IN ('accepted', 'rejected')),
    reason TEXT,
    reviewer_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- job_events is the timeline: created, assigned, delegated, started,
-- check_done, submitted, reviewed, rework, closed, cancelled, parts_*.
CREATE TABLE IF NOT EXISTS maintenance.job_events (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    job_id TEXT NOT NULL REFERENCES maintenance.jobs (id),
    at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    actor_id TEXT,
    kind TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS maintenance_job_events_job_id_at_idx ON maintenance.job_events (job_id, at);

CREATE TABLE IF NOT EXISTS maintenance.part_requests (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    job_id TEXT NOT NULL REFERENCES maintenance.jobs (id),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
    note TEXT,
    requested_by TEXT NOT NULL,
    requested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    decided_by TEXT,
    decided_at TIMESTAMPTZ,
    decision_note TEXT
);

CREATE INDEX IF NOT EXISTS maintenance_part_requests_tenant_id_status_idx ON maintenance.part_requests (tenant_id, status);

-- issued_quantity/purchase_quantity are set on approval (split_line in
-- domain/parts.py); fulfilment ("stock"/"purchase"/"split") is derived for
-- display from the two, not stored.
CREATE TABLE IF NOT EXISTS maintenance.part_request_lines (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    request_id TEXT NOT NULL REFERENCES maintenance.part_requests (id),
    product_id TEXT NOT NULL,
    uom_id TEXT NOT NULL,
    quantity NUMERIC NOT NULL CHECK (quantity > 0),
    location_id TEXT,
    issued_quantity NUMERIC,
    purchase_quantity NUMERIC
);
