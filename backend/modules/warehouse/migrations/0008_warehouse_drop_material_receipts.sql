-- Material Receipts has been replaced by the procurement module's Purchase Orders
-- (purchase_orders / purchase_order_lines / purchase_order_receipts). Run
-- scripts/migrate_material_receipts_to_procurement.py against every tenant BEFORE this
-- migration ships, so existing rows have a home in the new schema before this table is
-- dropped -- this migration does not do that copy itself.
DROP TABLE IF EXISTS warehouse.material_receipts;
