# Money as Decimal (WP-0.4) — plan

Spec: `specs/2026-11-20-money-as-decimal-design.md`.

1. [x] `core/domain/money.py`: `to_decimal`, `json_number` (+ `test_money.py`).
2. [x] Sales: `OrderLine` / `SalesOrder` fields `Decimal`, coerced in `__post_init__`; `total_amount`
   is `Decimal`; service reads rows without `float()`, passes `float` quantity to
   `StockService.reserve_stock`, writes JSON numbers to the event and audit payloads; router
   request models `Decimal`, `_serialize_order` writes JSON numbers; quote → order conversion
   without `float()`.
3. [x] Finance invoices: `Invoice.amount` / `amount_paid` `Decimal`; `status_for_payment` on
   `Decimal`; `InvoiceService` create/update/list/transition without `float()`; router request
   models `Decimal`.
4. [x] Procurement: `PurchaseOrderLine`, `PurchaseOrderReceipt`, `PurchaseOrderReceiptLine`
   `Decimal` (coerced); `compute_landed_cost` in `Decimal`; receipt confirmation converts UoM
   and exchange rate in `Decimal`, hands warehouse floats; router request models `Decimal`,
   responses JSON numbers. Reports left `float` (spec, "Not in scope").
5. [x] Tests: float-drift regressions (0.1 + 0.2 receipts against 0.3 ordered, landed cost,
   float callers), invoice amount over HTTP stored exactly.
6. [x] Full backend suite on Postgres (migrations + `seed_dev`), frontend `tsc` + vitest.
