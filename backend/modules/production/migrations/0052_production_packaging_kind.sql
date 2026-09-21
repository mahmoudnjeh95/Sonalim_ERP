-- Which kind of packaging a packaging component is, so the shift screen's film, carton,
-- bobine, scotch and ruban dropdowns can each list their own items. Only meaningful for
-- category 'packaging_component' (enforced in the domain, like packaging_format).
ALTER TABLE production.product_classifications
    ADD COLUMN IF NOT EXISTS packaging_kind TEXT
    CHECK (packaging_kind IN ('film', 'carton', 'bobine', 'scotch', 'ruban'));
