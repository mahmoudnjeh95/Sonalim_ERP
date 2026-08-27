INSERT INTO core.currencies (code, name, decimal_places) VALUES
    ('XOF', 'West African CFA Franc', 0),
    ('XAF', 'Central African CFA Franc', 0),
    ('EUR', 'Euro', 2),
    ('USD', 'US Dollar', 2),
    ('GBP', 'British Pound', 2),
    ('TND', 'Tunisian Dinar', 3)
ON CONFLICT (code) DO NOTHING;

CREATE TABLE IF NOT EXISTS core.exchange_rates (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    currency_code TEXT NOT NULL REFERENCES core.currencies (code),
    rate_to_base NUMERIC NOT NULL CHECK (rate_to_base > 0),
    effective_date DATE NOT NULL,
    source TEXT NOT NULL DEFAULT 'manual',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, currency_code, effective_date)
);

CREATE INDEX IF NOT EXISTS exchange_rates_lookup_idx
    ON core.exchange_rates (tenant_id, currency_code, effective_date DESC);
