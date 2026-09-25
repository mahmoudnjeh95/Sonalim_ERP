-- Film, carton, scotch and ruban products were sitting classified as raw_material with no
-- packaging_kind, so the shift form's film/carton/bobine/scotch/ruban dropdowns (which list
-- packaging_component products by kind) were empty. Reclassify the ones the plant already
-- has by name; "Sac Doman PC 4540gr" is a finished-good bag, not a packaging_component, and
-- is left alone.
UPDATE production.product_classifications c
SET category = 'packaging_component', packaging_kind = 'film'
FROM core.products p
WHERE p.id = c.product_id AND p.name ILIKE 'Film %';

UPDATE production.product_classifications c
SET category = 'packaging_component', packaging_kind = 'carton'
FROM core.products p
WHERE p.id = c.product_id AND p.name ILIKE 'Carton%';

UPDATE production.product_classifications c
SET category = 'packaging_component', packaging_kind = 'scotch'
FROM core.products p
WHERE p.id = c.product_id AND p.name ILIKE 'Scotch%';

UPDATE production.product_classifications c
SET category = 'packaging_component', packaging_kind = 'ruban'
FROM core.products p
WHERE p.id = c.product_id AND p.name ILIKE 'Ruban %';
