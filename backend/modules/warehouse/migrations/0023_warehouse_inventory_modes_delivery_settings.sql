-- Interim inventories (no freeze, no stock change), line observations, document dates,
-- delivery notes as a voucher type, the tenant's valuation method and attached files.

ALTER TABLE warehouse.cycle_counts ADD COLUMN IF NOT EXISTS mode TEXT NOT NULL DEFAULT 'full';
ALTER TABLE warehouse.cycle_counts DROP CONSTRAINT IF EXISTS cycle_counts_mode_check;
ALTER TABLE warehouse.cycle_counts ADD CONSTRAINT cycle_counts_mode_check CHECK (mode IN ('full', 'interim'));
ALTER TABLE warehouse.cycle_counts ADD COLUMN IF NOT EXISTS note TEXT;

ALTER TABLE warehouse.cycle_count_lines ADD COLUMN IF NOT EXISTS observation TEXT;
ALTER TABLE warehouse.cycle_count_lines DROP CONSTRAINT IF EXISTS cycle_count_lines_resolution_check;
ALTER TABLE warehouse.cycle_count_lines ADD CONSTRAINT cycle_count_lines_resolution_check
    CHECK (resolution IN ('matched', 'approved', 'rejected', 'noted'));

ALTER TABLE warehouse.vouchers ADD COLUMN IF NOT EXISTS document_date DATE NOT NULL DEFAULT CURRENT_DATE;
-- The document a delivery note was generated from; billable is false for a re-delivery after a return.
ALTER TABLE warehouse.vouchers ADD COLUMN IF NOT EXISTS from_voucher_id TEXT REFERENCES warehouse.vouchers (id);
ALTER TABLE warehouse.vouchers ADD COLUMN IF NOT EXISTS billable BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE warehouse.vouchers DROP CONSTRAINT IF EXISTS vouchers_type_check;
ALTER TABLE warehouse.vouchers ADD CONSTRAINT vouchers_type_check CHECK (type IN ('receipt', 'issue', 'return', 'transfer', 'delivery'));
-- One entry voucher per goods receipt: procurement already moved the stock, this is its document.
CREATE UNIQUE INDEX IF NOT EXISTS vouchers_purchase_receipt_uq ON warehouse.vouchers (tenant_id, ref_id)
    WHERE ref_type = 'purchase_receipt';

CREATE TABLE IF NOT EXISTS warehouse.settings (
    tenant_id TEXT PRIMARY KEY,
    valuation_method TEXT NOT NULL DEFAULT 'fifo' CHECK (valuation_method IN ('fifo', 'average')),
    updated_by TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS warehouse.document_attachments (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    entity_type TEXT NOT NULL CHECK (entity_type IN ('voucher', 'cycle_count')),
    entity_id TEXT NOT NULL,
    filename TEXT NOT NULL,
    content_type TEXT NOT NULL,
    size_bytes INT NOT NULL,
    content BYTEA NOT NULL,
    uploaded_by TEXT,
    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS document_attachments_entity_idx ON warehouse.document_attachments (tenant_id, entity_type, entity_id);
