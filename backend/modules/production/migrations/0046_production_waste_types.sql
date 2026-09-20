-- Déchet kinds a plant can name for itself.
--
-- The eight built-in categories (raw_material, press, pouring, cross, kneading,
-- finished_product_conditioning on the daily report; product, packaging on the
-- packing report) stay in code, with translated names. A tenant adds its own
-- here: a name, and which report the entry belongs to. Nothing is pre-filled --
-- a tenant that added nothing simply has the built-ins.
--
-- `report_type` is fixed at creation. A line filed under a type is validated
-- against the report it sits on, so moving a type from the daily to the packing
-- report would leave existing lines describing a stage their report never ran.
--
-- Retiring is not deleting, same as core.report_options: an inactive type is no
-- longer offered on a new line, but reports that used it keep their meaning and
-- stay editable.
CREATE TABLE IF NOT EXISTS production.waste_types (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    name TEXT NOT NULL,
    report_type TEXT NOT NULL CHECK (report_type IN ('daily', 'conditionnement')),
    sort_order INTEGER NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Two kinds with the same name on the same report are the same kind.
CREATE UNIQUE INDEX IF NOT EXISTS waste_types_unique_name
    ON production.waste_types (tenant_id, report_type, lower(name));

CREATE INDEX IF NOT EXISTS waste_types_tenant_idx
    ON production.waste_types (tenant_id, report_type, sort_order);

-- A line's category is now either a built-in key or the id of a row above, so a
-- fixed list in the database can no longer say what is valid. The service checks
-- it (validate_waste_lines), against the built-ins plus the tenant's own types,
-- and refuses a category the report type does not have. Dropping a constraint
-- is backward-compatible: older code only ever wrote the built-in keys.
ALTER TABLE production.report_waste_lines DROP CONSTRAINT IF EXISTS report_waste_lines_category_check;
