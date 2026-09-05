CREATE TABLE IF NOT EXISTS core.roles (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, code)
);

CREATE TABLE IF NOT EXISTS core.role_permissions (
    role_id TEXT NOT NULL REFERENCES core.roles (id),
    permission TEXT NOT NULL,
    PRIMARY KEY (role_id, permission)
);

CREATE TABLE IF NOT EXISTS core.user_roles (
    user_id TEXT NOT NULL REFERENCES core.users (id),
    role_id TEXT NOT NULL REFERENCES core.roles (id),
    granted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, role_id)
);
