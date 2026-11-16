# B3 — Receipts and disbursements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or superpowers:executing-plans. Read `2026-11-03-treasury-interfaces.md` first. Needs B1 (purchase invoice) and B2 (accounts).

**Goal:** Record customer receipts (encaissements) against sales invoices and supplier disbursements (décaissements) against purchase invoices, with several payment methods per document, moving account balances and driving invoice paid-status through events.

**Architecture:** Pure allocation/status rules in `treasury/domain/allocation.py`; `ReceiptService` and `DisbursementService` in `treasury/api/`; each posts account movements via `AccountMovementService` and publishes an event. Consumers: `finance/events/treasury_consumers.py` (sales invoices) and `procurement/events/treasury_consumers.py` (purchase invoices) apply allocation deltas. Cheque/draft payments are created here as *instruments in `pending`* but their collection lifecycle is B4.

## Decisions

1. A document (`receipts` / `disbursements`) has a header (partner, date, reason `full|advance`, `with_details` bool, note), `*_allocations` (invoice_id, amount) and `*_payments` (method `cash|cheque|draft|transfer|mobile_money`, amount, account_id, plus instrument fields). Sum of payments = document total; sum of allocations ≤ total; with_details=true requires allocations summing to the total, except `advance` (unallocated credit kept on the document).
2. Allocated amount per invoice may be less than the invoice remaining ("net to pay" editable) but never more (`OVER_ALLOCATION`); invoice must be `validated`/`issued`/`partially_paid` (`INVOICE_NOT_VALIDATED`); currency must match (`CURRENCY_MISMATCH`).
3. **Balance effects at posting:** cash, transfer and mobile_money move the chosen account immediately (receipt +, disbursement −). Cheques and drafts do **not** move any balance until collected/settled (B4 `treasury.instrument.collected`). This matches the manual's deposit-slip flow.
4. Cash limit: if `settings.cash_payment_limit` is set and a cash payment exceeds it, `CASH_LIMIT_EXCEEDED`. Null = no cap.
5. Cheque/draft payments require number, bank name, due date (`INSTRUMENT_FIELDS_REQUIRED`). Foreign-currency transfer payments are recorded in the account's currency; no conversion.
6. Invoice paid-status rule (shared pure function): `amount_paid = 0` → unchanged status; `0 < paid < amount` → `partially_paid`; `paid >= amount` → `paid`. Applies to both invoice kinds. The existing `finance.invoices` gets `amount_paid` and `partially_paid` here (migration `finance/0002_invoice_amount_paid.sql`); `mark_paid` is refused once a receipt allocation exists.
7. Prior-year invoices (invoice date in an earlier year than the document date) need `treasury.add_prior_year_invoice` (`PRIOR_YEAR_NOT_ALLOWED`); no hard-coded 16 March (spec "Not taken").
8. Cancelling a posted document is allowed only if none of its instruments is collected; it reverses account movements and publishes `.cancelled`. Posted documents are otherwise immutable; numbers `ENC-YYYY-000001` / `DEC-YYYY-000001` assigned at posting.

## Tasks

### Task 1 — Domain
- [ ] `domain/allocation.py` + `test_allocation.py`, failing tests first: sum rules (payments vs total, allocations vs total, advance), `OVER_ALLOCATION`, `derive_invoice_status(amount, amount_paid, current)`, cash-limit check, instrument field check, prior-year check. Implement; commit.

### Task 2 — Migrations
- [ ] `treasury/0002_treasury_receipts_disbursements.sql`: `receipts`, `receipt_allocations`, `receipt_payments`, `disbursements`, `disbursement_allocations`, `disbursement_payments`, `instruments` (id, tenant_id, direction `in|out`, method `cheque|draft`, number, bank_name, due_date, amount, currency, status `pending|collected|unpaid`, payment_id, account_id NULL, collected_at), `document_counters`. Money `NUMERIC(18,2)`; unique `(tenant_id, number)`.
- [ ] `finance/0002_finance_invoice_amount_paid.sql`: `ALTER TABLE finance.invoices ADD COLUMN amount_paid NUMERIC(18,2) NOT NULL DEFAULT 0`; add `finance.invoice_payment_deltas (event_type, document_id, invoice_id, amount, PRIMARY KEY (event_type, document_id, invoice_id))`. Same dedupe table for procurement in `procurement/0007_procurement_invoice_payment_deltas.sql`. Apply all; commit.

### Task 3 — Public invoice reads
- [ ] Add `InvoiceService.get_invoice(tenant_id, invoice_id)` (finance) returning `{id, partner_id, amount, amount_paid, remaining, currency, status, invoice_date}` and `apply_payment_delta` mirroring B1. Failing tests, implement, commit.

### Task 4 — Receipt service
- [ ] Failing integration tests: cash receipt moves the cash account and publishes `treasury.receipt.posted`; transfer to a bank account; mobile money to an operator account; cheque creates a `pending` instrument and moves nothing; mixed methods; with_details missing allocations refused; over-allocation refused; non-validated invoice refused; cash limit when configured; advance leaves credit; cancel reverses; cancel refused when an instrument is collected; permission checks.
- [ ] Implement `ReceiptService.create_and_post` (draft step omitted: documents post on creation, `draft` kept only if the plan reviewer wants it), `cancel`, `get`, `list`. Router `/treasury/receipts` (`manage_receipts`, view with `view`). Commit.

### Task 5 — Disbursement service
- [ ] Same test/implementation shape against purchase invoices, with `treasury.manage_disbursements`, plus "without details" free-form disbursements (partner + amount + reason + optional ledger account hint stored for B6) and a **payment order** record (`treasury.payment_orders (disbursement_id, number, status, notified_user_id, notified_at)`) with `POST /treasury/disbursements/{id}/payment-order` and `POST /treasury/payment-orders/{id}/notify` (writes a row to `treasury.user_notifications` surfaced by `GET /treasury/alerts`). Commit.

### Task 6 — Consumers
- [ ] `finance/events/treasury_consumers.py` and `procurement/events/treasury_consumers.py`: on `.posted` apply `+amount` per allocation, on `.cancelled` apply `−amount`, both guarded by the dedupe table and registry idempotency; re-derive status with the shared function. Import the consumer modules where the others are imported (see `finance/events/consumers.py` registration). Failing integration tests first, including replay-twice = applied once; update `module.json` `subscribes_events`; CATALOG.md rows. Commit.

### Task 7 — Frontend
- [ ] Receipts and Disbursements tabs/pages in `features/treasury/`: list with filters, create dialog (partner, invoices picker showing remaining, net-to-pay editable, multiple payment rows with method-specific fields, account select filtered by currency/kind), posted-document view, cancel, print view. Show invoice status badges updated on the sales/procurement pages (`partially_paid` added to the finance and purchase-invoice status filters and i18n). i18n en+fr; `npx tsc -b --force`. Commit.

### Task 8 — Handoff
- [ ] Run treasury + finance + procurement + core tests (report skips); manual walk: sales invoice issued → receipt partial → status `partially_paid` → second receipt → `paid`; same for a purchase invoice. Do not push.

## As built (2026-11-03)

- Receipts and disbursements share **one set of tables** (`treasury.documents` with `direction in|out`, `document_allocations`, `document_payments`, `instruments`, `document_counters`) instead of separate receipt/disbursement tables. The API still exposes `/treasury/receipts` and `/treasury/disbursements`.
- Documents post on creation (no draft step). Cancelling reverses account movements and publishes `.cancelled`.
- Consumers dedupe on `(event_type, document_id, invoice_id)` in `finance.invoice_payment_deltas` / `procurement.invoice_payment_deltas`.
- Added `GET /treasury/open-invoices?direction&partner_id` so the form does not need finance/procurement view permissions.
- Not built yet: payment orders and the notify-employee action (planned in Task 5), and print views (Task 7).
