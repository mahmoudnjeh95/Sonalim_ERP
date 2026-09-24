-- A packing row names the finished product it made. An OF can pack several products (a PC mold
-- change starts a new product on the same OF), so the product lives on the row, not only on the OF.
-- Opaque reference into core.products, like equipment_id: production keeps no foreign key into core.
ALTER TABLE production.shift_packing_rows ADD COLUMN IF NOT EXISTS product_id TEXT;
ALTER TABLE production.conditionnement_reports ADD COLUMN IF NOT EXISTS product_id TEXT;

-- Existing rows made what their OF was for.
UPDATE production.shift_packing_rows p
SET product_id = w.product_id
FROM production.work_orders w
WHERE w.id = p.of_id AND w.tenant_id = p.tenant_id AND p.product_id IS NULL AND w.product_id IS NOT NULL;

UPDATE production.conditionnement_reports c
SET product_id = w.product_id
FROM production.production_reports r
JOIN production.work_orders w ON w.id = r.of_id AND w.tenant_id = r.tenant_id
WHERE r.id = c.report_id AND r.tenant_id = c.tenant_id AND c.product_id IS NULL AND w.product_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS shift_packing_rows_product_idx ON production.shift_packing_rows (tenant_id, product_id);
