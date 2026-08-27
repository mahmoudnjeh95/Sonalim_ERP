-- bcrypt embeds its own salt in password_hash; password_salt is no longer
-- written for new users. Loosened, not dropped, so existing sha256+salt rows
-- (dev-seeded only, pre-production) remain valid until re-hashed on next login.
ALTER TABLE core.users ALTER COLUMN password_salt DROP NOT NULL;
