-- Phase 10: Add product type (PL/PC) and packaging specifications
-- Product type is a required classifier for pasta products (Pâte Longues / Pâte Courte)
-- Packaging fields capture hierarchy: sachet weight, package quantity, carton specs, pallet specs

ALTER TABLE core.products
  ADD COLUMN IF NOT EXISTS product_type TEXT NOT NULL DEFAULT 'PL'
    CHECK (product_type IN ('PL', 'PC')),
  ADD COLUMN IF NOT EXISTS empty_packaging_weight_grams NUMERIC,
  ADD COLUMN IF NOT EXISTS sachets_per_package NUMERIC,
  ADD COLUMN IF NOT EXISTS carton_weight_grams NUMERIC,
  ADD COLUMN IF NOT EXISTS cartons_per_pallet NUMERIC;

-- Ensure positive quantities and weights
ALTER TABLE core.products
  ADD CONSTRAINT products_empty_packaging_weight_positive
    CHECK (empty_packaging_weight_grams IS NULL OR empty_packaging_weight_grams > 0),
  ADD CONSTRAINT products_sachets_per_package_positive
    CHECK (sachets_per_package IS NULL OR sachets_per_package > 0),
  ADD CONSTRAINT products_carton_weight_positive
    CHECK (carton_weight_grams IS NULL OR carton_weight_grams > 0),
  ADD CONSTRAINT products_cartons_per_pallet_positive
    CHECK (cartons_per_pallet IS NULL OR cartons_per_pallet > 0);
