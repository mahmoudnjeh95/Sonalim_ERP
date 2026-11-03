-- What the bank charged for rejecting a cheque, and the account it took it from. Both are set together
-- or not at all; the balance itself moves through treasury.account_movements like any other movement.
ALTER TABLE treasury.instruments ADD COLUMN IF NOT EXISTS rejection_fee NUMERIC(18, 2);
ALTER TABLE treasury.instruments ADD COLUMN IF NOT EXISTS rejection_fee_account_id TEXT REFERENCES treasury.accounts (id);

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'instruments_rejection_fee_check') THEN
        ALTER TABLE treasury.instruments ADD CONSTRAINT instruments_rejection_fee_check CHECK (
            (rejection_fee IS NULL AND rejection_fee_account_id IS NULL)
            OR (rejection_fee > 0 AND rejection_fee_account_id IS NOT NULL)
        );
    END IF;
END $$;
