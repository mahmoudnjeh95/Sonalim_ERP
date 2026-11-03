-- Document-level vouchers over the move ledger, physical inventory with a location freeze.
-- Valuation is the FIFO cost layers of 0018. No foreign keys into other modules except the shared kernel.

CREATE TABLE IF NOT EXISTS warehouse.voucher_counters (
    tenant_id TEXT NOT NULL,
    voucher_type TEXT NOT NULL,
    year INT NOT NULL,
    last_number INT NOT NULL DEFAULT 0,
    PRIMARY KEY (tenant_id, voucher_type, year)
);

CREATE TABLE IF NOT EXISTS warehouse.vouchers (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    number TEXT,
    type TEXT NOT NULL CHECK (type IN ('receipt', 'issue', 'return', 'transfer')),
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'posted', 'cancelled')),
    source_location_id TEXT REFERENCES warehouse.locations (id),
    dest_location_id TEXT REFERENCES warehouse.locations (id),
    partner_id TEXT REFERENCES core.partners (id),
    ref_type TEXT,
    ref_id TEXT,
    return_of_voucher_id TEXT REFERENCES warehouse.vouchers (id),
    note TEXT,
    created_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    posted_by TEXT,
    posted_at TIMESTAMPTZ
);
CREATE UNIQUE INDEX IF NOT EXISTS vouchers_number_uq ON warehouse.vouchers (tenant_id, number) WHERE number IS NOT NULL;
CREATE INDEX IF NOT EXISTS vouchers_ref_idx ON warehouse.vouchers (tenant_id, ref_type, ref_id);

CREATE TABLE IF NOT EXISTS warehouse.voucher_lines (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    voucher_id TEXT NOT NULL REFERENCES warehouse.vouchers (id) ON DELETE CASCADE,
    product_id TEXT NOT NULL REFERENCES core.products (id),
    quantity NUMERIC NOT NULL CHECK (quantity > 0),
    unit_cost NUMERIC(18, 4),
    return_of_line_id TEXT REFERENCES warehouse.voucher_lines (id)
);
CREATE INDEX IF NOT EXISTS voucher_lines_voucher_idx ON warehouse.voucher_lines (voucher_id);

CREATE TABLE IF NOT EXISTS warehouse.inventories (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    number TEXT NOT NULL,
    location_id TEXT NOT NULL REFERENCES warehouse.locations (id),
    type TEXT NOT NULL CHECK (type IN ('full', 'interim')),
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed', 'cancelled')),
    note TEXT,
    opened_by TEXT,
    opened_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    closed_by TEXT,
    closed_at TIMESTAMPTZ
);
CREATE UNIQUE INDEX IF NOT EXISTS inventories_number_uq ON warehouse.inventories (tenant_id, number);
-- One open full inventory per location: that is what makes the freeze unambiguous.
CREATE UNIQUE INDEX IF NOT EXISTS inventories_one_open_full_uq
    ON warehouse.inventories (tenant_id, location_id) WHERE status = 'open' AND type = 'full';

CREATE TABLE IF NOT EXISTS warehouse.inventory_lines (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    inventory_id TEXT NOT NULL REFERENCES warehouse.inventories (id) ON DELETE CASCADE,
    product_id TEXT NOT NULL REFERENCES core.products (id),
    theoretical_qty NUMERIC NOT NULL,
    count_1 NUMERIC,
    count_2 NUMERIC,
    count_3 NUMERIC,
    final_qty NUMERIC,
    variance NUMERIC,
    observation TEXT,
    UNIQUE (inventory_id, product_id)
);

-- Cost valuation itself is FIFO (0018 cost_layers); this column only records the cost on a receipt move.
ALTER TABLE warehouse.stock_moves ADD COLUMN IF NOT EXISTS unit_cost NUMERIC(18, 4);
