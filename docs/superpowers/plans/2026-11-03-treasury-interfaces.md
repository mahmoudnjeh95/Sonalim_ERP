# Purchase invoice + Treasury — cross-plan contract

Read this before any of plans B1–B6. Spec: `docs/superpowers/specs/2026-11-03-stock-vouchers-inventory-treasury-design.md` (Part B and "Decisions (confirmed 2026-11-03)").

## Plan order (each merges on its own)

| Plan | File | Needs |
|---|---|---|
| B1 | `2026-11-03-b1-purchase-invoice.md` | nothing |
| B2 | `2026-11-03-b2-treasury-foundation.md` | nothing (new module + master data) |
| B3 | `2026-11-03-b3-receipts-disbursements.md` | B1, B2 |
| B4 | `2026-11-03-b4-instruments-alerts-journals.md` | B3 |
| B5 | `2026-11-03-b5-statement-import-reports.md` | B3 (B4 for cash journal links) |
| B6 | `2026-11-03-b6-ledger-posting.md` | B3 + HR/finance **Phase 4** (blocked until that merges) |

Part A (stock) is independent: `2026-11-03-stock-vouchers-inventory-valuation.md`.

## Ownership (who writes which table)

- `finance.invoices` (sales invoices): written only by `finance`. New column `amount_paid NUMERIC(18,2) NOT NULL DEFAULT 0`; status set extended with `partially_paid`. Updated by a finance consumer of `treasury.receipt.posted` / `treasury.receipt.cancelled`. The existing manual `mark_paid` stays for back-compat but is refused once any receipt allocation exists.
- `procurement.purchase_invoices` (new, B1): written only by `procurement`. Updated by a procurement consumer of `treasury.disbursement.posted` / `.cancelled`.
- `treasury.*`: written only by `treasury`. Treasury reads invoices **only** through public services: `modules.finance.api.service.InvoiceService.get_invoice(...)` and `modules.procurement.api.invoice_service.PurchaseInvoiceService.get_invoice(...)` (both added in these plans), imported lazily (optional dependencies).
- `treasury` is added to `MODULE_ORDER` in `core/migrations/runner.py` **after** `procurement`, and wired everywhere `maintenance` is (grep `maintenance` in `app/main.py`, the runner's `MODULE_MIGRATION_DIRS`, consumer imports).

## Money and currency

`NUMERIC(18,2)`, `decimal.Decimal` in Python, never float. Default currency `XOF` (F CFA). Treasury accounts have a currency; an allocation of a payment to an invoice must be in the invoice's currency (`CURRENCY_MISMATCH`). No FX conversion in these plans.

## Events (register all in `backend/events/CATALOG.md`; payloads exact)

| Event | Producer | Payload |
|---|---|---|
| `procurement.purchase_invoice.validated` | procurement | `invoice_id, partner_id, amount, currency, due_date` |
| `treasury.receipt.posted` | treasury | `receipt_id, partner_id, allocations:[{invoice_id, amount}], total, currency` |
| `treasury.receipt.cancelled` | treasury | `receipt_id, allocations:[{invoice_id, amount}]` |
| `treasury.disbursement.posted` | treasury | `disbursement_id, partner_id, allocations:[{invoice_id, amount}], total, currency` |
| `treasury.disbursement.cancelled` | treasury | `disbursement_id, allocations:[{invoice_id, amount}]` |
| `treasury.instrument.collected` | treasury | `instrument_id, direction, method, amount, currency, account_id` |
| `treasury.instrument.unpaid` | treasury | `instrument_id, direction, amount, currency` |

Consumers are idempotent on `event_id` (registry) **and** apply allocation deltas keyed by `(event_type, receipt_id or disbursement_id, invoice_id)` in a small dedupe table, so a replay never double-counts.

## Permission codes (exact)

Treasury (`treasury/module.json`): `treasury.view`, `treasury.manage_accounts`, `treasury.manage_receipts`, `treasury.manage_disbursements`, `treasury.collect_instruments`, `treasury.import_statements`, `treasury.admin_config`, `treasury.add_prior_year_invoice`. Procurement: `procurement.view_purchase_invoices`, `procurement.manage_purchase_invoices`, `procurement.admin_purchase_invoices`. Not auto-granted.

## Error codes (all with a French third argument)

`INVOICE_NOT_VALIDATED`, `OVER_ALLOCATION`, `CURRENCY_MISMATCH`, `ACCOUNT_NUMBER_DUPLICATE`, `CASH_LIMIT_EXCEEDED`, `INSTRUMENT_FIELDS_REQUIRED`, `INSTRUMENT_NOT_PENDING`, `INSUFFICIENT_BALANCE`, `ACCOUNT_LOCKED`, `PRIOR_YEAR_NOT_ALLOWED`, `STATEMENT_FORMAT_INVALID`, `STATEMENT_DUPLICATE_LINE`, `TOTAL_MISMATCH`, `DUPLICATE_SUPPLIER_INVOICE`.

## Alerts (no notification infrastructure exists)

Nothing in the repo sends notifications. Alerts are **computed on demand**: `GET /treasury/alerts` returns instruments whose alert window has opened; the SPA calls it on layout mount for users holding `treasury.view` and shows a banner/toast. No worker job, no email.

## Common rules (every plan)

Raw SQL via psycopg; callers commit; `record_audit()` in the same transaction on every mutation; routers pass `actor_id=tenant.user_id`; `Err(code, en, fr)` and `err_detail` (`core/test_error_translations.py` must stay green); every UI string in both `en` and `fr` of `frontend/src/lib/i18n.tsx`; tests next to code, `*_integration.py` use the `db` fixture and **skip** without a DB (read the skip count); frontend check `npx tsc -b --force` from `frontend/`; commits end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`; never `git stash`; `git add` only listed files; **never push** (a push to `huge_production_migration` deploys live). Backend commands run from `backend/` with `.venv/Scripts/python -m pytest ... -q`; the venv's interpreter currently points to a missing Python 3.11, so repair it first (recreate the venv with an installed Python and reinstall requirements).
