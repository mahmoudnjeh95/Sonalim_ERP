CREATE SCHEMA IF NOT EXISTS maintenance;

CREATE TABLE IF NOT EXISTS maintenance.equipment (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    work_center_id TEXT NOT NULL,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'operational',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, code)
);

CREATE INDEX IF NOT EXISTS maintenance_equipment_work_center_id_idx ON maintenance.equipment (work_center_id);

-- work_center_id is deliberately not a foreign key: it is an opaque reference
-- into production.work_centers, the same pattern qc uses for of_id. Modules
-- do not hold live FKs into another module's schema.

-- One-time cutover: the equipment registry used to live in production.machines.
-- Copy its rows across before 0002 drops that table. Irreversible by design --
-- once 0002 runs, production.machines and this INSERT's source are both gone.
INSERT INTO maintenance.equipment (id, tenant_id, work_center_id, code, name, status, created_at)
SELECT id, tenant_id, work_center_id, code, name, status, created_at FROM production.machines
ON CONFLICT (id) DO NOTHING;
