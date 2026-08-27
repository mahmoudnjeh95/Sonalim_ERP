ALTER TABLE production.product_classifications
    ADD COLUMN IF NOT EXISTS packaging_format TEXT CHECK (packaging_format IN ('packet', 'carton'));
