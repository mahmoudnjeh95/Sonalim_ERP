ALTER TABLE production.product_classifications
    DROP CONSTRAINT IF EXISTS product_classifications_packaging_format_check;

ALTER TABLE production.product_classifications
    ADD CONSTRAINT product_classifications_packaging_format_check
    CHECK (packaging_format IN ('packet', 'carton', 'sac'));
