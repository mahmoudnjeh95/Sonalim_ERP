-- The complete purchase invoice: priced lines with discount and VAT, links to the goods receipts it
-- bills, supplier credit notes, attachments, and a per-tenant default VAT rate.

CREATE TABLE IF NOT EXISTS procurement.invoice_settings (
    tenant_id TEXT PRIMARY KEY,
    default_vat_rate NUMERIC(5, 2) NOT NULL DEFAULT 18 CHECK (default_vat_rate >= 0 AND default_vat_rate <= 100),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Header totals. `amount` keeps its meaning for treasury and the payment events: what is due,
-- i.e. total_incl_tax minus validated credit notes. It can reach 0, and payments made before a credit
-- note can exceed it (the difference is a credit the supplier owes back).
ALTER TABLE procurement.purchase_invoices ADD COLUMN IF NOT EXISTS total_gross NUMERIC(18, 2);
ALTER TABLE procurement.purchase_invoices ADD COLUMN IF NOT EXISTS total_discount NUMERIC(18, 2) NOT NULL DEFAULT 0;
ALTER TABLE procurement.purchase_invoices ADD COLUMN IF NOT EXISTS total_excl_tax NUMERIC(18, 2);
ALTER TABLE procurement.purchase_invoices ADD COLUMN IF NOT EXISTS total_vat NUMERIC(18, 2) NOT NULL DEFAULT 0;
ALTER TABLE procurement.purchase_invoices ADD COLUMN IF NOT EXISTS total_incl_tax NUMERIC(18, 2);
ALTER TABLE procurement.purchase_invoices ADD COLUMN IF NOT EXISTS credited_amount NUMERIC(18, 2) NOT NULL DEFAULT 0;
ALTER TABLE procurement.purchase_invoices DROP CONSTRAINT IF EXISTS purchase_invoices_amount_check;
ALTER TABLE procurement.purchase_invoices DROP CONSTRAINT IF EXISTS purchase_invoices_check;
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'purchase_invoices_amount_not_negative') THEN
        ALTER TABLE procurement.purchase_invoices ADD CONSTRAINT purchase_invoices_amount_not_negative CHECK (amount >= 0);
    END IF;
END $$;
UPDATE procurement.purchase_invoices
SET total_gross = amount, total_excl_tax = amount, total_incl_tax = amount
WHERE total_incl_tax IS NULL;

ALTER TABLE procurement.purchase_invoice_lines ADD COLUMN IF NOT EXISTS line_no INT NOT NULL DEFAULT 0;
ALTER TABLE procurement.purchase_invoice_lines ADD COLUMN IF NOT EXISTS product_id TEXT REFERENCES core.products (id);
ALTER TABLE procurement.purchase_invoice_lines ADD COLUMN IF NOT EXISTS uom_id TEXT REFERENCES core.uoms (id);
ALTER TABLE procurement.purchase_invoice_lines ADD COLUMN IF NOT EXISTS discount_rate NUMERIC(5, 2) NOT NULL DEFAULT 0
    CHECK (discount_rate >= 0 AND discount_rate <= 100);
ALTER TABLE procurement.purchase_invoice_lines ADD COLUMN IF NOT EXISTS vat_rate NUMERIC(5, 2) NOT NULL DEFAULT 0
    CHECK (vat_rate >= 0 AND vat_rate <= 100);
ALTER TABLE procurement.purchase_invoice_lines ADD COLUMN IF NOT EXISTS purchase_order_line_id TEXT
    REFERENCES procurement.purchase_order_lines (id);
ALTER TABLE procurement.purchase_invoice_lines ADD COLUMN IF NOT EXISTS receipt_id TEXT
    REFERENCES procurement.purchase_order_receipts (id);
CREATE INDEX IF NOT EXISTS purchase_invoice_lines_po_line_idx
    ON procurement.purchase_invoice_lines (purchase_order_line_id) WHERE purchase_order_line_id IS NOT NULL;

-- A header-only invoice becomes one line with its old amount and no VAT, so its totals stay what they were.
INSERT INTO procurement.purchase_invoice_lines (id, tenant_id, invoice_id, line_no, description, quantity, unit_price, vat_rate)
SELECT i.id || '-L1', i.tenant_id, i.id, 1, COALESCE(NULLIF(i.note, ''), 'Facture ' || i.supplier_invoice_number), 1, i.amount, 0
FROM procurement.purchase_invoices i
WHERE NOT EXISTS (SELECT 1 FROM procurement.purchase_invoice_lines l WHERE l.invoice_id = i.id);

CREATE TABLE IF NOT EXISTS procurement.purchase_invoice_receipts (
    invoice_id TEXT NOT NULL REFERENCES procurement.purchase_invoices (id) ON DELETE CASCADE,
    receipt_id TEXT NOT NULL REFERENCES procurement.purchase_order_receipts (id),
    tenant_id TEXT NOT NULL,
    PRIMARY KEY (invoice_id, receipt_id)
);

CREATE TABLE IF NOT EXISTS procurement.purchase_credit_notes (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    number TEXT,
    invoice_id TEXT NOT NULL REFERENCES procurement.purchase_invoices (id),
    partner_id TEXT NOT NULL REFERENCES core.partners (id),
    note_date DATE NOT NULL,
    reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'validated', 'cancelled')),
    total_gross NUMERIC(18, 2) NOT NULL DEFAULT 0,
    total_discount NUMERIC(18, 2) NOT NULL DEFAULT 0,
    total_excl_tax NUMERIC(18, 2) NOT NULL DEFAULT 0,
    total_vat NUMERIC(18, 2) NOT NULL DEFAULT 0,
    total_incl_tax NUMERIC(18, 2) NOT NULL DEFAULT 0,
    created_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    validated_at TIMESTAMPTZ
);
CREATE UNIQUE INDEX IF NOT EXISTS purchase_credit_notes_number_uq
    ON procurement.purchase_credit_notes (tenant_id, number) WHERE number IS NOT NULL;
CREATE INDEX IF NOT EXISTS purchase_credit_notes_invoice_idx ON procurement.purchase_credit_notes (invoice_id);

CREATE TABLE IF NOT EXISTS procurement.purchase_credit_note_lines (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    credit_note_id TEXT NOT NULL REFERENCES procurement.purchase_credit_notes (id) ON DELETE CASCADE,
    invoice_line_id TEXT NOT NULL REFERENCES procurement.purchase_invoice_lines (id),
    line_no INT NOT NULL DEFAULT 0,
    description TEXT NOT NULL,
    quantity NUMERIC NOT NULL CHECK (quantity > 0),
    unit_price NUMERIC(18, 4) NOT NULL CHECK (unit_price >= 0),
    discount_rate NUMERIC(5, 2) NOT NULL DEFAULT 0,
    vat_rate NUMERIC(5, 2) NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS purchase_credit_note_lines_note_idx ON procurement.purchase_credit_note_lines (credit_note_id);

CREATE TABLE IF NOT EXISTS procurement.credit_note_counters (
    tenant_id TEXT NOT NULL,
    year INT NOT NULL,
    last_number INT NOT NULL DEFAULT 0,
    PRIMARY KEY (tenant_id, year)
);

CREATE TABLE IF NOT EXISTS procurement.purchase_invoice_attachments (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    invoice_id TEXT NOT NULL REFERENCES procurement.purchase_invoices (id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    content_type TEXT NOT NULL,
    size_bytes INT NOT NULL,
    content BYTEA NOT NULL,
    created_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS purchase_invoice_attachments_invoice_idx ON procurement.purchase_invoice_attachments (invoice_id);
