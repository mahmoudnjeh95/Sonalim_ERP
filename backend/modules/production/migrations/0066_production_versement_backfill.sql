-- The runs' dough and rebroyat used are now worked out from the shift's versements
-- whenever the Production section is saved. Shifts filled in before that recorded the
-- same material per run instead (semoule lines, rebroyat used), so give them the
-- versements it amounts to -- otherwise saving one of them again would zero its figures.
-- Only shifts with no versement of that kind yet are touched.

INSERT INTO production.shift_rebroyat_versements (id, tenant_id, shift_report_id, product_id, location_id, quantity, line_order)
SELECT 'bf-rv-' || r.shift_report_id || '-' || r.regrind_input_product_id, r.tenant_id, r.shift_report_id,
       r.regrind_input_product_id, MIN(r.raw_material_location_id), SUM(r.regrind_input_quantity),
       (ROW_NUMBER() OVER (PARTITION BY r.shift_report_id ORDER BY r.regrind_input_product_id))::int - 1
FROM production.shift_runs r
WHERE r.regrind_input_quantity > 0 AND r.regrind_input_product_id IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM production.shift_rebroyat_versements v WHERE v.shift_report_id = r.shift_report_id)
GROUP BY r.tenant_id, r.shift_report_id, r.regrind_input_product_id
ON CONFLICT (id) DO NOTHING;

INSERT INTO production.shift_versements (id, tenant_id, shift_report_id, product_id, location_id, quantity, line_order)
SELECT 'bf-v-' || r.shift_report_id || '-' || l.product_id, r.tenant_id, r.shift_report_id,
       l.product_id, MIN(l.location_id), SUM(l.quantity),
       (ROW_NUMBER() OVER (PARTITION BY r.shift_report_id ORDER BY l.product_id))::int - 1
FROM production.shift_run_semolina_lines l
JOIN production.shift_runs r ON r.id = l.run_id AND r.tenant_id = l.tenant_id
WHERE l.quantity > 0 AND l.product_id IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM production.shift_versements v WHERE v.shift_report_id = r.shift_report_id)
GROUP BY r.tenant_id, r.shift_report_id, l.product_id
ON CONFLICT (id) DO NOTHING;
