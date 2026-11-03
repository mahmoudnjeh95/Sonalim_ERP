-- One row per (event, document, invoice) already applied, so a replayed treasury event can
-- never double-count a disbursement.
CREATE TABLE IF NOT EXISTS procurement.invoice_payment_deltas (
    event_type TEXT NOT NULL,
    document_id TEXT NOT NULL,
    invoice_id TEXT NOT NULL,
    amount NUMERIC(18, 2) NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (event_type, document_id, invoice_id)
);
