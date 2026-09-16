CREATE TABLE IF NOT EXISTS production.work_centers (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    hourly_rate NUMERIC NOT NULL DEFAULT 0,
    is_blocked BOOLEAN NOT NULL DEFAULT FALSE,
    blocked_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, code)
);

CREATE TABLE IF NOT EXISTS production.machines (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    work_center_id TEXT NOT NULL REFERENCES production.work_centers (id),
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'operational',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, code)
);

CREATE INDEX IF NOT EXISTS machines_work_center_id_idx ON production.machines (work_center_id);

ALTER TABLE production.work_orders ADD COLUMN IF NOT EXISTS work_center_id TEXT REFERENCES production.work_centers (id);
