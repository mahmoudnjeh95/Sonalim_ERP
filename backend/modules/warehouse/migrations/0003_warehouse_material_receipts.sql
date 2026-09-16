CREATE TABLE IF NOT EXISTS warehouse.material_receipts (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    product_id TEXT NOT NULL,
    location_id TEXT NOT NULL REFERENCES warehouse.locations (id),
    supplier_id TEXT,
    status TEXT NOT NULL DEFAULT 'ordered',
    invoice_number TEXT,
    invoice_date DATE,
    received_at TIMESTAMPTZ,
    origin_country TEXT,
    quantity_containers NUMERIC,
    quantity_tons NUMERIC NOT NULL,
    unit_price NUMERIC NOT NULL DEFAULT 0,
    unit_price_currency TEXT NOT NULL DEFAULT 'EUR',
    base_cost NUMERIC NOT NULL DEFAULT 0,
    license_fee NUMERIC NOT NULL DEFAULT 0,
    insurance_fee NUMERIC NOT NULL DEFAULT 0,
    transit_fee NUMERIC NOT NULL DEFAULT 0,
    transport_fee NUMERIC NOT NULL DEFAULT 0,
    customs_duty NUMERIC NOT NULL DEFAULT 0,
    carrier TEXT,
    total_cost NUMERIC NOT NULL DEFAULT 0,
    cost_per_ton NUMERIC NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS material_receipts_product_idx ON warehouse.material_receipts (tenant_id, product_id);
