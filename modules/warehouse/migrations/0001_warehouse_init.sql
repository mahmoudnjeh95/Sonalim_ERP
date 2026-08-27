CREATE TABLE IF NOT EXISTS warehouse.stock_items (
    tenant_id TEXT NOT NULL,
    product_id TEXT NOT NULL,
    quantity_on_hand NUMERIC NOT NULL DEFAULT 0,
    quantity_reserved NUMERIC NOT NULL DEFAULT 0,
    PRIMARY KEY (tenant_id, product_id)
);

CREATE TABLE IF NOT EXISTS warehouse.stock_moves (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    product_id TEXT NOT NULL,
    quantity NUMERIC NOT NULL,
    move_type TEXT NOT NULL,
    reference TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
