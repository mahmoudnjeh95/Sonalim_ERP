-- What the vendor manual asks of receipts, instruments, cash registers and payment orders.

-- Every receipt payment waits on the deposit slip until it is collected, not only cheques and drafts.
ALTER TABLE treasury.instruments DROP CONSTRAINT IF EXISTS instruments_method_check;
ALTER TABLE treasury.instruments ADD CONSTRAINT instruments_method_check
    CHECK (method IN ('cash', 'cheque', 'draft', 'transfer', 'mobile_money'));
ALTER TABLE treasury.instruments ADD COLUMN IF NOT EXISTS issue_date DATE;
ALTER TABLE treasury.instruments ADD COLUMN IF NOT EXISTS branch_name TEXT;
ALTER TABLE treasury.instruments ADD COLUMN IF NOT EXISTS deposit_date DATE;
ALTER TABLE treasury.instruments ADD COLUMN IF NOT EXISTS slip_reference TEXT;

-- The part of an invoice the partner kept back (montant retenu): it settles the invoice without moving money.
ALTER TABLE treasury.documents ADD COLUMN IF NOT EXISTS withheld_amount NUMERIC(18, 2) NOT NULL DEFAULT 0;
ALTER TABLE treasury.documents DROP CONSTRAINT IF EXISTS documents_withheld_amount_check;
ALTER TABLE treasury.documents ADD CONSTRAINT documents_withheld_amount_check CHECK (withheld_amount >= 0);

-- The notes and coins counted for a cash payment: {"10000": 3, "500": 2}.
ALTER TABLE treasury.document_payments ADD COLUMN IF NOT EXISTS denominations JSONB;

-- A cash register is the principal one or a secondary one.
ALTER TABLE treasury.accounts ADD COLUMN IF NOT EXISTS cash_type TEXT;
ALTER TABLE treasury.accounts DROP CONSTRAINT IF EXISTS accounts_cash_type_check;
ALTER TABLE treasury.accounts ADD CONSTRAINT accounts_cash_type_check CHECK (cash_type IS NULL OR cash_type IN ('principal', 'secondary'));

-- An ordre de paiement asks someone to pay a purchase invoice. It moves no money and comes before any
-- disbursement, unlike treasury.payment_orders (ordre de virement), the bank instruction for a posted one.
CREATE TABLE IF NOT EXISTS treasury.invoice_payment_orders (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    number TEXT NOT NULL,
    order_date DATE NOT NULL,
    due_date DATE NOT NULL,
    method TEXT NOT NULL CHECK (method IN ('cash', 'cheque', 'draft', 'transfer', 'mobile_money')),
    partner_id TEXT NOT NULL REFERENCES core.partners (id),
    invoice_id TEXT NOT NULL,
    employee_user_id TEXT NOT NULL REFERENCES core.users (id),
    department TEXT,
    note TEXT,
    created_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS invoice_payment_orders_number_uq ON treasury.invoice_payment_orders (tenant_id, number);

-- Files attached to a receipt or disbursement.
CREATE TABLE IF NOT EXISTS treasury.document_attachments (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    document_id TEXT NOT NULL REFERENCES treasury.documents (id),
    filename TEXT NOT NULL,
    content_type TEXT NOT NULL,
    size_bytes INT NOT NULL,
    content BYTEA NOT NULL,
    created_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS document_attachments_document_idx ON treasury.document_attachments (document_id);
