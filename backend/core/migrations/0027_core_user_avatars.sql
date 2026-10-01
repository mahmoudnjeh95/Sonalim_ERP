-- The photo a person sets on their own profile. One row per user, replaced in place.
--
-- The bytes live here rather than on a volume or in object storage because an avatar is
-- small (the browser crops and re-encodes to a square before upload, and the route caps
-- what it accepts): keeping it in Postgres means it is covered by the same backup as the
-- rest of the tenant's data and needs no extra service on the server. The scan module
-- already stores page images the same way.
CREATE TABLE IF NOT EXISTS core.user_avatars (
    user_id TEXT PRIMARY KEY REFERENCES core.users (id) ON DELETE CASCADE,
    tenant_id TEXT NOT NULL,
    image BYTEA NOT NULL,
    content_type TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
