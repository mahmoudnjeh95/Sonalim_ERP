-- Supplier invoices. Payment progress (amount_paid) is only ever changed by the
-- service in response to treasury disbursement events; users never edit it.
CREATE TABLE IF NOT EXISTS procurement.purchase_invoices (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    number TEXT,
    partner_id TEXT NOT NULL REFERENCES core.partners (id),
    supplier_invoice_number TEXT NOT NULL,
    purchase_order_id TEXT REFERENCES procurement.purchase_orders (id),
    invoice_date DATE NOT NULL,
    due_date DATE,
    currency TEXT NOT NULL DEFAULT 'XOF' REFERENCES core.currencies (code),
    amount NUMERIC(18, 2) NOT NULL CHECK (amount > 0),
    amount_paid NUMERIC(18, 2) NOT NULL DEFAULT 0 CHECK (amount_paid >= 0),
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'validated', 'partially_paid', 'paid', 'cancelled')),
    note TEXT,
    created_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    validated_at TIMESTAMPTZ,
    CHECK (amount_paid <= amount)
);

CREATE UNIQUE INDEX IF NOT EXISTS purchase_invoices_supplier_number_uq
    ON procurement.purchase_invoices (tenant_id, partner_id, supplier_invoice_number);
CREATE UNIQUE INDEX IF NOT EXISTS purchase_invoices_number_uq
    ON procurement.purchase_invoices (tenant_id, number) WHERE number IS NOT NULL;
CREATE INDEX IF NOT EXISTS purchase_invoices_status_due_idx
    ON procurement.purchase_invoices (tenant_id, status, due_date);

CREATE TABLE IF NOT EXISTS procurement.purchase_invoice_lines (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    invoice_id TEXT NOT NULL REFERENCES procurement.purchase_invoices (id) ON DELETE CASCADE,
    description TEXT NOT NULL,
    quantity NUMERIC NOT NULL CHECK (quantity > 0),
    unit_price NUMERIC(18, 4) NOT NULL CHECK (unit_price >= 0)
);

CREATE INDEX IF NOT EXISTS purchase_invoice_lines_invoice_idx
    ON procurement.purchase_invoice_lines (invoice_id);

CREATE TABLE IF NOT EXISTS procurement.invoice_counters (
    tenant_id TEXT NOT NULL,
    year INT NOT NULL,
    last_number INT NOT NULL DEFAULT 0,
    PRIMARY KEY (tenant_id, year)
);
