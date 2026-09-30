-- Paper scan: photos of the shift fiches, what the OCR read on them, the review in
-- progress, the codes the plant writes (learned from corrections) and, once applied,
-- how each proposed value compared with what the user kept.
CREATE SCHEMA IF NOT EXISTS scan;

CREATE TABLE IF NOT EXISTS scan.scan_sessions (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('shift', 'qc')),
    work_center_id TEXT NOT NULL,
    report_date DATE NOT NULL,
    shift TEXT NOT NULL,
    default_of_id TEXT,
    shift_report_id TEXT,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'applied', 'discarded')),
    review_state JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    applied_by TEXT,
    applied_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS scan_sessions_tenant_created ON scan.scan_sessions (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS scan_sessions_shift_report ON scan.scan_sessions (tenant_id, shift_report_id);

CREATE TABLE IF NOT EXISTS scan.scan_pages (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    session_id TEXT NOT NULL REFERENCES scan.scan_sessions (id) ON DELETE CASCADE,
    image BYTEA NOT NULL,
    content_type TEXT NOT NULL,
    filename TEXT,
    width INTEGER,
    height INTEGER,
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'reading', 'read', 'unrecognized', 'failed')),
    attempts INTEGER NOT NULL DEFAULT 0,
    form_hint TEXT,
    form_type TEXT,
    rotation INTEGER NOT NULL DEFAULT 0,
    ocr_result JSONB,
    error TEXT,
    uploaded_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    read_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS scan_pages_session ON scan.scan_pages (session_id, created_at);
CREATE INDEX IF NOT EXISTS scan_pages_queued ON scan.scan_pages (created_at) WHERE status = 'queued';

CREATE TABLE IF NOT EXISTS scan.scan_aliases (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    raw_text_normalized TEXT NOT NULL,
    raw_text_example TEXT NOT NULL,
    target_value TEXT NOT NULL,
    use_count INTEGER NOT NULL DEFAULT 1,
    created_by TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, kind, raw_text_normalized)
);

CREATE TABLE IF NOT EXISTS scan.scan_field_outcomes (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    session_id TEXT NOT NULL REFERENCES scan.scan_sessions (id) ON DELETE CASCADE,
    page_id TEXT,
    field_path TEXT NOT NULL,
    read_text TEXT,
    confidence NUMERIC,
    proposed_value TEXT,
    final_value TEXT,
    flag TEXT,
    changed BOOLEAN NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS scan_field_outcomes_path ON scan.scan_field_outcomes (tenant_id, field_path);
