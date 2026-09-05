-- Same rationale as warehouse/0010 and production/0026: Product is
-- shared-kernel, so qc may reference core.products directly, and nothing was
-- protecting these columns from drifting away from a real product.
ALTER TABLE qc.follow_up_policies
    ADD CONSTRAINT follow_up_policies_product_id_fkey FOREIGN KEY (product_id) REFERENCES core.products (id);
ALTER TABLE qc.non_conformities
    ADD CONSTRAINT non_conformities_product_id_fkey FOREIGN KEY (product_id) REFERENCES core.products (id);
