-- XOF (F CFA) is the project's default currency. The invoice column defaulted to 'USD', but
-- amounts were always entered in F CFA: legacy USD rows are relabelled XOF, never converted
-- (same decision as hr 0006_hr_contract_terms.sql).
ALTER TABLE finance.invoices ALTER COLUMN currency SET DEFAULT 'XOF';
UPDATE finance.invoices SET currency = 'XOF' WHERE currency = 'USD';
