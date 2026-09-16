-- Extends the shared-kernel Product with the catalog fields the "New product" screen
-- needs (sell/purchase status, lot tracking policy, pricing, tax, accounting codes).
-- sku/name already cover "Product ref."/"Label", so no new columns for those.
ALTER TABLE core.products ADD COLUMN IF NOT EXISTS is_sellable BOOLEAN NOT NULL DEFAULT true;
ALTER TABLE core.products ADD COLUMN IF NOT EXISTS is_purchasable BOOLEAN NOT NULL DEFAULT true;
ALTER TABLE core.products ADD COLUMN IF NOT EXISTS lot_serial_tracking TEXT NOT NULL DEFAULT 'none'
    CHECK (lot_serial_tracking IN ('none', 'lot', 'serial'));
ALTER TABLE core.products ADD COLUMN IF NOT EXISTS expiry_date_policy TEXT NOT NULL DEFAULT 'none'
    CHECK (expiry_date_policy IN ('none', 'sell_by', 'eat_by'));
ALTER TABLE core.products ADD COLUMN IF NOT EXISTS description TEXT;
ALTER TABLE core.products ADD COLUMN IF NOT EXISTS stock_alert_threshold NUMERIC;
ALTER TABLE core.products ADD COLUMN IF NOT EXISTS internal_note TEXT;
ALTER TABLE core.products ADD COLUMN IF NOT EXISTS selling_price NUMERIC NOT NULL DEFAULT 0;
ALTER TABLE core.products ADD COLUMN IF NOT EXISTS min_selling_price NUMERIC;
ALTER TABLE core.products ADD COLUMN IF NOT EXISTS tax_rate NUMERIC NOT NULL DEFAULT 0;
ALTER TABLE core.products ADD COLUMN IF NOT EXISTS accounting_code_sale TEXT;
ALTER TABLE core.products ADD COLUMN IF NOT EXISTS accounting_code_sale_export TEXT;
ALTER TABLE core.products ADD COLUMN IF NOT EXISTS accounting_code_purchase TEXT;
ALTER TABLE core.products ADD COLUMN IF NOT EXISTS accounting_code_purchase_import TEXT;

-- Default warehouse: a plain id, not a foreign key. warehouse.locations lives in the
-- warehouse module and core cannot depend on a leaf module's schema (see
-- erp-platform-architecture skill's shared-kernel rule) — resolve this id through
-- warehouse's LocationService when needed, the same loose-reference pattern already
-- used for product_id inside modules/warehouse/migrations.
ALTER TABLE core.products ADD COLUMN IF NOT EXISTS default_location_id TEXT;
