-- Product is shared-kernel (core.products), so a direct FK from warehouse is
-- allowed under the architecture rule -- unlike source_type/source_id/of_id in
-- 0009, which stay opaque because they'd point into production/qc's own tables.
--
-- Without this, nothing stopped a stock_moves/stock_items row from carrying a
-- product_id that isn't a real product.id: core.api.service.delete_product()
-- already catches psycopg.errors.ForeignKeyViolation and returns PRODUCT_IN_USE,
-- but with no FK to violate, a product with live stock could be deleted outright,
-- leaving its stock orphaned and unresolvable in the UI. Found via a manually
-- inserted row carrying a product's SKU instead of its id, and confirmed live:
-- a product was deleted 2026-09-03 while still holding 2000.22 units of stock,
-- and the delete silently succeeded instead of being blocked.
ALTER TABLE warehouse.stock_moves
    ADD CONSTRAINT stock_moves_product_id_fkey FOREIGN KEY (product_id) REFERENCES core.products (id);

ALTER TABLE warehouse.stock_items
    ADD CONSTRAINT stock_items_product_id_fkey FOREIGN KEY (product_id) REFERENCES core.products (id);
