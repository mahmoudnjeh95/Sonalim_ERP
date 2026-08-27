CREATE SCHEMA IF NOT EXISTS procurement;

CREATE TABLE IF NOT EXISTS procurement.purchase_orders (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    supplier_id TEXT REFERENCES core.partners (id),
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'validated', 'approved', 'ordered', 'partially_received', 'fully_received', 'canceled', 'refused')),
    order_date DATE,
    expected_date DATE,
    currency_code TEXT NOT NULL DEFAULT 'EUR' REFERENCES core.currencies (code),
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS procurement.purchase_order_lines (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    purchase_order_id TEXT NOT NULL REFERENCES procurement.purchase_orders (id),
    product_id TEXT NOT NULL REFERENCES core.products (id),
    uom_id TEXT NOT NULL REFERENCES core.uoms (id),
    quantity_ordered NUMERIC NOT NULL,
    quantity_received NUMERIC NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'partially_received', 'fully_received')),
    unit_price NUMERIC NOT NULL DEFAULT 0,
    unit_price_currency TEXT NOT NULL DEFAULT 'EUR',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS purchase_order_lines_order_idx ON procurement.purchase_order_lines (tenant_id, purchase_order_id);

-- One row per physical delivery/shipment against an order. Landed-cost fields (freight,
-- customs, insurance) live here, not on the line, because they're incurred per shipment,
-- not per product — the same shape as the material receipt this replaces.
CREATE TABLE IF NOT EXISTS procurement.purchase_order_receipts (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    purchase_order_id TEXT NOT NULL REFERENCES procurement.purchase_orders (id),
    location_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'confirmed')),
    invoice_number TEXT,
    invoice_date DATE,
    origin_country TEXT,
    carrier TEXT,
    base_cost NUMERIC NOT NULL DEFAULT 0,
    license_fee NUMERIC NOT NULL DEFAULT 0,
    insurance_fee NUMERIC NOT NULL DEFAULT 0,
    transit_fee NUMERIC NOT NULL DEFAULT 0,
    transport_fee NUMERIC NOT NULL DEFAULT 0,
    customs_duty NUMERIC NOT NULL DEFAULT 0,
    total_cost NUMERIC NOT NULL DEFAULT 0,
    confirmed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- location_id references warehouse.locations.id. No FK: procurement and warehouse are
-- separate bounded contexts (see erp-platform-architecture skill) — resolved through
-- warehouse's LocationService, and stock is posted via the
-- procurement.purchase_order_receipt.confirmed event, not a direct cross-module call.
COMMENT ON COLUMN procurement.purchase_order_receipts.location_id IS
    'References warehouse.locations.id. No FK: procurement and warehouse are separate modules.';

CREATE INDEX IF NOT EXISTS purchase_order_receipts_order_idx ON procurement.purchase_order_receipts (tenant_id, purchase_order_id);

CREATE TABLE IF NOT EXISTS procurement.purchase_order_receipt_lines (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    purchase_order_receipt_id TEXT NOT NULL REFERENCES procurement.purchase_order_receipts (id),
    purchase_order_line_id TEXT NOT NULL REFERENCES procurement.purchase_order_lines (id),
    quantity NUMERIC NOT NULL,
    -- Assigned at receiving time for lot/serial-tracked products; feeds warehouse.lots.
    lot_number TEXT,
    cost_per_unit NUMERIC NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS purchase_order_receipt_lines_receipt_idx
    ON procurement.purchase_order_receipt_lines (tenant_id, purchase_order_receipt_id);
