-- A payment order (ordre de virement) is the instruction handed to the bank for the transfers of one
-- disbursement. It carries no money movement of its own: the disbursement already did that.
CREATE TABLE IF NOT EXISTS treasury.payment_orders (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    number TEXT NOT NULL,
    disbursement_id TEXT NOT NULL REFERENCES treasury.documents (id),
    note TEXT,
    created_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS payment_orders_number_uq ON treasury.payment_orders (tenant_id, number);
CREATE UNIQUE INDEX IF NOT EXISTS payment_orders_disbursement_uq ON treasury.payment_orders (disbursement_id);

-- In-app notices addressed to one user (for example "please execute this payment order").
CREATE TABLE IF NOT EXISTS treasury.user_notifications (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL REFERENCES core.users (id),
    kind TEXT NOT NULL,
    ref_id TEXT,
    message_en TEXT NOT NULL,
    message_fr TEXT NOT NULL,
    created_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    read_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS user_notifications_user_idx ON treasury.user_notifications (user_id, read_at);
