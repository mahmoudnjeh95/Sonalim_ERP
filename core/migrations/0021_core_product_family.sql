-- Phase 10 follow-up: product family grouping.
-- The fiche produit groups multiple packaged weights of the same pasta under one
-- family name (e.g. "Spaghetti 1,1" covers both the 200g and 500g SKUs). This is
-- free-text and unvalidated -- purely a grouping/reporting label, not a foreign key --
-- so products can be filtered/charted by family without a separate family table.

ALTER TABLE core.products
  ADD COLUMN IF NOT EXISTS product_family TEXT;
