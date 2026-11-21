# Tax engine (WP-1.1) — plan

Spec: `docs/superpowers/specs/2026-11-21-tax-engine-design.md`.

1. Core: migration `0031_core_tax_codes.sql` (table, product and partner columns); `core/domain/tax.py`
   (validation, line resolution, breakdown, whole-franc split) with domain tests; `core/tax_codes.py`
   (service + `/core/tax-codes` router, lazy Mali defaults, assignments, resolve endpoint);
   `core.manage_tax_codes` in `CORE_PERMISSIONS`; router in `app/main.py`.
2. Sales: migration (`tax_code` on order and quote lines); `OrderLine.tax_code`; order and quote creation
   resolve each line through `TaxCodeService.resolve_line`.
3. Procurement: migration (`tax_code` on invoice lines); invoice lines resolved the same way;
   credit-note lines inherit the invoice line's code; `vat_breakdown` on both validated events.
4. Finance: migration (`tax_code` on invoice and credit-note lines, `finance.tax_entries`); billing carries
   the order line's code; `vat_breakdown` on `invoice.issued` and `credit_note.issued`; posting per code
   (`posting.py` allows tax codes on `vat` rules); register writes; `TaxReportService` +
   `GET /finance/reports/vat`.
5. `events/CATALOG.md` versions and fields.
6. Frontend: tax codes screen (finance settings), VAT report screen, tax code select on sales and purchase
   invoice lines, tax codes on product and partner; en + fr strings.
7. Tests on Postgres 16 (migrations + `seed_dev`), `tsc` + vitest; roadmap progress log.
