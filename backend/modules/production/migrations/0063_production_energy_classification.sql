-- Fuel and gasoil are classified raw_material (they are bought and consumed like one) but
-- they are never poured into the line: the shift's "MP versé" dropdown must not offer them.
-- is_energy marks them, the same way is_water marks water. Flag the two the plant already
-- has by SKU.
ALTER TABLE production.product_classifications ADD COLUMN IF NOT EXISTS is_energy BOOLEAN NOT NULL DEFAULT FALSE;

UPDATE production.product_classifications c
SET is_energy = TRUE
FROM core.products p
WHERE p.id = c.product_id AND c.category = 'raw_material' AND NOT c.is_regrind AND NOT c.is_water
  AND lower(p.sku) IN ('fuel', 'gasoil');
