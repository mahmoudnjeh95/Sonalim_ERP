-- Same rationale as warehouse/0010, production/0026 and qc/0002: Product is
-- shared-kernel, so sales may reference core.products directly, and nothing
-- was protecting order_lines.product_id from drifting away from a real product.
ALTER TABLE sales.order_lines
    ADD CONSTRAINT order_lines_product_id_fkey FOREIGN KEY (product_id) REFERENCES core.products (id);
