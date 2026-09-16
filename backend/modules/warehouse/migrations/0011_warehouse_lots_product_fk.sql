-- Same rationale as 0010 for stock_moves/stock_items: Product is shared-kernel,
-- so warehouse may reference core.products directly, and nothing was stopping
-- lots.product_id from drifting away from a real product.
ALTER TABLE warehouse.lots
    ADD CONSTRAINT lots_product_id_fkey FOREIGN KEY (product_id) REFERENCES core.products (id);
