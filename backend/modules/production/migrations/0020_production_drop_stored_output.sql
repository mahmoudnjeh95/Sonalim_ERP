-- Phase 6: consolidation forbids stored totals.
--
-- `work_orders.actual_output_quantity` was a cached answer to "how much did this
-- OF produce?". That question now has a real source — the sum of the OF's
-- validated conditionnement reports — and keeping a column beside it invites the
-- two to disagree. Every consolidated figure is computed live from validated
-- reports, the same convention the codebase already uses for regrind's
-- loss_quantity and for yield.
--
-- Regrind is the exception that proves the rule: a rebroyat batch has no report
-- behind it, only the scrap it was built from, so what it actually yielded has
-- nowhere else to live. That value moves onto the batch, where it is a fact about
-- the batch rather than a cached total on the OF.
ALTER TABLE production.regrind_batches ADD COLUMN IF NOT EXISTS actual_output_quantity NUMERIC;

UPDATE production.regrind_batches rb
SET actual_output_quantity = wo.actual_output_quantity
FROM production.work_orders wo
WHERE wo.id = rb.work_order_id AND rb.actual_output_quantity IS NULL;

ALTER TABLE production.work_orders DROP COLUMN IF EXISTS actual_output_quantity;
