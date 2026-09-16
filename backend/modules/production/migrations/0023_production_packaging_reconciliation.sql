-- Phase 9: packaging reconciliation. Decisions 17-22.
--
-- The packing report grows a second finished-product figure, because it was
-- carrying two meanings in one column. `finished_product_quantity` is the
-- tonnage that came off the scale -- what yield and consolidation are computed
-- from. `packets_counted` is what the line actually tallied, and from this
-- migration it is what validation posts into stock (decision 18).
--
-- Posting the tally rather than the figure derived from the tonnage is the whole
-- point: if validation posted the estimate, stock would always *be* the estimate
-- and the ecart could never appear in it.
ALTER TABLE production.conditionnement_reports
    ADD COLUMN IF NOT EXISTS packets_counted NUMERIC NOT NULL DEFAULT 0;

-- Decision 20: the parameters are frozen onto the report when it is validated, so
-- correcting a product's net weight next month cannot silently rewrite the ecart
-- of a report that was signed off against the old one. NULL until validation.
ALTER TABLE production.conditionnement_reports
    ADD COLUMN IF NOT EXISTS snapshot_net_weight_grams NUMERIC;
ALTER TABLE production.conditionnement_reports
    ADD COLUMN IF NOT EXISTS snapshot_packets_per_carton NUMERIC;

-- ---------------------------------------------------------------------------
-- Backfill. This column is changing meaning, so existing rows have to be placed
-- explicitly rather than left to be reinterpreted by accident.
--
-- Every existing row's `finished_product_quantity` is, whatever anyone intended
-- it to mean, exactly the number `post_conditionnement_report` pushed into stock
-- as a piece count. So it moves to `packets_counted` first: that keeps the stock
-- ledger reconcilable against the reports that produced it, which is the one
-- property that must not break here.
UPDATE production.conditionnement_reports SET packets_counted = finished_product_quantity;

-- The tonnage can then be recovered wherever the OF's product knows what a packet
-- weighs. Where it does not, the figure is left exactly as it was: inventing a
-- tonnage from a missing weight would be worse than leaving a number that a human
-- can still recognise and correct. Those rows are findable with
--   SELECT r.id FROM production.production_reports r
--   JOIN production.conditionnement_reports c ON c.report_id = r.id
--   WHERE c.packets_counted = c.finished_product_quantity AND c.packets_counted > 0;
UPDATE production.conditionnement_reports c
SET finished_product_quantity = c.packets_counted * p.net_weight_grams / 1000000
FROM production.production_reports r
JOIN production.work_orders w ON w.id = r.of_id AND w.tenant_id = r.tenant_id
JOIN core.products p ON p.id = w.product_id AND p.tenant_id = w.tenant_id
WHERE c.report_id = r.id
  AND c.tenant_id = r.tenant_id
  AND p.net_weight_grams IS NOT NULL
  AND p.net_weight_grams > 0;

-- ---------------------------------------------------------------------------
-- Decision 22: the tolerance that colours an ecart, following the shape
-- qc.follow_up_policies already uses -- a tenant default row with product_id
-- NULL, and an optional override row per product. It colours a number and
-- nothing else; no validation path consults it.
CREATE TABLE IF NOT EXISTS production.packaging_tolerances (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    product_id TEXT,
    tolerance_percent NUMERIC NOT NULL CHECK (tolerance_percent >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS packaging_tolerances_one_per_product
    ON production.packaging_tolerances (tenant_id, product_id)
    NULLS NOT DISTINCT;
