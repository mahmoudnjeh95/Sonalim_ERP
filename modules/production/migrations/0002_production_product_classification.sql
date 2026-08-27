CREATE TABLE IF NOT EXISTS production.product_classifications (
    tenant_id TEXT NOT NULL,
    product_id TEXT NOT NULL,
    category TEXT NOT NULL CHECK (category IN ('raw_material', 'semi_finished', 'packaging_component', 'finished_good')),
    is_regrind BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (tenant_id, product_id)
);
