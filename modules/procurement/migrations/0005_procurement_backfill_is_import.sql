-- is_import defaults to false for every pre-existing order (0004), which is wrong for any
-- order that already paid license/insurance/transit/customs fees on a receipt -- those are
-- import-only fees under the new validate_receipt_fees rule. Backfill from that evidence so
-- existing orders aren't silently reclassified as "local" in the Analysis tab / cost-summary
-- import-vs-local split.
UPDATE procurement.purchase_orders po
SET is_import = true
WHERE is_import = false
  AND EXISTS (
    SELECT 1 FROM procurement.purchase_order_receipts r
    WHERE r.purchase_order_id = po.id
      AND (r.license_fee > 0 OR r.insurance_fee > 0 OR r.transit_fee > 0 OR r.customs_duty > 0)
  );
