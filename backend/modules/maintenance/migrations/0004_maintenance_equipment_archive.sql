-- Archiving retires a machine without deleting it: production history (reports,
-- downtime, shift sections, ...) keeps pointing at a valid equipment row, and
-- the machine can be unarchived if it turns out to still be in use.
ALTER TABLE maintenance.equipment
    ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ;
