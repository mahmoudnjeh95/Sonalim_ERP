CREATE TABLE IF NOT EXISTS production.resource_types (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    unit TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, code)
);

CREATE TABLE IF NOT EXISTS production.daily_consumption (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    consumption_date DATE NOT NULL,
    resource_type_id TEXT NOT NULL REFERENCES production.resource_types (id),
    quantity NUMERIC NOT NULL,
    note TEXT,
    actor_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, consumption_date, resource_type_id)
);

CREATE INDEX IF NOT EXISTS daily_consumption_date_idx ON production.daily_consumption (tenant_id, consumption_date);
