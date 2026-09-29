-- Public holidays per tenant and country. scripts/seed_hr_payroll.py seeds Mali with
-- confirmed = FALSE: religious holidays follow the moon and HR confirms each year's date.
CREATE TABLE IF NOT EXISTS hr.public_holidays (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    country_code TEXT NOT NULL CHECK (country_code ~ '^[A-Z]{2}$'),
    holiday_date DATE NOT NULL,
    name TEXT NOT NULL,
    paid BOOLEAN NOT NULL DEFAULT TRUE,
    confirmed BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, country_code, holiday_date)
);

-- One row per tenant, every value empty until HR sets it: the night-work window is
-- statutory and the punch values describe how the plant uses its clock. Nothing that
-- needs a value runs on an assumed one (PRESENCE_SETTINGS_MISSING instead).
CREATE TABLE IF NOT EXISTS hr.presence_settings (
    tenant_id TEXT PRIMARY KEY,
    night_start_minute SMALLINT CHECK (night_start_minute BETWEEN 0 AND 1439),
    night_end_minute SMALLINT CHECK (night_end_minute BETWEEN 0 AND 1439),
    punch_attach_minutes SMALLINT CHECK (punch_attach_minutes >= 0),
    punch_dedupe_seconds INTEGER CHECK (punch_dedupe_seconds >= 0),
    late_grace_minutes SMALLINT CHECK (late_grace_minutes >= 0),
    confirmed_by TEXT,
    confirmed_at TIMESTAMPTZ,
    updated_by TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
