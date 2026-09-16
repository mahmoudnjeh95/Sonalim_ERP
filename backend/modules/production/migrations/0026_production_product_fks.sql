-- Product is shared-kernel (core.products), so production may reference it
-- directly, same as procurement.purchase_order_lines already does. Every
-- product_id-shaped column in this module except one is a real product.id and
-- had no FK protecting it -- see 0010_warehouse_stock_product_fk.sql in the
-- warehouse module for the incident that prompted this sweep (a product with
-- live stock got deleted outright because nothing enforced this anywhere).
--
-- production.product_classifications.product_id is deliberately excluded: it
-- is keyed by SKU, not by products.id (see FinishedGoodsAnalysisTab.tsx), so
-- this FK would be wrong there.
ALTER TABLE production.conditionnement_reports
    ADD CONSTRAINT conditionnement_reports_carton_product_id_fkey FOREIGN KEY (carton_product_id) REFERENCES core.products (id);
ALTER TABLE production.conditionnement_reports
    ADD CONSTRAINT conditionnement_reports_film_product_id_fkey FOREIGN KEY (film_product_id) REFERENCES core.products (id);
ALTER TABLE production.conditionnement_reports
    ADD CONSTRAINT conditionnement_reports_tape_product_id_fkey FOREIGN KEY (tape_product_id) REFERENCES core.products (id);

ALTER TABLE production.daily_reports
    ADD CONSTRAINT daily_reports_regrind_input_product_id_fkey FOREIGN KEY (regrind_input_product_id) REFERENCES core.products (id);
ALTER TABLE production.daily_reports
    ADD CONSTRAINT daily_reports_regrind_product_id_fkey FOREIGN KEY (regrind_product_id) REFERENCES core.products (id);
ALTER TABLE production.daily_reports
    ADD CONSTRAINT daily_reports_semolina_product_id_fkey FOREIGN KEY (semolina_product_id) REFERENCES core.products (id);

ALTER TABLE production.packaging_bom_lines
    ADD CONSTRAINT packaging_bom_lines_component_product_id_fkey FOREIGN KEY (component_product_id) REFERENCES core.products (id);
ALTER TABLE production.packaging_boms
    ADD CONSTRAINT packaging_boms_target_product_id_fkey FOREIGN KEY (target_product_id) REFERENCES core.products (id);

ALTER TABLE production.packaging_tolerances
    ADD CONSTRAINT packaging_tolerances_product_id_fkey FOREIGN KEY (product_id) REFERENCES core.products (id);

ALTER TABLE production.recipe_lines
    ADD CONSTRAINT recipe_lines_component_product_id_fkey FOREIGN KEY (component_product_id) REFERENCES core.products (id);
ALTER TABLE production.recipes
    ADD CONSTRAINT recipes_target_product_id_fkey FOREIGN KEY (target_product_id) REFERENCES core.products (id);

ALTER TABLE production.regrind_defaults
    ADD CONSTRAINT regrind_defaults_input_product_id_fkey FOREIGN KEY (input_product_id) REFERENCES core.products (id);
ALTER TABLE production.regrind_defaults
    ADD CONSTRAINT regrind_defaults_output_product_id_fkey FOREIGN KEY (output_product_id) REFERENCES core.products (id);

ALTER TABLE production.report_waste_lines
    ADD CONSTRAINT report_waste_lines_product_id_fkey FOREIGN KEY (product_id) REFERENCES core.products (id);
ALTER TABLE production.scrap_records
    ADD CONSTRAINT scrap_records_product_id_fkey FOREIGN KEY (product_id) REFERENCES core.products (id);

ALTER TABLE production.work_order_inputs
    ADD CONSTRAINT work_order_inputs_product_id_fkey FOREIGN KEY (product_id) REFERENCES core.products (id);
ALTER TABLE production.work_orders
    ADD CONSTRAINT work_orders_product_id_fkey FOREIGN KEY (product_id) REFERENCES core.products (id);
