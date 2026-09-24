-- Rebroyat versement: regrind material (already reground) poured back into
-- production, recorded once per shift alongside the raw-material versements.
CREATE TABLE IF NOT EXISTS production.shift_rebroyat_versements (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    shift_report_id TEXT NOT NULL REFERENCES production.shift_reports (id) ON DELETE CASCADE,
    product_id TEXT,
    location_id TEXT,
    quantity NUMERIC NOT NULL DEFAULT 0,
    line_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS shift_rebroyat_versements_shift_idx ON production.shift_rebroyat_versements (shift_report_id);
