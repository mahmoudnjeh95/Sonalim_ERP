-- In-app notifications for any module. A row belongs to one user; read_at is
-- set when they open it. Modules write through core.notifications.notify().
CREATE TABLE IF NOT EXISTS core.notifications (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL REFERENCES core.users (id),
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    title_fr TEXT NOT NULL,
    body TEXT,
    body_fr TEXT,
    link TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    read_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS core_notifications_user_idx
    ON core.notifications (tenant_id, user_id, read_at, created_at DESC);
