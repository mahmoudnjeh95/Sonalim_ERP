-- What a plant changed about the built-in déchet kinds.
--
-- The built-ins stay in code (a line stores their key, and the day sheet and
-- analytics reason about some of them), so they cannot be deleted. A plant can
-- still rename one, take it off the forms, and move it anywhere in its report's
-- list, among its own kinds. One row per built-in it touched; no row means the
-- built-in as shipped: translated name, offered, in code order ahead of the
-- plant's own kinds.
--
-- `name` NULL means "the translated default". `sort_order` shares its scale with
-- production.waste_types.sort_order on the same report: the reorder endpoint
-- writes both lists in one go.
CREATE TABLE IF NOT EXISTS production.waste_type_builtin_settings (
    tenant_id TEXT NOT NULL,
    category TEXT NOT NULL,
    report_type TEXT NOT NULL CHECK (report_type IN ('daily', 'conditionnement')),
    name TEXT,
    sort_order INTEGER,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (tenant_id, category)
);
