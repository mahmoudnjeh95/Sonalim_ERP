-- How many days ahead HR is warned about contracts ending, trial periods ending and documents
-- expiring. Empty until HR sets them: an unset horizon switches that alert list off.
CREATE TABLE IF NOT EXISTS hr.settings (
    tenant_id TEXT PRIMARY KEY,
    contract_expiry_horizon_days INTEGER CONSTRAINT hr_settings_contract_days_check
        CHECK (contract_expiry_horizon_days IS NULL OR contract_expiry_horizon_days > 0),
    trial_end_horizon_days INTEGER CONSTRAINT hr_settings_trial_days_check
        CHECK (trial_end_horizon_days IS NULL OR trial_end_horizon_days > 0),
    document_expiry_horizon_days INTEGER CONSTRAINT hr_settings_document_days_check
        CHECK (document_expiry_horizon_days IS NULL OR document_expiry_horizon_days > 0),
    updated_by TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
