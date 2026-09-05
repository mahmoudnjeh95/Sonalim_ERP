-- Currency is now decided at receiving, not order creation (see the New Order dialog:
-- prices are never entered there either -- both come from the goods receipt's landed
-- cost). The order's currency_code is nullable and gets backfilled from the first
-- confirmed receipt's currency; required-ness of the receipt's own currency is enforced
-- in PurchaseOrderService.create_receipt, not the database, matching how other required
-- receipt fields (e.g. line quantities) are checked in this codebase.
ALTER TABLE procurement.purchase_orders ALTER COLUMN currency_code DROP NOT NULL;
ALTER TABLE procurement.purchase_orders ALTER COLUMN currency_code DROP DEFAULT;

ALTER TABLE procurement.purchase_order_receipts
    ADD COLUMN IF NOT EXISTS currency_code TEXT REFERENCES core.currencies (code);
