# B4 — Cheque/draft lifecycle, due-date alerts and cash journal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or superpowers:executing-plans. Read `2026-11-03-treasury-interfaces.md` first. Needs B3.

**Goal:** Let users collect or reject pending cheques and drafts through deposit slips (bordereaux de versement), see due-date alerts, and read a cash journal.

**Architecture:** Pure lifecycle rules in `treasury/domain/instruments.py`; `DepositSlipService` and `AlertService` in `treasury/api/`; the cash journal is a **read model over `account_movements`** for accounts of kind `cash` (no separate table).

## Decisions

1. Deposit slip = a batch: `treasury.deposit_slips (id, number, account_id, slip_date, status draft|posted)` with `deposit_slip_items (slip_id, instrument_id, outcome collected|unpaid)`. Instrument starts `pending`; posting a slip sets each item's outcome.
2. `collected` (received instrument): credit the slip's account (+amount) via `AccountMovementService` and publish `treasury.instrument.collected`. Issued instruments (direction `out`) are settled the same way with a debit.
3. `unpaid` is **cheques only** (manual): it debits the account for the amount (bounced cheque), reopens the invoice allocation (publish `treasury.instrument.unpaid`; B3 consumers subtract the paid amount), and sets the instrument `unpaid`. A pending/collected draft cannot be marked unpaid (`INSTRUMENT_NOT_PENDING`/validation).
4. An `unpaid` outcome is only legal after a prior `collected` for that instrument **or** directly from `pending` for cheques the bank returned before crediting — the manual allows `pending → unpaid` with a debit; this plan keeps the manual's behaviour (debit on `unpaid`) and records `unpaid` from `pending` as a zero-balance-effect marker plus allocation reopening. **Flag for the client:** confirm whether `pending → unpaid` should debit; default here: debit only if the instrument was previously `collected`.
5. Alerts are computed on demand (see contract). `GET /treasury/alerts` returns, for users with `treasury.view`: instruments where `pending` and `today >= due_date + offset` (received) or `today >= due_date + offset` with negative offset for issued, using `alert_rules`; plus unread `user_notifications` (payment-order notify from B3). Each alert has `kind`, `instrument_id`/`payment_order_id`, `due_date`, `days_overdue`, `partner`, `amount`.
6. Cash journal columns: date, label (source document), in, out, running balance; filter by cash account and date range; export CSV (XLSX only if an export helper already exists — see the stock plan, Task 7).

## Tasks

### Task 1 — Domain
- [ ] `domain/instruments.py` + tests (failing first): allowed transitions (`pending→collected`, `pending→unpaid` cheque only, `collected→unpaid` cheque only), `alert_due(instrument, rule, today)` for all four rule rows incl. negative offsets, `days_overdue`. Implement; commit.

### Task 2 — Migration `treasury/0003_treasury_deposit_slips.sql`
- [ ] `deposit_slips`, `deposit_slip_items`, `user_notifications (id, tenant_id, user_id, kind, ref_id, message_en, message_fr, created_at, read_at)` if not already created in B3. Apply; commit.

### Task 3 — Deposit slip service and router
- [ ] Failing integration tests: slip with two cheques, one collected one unpaid → balances and statuses right; draft marked unpaid refused; double posting refused; collected cheque twice refused; events published; account currency must match instrument currency; permission `collect_instruments`.
- [ ] Implement `DepositSlipService` (`create_draft`, `add_items`, `post`, `get`, `list`); router `/treasury/deposit-slips`, `/treasury/instruments` (list with status/direction/due filters). Commit.

### Task 4 — Alerts and journal
- [ ] Failing tests for `AlertService.compute(tenant_id, user_id, today)` (windows per rule, collected instruments excluded, payment-order notifications included) and `CashJournalService.entries(account_id, date_from, date_to)` with running balance.
- [ ] Implement; router `GET /treasury/alerts`, `POST /treasury/alerts/{id}/read` (notifications), `GET /treasury/journals/cash`. Commit.

### Task 5 — Frontend
- [ ] Instruments tab (filters, status badges, overdue highlight), Deposit slips tab with a "select pending instruments → collect / mark unpaid" flow (unpaid only offered for cheques), Cash journal tab with date/account filter and export. Layout-level alert banner: call `GET /treasury/alerts` on mount for users with `treasury.view`, show a dismissible summary with a link to Instruments. i18n en+fr; `npx tsc -b --force`. Commit.

### Task 6 — Handoff
- [ ] Run treasury tests (report skips); walk: receipt by cheque → alert on due date → deposit slip collected → bank balance up → cheque marked unpaid → invoice status reverts. Do not push.
