CREATE TABLE IF NOT EXISTS production.packaging_boms (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    target_product_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS production.packaging_bom_lines (
    id TEXT PRIMARY KEY,
    bom_id TEXT NOT NULL REFERENCES production.packaging_boms(id),
    tenant_id TEXT NOT NULL,
    component_product_id TEXT NOT NULL,
    quantity_per_unit NUMERIC NOT NULL
);

-- Defense in depth for "only one active BOM per target product": PackagingBomService
-- already serializes activation via a family-scoped row lock, but this index guarantees
-- the invariant at the database level too, independent of the application code path.
CREATE UNIQUE INDEX IF NOT EXISTS packaging_boms_one_active_per_target
    ON production.packaging_boms (tenant_id, target_product_id)
    WHERE status = 'active';
