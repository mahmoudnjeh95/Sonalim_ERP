# WP-1.2 Real customer invoices — design

## What already exists (read 2026-11-22)
Invoices built from deliveries have lines (list price, discount, net price, VAT rate), totals excl. tax /
VAT / incl. tax, a numbering sequence (`finance.document_counters`, `FV-YYYY-000001`), payment terms with
instalments and due dates, partial payments (`amount_paid`, `partially_paid`, treasury allocations) and
credit notes from returns, all with VAT.

## Gaps
1. An invoice made by hand (`POST /finance/invoices`) or from an order confirmation is a **single amount**:
   no lines, no VAT, no description, so it cannot be a legal invoice and the VAT report misses it.
2. Draft lines cannot be edited; the only edit is the admin one that overwrites `amount`, which for an invoice
   with lines leaves the lines and the total saying different things.
3. Rows created before lines existed have no line at all.
4. Issuing checks nothing: an invoice with no line or a zero total can be issued.

## Design
- `finance.invoice_lines` gains `description` and `product_id` becomes nullable (a service or free line).
  Migration `finance/0014` backfills one line (qty 1, price = amount, 0 % VAT) for every invoice without
  lines. Totals are unchanged.
- Pure rules in `domain/billing.py`: `ManualLine` (product or description, quantity > 0, unit price >= 0,
  discount 0-100 %, VAT 0-100 %), net price = list price after discount, `document_totals` as today.
- `InvoiceService.create_invoice(partner, lines, invoice_date)`: draft with lines and VAT, numbered, dated
  from the customer's terms. `create_draft_invoice(amount)` keeps working (events, seeds, tests): it writes
  its single line.
- `InvoiceService.replace_lines(draft, lines, invoice_date)`: draft only; recomputes totals and re-spreads the
  instalments.
- `admin_update_invoice(amount=...)`: allowed only on a single-amount invoice (it updates that line too);
  an invoice with real lines refuses it (`AMOUNT_FROM_LINES`).
- Issuing refuses an invoice with no line (`INVOICE_EMPTY`).
- API: `POST /finance/invoices` accepts `lines` (or `amount` as before) and `invoice_date`;
  `PUT /finance/invoices/{id}/lines`. A line may name a `tax_code` from WP-1.1 instead of a `vat_rate`; the
  rate is copied onto the line (snapshot).
- Frontend: the create dialog gets an editable line table (description or product, qty, price, discount,
  tax code) with live totals; draft invoices can be re-edited. en + fr.

## Out of scope
Manual credit notes (a credit note today comes from a return voucher; WP-2.3), PDF (WP-2.5), invoicing in
other currencies.

## Done when
A user can create, edit and issue a multi-line VAT invoice with no order or delivery; old single-amount rows
show one line; the VAT report counts them; tests pass on Postgres.
