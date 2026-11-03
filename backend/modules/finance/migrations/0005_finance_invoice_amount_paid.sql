-- Sales invoices become payable in instalments: treasury receipts allocate amounts to them,
-- and the status follows the amount paid (issued -> partially_paid -> paid).
ALTER TABLE finance.invoices ADD COLUMN IF NOT EXISTS amount_paid NUMERIC(18, 2) NOT NULL DEFAULT 0;

-- Already-paid invoices predate allocations: treat them as fully paid so the figures agree.
UPDATE finance.invoices SET amount_paid = amount WHERE status = 'paid' AND amount_paid = 0;

-- One row per (event, document, invoice) already applied, so a replayed treasury event can
-- never double-count a payment.
CREATE TABLE IF NOT EXISTS finance.invoice_payment_deltas (
    event_type TEXT NOT NULL,
    document_id TEXT NOT NULL,
    invoice_id TEXT NOT NULL,
    amount NUMERIC(18, 2) NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (event_type, document_id, invoice_id)
);
