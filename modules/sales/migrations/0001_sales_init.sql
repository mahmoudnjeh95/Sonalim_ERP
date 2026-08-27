CREATE TABLE IF NOT EXISTS sales.orders (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    partner_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS sales.order_lines (
    id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL REFERENCES sales.orders (id),
    tenant_id TEXT NOT NULL,
    product_id TEXT NOT NULL,
    quantity NUMERIC NOT NULL,
    unit_price NUMERIC NOT NULL
);
