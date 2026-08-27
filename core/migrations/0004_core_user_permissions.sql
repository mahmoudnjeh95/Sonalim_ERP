CREATE TABLE IF NOT EXISTS core.user_permissions (
    user_id TEXT NOT NULL REFERENCES core.users (id),
    permission TEXT NOT NULL,
    granted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, permission)
);
