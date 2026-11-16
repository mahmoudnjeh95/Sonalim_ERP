-- Sales invoices follow the delivery (the manual: a delivery note or a shipped pick list is what is
-- billed), not the order confirmation. Each invoice now records the delivery it bills and its lines;
-- returns against an invoiced delivery become credit notes (factures avoir).

ALTER TABLE finance.invoices ADD COLUMN IF NOT EXISTS number TEXT;
ALTER TABLE finance.invoices ADD COLUMN IF NOT EXISTS invoice_date DATE;
-- order: created at confirmation under the old rule; delivery_note: a billable BL; shipment: a shipped pick list.
ALTER TABLE finance.invoices ADD COLUMN IF NOT EXISTS source_type TEXT;
ALTER TABLE finance.invoices ADD COLUMN IF NOT EXISTS source_id TEXT;
ALTER TABLE finance.invoices ADD COLUMN IF NOT EXISTS source_number TEXT;
-- What validated credit notes took off; what is due is amount - amount_credited.
ALTER TABLE finance.invoices ADD COLUMN IF NOT EXISTS amount_credited NUMERIC(18, 2) NOT NULL DEFAULT 0;

UPDATE finance.invoices SET invoice_date = created_at::date WHERE invoice_date IS NULL;
UPDATE finance.invoices SET source_type = 'order', source_id = source_order_id
WHERE source_order_id IS NOT NULL AND source_type IS NULL;

-- One invoice per delivery document: a replayed event finds it.
CREATE UNIQUE INDEX IF NOT EXISTS invoices_source_uq
    ON finance.invoices (tenant_id, source_type, source_id) WHERE source_type IN ('delivery_note', 'shipment');
CREATE UNIQUE INDEX IF NOT EXISTS invoices_number_uq ON finance.invoices (tenant_id, number) WHERE number IS NOT NULL;
CREATE INDEX IF NOT EXISTS invoices_source_order_idx ON finance.invoices (tenant_id, source_order_id);

CREATE TABLE IF NOT EXISTS finance.invoice_lines (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    invoice_id TEXT NOT NULL REFERENCES finance.invoices (id),
    product_id TEXT NOT NULL,
    quantity NUMERIC(18, 4) NOT NULL CHECK (quantity > 0),
    unit_price NUMERIC(18, 4) NOT NULL CHECK (unit_price >= 0),
    amount NUMERIC(18, 2) NOT NULL
);
CREATE INDEX IF NOT EXISTS invoice_lines_invoice_idx ON finance.invoice_lines (invoice_id);

CREATE TABLE IF NOT EXISTS finance.document_counters (
    tenant_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    year INT NOT NULL,
    last_number INT NOT NULL,
    PRIMARY KEY (tenant_id, kind, year)
);

CREATE TABLE IF NOT EXISTS finance.credit_notes (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    number TEXT NOT NULL,
    invoice_id TEXT NOT NULL REFERENCES finance.invoices (id),
    partner_id TEXT NOT NULL,
    -- the posted return voucher it comes from
    source_id TEXT NOT NULL,
    source_number TEXT,
    credit_date DATE NOT NULL,
    amount NUMERIC(18, 2) NOT NULL CHECK (amount > 0),
    currency TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, number),
    UNIQUE (tenant_id, source_id, invoice_id)
);
CREATE INDEX IF NOT EXISTS credit_notes_invoice_idx ON finance.credit_notes (invoice_id);

CREATE TABLE IF NOT EXISTS finance.credit_note_lines (
    id TEXT PRIMARY KEY,
    credit_note_id TEXT NOT NULL REFERENCES finance.credit_notes (id),
    product_id TEXT NOT NULL,
    quantity NUMERIC(18, 4) NOT NULL CHECK (quantity > 0),
    unit_price NUMERIC(18, 4) NOT NULL,
    amount NUMERIC(18, 2) NOT NULL
);
CREATE INDEX IF NOT EXISTS credit_note_lines_note_idx ON finance.credit_note_lines (credit_note_id);
