-- A packing row's empty cartons are now the cartons lost in the packing-waste section,
-- worked out whenever either section is saved. Rows filled in before that typed the figure
-- on the row itself, so give each one the lost-carton line it amounts to -- otherwise saving
-- that shift again would zero it. Rows that already have such a line are left alone.

INSERT INTO production.shift_waste_lines
    (id, tenant_id, shift_report_id, section_key, packing_row_id, category, product_id, quantity, line_order)
SELECT 'bf-wc-' || p.id, p.tenant_id, p.shift_report_id, 'waste_packing', p.id, 'packaging',
       p.carton_product_id, p.waste_carton_quantity, 1000 + p.line_order
FROM production.shift_packing_rows p
WHERE p.waste_carton_quantity > 0 AND p.carton_product_id IS NOT NULL
  AND NOT EXISTS (
      SELECT 1 FROM production.shift_waste_lines w
      WHERE w.tenant_id = p.tenant_id AND w.shift_report_id = p.shift_report_id
        AND w.section_key = 'waste_packing' AND w.product_id = p.carton_product_id
  )
ON CONFLICT (id) DO NOTHING;
