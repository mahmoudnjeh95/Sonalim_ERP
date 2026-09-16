-- core.users has never carried a display name -- only email, used everywhere a
-- user is shown (created_by, validated_by, an OF's supervisor). Nullable: existing
-- accounts have none on file yet, and the fallback everywhere that reads it stays
-- the email until an admin sets one via the Users page.
ALTER TABLE core.users ADD COLUMN IF NOT EXISTS full_name TEXT;
