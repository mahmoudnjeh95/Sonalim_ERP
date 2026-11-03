-- An employee's papers and when they expire. The platform has no file storage yet: file_ref
-- says where the scan is kept (a path or a URL).
CREATE TABLE IF NOT EXISTS hr.employee_documents (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    employee_id TEXT NOT NULL REFERENCES hr.employees (id),
    kind TEXT NOT NULL CONSTRAINT hr_employee_documents_kind_check CHECK (kind IN (
        'id_card', 'passport', 'work_permit', 'medical_certificate', 'driving_licence',
        'diploma', 'criminal_record', 'signed_contract', 'other'
    )),
    title TEXT,
    file_ref TEXT,
    issued_on DATE,
    expires_on DATE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT hr_employee_documents_dates_check CHECK (issued_on IS NULL OR expires_on IS NULL OR expires_on >= issued_on)
);
CREATE INDEX IF NOT EXISTS hr_employee_documents_employee_idx ON hr.employee_documents (tenant_id, employee_id);
CREATE INDEX IF NOT EXISTS hr_employee_documents_expiry_idx ON hr.employee_documents (tenant_id, expires_on) WHERE expires_on IS NOT NULL;
