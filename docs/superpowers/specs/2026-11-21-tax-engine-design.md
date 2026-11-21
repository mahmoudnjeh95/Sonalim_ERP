# WP-1.1 Tax engine — design

## What already exists (read 2026-11-21)

- A VAT **rate on every line**: `sales.order_lines`, `sales.quote_lines`, `finance.invoice_lines`,
  `finance.credit_note_lines`, `procurement.purchase_invoice_lines` (`vat_rate NUMERIC(5,2)`), and the
  document totals `amount_excl_tax` / `vat_amount` (finance), `total_excl_tax/vat/incl_tax` (procurement).
- **Two separate default rates**, both 18 %: `sales.settings.default_vat_rate` and
  `procurement.invoice_settings.default_vat_rate`. `core.products.tax_rate` exists but nothing reads it.
- **Tax accounts in posting rules**: `invoice / vat / *` credits 443 (collected), `purchase_invoice / vat / *`
  debits 445 (deductible); credit notes and supplier credit notes mirror them.

## Gaps this package closes

1. No tax codes: a rate is a bare number, so there is no name ("TVA 18 %", "Exonéré"), no way to say a line
   is *exempt* rather than merely 0 %, and no one place to change the rate when the law does.
2. Two defaults to keep in step by hand.
3. No tax report: nothing says how much VAT was collected, how much is deductible, and what is owed.

## Design

### Tax code catalogue (shared kernel)
`core.tax_codes` per tenant: `code`, `name_fr`, `name_en`, `rate` (0–100), `applies_to`
(`sales` | `purchase` | `both`), `exempt` (rate must be 0), `active`, `is_default_sales`,
`is_default_purchase`. Same shape as `core.payment_terms`: filled with defaults on first read
(`TVA18` 18 % both, default for both; `EXO` 0 % exempt, both), `core/tax_codes.py` service with audit,
at most one default per side (setting one clears the previous one in the same transaction).
A line keeps its own `vat_rate` snapshot, as today: changing a code never rewrites issued documents.

### One default
`TaxCodeService.default_rate(tenant_id, side)` returns the default code's rate. Sales and procurement
settings read it when the tenant has a default code and fall back to their stored value otherwise.
Updating either module's `default_vat_rate` setting now sets the default *code* instead of creating a
second truth: it finds an active code with that rate and side, or creates `TVA<rate>`. (Their APIs and
the frontend settings screens do not change.)

### Tax report (finance)
`GET /finance/reports/vat?date_from&date_to` (permission `finance.view_ledger`):
- `collected_by_rate`: from `finance.invoice_lines` of invoices issued/partially paid/paid in the period,
  minus `finance.credit_note_lines`, grouped by `vat_rate`: net base, VAT. Rate 0 is reported as
  "exempt / zero-rated".
- `ledger`: booked movement in the period on the collected-VAT account (credit of the `invoice / vat`
  rule) and the deductible-VAT account (debit of the `purchase_invoice / vat` rule); `vat_payable` =
  collected − deductible. The purchase side comes from the ledger because finance may not read
  procurement tables.
- `warnings`: lists a missing/unconfirmed VAT rule instead of failing.

### Frontend
Tax codes screen (list, create, edit, set default) in finance settings; VAT report page. en + fr keys.

## Out of scope (recorded for later packages)
Tax code on the line itself and on events (needs a payload version bump), withholding taxes, reverse
charge, per-product default code, filing/export formats (WP-3.4 country packs).

## Done when
Tax codes can be created and made default per tenant; sales and purchase defaults come from them; the VAT
report shows collected / deductible / payable for a period; tests pass against Postgres; manifests and
catalog tests pass.
