# B6 — Treasury ledger posting (blocked on HR/finance Phase 4) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or superpowers:executing-plans. Read `2026-11-03-treasury-interfaces.md` first. **Do not start until `2026-09-25-hr-p4-finance-ledger.md` is merged** (it provides `finance.journal_entries`, posting rules, `LedgerPostingService`, `PERIOD_CLOSED`).

**Goal:** Post treasury activity into the SYSCOHADA ledger from events, completing confirmed decision 6 ("record now, post later").

**Architecture:** Consumers in `modules/finance/events/treasury_ledger_consumers.py` (finance owns the ledger) call Phase 4's `LedgerPostingService`; they read treasury data only through a new public `TreasuryPostingService` (`modules/treasury/api/posting_service.py`) returning plain dicts, imported lazily — the same pattern Phase 4 uses for payroll. Failures use Phase 4's `finance.posting_failures` + retry mechanism.

## Decisions

1. **Journals:** bank movements → `BNQ`; cash → `CAI`; mobile money → `BNQ` (own 5xx account). Posting-rule keys extend Phase 4's `(source, source_kind, code)`: `source='treasury'`, `source_kind` in `receipt_payment|disbursement_payment|instrument_collected|instrument_unpaid`, `code` = method; all seeded `to_confirm`.
2. **Entries (defaults, to be confirmed by the accountant):**
   - Receipt payment by cash/transfer/mobile money: debit account's `ledger_account_code` (571 / 521 / the operator's 5xx), credit **411** with `partner_id`.
   - Cheque/draft received: at receipt, debit **413** (effets à recevoir) / **5113**-style "effets à l'encaissement" per accountant, credit 411; at `collected`, debit the bank account, credit that holding account; at `unpaid`, reverse.
   - Disbursement payment: debit **401** with `partner_id`, credit the account's ledger code; issued cheque/draft use **4021** (effets à payer) until settled.
   - Advances (unallocated receipts): credit **4191** (clients, avances reçues); disbursement advances debit **4091**.
   The account numbers above are SYSCOHADA-based suggestions, not facts to hard-code: they live only in `finance.posting_rules`, and posting refuses with `RULE_MISSING` if a rule is absent or an account has no `ledger_account_code`.
3. **Idempotency:** unique on `(source_module='treasury', source_id=<payment/instrument id>, source_kind)`; cancellations post a reversal entry (Phase 4's reversal path), never an edit.
4. **Period closed / missing:** refused with `PERIOD_CLOSED`/`PERIOD_MISSING`, recorded in `posting_failures`, visible on the receipt/disbursement page as "not posted" with the reason and a retry button (`finance.manage_entries` required for retry).
5. **Backfill:** a one-off command `python -m scripts.backfill_treasury_ledger --from YYYY-MM-DD` replays existing posted documents (dry-run by default, prints counts, `--apply` to write). Needed because treasury goes live before the ledger.

## Tasks

### Task 1 — Public read service
- [ ] `treasury/api/posting_service.py` `TreasuryPostingService.payment_lines(tenant_id, document_type, document_id)` and `.instrument_lines(tenant_id, instrument_id)` returning `{kind, method, amount, currency, account_ledger_code, partner_id, date}`. Failing tests first; implement; commit.

### Task 2 — Rule seed
- [ ] Seed `finance.posting_rules` for `source='treasury'` (migration or seed script following how Phase 4 seeds payroll rules), status `to_confirm`, with the defaults in Decision 2. Commit.

### Task 3 — Consumers
- [ ] Failing integration tests (`finance/events/test_treasury_ledger_integration.py`): each event type produces a balanced entry with the right journal and partner; replay twice → one entry; missing rule/ledger code → failure row, event dead-letters; closed period → failure row; cancellation → reversal entry; unpaid → reversal of the collected entry.
- [ ] Implement consumers for `treasury.receipt.posted/cancelled`, `treasury.disbursement.posted/cancelled`, `treasury.instrument.collected/unpaid`; `module.json` `subscribes_events`; CATALOG.md subscriber notes. Commit.

### Task 4 — UI surface and backfill
- [ ] Show "posted / not posted + reason + retry" on the receipt and disbursement detail views (reuse Phase 4's ledger-source lookup `GET /finance/ledger/sources/{source_module}/{source_id}`); i18n en+fr. Write the backfill script with dry-run default and a test using the `db` fixture. `npx tsc -b --force`; commit.

### Task 5 — Handoff
- [ ] Run finance + treasury tests (report skips). Ask the accountant to confirm every `to_confirm` rule before first real posting. Do not push.

## As built (2026-11-03, after the merge with the remote ledger)

Implemented on top of the remote's ledger, behind a switch that is **off by default**.

- **Switch:** treasury setting `ledger_posting_enabled` (boolean, default false; `PUT /treasury/settings/ledger_posting_enabled`). While off, the consumers skip treasury events: no entry and no `posting_failures` row. Events skipped while it was off are not queued; turning it on later needs a backfill of earlier documents (not written).
- **Files:** `finance/domain/treasury_posting.py` (pure rules), `finance/api/treasury_ledger_service.py`, treasury sources in `finance/api/ledger_event_postings.py` (`SOURCES`, `_post_treasury`; retry of a refused posting works unchanged), the gate in `finance/events/ledger_consumers.py`, `treasury` added to the rule kinds in `finance/domain/posting.py`, and `TreasuryPostingService.ledger_posting_enabled` / `account_ledger_code`.
- **No account numbers in code, and no seeded rules.** The money side of a payment is the `ledger_account_code` of the treasury account that moved; everything else comes from `finance.posting_rules` with `source = 'treasury'`. A missing rule, an incomplete rule or an account without a ledger code is refused (`POSTING_RULE_MISSING`, `LEDGER_ACCOUNT_MISSING`) and recorded in `posting_failures`; closed periods are refused by the ledger as for invoices.
- **Rule shapes** (code = payment method, `in`/`out` for instrument kinds, or `*`): `receipt_payment` (credit = customer account; debit = holding account for a cheque/draft still in no account), `disbursement_payment` (debit = supplier account; credit = holding), `receipt_advance` / `disbursement_advance` (self-contained, the part tied to no invoice), `instrument_collected` (holding against the slip account), `instrument_unpaid` (self-contained, puts the debt back). Each names its journal.
- **Entries:** one per payment method (`receipt_payment_<method>`) plus `..._advance`, idempotent on `(treasury, document_id, source_kind)`. Cancelling a document reverses its entries; a bounced instrument reverses its collection entry and posts `instrument_unpaid`.
- **Not built:** account-to-account transfers (treasury has no such feature and no event), the backfill script, and the "posted / not posted + retry" display on the receipt and disbursement pages. The existing posting-failures screen and retry endpoint already cover refusals.
- **For the accountant:** confirm the accounts for each rule listed above (the plan's suggestions: 411, 401, 413 / 4021 holding, 4191 / 4091 advances, journals BNQ / CAI / OD), set `ledger_account_code` on every treasury account (each mobile-money operator its own 5xx), decide whether a cheque rejected before the bank credited it needs an entry, and decide whether the invoice-paid entry (generic bank account) must be switched off for treasury-settled invoices (it already never fires for them). Then turn the switch on.
