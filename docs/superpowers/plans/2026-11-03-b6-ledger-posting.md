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

- **Switch:** treasury setting `ledger_posting_enabled` (boolean, default false; `PUT /treasury/settings/ledger_posting_enabled`, which requires the dedicated `treasury.admin_ledger_posting`; other settings keep `treasury.admin_config`). While off, the consumers skip treasury events: no entry and no `posting_failures` row. Events skipped while it was off are not queued; turning it on later needs a backfill of earlier documents (not written).
- **Files:** `finance/domain/treasury_posting.py` (pure rules), `finance/api/treasury_ledger_service.py`, treasury sources in `finance/api/ledger_event_postings.py` (`SOURCES`, `_post_treasury`; retry of a refused posting works unchanged), the gate in `finance/events/ledger_consumers.py`, `treasury` added to the rule kinds in `finance/domain/posting.py`, and `TreasuryPostingService.ledger_posting_enabled` / `account_ledger_code`.
- **No account numbers in code, and no seeded rules.** The money side of a payment is the `ledger_account_code` of the treasury account that moved; everything else comes from `finance.posting_rules` with `source = 'treasury'`. A missing rule, an incomplete rule or an account without a ledger code is refused (`POSTING_RULE_MISSING`, `LEDGER_ACCOUNT_MISSING`) and recorded in `posting_failures`; closed periods are refused by the ledger as for invoices.
- **Rule shapes** (code = payment method, `in`/`out` for instrument kinds, or `*`): `receipt_payment` (credit = customer account; debit = holding account for a cheque/draft still in no account), `disbursement_payment` (debit = supplier account; credit = holding), `receipt_advance` / `disbursement_advance` (self-contained, the part tied to no invoice), `instrument_collected` (holding against the slip account), `instrument_unpaid` (self-contained, puts the debt back). Each names its journal.
- **Entries:** one per payment method (`receipt_payment_<method>`) plus `..._advance`, idempotent on `(treasury, document_id, source_kind)`. Cancelling a document reverses its entries; a bounced instrument reverses its collection entry and posts `instrument_unpaid`.
- **Current status wins over the event:** a receipt or disbursement that is no longer `posted`, or an instrument that is no longer `collected`, posts nothing, and the delivery or retry resolves its failure. So a refused posting followed by a cancellation or a bounce cannot post late. Until it is retried, the failure stays open even though nothing remains to post.
- **Cancelling after processing:** treasury refuses to cancel a document whose cheque or draft was collected or rejected (`INSTRUMENT_ALREADY_PROCESSED`), so the ledger never has to undo that case. A correction there is a manual entry.
- **Bounce before collection:** a cheque rejected while still pending moves no treasury balance, but the ledger still posts `instrument_unpaid` (customer against holding on a receipt, holding against supplier on a disbursement). The client decided (2026-11-03) to keep this entry and record the bank's charge separately.
- **Rejection fee:** marking a cheque unpaid can carry what the bank charged and the account it came out of (`mark_unpaid`, pending or collected). The fee goes through `AccountMovementService`, so it shows in the journals with source type `instrument_rejection_fee`, and it is stored on the instrument. In the ledger it is a separate entry of kind `instrument_rejection_fee`: debit from the rule, credit the ledger code of the account charged, idempotent, and refused like any other posting if the rule or code is missing (the unpaid entry is then refused with it, and a retry posts both). A rejection through a deposit slip carries no fee.
- **Bounce of an advance (accountant to decide):** `instrument_unpaid` always uses its rule's accounts. If the bounced cheque paid an advance, the customer account is debited while the advance account keeps its credit: balanced, but both are overstated until someone clears them.
- **No-details documents:** a document saved without invoice details has its whole amount unallocated, so it is booked by the advance rule even if it is not really an advance.
- **XOF and whole francs only (client decision, 2026-11-03):** treasury refuses any other currency and any fractional amount before a document exists (`TREASURY_CURRENCY_NOT_XOF`, `AMOUNT_NOT_WHOLE`), so the ledger's `CURRENCY_NOT_XOF` and whole-franc refusals remain only as safety nets. An invoice in another currency cannot be settled through treasury (`INVOICE_CURRENCY_NOT_XOF`).
- **Invoices with cents:** payments are whole francs, so a remainder under one franc counts as settled. An invoice of 1000.50 is `paid` after 1000, with `amount_paid` 1000. The ledger rounds the invoice half up to 1001 (`to_xof`), so when posting is on, 411 keeps 1 franc on that customer; 1000.40 rounds to 1000 and leaves nothing.
- **Retry respects the switch:** with `ledger_posting_enabled` off, retrying a treasury failure is refused with `LEDGER_POSTING_DISABLED` (409) and the failure stays open, so "off" means no entries at all. Payroll and invoice failures are not affected.
- **Not built:** account-to-account transfers (treasury has no such feature and no event), the backfill script, and the "posted / not posted + retry" display on the receipt and disbursement pages. The existing posting-failures screen and retry endpoint already cover refusals.
- **For the accountant:** confirm the accounts for each rule listed above, including `instrument_rejection_fee` (the bank-charges account; the seeded chart's fee account is unconfirmed) (the plan's suggestions: 411, 401, 413 / 4021 holding, 4191 / 4091 advances, journals BNQ / CAI / OD), set `ledger_account_code` on every treasury account (each mobile-money operator its own 5xx), decide how to clear the residual of up to 1 franc left on 411/401 by an invoice with cents, and decide whether the invoice-paid entry (generic bank account) must be switched off for treasury-settled invoices (it already never fires for them). Then turn the switch on.

### Added for the manual's requirements (2026-11-04)

- **Payments waiting on the deposit slip:** with `receipts_collect_on_slip` on (the default), cash, transfers and mobile money on a receipt wait like a cheque. `document_lines` reports them with no account, so `receipt_payment` debits its holding account and `instrument_collected` later moves it to the account's ledger code. Each method therefore needs a holding account in its `receipt_payment` rule and an `instrument_collected` rule, or the posting is refused and recorded.
- **Withheld amount:** a new rule kind per direction, `receipt_withheld` (debit = withheld-tax receivable, credit = customer account) and `disbursement_withheld` (debit = supplier account, credit = withheld-tax payable). A document with a withheld amount and no such rule is refused and recorded. Cancelling reverses it with the other entries.
- **For the accountant:** confirm the holding account for cash, transfers and mobile money, and the two withheld accounts.

### First end-to-end run with posting on (2026-11-05)

Run on a scratch database with placeholder accounts; every entry balanced, replays added nothing, the trial balance netted to zero and 401, 411, 521, 552 and 571 matched the invoices and the treasury accounts. What changed:

- **Holding accounts:** `instrument_collected` and `instrument_unpaid` take the holding account from the payment's own `receipt_payment` / `disbursement_payment` rule (the account the payment was parked on), not from their own rule. Before, a cash payment parked on one holding account and collected against another left both wrong.
- **Collections post in the journal of the account they land in:** an `instrument_collected` rule may be written for an account kind (`bank`, `cash`, `mobile_money`) and then needs only a journal (migration `finance/0006` allows a journal-only collection rule); it wins over the `in`/`out` rule. Labels follow the method: "Versement espèces", "Virement reçu", "Encaissement chèque", "Chèque impayé"…
- **Opening balances (`account_opening`):** switching posting on posts each treasury account's current balance, dated that day, against the rule's credit account (code = account kind or `*`); an account created while posting is on is opened at once. One entry per account, never twice. All or nothing: a missing rule, an account with no ledger code or a closed period refuses the switch (`LEDGER_OPENING_REFUSED`) and posting stays off. While posting is on, an account with no ledger code cannot be created and an opening balance cannot be changed (correct it with a ledger entry).
- **Purchase invoices (`purchase_invoice / validated`, code `*`):** a validated purchase invoice debits the purchase account and credits the supplier (with the partner), in the rule's journal; cancelling a validated invoice reverses it (new event `procurement.purchase_invoice.cancelled`). Like sales invoices, this is always on, not behind the treasury switch; refusals go to `posting_failures` and can be retried, and a retry skips an invoice cancelled since. Seeded default (`to_confirm`): debit 601, credit 401, journal ACH; existing tenants get it by running the ledger setup again (`POST /finance/setup`).
- **Not handled:** documents recorded while posting was off are not backfilled. Switching on posts the accounts' current balances, so 521/571/552 are right, but earlier receipts never cleared 411 in the ledger, and payments still waiting on the slip at switch-on will credit a holding account that was never debited. Switch on before the first real document, or plan a backfill.
- **For the accountant, in addition:** the opening (à-nouveaux) account and journal for `account_opening` (the run used 471 / OD as placeholders); the purchase account for `purchase_invoice / validated` (601 seeded; 602 if purchases are mostly raw materials, and VAT 445 is not split out because the purchase invoice carries no VAT); and the journal of collections into a cash register (an `instrument_collected` rule with code `cash`).

### Complete purchase invoice (2026-11-05)

- **VAT is now split out.** A purchase invoice carries priced lines with a discount and a VAT rate (tenant default 18 %, `procurement.invoice_settings`), so `procurement.purchase_invoice.validated` (version 1.1) carries `total_vat` and the excluding-tax value per product. The entry is: purchases excluding tax on the debit, the deductible VAT on the debit, the supplier for the total including tax on the credit. A 1.0 event (no VAT) still posts as before.
- **New rule kind `purchase_invoice / vat` (code `*`):** names only the deductible VAT account on the debit. Seeded (`to_confirm`) to **445** "État, TVA récupérable". SYSCOHADA's finer 4452 "TVA récupérable sur achats" is not seeded: 445 is a posting account in the seeded chart and the chart refuses a child under a posting account, so using 4452 means the accountant turns 445 into a heading first. Without the rule, an invoice with VAT is refused into `posting_failures` (`POSTING_RULE_MISSING`) and can be retried once it exists.
- **Purchase account per product:** a line whose product has `accounting_code_purchase` set posts its excluding-tax value there; the other lines go to the `validated` rule's debit account (601 seeded). Whole francs per account; the rounding gap lands on the largest.
- **Supplier credit notes:** new event `procurement.purchase_credit_note.validated` posts the mirror (supplier debited, purchases and VAT credited) in the same journal, source kind `purchase_credit_note_validated`, idempotent. A validated credit note is final, so there is no reversal.
- **For the accountant, in addition:** confirm 445 (or create 4452) for deductible VAT, the purchase account per product family (fill `accounting_code_purchase` on products where 601 is wrong, e.g. 602 for raw materials, 608 for packaging), and whether credit notes should go to a separate journal.
