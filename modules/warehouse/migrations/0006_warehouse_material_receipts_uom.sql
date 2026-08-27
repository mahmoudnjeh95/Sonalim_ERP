-- Material receipts were hardcoded to tons regardless of the product's actual unit of
-- measure (e.g. carton boxes and packaging film are tracked in pieces/kg, not tons).
-- Generalize the quantity column and attach an explicit uom_id per receipt.
ALTER TABLE warehouse.material_receipts RENAME COLUMN quantity_tons TO quantity;
ALTER TABLE warehouse.material_receipts RENAME COLUMN cost_per_ton TO cost_per_unit;
ALTER TABLE warehouse.material_receipts ADD COLUMN uom_id TEXT REFERENCES core.uoms (id);

-- Backfill from each receipt's product uom (falls back to 'ton' if the product can't be
-- resolved), since every existing receipt was in fact entered in its product's own unit —
-- the form just mislabeled the field as tons.
UPDATE warehouse.material_receipts r
SET uom_id = COALESCE(
    (SELECT p.uom_id FROM core.products p WHERE p.id = r.product_id AND p.tenant_id = r.tenant_id),
    (SELECT u.id FROM core.uoms u WHERE u.tenant_id = r.tenant_id AND u.code = 'ton')
)
WHERE r.uom_id IS NULL;

ALTER TABLE warehouse.material_receipts ALTER COLUMN uom_id SET NOT NULL;
