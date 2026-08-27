CREATE TABLE IF NOT EXISTS core.user_table_preferences (
    user_id TEXT NOT NULL REFERENCES core.users (id),
    tenant_id TEXT NOT NULL,
    table_key TEXT NOT NULL,
    columns JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, table_key)
);
