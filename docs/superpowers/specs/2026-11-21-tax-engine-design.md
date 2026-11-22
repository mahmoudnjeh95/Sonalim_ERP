# Tax engine (WP-1.1) — design

## What was there

- A VAT **rate** on every priced line: `sales.order_lines`, `sales.quote_lines`, `finance.invoice_lines`,
  `finance.credit_note_lines`, `procurement.purchase_invoice_lines`, `procurement.purchase_credit_note_lines`.
  The default rate is a per-module setting (`sales.settings.default_vat_rate`,
  `procurement.invoice_settings.default_vat_rate`, 18 %). `core.products.tax_rate` exists but nothing reads it.
- Documents carry their VAT total (`finance.invoices.vat_amount`, `procurement.purchase_invoices.total_vat`, …),
  and the events carry it (`finance.invoice.issued` 1.1 `vat`, `procurement.purchase_invoice.validated` 1.1
  `total_vat`).
- The ledger posts the whole VAT of a document to one account: rule `invoice / vat / *` (443 collected) or
  `purchase_invoice / vat / *` (445 deductible). Rules of those sources only accept the code `*`.
- No tax code, no exemption, no tax report.

## What this adds

1. **Tax codes, per tenant, in the shared kernel** (`core.tax_codes`): `code` (immutable, e.g. `TVA18`),
   French/English names, `rate`, `scope` (`sales`, `purchases`, `both`), `exempt` with a `legal_mention`
   (the sentence printed on an invoice, e.g. "Exonération de TVA — article …"), `active`. Sales, finance
   and procurement all need them, so they live in core like payment terms. Seeded lazily on first read
   with the Mali defaults `TVA18` (18 %) and `EXO` (exempt, 0 %); WP-3.4 moves that to country packs.
2. **Assignments**: a product names its sales and purchase code (`core.products.sales_tax_code_id`,
   `purchase_tax_code_id`); a partner can carry an exemption or special code that overrides the product
   (`core.partners.customer_tax_code_id`, `supplier_tax_code_id`).
3. **Lines carry the code** (`tax_code` TEXT, a snapshot like `vat_rate`; NULL on old rows) on sales order and
   quote lines, finance invoice and credit-note lines, and purchase invoice lines. A purchase credit-note line
   takes its invoice line's code while it keeps that line's rate (no column). Resolution in
   `TaxCodeService.resolve_line` (core):
   - an explicit `tax_code` wins; its rate is the line's rate (an explicit different `vat_rate` is refused,
     `TAX_RATE_MISMATCH`); an inactive or out-of-scope code is refused;
   - an explicit `vat_rate` with no code keeps the rate and takes the code of that rate (partner's, then
     product's, then the first active non-exempt code of that scope with the rate), or none: an exemption is a
     status someone chose, never read from a 0 % rate;
   - neither: partner code, then product code, then the module's default rate (as today) with its code.
   Existing callers that send only rates keep their exact totals.
4. **VAT breakdown on the events**: `finance.invoice.issued` 1.2, `finance.credit_note.issued` 1.1,
   `procurement.purchase_invoice.validated` 1.2 and `procurement.purchase_credit_note.validated` 1.1 add
   `vat_breakdown`: `[{tax_code, rate, base, vat}]`, one per (code, rate), unrounded. Additive.
5. **Tax accounts in posting rules**: `invoice / vat / <tax code>` and `purchase_invoice / vat / <tax code>`
   are allowed, with `*` as the fallback. Finance splits the document's VAT (in whole F CFA) across the
   breakdown, the rounding gap on the largest part, and posts each part to its code's rule account. An
   event without a breakdown posts as before.
6. **Tax register and report**: finance writes `finance.tax_entries` in the same transaction as each VAT-
   bearing entry: date, direction (`collected` / `deductible`), code, rate, base and VAT in F CFA, signed
   (credit notes and cancelled purchase invoices negative), source document and journal entry. Exempt and
   0 % lines are recorded too (their base is part of the return). `GET /finance/reports/vat?date_from&date_to`
   gives per direction and code the base and VAT, the net VAT due (collected − deductible), and as a check
   the movements of the VAT accounts in the ledger over the period. Documents posted before this release are
   not in the register (finance cannot read procurement's tables to backfill it); the ledger check column
   still shows their VAT.

## Not in this WP

- Withholding taxes (AIB, BIC précompte): treasury already has `*_withheld` rules.
- Printing the legal mention on a PDF (WP-2.5), per-country packs (WP-3.4).
- Backfilling the register for documents posted earlier.

## Screens

- Accounting > Tax codes (`/finance/tax-codes`): the catalog, and the code of a partner or product per side.
- Accounting > VAT return (`/finance/vat`).
- Sales quote/order lines and purchase invoice lines choose a code instead of typing a rate (the rate input
  stays when a tenant has no codes). A line nobody touched follows `GET /core/tax-codes/resolve` (partner,
  then product, then default rate); a line loaded from a saved document keeps its tax.

## Permissions

- `core.manage_tax_codes` (new, core): create/edit codes and assignments. Reading codes needs a session.
- The report uses `finance.view_ledger`.
