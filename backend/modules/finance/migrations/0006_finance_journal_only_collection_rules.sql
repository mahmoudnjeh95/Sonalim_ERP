-- A treasury collection rule may name only its journal: both sides of the entry come from elsewhere
-- (the account the money lands in, and the holding account of the payment's own rule). Every other
-- rule still posts to at least one account.
ALTER TABLE finance.posting_rules DROP CONSTRAINT IF EXISTS posting_rules_check;
ALTER TABLE finance.posting_rules DROP CONSTRAINT IF EXISTS posting_rules_accounts_check;
ALTER TABLE finance.posting_rules ADD CONSTRAINT posting_rules_accounts_check CHECK (
    debit_account_code IS NOT NULL
    OR credit_account_code IS NOT NULL
    OR (source = 'treasury' AND source_kind = 'instrument_collected' AND journal_code IS NOT NULL)
);
