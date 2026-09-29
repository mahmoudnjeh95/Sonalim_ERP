# Phase 4 — Finance ledger (SYSCOHADA) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the `finance` module a SYSCOHADA general ledger (chart, journals, fiscal years and monthly periods, balanced immutable entries, posting rules), post payroll runs and invoices into it from events, and show it on six new Finance screens plus a "posted / not posted" line on the payroll run page.

**Architecture:** Pure domain code (`modules/finance/domain/ledger.py`, `posting.py`, `syscohada_chart.py`) decides what a valid entry is and how a payroll line or an invoice maps to accounts; services in `modules/finance/api/` write entries through one path (`LedgerPostingService`: check → insert draft → post → outbox event → audit). Event consumers (`modules/finance/events/ledger_consumers.py`) call payroll's public `PayrollPostingService` (never payroll tables), are idempotent on `event_id` (registry) and on `(source_module, source_id, source_kind)` (unique index), and on a refusal record the reason in `finance.posting_failures` in their own committed transaction before raising (so the message dead-letters and the run page can show why). PostgreSQL triggers make posted entries immutable and a deferred constraint trigger re-checks the balance at commit.

**Tech Stack:** FastAPI, raw SQL with psycopg 3, PL/pgSQL triggers, pytest; React 18 + TypeScript, TanStack Query, React Hook Form + Zod, Tailwind, lucide-react, sonner.

**Spec:** `docs/superpowers/specs/2026-09-25-hr-payroll-finance-design.md` (section "Phase 4 — Finance ledger") and the cross-phase contract `docs/superpowers/plans/2026-09-25-hr-payroll-finance-interfaces.md`. Phases 1–3 are assumed merged.

## Global Constraints

- Money columns are `NUMERIC(18,0)` in XOF (no sub-unit); Python uses `decimal.Decimal`, never `float`; the HTTP API returns whole francs as JSON integers. The UI shows the currency as "F CFA".
- A "period" is a `datetime.date` equal to the first day of the month. A fiscal year is a calendar year with 12 monthly periods.
- Finance migrations use numbers `0002_*` and up (`0002_finance_ledger_master_data.sql`, `0003_finance_journal_entries.sql`). Never edit an applied migration. After adding one, apply it before running integration tests — from `backend/`: `.venv/Scripts/python -c "from dotenv import load_dotenv; load_dotenv('../.env'); from core.migrations.runner import apply_all_migrations; apply_all_migrations()"`.
- Finance reads payroll **only** through `modules/payroll/api/posting_service.py` → `PayrollPostingService(connection).posting_lines(*, tenant_id, run_id)` / `.payment_lines(*, tenant_id, run_id)`, imported lazily (payroll is an `optional_depends` of finance). `posting_lines` dicts: `source_kind` in `earning|deduction|employee_contribution|employer_contribution|employer_charge|tax|net`, `code`, `amount: Decimal` (positive), `employee_id`. `payment_lines` dicts: `method` in `bank|mobile_money|cash`, `amount: Decimal`, `employee_id`.
- Consumed events (payloads exactly): `payroll.run.approved {run_id, period, run_type}`, `payroll.run.paid {run_id, period}`, `payroll.run.reversed {run_id, period}`, `finance.invoice.issued` / `finance.invoice.paid {invoice_id, partner_id, amount, currency}`. Published: `finance.journal_entry.posted {entry_id, journal_code, source_module, source_id}`.
- Posting-rule keys are `(source, source_kind, code)`; payroll rules use `source='payroll'` and a fallback row with `code='*'` for each `source_kind`. Seeded rules have `status='to_confirm'` until the accountant confirms them.
- `LedgerQueryService.entries_for_source(*, tenant_id, source_module, source_id) -> list[dict]` is the public read the payroll run page uses (through `GET /finance/ledger/sources/{source_module}/{source_id}`).
- New permission codes, exactly: `finance.view_ledger`, `finance.manage_entries`, `finance.admin_entries`, `finance.manage_accounts`, `finance.admin_accounts`, `finance.admin_periods`, `finance.manage_posting_rules` (existing `finance.*_invoices` stay).
- Frontend routes, exactly: `/finance/accounts`, `/finance/entries`, `/finance/trial-balance`, `/finance/ledger`, `/finance/periods`, `/finance/posting-rules`, all in `frontend/src/features/finance/`.
- Every `Err(...)` carries its French as the third argument; every `HTTPException` detail is `err_detail(err)` or a dict with `message_fr` (`core/test_error_translations.py` fails otherwise).
- Every mutation calls `record_audit()` in the same transaction; routers pass `actor_id=tenant.user_id`; automatic postings use the actor `"system:event-consumer"` (the existing convention in `InvoiceService`).
- **Posted entries are never edited**, not even with `finance.admin_entries`: the spec's immutability wins over the platform "edit at any status" rule. `PATCH /finance/entries/{id}` works on drafts only (`ENTRY_POSTED` otherwise); a posted entry is corrected by reversal.
- Every user-facing string goes through `useI18n()` with the key added to **both** `en` and `fr` in `frontend/src/lib/i18n.tsx`. Add new keys at the end of the `en` object (just before its closing `} as const;`) and at the end of the `fr` object (just before the `};` that precedes `const dictionaries`).
- Every list uses `FilterTabs` + `ColumnFilterRow` + `useTableColumns` (through the `LedgerTable` wrapper of Task 11); server state through TanStack Query; one branded loader per screen (secondary blocks use `Skeleton`).
- Tests: domain tests (`*/domain/test_*.py`) need no DB; integration tests end in `_integration.py`, use the `db` fixture and **skip** without a DB — a green run with skips tested nothing, so read the skip count. Run from `backend/`: `.venv/Scripts/python -m pytest <path> -q`. Frontend check from `frontend/`: `npx tsc -b --force`.
- Shared working tree: never `git stash`; `git add` only the files the task lists. Every commit message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Do not push.

## Decisions this plan makes where the spec is silent

1. **Fiscal years are opened explicitly** (`POST /finance/fiscal-years {year}` creates the year and its 12 open periods). Posting to a date with no period is refused with `PERIOD_MISSING` (new code), distinct from `PERIOD_CLOSED`.
2. **Dead-letter with a readable reason:** a refused automatic posting is upserted into `finance.posting_failures` (one row per `(source_module, source_id, source_kind)`, carrying the event envelope and the bilingual error) in its own committed transaction; then the handler raises so the registry nacks → DLQ. `POST /finance/posting-failures/{id}/retry` replays the stored envelope once the cause is fixed (period reopened, rule added). A successful posting resolves the row; a run reversal cancels the run's open failures.
3. **A payment cannot post before its run:** `payroll.run.paid` is refused with `RUN_NOT_POSTED` (new code) while the run's PAIE entry does not exist (e.g. the approval was refused for a closed period), so 422 is never debited without its credit.
4. **Journals on rules:** `finance.posting_rules.journal_code` names the journal for self-contained rules (payroll `payment` rules, invoice `issued`/`paid` rules). A run's entry always goes to `PAIE`; manual entries default to `OD`.
5. **Default mapping gaps filled (all `to_confirm`):** employer charges credit **442** (État, autres impôts et taxes) — the spec gives only the debit 641; mobile money pays out of **552** (SYSCOHADA revised class 55 "instruments de monnaie électronique", sub-account "téléphone portable"); **585** (Virements de fonds) is seeded in the chart but not used by default. Every contribution goes to 431 through the `'*'` rule; AMO → 433 needs code rows because contribution codes belong to phase 3 — the seed script (Task 15) adds them for the AMO codes the seeded run actually uses and prints them.
6. **Invoices:** the existing invoices carry no VAT, so no 443 line is written (443 is in the chart for later). Issued → VTE 411/702, paid → BNQ 521/411, dated by the event's `occurred_at`. Non-XOF invoices are refused with `CURRENCY_NOT_XOF` (multi-currency is out of scope); amounts are rounded half-up to whole francs. Like payroll, a payment whose invoice entry is missing is refused (`INVOICE_NOT_POSTED`, new code) instead of crediting 411 alone.
7. **Ledger labels are French** ("Paie 01/2030", "Extourne de PAIE-2030-000001"): they are the books' content, kept in the legal language, not UI strings. Account and journal names are French SYSCOHADA data.
8. **Per-employee detail on 422** (`employee_ref`) is optional in the spec and not written; the column exists for later.
9. **Posting-rule edits** are gated by `finance.manage_posting_rules` (the spec lists no `admin_posting_rules`); any edit sends the rule back to `to_confirm`.
10. **Journal listing** = `GET /finance/entries?journal_code=&date_from=&date_to=` (the Entries screen filtered by journal, with totals); no separate endpoint.
11. The run page's posting status endpoint accepts `finance.view_ledger` **or** `payroll.view_runs`, so a payroll officer sees it without ledger access.

New error codes beyond the spec's list: `NOT_FOUND`, `INVALID_ENTRY`, `INVALID_ENTRY_LINE`, `INVALID_ACCOUNT`, `ACCOUNT_EXISTS`, `INVALID_POSTING_RULE`, `POSTING_RULE_EXISTS`, `INVALID_PERIOD`, `PERIOD_MISSING`, `FISCAL_YEAR_EXISTS`, `INVALID_TRANSITION`, `ENTRY_POSTED`, `CURRENCY_NOT_XOF`, `RUN_NOT_POSTED`, `INVOICE_NOT_POSTED`.

## Review Focus

1. **Payment event processed while the run's PAIE entry is missing** (approval dead-lettered for a closed period, then the payout is confirmed in the next month): expected a refusal `RUN_NOT_POSTED` recorded on the run page, never a lone 422 debit; after the run is retried, retrying the payment posts it. Pinned in Task 5 (`test_a_payment_before_its_run_is_refused_until_the_run_posts`).
2. **The same refused event delivered again after it was fixed and retried** (a DLQ replay after the retry button): expected no second entry and the failure staying resolved. Pinned in Task 5 (`test_a_closed_period_dead_letters_then_retry_posts_once`).
3. **A run reversed while its approval posting is still refused:** expected nothing to reverse, the open failure cancelled (a later retry must not post a reversed run). Pinned in Task 5 (`test_reversing_a_run_whose_posting_failed_cancels_the_failure`).
4. **A draft left in a month that is then closed:** expected `PERIOD_CLOSED` on post, the draft untouched, and posting working again after reopening. Pinned in Task 8 (`test_a_draft_in_a_period_closed_later_cannot_be_posted_until_reopened`).
5. **An account made non-postable after the default rules point at it** (the accountant splits 661 into sub-accounts): expected the payroll posting refused with `ACCOUNT_NOT_POSTABLE` and recorded as a failure, not a database error. Pinned in Task 5 (`test_a_rule_pointing_at_a_heading_account_is_refused_and_recorded`).

---

## File structure

Backend (`backend/`):

| File | Responsibility |
|---|---|
| `modules/finance/domain/ledger.py` (create) | `Account`, `EntryLine`, `SourceRef`; line validation, balanced-entry builder, reversal, balance split, account validation |
| `modules/finance/domain/posting.py` (create) | `PostingRule`, `PaymentEntry`; rule resolution with `'*'` fallback, payroll run/payment mapping, invoice mapping, XOF conversion, rule validation |
| `modules/finance/domain/syscohada_chart.py` (create) | Seed data: chart, journals, default posting rules |
| `modules/finance/migrations/0002_finance_ledger_master_data.sql` (create) | accounts, journals, fiscal_years, periods, posting_rules |
| `modules/finance/migrations/0003_finance_journal_entries.sql` (create) | journal_entries, journal_lines, posting_failures, immutability + deferred balance triggers |
| `modules/finance/api/chart_setup_service.py` (create) | `ChartSetupService.ensure_defaults` |
| `modules/finance/api/period_service.py` (create) | `PeriodService`: open year, list, close, reopen, `ensure_open` |
| `modules/finance/api/ledger_sql.py` (create) | Shared entry SELECT and row→dict |
| `modules/finance/api/ledger_posting_service.py` (create) | `LedgerPostingService`: the single write path |
| `modules/finance/api/posting_rule_service.py` (create, extended in Task 7) | `PostingRuleService` |
| `modules/finance/api/posting_failure_service.py` (create) | `PostingFailureService` |
| `modules/finance/api/payroll_ledger_service.py` (create) | `PayrollLedgerService`: run / payment / reversal postings |
| `modules/finance/api/invoice_ledger_service.py` (create) | `InvoiceLedgerService`: issued / paid postings |
| `modules/finance/api/ledger_event_postings.py` (create) | event → posting dispatch, `retry_failure` |
| `modules/finance/events/ledger_consumers.py` (create) | registry handlers |
| `modules/finance/api/account_service.py` (create) | `AccountService` (accounts + journals) |
| `modules/finance/api/manual_entry_service.py` (create) | `ManualEntryService` (OD drafts) |
| `modules/finance/api/ledger_query_service.py` (create) | `LedgerQueryService` |
| `modules/finance/api/ledger_report_service.py` (create) | `LedgerReportService` |
| `modules/finance/api/ledger_router.py` (create) | every `/finance/...` ledger endpoint |
| `modules/finance/testing_support.py` (create) | `NoCommitConnection` for tests |
| `modules/finance/conftest.py` (create) | `ledger` fixture |
| `modules/finance/module.json`, `app/main.py`, `worker/main.py`, `events/CATALOG.md` (modify) | wiring |
| `scripts/seed_finance_ledger.py` (create) | demo ledger + posting of the seeded payroll run |

Frontend (`frontend/src/`):

| File | Responsibility |
|---|---|
| `features/finance/ledgerApi.ts` | types, query keys, fetchers |
| `features/finance/ledgerFormat.ts` | F CFA / date / period formatting, error text |
| `features/finance/LedgerTable.tsx` | table wrapper over `useTableColumns` + `ColumnFilterRow` + filter-cell helpers |
| `features/finance/AccountsPage.tsx`, `PostingRulesPage.tsx`, `EntriesPage.tsx`, `TrialBalancePage.tsx`, `GeneralLedgerPage.tsx`, `PeriodsPage.tsx` | the six screens |
| `features/finance/LedgerPostingStatus.tsx` | posted / not posted block for the payroll run page |
| `routes/router.tsx`, `routes/Sidebar.tsx`, `lib/i18n.tsx` (modify) | routes, nav, strings |
| the payroll run page (phase 3, route `/payroll/runs/:id`) (modify) | render `LedgerPostingStatus` |

---

### Task 1: Balanced-entry builder (pure domain)

**Files:**
- Create: `backend/modules/finance/domain/ledger.py`
- Test: `backend/modules/finance/domain/test_ledger.py`

**Interfaces:**
- Consumes: `core.domain.result.Err`, `Ok`, `Result`.
- Produces (used by every later backend task):
  - `ZERO: Decimal`, `ACCOUNT_TYPES: tuple[str, ...]`
  - `@dataclass(frozen=True) Account(code: str, name: str, class_no: int, account_type: str, is_postable: bool, parent_code: str | None = None)` — field order matches the SQL `SELECT code, name, class_no, account_type, is_postable, parent_code`.
  - `@dataclass(frozen=True) EntryLine(account_code: str, debit: Decimal = ZERO, credit: Decimal = ZERO, label: str | None = None, partner_id: str | None = None, employee_ref: str | None = None)` — field order matches `SELECT account_code, debit, credit, label, partner_id, employee_ref`.
  - `@dataclass(frozen=True) SourceRef(module: str, id: str, kind: str)`
  - `validate_lines(lines, accounts: Mapping[str, Account]) -> Result[list[EntryLine]]` (no balance check; codes `INVALID_ENTRY_LINE`, `ACCOUNT_NOT_POSTABLE`)
  - `build_entry(lines, accounts) -> Result[list[EntryLine]]` (adds `ENTRY_UNBALANCED`)
  - `totals(lines) -> tuple[Decimal, Decimal]`, `reverse_lines(lines) -> list[EntryLine]`, `split_balance(net: Decimal) -> tuple[Decimal, Decimal]`
  - `validate_account(account: Account, parent: Account | None) -> Result[Account]` (`INVALID_ACCOUNT`)

- [ ] **Step 1: Write the failing test**

`backend/modules/finance/domain/test_ledger.py`:

```python
"""The balanced-entry builder: what the ledger accepts as an entry, with no database."""
from decimal import Decimal

from core.domain.result import Err, Ok
from modules.finance.domain.ledger import (
    Account,
    EntryLine,
    build_entry,
    reverse_lines,
    split_balance,
    totals,
    validate_account,
    validate_lines,
)

D = Decimal
ACCOUNTS = {
    "42": Account("42", "Personnel", 4, "liability", False, "4"),
    "422": Account("422", "Personnel, rémunérations dues", 4, "liability", True, "42"),
    "661": Account("661", "Rémunérations directes versées au personnel national", 6, "expense", True, "66"),
}


def _code(result) -> str:
    assert isinstance(result, Err), result
    return result.code


def test_a_balanced_entry_builds():
    result = build_entry([EntryLine("661", debit=D(320000)), EntryLine("422", credit=D(320000))], ACCOUNTS)
    assert isinstance(result, Ok)
    assert totals(result.value) == (D(320000), D(320000))


def test_unequal_sides_are_refused():
    lines = [EntryLine("661", debit=D(100)), EntryLine("422", credit=D(90))]
    assert _code(build_entry(lines, ACCOUNTS)) == "ENTRY_UNBALANCED"


def test_an_entry_needs_a_line_on_each_side():
    assert _code(build_entry([EntryLine("661", debit=D(100))], ACCOUNTS)) == "ENTRY_UNBALANCED"
    assert _code(build_entry([], ACCOUNTS)) == "ENTRY_UNBALANCED"


def test_a_heading_account_cannot_be_posted_to():
    lines = [EntryLine("42", debit=D(5)), EntryLine("422", credit=D(5))]
    assert _code(build_entry(lines, ACCOUNTS)) == "ACCOUNT_NOT_POSTABLE"


def test_an_unknown_account_cannot_be_posted_to():
    lines = [EntryLine("999", debit=D(5)), EntryLine("422", credit=D(5))]
    assert _code(build_entry(lines, ACCOUNTS)) == "ACCOUNT_NOT_POSTABLE"


def test_a_line_carries_exactly_one_side():
    assert _code(validate_lines([EntryLine("661", debit=D(5), credit=D(5))], ACCOUNTS)) == "INVALID_ENTRY_LINE"
    assert _code(validate_lines([EntryLine("661")], ACCOUNTS)) == "INVALID_ENTRY_LINE"


def test_amounts_are_whole_non_negative_francs():
    assert _code(validate_lines([EntryLine("661", debit=D("10.5"))], ACCOUNTS)) == "INVALID_ENTRY_LINE"
    assert _code(validate_lines([EntryLine("661", debit=D(-10))], ACCOUNTS)) == "INVALID_ENTRY_LINE"


def test_a_draft_may_be_unbalanced():
    assert isinstance(validate_lines([EntryLine("661", debit=D(100))], ACCOUNTS), Ok)


def test_every_refusal_speaks_french():
    result = build_entry([EntryLine("661", debit=D(100))], ACCOUNTS)
    assert isinstance(result, Err) and result.message_fr


def test_reversing_swaps_every_side():
    mirrored = reverse_lines([EntryLine("661", debit=D(7), label="x"), EntryLine("422", credit=D(7))])
    assert mirrored == [EntryLine("661", credit=D(7), label="x"), EntryLine("422", debit=D(7))]


def test_split_balance_prints_the_side_the_balance_is_on():
    assert split_balance(D(50)) == (D(50), D(0))
    assert split_balance(D(-20)) == (D(0), D(20))
    assert split_balance(D(0)) == (D(0), D(0))


def test_an_account_number_starts_with_its_class():
    assert _code(validate_account(Account("521", "Banques locales", 6, "asset", True), None)) == "INVALID_ACCOUNT"


def test_an_account_extends_its_parent_number():
    parent = Account("52", "Banques", 5, "asset", False, "5")
    assert isinstance(validate_account(Account("5211", "BDM", 5, "asset", True, "52"), parent), Ok)
    assert _code(validate_account(Account("5711", "Caisse", 5, "asset", True, "52"), parent)) == "INVALID_ACCOUNT"
    assert _code(validate_account(Account("5211", "BDM", 5, "asset", True, "52"), None)) == "INVALID_ACCOUNT"


def test_an_account_code_is_digits_not_starting_with_zero():
    assert _code(validate_account(Account("0521", "x", 0, "asset", True), None)) == "INVALID_ACCOUNT"
    assert _code(validate_account(Account("52A", "x", 5, "asset", True), None)) == "INVALID_ACCOUNT"


def test_an_account_has_a_known_type_and_a_name():
    assert _code(validate_account(Account("521", "x", 5, "cash", True), None)) == "INVALID_ACCOUNT"
    assert _code(validate_account(Account("521", " ", 5, "asset", True), None)) == "INVALID_ACCOUNT"
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `backend/`): `.venv/Scripts/python -m pytest modules/finance/domain/test_ledger.py -q`
Expected: collection error `ModuleNotFoundError: No module named 'modules.finance.domain.ledger'`.

- [ ] **Step 3: Write the implementation**

`backend/modules/finance/domain/ledger.py`:

```python
"""Double-entry rules the ledger never bends, with no database.

An entry is a list of lines; each line hits one postable account on one side, in whole francs
(XOF has no sub-unit), and the two sides of a postable entry are equal and both present.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Iterable, Mapping

from core.domain.result import Err, Ok, Result

ZERO = Decimal("0")
ACCOUNT_TYPES = ("asset", "liability", "equity", "income", "expense")


@dataclass(frozen=True)
class Account:
    code: str
    name: str
    class_no: int
    account_type: str
    is_postable: bool
    parent_code: str | None = None


@dataclass(frozen=True)
class EntryLine:
    account_code: str
    debit: Decimal = ZERO
    credit: Decimal = ZERO
    label: str | None = None
    partner_id: str | None = None
    employee_ref: str | None = None


@dataclass(frozen=True)
class SourceRef:
    """What an automatic entry was posted for; (module, id, kind) is unique among entries."""

    module: str
    id: str
    kind: str


def _whole(value: Decimal) -> bool:
    return value == value.to_integral_value()


def validate_lines(lines: Iterable[EntryLine], accounts: Mapping[str, Account]) -> Result[list[EntryLine]]:
    """Each line on its own: one side, a whole non-negative amount, a postable account.

    The balance is not checked here, so a draft can be saved while it is still being written.
    """
    checked = list(lines)
    for index, line in enumerate(checked, start=1):
        if line.debit < ZERO or line.credit < ZERO or not _whole(line.debit) or not _whole(line.credit):
            return Err(
                "INVALID_ENTRY_LINE",
                f"line {index}: amounts are whole, non-negative francs",
                f"ligne {index} : les montants sont des francs entiers et positifs",
            )
        if (line.debit > ZERO) == (line.credit > ZERO):
            return Err(
                "INVALID_ENTRY_LINE",
                f"line {index}: a line carries either a debit or a credit",
                f"ligne {index} : une ligne porte soit un débit, soit un crédit",
            )
        account = accounts.get(line.account_code)
        if account is None or not account.is_postable:
            return Err(
                "ACCOUNT_NOT_POSTABLE",
                f"line {index}: account {line.account_code} does not exist or is a heading that cannot be posted to",
                f"ligne {index} : le compte {line.account_code} n'existe pas ou est un compte de regroupement non imputable",
            )
    return Ok(checked)


def totals(lines: Iterable[EntryLine]) -> tuple[Decimal, Decimal]:
    debit = credit = ZERO
    for line in lines:
        debit += line.debit
        credit += line.credit
    return debit, credit


def build_entry(lines: Iterable[EntryLine], accounts: Mapping[str, Account]) -> Result[list[EntryLine]]:
    """The lines of a postable entry: every line valid, at least one debit and one credit, sides equal."""
    checked = validate_lines(lines, accounts)
    if isinstance(checked, Err):
        return checked
    debit, credit = totals(checked.value)
    has_both_sides = any(line.debit > ZERO for line in checked.value) and any(line.credit > ZERO for line in checked.value)
    if not has_both_sides or debit != credit:
        return Err(
            "ENTRY_UNBALANCED",
            f"debits ({debit}) and credits ({credit}) must be equal, with at least one line on each side",
            f"le total des débits ({debit}) doit égaler celui des crédits ({credit}), avec au moins une ligne de chaque côté",
        )
    return Ok(checked.value)


def reverse_lines(lines: Iterable[EntryLine]) -> list[EntryLine]:
    """The mirror of an entry: every debit becomes a credit of the same amount on the same account, and back."""
    return [replace(line, debit=line.credit, credit=line.debit) for line in lines]


def split_balance(net: Decimal) -> tuple[Decimal, Decimal]:
    """A signed balance (debit minus credit) as the (debit balance, credit balance) pair a trial balance prints."""
    return (net, ZERO) if net >= ZERO else (ZERO, -net)


def validate_account(account: Account, parent: Account | None) -> Result[Account]:
    """A SYSCOHADA account number: digits, its first digit is its class, it extends its parent's number."""
    code = account.code
    if not code.isdigit() or not 1 <= len(code) <= 10 or code[0] == "0":
        return Err(
            "INVALID_ACCOUNT",
            f"account number {code!r} must be 1 to 10 digits, not starting with 0",
            f"le numéro de compte {code!r} doit compter 1 à 10 chiffres, sans commencer par 0",
        )
    if account.class_no != int(code[0]):
        return Err(
            "INVALID_ACCOUNT",
            f"account {code} belongs to class {code[0]}",
            f"le compte {code} appartient à la classe {code[0]}",
        )
    if account.account_type not in ACCOUNT_TYPES:
        return Err(
            "INVALID_ACCOUNT",
            f"unknown account type {account.account_type!r}",
            f"type de compte inconnu {account.account_type!r}",
        )
    if not account.name.strip():
        return Err("INVALID_ACCOUNT", "an account needs a name", "un compte doit avoir un intitulé")
    if account.parent_code is not None:
        if parent is None:
            return Err(
                "INVALID_ACCOUNT",
                f"parent account {account.parent_code} does not exist",
                f"le compte parent {account.parent_code} n'existe pas",
            )
        if not (code.startswith(parent.code) and len(code) > len(parent.code)):
            return Err(
                "INVALID_ACCOUNT",
                f"account {code} must start with its parent's number {parent.code}",
                f"le compte {code} doit commencer par le numéro de son parent {parent.code}",
            )
    return Ok(account)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest modules/finance/domain/test_ledger.py core/test_error_translations.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/finance/domain/ledger.py backend/modules/finance/domain/test_ledger.py
git commit -m "feat(finance): balanced-entry builder for the SYSCOHADA ledger

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Posting rules and source mappings (pure domain)

**Files:**
- Create: `backend/modules/finance/domain/posting.py`
- Test: `backend/modules/finance/domain/test_posting.py`

**Interfaces:**
- Consumes (Task 1): `ZERO`, `Account`, `EntryLine`.
- Produces:
  - `WILDCARD = "*"`, `PAYROLL_LINE_KINDS`, `PAYMENT_METHODS = ("bank", "mobile_money", "cash")`, `RULE_KINDS: dict[str, tuple[str, ...]]` (`payroll` → the seven line kinds + `payment`; `invoice` → `issued`, `paid`), `RULE_STATUSES = ("to_confirm", "confirmed")`
  - `@dataclass(frozen=True) PostingRule(source, source_kind, code, debit_account_code: str | None, credit_account_code: str | None, journal_code: str | None = None, status: str = "to_confirm", id: str | None = None)` — field order matches `SELECT source, source_kind, code, debit_account_code, credit_account_code, journal_code, status, id`.
  - `@dataclass(frozen=True) PaymentEntry(method: str, journal_code: str, lines: list[EntryLine])`
  - `resolve_rule(rules, *, source, source_kind, code) -> Result[PostingRule]` (`POSTING_RULE_MISSING`)
  - `payroll_run_lines(posting_lines: Iterable[Mapping], rules) -> Result[list[EntryLine]]`
  - `payroll_payment_entries(payment_lines: Iterable[Mapping], rules) -> Result[list[PaymentEntry]]`
  - `to_xof(raw, *, currency: str) -> Result[Decimal]` (`CURRENCY_NOT_XOF`, `INVALID_ENTRY_LINE`)
  - `invoice_entry(kind: str, *, amount: Decimal, partner_id: str, label: str, rules) -> Result[tuple[str, list[EntryLine]]]` → `(journal_code, lines)`
  - `validate_rule(rule, accounts: Mapping[str, Account], journal_codes: set[str]) -> Result[PostingRule]` (`INVALID_POSTING_RULE`, `ACCOUNT_NOT_POSTABLE`; returns the rule with its code stripped)

- [ ] **Step 1: Write the failing test**

`backend/modules/finance/domain/test_posting.py`:

```python
"""Posting rules: how payroll lines and invoices become journal lines, with no database."""
from decimal import Decimal

from core.domain.result import Err, Ok
from modules.finance.domain.ledger import Account, EntryLine, build_entry
from modules.finance.domain.posting import (
    PostingRule,
    invoice_entry,
    payroll_payment_entries,
    payroll_run_lines,
    resolve_rule,
    to_xof,
    validate_rule,
)

D = Decimal


def _rule(source, kind, code, debit, credit, journal=None) -> PostingRule:
    return PostingRule(
        source=source, source_kind=kind, code=code,
        debit_account_code=debit, credit_account_code=credit, journal_code=journal,
    )


RULES = [
    _rule("payroll", "earning", "*", "661", None),
    _rule("payroll", "deduction", "*", None, "421"),
    _rule("payroll", "employee_contribution", "*", None, "431"),
    _rule("payroll", "employer_contribution", "*", "664", "431"),
    _rule("payroll", "employer_charge", "*", "641", "442"),
    _rule("payroll", "tax", "*", None, "447"),
    _rule("payroll", "net", "*", None, "422"),
    _rule("payroll", "payment", "bank", "422", "521", "BNQ"),
    _rule("payroll", "payment", "cash", "422", "571", "CAI"),
    _rule("invoice", "issued", "*", "411", "702", "VTE"),
    _rule("invoice", "paid", "*", "521", "411", "BNQ"),
]
ACCOUNTS = {
    code: Account(code, code, int(code[0]), "asset", True)
    for code in ("411", "421", "422", "431", "433", "442", "447", "521", "571", "641", "661", "664", "702")
}
JOURNALS = {"PAIE", "VTE", "ACH", "BNQ", "CAI", "OD"}

# One employee: gross 320 000 = INPS 11 040 + ITS 25 000 + advance 10 000 + net 273 960.
RUN = [
    {"source_kind": "earning", "code": "BASE", "amount": D(300000), "employee_id": "e1"},
    {"source_kind": "earning", "code": "OT_DAY", "amount": D(20000), "employee_id": "e1"},
    {"source_kind": "employee_contribution", "code": "INPS_EE", "amount": D(11040), "employee_id": "e1"},
    {"source_kind": "tax", "code": "ITS", "amount": D(25000), "employee_id": "e1"},
    {"source_kind": "deduction", "code": "ADVANCE", "amount": D(10000), "employee_id": "e1"},
    {"source_kind": "net", "code": "NET", "amount": D(273960), "employee_id": "e1"},
    {"source_kind": "employer_contribution", "code": "INPS_ER", "amount": D(60000), "employee_id": "e1"},
    {"source_kind": "employer_charge", "code": "TL", "amount": D(3200), "employee_id": "e1"},
]


def test_the_exact_code_wins_over_the_fallback():
    rules = RULES + [_rule("payroll", "employee_contribution", "AMO_EE", None, "433")]
    amo = resolve_rule(rules, source="payroll", source_kind="employee_contribution", code="AMO_EE")
    inps = resolve_rule(rules, source="payroll", source_kind="employee_contribution", code="INPS_EE")
    assert amo.value.credit_account_code == "433"
    assert inps.value.credit_account_code == "431"


def test_no_rule_and_no_fallback_is_posting_rule_missing():
    result = resolve_rule(RULES, source="payroll", source_kind="benefit", code="CAR")
    assert isinstance(result, Err) and result.code == "POSTING_RULE_MISSING" and result.message_fr


def test_a_run_becomes_one_balanced_entry_aggregated_by_account():
    result = payroll_run_lines(RUN, RULES)
    assert isinstance(result, Ok), result
    assert result.value == [
        EntryLine("641", debit=D(3200)),
        EntryLine("661", debit=D(320000)),
        EntryLine("664", debit=D(60000)),
        EntryLine("421", credit=D(10000)),
        EntryLine("422", credit=D(273960)),
        EntryLine("431", credit=D(71040)),
        EntryLine("442", credit=D(3200)),
        EntryLine("447", credit=D(25000)),
    ]
    assert isinstance(build_entry(result.value, ACCOUNTS), Ok)


def test_many_employees_add_up_on_the_same_account():
    two = RUN + [dict(line, employee_id="e2") for line in RUN]
    lines = {(line.account_code, line.debit > 0): line for line in payroll_run_lines(two, RULES).value}
    assert lines[("661", True)].debit == D(640000)
    assert lines[("422", False)].credit == D(547920)


def test_zero_lines_are_skipped_and_negative_lines_refused():
    with_zero = RUN + [{"source_kind": "earning", "code": "BONUS", "amount": D(0), "employee_id": "e1"}]
    assert payroll_run_lines(with_zero, RULES).value == payroll_run_lines(RUN, RULES).value
    negative = payroll_run_lines([{"source_kind": "earning", "code": "BASE", "amount": D(-5), "employee_id": "e1"}], RULES)
    assert isinstance(negative, Err) and negative.code == "INVALID_ENTRY_LINE"


def test_an_unmapped_kind_refuses_the_whole_run():
    extra = RUN + [{"source_kind": "benefit", "code": "CAR", "amount": D(5), "employee_id": "e1"}]
    result = payroll_run_lines(extra, RULES)
    assert isinstance(result, Err) and result.code == "POSTING_RULE_MISSING"


def test_payments_make_one_entry_per_method_clearing_net_pay():
    result = payroll_payment_entries(
        [
            {"method": "bank", "amount": D(200000), "employee_id": "e1"},
            {"method": "cash", "amount": D(23960), "employee_id": "e2"},
            {"method": "bank", "amount": D(50000), "employee_id": "e3"},
        ],
        RULES,
    )
    assert isinstance(result, Ok), result
    assert [(entry.method, entry.journal_code) for entry in result.value] == [("bank", "BNQ"), ("cash", "CAI")]
    assert result.value[0].lines == [EntryLine("422", debit=D(250000)), EntryLine("521", credit=D(250000))]


def test_a_payment_method_without_a_complete_rule_is_refused():
    lines = [{"method": "mobile_money", "amount": D(1000), "employee_id": "e1"}]
    missing = payroll_payment_entries(lines, RULES)
    assert isinstance(missing, Err) and missing.code == "POSTING_RULE_MISSING"
    partial = payroll_payment_entries(lines, RULES + [_rule("payroll", "payment", "mobile_money", "422", None)])
    assert isinstance(partial, Err) and partial.code == "POSTING_RULE_MISSING"


def test_an_unknown_payment_method_is_refused():
    result = payroll_payment_entries([{"method": "cheque", "amount": D(1000), "employee_id": "e1"}], RULES)
    assert isinstance(result, Err) and result.code == "INVALID_ENTRY_LINE"


def test_invoice_amounts_are_whole_xof_rounded_half_up():
    assert to_xof(1500.4, currency="XOF").value == D(1500)
    assert to_xof("1500.5", currency="XOF").value == D(1501)
    assert to_xof(1500, currency="EUR").code == "CURRENCY_NOT_XOF"
    assert to_xof(0, currency="XOF").code == "INVALID_ENTRY_LINE"
    assert to_xof("abc", currency="XOF").code == "INVALID_ENTRY_LINE"


def test_an_issued_invoice_debits_the_customer_and_its_payment_credits_it():
    issued = invoice_entry("issued", amount=D(150000), partner_id="p1", label="Facture F1", rules=RULES)
    assert issued.value == (
        "VTE",
        [
            EntryLine("411", debit=D(150000), label="Facture F1", partner_id="p1"),
            EntryLine("702", credit=D(150000), label="Facture F1"),
        ],
    )
    paid = invoice_entry("paid", amount=D(150000), partner_id="p1", label="Règlement F1", rules=RULES)
    assert paid.value == (
        "BNQ",
        [
            EntryLine("521", debit=D(150000), label="Règlement F1"),
            EntryLine("411", credit=D(150000), label="Règlement F1", partner_id="p1"),
        ],
    )


def test_a_valid_rule_comes_back_with_its_code_trimmed():
    result = validate_rule(_rule("payroll", "employee_contribution", " AMO_EE ", None, "433"), ACCOUNTS, JOURNALS)
    assert isinstance(result, Ok) and result.value.code == "AMO_EE"


def test_invalid_rules_are_refused():
    cases = [
        (_rule("stock", "earning", "*", "661", None), "INVALID_POSTING_RULE"),
        (_rule("payroll", "bonus", "*", "661", None), "INVALID_POSTING_RULE"),
        (_rule("payroll", "earning", "", "661", None), "INVALID_POSTING_RULE"),
        (_rule("payroll", "earning", "*", None, None), "INVALID_POSTING_RULE"),
        (_rule("payroll", "earning", "*", "999", None), "ACCOUNT_NOT_POSTABLE"),
        (_rule("payroll", "payment", "cheque", "422", "521", "BNQ"), "INVALID_POSTING_RULE"),
        (_rule("payroll", "payment", "bank", "422", "521", None), "INVALID_POSTING_RULE"),
        (_rule("payroll", "payment", "bank", "422", "521", "XXX"), "INVALID_POSTING_RULE"),
        (_rule("invoice", "issued", "P1", "411", "702", "VTE"), "INVALID_POSTING_RULE"),
    ]
    for rule, code in cases:
        result = validate_rule(rule, ACCOUNTS, JOURNALS)
        assert isinstance(result, Err) and result.code == code, rule
        assert result.message_fr, rule
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest modules/finance/domain/test_posting.py -q`
Expected: collection error `No module named 'modules.finance.domain.posting'`.

- [ ] **Step 3: Write the implementation**

`backend/modules/finance/domain/posting.py`:

```python
"""How a payroll run or an invoice becomes journal lines, with no database.

A posting rule is keyed by (source, source_kind, code); code '*' is the fallback of its kind.
A rule names a debit account, a credit account, or both. Payment and invoice rules are
self-contained — both sides and the journal — because they alone make a whole entry.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Iterable, Mapping

from core.domain.result import Err, Ok, Result
from modules.finance.domain.ledger import ZERO, Account, EntryLine

WILDCARD = "*"
PAYROLL_LINE_KINDS = (
    "earning",
    "deduction",
    "employee_contribution",
    "employer_contribution",
    "employer_charge",
    "tax",
    "net",
)
PAYMENT_METHODS = ("bank", "mobile_money", "cash")
RULE_KINDS: dict[str, tuple[str, ...]] = {
    "payroll": PAYROLL_LINE_KINDS + ("payment",),
    "invoice": ("issued", "paid"),
}
SELF_CONTAINED_KINDS = {("payroll", "payment"), ("invoice", "issued"), ("invoice", "paid")}
RULE_STATUSES = ("to_confirm", "confirmed")


@dataclass(frozen=True)
class PostingRule:
    source: str
    source_kind: str
    code: str
    debit_account_code: str | None
    credit_account_code: str | None
    journal_code: str | None = None
    status: str = "to_confirm"
    id: str | None = None


@dataclass(frozen=True)
class PaymentEntry:
    method: str
    journal_code: str
    lines: list[EntryLine]


def resolve_rule(rules: Iterable[PostingRule], *, source: str, source_kind: str, code: str) -> Result[PostingRule]:
    """The rule written for this exact code, else the '*' rule of its kind."""
    fallback: PostingRule | None = None
    for rule in rules:
        if rule.source != source or rule.source_kind != source_kind:
            continue
        if rule.code == code:
            return Ok(rule)
        if rule.code == WILDCARD:
            fallback = rule
    if fallback is None:
        return Err(
            "POSTING_RULE_MISSING",
            f"no posting rule for {source} / {source_kind} / {code} and no '*' rule for {source_kind}",
            f"aucune règle d'imputation pour {source} / {source_kind} / {code}, ni de règle « * » pour {source_kind}",
        )
    return Ok(fallback)


def _complete(rule: PostingRule, *, code: str) -> Result[PostingRule]:
    if rule.debit_account_code and rule.credit_account_code and rule.journal_code:
        return Ok(rule)
    return Err(
        "POSTING_RULE_MISSING",
        f"the {rule.source} / {rule.source_kind} / {code} rule needs a debit account, a credit account and a journal",
        f"la règle {rule.source} / {rule.source_kind} / {code} doit indiquer un compte au débit, un compte au crédit et un journal",
    )


def _amount(raw: object, *, code: str) -> Result[Decimal]:
    try:
        amount = Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return Err("INVALID_ENTRY_LINE", f"{code}: {raw!r} is not an amount", f"{code} : {raw!r} n'est pas un montant")
    if amount < ZERO or amount != amount.to_integral_value():
        return Err(
            "INVALID_ENTRY_LINE",
            f"{code}: {amount} is not a whole, non-negative amount of francs",
            f"{code} : {amount} n'est pas un montant entier et positif en francs",
        )
    return Ok(amount)


def payroll_run_lines(posting_lines: Iterable[Mapping], rules: Iterable[PostingRule]) -> Result[list[EntryLine]]:
    """The PAIE entry of a run: each payroll line goes to its rule's debit and/or credit account,
    amounts are summed per account and side, debits first, each side ordered by account number."""
    rules = list(rules)
    debits: dict[str, Decimal] = defaultdict(lambda: ZERO)
    credits: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for line in posting_lines:
        code = str(line["code"])
        amount = _amount(line["amount"], code=code)
        if isinstance(amount, Err):
            return amount
        if amount.value == ZERO:
            continue
        resolved = resolve_rule(rules, source="payroll", source_kind=str(line["source_kind"]), code=code)
        if isinstance(resolved, Err):
            return resolved
        rule = resolved.value
        if rule.debit_account_code:
            debits[rule.debit_account_code] += amount.value
        if rule.credit_account_code:
            credits[rule.credit_account_code] += amount.value
    return Ok(
        [EntryLine(account, debit=total) for account, total in sorted(debits.items())]
        + [EntryLine(account, credit=total) for account, total in sorted(credits.items())]
    )


def payroll_payment_entries(payment_lines: Iterable[Mapping], rules: Iterable[PostingRule]) -> Result[list[PaymentEntry]]:
    """One entry per payment method used: net pay (debit side of the rule) against the method's
    bank / e-money / cash account, in the journal the rule names."""
    rules = list(rules)
    per_method: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for line in payment_lines:
        method = str(line["method"])
        if method not in PAYMENT_METHODS:
            return Err(
                "INVALID_ENTRY_LINE",
                f"unknown payment method {method!r}",
                f"mode de paiement inconnu {method!r}",
            )
        amount = _amount(line["amount"], code=method)
        if isinstance(amount, Err):
            return amount
        per_method[method] += amount.value
    entries: list[PaymentEntry] = []
    for method in PAYMENT_METHODS:
        total = per_method.get(method, ZERO)
        if total == ZERO:
            continue
        resolved = resolve_rule(rules, source="payroll", source_kind="payment", code=method)
        if isinstance(resolved, Err):
            return resolved
        complete = _complete(resolved.value, code=method)
        if isinstance(complete, Err):
            return complete
        rule = complete.value
        entries.append(
            PaymentEntry(
                method=method,
                journal_code=str(rule.journal_code),
                lines=[
                    EntryLine(str(rule.debit_account_code), debit=total),
                    EntryLine(str(rule.credit_account_code), credit=total),
                ],
            )
        )
    return Ok(entries)


def to_xof(raw: object, *, currency: str) -> Result[Decimal]:
    """An invoice amount in whole francs. Only XOF is posted; rounding is half up."""
    if currency != "XOF":
        return Err(
            "CURRENCY_NOT_XOF",
            f"only XOF amounts are posted to the ledger, not {currency}",
            f"seuls les montants en XOF (F CFA) sont comptabilisés, pas {currency}",
        )
    try:
        amount = Decimal(str(raw)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return Err("INVALID_ENTRY_LINE", f"{raw!r} is not an amount", f"{raw!r} n'est pas un montant")
    if amount <= ZERO:
        return Err(
            "INVALID_ENTRY_LINE",
            "an invoice amount must be positive",
            "le montant d'une facture doit être positif",
        )
    return Ok(amount)


def invoice_entry(
    kind: str, *, amount: Decimal, partner_id: str, label: str, rules: Iterable[PostingRule]
) -> Result[tuple[str, list[EntryLine]]]:
    """The entry of an issued invoice (the customer side is the debit) or of its payment (the
    customer side is the credit). The partner id rides on the customer line only."""
    resolved = resolve_rule(rules, source="invoice", source_kind=kind, code=WILDCARD)
    if isinstance(resolved, Err):
        return resolved
    complete = _complete(resolved.value, code=WILDCARD)
    if isinstance(complete, Err):
        return complete
    rule = complete.value
    customer_on_debit = kind == "issued"
    lines = [
        EntryLine(str(rule.debit_account_code), debit=amount, label=label, partner_id=partner_id if customer_on_debit else None),
        EntryLine(str(rule.credit_account_code), credit=amount, label=label, partner_id=None if customer_on_debit else partner_id),
    ]
    return Ok((str(rule.journal_code), lines))


def validate_rule(rule: PostingRule, accounts: Mapping[str, Account], journal_codes: set[str]) -> Result[PostingRule]:
    kinds = RULE_KINDS.get(rule.source)
    if kinds is None:
        return Err(
            "INVALID_POSTING_RULE",
            f"unknown source {rule.source!r}; use one of {', '.join(RULE_KINDS)}",
            f"source inconnue {rule.source!r} ; utilisez {', '.join(RULE_KINDS)}",
        )
    if rule.source_kind not in kinds:
        return Err(
            "INVALID_POSTING_RULE",
            f"{rule.source} has no kind {rule.source_kind!r}; use one of {', '.join(kinds)}",
            f"{rule.source} n'a pas de type {rule.source_kind!r} ; utilisez {', '.join(kinds)}",
        )
    code = rule.code.strip()
    if not code:
        return Err(
            "INVALID_POSTING_RULE",
            "a rule needs a code, or '*' for every code of its kind",
            "une règle doit avoir un code, ou « * » pour tous les codes de son type",
        )
    if (rule.source, rule.source_kind) == ("payroll", "payment") and code not in PAYMENT_METHODS + (WILDCARD,):
        return Err(
            "INVALID_POSTING_RULE",
            f"a payment rule's code is a payment method: {', '.join(PAYMENT_METHODS)} or '*'",
            f"le code d'une règle de paiement est un mode de paiement : {', '.join(PAYMENT_METHODS)} ou « * »",
        )
    if rule.source == "invoice" and code != WILDCARD:
        return Err(
            "INVALID_POSTING_RULE",
            "invoice rules use the code '*'",
            "les règles de facture utilisent le code « * »",
        )
    if not rule.debit_account_code and not rule.credit_account_code:
        return Err(
            "INVALID_POSTING_RULE",
            "a rule posts to at least one account",
            "une règle impute au moins un compte",
        )
    for account_code in (rule.debit_account_code, rule.credit_account_code):
        if account_code:
            account = accounts.get(account_code)
            if account is None or not account.is_postable:
                return Err(
                    "ACCOUNT_NOT_POSTABLE",
                    f"account {account_code} does not exist or cannot be posted to",
                    f"le compte {account_code} n'existe pas ou n'est pas imputable",
                )
    if rule.journal_code and rule.journal_code not in journal_codes:
        return Err(
            "INVALID_POSTING_RULE",
            f"journal {rule.journal_code} does not exist",
            f"le journal {rule.journal_code} n'existe pas",
        )
    if (rule.source, rule.source_kind) in SELF_CONTAINED_KINDS:
        complete = _complete(rule, code=code)
        if isinstance(complete, Err):
            return Err("INVALID_POSTING_RULE", complete.message, complete.message_fr)
    return Ok(replace(rule, code=code))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest modules/finance/domain -q core/test_error_translations.py`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/finance/domain/posting.py backend/modules/finance/domain/test_posting.py
git commit -m "feat(finance): posting rules with '*' fallback for payroll and invoices

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Ledger master data — chart seed, journals, fiscal years, periods

**Files:**
- Create: `backend/modules/finance/domain/syscohada_chart.py`
- Create: `backend/modules/finance/migrations/0002_finance_ledger_master_data.sql`
- Create: `backend/modules/finance/api/chart_setup_service.py`
- Create: `backend/modules/finance/api/period_service.py`
- Modify: `backend/modules/finance/module.json` (whole file replaced)
- Test: `backend/modules/finance/domain/test_syscohada_chart.py`
- Test: `backend/modules/finance/api/test_ledger_setup_integration.py`

**Interfaces:**
- Consumes (Tasks 1–2): `Account`, `validate_account`, `PostingRule`, `validate_rule`, `PAYROLL_LINE_KINDS`, `PAYMENT_METHODS`, `WILDCARD`.
- Produces:
  - `CHART: tuple[Account, ...]` (parents before children), `JOURNALS: tuple[tuple[str, str, str], ...]` = `(code, name, journal_type)`, `DEFAULT_POSTING_RULES: tuple[PostingRule, ...]`
  - Tables `finance.accounts` PK `(tenant_id, code)`, `finance.journals` PK `(tenant_id, code)`, `finance.fiscal_years (id)`, `finance.periods` PK `(tenant_id, period)`, `finance.posting_rules (id)` unique `(tenant_id, source, source_kind, code)`.
  - `ChartSetupService(connection).ensure_defaults(*, tenant_id, actor_id) -> dict[str, int]` with keys `accounts`, `journals`, `posting_rules` (rows inserted).
  - `PeriodService(connection)`: `open_fiscal_year(*, tenant_id, actor_id, year: int) -> Result[dict]`; `list_periods(*, tenant_id, year: int | None = None) -> list[dict]` (keys `period, year, status, closed_by, closed_at`); `ensure_open(*, tenant_id, day: date) -> Result[date]` (`PERIOD_MISSING` / `PERIOD_CLOSED`); `close_period(*, tenant_id, actor_id, period: date) -> Result[dict]`; `reopen_period(...)` same signature.
  - `period_missing(period: date) -> Err`.

- [ ] **Step 1: Write the failing domain test**

`backend/modules/finance/domain/test_syscohada_chart.py`:

```python
"""The SYSCOHADA seed obeys the ledger's own rules, and the manifest declares the ledger."""
import json
import pathlib

from core.domain.result import Ok
from modules.finance.domain.ledger import validate_account
from modules.finance.domain.posting import PAYMENT_METHODS, PAYROLL_LINE_KINDS, WILDCARD, validate_rule
from modules.finance.domain.syscohada_chart import CHART, DEFAULT_POSTING_RULES, JOURNALS

BY_CODE = {account.code: account for account in CHART}


def test_every_account_is_valid_and_comes_after_its_parent():
    seen: set[str] = set()
    for account in CHART:
        parent = BY_CODE.get(account.parent_code) if account.parent_code else None
        assert isinstance(validate_account(account, parent), Ok), account.code
        if account.parent_code:
            assert account.parent_code in seen, f"{account.code} is listed before its parent"
            assert not BY_CODE[account.parent_code].is_postable, f"the parent of {account.code} is a posting account"
        seen.add(account.code)
    assert len(seen) == len(CHART)


def test_the_nine_classes_are_headings():
    for class_no in range(1, 10):
        account = BY_CODE[str(class_no)]
        assert account.class_no == class_no and not account.is_postable


def test_the_accounts_the_plant_posts_to_are_postable():
    for code in (
        "401", "411", "421", "422", "431", "433", "441", "442", "443", "444", "445", "446", "447",
        "521", "552", "571", "585", "641", "661", "663", "664", "701", "702",
    ):
        assert BY_CODE[code].is_postable, code


def test_the_six_journals():
    assert [code for code, _, _ in JOURNALS] == ["PAIE", "VTE", "ACH", "BNQ", "CAI", "OD"]


def test_every_default_rule_is_valid_against_the_seed_and_awaits_confirmation():
    journals = {code for code, _, _ in JOURNALS}
    for rule in DEFAULT_POSTING_RULES:
        assert isinstance(validate_rule(rule, BY_CODE, journals), Ok), rule
        assert rule.status == "to_confirm"


def test_every_payroll_line_kind_and_payment_method_has_a_default():
    keys = {(rule.source, rule.source_kind, rule.code) for rule in DEFAULT_POSTING_RULES}
    for kind in PAYROLL_LINE_KINDS:
        assert ("payroll", kind, WILDCARD) in keys, kind
    for method in PAYMENT_METHODS:
        assert ("payroll", "payment", method) in keys, method
    assert ("invoice", "issued", WILDCARD) in keys
    assert ("invoice", "paid", WILDCARD) in keys


def test_the_manifest_declares_the_ledger():
    manifest_path = pathlib.Path(__file__).resolve().parents[1] / "module.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for permission in (
        "finance.view_ledger",
        "finance.manage_entries",
        "finance.admin_entries",
        "finance.manage_accounts",
        "finance.admin_accounts",
        "finance.admin_periods",
        "finance.manage_posting_rules",
    ):
        assert permission in manifest["permissions"], permission
    assert "payroll" in manifest["optional_depends"]
    assert "finance.journal_entry.posted" in manifest["publishes_events"]
    for event in ("payroll.run.approved", "payroll.run.paid", "payroll.run.reversed", "finance.invoice.issued", "finance.invoice.paid"):
        assert event in manifest["subscribes_events"], event
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python -m pytest modules/finance/domain/test_syscohada_chart.py -q`
Expected: collection error `No module named 'modules.finance.domain.syscohada_chart'`.

- [ ] **Step 3: Write the seed data**

`backend/modules/finance/domain/syscohada_chart.py`:

```python
"""The SYSCOHADA revised chart (plan comptable OHADA 2017) as seed data.

The nine classes, the headings above the accounts, and the accounts this plant posts to.
Numbers and names are seed data from public references, to be checked by the client's
accountant (spec: "no invented numbers"); accounts can be added and renamed from the screen.
Default posting rules are all `to_confirm`.
"""
from __future__ import annotations

from modules.finance.domain.ledger import Account
from modules.finance.domain.posting import PostingRule

HEADING = False
POSTABLE = True


def _account(code: str, name: str, account_type: str, is_postable: bool, parent: str | None = None) -> Account:
    return Account(
        code=code, name=name, class_no=int(code[0]), account_type=account_type,
        is_postable=is_postable, parent_code=parent,
    )


CHART: tuple[Account, ...] = (
    _account("1", "Comptes de ressources durables", "equity", HEADING),
    _account("2", "Comptes d'actif immobilisé", "asset", HEADING),
    _account("3", "Comptes de stocks", "asset", HEADING),
    _account("4", "Comptes de tiers", "liability", HEADING),
    _account("5", "Comptes de trésorerie", "asset", HEADING),
    _account("6", "Comptes de charges des activités ordinaires", "expense", HEADING),
    _account("7", "Comptes de produits des activités ordinaires", "income", HEADING),
    _account("8", "Comptes des autres charges et des autres produits", "expense", HEADING),
    _account("9", "Comptes des engagements hors bilan et de la comptabilité analytique", "expense", HEADING),
    # Class 1
    _account("10", "Capital", "equity", HEADING, "1"),
    _account("101", "Capital social", "equity", POSTABLE, "10"),
    _account("11", "Réserves", "equity", HEADING, "1"),
    _account("111", "Réserve légale", "equity", POSTABLE, "11"),
    _account("12", "Report à nouveau", "equity", HEADING, "1"),
    _account("121", "Report à nouveau créditeur", "equity", POSTABLE, "12"),
    _account("129", "Report à nouveau débiteur", "equity", POSTABLE, "12"),
    _account("13", "Résultat net de l'exercice", "equity", HEADING, "1"),
    _account("131", "Résultat net : bénéfice", "equity", POSTABLE, "13"),
    _account("139", "Résultat net : perte", "equity", POSTABLE, "13"),
    _account("16", "Emprunts et dettes assimilées", "liability", HEADING, "1"),
    _account("162", "Emprunts et dettes auprès des établissements de crédit", "liability", POSTABLE, "16"),
    # Class 2
    _account("24", "Matériel, mobilier et actifs biologiques", "asset", HEADING, "2"),
    _account("241", "Matériel et outillage industriel et commercial", "asset", POSTABLE, "24"),
    _account("245", "Matériel de transport", "asset", POSTABLE, "24"),
    _account("28", "Amortissements", "asset", HEADING, "2"),
    _account("284", "Amortissements du matériel", "asset", POSTABLE, "28"),
    # Class 3
    _account("31", "Marchandises", "asset", HEADING, "3"),
    _account("311", "Marchandises A", "asset", POSTABLE, "31"),
    _account("32", "Matières premières et fournitures liées", "asset", HEADING, "3"),
    _account("321", "Matières premières", "asset", POSTABLE, "32"),
    _account("33", "Autres approvisionnements", "asset", HEADING, "3"),
    _account("335", "Emballages", "asset", POSTABLE, "33"),
    _account("36", "Produits finis", "asset", HEADING, "3"),
    _account("361", "Produits finis A", "asset", POSTABLE, "36"),
    # Class 4
    _account("40", "Fournisseurs et comptes rattachés", "liability", HEADING, "4"),
    _account("401", "Fournisseurs, dettes en compte", "liability", POSTABLE, "40"),
    _account("41", "Clients et comptes rattachés", "asset", HEADING, "4"),
    _account("411", "Clients", "asset", POSTABLE, "41"),
    _account("42", "Personnel", "liability", HEADING, "4"),
    _account("421", "Personnel, avances et acomptes", "asset", POSTABLE, "42"),
    _account("422", "Personnel, rémunérations dues", "liability", POSTABLE, "42"),
    _account("43", "Organismes sociaux", "liability", HEADING, "4"),
    _account("431", "Sécurité sociale", "liability", POSTABLE, "43"),
    _account("433", "Autres organismes sociaux", "liability", POSTABLE, "43"),
    _account("44", "État et collectivités publiques", "liability", HEADING, "4"),
    _account("441", "État, impôt sur les bénéfices", "liability", POSTABLE, "44"),
    _account("442", "État, autres impôts et taxes", "liability", POSTABLE, "44"),
    _account("443", "État, TVA facturée", "liability", POSTABLE, "44"),
    _account("444", "État, TVA due ou crédit de TVA", "liability", POSTABLE, "44"),
    _account("445", "État, TVA récupérable", "asset", POSTABLE, "44"),
    _account("446", "État, autres taxes sur le chiffre d'affaires", "liability", POSTABLE, "44"),
    _account("447", "État, impôts retenus à la source", "liability", POSTABLE, "44"),
    _account("47", "Débiteurs et créditeurs divers", "liability", HEADING, "4"),
    _account("471", "Débiteurs et créditeurs divers, comptes d'attente", "liability", POSTABLE, "47"),
    # Class 5
    _account("52", "Banques", "asset", HEADING, "5"),
    _account("521", "Banques locales", "asset", POSTABLE, "52"),
    _account("55", "Instruments de monnaie électronique", "asset", HEADING, "5"),
    _account("552", "Monnaie électronique, téléphone portable", "asset", POSTABLE, "55"),
    _account("57", "Caisse", "asset", HEADING, "5"),
    _account("571", "Caisse siège social", "asset", POSTABLE, "57"),
    _account("58", "Régies d'avances, accréditifs et virements internes", "asset", HEADING, "5"),
    _account("585", "Virements de fonds", "asset", POSTABLE, "58"),
    # Class 6
    _account("60", "Achats et variations de stocks", "expense", HEADING, "6"),
    _account("601", "Achats de marchandises", "expense", POSTABLE, "60"),
    _account("602", "Achats de matières premières et fournitures liées", "expense", POSTABLE, "60"),
    _account("608", "Achats d'emballages", "expense", POSTABLE, "60"),
    _account("64", "Impôts et taxes", "expense", HEADING, "6"),
    _account("641", "Impôts et taxes directs", "expense", POSTABLE, "64"),
    _account("66", "Charges de personnel", "expense", HEADING, "6"),
    _account("661", "Rémunérations directes versées au personnel national", "expense", POSTABLE, "66"),
    _account("663", "Indemnités forfaitaires versées au personnel", "expense", POSTABLE, "66"),
    _account("664", "Charges sociales", "expense", POSTABLE, "66"),
    # Class 7
    _account("70", "Ventes", "income", HEADING, "7"),
    _account("701", "Ventes de marchandises", "income", POSTABLE, "70"),
    _account("702", "Ventes de produits finis", "income", POSTABLE, "70"),
    _account("706", "Services vendus", "income", POSTABLE, "70"),
)

JOURNALS: tuple[tuple[str, str, str], ...] = (
    ("PAIE", "Journal de paie", "payroll"),
    ("VTE", "Journal des ventes", "sales"),
    ("ACH", "Journal des achats", "purchases"),
    ("BNQ", "Journal de banque", "bank"),
    ("CAI", "Journal de caisse", "cash"),
    ("OD", "Opérations diverses", "general"),
)


def _rule(source: str, kind: str, code: str, debit: str | None, credit: str | None, journal: str | None = None) -> PostingRule:
    return PostingRule(
        source=source, source_kind=kind, code=code,
        debit_account_code=debit, credit_account_code=credit, journal_code=journal,
    )


# Spec default mapping, to be confirmed by the accountant. Filled where the spec is silent:
# employer charges credit 442; mobile money pays out of 552. AMO -> 433 needs code rows (the
# contribution codes belong to payroll) — scripts/seed_finance_ledger.py adds them.
DEFAULT_POSTING_RULES: tuple[PostingRule, ...] = (
    _rule("payroll", "earning", "*", "661", None),
    _rule("payroll", "deduction", "*", None, "421"),
    _rule("payroll", "employee_contribution", "*", None, "431"),
    _rule("payroll", "employer_contribution", "*", "664", "431"),
    _rule("payroll", "employer_charge", "*", "641", "442"),
    _rule("payroll", "tax", "*", None, "447"),
    _rule("payroll", "net", "*", None, "422"),
    _rule("payroll", "payment", "bank", "422", "521", "BNQ"),
    _rule("payroll", "payment", "mobile_money", "422", "552", "BNQ"),
    _rule("payroll", "payment", "cash", "422", "571", "CAI"),
    _rule("invoice", "issued", "*", "411", "702", "VTE"),
    _rule("invoice", "paid", "*", "521", "411", "BNQ"),
)
```

- [ ] **Step 4: Replace the manifest**

`backend/modules/finance/module.json` (the whole phase's surface, declared up front as the architecture skill requires):

```json
{
  "name": "finance",
  "version": "0.2.0",
  "depends": ["core"],
  "optional_depends": ["sales", "payroll"],
  "provides_api": [
    "InvoiceService",
    "LedgerPostingService",
    "LedgerQueryService",
    "LedgerReportService",
    "PeriodService"
  ],
  "publishes_events": ["finance.invoice.issued", "finance.invoice.paid", "finance.journal_entry.posted"],
  "subscribes_events": [
    "sales.order.confirmed",
    "payroll.run.approved",
    "payroll.run.paid",
    "payroll.run.reversed",
    "finance.invoice.issued",
    "finance.invoice.paid"
  ],
  "migrations_path": "./migrations",
  "permissions": [
    "finance.view_invoices",
    "finance.manage_invoices",
    "finance.admin_invoices",
    "finance.view_ledger",
    "finance.manage_entries",
    "finance.admin_entries",
    "finance.manage_accounts",
    "finance.admin_accounts",
    "finance.admin_periods",
    "finance.manage_posting_rules"
  ]
}
```

- [ ] **Step 5: Run the domain test to verify it passes**

Run: `.venv/Scripts/python -m pytest modules/finance/domain -q`
Expected: all PASS.

- [ ] **Step 6: Write the migration**

`backend/modules/finance/migrations/0002_finance_ledger_master_data.sql`:

```sql
-- SYSCOHADA ledger, master data: chart of accounts, journals, fiscal years with their monthly
-- periods, and the posting rules that turn payroll runs and invoices into entries. All per
-- tenant; the seed rows are written by ChartSetupService (POST /finance/setup), not here.

CREATE TABLE IF NOT EXISTS finance.accounts (
    tenant_id TEXT NOT NULL,
    code TEXT NOT NULL CHECK (code ~ '^[1-9][0-9]{0,9}$'),
    name TEXT NOT NULL CHECK (btrim(name) <> ''),
    class_no SMALLINT NOT NULL CHECK (class_no BETWEEN 1 AND 9),
    account_type TEXT NOT NULL CHECK (account_type IN ('asset', 'liability', 'equity', 'income', 'expense')),
    is_postable BOOLEAN NOT NULL DEFAULT TRUE,
    parent_code TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (tenant_id, code),
    CHECK (class_no = substr(code, 1, 1)::int),
    FOREIGN KEY (tenant_id, parent_code) REFERENCES finance.accounts (tenant_id, code)
);

CREATE TABLE IF NOT EXISTS finance.journals (
    tenant_id TEXT NOT NULL,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    journal_type TEXT NOT NULL CHECK (journal_type IN ('payroll', 'sales', 'purchases', 'bank', 'cash', 'general')),
    PRIMARY KEY (tenant_id, code)
);

-- SYSCOHADA: the fiscal year is the calendar year, cut into twelve monthly periods.
CREATE TABLE IF NOT EXISTS finance.fiscal_years (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    year INTEGER NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, year),
    CHECK (end_date > start_date)
);

CREATE TABLE IF NOT EXISTS finance.periods (
    tenant_id TEXT NOT NULL,
    period DATE NOT NULL CHECK (EXTRACT(DAY FROM period) = 1),
    fiscal_year_id TEXT NOT NULL REFERENCES finance.fiscal_years (id),
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed')),
    closed_by TEXT,
    closed_at TIMESTAMPTZ,
    PRIMARY KEY (tenant_id, period)
);

-- (source, source_kind, code) -> accounts. code '*' is the fallback of its kind. Payment and
-- invoice rules also name the journal their entry goes to.
CREATE TABLE IF NOT EXISTS finance.posting_rules (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    source TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    code TEXT NOT NULL,
    debit_account_code TEXT,
    credit_account_code TEXT,
    journal_code TEXT,
    status TEXT NOT NULL DEFAULT 'to_confirm' CHECK (status IN ('to_confirm', 'confirmed')),
    confirmed_by TEXT,
    confirmed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, source, source_kind, code),
    CHECK (debit_account_code IS NOT NULL OR credit_account_code IS NOT NULL),
    FOREIGN KEY (tenant_id, debit_account_code) REFERENCES finance.accounts (tenant_id, code),
    FOREIGN KEY (tenant_id, credit_account_code) REFERENCES finance.accounts (tenant_id, code),
    FOREIGN KEY (tenant_id, journal_code) REFERENCES finance.journals (tenant_id, code)
);
```

- [ ] **Step 7: Write the failing integration test**

`backend/modules/finance/api/test_ledger_setup_integration.py`:

```python
"""Installing the SYSCOHADA seed, and opening and closing accounting periods."""
from __future__ import annotations

import datetime

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from modules.finance.api.chart_setup_service import ChartSetupService
from modules.finance.api.period_service import PeriodService
from modules.finance.domain.syscohada_chart import CHART, DEFAULT_POSTING_RULES, JOURNALS

TENANT = "integration-test-ledger-setup"
MARCH = datetime.date(2030, 3, 1)


@pytest.fixture
def actor(db) -> str:
    user = str(ULID())
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (user, TENANT, f"{user}@test.local"),
    )
    return user


def test_setup_installs_the_chart_journals_and_rules_once(db, actor):
    first = ChartSetupService(db).ensure_defaults(tenant_id=TENANT, actor_id=actor)
    assert first == {"accounts": len(CHART), "journals": len(JOURNALS), "posting_rules": len(DEFAULT_POSTING_RULES)}
    again = ChartSetupService(db).ensure_defaults(tenant_id=TENANT, actor_id=actor)
    assert again == {"accounts": 0, "journals": 0, "posting_rules": 0}
    statuses = {row[0] for row in db.execute("SELECT status FROM finance.posting_rules WHERE tenant_id = %s", (TENANT,))}
    assert statuses == {"to_confirm"}
    audited = db.execute(
        "SELECT count(*) FROM core.audit_log WHERE tenant_id = %s AND action = 'ledger_setup.applied'", (TENANT,)
    ).fetchone()[0]
    assert audited == 1


def test_opening_a_year_creates_twelve_open_periods(db, actor):
    periods = PeriodService(db)
    assert isinstance(periods.open_fiscal_year(tenant_id=TENANT, actor_id=actor, year=2030), Ok)
    listed = periods.list_periods(tenant_id=TENANT, year=2030)
    assert [p["period"] for p in listed] == [datetime.date(2030, month, 1) for month in range(1, 13)]
    assert {p["status"] for p in listed} == {"open"}
    again = periods.open_fiscal_year(tenant_id=TENANT, actor_id=actor, year=2030)
    assert isinstance(again, Err) and again.code == "FISCAL_YEAR_EXISTS"


def test_a_closed_period_refuses_postings_until_reopened(db, actor):
    periods = PeriodService(db)
    periods.open_fiscal_year(tenant_id=TENANT, actor_id=actor, year=2030)
    assert isinstance(periods.close_period(tenant_id=TENANT, actor_id=actor, period=MARCH), Ok)
    refused = periods.ensure_open(tenant_id=TENANT, day=datetime.date(2030, 3, 17))
    assert isinstance(refused, Err) and refused.code == "PERIOD_CLOSED" and refused.message_fr
    twice = periods.close_period(tenant_id=TENANT, actor_id=actor, period=MARCH)
    assert isinstance(twice, Err) and twice.code == "INVALID_TRANSITION"
    assert isinstance(periods.reopen_period(tenant_id=TENANT, actor_id=actor, period=MARCH), Ok)
    assert periods.ensure_open(tenant_id=TENANT, day=datetime.date(2030, 3, 17)) == Ok(MARCH)
    actions = {
        row[0]
        for row in db.execute("SELECT action FROM core.audit_log WHERE tenant_id = %s AND entity_type = 'period'", (TENANT,))
    }
    assert actions == {"period.closed", "period.reopened"}


def test_a_date_without_a_period_is_period_missing(db, actor):
    refused = PeriodService(db).ensure_open(tenant_id=TENANT, day=datetime.date(2031, 1, 5))
    assert isinstance(refused, Err) and refused.code == "PERIOD_MISSING"


def test_a_period_is_named_by_its_first_day(db, actor):
    periods = PeriodService(db)
    periods.open_fiscal_year(tenant_id=TENANT, actor_id=actor, year=2030)
    refused = periods.close_period(tenant_id=TENANT, actor_id=actor, period=datetime.date(2030, 3, 2))
    assert isinstance(refused, Err) and refused.code == "INVALID_PERIOD"
```

- [ ] **Step 8: Run it to verify it fails**

Run: `.venv/Scripts/python -m pytest modules/finance/api/test_ledger_setup_integration.py -q`
Expected: collection error `No module named 'modules.finance.api.chart_setup_service'`.

- [ ] **Step 9: Write the services**

`backend/modules/finance/api/chart_setup_service.py`:

```python
"""Installs the SYSCOHADA seed for a tenant: chart, journals and default posting rules.

Idempotent: rows that already exist — possibly renamed or re-mapped by the accountant — are left
alone, so running it again after an upgrade only adds what is new."""
from __future__ import annotations

import psycopg
from ulid import ULID

from core.audit import record_audit
from modules.finance.domain.syscohada_chart import CHART, DEFAULT_POSTING_RULES, JOURNALS


class ChartSetupService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def ensure_defaults(self, *, tenant_id: str, actor_id: str) -> dict[str, int]:
        counts = {"accounts": 0, "journals": 0, "posting_rules": 0}
        for account in CHART:
            cursor = self._connection.execute(
                """
                INSERT INTO finance.accounts (tenant_id, code, name, class_no, account_type, is_postable, parent_code)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (tenant_id, code) DO NOTHING
                """,
                (
                    tenant_id, account.code, account.name, account.class_no,
                    account.account_type, account.is_postable, account.parent_code,
                ),
            )
            counts["accounts"] += cursor.rowcount
        for code, name, journal_type in JOURNALS:
            cursor = self._connection.execute(
                """
                INSERT INTO finance.journals (tenant_id, code, name, journal_type)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (tenant_id, code) DO NOTHING
                """,
                (tenant_id, code, name, journal_type),
            )
            counts["journals"] += cursor.rowcount
        for rule in DEFAULT_POSTING_RULES:
            cursor = self._connection.execute(
                """
                INSERT INTO finance.posting_rules
                    (id, tenant_id, source, source_kind, code, debit_account_code, credit_account_code, journal_code)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (tenant_id, source, source_kind, code) DO NOTHING
                """,
                (
                    str(ULID()), tenant_id, rule.source, rule.source_kind, rule.code,
                    rule.debit_account_code, rule.credit_account_code, rule.journal_code,
                ),
            )
            counts["posting_rules"] += cursor.rowcount
        if any(counts.values()):
            record_audit(
                self._connection,
                tenant_id=tenant_id,
                actor_id=actor_id,
                action="ledger_setup.applied",
                entity_type="ledger_setup",
                entity_id=tenant_id,
                payload=counts,
            )
        return counts
```

`backend/modules/finance/api/period_service.py`:

```python
"""Fiscal years (calendar years, SYSCOHADA) and their monthly periods, open or closed.

Nothing is posted into a closed period; `ensure_open` is the one check every posting goes through."""
from __future__ import annotations

import datetime

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result

PERIOD_KEYS = ("period", "year", "status", "closed_by", "closed_at")


def period_missing(period: datetime.date) -> Err:
    return Err(
        "PERIOD_MISSING",
        f"no accounting period for {period:%Y-%m}; open fiscal year {period.year} first",
        f"aucune période comptable pour {period:%m/%Y} ; ouvrez d'abord l'exercice {period.year}",
    )


class PeriodService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def open_fiscal_year(self, *, tenant_id: str, actor_id: str, year: int) -> Result[dict]:
        if not 2000 <= year <= 2100:
            return Err(
                "INVALID_PERIOD",
                f"{year} is not a fiscal year this ledger accepts (2000 to 2100)",
                f"{year} n'est pas un exercice accepté (2000 à 2100)",
            )
        exists = self._connection.execute(
            "SELECT 1 FROM finance.fiscal_years WHERE tenant_id = %s AND year = %s", (tenant_id, year)
        ).fetchone()
        if exists:
            return Err("FISCAL_YEAR_EXISTS", f"fiscal year {year} is already open", f"l'exercice {year} est déjà ouvert")
        fiscal_year_id = str(ULID())
        start, end = datetime.date(year, 1, 1), datetime.date(year, 12, 31)
        self._connection.execute(
            """
            INSERT INTO finance.fiscal_years (id, tenant_id, year, start_date, end_date, created_by)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (fiscal_year_id, tenant_id, year, start, end, actor_id),
        )
        for month in range(1, 13):
            self._connection.execute(
                "INSERT INTO finance.periods (tenant_id, period, fiscal_year_id) VALUES (%s, %s, %s)",
                (tenant_id, datetime.date(year, month, 1), fiscal_year_id),
            )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="fiscal_year.opened",
            entity_type="fiscal_year",
            entity_id=fiscal_year_id,
            payload={"year": year},
        )
        return Ok({"id": fiscal_year_id, "year": year, "start_date": start, "end_date": end})

    def list_periods(self, *, tenant_id: str, year: int | None = None) -> list[dict]:
        sql = """
            SELECT p.period, f.year, p.status, p.closed_by, p.closed_at
            FROM finance.periods p
            JOIN finance.fiscal_years f ON f.id = p.fiscal_year_id
            WHERE p.tenant_id = %s
        """
        params: list[object] = [tenant_id]
        if year is not None:
            sql += " AND f.year = %s"
            params.append(year)
        rows = self._connection.execute(sql + " ORDER BY p.period", params).fetchall()
        return [dict(zip(PERIOD_KEYS, row)) for row in rows]

    def ensure_open(self, *, tenant_id: str, day: datetime.date) -> Result[datetime.date]:
        """The period `day` falls in, if it exists and is open."""
        period = day.replace(day=1)
        row = self._connection.execute(
            "SELECT status FROM finance.periods WHERE tenant_id = %s AND period = %s", (tenant_id, period)
        ).fetchone()
        if row is None:
            return period_missing(period)
        if row[0] == "closed":
            return Err(
                "PERIOD_CLOSED",
                f"period {period:%Y-%m} is closed; nothing can be posted into it",
                f"la période {period:%m/%Y} est clôturée ; aucune écriture ne peut y être passée",
            )
        return Ok(period)

    def close_period(self, *, tenant_id: str, actor_id: str, period: datetime.date) -> Result[dict]:
        return self._set_status(tenant_id=tenant_id, actor_id=actor_id, period=period, status="closed")

    def reopen_period(self, *, tenant_id: str, actor_id: str, period: datetime.date) -> Result[dict]:
        return self._set_status(tenant_id=tenant_id, actor_id=actor_id, period=period, status="open")

    def _set_status(self, *, tenant_id: str, actor_id: str, period: datetime.date, status: str) -> Result[dict]:
        if period.day != 1:
            return Err(
                "INVALID_PERIOD",
                "a period is named by the first day of its month",
                "une période est désignée par le premier jour de son mois",
            )
        row = self._connection.execute(
            "SELECT status FROM finance.periods WHERE tenant_id = %s AND period = %s FOR UPDATE", (tenant_id, period)
        ).fetchone()
        if row is None:
            return period_missing(period)
        if row[0] == status:
            word_en, word_fr = ("closed", "clôturée") if status == "closed" else ("open", "ouverte")
            return Err(
                "INVALID_TRANSITION",
                f"period {period:%Y-%m} is already {word_en}",
                f"la période {period:%m/%Y} est déjà {word_fr}",
            )
        if status == "closed":
            self._connection.execute(
                """
                UPDATE finance.periods SET status = 'closed', closed_by = %s, closed_at = NOW()
                WHERE tenant_id = %s AND period = %s
                """,
                (actor_id, tenant_id, period),
            )
        else:
            self._connection.execute(
                """
                UPDATE finance.periods SET status = 'open', closed_by = NULL, closed_at = NULL
                WHERE tenant_id = %s AND period = %s
                """,
                (tenant_id, period),
            )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="period.closed" if status == "closed" else "period.reopened",
            entity_type="period",
            entity_id=period.isoformat(),
            payload={"period": period.isoformat(), "from_status": row[0], "to_status": status},
        )
        return Ok(next(p for p in self.list_periods(tenant_id=tenant_id, year=period.year) if p["period"] == period))
```

- [ ] **Step 10: Apply the migration and run the tests**

Run (from `backend/`):
`.venv/Scripts/python -c "from dotenv import load_dotenv; load_dotenv('../.env'); from core.migrations.runner import apply_all_migrations; apply_all_migrations()"`
then `.venv/Scripts/python -m pytest modules/finance core/test_error_translations.py -q -rs`
Expected: all PASS, and the `-rs` summary lists **no** skipped `*_integration.py` test (a skip means the DB is unreachable — fix that before going on).

- [ ] **Step 11: Commit**

```bash
git add backend/modules/finance/domain/syscohada_chart.py backend/modules/finance/domain/test_syscohada_chart.py backend/modules/finance/migrations/0002_finance_ledger_master_data.sql backend/modules/finance/api/chart_setup_service.py backend/modules/finance/api/period_service.py backend/modules/finance/api/test_ledger_setup_integration.py backend/modules/finance/module.json
git commit -m "feat(finance): SYSCOHADA chart seed, journals, fiscal years and periods

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Journal entries, triggers and the single posting path

**Files:**
- Create: `backend/modules/finance/migrations/0003_finance_journal_entries.sql`
- Create: `backend/modules/finance/api/ledger_sql.py`
- Create: `backend/modules/finance/api/ledger_posting_service.py`
- Create: `backend/modules/finance/testing_support.py`
- Create: `backend/modules/finance/conftest.py`
- Modify: `backend/events/CATALOG.md` (one row added)
- Test: `backend/modules/finance/api/test_ledger_posting_integration.py`

**Interfaces:**
- Consumes: Task 1 (`Account`, `EntryLine`, `SourceRef`, `build_entry`, `validate_lines`, `reverse_lines`, `totals`), Task 3 (`PeriodService.ensure_open`, `ChartSetupService`, tables), `core.domain.sequences.next_sequence_value`, `core.events.outbox.publish_event`, `core.audit.record_audit`.
- Produces:
  - Tables `finance.journal_entries` (unique `(tenant_id, source_module, source_id, source_kind)` when sourced, unique `(tenant_id, number)`), `finance.journal_lines`, `finance.posting_failures` (unique `(tenant_id, source_module, source_id, source_kind)`), triggers raising `ENTRY_POSTED: …` / `ENTRY_UNBALANCED: …`.
  - `ledger_sql.ENTRY_KEYS`, `ENTRY_SELECT` (ends with the `FROM … LEFT JOIN LATERAL … ON TRUE`, callers append `WHERE …`), `entry_dict(row) -> dict`, `STATUS_FR: dict[str, str]`.
  - Entry dict keys: `id, number, journal_code, entry_date, period, label, reference, status, source_module, source_id, source_kind, reversal_of, created_by, created_at, posted_by, posted_at, total_debit, total_credit`.
  - `SYSTEM_ACTOR = "system:event-consumer"`, `entry_not_found(entry_id) -> Err`.
  - `LedgerPostingService(connection)`: `load_accounts(*, tenant_id, codes) -> dict[str, Account]`; `journal_codes(*, tenant_id) -> set[str]`; `get_summary(*, tenant_id, entry_id) -> dict | None`; `find_by_source(*, tenant_id, source: SourceRef) -> dict | None`; `lines_of(entry_id) -> list[EntryLine]`; `check_draft(*, tenant_id, journal_code, entry_date, label, lines) -> Result[list[EntryLine]]`; `check_postable(*, tenant_id, journal_code, entry_date, lines) -> Result[list[EntryLine]]`; `insert_draft(*, tenant_id, actor_id, journal_code, entry_date, label, lines, reference=None, source=None, reversal_of=None) -> Result[str]` (no audit); `replace_lines(*, tenant_id, entry_id, lines) -> None`; `post_draft(*, tenant_id, actor_id, entry_id, correlation_id, causation_id=None) -> Result[dict]`; `post_entry(*, tenant_id, actor_id, journal_code, entry_date, label, lines, correlation_id, source=None, reference=None, reversal_of=None, causation_id=None) -> Result[dict]`; `reverse_entry(*, tenant_id, actor_id, entry_id, entry_date, correlation_id, causation_id=None) -> Result[dict]`.
  - Entry numbers: `{journal}-{year}-{6 digits}` from `core.sequences` name `finance.entry.{journal}.{year}`.
  - Test helpers: `modules.finance.testing_support.NoCommitConnection`; fixture `ledger` (from `modules/finance/conftest.py`) → `{"db", "tenant", "actor", "year"}` with the chart, journals, default rules and fiscal year 2030 installed for tenant `integration-test-ledger`.

- [ ] **Step 1: Write the migration**

`backend/modules/finance/migrations/0003_finance_journal_entries.sql`:

```sql
-- SYSCOHADA ledger, entries: journal entries and their lines, the automatic postings that were
-- refused (and why), and the triggers that keep the books honest: a posted entry never changes
-- except posted -> reversed, its lines never change, and at commit every posted entry balances.

CREATE TABLE IF NOT EXISTS finance.journal_entries (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    journal_code TEXT NOT NULL,
    number TEXT,
    entry_date DATE NOT NULL,
    period DATE NOT NULL,
    label TEXT NOT NULL CHECK (btrim(label) <> ''),
    reference TEXT,
    source_module TEXT,
    source_id TEXT,
    source_kind TEXT,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'posted', 'reversed')),
    reversal_of TEXT REFERENCES finance.journal_entries (id),
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    posted_by TEXT,
    posted_at TIMESTAMPTZ,
    FOREIGN KEY (tenant_id, journal_code) REFERENCES finance.journals (tenant_id, code),
    FOREIGN KEY (tenant_id, period) REFERENCES finance.periods (tenant_id, period),
    CHECK (period = date_trunc('month', entry_date)::date),
    CHECK ((source_module IS NULL) = (source_id IS NULL) AND (source_id IS NULL) = (source_kind IS NULL)),
    CHECK (status = 'draft' OR (number IS NOT NULL AND posted_at IS NOT NULL))
);

-- One entry per (source, kind): the second delivery of an event finds the first entry.
CREATE UNIQUE INDEX IF NOT EXISTS journal_entries_source_uq
    ON finance.journal_entries (tenant_id, source_module, source_id, source_kind)
    WHERE source_module IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS journal_entries_number_uq
    ON finance.journal_entries (tenant_id, number) WHERE number IS NOT NULL;
CREATE INDEX IF NOT EXISTS journal_entries_date_idx ON finance.journal_entries (tenant_id, entry_date);
CREATE INDEX IF NOT EXISTS journal_entries_source_idx ON finance.journal_entries (tenant_id, source_module, source_id);

CREATE TABLE IF NOT EXISTS finance.journal_lines (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    entry_id TEXT NOT NULL REFERENCES finance.journal_entries (id) ON DELETE CASCADE,
    line_no INTEGER NOT NULL CHECK (line_no > 0),
    account_code TEXT NOT NULL,
    debit NUMERIC(18,0) NOT NULL DEFAULT 0 CHECK (debit >= 0),
    credit NUMERIC(18,0) NOT NULL DEFAULT 0 CHECK (credit >= 0),
    label TEXT,
    partner_id TEXT REFERENCES core.partners (id),
    employee_ref TEXT,
    UNIQUE (entry_id, line_no),
    CHECK ((debit = 0) <> (credit = 0)),
    FOREIGN KEY (tenant_id, account_code) REFERENCES finance.accounts (tenant_id, code)
);
CREATE INDEX IF NOT EXISTS journal_lines_account_idx ON finance.journal_lines (tenant_id, account_code);

-- An automatic posting that was refused: the event it came from and why. The run page reads
-- it; POST /finance/posting-failures/{id}/retry replays the envelope once the cause is fixed.
CREATE TABLE IF NOT EXISTS finance.posting_failures (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    source_module TEXT NOT NULL,
    source_id TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    event_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    envelope JSONB NOT NULL,
    error_code TEXT NOT NULL,
    error_message TEXT NOT NULL,
    error_message_fr TEXT,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'resolved', 'cancelled')),
    failed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMPTZ,
    UNIQUE (tenant_id, source_module, source_id, source_kind)
);

CREATE OR REPLACE FUNCTION finance.guard_posted_entry() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.status <> 'draft' THEN
            RAISE EXCEPTION 'ENTRY_POSTED: journal entry % is % and cannot be deleted', OLD.id, OLD.status;
        END IF;
        RETURN OLD;
    END IF;
    IF OLD.status = 'draft' THEN
        RETURN NEW;
    END IF;
    IF OLD.status = 'posted' AND NEW.status = 'reversed'
       AND (NEW.id, NEW.tenant_id, NEW.journal_code, NEW.number, NEW.entry_date, NEW.period, NEW.label,
            NEW.reference, NEW.source_module, NEW.source_id, NEW.source_kind, NEW.reversal_of,
            NEW.created_by, NEW.posted_by, NEW.posted_at)
           IS NOT DISTINCT FROM
           (OLD.id, OLD.tenant_id, OLD.journal_code, OLD.number, OLD.entry_date, OLD.period, OLD.label,
            OLD.reference, OLD.source_module, OLD.source_id, OLD.source_kind, OLD.reversal_of,
            OLD.created_by, OLD.posted_by, OLD.posted_at) THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'ENTRY_POSTED: journal entry % is % and cannot be changed', OLD.id, OLD.status;
END;
$$;

DROP TRIGGER IF EXISTS journal_entries_guard ON finance.journal_entries;
CREATE TRIGGER journal_entries_guard
    BEFORE UPDATE OR DELETE ON finance.journal_entries
    FOR EACH ROW EXECUTE FUNCTION finance.guard_posted_entry();

CREATE OR REPLACE FUNCTION finance.guard_posted_lines() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    target TEXT;
    parent_status TEXT;
BEGIN
    IF TG_OP = 'UPDATE' AND NEW.entry_id IS DISTINCT FROM OLD.entry_id THEN
        RAISE EXCEPTION 'ENTRY_POSTED: a line cannot move to another journal entry';
    END IF;
    IF TG_OP = 'DELETE' THEN
        target := OLD.entry_id;
    ELSE
        target := NEW.entry_id;
    END IF;
    -- NULL when the entry itself is being deleted, which only a draft can be.
    SELECT status INTO parent_status FROM finance.journal_entries WHERE id = target;
    IF parent_status IS NOT NULL AND parent_status <> 'draft' THEN
        RAISE EXCEPTION 'ENTRY_POSTED: the lines of journal entry % are frozen once it is %', target, parent_status;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS journal_lines_guard ON finance.journal_lines;
CREATE TRIGGER journal_lines_guard
    BEFORE INSERT OR UPDATE OR DELETE ON finance.journal_lines
    FOR EACH ROW EXECUTE FUNCTION finance.guard_posted_lines();

-- Re-checked at commit, whatever wrote the rows: a posted entry has two or more lines and equal sides.
CREATE OR REPLACE FUNCTION finance.check_entry_balance() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    target TEXT;
    entry_status TEXT;
    total_debit NUMERIC;
    total_credit NUMERIC;
    line_count INTEGER;
BEGIN
    IF TG_TABLE_NAME = 'journal_entries' THEN
        target := NEW.id;
    ELSIF TG_OP = 'DELETE' THEN
        target := OLD.entry_id;
    ELSE
        target := NEW.entry_id;
    END IF;
    SELECT status INTO entry_status FROM finance.journal_entries WHERE id = target;
    IF entry_status IS NULL OR entry_status = 'draft' THEN
        RETURN NULL;
    END IF;
    SELECT COALESCE(SUM(debit), 0), COALESCE(SUM(credit), 0), COUNT(*)
      INTO total_debit, total_credit, line_count
      FROM finance.journal_lines WHERE entry_id = target;
    IF line_count < 2 OR total_debit = 0 OR total_debit <> total_credit THEN
        RAISE EXCEPTION 'ENTRY_UNBALANCED: journal entry % has debit % and credit % over % line(s)',
            target, total_debit, total_credit, line_count;
    END IF;
    RETURN NULL;
END;
$$;

DROP TRIGGER IF EXISTS journal_entries_balanced ON finance.journal_entries;
CREATE CONSTRAINT TRIGGER journal_entries_balanced
    AFTER INSERT OR UPDATE ON finance.journal_entries
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION finance.check_entry_balance();

DROP TRIGGER IF EXISTS journal_lines_balanced ON finance.journal_lines;
CREATE CONSTRAINT TRIGGER journal_lines_balanced
    AFTER INSERT OR UPDATE OR DELETE ON finance.journal_lines
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION finance.check_entry_balance();
```

Apply it (from `backend/`): `.venv/Scripts/python -c "from dotenv import load_dotenv; load_dotenv('../.env'); from core.migrations.runner import apply_all_migrations; apply_all_migrations()"`

- [ ] **Step 2: Add the test helpers**

`backend/modules/finance/testing_support.py`:

```python
"""Test helpers for the finance module (not a test file itself)."""
from __future__ import annotations


class NoCommitConnection:
    """The `db` fixture's connection with commit and rollback made no-ops.

    Code that manages its own transaction — the event registry (`core.events.consumers._process`),
    the ledger consumers, the routers — runs against it without ending the fixture's transaction,
    so everything still rolls back when the test ends."""

    def __init__(self, connection) -> None:
        self._connection = connection

    def __getattr__(self, name):
        return getattr(self._connection, name)

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> bool:
        return False
```

`backend/modules/finance/conftest.py`:

```python
"""The `ledger` fixture: a tenant with the SYSCOHADA seed and fiscal year 2030 open, inside the
rolled-back `db` connection of backend/conftest.py (so it skips when no database is reachable)."""
from __future__ import annotations

import pytest
from ulid import ULID

LEDGER_TENANT = "integration-test-ledger"
LEDGER_YEAR = 2030


@pytest.fixture
def ledger(db) -> dict:
    from core.domain.result import Ok
    from modules.finance.api.chart_setup_service import ChartSetupService
    from modules.finance.api.period_service import PeriodService

    actor = str(ULID())
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (actor, LEDGER_TENANT, f"{actor}@test.local"),
    )
    ChartSetupService(db).ensure_defaults(tenant_id=LEDGER_TENANT, actor_id=actor)
    opened = PeriodService(db).open_fiscal_year(tenant_id=LEDGER_TENANT, actor_id=actor, year=LEDGER_YEAR)
    assert isinstance(opened, Ok), opened
    return {"db": db, "tenant": LEDGER_TENANT, "actor": actor, "year": LEDGER_YEAR}
```

- [ ] **Step 3: Write the failing test**

`backend/modules/finance/api/test_ledger_posting_integration.py`:

```python
"""The single posting path: checks, numbering, the posted event, immutability, reversal."""
from __future__ import annotations

import datetime
from decimal import Decimal

import psycopg
import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from modules.finance.api.ledger_posting_service import LedgerPostingService
from modules.finance.api.period_service import PeriodService
from modules.finance.domain.ledger import EntryLine, SourceRef

D = Decimal
DAY = datetime.date(2030, 1, 20)
CAPITAL = [EntryLine("521", debit=D(1000000)), EntryLine("101", credit=D(1000000))]


def _post(ledger, *, lines=None, day=DAY, source=None, journal="OD"):
    return LedgerPostingService(ledger["db"]).post_entry(
        tenant_id=ledger["tenant"],
        actor_id=ledger["actor"],
        journal_code=journal,
        entry_date=day,
        label="Apport en capital",
        lines=lines or CAPITAL,
        correlation_id=str(ULID()),
        source=source,
    )


def _count(ledger) -> int:
    return ledger["db"].execute(
        "SELECT count(*) FROM finance.journal_entries WHERE tenant_id = %s", (ledger["tenant"],)
    ).fetchone()[0]


def test_a_balanced_entry_is_posted_numbered_announced_and_audited(ledger):
    result = _post(ledger)
    assert isinstance(result, Ok), result
    entry = result.value
    assert entry["status"] == "posted" and entry["number"] == "OD-2030-000001"
    assert entry["period"] == datetime.date(2030, 1, 1)
    assert entry["total_debit"] == entry["total_credit"] == D(1000000)
    db = ledger["db"]
    envelope = db.execute(
        "SELECT payload FROM events.outbox WHERE event_type = 'finance.journal_entry.posted' AND tenant_id = %s",
        (ledger["tenant"],),
    ).fetchone()[0]
    assert envelope["payload"] == {"entry_id": entry["id"], "journal_code": "OD", "source_module": None, "source_id": None}
    audited = db.execute(
        "SELECT count(*) FROM core.audit_log WHERE entity_id = %s AND action = 'journal_entry.posted'", (entry["id"],)
    ).fetchone()[0]
    assert audited == 1
    db.execute("SET CONSTRAINTS ALL IMMEDIATE")  # the deferred balance trigger accepts it


def test_posting_into_a_closed_period_is_refused_and_writes_nothing(ledger):
    PeriodService(ledger["db"]).close_period(tenant_id=ledger["tenant"], actor_id=ledger["actor"], period=datetime.date(2030, 1, 1))
    result = _post(ledger)
    assert isinstance(result, Err) and result.code == "PERIOD_CLOSED"
    assert _count(ledger) == 0


def test_a_date_outside_every_fiscal_year_is_period_missing(ledger):
    result = _post(ledger, day=datetime.date(2031, 2, 1))
    assert isinstance(result, Err) and result.code == "PERIOD_MISSING"


def test_an_unbalanced_entry_is_refused_and_writes_nothing(ledger):
    result = _post(ledger, lines=[EntryLine("521", debit=D(10)), EntryLine("101", credit=D(9))])
    assert isinstance(result, Err) and result.code == "ENTRY_UNBALANCED"
    assert _count(ledger) == 0


def test_a_heading_account_is_refused(ledger):
    result = _post(ledger, lines=[EntryLine("52", debit=D(10)), EntryLine("101", credit=D(10))])
    assert isinstance(result, Err) and result.code == "ACCOUNT_NOT_POSTABLE"


def test_an_unknown_journal_is_refused(ledger):
    result = _post(ledger, journal="XYZ")
    assert isinstance(result, Err) and result.code == "NOT_FOUND"


def test_the_same_source_posts_once(ledger):
    source = SourceRef("payroll", "RUN-1", "payroll_run")
    first = _post(ledger, source=source)
    second = _post(ledger, source=source)
    assert first.value["id"] == second.value["id"]
    assert _count(ledger) == 1


def test_posted_lines_and_headers_are_frozen(ledger):
    entry_id = _post(ledger).value["id"]
    db = ledger["db"]
    for statement in (
        "UPDATE finance.journal_lines SET debit = debit + 1 WHERE entry_id = %s",
        "DELETE FROM finance.journal_lines WHERE entry_id = %s",
        "UPDATE finance.journal_entries SET label = 'changed' WHERE id = %s",
        "DELETE FROM finance.journal_entries WHERE id = %s",
    ):
        with pytest.raises(psycopg.errors.RaiseException, match="ENTRY_POSTED"):
            with db.transaction():
                db.execute(statement, (entry_id,))
    with pytest.raises(psycopg.errors.RaiseException, match="ENTRY_POSTED"):
        with db.transaction():
            db.execute(
                """
                INSERT INTO finance.journal_lines (id, tenant_id, entry_id, line_no, account_code, debit)
                VALUES (%s, %s, %s, 99, '521', 1)
                """,
                (str(ULID()), ledger["tenant"], entry_id),
            )


def test_the_deferred_trigger_refuses_a_posted_unbalanced_entry(ledger):
    db = ledger["db"]
    entry_id = str(ULID())
    with pytest.raises(psycopg.errors.RaiseException, match="ENTRY_UNBALANCED"):
        with db.transaction():
            db.execute(
                """
                INSERT INTO finance.journal_entries (id, tenant_id, journal_code, entry_date, period, label, created_by)
                VALUES (%s, %s, 'OD', '2030-01-20', '2030-01-01', 'bypass', %s)
                """,
                (entry_id, ledger["tenant"], ledger["actor"]),
            )
            db.execute(
                """
                INSERT INTO finance.journal_lines (id, tenant_id, entry_id, line_no, account_code, debit)
                VALUES (%s, %s, %s, 1, '521', 500)
                """,
                (str(ULID()), ledger["tenant"], entry_id),
            )
            db.execute(
                "UPDATE finance.journal_entries SET status = 'posted', number = 'OD-TEST-1', posted_at = NOW() WHERE id = %s",
                (entry_id,),
            )
            db.execute("SET CONSTRAINTS ALL IMMEDIATE")


def test_reversing_mirrors_the_entry_and_marks_it_reversed(ledger):
    posting = LedgerPostingService(ledger["db"])
    original = _post(ledger, source=SourceRef("payroll", "RUN-2", "payroll_run")).value
    reversal = posting.reverse_entry(
        tenant_id=ledger["tenant"], actor_id=ledger["actor"], entry_id=original["id"],
        entry_date=datetime.date(2030, 2, 3), correlation_id=str(ULID()),
    )
    assert isinstance(reversal, Ok), reversal
    assert reversal.value["reversal_of"] == original["id"]
    assert reversal.value["source_kind"] == "payroll_run_reversal"
    assert reversal.value["label"] == f"Extourne de {original['number']}"
    lines = ledger["db"].execute(
        "SELECT account_code, debit, credit FROM finance.journal_lines WHERE entry_id = %s ORDER BY line_no",
        (reversal.value["id"],),
    ).fetchall()
    assert lines == [("521", D(0), D(1000000)), ("101", D(1000000), D(0))]
    assert posting.get_summary(tenant_id=ledger["tenant"], entry_id=original["id"])["status"] == "reversed"
    again = posting.reverse_entry(
        tenant_id=ledger["tenant"], actor_id=ledger["actor"], entry_id=original["id"],
        entry_date=datetime.date(2030, 2, 3), correlation_id=str(ULID()),
    )
    assert isinstance(again, Err) and again.code == "INVALID_TRANSITION"
    ledger["db"].execute("SET CONSTRAINTS ALL IMMEDIATE")


def test_posting_an_entry_twice_is_refused(ledger):
    entry = _post(ledger).value
    again = LedgerPostingService(ledger["db"]).post_draft(
        tenant_id=ledger["tenant"], actor_id=ledger["actor"], entry_id=entry["id"], correlation_id=str(ULID())
    )
    assert isinstance(again, Err) and again.code == "ENTRY_POSTED"
```

- [ ] **Step 4: Run it to verify it fails**

Run: `.venv/Scripts/python -m pytest modules/finance/api/test_ledger_posting_integration.py -q`
Expected: collection error `No module named 'modules.finance.api.ledger_posting_service'`.

- [ ] **Step 5: Write the shared SQL and the posting service**

`backend/modules/finance/api/ledger_sql.py`:

```python
"""The SELECT every entry read shares, so the posting, query and manual-entry services return the
same dict for an entry. Callers append their own WHERE / ORDER BY."""
from __future__ import annotations

ENTRY_KEYS = (
    "id", "number", "journal_code", "entry_date", "period", "label", "reference", "status",
    "source_module", "source_id", "source_kind", "reversal_of", "created_by", "created_at",
    "posted_by", "posted_at", "total_debit", "total_credit",
)

ENTRY_SELECT = """
    SELECT e.id, e.number, e.journal_code, e.entry_date, e.period, e.label, e.reference, e.status,
           e.source_module, e.source_id, e.source_kind, e.reversal_of, e.created_by, e.created_at,
           e.posted_by, e.posted_at,
           COALESCE(t.total_debit, 0), COALESCE(t.total_credit, 0)
    FROM finance.journal_entries e
    LEFT JOIN LATERAL (
        SELECT SUM(l.debit) AS total_debit, SUM(l.credit) AS total_credit
        FROM finance.journal_lines l
        WHERE l.entry_id = e.id
    ) t ON TRUE
"""

STATUS_FR = {"draft": "brouillon", "posted": "comptabilisée", "reversed": "extournée"}


def entry_dict(row) -> dict:
    return dict(zip(ENTRY_KEYS, row))
```

`backend/modules/finance/api/ledger_posting_service.py`:

```python
"""The single write path of the ledger.

Every entry, manual or automatic, is inserted as a draft and posted through here, so the checks
(journal exists, period open, postable accounts, balanced sides), the entry number, the
`finance.journal_entry.posted` event and the audit row live in one place. `post_entry` checks
everything before it writes anything, so a refusal leaves nothing behind."""
from __future__ import annotations

import datetime
from typing import Iterable

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from core.domain.sequences import next_sequence_value
from core.events.outbox import publish_event
from modules.finance.api.ledger_sql import ENTRY_SELECT, STATUS_FR, entry_dict
from modules.finance.api.period_service import PeriodService
from modules.finance.domain.ledger import (
    Account,
    EntryLine,
    SourceRef,
    build_entry,
    reverse_lines,
    totals,
    validate_lines,
)

SYSTEM_ACTOR = "system:event-consumer"


def entry_not_found(entry_id: str) -> Err:
    return Err("NOT_FOUND", f"journal entry {entry_id} not found", f"écriture {entry_id} introuvable")


class LedgerPostingService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection
        self._periods = PeriodService(connection)

    # Reads the writer needs.

    def load_accounts(self, *, tenant_id: str, codes: Iterable[str]) -> dict[str, Account]:
        rows = self._connection.execute(
            """
            SELECT code, name, class_no, account_type, is_postable, parent_code
            FROM finance.accounts
            WHERE tenant_id = %s AND code = ANY(%s)
            """,
            (tenant_id, sorted(set(codes))),
        ).fetchall()
        return {row[0]: Account(*row) for row in rows}

    def journal_codes(self, *, tenant_id: str) -> set[str]:
        rows = self._connection.execute("SELECT code FROM finance.journals WHERE tenant_id = %s", (tenant_id,)).fetchall()
        return {row[0] for row in rows}

    def get_summary(self, *, tenant_id: str, entry_id: str) -> dict | None:
        row = self._connection.execute(
            f"{ENTRY_SELECT} WHERE e.tenant_id = %s AND e.id = %s", (tenant_id, entry_id)
        ).fetchone()
        return None if row is None else entry_dict(row)

    def find_by_source(self, *, tenant_id: str, source: SourceRef) -> dict | None:
        row = self._connection.execute(
            f"""{ENTRY_SELECT}
            WHERE e.tenant_id = %s AND e.source_module = %s AND e.source_id = %s AND e.source_kind = %s""",
            (tenant_id, source.module, source.id, source.kind),
        ).fetchone()
        return None if row is None else entry_dict(row)

    def lines_of(self, entry_id: str) -> list[EntryLine]:
        rows = self._connection.execute(
            """
            SELECT account_code, debit, credit, label, partner_id, employee_ref
            FROM finance.journal_lines WHERE entry_id = %s ORDER BY line_no
            """,
            (entry_id,),
        ).fetchall()
        return [EntryLine(*row) for row in rows]

    # Checks, without writing.

    def _check_frame(self, *, tenant_id: str, journal_code: str, entry_date: datetime.date) -> Result[datetime.date]:
        if journal_code not in self.journal_codes(tenant_id=tenant_id):
            return Err("NOT_FOUND", f"journal {journal_code} does not exist", f"le journal {journal_code} n'existe pas")
        return self._periods.ensure_open(tenant_id=tenant_id, day=entry_date)

    def check_draft(
        self, *, tenant_id: str, journal_code: str, entry_date: datetime.date, label: str | None, lines: Iterable[EntryLine]
    ) -> Result[list[EntryLine]]:
        """What a draft needs: a label, an existing journal, an open period, valid lines (sides may differ)."""
        if not (label or "").strip():
            return Err("INVALID_ENTRY", "an entry needs a label", "une écriture doit avoir un libellé")
        frame = self._check_frame(tenant_id=tenant_id, journal_code=journal_code, entry_date=entry_date)
        if isinstance(frame, Err):
            return frame
        lines = list(lines)
        return validate_lines(lines, self.load_accounts(tenant_id=tenant_id, codes=[line.account_code for line in lines]))

    def check_postable(
        self, *, tenant_id: str, journal_code: str, entry_date: datetime.date, lines: Iterable[EntryLine]
    ) -> Result[list[EntryLine]]:
        """Everything posting checks: journal, open period, postable accounts, balanced sides."""
        frame = self._check_frame(tenant_id=tenant_id, journal_code=journal_code, entry_date=entry_date)
        if isinstance(frame, Err):
            return frame
        lines = list(lines)
        return build_entry(lines, self.load_accounts(tenant_id=tenant_id, codes=[line.account_code for line in lines]))

    # Writes.

    def insert_draft(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        journal_code: str,
        entry_date: datetime.date,
        label: str,
        lines: Iterable[EntryLine],
        reference: str | None = None,
        source: SourceRef | None = None,
        reversal_of: str | None = None,
    ) -> Result[str]:
        """Writes a draft (no audit row: the caller audits what the user did)."""
        checked = self.check_draft(
            tenant_id=tenant_id, journal_code=journal_code, entry_date=entry_date, label=label, lines=lines
        )
        if isinstance(checked, Err):
            return checked
        entry_id = str(ULID())
        self._connection.execute(
            """
            INSERT INTO finance.journal_entries
                (id, tenant_id, journal_code, entry_date, period, label, reference,
                 source_module, source_id, source_kind, reversal_of, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                entry_id, tenant_id, journal_code, entry_date, entry_date.replace(day=1), label.strip(), reference,
                source.module if source else None, source.id if source else None, source.kind if source else None,
                reversal_of, actor_id,
            ),
        )
        self.replace_lines(tenant_id=tenant_id, entry_id=entry_id, lines=checked.value)
        return Ok(entry_id)

    def replace_lines(self, *, tenant_id: str, entry_id: str, lines: list[EntryLine]) -> None:
        self._connection.execute("DELETE FROM finance.journal_lines WHERE entry_id = %s", (entry_id,))
        for line_no, line in enumerate(lines, start=1):
            self._connection.execute(
                """
                INSERT INTO finance.journal_lines
                    (id, tenant_id, entry_id, line_no, account_code, debit, credit, label, partner_id, employee_ref)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    str(ULID()), tenant_id, entry_id, line_no, line.account_code, line.debit, line.credit,
                    line.label, line.partner_id, line.employee_ref,
                ),
            )

    def post_draft(
        self, *, tenant_id: str, actor_id: str, entry_id: str, correlation_id: str, causation_id: str | None = None
    ) -> Result[dict]:
        row = self._connection.execute(
            """
            SELECT journal_code, entry_date, status, number, source_module, source_id
            FROM finance.journal_entries WHERE id = %s AND tenant_id = %s FOR UPDATE
            """,
            (entry_id, tenant_id),
        ).fetchone()
        if row is None:
            return entry_not_found(entry_id)
        journal_code, entry_date, status, number, source_module, source_id = row
        if status != "draft":
            return Err(
                "ENTRY_POSTED",
                f"journal entry {number or entry_id} is already {status}",
                f"l'écriture {number or entry_id} est déjà {STATUS_FR[status]}",
            )
        checked = self.check_postable(
            tenant_id=tenant_id, journal_code=journal_code, entry_date=entry_date, lines=self.lines_of(entry_id)
        )
        if isinstance(checked, Err):
            return checked
        number = next_sequence_value(
            self._connection,
            tenant_id=tenant_id,
            name=f"finance.entry.{journal_code}.{entry_date.year}",
            prefix=f"{journal_code}-{entry_date.year}-",
        )
        self._connection.execute(
            """
            UPDATE finance.journal_entries
            SET status = 'posted', number = %s, posted_by = %s, posted_at = NOW()
            WHERE id = %s
            """,
            (number, actor_id, entry_id),
        )
        publish_event(
            self._connection,
            event_type="finance.journal_entry.posted",
            producer="finance",
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
            payload={
                "entry_id": entry_id,
                "journal_code": journal_code,
                "source_module": source_module,
                "source_id": source_id,
            },
        )
        total, _ = totals(checked.value)
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="journal_entry.posted",
            entity_type="journal_entry",
            entity_id=entry_id,
            payload={"number": number, "journal_code": journal_code, "entry_date": entry_date.isoformat(), "total": int(total)},
        )
        return Ok(self.get_summary(tenant_id=tenant_id, entry_id=entry_id))

    def post_entry(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        journal_code: str,
        entry_date: datetime.date,
        label: str,
        lines: Iterable[EntryLine],
        correlation_id: str,
        source: SourceRef | None = None,
        reference: str | None = None,
        reversal_of: str | None = None,
        causation_id: str | None = None,
    ) -> Result[dict]:
        """Insert and post in one go. With a source, a second call returns the entry already posted."""
        if source is not None:
            existing = self.find_by_source(tenant_id=tenant_id, source=source)
            if existing is not None:
                return Ok(existing)
        lines = list(lines)
        checked = self.check_postable(tenant_id=tenant_id, journal_code=journal_code, entry_date=entry_date, lines=lines)
        if isinstance(checked, Err):
            return checked
        inserted = self.insert_draft(
            tenant_id=tenant_id, actor_id=actor_id, journal_code=journal_code, entry_date=entry_date,
            label=label, lines=checked.value, reference=reference, source=source, reversal_of=reversal_of,
        )
        if isinstance(inserted, Err):
            return inserted
        return self.post_draft(
            tenant_id=tenant_id, actor_id=actor_id, entry_id=inserted.value,
            correlation_id=correlation_id, causation_id=causation_id,
        )

    def reverse_entry(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        entry_id: str,
        entry_date: datetime.date,
        correlation_id: str,
        causation_id: str | None = None,
    ) -> Result[dict]:
        """Posts the mirror of a posted entry, dated `entry_date`, and marks the original reversed."""
        row = self._connection.execute(
            """
            SELECT journal_code, number, status, source_module, source_id, source_kind
            FROM finance.journal_entries WHERE id = %s AND tenant_id = %s FOR UPDATE
            """,
            (entry_id, tenant_id),
        ).fetchone()
        if row is None:
            return entry_not_found(entry_id)
        journal_code, number, status, source_module, source_id, source_kind = row
        if status != "posted":
            return Err(
                "INVALID_TRANSITION",
                f"only a posted entry can be reversed; {number or entry_id} is {status}",
                f"seule une écriture comptabilisée peut être extournée ; {number or entry_id} est {STATUS_FR[status]}",
            )
        source = SourceRef(source_module, source_id, f"{source_kind}_reversal") if source_module else None
        posted = self.post_entry(
            tenant_id=tenant_id,
            actor_id=actor_id,
            journal_code=journal_code,
            entry_date=entry_date,
            label=f"Extourne de {number}",
            lines=reverse_lines(self.lines_of(entry_id)),
            correlation_id=correlation_id,
            source=source,
            reference=number,
            reversal_of=entry_id,
            causation_id=causation_id,
        )
        if isinstance(posted, Err):
            return posted
        self._connection.execute("UPDATE finance.journal_entries SET status = 'reversed' WHERE id = %s", (entry_id,))
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="journal_entry.reversed",
            entity_type="journal_entry",
            entity_id=entry_id,
            payload={"number": number, "reversal_entry_id": posted.value["id"], "reversal_number": posted.value["number"]},
        )
        return posted
```

- [ ] **Step 6: Register the new event**

In `backend/events/CATALOG.md`, add this row right after the `finance.invoice.paid` row:

```markdown
| `finance.journal_entry.posted` | 1.0 | finance | — | `entry_id`, `journal_code`, `source_module`, `source_id` — an entry was posted to the ledger (manual entries have null source fields); fires once per entry, reversals included |
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest modules/finance core/test_error_translations.py -q -rs`
Expected: all PASS, no skipped integration test.

- [ ] **Step 8: Commit**

```bash
git add backend/modules/finance/migrations/0003_finance_journal_entries.sql backend/modules/finance/api/ledger_sql.py backend/modules/finance/api/ledger_posting_service.py backend/modules/finance/testing_support.py backend/modules/finance/conftest.py backend/modules/finance/api/test_ledger_posting_integration.py backend/events/CATALOG.md
git commit -m "feat(finance): journal entries with immutable posting, deferred balance check and reversal

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Payroll events into the ledger (approved, paid, reversed) with dead-letter reasons and retry

**Files:**
- Create: `backend/modules/finance/api/posting_rule_service.py` (read side; Task 7 adds the edits)
- Create: `backend/modules/finance/api/posting_failure_service.py`
- Create: `backend/modules/finance/api/payroll_ledger_service.py`
- Create: `backend/modules/finance/api/ledger_event_postings.py`
- Create: `backend/modules/finance/events/ledger_consumers.py`
- Modify: `backend/worker/main.py` (one import)
- Modify: `backend/events/CATALOG.md` (consumers column of the three payroll rows)
- Test: `backend/modules/finance/events/test_payroll_ledger_consumers_integration.py`

**Interfaces:**
- Consumes: Task 2 (`payroll_run_lines`, `payroll_payment_entries`, `PostingRule`), Task 4 (`LedgerPostingService`, `SYSTEM_ACTOR`, `SourceRef`, `ledger` fixture, `NoCommitConnection`), Task 3 (`PeriodService`), `core.events.consumers.register` / `_process`, and payroll's contract `PayrollPostingService(connection).posting_lines(*, tenant_id, run_id)` / `.payment_lines(*, tenant_id, run_id)`.
- Produces:
  - `PostingRuleService(connection).rules_for(*, tenant_id, source) -> list[PostingRule]`
  - `PostingFailureService(connection)`: `record(*, tenant_id, source_module, source_id, source_kind, envelope: dict, err: Err) -> str`; `resolve(*, tenant_id, source_module, source_id, source_kind, actor_id=SYSTEM_ACTOR) -> int`; `cancel_for_source(*, tenant_id, source_module, source_id, kinds: list[str]) -> int`; `get(*, tenant_id, failure_id) -> dict | None` (with `envelope`); `list_failures(*, tenant_id, status: str | None = "open") -> list[dict]`; `failures_for_source(*, tenant_id, source_module, source_id) -> list[dict]`. Failure dict keys: `id, source_module, source_id, source_kind, event_id, event_type, error_code, error_message, error_message_fr, status, failed_at, resolved_at`. `FAILURE_STATUS_FR`.
  - `payroll_ledger_service.PAYROLL_API_FACTORY` (tests replace it), `last_day_of(period) -> date`, `PayrollLedgerService(connection)`: `post_run(*, tenant_id, run_id, period, correlation_id, causation_id=None) -> Result[list[dict]]`; `post_payment(*, tenant_id, run_id, period, paid_on, correlation_id, causation_id=None) -> Result[list[dict]]` (`RUN_NOT_POSTED`); `post_reversal(*, tenant_id, run_id, reversed_on, correlation_id, causation_id=None) -> Result[list[dict]]`.
  - Entry source kinds: `payroll_run`, `payroll_payment_bank|mobile_money|cash`, each `+ "_reversal"`. Failure kinds: `payroll_run`, `payroll_payment`, `payroll_reversal`.
  - `ledger_event_postings.SOURCES: dict[str, tuple[str, str, str]]` (event type → `(source_module, payload id key, failure kind)`), `source_of(envelope) -> tuple[str, str, str]`, `occurred_on(envelope) -> date`, `post_for_event(connection, envelope) -> Result[list[dict]]`, `retry_failure(connection, *, tenant_id, actor_id, failure_id) -> Result[list[dict]]`.
  - `ledger_consumers.handle_ledger_event(connection, envelope) -> None`, `PostingRefused(Exception)`, `consumer_name(event_type) -> str` (`"finance.ledger.payroll_run_approved"` …); one registry entry per `SOURCES` key.

- [ ] **Step 1: Write the failing test**

`backend/modules/finance/events/test_payroll_ledger_consumers_integration.py`:

```python
"""Payroll events into the ledger, through the real event registry.

`core.events.consumers._process` commits after each handler, so it runs on a NoCommitConnection:
commits and rollbacks are no-ops and the fixture still rolls everything back. Payroll's
PayrollPostingService is replaced by a fake returning the contract's dicts."""
from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from core.events.consumers import _process
from modules.finance.api import payroll_ledger_service
from modules.finance.api.ledger_event_postings import retry_failure
from modules.finance.api.period_service import PeriodService
from modules.finance.events import ledger_consumers  # noqa: F401  (registers the handlers)
from modules.finance.testing_support import NoCommitConnection

D = Decimal
JANUARY = datetime.date(2030, 1, 1)

# One employee: gross 320 000 = INPS 11 040 + ITS 25 000 + advance 10 000 + net 273 960.
POSTING_LINES = [
    {"source_kind": "earning", "code": "BASE", "amount": D(300000), "employee_id": "e1"},
    {"source_kind": "earning", "code": "OT_DAY", "amount": D(20000), "employee_id": "e1"},
    {"source_kind": "employee_contribution", "code": "INPS_EE", "amount": D(11040), "employee_id": "e1"},
    {"source_kind": "tax", "code": "ITS", "amount": D(25000), "employee_id": "e1"},
    {"source_kind": "deduction", "code": "ADVANCE", "amount": D(10000), "employee_id": "e1"},
    {"source_kind": "net", "code": "NET", "amount": D(273960), "employee_id": "e1"},
    {"source_kind": "employer_contribution", "code": "INPS_ER", "amount": D(60000), "employee_id": "e1"},
    {"source_kind": "employer_charge", "code": "TL", "amount": D(3200), "employee_id": "e1"},
]
PAYMENT_LINES = [
    {"method": "bank", "amount": D(200000), "employee_id": "e1"},
    {"method": "cash", "amount": D(73960), "employee_id": "e1"},
]


class FakePayroll:
    def __init__(self) -> None:
        self.posting_calls = 0

    def posting_lines(self, *, tenant_id: str, run_id: str) -> list[dict]:
        self.posting_calls += 1
        return POSTING_LINES

    def payment_lines(self, *, tenant_id: str, run_id: str) -> list[dict]:
        return PAYMENT_LINES


@pytest.fixture
def payroll(ledger, monkeypatch) -> FakePayroll:
    fake = FakePayroll()
    monkeypatch.setattr(payroll_ledger_service, "PAYROLL_API_FACTORY", lambda connection: fake)
    return fake


@pytest.fixture
def run_id() -> str:
    return str(ULID())


def _envelope(ledger, event_type: str, run_id: str, *, occurred_at: str = "2030-02-05T09:00:00+00:00") -> dict:
    return {
        "event_id": str(ULID()),
        "event_type": event_type,
        "event_version": "1.0",
        "occurred_at": occurred_at,
        "producer": "payroll",
        "tenant_id": ledger["tenant"],
        "correlation_id": str(ULID()),
        "causation_id": None,
        "payload": {"run_id": run_id, "period": "2030-01-01", "run_type": "regular"},
    }


def _deliver(ledger, envelope: dict) -> bool:
    return _process(NoCommitConnection(ledger["db"]), envelope)


def _entries(ledger, run_id: str) -> list[tuple]:
    return ledger["db"].execute(
        """
        SELECT source_kind, journal_code, status, entry_date FROM finance.journal_entries
        WHERE tenant_id = %s AND source_module = 'payroll' AND source_id = %s
        ORDER BY source_kind
        """,
        (ledger["tenant"], run_id),
    ).fetchall()


def _lines(ledger, run_id: str, source_kind: str) -> dict[str, tuple[Decimal, Decimal]]:
    rows = ledger["db"].execute(
        """
        SELECT l.account_code, l.debit, l.credit FROM finance.journal_lines l
        JOIN finance.journal_entries e ON e.id = l.entry_id
        WHERE e.tenant_id = %s AND e.source_id = %s AND e.source_kind = %s
        """,
        (ledger["tenant"], run_id, source_kind),
    ).fetchall()
    return {code: (debit, credit) for code, debit, credit in rows}


def _net(ledger, run_id: str, account_code: str) -> Decimal:
    return ledger["db"].execute(
        """
        SELECT COALESCE(SUM(l.debit - l.credit), 0) FROM finance.journal_lines l
        JOIN finance.journal_entries e ON e.id = l.entry_id
        WHERE e.tenant_id = %s AND e.source_id = %s AND l.account_code = %s
        """,
        (ledger["tenant"], run_id, account_code),
    ).fetchone()[0]


def _failures(ledger, run_id: str) -> list[tuple]:
    return ledger["db"].execute(
        """
        SELECT id, source_kind, error_code, status FROM finance.posting_failures
        WHERE tenant_id = %s AND source_id = %s ORDER BY source_kind
        """,
        (ledger["tenant"], run_id),
    ).fetchall()


def test_an_approved_run_posts_one_balanced_paie_entry(ledger, payroll, run_id):
    assert _deliver(ledger, _envelope(ledger, "payroll.run.approved", run_id)) is True
    assert _entries(ledger, run_id) == [("payroll_run", "PAIE", "posted", datetime.date(2030, 1, 31))]
    assert _lines(ledger, run_id, "payroll_run") == {
        "641": (D(3200), D(0)),
        "661": (D(320000), D(0)),
        "664": (D(60000), D(0)),
        "421": (D(0), D(10000)),
        "422": (D(0), D(273960)),
        "431": (D(0), D(71040)),
        "442": (D(0), D(3200)),
        "447": (D(0), D(25000)),
    }
    ledger["db"].execute("SET CONSTRAINTS ALL IMMEDIATE")


def test_the_same_approved_event_delivered_twice_posts_once(ledger, payroll, run_id):
    envelope = _envelope(ledger, "payroll.run.approved", run_id)
    assert _deliver(ledger, envelope) is True
    assert _deliver(ledger, envelope) is True
    assert len(_entries(ledger, run_id)) == 1
    assert payroll.posting_calls == 1  # the second delivery was skipped on its event_id


def test_a_second_approval_event_for_the_same_run_does_not_post_again(ledger, payroll, run_id):
    assert _deliver(ledger, _envelope(ledger, "payroll.run.approved", run_id)) is True
    assert _deliver(ledger, _envelope(ledger, "payroll.run.approved", run_id)) is True
    assert len(_entries(ledger, run_id)) == 1


def test_a_paid_run_clears_net_pay_per_payment_method(ledger, payroll, run_id):
    _deliver(ledger, _envelope(ledger, "payroll.run.approved", run_id))
    assert _deliver(ledger, _envelope(ledger, "payroll.run.paid", run_id)) is True
    assert _entries(ledger, run_id) == [
        ("payroll_payment_bank", "BNQ", "posted", datetime.date(2030, 2, 5)),
        ("payroll_payment_cash", "CAI", "posted", datetime.date(2030, 2, 5)),
        ("payroll_run", "PAIE", "posted", datetime.date(2030, 1, 31)),
    ]
    assert _net(ledger, run_id, "422") == D(0)
    assert _net(ledger, run_id, "521") == D(-200000)
    assert _net(ledger, run_id, "571") == D(-73960)


def test_the_same_paid_event_delivered_twice_posts_once(ledger, payroll, run_id):
    _deliver(ledger, _envelope(ledger, "payroll.run.approved", run_id))
    envelope = _envelope(ledger, "payroll.run.paid", run_id)
    assert _deliver(ledger, envelope) is True
    assert _deliver(ledger, envelope) is True
    assert _deliver(ledger, _envelope(ledger, "payroll.run.paid", run_id)) is True  # new event id, same run
    assert len(_entries(ledger, run_id)) == 3


def test_a_reversed_run_mirrors_every_entry_once(ledger, payroll, run_id):
    _deliver(ledger, _envelope(ledger, "payroll.run.approved", run_id))
    _deliver(ledger, _envelope(ledger, "payroll.run.paid", run_id))
    envelope = _envelope(ledger, "payroll.run.reversed", run_id, occurred_at="2030-02-10T08:00:00+00:00")
    assert _deliver(ledger, envelope) is True
    assert _deliver(ledger, envelope) is True
    assert _deliver(ledger, _envelope(ledger, "payroll.run.reversed", run_id)) is True  # new event id: nothing left to reverse
    statuses = {kind: status for kind, _, status, _ in _entries(ledger, run_id)}
    assert statuses == {
        "payroll_run": "reversed",
        "payroll_payment_bank": "reversed",
        "payroll_payment_cash": "reversed",
        "payroll_run_reversal": "posted",
        "payroll_payment_bank_reversal": "posted",
        "payroll_payment_cash_reversal": "posted",
    }
    for account in ("422", "431", "447", "521", "571", "661"):
        assert _net(ledger, run_id, account) == D(0), account
    ledger["db"].execute("SET CONSTRAINTS ALL IMMEDIATE")


def test_a_closed_period_dead_letters_then_retry_posts_once(ledger, payroll, run_id):
    periods = PeriodService(ledger["db"])
    periods.close_period(tenant_id=ledger["tenant"], actor_id=ledger["actor"], period=JANUARY)
    envelope = _envelope(ledger, "payroll.run.approved", run_id)
    assert _deliver(ledger, envelope) is False  # nacked: the message goes to the dead-letter queue
    assert _entries(ledger, run_id) == []
    [(failure_id, kind, code, status)] = _failures(ledger, run_id)
    assert (kind, code, status) == ("payroll_run", "PERIOD_CLOSED", "open")

    periods.reopen_period(tenant_id=ledger["tenant"], actor_id=ledger["actor"], period=JANUARY)
    retried = retry_failure(ledger["db"], tenant_id=ledger["tenant"], actor_id=ledger["actor"], failure_id=failure_id)
    assert isinstance(retried, Ok), retried
    assert len(_entries(ledger, run_id)) == 1
    assert _failures(ledger, run_id)[0][3] == "resolved"

    # The dead-lettered message replayed later: still one entry, the failure stays resolved.
    assert _deliver(ledger, envelope) is True
    assert len(_entries(ledger, run_id)) == 1
    assert _failures(ledger, run_id)[0][3] == "resolved"
    again = retry_failure(ledger["db"], tenant_id=ledger["tenant"], actor_id=ledger["actor"], failure_id=failure_id)
    assert isinstance(again, Err) and again.code == "INVALID_TRANSITION"


def test_a_payment_before_its_run_is_refused_until_the_run_posts(ledger, payroll, run_id):
    assert _deliver(ledger, _envelope(ledger, "payroll.run.paid", run_id)) is False
    [(failure_id, kind, code, _)] = _failures(ledger, run_id)
    assert (kind, code) == ("payroll_payment", "RUN_NOT_POSTED")
    assert _entries(ledger, run_id) == []
    assert _deliver(ledger, _envelope(ledger, "payroll.run.approved", run_id)) is True
    retried = retry_failure(ledger["db"], tenant_id=ledger["tenant"], actor_id=ledger["actor"], failure_id=failure_id)
    assert isinstance(retried, Ok), retried
    assert _net(ledger, run_id, "422") == D(0)


def test_reversing_a_run_whose_posting_failed_cancels_the_failure(ledger, payroll, run_id):
    PeriodService(ledger["db"]).close_period(tenant_id=ledger["tenant"], actor_id=ledger["actor"], period=JANUARY)
    assert _deliver(ledger, _envelope(ledger, "payroll.run.approved", run_id)) is False
    assert _deliver(ledger, _envelope(ledger, "payroll.run.reversed", run_id)) is True
    [(failure_id, kind, _, status)] = _failures(ledger, run_id)
    assert (kind, status) == ("payroll_run", "cancelled")
    assert _entries(ledger, run_id) == []
    retried = retry_failure(ledger["db"], tenant_id=ledger["tenant"], actor_id=ledger["actor"], failure_id=failure_id)
    assert isinstance(retried, Err) and retried.code == "INVALID_TRANSITION"


def test_a_missing_posting_rule_is_refused_and_recorded(ledger, payroll, run_id):
    ledger["db"].execute(
        "DELETE FROM finance.posting_rules WHERE tenant_id = %s AND source = 'payroll' AND source_kind = 'tax'",
        (ledger["tenant"],),
    )
    assert _deliver(ledger, _envelope(ledger, "payroll.run.approved", run_id)) is False
    [(_, kind, code, status)] = _failures(ledger, run_id)
    assert (kind, code, status) == ("payroll_run", "POSTING_RULE_MISSING", "open")


def test_a_rule_pointing_at_a_heading_account_is_refused_and_recorded(ledger, payroll, run_id):
    ledger["db"].execute(
        "UPDATE finance.accounts SET is_postable = FALSE WHERE tenant_id = %s AND code = '661'", (ledger["tenant"],)
    )
    assert _deliver(ledger, _envelope(ledger, "payroll.run.approved", run_id)) is False
    [(_, _, code, _)] = _failures(ledger, run_id)
    assert code == "ACCOUNT_NOT_POSTABLE"


def test_a_failure_keeps_both_languages_and_its_envelope(ledger, payroll, run_id):
    PeriodService(ledger["db"]).close_period(tenant_id=ledger["tenant"], actor_id=ledger["actor"], period=JANUARY)
    envelope = _envelope(ledger, "payroll.run.approved", run_id)
    _deliver(ledger, envelope)
    message, message_fr, stored = ledger["db"].execute(
        "SELECT error_message, error_message_fr, envelope FROM finance.posting_failures WHERE tenant_id = %s AND source_id = %s",
        (ledger["tenant"], run_id),
    ).fetchone()
    assert message and message_fr
    assert stored["event_id"] == envelope["event_id"]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python -m pytest modules/finance/events/test_payroll_ledger_consumers_integration.py -q`
Expected: collection error `cannot import name 'payroll_ledger_service' from 'modules.finance.api'`.

- [ ] **Step 3: Write the rule reader and the failure store**

`backend/modules/finance/api/posting_rule_service.py`:

```python
"""The posting rules of a tenant: read by the posters, edited from the Posting rules screen."""
from __future__ import annotations

import psycopg

from modules.finance.domain.posting import PostingRule


class PostingRuleService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def rules_for(self, *, tenant_id: str, source: str) -> list[PostingRule]:
        rows = self._connection.execute(
            """
            SELECT source, source_kind, code, debit_account_code, credit_account_code, journal_code, status, id
            FROM finance.posting_rules
            WHERE tenant_id = %s AND source = %s
            """,
            (tenant_id, source),
        ).fetchall()
        return [PostingRule(*row) for row in rows]
```

`backend/modules/finance/api/posting_failure_service.py`:

```python
"""Automatic postings that were refused, and why.

One row per (source_module, source_id, source_kind): a new refusal of the same posting overwrites
the reason and reopens it. The consumer writes it in its own committed transaction before the
event is dead-lettered; a later successful posting resolves it; reversing the run cancels it."""
from __future__ import annotations

import psycopg
from psycopg.types.json import Jsonb
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err
from modules.finance.api.ledger_posting_service import SYSTEM_ACTOR

FAILURE_KEYS = (
    "id", "source_module", "source_id", "source_kind", "event_id", "event_type",
    "error_code", "error_message", "error_message_fr", "status", "failed_at", "resolved_at",
)
FAILURE_COLUMNS = ", ".join(FAILURE_KEYS)
FAILURE_STATUS_FR = {"open": "ouvert", "resolved": "résolu", "cancelled": "annulé"}


class PostingFailureService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def record(
        self, *, tenant_id: str, source_module: str, source_id: str, source_kind: str, envelope: dict, err: Err
    ) -> str:
        row = self._connection.execute(
            """
            INSERT INTO finance.posting_failures
                (id, tenant_id, source_module, source_id, source_kind, event_id, event_type, envelope,
                 error_code, error_message, error_message_fr)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id, source_module, source_id, source_kind) DO UPDATE SET
                event_id = EXCLUDED.event_id,
                event_type = EXCLUDED.event_type,
                envelope = EXCLUDED.envelope,
                error_code = EXCLUDED.error_code,
                error_message = EXCLUDED.error_message,
                error_message_fr = EXCLUDED.error_message_fr,
                status = 'open',
                failed_at = NOW(),
                resolved_at = NULL
            RETURNING id
            """,
            (
                str(ULID()), tenant_id, source_module, source_id, source_kind,
                envelope["event_id"], envelope["event_type"], Jsonb(envelope),
                err.code, err.message, err.message_fr,
            ),
        ).fetchone()
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=SYSTEM_ACTOR,
            action="posting.refused",
            entity_type="posting_failure",
            entity_id=row[0],
            payload={"source_module": source_module, "source_id": source_id, "source_kind": source_kind, "code": err.code},
        )
        return row[0]

    def resolve(
        self, *, tenant_id: str, source_module: str, source_id: str, source_kind: str, actor_id: str = SYSTEM_ACTOR
    ) -> int:
        rows = self._connection.execute(
            """
            UPDATE finance.posting_failures SET status = 'resolved', resolved_at = NOW()
            WHERE tenant_id = %s AND source_module = %s AND source_id = %s AND source_kind = %s AND status = 'open'
            RETURNING id
            """,
            (tenant_id, source_module, source_id, source_kind),
        ).fetchall()
        for (failure_id,) in rows:
            record_audit(
                self._connection,
                tenant_id=tenant_id,
                actor_id=actor_id,
                action="posting_failure.resolved",
                entity_type="posting_failure",
                entity_id=failure_id,
                payload={"source_kind": source_kind},
            )
        return len(rows)

    def cancel_for_source(self, *, tenant_id: str, source_module: str, source_id: str, kinds: list[str]) -> int:
        rows = self._connection.execute(
            """
            UPDATE finance.posting_failures SET status = 'cancelled', resolved_at = NOW()
            WHERE tenant_id = %s AND source_module = %s AND source_id = %s AND source_kind = ANY(%s) AND status = 'open'
            RETURNING id, source_kind
            """,
            (tenant_id, source_module, source_id, kinds),
        ).fetchall()
        for failure_id, kind in rows:
            record_audit(
                self._connection,
                tenant_id=tenant_id,
                actor_id=SYSTEM_ACTOR,
                action="posting_failure.cancelled",
                entity_type="posting_failure",
                entity_id=failure_id,
                payload={"source_kind": kind},
            )
        return len(rows)

    def get(self, *, tenant_id: str, failure_id: str) -> dict | None:
        row = self._connection.execute(
            f"SELECT {FAILURE_COLUMNS}, envelope FROM finance.posting_failures WHERE tenant_id = %s AND id = %s",
            (tenant_id, failure_id),
        ).fetchone()
        return None if row is None else dict(zip(FAILURE_KEYS + ("envelope",), row))

    def list_failures(self, *, tenant_id: str, status: str | None = "open") -> list[dict]:
        sql = f"SELECT {FAILURE_COLUMNS} FROM finance.posting_failures WHERE tenant_id = %s"
        params: list[object] = [tenant_id]
        if status:
            sql += " AND status = %s"
            params.append(status)
        rows = self._connection.execute(sql + " ORDER BY failed_at DESC", params).fetchall()
        return [dict(zip(FAILURE_KEYS, row)) for row in rows]

    def failures_for_source(self, *, tenant_id: str, source_module: str, source_id: str) -> list[dict]:
        rows = self._connection.execute(
            f"""
            SELECT {FAILURE_COLUMNS} FROM finance.posting_failures
            WHERE tenant_id = %s AND source_module = %s AND source_id = %s
            ORDER BY failed_at
            """,
            (tenant_id, source_module, source_id),
        ).fetchall()
        return [dict(zip(FAILURE_KEYS, row)) for row in rows]
```

- [ ] **Step 4: Write the payroll poster**

`backend/modules/finance/api/payroll_ledger_service.py`:

```python
"""Payroll runs into the ledger: the PAIE entry of an approved run, one bank / mobile-money / cash
entry per payment method when it is paid, and the mirror of all of them when the run is reversed.

The lines come from payroll's public API only (`PayrollPostingService`); finance never reads
payroll tables. Payroll is an optional dependency, imported when a payroll event is posted."""
from __future__ import annotations

import datetime
from typing import Callable

import psycopg

from core.domain.result import Err, Ok, Result
from modules.finance.api.ledger_posting_service import SYSTEM_ACTOR, LedgerPostingService
from modules.finance.api.posting_failure_service import PostingFailureService
from modules.finance.api.posting_rule_service import PostingRuleService
from modules.finance.domain.ledger import SourceRef
from modules.finance.domain.posting import PaymentEntry, payroll_payment_entries, payroll_run_lines

PAYROLL_JOURNAL = "PAIE"
PAYROLL_MODULE = "payroll"
RUN_KIND = "payroll_run"
PAYMENT_KIND_PREFIX = "payroll_payment_"
METHOD_LABEL_FR = {"bank": "virement", "mobile_money": "mobile money", "cash": "espèces"}


def _default_payroll_api(connection: psycopg.Connection):
    from modules.payroll.api.posting_service import PayrollPostingService

    return PayrollPostingService(connection)


# The one seam tests replace with a fake; production code never reassigns it.
PAYROLL_API_FACTORY: Callable[[psycopg.Connection], object] = _default_payroll_api


def last_day_of(period: datetime.date) -> datetime.date:
    next_month = (period.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
    return next_month - datetime.timedelta(days=1)


class PayrollLedgerService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection
        self._posting = LedgerPostingService(connection)
        self._rules = PostingRuleService(connection)

    def _payroll(self):
        return PAYROLL_API_FACTORY(self._connection)

    def post_run(
        self, *, tenant_id: str, run_id: str, period: datetime.date, correlation_id: str, causation_id: str | None = None
    ) -> Result[list[dict]]:
        """One PAIE entry per run, dated the last day of the pay month, lines summed per account."""
        source = SourceRef(PAYROLL_MODULE, run_id, RUN_KIND)
        existing = self._posting.find_by_source(tenant_id=tenant_id, source=source)
        if existing is not None:
            return Ok([existing])
        lines = payroll_run_lines(
            self._payroll().posting_lines(tenant_id=tenant_id, run_id=run_id),
            self._rules.rules_for(tenant_id=tenant_id, source="payroll"),
        )
        if isinstance(lines, Err):
            return lines
        posted = self._posting.post_entry(
            tenant_id=tenant_id,
            actor_id=SYSTEM_ACTOR,
            journal_code=PAYROLL_JOURNAL,
            entry_date=last_day_of(period),
            label=f"Paie {period:%m/%Y}",
            lines=lines.value,
            correlation_id=correlation_id,
            source=source,
            reference=run_id,
            causation_id=causation_id,
        )
        if isinstance(posted, Err):
            return posted
        return Ok([posted.value])

    def post_payment(
        self,
        *,
        tenant_id: str,
        run_id: str,
        period: datetime.date,
        paid_on: datetime.date,
        correlation_id: str,
        causation_id: str | None = None,
    ) -> Result[list[dict]]:
        """One entry per payment method, dated the day the run was paid, clearing net pay.
        Every method is checked before any is written, so a refusal leaves nothing half-posted."""
        if self._posting.find_by_source(tenant_id=tenant_id, source=SourceRef(PAYROLL_MODULE, run_id, RUN_KIND)) is None:
            return Err(
                "RUN_NOT_POSTED",
                f"payroll run {run_id} has no posted PAIE entry yet, so its payment cannot clear net pay",
                f"la paie {run_id} n'a pas encore d'écriture PAIE comptabilisée ; son règlement ne peut pas solder les salaires nets",
            )
        entries = payroll_payment_entries(
            self._payroll().payment_lines(tenant_id=tenant_id, run_id=run_id),
            self._rules.rules_for(tenant_id=tenant_id, source="payroll"),
        )
        if isinstance(entries, Err):
            return entries
        posted: list[dict] = []
        pending: list[tuple[SourceRef, PaymentEntry]] = []
        for entry in entries.value:
            source = SourceRef(PAYROLL_MODULE, run_id, PAYMENT_KIND_PREFIX + entry.method)
            existing = self._posting.find_by_source(tenant_id=tenant_id, source=source)
            if existing is not None:
                posted.append(existing)
                continue
            checked = self._posting.check_postable(
                tenant_id=tenant_id, journal_code=entry.journal_code, entry_date=paid_on, lines=entry.lines
            )
            if isinstance(checked, Err):
                return checked
            pending.append((source, entry))
        for source, entry in pending:
            result = self._posting.post_entry(
                tenant_id=tenant_id,
                actor_id=SYSTEM_ACTOR,
                journal_code=entry.journal_code,
                entry_date=paid_on,
                label=f"Paie {period:%m/%Y} – règlement {METHOD_LABEL_FR[entry.method]}",
                lines=entry.lines,
                correlation_id=correlation_id,
                source=source,
                reference=run_id,
                causation_id=causation_id,
            )
            if isinstance(result, Err):
                return result
            posted.append(result.value)
        return Ok(posted)

    def post_reversal(
        self,
        *,
        tenant_id: str,
        run_id: str,
        reversed_on: datetime.date,
        correlation_id: str,
        causation_id: str | None = None,
    ) -> Result[list[dict]]:
        """Mirrors every posted entry of the run, dated the day it was reversed; then cancels the
        run's open posting failures so a later retry cannot post a reversed run."""
        rows = self._connection.execute(
            """
            SELECT id FROM finance.journal_entries
            WHERE tenant_id = %s AND source_module = %s AND source_id = %s
              AND status = 'posted' AND reversal_of IS NULL
            ORDER BY created_at, id
            """,
            (tenant_id, PAYROLL_MODULE, run_id),
        ).fetchall()
        reversals: list[dict] = []
        for (entry_id,) in rows:
            reversed_entry = self._posting.reverse_entry(
                tenant_id=tenant_id,
                actor_id=SYSTEM_ACTOR,
                entry_id=entry_id,
                entry_date=reversed_on,
                correlation_id=correlation_id,
                causation_id=causation_id,
            )
            if isinstance(reversed_entry, Err):
                return reversed_entry
            reversals.append(reversed_entry.value)
        PostingFailureService(self._connection).cancel_for_source(
            tenant_id=tenant_id, source_module=PAYROLL_MODULE, source_id=run_id, kinds=[RUN_KIND, "payroll_payment"]
        )
        return Ok(reversals)
```

- [ ] **Step 5: Write the event dispatch, the retry and the consumers**

`backend/modules/finance/api/ledger_event_postings.py`:

```python
"""Which ledger posting an event asks for — shared by the consumers and by the retry of a refused
posting, so both go through exactly the same code."""
from __future__ import annotations

import datetime

import psycopg

from core.audit import record_audit
from core.domain.result import Err, Result
from modules.finance.api.posting_failure_service import FAILURE_STATUS_FR, PostingFailureService

# event type -> (source_module, payload key holding the source id, failure kind)
SOURCES: dict[str, tuple[str, str, str]] = {
    "payroll.run.approved": ("payroll", "run_id", "payroll_run"),
    "payroll.run.paid": ("payroll", "run_id", "payroll_payment"),
    "payroll.run.reversed": ("payroll", "run_id", "payroll_reversal"),
}


def source_of(envelope: dict) -> tuple[str, str, str]:
    module, id_key, kind = SOURCES[envelope["event_type"]]
    return module, str(envelope["payload"][id_key]), kind


def occurred_on(envelope: dict) -> datetime.date:
    """The business date of an event. Mali is UTC+0, so the UTC date is the local date."""
    return datetime.datetime.fromisoformat(envelope["occurred_at"]).date()


def post_for_event(connection: psycopg.Connection, envelope: dict) -> Result[list[dict]]:
    event_type = envelope["event_type"]
    tenant_id = envelope["tenant_id"]
    payload = envelope["payload"]
    correlation_id = envelope.get("correlation_id") or envelope["event_id"]
    causation_id = envelope["event_id"]
    if event_type in ("payroll.run.approved", "payroll.run.paid", "payroll.run.reversed"):
        from modules.finance.api.payroll_ledger_service import PayrollLedgerService

        payroll = PayrollLedgerService(connection)
        run_id = str(payload["run_id"])
        if event_type == "payroll.run.approved":
            return payroll.post_run(
                tenant_id=tenant_id,
                run_id=run_id,
                period=datetime.date.fromisoformat(payload["period"]),
                correlation_id=correlation_id,
                causation_id=causation_id,
            )
        if event_type == "payroll.run.paid":
            return payroll.post_payment(
                tenant_id=tenant_id,
                run_id=run_id,
                period=datetime.date.fromisoformat(payload["period"]),
                paid_on=occurred_on(envelope),
                correlation_id=correlation_id,
                causation_id=causation_id,
            )
        return payroll.post_reversal(
            tenant_id=tenant_id,
            run_id=run_id,
            reversed_on=occurred_on(envelope),
            correlation_id=correlation_id,
            causation_id=causation_id,
        )
    raise ValueError(f"the ledger has no posting for {event_type}")


def retry_failure(connection: psycopg.Connection, *, tenant_id: str, actor_id: str, failure_id: str) -> Result[list[dict]]:
    """Replays the stored event of an open failure. On success the failure is resolved; on a new
    refusal the caller rolls back and the failure keeps its first reason."""
    failures = PostingFailureService(connection)
    failure = failures.get(tenant_id=tenant_id, failure_id=failure_id)
    if failure is None:
        return Err(
            "NOT_FOUND",
            f"posting failure {failure_id} not found",
            f"échec d'imputation {failure_id} introuvable",
        )
    if failure["status"] != "open":
        return Err(
            "INVALID_TRANSITION",
            f"posting failure {failure_id} is already {failure['status']}",
            f"l'échec d'imputation {failure_id} est déjà {FAILURE_STATUS_FR[failure['status']]}",
        )
    result = post_for_event(connection, failure["envelope"])
    if isinstance(result, Err):
        return result
    failures.resolve(
        tenant_id=tenant_id,
        source_module=failure["source_module"],
        source_id=failure["source_id"],
        source_kind=failure["source_kind"],
        actor_id=actor_id,
    )
    record_audit(
        connection,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="posting_failure.retried",
        entity_type="posting_failure",
        entity_id=failure_id,
        payload={"entries": [entry["id"] for entry in result.value]},
    )
    return result
```

`backend/modules/finance/events/ledger_consumers.py`:

```python
"""The ledger's event consumers: payroll runs and invoices become journal entries.

Idempotent twice over: the registry skips an event_id this consumer already processed, and every
posting returns the entry already posted for the same (source_module, source_id, source_kind).
A refused posting (closed period, missing rule, …) is written to finance.posting_failures in its
own committed transaction, then the handler raises: the registry nacks and the message goes to
the dead-letter queue, while the run page can show why and
POST /finance/posting-failures/{id}/retry replays it once the cause is fixed."""
from __future__ import annotations

import psycopg

from core.domain.result import Err
from core.events.consumers import register
from modules.finance.api.ledger_event_postings import SOURCES, post_for_event, source_of
from modules.finance.api.posting_failure_service import PostingFailureService


class PostingRefused(Exception):
    def __init__(self, err: Err) -> None:
        super().__init__(f"{err.code}: {err.message}")
        self.err = err


def consumer_name(event_type: str) -> str:
    return "finance.ledger." + event_type.replace(".", "_")


def handle_ledger_event(connection: psycopg.Connection, envelope: dict) -> None:
    source_module, source_id, source_kind = source_of(envelope)
    tenant_id = envelope["tenant_id"]
    result = post_for_event(connection, envelope)
    failures = PostingFailureService(connection)
    if isinstance(result, Err):
        connection.rollback()
        failures.record(
            tenant_id=tenant_id,
            source_module=source_module,
            source_id=source_id,
            source_kind=source_kind,
            envelope=envelope,
            err=result,
        )
        connection.commit()
        raise PostingRefused(result)
    failures.resolve(tenant_id=tenant_id, source_module=source_module, source_id=source_id, source_kind=source_kind)


for _event_type in SOURCES:
    register(consumer_name(_event_type), _event_type, handle_ledger_event)
```

- [ ] **Step 6: Wire the worker and the catalog**

In `backend/worker/main.py`, add after the line `from modules.finance.events import consumers as _finance_consumers  # noqa: F401`:

```python
from modules.finance.events import ledger_consumers as _finance_ledger_consumers  # noqa: F401
```

In `backend/events/CATALOG.md`, in the rows `payroll.run.approved`, `payroll.run.paid` and `payroll.run.reversed` (added by phase 3), set the **Consumers** cell to `finance` (keep the other cells as they are; if phase 3 already wrote `finance`, leave the rows unchanged).

- [ ] **Step 7: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest modules/finance core/test_error_translations.py -q -rs`
Expected: all PASS, no skipped integration test.

- [ ] **Step 8: Commit**

```bash
git add backend/modules/finance/api/posting_rule_service.py backend/modules/finance/api/posting_failure_service.py backend/modules/finance/api/payroll_ledger_service.py backend/modules/finance/api/ledger_event_postings.py backend/modules/finance/events/ledger_consumers.py backend/modules/finance/events/test_payroll_ledger_consumers_integration.py backend/worker/main.py backend/events/CATALOG.md
git commit -m "feat(finance): post payroll runs, payments and reversals to the ledger from events

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Invoice events into the ledger (VTE / BNQ)

**Files:**
- Create: `backend/modules/finance/api/invoice_ledger_service.py`
- Modify: `backend/modules/finance/api/ledger_event_postings.py` (`SOURCES` + one branch in `post_for_event`)
- Modify: `backend/events/CATALOG.md` (consumers column of the two invoice rows)
- Test: `backend/modules/finance/events/test_invoice_ledger_consumers_integration.py`

**Interfaces:**
- Consumes: Task 2 (`to_xof`, `invoice_entry`), Task 4 (`LedgerPostingService`, `SYSTEM_ACTOR`), Task 5 (`PostingRuleService.rules_for`, `SOURCES`, `post_for_event`, `occurred_on`, the consumer loop registering every `SOURCES` key), existing `InvoiceService` (`create_draft_invoice`, `issue_invoice`).
- Produces: `InvoiceLedgerService(connection)`: `post_issued(*, tenant_id, invoice_id, partner_id, amount, currency, issued_on, correlation_id, causation_id=None) -> Result[list[dict]]`; `post_paid(*, tenant_id, invoice_id, partner_id, amount, currency, paid_on, correlation_id, causation_id=None) -> Result[list[dict]]` (`INVOICE_NOT_POSTED` while the issue entry is missing). Entries use `source_module='finance'`, `source_id=<invoice id>`, `source_kind` `invoice_issued` / `invoice_paid`; consumers `finance.ledger.finance_invoice_issued` / `finance.ledger.finance_invoice_paid`.

- [ ] **Step 1: Write the failing test**

`backend/modules/finance/events/test_invoice_ledger_consumers_integration.py`:

```python
"""Invoice events into the ledger (finance consumes its own events), through the real registry."""
from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from ulid import ULID

from core.domain.result import Ok
from core.events.consumers import _process
from modules.finance.api.period_service import PeriodService
from modules.finance.api.service import InvoiceService
from modules.finance.events import ledger_consumers  # noqa: F401  (registers the handlers)
from modules.finance.testing_support import NoCommitConnection

D = Decimal


@pytest.fixture
def partner(ledger) -> str:
    partner_id = str(ULID())
    ledger["db"].execute(
        "INSERT INTO core.partners (id, tenant_id, name, kind) VALUES (%s, %s, %s, 'customer')",
        (partner_id, ledger["tenant"], f"Client {partner_id}"),
    )
    return partner_id


def _envelope(ledger, event_type, invoice_id, partner_id, *, amount=150000.0, currency="XOF",
              occurred_at="2030-03-04T10:00:00+00:00") -> dict:
    return {
        "event_id": str(ULID()),
        "event_type": event_type,
        "event_version": "1.0",
        "occurred_at": occurred_at,
        "producer": "finance",
        "tenant_id": ledger["tenant"],
        "correlation_id": str(ULID()),
        "causation_id": None,
        "payload": {"invoice_id": invoice_id, "partner_id": partner_id, "amount": amount, "currency": currency},
    }


def _deliver(ledger, envelope: dict) -> bool:
    return _process(NoCommitConnection(ledger["db"]), envelope)


def _lines(ledger, invoice_id: str, kind: str) -> list[tuple]:
    return ledger["db"].execute(
        """
        SELECT e.journal_code, l.account_code, l.debit, l.credit, l.partner_id
        FROM finance.journal_lines l
        JOIN finance.journal_entries e ON e.id = l.entry_id
        WHERE e.tenant_id = %s AND e.source_module = 'finance' AND e.source_id = %s AND e.source_kind = %s
        ORDER BY l.line_no
        """,
        (ledger["tenant"], invoice_id, kind),
    ).fetchall()


def _failure(ledger, invoice_id: str) -> tuple | None:
    return ledger["db"].execute(
        "SELECT source_kind, error_code, status FROM finance.posting_failures WHERE tenant_id = %s AND source_id = %s",
        (ledger["tenant"], invoice_id),
    ).fetchone()


def test_an_issued_invoice_posts_to_vte_with_the_customer_on_411(ledger, partner):
    invoice_id = str(ULID())
    assert _deliver(ledger, _envelope(ledger, "finance.invoice.issued", invoice_id, partner, amount=150000.4)) is True
    assert _lines(ledger, invoice_id, "invoice_issued") == [
        ("VTE", "411", D(150000), D(0), partner),
        ("VTE", "702", D(0), D(150000), None),
    ]


def test_the_same_issued_event_delivered_twice_posts_once(ledger, partner):
    invoice_id = str(ULID())
    envelope = _envelope(ledger, "finance.invoice.issued", invoice_id, partner)
    assert _deliver(ledger, envelope) is True
    assert _deliver(ledger, envelope) is True
    assert _deliver(ledger, _envelope(ledger, "finance.invoice.issued", invoice_id, partner)) is True  # new event id
    count = ledger["db"].execute(
        "SELECT count(*) FROM finance.journal_entries WHERE tenant_id = %s AND source_id = %s", (ledger["tenant"], invoice_id)
    ).fetchone()[0]
    assert count == 1


def test_a_paid_invoice_clears_the_customer_through_the_bank_once(ledger, partner):
    invoice_id = str(ULID())
    _deliver(ledger, _envelope(ledger, "finance.invoice.issued", invoice_id, partner))
    paid = _envelope(ledger, "finance.invoice.paid", invoice_id, partner, occurred_at="2030-03-20T15:00:00+00:00")
    assert _deliver(ledger, paid) is True
    assert _deliver(ledger, paid) is True
    assert _lines(ledger, invoice_id, "invoice_paid") == [
        ("BNQ", "521", D(150000), D(0), None),
        ("BNQ", "411", D(0), D(150000), partner),
    ]


def test_a_payment_before_its_invoice_is_posted_is_refused(ledger, partner):
    invoice_id = str(ULID())
    assert _deliver(ledger, _envelope(ledger, "finance.invoice.paid", invoice_id, partner)) is False
    assert _failure(ledger, invoice_id) == ("invoice_paid", "INVOICE_NOT_POSTED", "open")


def test_a_foreign_currency_invoice_is_refused_and_recorded(ledger, partner):
    invoice_id = str(ULID())
    assert _deliver(ledger, _envelope(ledger, "finance.invoice.issued", invoice_id, partner, currency="EUR")) is False
    assert _failure(ledger, invoice_id) == ("invoice_issued", "CURRENCY_NOT_XOF", "open")


def test_an_invoice_in_a_closed_period_is_refused_and_recorded(ledger, partner):
    PeriodService(ledger["db"]).close_period(
        tenant_id=ledger["tenant"], actor_id=ledger["actor"], period=datetime.date(2030, 3, 1)
    )
    invoice_id = str(ULID())
    assert _deliver(ledger, _envelope(ledger, "finance.invoice.issued", invoice_id, partner)) is False
    assert _failure(ledger, invoice_id) == ("invoice_issued", "PERIOD_CLOSED", "open")


def test_the_envelope_invoice_service_publishes_is_the_one_the_ledger_posts(ledger, partner):
    db = ledger["db"]
    year = datetime.datetime.now(datetime.timezone.utc).year
    if year != ledger["year"]:
        PeriodService(db).open_fiscal_year(tenant_id=ledger["tenant"], actor_id=ledger["actor"], year=year)
    invoices = InvoiceService(db)
    invoice = invoices.create_draft_invoice(
        tenant_id=ledger["tenant"], partner_id=partner, amount=98000, currency="XOF", actor_id=ledger["actor"]
    )
    issued = invoices.issue_invoice(
        tenant_id=ledger["tenant"], actor_id=ledger["actor"], invoice_id=invoice.id, correlation_id=str(ULID())
    )
    assert isinstance(issued, Ok)
    envelope = db.execute(
        """
        SELECT payload FROM events.outbox
        WHERE event_type = 'finance.invoice.issued' AND payload -> 'payload' ->> 'invoice_id' = %s
        """,
        (invoice.id,),
    ).fetchone()[0]
    assert _deliver(ledger, envelope) is True
    lines = _lines(ledger, invoice.id, "invoice_issued")
    assert [(code, debit, credit) for _, code, debit, credit, _ in lines] == [
        ("411", D(98000), D(0)),
        ("702", D(0), D(98000)),
    ]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python -m pytest modules/finance/events/test_invoice_ledger_consumers_integration.py -q`
Expected: FAIL — no handler is registered for `finance.invoice.*` yet, so `_process` returns `True` without posting: the line assertions fail with `[] != [...]` and the refusal tests fail on `True is False`.

- [ ] **Step 3: Write the invoice poster**

`backend/modules/finance/api/invoice_ledger_service.py`:

```python
"""Invoices into the ledger: the VTE entry when an invoice is issued, the bank entry when it is paid.

Only the event payload is used, so editing an invoice after it was issued does not change what
was posted; a correction is a manual OD entry."""
from __future__ import annotations

import datetime

import psycopg

from core.domain.result import Err, Ok, Result
from modules.finance.api.ledger_posting_service import SYSTEM_ACTOR, LedgerPostingService
from modules.finance.api.posting_rule_service import PostingRuleService
from modules.finance.domain.ledger import SourceRef
from modules.finance.domain.posting import invoice_entry, to_xof

INVOICE_MODULE = "finance"
LABELS = {"issued": "Facture {invoice_id}", "paid": "Règlement facture {invoice_id}"}


class InvoiceLedgerService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection
        self._posting = LedgerPostingService(connection)
        self._rules = PostingRuleService(connection)

    def post_issued(
        self,
        *,
        tenant_id: str,
        invoice_id: str,
        partner_id: str,
        amount: object,
        currency: str,
        issued_on: datetime.date,
        correlation_id: str,
        causation_id: str | None = None,
    ) -> Result[list[dict]]:
        return self._post(
            "issued", tenant_id=tenant_id, invoice_id=invoice_id, partner_id=partner_id, amount=amount,
            currency=currency, entry_date=issued_on, correlation_id=correlation_id, causation_id=causation_id,
        )

    def post_paid(
        self,
        *,
        tenant_id: str,
        invoice_id: str,
        partner_id: str,
        amount: object,
        currency: str,
        paid_on: datetime.date,
        correlation_id: str,
        causation_id: str | None = None,
    ) -> Result[list[dict]]:
        issued = SourceRef(INVOICE_MODULE, invoice_id, "invoice_issued")
        if self._posting.find_by_source(tenant_id=tenant_id, source=issued) is None:
            return Err(
                "INVOICE_NOT_POSTED",
                f"invoice {invoice_id} has no posted sales entry yet, so its payment cannot clear the customer",
                f"la facture {invoice_id} n'a pas encore d'écriture de vente comptabilisée ; son règlement ne peut pas solder le client",
            )
        return self._post(
            "paid", tenant_id=tenant_id, invoice_id=invoice_id, partner_id=partner_id, amount=amount,
            currency=currency, entry_date=paid_on, correlation_id=correlation_id, causation_id=causation_id,
        )

    def _post(
        self,
        kind: str,
        *,
        tenant_id: str,
        invoice_id: str,
        partner_id: str,
        amount: object,
        currency: str,
        entry_date: datetime.date,
        correlation_id: str,
        causation_id: str | None,
    ) -> Result[list[dict]]:
        source = SourceRef(INVOICE_MODULE, invoice_id, f"invoice_{kind}")
        existing = self._posting.find_by_source(tenant_id=tenant_id, source=source)
        if existing is not None:
            return Ok([existing])
        xof = to_xof(amount, currency=currency)
        if isinstance(xof, Err):
            return xof
        label = LABELS[kind].format(invoice_id=invoice_id)
        entry = invoice_entry(
            kind, amount=xof.value, partner_id=partner_id, label=label,
            rules=self._rules.rules_for(tenant_id=tenant_id, source="invoice"),
        )
        if isinstance(entry, Err):
            return entry
        journal_code, lines = entry.value
        posted = self._posting.post_entry(
            tenant_id=tenant_id,
            actor_id=SYSTEM_ACTOR,
            journal_code=journal_code,
            entry_date=entry_date,
            label=label,
            lines=lines,
            correlation_id=correlation_id,
            source=source,
            reference=invoice_id,
            causation_id=causation_id,
        )
        if isinstance(posted, Err):
            return posted
        return Ok([posted.value])
```

- [ ] **Step 4: Route the invoice events**

In `backend/modules/finance/api/ledger_event_postings.py`, replace the `SOURCES` dict with:

```python
# event type -> (source_module, payload key holding the source id, failure kind)
SOURCES: dict[str, tuple[str, str, str]] = {
    "payroll.run.approved": ("payroll", "run_id", "payroll_run"),
    "payroll.run.paid": ("payroll", "run_id", "payroll_payment"),
    "payroll.run.reversed": ("payroll", "run_id", "payroll_reversal"),
    "finance.invoice.issued": ("finance", "invoice_id", "invoice_issued"),
    "finance.invoice.paid": ("finance", "invoice_id", "invoice_paid"),
}
```

and in `post_for_event`, insert this block immediately before the final `raise ValueError(...)` line:

```python
    if event_type in ("finance.invoice.issued", "finance.invoice.paid"):
        from modules.finance.api.invoice_ledger_service import InvoiceLedgerService

        invoices = InvoiceLedgerService(connection)
        common = {
            "tenant_id": tenant_id,
            "invoice_id": str(payload["invoice_id"]),
            "partner_id": str(payload["partner_id"]),
            "amount": payload["amount"],
            "currency": str(payload["currency"]),
            "correlation_id": correlation_id,
            "causation_id": causation_id,
        }
        if event_type == "finance.invoice.issued":
            return invoices.post_issued(issued_on=occurred_on(envelope), **common)
        return invoices.post_paid(paid_on=occurred_on(envelope), **common)
```

(`ledger_consumers.py` registers one handler per `SOURCES` key at import, so the two new consumers need no other change.)

In `backend/events/CATALOG.md`, set the **Consumers** cell of the `finance.invoice.issued` and `finance.invoice.paid` rows to `finance`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest modules/finance core/test_error_translations.py -q -rs`
Expected: all PASS, no skipped integration test.

- [ ] **Step 6: Commit**

```bash
git add backend/modules/finance/api/invoice_ledger_service.py backend/modules/finance/api/ledger_event_postings.py backend/modules/finance/events/test_invoice_ledger_consumers_integration.py backend/events/CATALOG.md
git commit -m "feat(finance): post issued and paid invoices to the sales and bank journals

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Editing the chart of accounts and the posting rules

**Files:**
- Create: `backend/modules/finance/api/account_service.py`
- Modify: `backend/modules/finance/api/posting_rule_service.py` (whole file replaced; `rules_for` unchanged)
- Test: `backend/modules/finance/api/test_ledger_master_data_integration.py`

**Interfaces:**
- Consumes: Task 1 (`Account`, `validate_account`), Task 2 (`PostingRule`, `validate_rule`), Task 4 (`LedgerPostingService.load_accounts`, `.journal_codes`, `ledger` fixture), Task 5 (`PostingRuleService.rules_for`).
- Produces:
  - `AccountService(connection)`: `list_accounts(*, tenant_id) -> list[dict]` (keys `code, name, class_no, account_type, is_postable, parent_code`, ordered by code); `list_journals(*, tenant_id) -> list[dict]` (keys `code, name, journal_type`); `create_account(*, tenant_id, actor_id, code, name, account_type, is_postable=True, parent_code=None) -> Result[dict]` (`INVALID_ACCOUNT`, `ACCOUNT_EXISTS`); `update_account(*, tenant_id, actor_id, code, name=None, account_type=None, is_postable=None, parent_code=None) -> Result[dict]` (`None` = unchanged, `parent_code=""` removes the parent; the number never changes; `NOT_FOUND`).
  - `PostingRuleService(connection)`: `rules_for` (as before); `list_rules(*, tenant_id) -> list[dict]` (keys `id, source, source_kind, code, debit_account_code, credit_account_code, journal_code, status, confirmed_by, confirmed_at, updated_at`); `create_rule(*, tenant_id, actor_id, source, source_kind, code, debit_account_code=None, credit_account_code=None, journal_code=None) -> Result[dict]` (`POSTING_RULE_EXISTS`, `INVALID_POSTING_RULE`, `ACCOUNT_NOT_POSTABLE`); `update_rule(*, tenant_id, actor_id, rule_id, debit_account_code=None, credit_account_code=None, journal_code=None) -> Result[dict]` (`None` = unchanged, `""` clears; always back to `to_confirm`); `confirm_rule(*, tenant_id, actor_id, rule_id) -> Result[dict]` (`INVALID_TRANSITION` when already confirmed).

- [ ] **Step 1: Write the failing test**

`backend/modules/finance/api/test_ledger_master_data_integration.py`:

```python
"""Editing the chart of accounts and the posting rules."""
from __future__ import annotations

from core.domain.result import Err, Ok
from modules.finance.api.account_service import AccountService
from modules.finance.api.posting_rule_service import PostingRuleService


def _audited(ledger, entity_id: str, action: str) -> int:
    return ledger["db"].execute(
        "SELECT count(*) FROM core.audit_log WHERE tenant_id = %s AND entity_id = %s AND action = %s",
        (ledger["tenant"], entity_id, action),
    ).fetchone()[0]


def _rule(ledger, source_kind: str) -> dict:
    rules = PostingRuleService(ledger["db"]).list_rules(tenant_id=ledger["tenant"])
    return next(rule for rule in rules if rule["source_kind"] == source_kind and rule["code"] == "*")


def test_a_sub_account_extends_its_heading(ledger):
    accounts = AccountService(ledger["db"])
    created = accounts.create_account(
        tenant_id=ledger["tenant"], actor_id=ledger["actor"], code="5211", name="BDM-SA compte courant",
        account_type="asset", parent_code="52",
    )
    assert isinstance(created, Ok), created
    assert created.value == {
        "code": "5211", "name": "BDM-SA compte courant", "class_no": 5,
        "account_type": "asset", "is_postable": True, "parent_code": "52",
    }
    assert _audited(ledger, "5211", "account.created") == 1
    duplicate = accounts.create_account(
        tenant_id=ledger["tenant"], actor_id=ledger["actor"], code="5211", name="Autre",
        account_type="asset", parent_code="52",
    )
    assert isinstance(duplicate, Err) and duplicate.code == "ACCOUNT_EXISTS"
    wrong_parent = accounts.create_account(
        tenant_id=ledger["tenant"], actor_id=ledger["actor"], code="5711", name="Caisse usine",
        account_type="asset", parent_code="52",
    )
    assert isinstance(wrong_parent, Err) and wrong_parent.code == "INVALID_ACCOUNT"


def test_editing_an_account_keeps_its_number_and_audits_the_change(ledger):
    accounts = AccountService(ledger["db"])
    updated = accounts.update_account(tenant_id=ledger["tenant"], actor_id=ledger["actor"], code="571", name="Caisse usine")
    assert isinstance(updated, Ok), updated
    assert updated.value["name"] == "Caisse usine" and updated.value["is_postable"] is True
    payload = ledger["db"].execute(
        "SELECT payload FROM core.audit_log WHERE tenant_id = %s AND entity_id = '571' AND action = 'account.updated'",
        (ledger["tenant"],),
    ).fetchone()[0]
    assert payload == {"name": "Caisse usine"}
    missing = accounts.update_account(tenant_id=ledger["tenant"], actor_id=ledger["actor"], code="999", name="x")
    assert isinstance(missing, Err) and missing.code == "NOT_FOUND"
    bad_type = accounts.update_account(tenant_id=ledger["tenant"], actor_id=ledger["actor"], code="571", account_type="cash")
    assert isinstance(bad_type, Err) and bad_type.code == "INVALID_ACCOUNT"


def test_the_six_journals_are_listed(ledger):
    codes = [journal["code"] for journal in AccountService(ledger["db"]).list_journals(tenant_id=ledger["tenant"])]
    assert sorted(codes) == ["ACH", "BNQ", "CAI", "OD", "PAIE", "VTE"]


def test_a_code_specific_rule_is_created_to_confirm(ledger):
    rules = PostingRuleService(ledger["db"])
    created = rules.create_rule(
        tenant_id=ledger["tenant"], actor_id=ledger["actor"], source="payroll",
        source_kind="employee_contribution", code="AMO_EE", credit_account_code="433",
    )
    assert isinstance(created, Ok), created
    assert created.value["status"] == "to_confirm" and created.value["credit_account_code"] == "433"
    assert _audited(ledger, created.value["id"], "posting_rule.created") == 1
    duplicate = rules.create_rule(
        tenant_id=ledger["tenant"], actor_id=ledger["actor"], source="payroll",
        source_kind="employee_contribution", code="AMO_EE", credit_account_code="431",
    )
    assert isinstance(duplicate, Err) and duplicate.code == "POSTING_RULE_EXISTS"
    heading = rules.create_rule(
        tenant_id=ledger["tenant"], actor_id=ledger["actor"], source="payroll",
        source_kind="employer_contribution", code="AMO_ER", debit_account_code="66", credit_account_code="433",
    )
    assert isinstance(heading, Err) and heading.code == "ACCOUNT_NOT_POSTABLE"


def test_confirming_then_editing_sends_a_rule_back_to_confirmation(ledger):
    rules = PostingRuleService(ledger["db"])
    net = _rule(ledger, "net")
    confirmed = rules.confirm_rule(tenant_id=ledger["tenant"], actor_id=ledger["actor"], rule_id=net["id"])
    assert isinstance(confirmed, Ok), confirmed
    assert confirmed.value["status"] == "confirmed" and confirmed.value["confirmed_by"] == ledger["actor"]
    twice = rules.confirm_rule(tenant_id=ledger["tenant"], actor_id=ledger["actor"], rule_id=net["id"])
    assert isinstance(twice, Err) and twice.code == "INVALID_TRANSITION"
    AccountService(ledger["db"]).create_account(
        tenant_id=ledger["tenant"], actor_id=ledger["actor"], code="4221", name="Rémunérations dues, usine",
        account_type="liability", parent_code="42",
    )
    edited = rules.update_rule(tenant_id=ledger["tenant"], actor_id=ledger["actor"], rule_id=net["id"], credit_account_code="4221")
    assert isinstance(edited, Ok), edited
    assert edited.value["credit_account_code"] == "4221"
    assert edited.value["status"] == "to_confirm" and edited.value["confirmed_by"] is None


def test_a_rule_cannot_lose_both_accounts(ledger):
    rules = PostingRuleService(ledger["db"])
    earning = _rule(ledger, "earning")
    cleared = rules.update_rule(tenant_id=ledger["tenant"], actor_id=ledger["actor"], rule_id=earning["id"], debit_account_code="")
    assert isinstance(cleared, Err) and cleared.code == "INVALID_POSTING_RULE"
    missing = rules.update_rule(tenant_id=ledger["tenant"], actor_id=ledger["actor"], rule_id="nope", debit_account_code="661")
    assert isinstance(missing, Err) and missing.code == "NOT_FOUND"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python -m pytest modules/finance/api/test_ledger_master_data_integration.py -q`
Expected: collection error `No module named 'modules.finance.api.account_service'`.

- [ ] **Step 3: Write the account service**

`backend/modules/finance/api/account_service.py`:

```python
"""The chart of accounts and the journals of a tenant, as the screens list and edit them.

An account's number never changes once created (lines reference it); everything else can be
edited behind finance.admin_accounts."""
from __future__ import annotations

import psycopg

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.finance.domain.ledger import Account, validate_account

ACCOUNT_KEYS = ("code", "name", "class_no", "account_type", "is_postable", "parent_code")
JOURNAL_KEYS = ("code", "name", "journal_type")


def account_dict(account: Account) -> dict:
    return {key: getattr(account, key) for key in ACCOUNT_KEYS}


class AccountService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def list_accounts(self, *, tenant_id: str) -> list[dict]:
        rows = self._connection.execute(
            """
            SELECT code, name, class_no, account_type, is_postable, parent_code
            FROM finance.accounts WHERE tenant_id = %s ORDER BY code
            """,
            (tenant_id,),
        ).fetchall()
        return [dict(zip(ACCOUNT_KEYS, row)) for row in rows]

    def list_journals(self, *, tenant_id: str) -> list[dict]:
        rows = self._connection.execute(
            "SELECT code, name, journal_type FROM finance.journals WHERE tenant_id = %s ORDER BY code", (tenant_id,)
        ).fetchall()
        return [dict(zip(JOURNAL_KEYS, row)) for row in rows]

    def _get(self, tenant_id: str, code: str | None, *, lock: bool = False) -> Account | None:
        if not code:
            return None
        row = self._connection.execute(
            """
            SELECT code, name, class_no, account_type, is_postable, parent_code
            FROM finance.accounts WHERE tenant_id = %s AND code = %s
            """
            + (" FOR UPDATE" if lock else ""),
            (tenant_id, code),
        ).fetchone()
        return None if row is None else Account(*row)

    def create_account(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        code: str,
        name: str,
        account_type: str,
        is_postable: bool = True,
        parent_code: str | None = None,
    ) -> Result[dict]:
        code = code.strip()
        parent_code = (parent_code or "").strip() or None
        candidate = Account(
            code=code,
            name=name.strip(),
            class_no=int(code[0]) if code[:1].isdigit() else 0,
            account_type=account_type,
            is_postable=is_postable,
            parent_code=parent_code,
        )
        checked = validate_account(candidate, self._get(tenant_id, parent_code))
        if isinstance(checked, Err):
            return checked
        if self._get(tenant_id, code) is not None:
            return Err("ACCOUNT_EXISTS", f"account {code} already exists", f"le compte {code} existe déjà")
        self._connection.execute(
            """
            INSERT INTO finance.accounts (tenant_id, code, name, class_no, account_type, is_postable, parent_code)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                tenant_id, candidate.code, candidate.name, candidate.class_no,
                candidate.account_type, candidate.is_postable, candidate.parent_code,
            ),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="account.created",
            entity_type="account",
            entity_id=code,
            payload=account_dict(candidate),
        )
        return Ok(account_dict(candidate))

    def update_account(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        code: str,
        name: str | None = None,
        account_type: str | None = None,
        is_postable: bool | None = None,
        parent_code: str | None = None,
    ) -> Result[dict]:
        """`None` leaves a field unchanged; `parent_code=""` removes the parent."""
        current = self._get(tenant_id, code, lock=True)
        if current is None:
            return Err("NOT_FOUND", f"account {code} not found", f"compte {code} introuvable")
        new_parent = current.parent_code if parent_code is None else (parent_code.strip() or None)
        updated = Account(
            code=current.code,
            name=current.name if name is None else name.strip(),
            class_no=current.class_no,
            account_type=current.account_type if account_type is None else account_type,
            is_postable=current.is_postable if is_postable is None else is_postable,
            parent_code=new_parent,
        )
        checked = validate_account(updated, self._get(tenant_id, new_parent))
        if isinstance(checked, Err):
            return checked
        self._connection.execute(
            """
            UPDATE finance.accounts
            SET name = %s, account_type = %s, is_postable = %s, parent_code = %s, updated_at = NOW()
            WHERE tenant_id = %s AND code = %s
            """,
            (updated.name, updated.account_type, updated.is_postable, updated.parent_code, tenant_id, code),
        )
        changed = {key: getattr(updated, key) for key in ACCOUNT_KEYS if getattr(updated, key) != getattr(current, key)}
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="account.updated",
            entity_type="account",
            entity_id=code,
            payload=changed,
        )
        return Ok(account_dict(updated))
```

- [ ] **Step 4: Replace the posting rule service**

`backend/modules/finance/api/posting_rule_service.py`:

```python
"""The posting rules of a tenant: read by the posters, edited from the Posting rules screen.

Seeded rules start `to_confirm`; the accountant confirms them one by one. Any edit sends a rule
back to `to_confirm`, so "confirmed" always means "this exact mapping was checked"."""
from __future__ import annotations

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.finance.api.ledger_posting_service import LedgerPostingService
from modules.finance.domain.posting import PostingRule, validate_rule

RULE_KEYS = (
    "id", "source", "source_kind", "code", "debit_account_code", "credit_account_code",
    "journal_code", "status", "confirmed_by", "confirmed_at", "updated_at",
)
RULE_COLUMNS = ", ".join(RULE_KEYS)


def rule_not_found(rule_id: str) -> Err:
    return Err("NOT_FOUND", f"posting rule {rule_id} not found", f"règle d'imputation {rule_id} introuvable")


def _merge(current: str | None, new: str | None) -> str | None:
    """`None` keeps the current value; an empty string clears it."""
    if new is None:
        return current
    return new.strip() or None


class PostingRuleService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def rules_for(self, *, tenant_id: str, source: str) -> list[PostingRule]:
        rows = self._connection.execute(
            """
            SELECT source, source_kind, code, debit_account_code, credit_account_code, journal_code, status, id
            FROM finance.posting_rules
            WHERE tenant_id = %s AND source = %s
            """,
            (tenant_id, source),
        ).fetchall()
        return [PostingRule(*row) for row in rows]

    def list_rules(self, *, tenant_id: str) -> list[dict]:
        rows = self._connection.execute(
            f"SELECT {RULE_COLUMNS} FROM finance.posting_rules WHERE tenant_id = %s ORDER BY source, source_kind, code",
            (tenant_id,),
        ).fetchall()
        return [dict(zip(RULE_KEYS, row)) for row in rows]

    def _get(self, tenant_id: str, rule_id: str) -> dict | None:
        row = self._connection.execute(
            f"SELECT {RULE_COLUMNS} FROM finance.posting_rules WHERE tenant_id = %s AND id = %s FOR UPDATE",
            (tenant_id, rule_id),
        ).fetchone()
        return None if row is None else dict(zip(RULE_KEYS, row))

    def _validate(self, tenant_id: str, rule: PostingRule) -> Result[PostingRule]:
        ledger = LedgerPostingService(self._connection)
        codes = [code for code in (rule.debit_account_code, rule.credit_account_code) if code]
        return validate_rule(rule, ledger.load_accounts(tenant_id=tenant_id, codes=codes), ledger.journal_codes(tenant_id=tenant_id))

    def create_rule(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        source: str,
        source_kind: str,
        code: str,
        debit_account_code: str | None = None,
        credit_account_code: str | None = None,
        journal_code: str | None = None,
    ) -> Result[dict]:
        checked = self._validate(
            tenant_id,
            PostingRule(
                source=source.strip(),
                source_kind=source_kind.strip(),
                code=code,
                debit_account_code=_merge(None, debit_account_code),
                credit_account_code=_merge(None, credit_account_code),
                journal_code=_merge(None, journal_code),
            ),
        )
        if isinstance(checked, Err):
            return checked
        rule = checked.value
        exists = self._connection.execute(
            """
            SELECT 1 FROM finance.posting_rules
            WHERE tenant_id = %s AND source = %s AND source_kind = %s AND code = %s
            """,
            (tenant_id, rule.source, rule.source_kind, rule.code),
        ).fetchone()
        if exists:
            return Err(
                "POSTING_RULE_EXISTS",
                f"a rule for {rule.source} / {rule.source_kind} / {rule.code} already exists",
                f"une règle existe déjà pour {rule.source} / {rule.source_kind} / {rule.code}",
            )
        rule_id = str(ULID())
        self._connection.execute(
            """
            INSERT INTO finance.posting_rules
                (id, tenant_id, source, source_kind, code, debit_account_code, credit_account_code, journal_code)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                rule_id, tenant_id, rule.source, rule.source_kind, rule.code,
                rule.debit_account_code, rule.credit_account_code, rule.journal_code,
            ),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="posting_rule.created",
            entity_type="posting_rule",
            entity_id=rule_id,
            payload={
                "source": rule.source,
                "source_kind": rule.source_kind,
                "code": rule.code,
                "debit_account_code": rule.debit_account_code,
                "credit_account_code": rule.credit_account_code,
                "journal_code": rule.journal_code,
            },
        )
        return Ok(self._get(tenant_id, rule_id))

    def update_rule(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        rule_id: str,
        debit_account_code: str | None = None,
        credit_account_code: str | None = None,
        journal_code: str | None = None,
    ) -> Result[dict]:
        """`None` keeps a field, `""` clears it. Any edit sends the rule back to `to_confirm`."""
        current = self._get(tenant_id, rule_id)
        if current is None:
            return rule_not_found(rule_id)
        checked = self._validate(
            tenant_id,
            PostingRule(
                source=current["source"],
                source_kind=current["source_kind"],
                code=current["code"],
                debit_account_code=_merge(current["debit_account_code"], debit_account_code),
                credit_account_code=_merge(current["credit_account_code"], credit_account_code),
                journal_code=_merge(current["journal_code"], journal_code),
            ),
        )
        if isinstance(checked, Err):
            return checked
        rule = checked.value
        self._connection.execute(
            """
            UPDATE finance.posting_rules
            SET debit_account_code = %s, credit_account_code = %s, journal_code = %s,
                status = 'to_confirm', confirmed_by = NULL, confirmed_at = NULL, updated_at = NOW()
            WHERE tenant_id = %s AND id = %s
            """,
            (rule.debit_account_code, rule.credit_account_code, rule.journal_code, tenant_id, rule_id),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="posting_rule.updated",
            entity_type="posting_rule",
            entity_id=rule_id,
            payload={
                "debit_account_code": rule.debit_account_code,
                "credit_account_code": rule.credit_account_code,
                "journal_code": rule.journal_code,
                "previous_status": current["status"],
            },
        )
        return Ok(self._get(tenant_id, rule_id))

    def confirm_rule(self, *, tenant_id: str, actor_id: str, rule_id: str) -> Result[dict]:
        current = self._get(tenant_id, rule_id)
        if current is None:
            return rule_not_found(rule_id)
        key = f"{current['source']} / {current['source_kind']} / {current['code']}"
        if current["status"] == "confirmed":
            return Err(
                "INVALID_TRANSITION",
                f"posting rule {key} is already confirmed",
                f"la règle d'imputation {key} est déjà confirmée",
            )
        self._connection.execute(
            """
            UPDATE finance.posting_rules
            SET status = 'confirmed', confirmed_by = %s, confirmed_at = NOW(), updated_at = NOW()
            WHERE tenant_id = %s AND id = %s
            """,
            (actor_id, tenant_id, rule_id),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="posting_rule.confirmed",
            entity_type="posting_rule",
            entity_id=rule_id,
            payload={"source": current["source"], "source_kind": current["source_kind"], "code": current["code"]},
        )
        return Ok(self._get(tenant_id, rule_id))
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest modules/finance core/test_error_translations.py -q -rs`
Expected: all PASS, no skipped integration test.

- [ ] **Step 6: Commit**

```bash
git add backend/modules/finance/api/account_service.py backend/modules/finance/api/posting_rule_service.py backend/modules/finance/api/test_ledger_master_data_integration.py
git commit -m "feat(finance): edit accounts and posting rules, confirm rules one by one

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Manual OD entries and the ledger's read side

**Files:**
- Create: `backend/modules/finance/api/ledger_query_service.py`
- Create: `backend/modules/finance/api/manual_entry_service.py`
- Test: `backend/modules/finance/api/test_manual_entries_integration.py`

**Interfaces:**
- Consumes: Task 4 (`LedgerPostingService.insert_draft`, `.check_draft`, `.replace_lines`, `.lines_of`, `.post_draft`, `.reverse_entry`, `entry_not_found`, `ENTRY_SELECT`, `entry_dict`, `STATUS_FR`), Task 3 (`PeriodService`).
- Produces:
  - `LedgerQueryService(connection)`: `entries_for_source(*, tenant_id, source_module, source_id) -> list[dict]` (the contract read); `list_entries(*, tenant_id, date_from, date_to, journal_code=None, status=None) -> list[dict]`; `get_entry(*, tenant_id, entry_id) -> dict | None` — entry dict plus `lines`: `[{line_no, account_code, account_name, debit, credit, label, partner_id, partner_name, employee_ref}]`.
  - `ManualEntryService(connection)`: `create_draft(*, tenant_id, actor_id, journal_code, entry_date, label, lines, reference=None) -> Result[dict]`; `update_draft(*, tenant_id, actor_id, entry_id, journal_code=None, entry_date=None, label=None, reference=None, lines=None) -> Result[dict]` (drafts only: `ENTRY_POSTED`); `delete_draft(*, tenant_id, actor_id, entry_id) -> Result[dict]`; `post(*, tenant_id, actor_id, entry_id, correlation_id) -> Result[dict]`; `reverse(*, tenant_id, actor_id, entry_id, entry_date, correlation_id) -> Result[dict]`. Returned dicts are `get_entry` / `post_draft` shapes.

- [ ] **Step 1: Write the failing test**

`backend/modules/finance/api/test_manual_entries_integration.py`:

```python
"""Manual OD entries (draft -> posted -> reversed) and the ledger's read side."""
from __future__ import annotations

import datetime
from decimal import Decimal

from ulid import ULID

from core.domain.result import Err, Ok
from modules.finance.api.ledger_posting_service import LedgerPostingService
from modules.finance.api.ledger_query_service import LedgerQueryService
from modules.finance.api.manual_entry_service import ManualEntryService
from modules.finance.api.period_service import PeriodService
from modules.finance.domain.ledger import EntryLine, SourceRef

D = Decimal
FEBRUARY = datetime.date(2030, 2, 1)
END_OF_FEBRUARY = datetime.date(2030, 2, 28)
DAY = datetime.date(2030, 2, 14)
BALANCED = [EntryLine("641", debit=D(150000)), EntryLine("521", credit=D(150000))]


def _draft(ledger, lines=BALANCED):
    return ManualEntryService(ledger["db"]).create_draft(
        tenant_id=ledger["tenant"], actor_id=ledger["actor"], journal_code="OD", entry_date=DAY,
        label="Patente 2030", lines=lines, reference="AVIS-2030-17",
    )


def _post(ledger, entry_id: str):
    return ManualEntryService(ledger["db"]).post(
        tenant_id=ledger["tenant"], actor_id=ledger["actor"], entry_id=entry_id, correlation_id=str(ULID())
    )


def test_a_draft_may_be_unbalanced_and_is_posted_only_once_it_balances(ledger):
    manual = ManualEntryService(ledger["db"])
    draft = _draft(ledger, [EntryLine("641", debit=D(150000)), EntryLine("521", credit=D(100000))])
    assert isinstance(draft, Ok), draft
    entry_id = draft.value["id"]
    assert draft.value["status"] == "draft" and draft.value["number"] is None
    refused = _post(ledger, entry_id)
    assert isinstance(refused, Err) and refused.code == "ENTRY_UNBALANCED"
    fixed = manual.update_draft(tenant_id=ledger["tenant"], actor_id=ledger["actor"], entry_id=entry_id, lines=BALANCED)
    assert isinstance(fixed, Ok), fixed
    assert fixed.value["total_credit"] == D(150000)
    posted = _post(ledger, entry_id)
    assert isinstance(posted, Ok), posted
    assert posted.value["number"] == "OD-2030-000001"
    actions = {row[0] for row in ledger["db"].execute("SELECT action FROM core.audit_log WHERE entity_id = %s", (entry_id,))}
    assert actions == {"journal_entry.created", "journal_entry.updated", "journal_entry.posted"}


def test_a_posted_entry_is_never_edited_or_deleted(ledger):
    manual = ManualEntryService(ledger["db"])
    entry_id = _draft(ledger).value["id"]
    _post(ledger, entry_id)
    edited = manual.update_draft(tenant_id=ledger["tenant"], actor_id=ledger["actor"], entry_id=entry_id, label="changed")
    assert isinstance(edited, Err) and edited.code == "ENTRY_POSTED" and edited.message_fr
    deleted = manual.delete_draft(tenant_id=ledger["tenant"], actor_id=ledger["actor"], entry_id=entry_id)
    assert isinstance(deleted, Err) and deleted.code == "ENTRY_POSTED"


def test_a_draft_can_be_deleted_and_the_deletion_is_audited(ledger):
    entry_id = _draft(ledger).value["id"]
    deleted = ManualEntryService(ledger["db"]).delete_draft(tenant_id=ledger["tenant"], actor_id=ledger["actor"], entry_id=entry_id)
    assert isinstance(deleted, Ok)
    assert LedgerQueryService(ledger["db"]).get_entry(tenant_id=ledger["tenant"], entry_id=entry_id) is None
    payload = ledger["db"].execute(
        "SELECT payload FROM core.audit_log WHERE entity_id = %s AND action = 'journal_entry.deleted'", (entry_id,)
    ).fetchone()[0]
    assert payload["label"] == "Patente 2030" and payload["status"] == "draft"


def test_a_draft_in_a_period_closed_later_cannot_be_posted_until_reopened(ledger):
    periods = PeriodService(ledger["db"])
    entry_id = _draft(ledger).value["id"]
    periods.close_period(tenant_id=ledger["tenant"], actor_id=ledger["actor"], period=FEBRUARY)
    refused = _post(ledger, entry_id)
    assert isinstance(refused, Err) and refused.code == "PERIOD_CLOSED"
    assert LedgerQueryService(ledger["db"]).get_entry(tenant_id=ledger["tenant"], entry_id=entry_id)["status"] == "draft"
    periods.reopen_period(tenant_id=ledger["tenant"], actor_id=ledger["actor"], period=FEBRUARY)
    assert isinstance(_post(ledger, entry_id), Ok)


def test_a_manual_entry_is_corrected_by_its_mirror(ledger):
    entry_id = _draft(ledger).value["id"]
    _post(ledger, entry_id)
    reversal = ManualEntryService(ledger["db"]).reverse(
        tenant_id=ledger["tenant"], actor_id=ledger["actor"], entry_id=entry_id,
        entry_date=END_OF_FEBRUARY, correlation_id=str(ULID()),
    )
    assert isinstance(reversal, Ok), reversal
    assert reversal.value["reversal_of"] == entry_id and reversal.value["source_kind"] is None
    assert LedgerQueryService(ledger["db"]).get_entry(tenant_id=ledger["tenant"], entry_id=entry_id)["status"] == "reversed"


def test_the_entry_detail_names_accounts_and_partners(ledger):
    partner_id = str(ULID())
    ledger["db"].execute(
        "INSERT INTO core.partners (id, tenant_id, name, kind) VALUES (%s, %s, %s, 'customer')",
        (partner_id, ledger["tenant"], f"Client {partner_id}"),
    )
    entry_id = _draft(
        ledger, [EntryLine("411", debit=D(5000), partner_id=partner_id, label="Facture manuelle"), EntryLine("702", credit=D(5000))]
    ).value["id"]
    detail = LedgerQueryService(ledger["db"]).get_entry(tenant_id=ledger["tenant"], entry_id=entry_id)
    assert [(line["account_code"], line["account_name"], line["partner_name"]) for line in detail["lines"]] == [
        ("411", "Clients", f"Client {partner_id}"),
        ("702", "Ventes de produits finis", None),
    ]


def test_entries_are_found_by_source_and_by_filters(ledger):
    posting = LedgerPostingService(ledger["db"])
    for kind, journal, lines in (
        ("payroll_run", "PAIE", [EntryLine("661", debit=D(100)), EntryLine("422", credit=D(100))]),
        ("payroll_payment_bank", "BNQ", [EntryLine("422", debit=D(100)), EntryLine("521", credit=D(100))]),
    ):
        posted = posting.post_entry(
            tenant_id=ledger["tenant"], actor_id=ledger["actor"], journal_code=journal, entry_date=DAY,
            label="Paie 02/2030", lines=lines, correlation_id=str(ULID()), source=SourceRef("payroll", "RUN-Q", kind),
        )
        assert isinstance(posted, Ok), posted
    _draft(ledger)
    query = LedgerQueryService(ledger["db"])
    found = query.entries_for_source(tenant_id=ledger["tenant"], source_module="payroll", source_id="RUN-Q")
    assert sorted(entry["source_kind"] for entry in found) == ["payroll_payment_bank", "payroll_run"]
    assert {entry["status"] for entry in found} == {"posted"}
    february = query.list_entries(tenant_id=ledger["tenant"], date_from=FEBRUARY, date_to=END_OF_FEBRUARY)
    assert len(february) == 3
    paie = query.list_entries(tenant_id=ledger["tenant"], date_from=FEBRUARY, date_to=END_OF_FEBRUARY, journal_code="PAIE")
    assert [entry["journal_code"] for entry in paie] == ["PAIE"]
    drafts = query.list_entries(tenant_id=ledger["tenant"], date_from=FEBRUARY, date_to=END_OF_FEBRUARY, status="draft")
    assert len(drafts) == 1
    march = query.list_entries(tenant_id=ledger["tenant"], date_from=datetime.date(2030, 3, 1), date_to=datetime.date(2030, 3, 31))
    assert march == []
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python -m pytest modules/finance/api/test_manual_entries_integration.py -q`
Expected: collection error `No module named 'modules.finance.api.ledger_query_service'`.

- [ ] **Step 3: Write the query service**

`backend/modules/finance/api/ledger_query_service.py`:

```python
"""The ledger's read side: entries of one source (what the payroll run page shows), entries by
filters (the Entries screen, which is also the journal listing), one entry with its lines."""
from __future__ import annotations

import datetime

import psycopg

from modules.finance.api.ledger_sql import ENTRY_SELECT, entry_dict

LINE_KEYS = (
    "line_no", "account_code", "account_name", "debit", "credit", "label",
    "partner_id", "partner_name", "employee_ref",
)


class LedgerQueryService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def entries_for_source(self, *, tenant_id: str, source_module: str, source_id: str) -> list[dict]:
        """Every entry written for one source (a payroll run, an invoice), reversals included."""
        rows = self._connection.execute(
            f"""{ENTRY_SELECT}
            WHERE e.tenant_id = %s AND e.source_module = %s AND e.source_id = %s
            ORDER BY e.created_at, e.id""",
            (tenant_id, source_module, source_id),
        ).fetchall()
        return [entry_dict(row) for row in rows]

    def list_entries(
        self,
        *,
        tenant_id: str,
        date_from: datetime.date,
        date_to: datetime.date,
        journal_code: str | None = None,
        status: str | None = None,
    ) -> list[dict]:
        clauses = ["e.tenant_id = %s", "e.entry_date BETWEEN %s AND %s"]
        params: list[object] = [tenant_id, date_from, date_to]
        if journal_code:
            clauses.append("e.journal_code = %s")
            params.append(journal_code)
        if status:
            clauses.append("e.status = %s")
            params.append(status)
        rows = self._connection.execute(
            f"""{ENTRY_SELECT}
            WHERE {' AND '.join(clauses)}
            ORDER BY e.entry_date DESC, e.number DESC NULLS FIRST, e.created_at DESC""",
            params,
        ).fetchall()
        return [entry_dict(row) for row in rows]

    def get_entry(self, *, tenant_id: str, entry_id: str) -> dict | None:
        row = self._connection.execute(
            f"{ENTRY_SELECT} WHERE e.tenant_id = %s AND e.id = %s", (tenant_id, entry_id)
        ).fetchone()
        if row is None:
            return None
        entry = entry_dict(row)
        lines = self._connection.execute(
            """
            SELECT l.line_no, l.account_code, a.name, l.debit, l.credit, l.label, l.partner_id, p.name, l.employee_ref
            FROM finance.journal_lines l
            JOIN finance.accounts a ON a.tenant_id = l.tenant_id AND a.code = l.account_code
            LEFT JOIN core.partners p ON p.id = l.partner_id
            WHERE l.entry_id = %s
            ORDER BY l.line_no
            """,
            (entry_id,),
        ).fetchall()
        entry["lines"] = [dict(zip(LINE_KEYS, line)) for line in lines]
        return entry
```

- [ ] **Step 4: Write the manual entry service**

`backend/modules/finance/api/manual_entry_service.py`:

```python
"""Manual entries (typically in the OD journal): saved as drafts, edited while draft, posted
through the same path as automatic entries, corrected afterwards only by reversal."""
from __future__ import annotations

import datetime

import psycopg

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.finance.api.ledger_posting_service import LedgerPostingService, entry_not_found
from modules.finance.api.ledger_query_service import LedgerQueryService
from modules.finance.api.ledger_sql import STATUS_FR
from modules.finance.domain.ledger import EntryLine


class ManualEntryService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection
        self._posting = LedgerPostingService(connection)
        self._query = LedgerQueryService(connection)

    def create_draft(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        journal_code: str,
        entry_date: datetime.date,
        label: str,
        lines: list[EntryLine],
        reference: str | None = None,
    ) -> Result[dict]:
        inserted = self._posting.insert_draft(
            tenant_id=tenant_id, actor_id=actor_id, journal_code=journal_code, entry_date=entry_date,
            label=label, lines=lines, reference=(reference or "").strip() or None,
        )
        if isinstance(inserted, Err):
            return inserted
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="journal_entry.created",
            entity_type="journal_entry",
            entity_id=inserted.value,
            payload={"journal_code": journal_code, "entry_date": entry_date.isoformat(), "label": label.strip(), "lines": len(lines)},
        )
        return Ok(self._query.get_entry(tenant_id=tenant_id, entry_id=inserted.value))

    def _draft(self, tenant_id: str, entry_id: str) -> Result[tuple]:
        row = self._connection.execute(
            """
            SELECT journal_code, entry_date, label, reference, status, number
            FROM finance.journal_entries WHERE id = %s AND tenant_id = %s FOR UPDATE
            """,
            (entry_id, tenant_id),
        ).fetchone()
        if row is None:
            return entry_not_found(entry_id)
        status, number = row[4], row[5]
        if status != "draft":
            return Err(
                "ENTRY_POSTED",
                f"entry {number} is {status}; a posted entry is never edited or deleted, reverse it instead",
                f"l'écriture {number} est {STATUS_FR[status]} ; une écriture comptabilisée ne se modifie ni ne se supprime, extournez-la",
            )
        return Ok(row)

    def update_draft(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        entry_id: str,
        journal_code: str | None = None,
        entry_date: datetime.date | None = None,
        label: str | None = None,
        reference: str | None = None,
        lines: list[EntryLine] | None = None,
    ) -> Result[dict]:
        """`None` leaves a field unchanged; `reference=""` clears it; `lines` replaces every line."""
        current = self._draft(tenant_id, entry_id)
        if isinstance(current, Err):
            return current
        current_journal, current_date, current_label, current_reference, _, _ = current.value
        new_journal = journal_code or current_journal
        new_date = entry_date or current_date
        new_label = current_label if label is None else label
        new_reference = current_reference if reference is None else (reference.strip() or None)
        new_lines = lines if lines is not None else self._posting.lines_of(entry_id)
        checked = self._posting.check_draft(
            tenant_id=tenant_id, journal_code=new_journal, entry_date=new_date, label=new_label, lines=new_lines
        )
        if isinstance(checked, Err):
            return checked
        self._connection.execute(
            """
            UPDATE finance.journal_entries
            SET journal_code = %s, entry_date = %s, period = %s, label = %s, reference = %s
            WHERE id = %s
            """,
            (new_journal, new_date, new_date.replace(day=1), new_label.strip(), new_reference, entry_id),
        )
        if lines is not None:
            self._posting.replace_lines(tenant_id=tenant_id, entry_id=entry_id, lines=checked.value)
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="journal_entry.updated",
            entity_type="journal_entry",
            entity_id=entry_id,
            payload={
                "journal_code": new_journal,
                "entry_date": new_date.isoformat(),
                "label": new_label.strip(),
                "reference": new_reference,
                "lines_replaced": lines is not None,
            },
        )
        return Ok(self._query.get_entry(tenant_id=tenant_id, entry_id=entry_id))

    def delete_draft(self, *, tenant_id: str, actor_id: str, entry_id: str) -> Result[dict]:
        current = self._draft(tenant_id, entry_id)
        if isinstance(current, Err):
            return current
        journal_code, entry_date, label, reference, status, _ = current.value
        self._connection.execute("DELETE FROM finance.journal_entries WHERE id = %s", (entry_id,))
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="journal_entry.deleted",
            entity_type="journal_entry",
            entity_id=entry_id,
            payload={
                "journal_code": journal_code,
                "entry_date": entry_date.isoformat(),
                "label": label,
                "reference": reference,
                "status": status,
            },
        )
        return Ok({"id": entry_id})

    def post(self, *, tenant_id: str, actor_id: str, entry_id: str, correlation_id: str) -> Result[dict]:
        return self._posting.post_draft(
            tenant_id=tenant_id, actor_id=actor_id, entry_id=entry_id, correlation_id=correlation_id
        )

    def reverse(
        self, *, tenant_id: str, actor_id: str, entry_id: str, entry_date: datetime.date, correlation_id: str
    ) -> Result[dict]:
        return self._posting.reverse_entry(
            tenant_id=tenant_id, actor_id=actor_id, entry_id=entry_id, entry_date=entry_date, correlation_id=correlation_id
        )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest modules/finance core/test_error_translations.py -q -rs`
Expected: all PASS, no skipped integration test.

- [ ] **Step 6: Commit**

```bash
git add backend/modules/finance/api/ledger_query_service.py backend/modules/finance/api/manual_entry_service.py backend/modules/finance/api/test_manual_entries_integration.py
git commit -m "feat(finance): manual OD entries from draft to posted, and ledger queries by source

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Reports — trial balance, general ledger, 42x/43x/44x balances

**Files:**
- Create: `backend/modules/finance/api/ledger_report_service.py`
- Test: `backend/modules/finance/api/test_ledger_reports_integration.py`

**Interfaces:**
- Consumes: Task 1 (`ZERO`, `split_balance`), Task 7 (`account_service.ACCOUNT_KEYS`), Task 4 / Task 8 services to book test data.
- Produces: `LedgerReportService(connection)`:
  - `trial_balance(*, tenant_id, date_from, date_to) -> dict` → `{"rows": [{account_code, account_name, class_no, opening_debit, opening_credit, period_debit, period_credit, closing_debit, closing_credit}], "totals": {the six amounts}}` — opening = everything booked before `date_from`.
  - `general_ledger(*, tenant_id, account_code, date_from, date_to) -> Result[dict]` → `{account: {code, name, class_no, account_type, is_postable, parent_code}, opening_balance, lines: [{entry_id, number, journal_code, entry_date, label, reference, debit, credit, balance}], total_debit, total_credit, closing_balance}` (balances signed debit − credit; `NOT_FOUND`).
  - `account_balances(*, tenant_id, prefixes: list[str], as_of) -> list[dict]` → `[{account_code, account_name, debit, credit, owed}]` for postable accounts, `owed = credit − debit`.
  - "Booked" = status `posted` or `reversed`; drafts never count.

- [ ] **Step 1: Write the failing test**

`backend/modules/finance/api/test_ledger_reports_integration.py`:

```python
"""Trial balance, general ledger and the 42x/43x/44x balances over booked entries."""
from __future__ import annotations

import datetime
from decimal import Decimal

from ulid import ULID

from core.domain.result import Err, Ok
from modules.finance.api.ledger_posting_service import LedgerPostingService
from modules.finance.api.ledger_report_service import LedgerReportService
from modules.finance.api.manual_entry_service import ManualEntryService
from modules.finance.domain.ledger import EntryLine

D = Decimal
FEB_FROM, FEB_TO = datetime.date(2030, 2, 1), datetime.date(2030, 2, 28)


def _post(ledger, day: datetime.date, label: str, lines: list[EntryLine]) -> dict:
    result = LedgerPostingService(ledger["db"]).post_entry(
        tenant_id=ledger["tenant"], actor_id=ledger["actor"], journal_code="OD", entry_date=day,
        label=label, lines=lines, correlation_id=str(ULID()),
    )
    assert isinstance(result, Ok), result
    return result.value


def _book(ledger) -> None:
    """January: capital paid in. February: a payroll (661 against 422 and 431) and its payment,
    plus a draft that no report may count."""
    _post(ledger, datetime.date(2030, 1, 10), "Apport en capital",
          [EntryLine("521", debit=D(1000000)), EntryLine("101", credit=D(1000000))])
    _post(ledger, FEB_TO, "Paie 02/2030",
          [EntryLine("661", debit=D(320000)), EntryLine("422", credit=D(300000)), EntryLine("431", credit=D(20000))])
    _post(ledger, FEB_TO, "Virement des salaires",
          [EntryLine("422", debit=D(300000)), EntryLine("521", credit=D(300000))])
    ManualEntryService(ledger["db"]).create_draft(
        tenant_id=ledger["tenant"], actor_id=ledger["actor"], journal_code="OD", entry_date=datetime.date(2030, 2, 20),
        label="Brouillon ignoré", lines=[EntryLine("661", debit=D(5)), EntryLine("521", credit=D(5))],
    )


def test_the_trial_balance_splits_opening_period_and_closing(ledger):
    _book(ledger)
    report = LedgerReportService(ledger["db"]).trial_balance(tenant_id=ledger["tenant"], date_from=FEB_FROM, date_to=FEB_TO)
    rows = {row["account_code"]: row for row in report["rows"]}
    assert set(rows) == {"101", "422", "431", "521", "661"}
    assert (rows["101"]["opening_credit"], rows["101"]["closing_credit"]) == (D(1000000), D(1000000))
    assert (rows["521"]["opening_debit"], rows["521"]["period_credit"], rows["521"]["closing_debit"]) == (
        D(1000000), D(300000), D(700000),
    )
    assert (
        rows["422"]["period_debit"], rows["422"]["period_credit"], rows["422"]["closing_debit"], rows["422"]["closing_credit"]
    ) == (D(300000), D(300000), D(0), D(0))
    assert rows["431"]["closing_credit"] == D(20000)
    assert rows["661"]["closing_debit"] == D(320000)
    totals = report["totals"]
    assert totals["opening_debit"] == totals["opening_credit"] == D(1000000)
    assert totals["period_debit"] == totals["period_credit"] == D(620000)
    assert totals["closing_debit"] == totals["closing_credit"] == D(1020000)


def test_a_reversed_pair_nets_to_zero_but_stays_visible(ledger):
    _book(ledger)
    posted = _post(ledger, datetime.date(2030, 2, 10), "Erreur de saisie",
                   [EntryLine("661", debit=D(7000)), EntryLine("571", credit=D(7000))])
    LedgerPostingService(ledger["db"]).reverse_entry(
        tenant_id=ledger["tenant"], actor_id=ledger["actor"], entry_id=posted["id"],
        entry_date=datetime.date(2030, 2, 11), correlation_id=str(ULID()),
    )
    report = LedgerReportService(ledger["db"]).trial_balance(tenant_id=ledger["tenant"], date_from=FEB_FROM, date_to=FEB_TO)
    rows = {row["account_code"]: row for row in report["rows"]}
    assert (
        rows["571"]["period_debit"], rows["571"]["period_credit"], rows["571"]["closing_debit"], rows["571"]["closing_credit"]
    ) == (D(7000), D(7000), D(0), D(0))
    assert rows["661"]["closing_debit"] == D(320000)


def test_the_general_ledger_runs_a_balance_from_the_opening(ledger):
    _book(ledger)
    reports = LedgerReportService(ledger["db"])
    result = reports.general_ledger(tenant_id=ledger["tenant"], account_code="521", date_from=FEB_FROM, date_to=FEB_TO)
    assert isinstance(result, Ok), result
    view = result.value
    assert view["account"]["name"] == "Banques locales"
    assert view["opening_balance"] == D(1000000)
    assert [(line["label"], line["credit"], line["balance"]) for line in view["lines"]] == [
        ("Virement des salaires", D(300000), D(700000)),
    ]
    assert (view["total_debit"], view["total_credit"], view["closing_balance"]) == (D(0), D(300000), D(700000))
    missing = reports.general_ledger(tenant_id=ledger["tenant"], account_code="999", date_from=FEB_FROM, date_to=FEB_TO)
    assert isinstance(missing, Err) and missing.code == "NOT_FOUND"


def test_balances_show_what_is_owed_to_staff_social_bodies_and_the_state(ledger):
    _book(ledger)
    reports = LedgerReportService(ledger["db"])
    balances = reports.account_balances(tenant_id=ledger["tenant"], prefixes=["42", "43", "44"], as_of=FEB_TO)
    owed = {row["account_code"]: row["owed"] for row in balances}
    assert owed["422"] == D(0) and owed["431"] == D(20000) and owed["447"] == D(0)
    assert set(owed) >= {"421", "422", "431", "433", "441", "442", "443", "444", "445", "446", "447"}
    assert "42" not in owed  # headings are not listed
    january = reports.account_balances(tenant_id=ledger["tenant"], prefixes=["43"], as_of=datetime.date(2030, 1, 31))
    assert [row["owed"] for row in january] == [D(0), D(0)]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python -m pytest modules/finance/api/test_ledger_reports_integration.py -q`
Expected: collection error `No module named 'modules.finance.api.ledger_report_service'`.

- [ ] **Step 3: Write the report service**

`backend/modules/finance/api/ledger_report_service.py`:

```python
"""Reports over booked entries: trial balance, general ledger of one account, and the balances of
a group of accounts (42x staff, 43x social bodies, 44x the State: what the company owes them).

Booked = posted or reversed. A reversal is itself a posted entry, so a reversed pair nets to zero
while both stay visible; drafts never count."""
from __future__ import annotations

import datetime

import psycopg

from core.domain.result import Err, Ok, Result
from modules.finance.api.account_service import ACCOUNT_KEYS
from modules.finance.domain.ledger import ZERO, split_balance

BOOKED = ["posted", "reversed"]
TRIAL_BALANCE_AMOUNTS = (
    "opening_debit", "opening_credit", "period_debit", "period_credit", "closing_debit", "closing_credit",
)


class LedgerReportService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def trial_balance(self, *, tenant_id: str, date_from: datetime.date, date_to: datetime.date) -> dict:
        rows = self._connection.execute(
            """
            SELECT a.code, a.name, a.class_no,
                   COALESCE(SUM(l.debit) FILTER (WHERE e.entry_date < %(date_from)s), 0),
                   COALESCE(SUM(l.credit) FILTER (WHERE e.entry_date < %(date_from)s), 0),
                   COALESCE(SUM(l.debit) FILTER (WHERE e.entry_date >= %(date_from)s), 0),
                   COALESCE(SUM(l.credit) FILTER (WHERE e.entry_date >= %(date_from)s), 0)
            FROM finance.journal_lines l
            JOIN finance.journal_entries e ON e.id = l.entry_id
            JOIN finance.accounts a ON a.tenant_id = l.tenant_id AND a.code = l.account_code
            WHERE l.tenant_id = %(tenant_id)s AND e.status = ANY(%(booked)s) AND e.entry_date <= %(date_to)s
            GROUP BY a.code, a.name, a.class_no
            ORDER BY a.code
            """,
            {"tenant_id": tenant_id, "date_from": date_from, "date_to": date_to, "booked": BOOKED},
        ).fetchall()
        report_rows: list[dict] = []
        totals = {key: ZERO for key in TRIAL_BALANCE_AMOUNTS}
        for code, name, class_no, before_debit, before_credit, period_debit, period_credit in rows:
            opening = before_debit - before_credit
            opening_debit, opening_credit = split_balance(opening)
            closing_debit, closing_credit = split_balance(opening + period_debit - period_credit)
            row = {
                "account_code": code,
                "account_name": name,
                "class_no": class_no,
                "opening_debit": opening_debit,
                "opening_credit": opening_credit,
                "period_debit": period_debit,
                "period_credit": period_credit,
                "closing_debit": closing_debit,
                "closing_credit": closing_credit,
            }
            for key in TRIAL_BALANCE_AMOUNTS:
                totals[key] += row[key]
            report_rows.append(row)
        return {"rows": report_rows, "totals": totals}

    def general_ledger(
        self, *, tenant_id: str, account_code: str, date_from: datetime.date, date_to: datetime.date
    ) -> Result[dict]:
        account = self._connection.execute(
            """
            SELECT code, name, class_no, account_type, is_postable, parent_code
            FROM finance.accounts WHERE tenant_id = %s AND code = %s
            """,
            (tenant_id, account_code),
        ).fetchone()
        if account is None:
            return Err("NOT_FOUND", f"account {account_code} not found", f"compte {account_code} introuvable")
        opening = self._connection.execute(
            """
            SELECT COALESCE(SUM(l.debit - l.credit), 0)
            FROM finance.journal_lines l
            JOIN finance.journal_entries e ON e.id = l.entry_id
            WHERE l.tenant_id = %s AND l.account_code = %s AND e.status = ANY(%s) AND e.entry_date < %s
            """,
            (tenant_id, account_code, BOOKED, date_from),
        ).fetchone()[0]
        rows = self._connection.execute(
            """
            SELECT e.id, e.number, e.journal_code, e.entry_date, COALESCE(l.label, e.label), e.reference, l.debit, l.credit
            FROM finance.journal_lines l
            JOIN finance.journal_entries e ON e.id = l.entry_id
            WHERE l.tenant_id = %s AND l.account_code = %s AND e.status = ANY(%s)
              AND e.entry_date BETWEEN %s AND %s
            ORDER BY e.entry_date, e.number, l.line_no
            """,
            (tenant_id, account_code, BOOKED, date_from, date_to),
        ).fetchall()
        balance = opening
        total_debit = total_credit = ZERO
        lines: list[dict] = []
        for entry_id, number, journal_code, entry_date, label, reference, debit, credit in rows:
            balance += debit - credit
            total_debit += debit
            total_credit += credit
            lines.append(
                {
                    "entry_id": entry_id,
                    "number": number,
                    "journal_code": journal_code,
                    "entry_date": entry_date,
                    "label": label,
                    "reference": reference,
                    "debit": debit,
                    "credit": credit,
                    "balance": balance,
                }
            )
        return Ok(
            {
                "account": dict(zip(ACCOUNT_KEYS, account)),
                "opening_balance": opening,
                "lines": lines,
                "total_debit": total_debit,
                "total_credit": total_credit,
                "closing_balance": balance,
            }
        )

    def account_balances(self, *, tenant_id: str, prefixes: list[str], as_of: datetime.date) -> list[dict]:
        """Postable accounts whose number starts with one of `prefixes`, as booked on `as_of`.
        `owed` is credit minus debit: what the company owes on a liability account."""
        patterns = [f"{prefix}%" for prefix in prefixes if prefix.isdigit()]
        if not patterns:
            return []
        rows = self._connection.execute(
            """
            SELECT a.code, a.name, COALESCE(SUM(m.debit), 0), COALESCE(SUM(m.credit), 0)
            FROM finance.accounts a
            LEFT JOIN (
                SELECT l.account_code, l.debit, l.credit
                FROM finance.journal_lines l
                JOIN finance.journal_entries e ON e.id = l.entry_id
                WHERE l.tenant_id = %s AND e.status = ANY(%s) AND e.entry_date <= %s
            ) m ON m.account_code = a.code
            WHERE a.tenant_id = %s AND a.is_postable AND a.code LIKE ANY(%s)
            GROUP BY a.code, a.name
            ORDER BY a.code
            """,
            (tenant_id, BOOKED, as_of, tenant_id, patterns),
        ).fetchall()
        return [
            {"account_code": code, "account_name": name, "debit": debit, "credit": credit, "owed": credit - debit}
            for code, name, debit, credit in rows
        ]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest modules/finance -q -rs`
Expected: all PASS, no skipped integration test.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/finance/api/ledger_report_service.py backend/modules/finance/api/test_ledger_reports_integration.py
git commit -m "feat(finance): trial balance, general ledger and 42x/43x/44x balances

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Ledger HTTP routes

**Files:**
- Create: `backend/modules/finance/api/ledger_router.py`
- Modify: `backend/app/main.py` (import + `include_router`)
- Test: `backend/modules/finance/api/test_ledger_router_integration.py`

**Interfaces:**
- Consumes: every service of Tasks 3–9; `core.tenancy.require_permission`, `require_session`, `user_has_permission`; `core.domain.result.err_detail`.
- Produces (all JSON, money as integers, dates ISO; errors `{"detail": {"code", "message", "message_fr"}}` with 404 for `NOT_FOUND`, 409 for `PERIOD_CLOSED`, `ENTRY_POSTED`, `INVALID_TRANSITION`, `FISCAL_YEAR_EXISTS`, `ACCOUNT_EXISTS`, `POSTING_RULE_EXISTS`, `RUN_NOT_POSTED`, `INVOICE_NOT_POSTED`, 400 otherwise):

| Method + path | Permission | Body / query → response |
|---|---|---|
| `POST /finance/setup` | `finance.admin_accounts` | → `{accounts, journals, posting_rules}` counts |
| `GET /finance/accounts` | `finance.view_ledger` | → account list |
| `POST /finance/accounts` (201) | `finance.manage_accounts` | `{code, name, account_type, is_postable?, parent_code?}` → account |
| `PATCH /finance/accounts/{code}` | `finance.admin_accounts` | `{name?, account_type?, is_postable?, parent_code?}` (`""` removes parent) → account |
| `GET /finance/journals` | `finance.view_ledger` | → `[{code, name, journal_type}]` |
| `GET /finance/periods?year=` | `finance.view_ledger` | → `[{period, year, status, closed_by, closed_at}]` |
| `POST /finance/fiscal-years` (201) | `finance.admin_periods` | `{year}` → `{id, year, start_date, end_date}` |
| `POST /finance/periods/{period}/close` · `/reopen` | `finance.admin_periods` | → period |
| `GET /finance/posting-rules` | `finance.view_ledger` | → rule list |
| `POST /finance/posting-rules` (201) | `finance.manage_posting_rules` | `{source, source_kind, code, debit_account_code?, credit_account_code?, journal_code?}` → rule |
| `PATCH /finance/posting-rules/{id}` | `finance.manage_posting_rules` | `{debit_account_code?, credit_account_code?, journal_code?}` (`""` clears) → rule |
| `POST /finance/posting-rules/{id}/confirm` | `finance.manage_posting_rules` | → rule |
| `GET /finance/entries?date_from&date_to&journal_code&status` | `finance.view_ledger` | → entry list |
| `GET /finance/entries/{id}` | `finance.view_ledger` | → entry with `lines` |
| `POST /finance/entries` (201) | `finance.manage_entries` | `{journal_code="OD", entry_date, label, reference?, lines: [{account_code, debit, credit, label?, partner_id?}]}` → entry with lines |
| `PATCH /finance/entries/{id}` | `finance.admin_entries` | same fields, all optional → entry (drafts only) |
| `DELETE /finance/entries/{id}` | `finance.manage_entries` | → `{id}` (drafts only) |
| `POST /finance/entries/{id}/post` | `finance.manage_entries` | `{correlation_id?}` → entry |
| `POST /finance/entries/{id}/reverse` | `finance.admin_entries` | `{entry_date, correlation_id?}` → reversal entry |
| `GET /finance/posting-failures?status=open\|resolved\|cancelled\|all` | `finance.view_ledger` | → failure list |
| `POST /finance/posting-failures/{id}/retry` | `finance.manage_entries` | → `{entries: [...]}` |
| `GET /finance/ledger/sources/{source_module}/{source_id}` | `finance.view_ledger` **or** `payroll.view_runs` | → `{entries, failures}` |
| `GET /finance/reports/trial-balance?date_from&date_to` | `finance.view_ledger` | → `{rows, totals}` |
| `GET /finance/reports/general-ledger?account_code&date_from&date_to` | `finance.view_ledger` | → general ledger |
| `GET /finance/reports/balances?as_of&prefixes=42,43,44` | `finance.view_ledger` | → balance list |

- [ ] **Step 1: Write the failing test**

`backend/modules/finance/api/test_ledger_router_integration.py`:

```python
"""The ledger over HTTP: who may do what, status codes, and JSON shapes (money as integers).

A throwaway FastAPI app carries just the ledger router; its connection is the fixture's
rolled-back one wrapped in NoCommitConnection."""
from __future__ import annotations

import pytest
from fastapi import FastAPI

pytest.importorskip("httpx", reason="the FastAPI test client needs httpx (requirements-dev.txt)")
from fastapi.testclient import TestClient  # noqa: E402

from core.tenancy import TenantContext, require_session  # noqa: E402
from modules.finance.api import ledger_router as router_module  # noqa: E402
from modules.finance.testing_support import NoCommitConnection  # noqa: E402

PATENTE = {
    "entry_date": "2030-02-14",
    "label": "Patente 2030",
    "lines": [{"account_code": "641", "debit": 150000}, {"account_code": "521", "credit": 150000}],
}


@pytest.fixture
def api(ledger, monkeypatch) -> dict:
    wrapped = NoCommitConnection(ledger["db"])
    monkeypatch.setattr(router_module, "get_connection", lambda: wrapped)
    monkeypatch.setattr("core.tenancy.get_connection", lambda: wrapped)
    app = FastAPI()
    app.include_router(router_module.router)
    app.dependency_overrides[require_session] = lambda: TenantContext(
        tenant_id=ledger["tenant"], user_id=ledger["actor"], session_token="t"
    )

    def grant(*permissions: str) -> None:
        for permission in permissions:
            ledger["db"].execute(
                "INSERT INTO core.user_permissions (user_id, permission) VALUES (%s, %s)", (ledger["actor"], permission)
            )

    return {"client": TestClient(app), "grant": grant}


def test_reading_the_ledger_needs_view_ledger(api):
    assert api["client"].get("/finance/accounts").status_code == 403
    api["grant"]("finance.view_ledger")
    response = api["client"].get("/finance/accounts")
    assert response.status_code == 200
    assert {
        "code": "422", "name": "Personnel, rémunérations dues", "class_no": 4,
        "account_type": "liability", "is_postable": True, "parent_code": "42",
    } in response.json()


def test_editing_an_account_needs_admin_accounts(api):
    api["grant"]("finance.manage_accounts")
    created = api["client"].post(
        "/finance/accounts", json={"code": "5211", "name": "BDM-SA", "account_type": "asset", "parent_code": "52"}
    )
    assert created.status_code == 201, created.text
    assert api["client"].patch("/finance/accounts/5211", json={"name": "BDM"}).status_code == 403
    api["grant"]("finance.admin_accounts")
    assert api["client"].patch("/finance/accounts/5211", json={"name": "BDM"}).json()["name"] == "BDM"


def test_a_manual_entry_goes_from_draft_to_posted_and_then_stays_frozen(api):
    api["grant"]("finance.view_ledger", "finance.manage_entries")
    created = api["client"].post("/finance/entries", json=PATENTE)
    assert created.status_code == 201, created.text
    entry = created.json()
    assert entry["journal_code"] == "OD" and entry["status"] == "draft"
    assert entry["total_debit"] == 150000 and entry["lines"][0]["account_name"] == "Impôts et taxes directs"
    posted = api["client"].post(f"/finance/entries/{entry['id']}/post", json={})
    assert posted.status_code == 200, posted.text
    assert posted.json()["number"] == "OD-2030-000001"
    api["grant"]("finance.admin_entries")
    refused = api["client"].patch(f"/finance/entries/{entry['id']}", json={"label": "x"})
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "ENTRY_POSTED" and refused.json()["detail"]["message_fr"]
    listed = api["client"].get(
        "/finance/entries", params={"date_from": "2030-02-01", "date_to": "2030-02-28", "journal_code": "OD"}
    )
    assert [row["number"] for row in listed.json()] == ["OD-2030-000001"]


def test_posting_into_a_closed_period_is_a_409_in_both_languages(api):
    api["grant"]("finance.manage_entries", "finance.admin_periods")
    closed = api["client"].post("/finance/periods/2030-02-01/close")
    assert closed.status_code == 200 and closed.json()["status"] == "closed"
    refused = api["client"].post("/finance/entries", json=PATENTE)
    assert refused.status_code == 409
    detail = refused.json()["detail"]
    assert detail["code"] == "PERIOD_CLOSED" and "clôturée" in detail["message_fr"]


def test_the_run_page_reads_postings_with_payroll_view_runs_alone(api):
    assert api["client"].get("/finance/ledger/sources/payroll/RUN-X").status_code == 403
    api["grant"]("payroll.view_runs")
    response = api["client"].get("/finance/ledger/sources/payroll/RUN-X")
    assert response.status_code == 200
    assert response.json() == {"entries": [], "failures": []}


def test_reports_return_whole_francs_and_refuse_a_backwards_range(api):
    api["grant"]("finance.view_ledger", "finance.manage_entries")
    entry = api["client"].post("/finance/entries", json=PATENTE).json()
    api["client"].post(f"/finance/entries/{entry['id']}/post", json={})
    trial = api["client"].get("/finance/reports/trial-balance", params={"date_from": "2030-02-01", "date_to": "2030-02-28"})
    totals = trial.json()["totals"]
    assert totals["period_debit"] == 150000 and isinstance(totals["period_debit"], int)
    general = api["client"].get(
        "/finance/reports/general-ledger", params={"account_code": "521", "date_from": "2030-02-01", "date_to": "2030-02-28"}
    )
    assert general.json()["closing_balance"] == -150000
    balances = api["client"].get("/finance/reports/balances", params={"as_of": "2030-02-28"}).json()
    assert {row["account_code"] for row in balances} >= {"421", "422", "431", "433", "447"}
    backwards = api["client"].get("/finance/reports/trial-balance", params={"date_from": "2030-03-01", "date_to": "2030-02-01"})
    assert backwards.status_code == 400 and backwards.json()["detail"]["message_fr"]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python -m pytest modules/finance/api/test_ledger_router_integration.py -q`
Expected: collection error `cannot import name 'ledger_router' from 'modules.finance.api'`.

- [ ] **Step 3: Write the router**

`backend/modules/finance/api/ledger_router.py`:

```python
"""HTTP routes of the SYSCOHADA ledger under /finance. Invoices keep their own router."""
from __future__ import annotations

import datetime
from decimal import Decimal
from typing import NoReturn

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from ulid import ULID

from core.db import get_connection
from core.domain.result import Err, err_detail
from core.tenancy import TenantContext, require_permission, require_session, user_has_permission
from modules.finance.api.account_service import AccountService
from modules.finance.api.chart_setup_service import ChartSetupService
from modules.finance.api.ledger_event_postings import retry_failure
from modules.finance.api.ledger_posting_service import entry_not_found
from modules.finance.api.ledger_query_service import LedgerQueryService
from modules.finance.api.ledger_report_service import LedgerReportService
from modules.finance.api.manual_entry_service import ManualEntryService
from modules.finance.api.period_service import PeriodService
from modules.finance.api.posting_failure_service import PostingFailureService
from modules.finance.api.posting_rule_service import PostingRuleService
from modules.finance.domain.ledger import EntryLine

router = APIRouter(prefix="/finance", tags=["finance.ledger"])

CONFLICT_CODES = {
    "PERIOD_CLOSED", "ENTRY_POSTED", "INVALID_TRANSITION", "FISCAL_YEAR_EXISTS", "ACCOUNT_EXISTS",
    "POSTING_RULE_EXISTS", "RUN_NOT_POSTED", "INVOICE_NOT_POSTED",
}


def jsonable(value):
    """Whole francs as JSON integers, dates as ISO strings, recursively."""
    if isinstance(value, Decimal):
        return int(value)
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    return value


def _refuse(connection, err: Err) -> NoReturn:
    connection.rollback()
    if err.code == "NOT_FOUND":
        code = status.HTTP_404_NOT_FOUND
    elif err.code in CONFLICT_CODES:
        code = status.HTTP_409_CONFLICT
    else:
        code = status.HTTP_400_BAD_REQUEST
    raise HTTPException(code, err_detail(err))


def _check_range(date_from: datetime.date, date_to: datetime.date) -> None:
    if date_from > date_to:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            err_detail(
                Err(
                    "INVALID_PERIOD",
                    f"the range starts ({date_from}) after it ends ({date_to})",
                    f"la plage commence ({date_from}) après sa fin ({date_to})",
                )
            ),
        )


def require_any_permission(*permissions: str):
    """Like require_permission, satisfied by any one of `permissions`."""

    def dependency(tenant: TenantContext = Depends(require_session)) -> TenantContext:
        with get_connection() as connection:
            allowed = any(
                user_has_permission(connection, user_id=tenant.user_id, permission=permission) for permission in permissions
            )
        if not allowed:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                {
                    "code": "FORBIDDEN",
                    "message": f"missing permission: one of {', '.join(permissions)}",
                    "message_fr": f"permission manquante : l'une de {', '.join(permissions)}",
                },
            )
        return tenant

    return dependency


class AccountIn(BaseModel):
    code: str
    name: str
    account_type: str
    is_postable: bool = True
    parent_code: str | None = None


class AccountPatch(BaseModel):
    name: str | None = None
    account_type: str | None = None
    is_postable: bool | None = None
    parent_code: str | None = None  # "" removes the parent


class FiscalYearIn(BaseModel):
    year: int


class RuleIn(BaseModel):
    source: str
    source_kind: str
    code: str
    debit_account_code: str | None = None
    credit_account_code: str | None = None
    journal_code: str | None = None


class RulePatch(BaseModel):
    debit_account_code: str | None = None  # "" clears the side
    credit_account_code: str | None = None
    journal_code: str | None = None


class LineIn(BaseModel):
    account_code: str
    debit: int = Field(default=0, ge=0)
    credit: int = Field(default=0, ge=0)
    label: str | None = None
    partner_id: str | None = None

    def to_line(self) -> EntryLine:
        return EntryLine(
            account_code=self.account_code.strip(),
            debit=Decimal(self.debit),
            credit=Decimal(self.credit),
            label=(self.label or "").strip() or None,
            partner_id=self.partner_id or None,
        )


class EntryIn(BaseModel):
    journal_code: str = "OD"
    entry_date: datetime.date
    label: str
    reference: str | None = None
    lines: list[LineIn]


class EntryPatch(BaseModel):
    journal_code: str | None = None
    entry_date: datetime.date | None = None
    label: str | None = None
    reference: str | None = None
    lines: list[LineIn] | None = None


class PostIn(BaseModel):
    correlation_id: str | None = None


class ReverseIn(BaseModel):
    entry_date: datetime.date
    correlation_id: str | None = None


# Setup and chart of accounts.


@router.post("/setup")
def setup_ledger(tenant: TenantContext = Depends(require_permission("finance.admin_accounts"))) -> dict:
    with get_connection() as connection:
        counts = ChartSetupService(connection).ensure_defaults(tenant_id=tenant.tenant_id, actor_id=tenant.user_id)
        connection.commit()
    return counts


@router.get("/accounts")
def list_accounts(tenant: TenantContext = Depends(require_permission("finance.view_ledger"))) -> list[dict]:
    with get_connection() as connection:
        return jsonable(AccountService(connection).list_accounts(tenant_id=tenant.tenant_id))


@router.post("/accounts", status_code=status.HTTP_201_CREATED)
def create_account(body: AccountIn, tenant: TenantContext = Depends(require_permission("finance.manage_accounts"))) -> dict:
    with get_connection() as connection:
        result = AccountService(connection).create_account(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, code=body.code, name=body.name,
            account_type=body.account_type, is_postable=body.is_postable, parent_code=body.parent_code,
        )
        if isinstance(result, Err):
            _refuse(connection, result)
        connection.commit()
    return jsonable(result.value)


@router.patch("/accounts/{code}")
def update_account(
    code: str, body: AccountPatch, tenant: TenantContext = Depends(require_permission("finance.admin_accounts"))
) -> dict:
    with get_connection() as connection:
        result = AccountService(connection).update_account(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, code=code, name=body.name,
            account_type=body.account_type, is_postable=body.is_postable, parent_code=body.parent_code,
        )
        if isinstance(result, Err):
            _refuse(connection, result)
        connection.commit()
    return jsonable(result.value)


@router.get("/journals")
def list_journals(tenant: TenantContext = Depends(require_permission("finance.view_ledger"))) -> list[dict]:
    with get_connection() as connection:
        return jsonable(AccountService(connection).list_journals(tenant_id=tenant.tenant_id))


# Fiscal years and periods.


@router.get("/periods")
def list_periods(
    year: int | None = None, tenant: TenantContext = Depends(require_permission("finance.view_ledger"))
) -> list[dict]:
    with get_connection() as connection:
        return jsonable(PeriodService(connection).list_periods(tenant_id=tenant.tenant_id, year=year))


@router.post("/fiscal-years", status_code=status.HTTP_201_CREATED)
def open_fiscal_year(body: FiscalYearIn, tenant: TenantContext = Depends(require_permission("finance.admin_periods"))) -> dict:
    with get_connection() as connection:
        result = PeriodService(connection).open_fiscal_year(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, year=body.year)
        if isinstance(result, Err):
            _refuse(connection, result)
        connection.commit()
    return jsonable(result.value)


@router.post("/periods/{period}/close")
def close_period(period: datetime.date, tenant: TenantContext = Depends(require_permission("finance.admin_periods"))) -> dict:
    with get_connection() as connection:
        result = PeriodService(connection).close_period(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, period=period)
        if isinstance(result, Err):
            _refuse(connection, result)
        connection.commit()
    return jsonable(result.value)


@router.post("/periods/{period}/reopen")
def reopen_period(period: datetime.date, tenant: TenantContext = Depends(require_permission("finance.admin_periods"))) -> dict:
    with get_connection() as connection:
        result = PeriodService(connection).reopen_period(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, period=period)
        if isinstance(result, Err):
            _refuse(connection, result)
        connection.commit()
    return jsonable(result.value)


# Posting rules.


@router.get("/posting-rules")
def list_posting_rules(tenant: TenantContext = Depends(require_permission("finance.view_ledger"))) -> list[dict]:
    with get_connection() as connection:
        return jsonable(PostingRuleService(connection).list_rules(tenant_id=tenant.tenant_id))


@router.post("/posting-rules", status_code=status.HTTP_201_CREATED)
def create_posting_rule(
    body: RuleIn, tenant: TenantContext = Depends(require_permission("finance.manage_posting_rules"))
) -> dict:
    with get_connection() as connection:
        result = PostingRuleService(connection).create_rule(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, source=body.source, source_kind=body.source_kind,
            code=body.code, debit_account_code=body.debit_account_code, credit_account_code=body.credit_account_code,
            journal_code=body.journal_code,
        )
        if isinstance(result, Err):
            _refuse(connection, result)
        connection.commit()
    return jsonable(result.value)


@router.patch("/posting-rules/{rule_id}")
def update_posting_rule(
    rule_id: str, body: RulePatch, tenant: TenantContext = Depends(require_permission("finance.manage_posting_rules"))
) -> dict:
    with get_connection() as connection:
        result = PostingRuleService(connection).update_rule(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, rule_id=rule_id,
            debit_account_code=body.debit_account_code, credit_account_code=body.credit_account_code,
            journal_code=body.journal_code,
        )
        if isinstance(result, Err):
            _refuse(connection, result)
        connection.commit()
    return jsonable(result.value)


@router.post("/posting-rules/{rule_id}/confirm")
def confirm_posting_rule(
    rule_id: str, tenant: TenantContext = Depends(require_permission("finance.manage_posting_rules"))
) -> dict:
    with get_connection() as connection:
        result = PostingRuleService(connection).confirm_rule(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, rule_id=rule_id)
        if isinstance(result, Err):
            _refuse(connection, result)
        connection.commit()
    return jsonable(result.value)


# Entries.


@router.get("/entries")
def list_entries(
    date_from: datetime.date,
    date_to: datetime.date,
    journal_code: str | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    tenant: TenantContext = Depends(require_permission("finance.view_ledger")),
) -> list[dict]:
    _check_range(date_from, date_to)
    with get_connection() as connection:
        return jsonable(
            LedgerQueryService(connection).list_entries(
                tenant_id=tenant.tenant_id, date_from=date_from, date_to=date_to,
                journal_code=journal_code, status=status_filter,
            )
        )


@router.get("/entries/{entry_id}")
def get_entry(entry_id: str, tenant: TenantContext = Depends(require_permission("finance.view_ledger"))) -> dict:
    with get_connection() as connection:
        entry = LedgerQueryService(connection).get_entry(tenant_id=tenant.tenant_id, entry_id=entry_id)
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, err_detail(entry_not_found(entry_id)))
    return jsonable(entry)


@router.post("/entries", status_code=status.HTTP_201_CREATED)
def create_entry(body: EntryIn, tenant: TenantContext = Depends(require_permission("finance.manage_entries"))) -> dict:
    with get_connection() as connection:
        result = ManualEntryService(connection).create_draft(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, journal_code=body.journal_code,
            entry_date=body.entry_date, label=body.label, reference=body.reference,
            lines=[line.to_line() for line in body.lines],
        )
        if isinstance(result, Err):
            _refuse(connection, result)
        connection.commit()
    return jsonable(result.value)


@router.patch("/entries/{entry_id}")
def update_entry(
    entry_id: str, body: EntryPatch, tenant: TenantContext = Depends(require_permission("finance.admin_entries"))
) -> dict:
    with get_connection() as connection:
        result = ManualEntryService(connection).update_draft(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, entry_id=entry_id,
            journal_code=body.journal_code, entry_date=body.entry_date, label=body.label, reference=body.reference,
            lines=None if body.lines is None else [line.to_line() for line in body.lines],
        )
        if isinstance(result, Err):
            _refuse(connection, result)
        connection.commit()
    return jsonable(result.value)


@router.delete("/entries/{entry_id}")
def delete_entry(entry_id: str, tenant: TenantContext = Depends(require_permission("finance.manage_entries"))) -> dict:
    with get_connection() as connection:
        result = ManualEntryService(connection).delete_draft(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, entry_id=entry_id)
        if isinstance(result, Err):
            _refuse(connection, result)
        connection.commit()
    return result.value


@router.post("/entries/{entry_id}/post")
def post_entry(
    entry_id: str, body: PostIn, tenant: TenantContext = Depends(require_permission("finance.manage_entries"))
) -> dict:
    with get_connection() as connection:
        result = ManualEntryService(connection).post(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, entry_id=entry_id,
            correlation_id=body.correlation_id or str(ULID()),
        )
        if isinstance(result, Err):
            _refuse(connection, result)
        connection.commit()
    return jsonable(result.value)


@router.post("/entries/{entry_id}/reverse")
def reverse_entry(
    entry_id: str, body: ReverseIn, tenant: TenantContext = Depends(require_permission("finance.admin_entries"))
) -> dict:
    with get_connection() as connection:
        result = ManualEntryService(connection).reverse(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, entry_id=entry_id,
            entry_date=body.entry_date, correlation_id=body.correlation_id or str(ULID()),
        )
        if isinstance(result, Err):
            _refuse(connection, result)
        connection.commit()
    return jsonable(result.value)


# Refused automatic postings, and what one source (a payroll run) has in the ledger.


@router.get("/posting-failures")
def list_posting_failures(
    status_filter: str = Query(default="open", alias="status"),
    tenant: TenantContext = Depends(require_permission("finance.view_ledger")),
) -> list[dict]:
    with get_connection() as connection:
        return jsonable(
            PostingFailureService(connection).list_failures(
                tenant_id=tenant.tenant_id, status=None if status_filter == "all" else status_filter
            )
        )


@router.post("/posting-failures/{failure_id}/retry")
def retry_posting_failure(
    failure_id: str, tenant: TenantContext = Depends(require_permission("finance.manage_entries"))
) -> dict:
    with get_connection() as connection:
        result = retry_failure(connection, tenant_id=tenant.tenant_id, actor_id=tenant.user_id, failure_id=failure_id)
        if isinstance(result, Err):
            _refuse(connection, result)
        connection.commit()
    return {"entries": jsonable(result.value)}


@router.get("/ledger/sources/{source_module}/{source_id}")
def source_postings(
    source_module: str,
    source_id: str,
    tenant: TenantContext = Depends(require_any_permission("finance.view_ledger", "payroll.view_runs")),
) -> dict:
    with get_connection() as connection:
        entries = LedgerQueryService(connection).entries_for_source(
            tenant_id=tenant.tenant_id, source_module=source_module, source_id=source_id
        )
        failures = PostingFailureService(connection).failures_for_source(
            tenant_id=tenant.tenant_id, source_module=source_module, source_id=source_id
        )
    return {"entries": jsonable(entries), "failures": jsonable(failures)}


# Reports.


@router.get("/reports/trial-balance")
def trial_balance(
    date_from: datetime.date,
    date_to: datetime.date,
    tenant: TenantContext = Depends(require_permission("finance.view_ledger")),
) -> dict:
    _check_range(date_from, date_to)
    with get_connection() as connection:
        return jsonable(LedgerReportService(connection).trial_balance(tenant_id=tenant.tenant_id, date_from=date_from, date_to=date_to))


@router.get("/reports/general-ledger")
def general_ledger(
    account_code: str,
    date_from: datetime.date,
    date_to: datetime.date,
    tenant: TenantContext = Depends(require_permission("finance.view_ledger")),
) -> dict:
    _check_range(date_from, date_to)
    with get_connection() as connection:
        result = LedgerReportService(connection).general_ledger(
            tenant_id=tenant.tenant_id, account_code=account_code, date_from=date_from, date_to=date_to
        )
        if isinstance(result, Err):
            _refuse(connection, result)
    return jsonable(result.value)


@router.get("/reports/balances")
def account_balances(
    as_of: datetime.date,
    prefixes: str = "42,43,44",
    tenant: TenantContext = Depends(require_permission("finance.view_ledger")),
) -> list[dict]:
    with get_connection() as connection:
        return jsonable(
            LedgerReportService(connection).account_balances(
                tenant_id=tenant.tenant_id,
                prefixes=[prefix.strip() for prefix in prefixes.split(",") if prefix.strip()],
                as_of=as_of,
            )
        )
```

- [ ] **Step 4: Mount the router**

In `backend/app/main.py`, add after `from modules.finance.api.router import router as finance_router`:

```python
from modules.finance.api.ledger_router import router as finance_ledger_router
```

and after `app.include_router(finance_router)`:

```python
app.include_router(finance_ledger_router)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest modules/finance core/test_error_translations.py -q -rs`
Expected: all PASS; the router tests are not skipped (if `httpx` is missing: `.venv/Scripts/python -m pip install -r requirements-dev.txt`).

- [ ] **Step 6: Commit**

```bash
git add backend/modules/finance/api/ledger_router.py backend/modules/finance/api/test_ledger_router_integration.py backend/app/main.py
git commit -m "feat(finance): ledger HTTP routes for accounts, periods, rules, entries and reports

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: Frontend foundations, Chart of accounts and Posting rules screens

**Files:**
- Create: `frontend/src/features/finance/ledgerApi.ts`
- Create: `frontend/src/features/finance/ledgerFormat.ts`
- Create: `frontend/src/features/finance/LedgerTable.tsx`
- Create: `frontend/src/features/finance/AccountsPage.tsx`
- Create: `frontend/src/features/finance/PostingRulesPage.tsx`
- Modify: `frontend/src/routes/router.tsx` (two routes)
- Modify: `frontend/src/routes/Sidebar.tsx` (icons import, `/finance` becomes `exact`, new "Accounting" group)
- Modify: `frontend/src/lib/i18n.tsx` (keys below, `en` and `fr`)

**Interfaces:**
- Consumes: the HTTP routes of Task 10; `apiFetch`, `ApiError` (`lib/api.ts`); `useTableColumns`, `ColumnDef` (`lib/useTableColumns.ts`); `useColumnFilters`, `FilterField` (`lib/useColumnFilters.ts`); `ColumnFilterRow`, `FilterCell`, `ColumnVisibilityMenu`, `FilterTabs`, `EmptyState`, `TableLoadingRow`; `useAuth().hasPermission`; `useI18n().t` / `.language`; `currentLocale()`.
- Produces (used by Tasks 12–14):
  - `ledgerApi.ts`: all types (`LedgerAccount`, `AccountType`, `ACCOUNT_TYPES`, `Journal`, `AccountingPeriod`, `PeriodStatus`, `PostingRule`, `RuleSource`, `RULE_SOURCES`, `RULE_KINDS`, `RuleStatus`, `JournalEntry`, `JournalEntryDetail`, `JournalLine`, `EntryStatus`, `EntryInput`, `EntryLineInput`, `EntryFilters`, `PostingFailure`, `FailureStatus`, `SourcePostings`, `TrialBalance`, `TrialBalanceRow`, `TrialBalanceAmounts`, `GeneralLedger`, `GeneralLedgerLine`, `AccountBalance`), `LEDGER_KEYS`, `invalidateLedgerData(queryClient)`, and one fetcher per route (`setupLedger`, `listAccounts`, `createAccount`, `updateAccount`, `listJournals`, `listPeriods`, `openFiscalYear`, `closePeriod`, `reopenPeriod`, `listPostingRules`, `createPostingRule`, `updatePostingRule`, `confirmPostingRule`, `listEntries`, `getEntry`, `createEntry`, `updateEntry`, `deleteEntry`, `postEntry`, `reverseEntry`, `listPostingFailures`, `retryPostingFailure`, `getSourcePostings`, `getTrialBalance`, `getGeneralLedger`, `getBalances`).
  - `ledgerFormat.ts`: `formatAmount`, `formatAmountCell`, `formatXof`, `formatDate`, `formatMonth`, `todayIso`, `monthStartIso`, `monthEndIso`, `yearStartIso`, `errorText`.
  - `LedgerTable.tsx`: `LedgerTable<Row>` (props `tableKey, columns, rows, rowKey, isLoading, loading?: "loader" | "skeleton", emptyIcon, emptyTitle, emptyDescription, toolbar?, footer?: (columnKey) => ReactNode, onRowClick?`), `textFilter(filters, key, placeholder)`, `rangeFilter(filters, key)`, `EntryStatusBadge({ status })`.
  - `AccountsPage`, `PostingRulesPage`; `ACCOUNT_TYPE_KEYS`, `KIND_KEYS`, `SOURCE_KEYS`, `kindLabel(t, kind)`.

- [ ] **Step 1: Add the API layer and formatting helpers**

`frontend/src/features/finance/ledgerApi.ts`:

```ts
import type { QueryClient } from "@tanstack/react-query";
import { apiFetch } from "../../lib/api";

export const ACCOUNT_TYPES = ["asset", "liability", "equity", "income", "expense"] as const;
export type AccountType = (typeof ACCOUNT_TYPES)[number];

export interface LedgerAccount {
  code: string;
  name: string;
  class_no: number;
  account_type: AccountType;
  is_postable: boolean;
  parent_code: string | null;
}

export interface AccountInput {
  code: string;
  name: string;
  account_type: AccountType;
  is_postable: boolean;
  parent_code: string | null;
}

export interface AccountPatch {
  name?: string;
  account_type?: AccountType;
  is_postable?: boolean;
  /** "" removes the parent. */
  parent_code?: string;
}

export interface Journal {
  code: string;
  name: string;
  journal_type: string;
}

export type PeriodStatus = "open" | "closed";

export interface AccountingPeriod {
  period: string;
  year: number;
  status: PeriodStatus;
  closed_by: string | null;
  closed_at: string | null;
}

export const RULE_SOURCES = ["payroll", "invoice"] as const;
export type RuleSource = (typeof RULE_SOURCES)[number];
export const RULE_KINDS: Record<RuleSource, readonly string[]> = {
  payroll: ["earning", "deduction", "employee_contribution", "employer_contribution", "employer_charge", "tax", "net", "payment"],
  invoice: ["issued", "paid"],
};
export type RuleStatus = "to_confirm" | "confirmed";

export interface PostingRule {
  id: string;
  source: RuleSource;
  source_kind: string;
  code: string;
  debit_account_code: string | null;
  credit_account_code: string | null;
  journal_code: string | null;
  status: RuleStatus;
  confirmed_by: string | null;
  confirmed_at: string | null;
  updated_at: string;
}

export interface PostingRuleInput {
  source: RuleSource;
  source_kind: string;
  code: string;
  debit_account_code: string | null;
  credit_account_code: string | null;
  journal_code: string | null;
}

/** Every field optional; "" clears it. */
export interface PostingRulePatch {
  debit_account_code?: string;
  credit_account_code?: string;
  journal_code?: string;
}

export type EntryStatus = "draft" | "posted" | "reversed";

export interface JournalEntry {
  id: string;
  number: string | null;
  journal_code: string;
  entry_date: string;
  period: string;
  label: string;
  reference: string | null;
  status: EntryStatus;
  source_module: string | null;
  source_id: string | null;
  source_kind: string | null;
  reversal_of: string | null;
  created_by: string;
  created_at: string;
  posted_by: string | null;
  posted_at: string | null;
  total_debit: number;
  total_credit: number;
}

export interface JournalLine {
  line_no: number;
  account_code: string;
  account_name: string;
  debit: number;
  credit: number;
  label: string | null;
  partner_id: string | null;
  partner_name: string | null;
  employee_ref: string | null;
}

export interface JournalEntryDetail extends JournalEntry {
  lines: JournalLine[];
}

export interface EntryLineInput {
  account_code: string;
  debit: number;
  credit: number;
  label?: string | null;
  partner_id?: string | null;
}

export interface EntryInput {
  journal_code: string;
  entry_date: string;
  label: string;
  reference?: string | null;
  lines: EntryLineInput[];
}

export interface EntryFilters {
  date_from: string;
  date_to: string;
  journal_code?: string;
}

export type FailureStatus = "open" | "resolved" | "cancelled";

export interface PostingFailure {
  id: string;
  source_module: string;
  source_id: string;
  source_kind: string;
  event_id: string;
  event_type: string;
  error_code: string;
  error_message: string;
  error_message_fr: string | null;
  status: FailureStatus;
  failed_at: string;
  resolved_at: string | null;
}

export interface SourcePostings {
  entries: JournalEntry[];
  failures: PostingFailure[];
}

export interface TrialBalanceAmounts {
  opening_debit: number;
  opening_credit: number;
  period_debit: number;
  period_credit: number;
  closing_debit: number;
  closing_credit: number;
}

export interface TrialBalanceRow extends TrialBalanceAmounts {
  account_code: string;
  account_name: string;
  class_no: number;
}

export interface TrialBalance {
  rows: TrialBalanceRow[];
  totals: TrialBalanceAmounts;
}

export interface GeneralLedgerLine {
  entry_id: string;
  number: string;
  journal_code: string;
  entry_date: string;
  label: string;
  reference: string | null;
  debit: number;
  credit: number;
  balance: number;
}

export interface GeneralLedger {
  account: LedgerAccount;
  opening_balance: number;
  lines: GeneralLedgerLine[];
  total_debit: number;
  total_credit: number;
  closing_balance: number;
}

export interface AccountBalance {
  account_code: string;
  account_name: string;
  debit: number;
  credit: number;
  owed: number;
}

export const LEDGER_KEYS = {
  accounts: ["finance", "ledger", "accounts"] as const,
  journals: ["finance", "ledger", "journals"] as const,
  periods: ["finance", "ledger", "periods"] as const,
  rules: ["finance", "ledger", "posting-rules"] as const,
  entries: ["finance", "ledger", "entries"] as const,
  entryList: (filters: EntryFilters) => ["finance", "ledger", "entries", "list", filters] as const,
  entry: (id: string) => ["finance", "ledger", "entries", "detail", id] as const,
  failures: ["finance", "ledger", "posting-failures"] as const,
  reports: ["finance", "ledger", "reports"] as const,
  trialBalance: (from: string, to: string) => ["finance", "ledger", "reports", "trial-balance", from, to] as const,
  generalLedger: (code: string, from: string, to: string) =>
    ["finance", "ledger", "reports", "general-ledger", code, from, to] as const,
  balances: (asOf: string) => ["finance", "ledger", "reports", "balances", asOf] as const,
  sources: ["finance", "ledger", "sources"] as const,
  source: (module: string, id: string) => ["finance", "ledger", "sources", module, id] as const,
};

/** After anything that posts, reverses or deletes: every read that could show it. */
export function invalidateLedgerData(queryClient: QueryClient) {
  for (const queryKey of [LEDGER_KEYS.entries, LEDGER_KEYS.reports, LEDGER_KEYS.sources, LEDGER_KEYS.failures]) {
    void queryClient.invalidateQueries({ queryKey });
  }
}

function query(params: Record<string, string | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value) search.set(key, value);
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

export function setupLedger(token: string) {
  return apiFetch<{ accounts: number; journals: number; posting_rules: number }>("/finance/setup", { method: "POST", token });
}

export function listAccounts(token: string) {
  return apiFetch<LedgerAccount[]>("/finance/accounts", { token });
}

export function createAccount(token: string, input: AccountInput) {
  return apiFetch<LedgerAccount>("/finance/accounts", { method: "POST", token, body: input });
}

export function updateAccount(token: string, code: string, patch: AccountPatch) {
  return apiFetch<LedgerAccount>(`/finance/accounts/${encodeURIComponent(code)}`, { method: "PATCH", token, body: patch });
}

export function listJournals(token: string) {
  return apiFetch<Journal[]>("/finance/journals", { token });
}

export function listPeriods(token: string) {
  return apiFetch<AccountingPeriod[]>("/finance/periods", { token });
}

export function openFiscalYear(token: string, year: number) {
  return apiFetch<{ id: string; year: number }>("/finance/fiscal-years", { method: "POST", token, body: { year } });
}

export function closePeriod(token: string, period: string) {
  return apiFetch<AccountingPeriod>(`/finance/periods/${period}/close`, { method: "POST", token });
}

export function reopenPeriod(token: string, period: string) {
  return apiFetch<AccountingPeriod>(`/finance/periods/${period}/reopen`, { method: "POST", token });
}

export function listPostingRules(token: string) {
  return apiFetch<PostingRule[]>("/finance/posting-rules", { token });
}

export function createPostingRule(token: string, input: PostingRuleInput) {
  return apiFetch<PostingRule>("/finance/posting-rules", { method: "POST", token, body: input });
}

export function updatePostingRule(token: string, id: string, patch: PostingRulePatch) {
  return apiFetch<PostingRule>(`/finance/posting-rules/${id}`, { method: "PATCH", token, body: patch });
}

export function confirmPostingRule(token: string, id: string) {
  return apiFetch<PostingRule>(`/finance/posting-rules/${id}/confirm`, { method: "POST", token });
}

export function listEntries(token: string, filters: EntryFilters) {
  const search = query({ date_from: filters.date_from, date_to: filters.date_to, journal_code: filters.journal_code });
  return apiFetch<JournalEntry[]>(`/finance/entries${search}`, { token });
}

export function getEntry(token: string, id: string) {
  return apiFetch<JournalEntryDetail>(`/finance/entries/${id}`, { token });
}

export function createEntry(token: string, input: EntryInput) {
  return apiFetch<JournalEntryDetail>("/finance/entries", { method: "POST", token, body: input });
}

export function updateEntry(token: string, id: string, input: EntryInput) {
  return apiFetch<JournalEntryDetail>(`/finance/entries/${id}`, { method: "PATCH", token, body: input });
}

export function deleteEntry(token: string, id: string) {
  return apiFetch<{ id: string }>(`/finance/entries/${id}`, { method: "DELETE", token });
}

export function postEntry(token: string, id: string) {
  return apiFetch<JournalEntry>(`/finance/entries/${id}/post`, {
    method: "POST",
    token,
    body: { correlation_id: crypto.randomUUID() },
  });
}

export function reverseEntry(token: string, id: string, entryDate: string) {
  return apiFetch<JournalEntry>(`/finance/entries/${id}/reverse`, {
    method: "POST",
    token,
    body: { entry_date: entryDate, correlation_id: crypto.randomUUID() },
  });
}

export function listPostingFailures(token: string) {
  return apiFetch<PostingFailure[]>("/finance/posting-failures?status=open", { token });
}

export function retryPostingFailure(token: string, id: string) {
  return apiFetch<{ entries: JournalEntry[] }>(`/finance/posting-failures/${id}/retry`, { method: "POST", token });
}

export function getSourcePostings(token: string, module: string, id: string) {
  return apiFetch<SourcePostings>(`/finance/ledger/sources/${encodeURIComponent(module)}/${encodeURIComponent(id)}`, { token });
}

export function getTrialBalance(token: string, from: string, to: string) {
  return apiFetch<TrialBalance>(`/finance/reports/trial-balance${query({ date_from: from, date_to: to })}`, { token });
}

export function getGeneralLedger(token: string, accountCode: string, from: string, to: string) {
  const search = query({ account_code: accountCode, date_from: from, date_to: to });
  return apiFetch<GeneralLedger>(`/finance/reports/general-ledger${search}`, { token });
}

export function getBalances(token: string, asOf: string) {
  return apiFetch<AccountBalance[]>(`/finance/reports/balances${query({ as_of: asOf, prefixes: "42,43,44" })}`, { token });
}
```

`frontend/src/features/finance/ledgerFormat.ts`:

```ts
import { ApiError } from "../../lib/api";
import { currentLocale } from "../../lib/i18n";

/** Whole francs (XOF has no sub-unit), grouped the way the chosen language writes numbers. */
export function formatAmount(amount: number): string {
  return new Intl.NumberFormat(currentLocale(), { maximumFractionDigits: 0 }).format(amount);
}

/** An amount cell of a ledger table: blank for zero, the way accountants print books. */
export function formatAmountCell(amount: number): string {
  return amount === 0 ? "" : formatAmount(amount);
}

export function formatXof(amount: number): string {
  return `${formatAmount(amount)} F CFA`;
}

export function formatDate(iso: string): string {
  return new Intl.DateTimeFormat(currentLocale(), { day: "2-digit", month: "2-digit", year: "numeric" }).format(
    new Date(`${iso.slice(0, 10)}T00:00:00`),
  );
}

export function formatMonth(period: string): string {
  return new Intl.DateTimeFormat(currentLocale(), { month: "long", year: "numeric" }).format(new Date(`${period}T00:00:00`));
}

function isoDay(date: Date): string {
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}`;
}

export function todayIso(): string {
  return isoDay(new Date());
}

export function monthStartIso(date = new Date()): string {
  return isoDay(new Date(date.getFullYear(), date.getMonth(), 1));
}

export function monthEndIso(date = new Date()): string {
  return isoDay(new Date(date.getFullYear(), date.getMonth() + 1, 0));
}

export function yearStartIso(date = new Date()): string {
  return isoDay(new Date(date.getFullYear(), 0, 1));
}

export function errorText(error: unknown): string | undefined {
  return error instanceof ApiError ? error.message : undefined;
}
```

- [ ] **Step 2: Add the shared ledger table**

`frontend/src/features/finance/LedgerTable.tsx`:

```tsx
import type { ReactNode } from "react";
import { Badge } from "../../components/ui/badge";
import { Skeleton } from "../../components/ui/skeleton";
import { ResizableTableHead, Table, TableBody, TableCell, TableHeader, TableRow } from "../../components/ui/table";
import { TableLoadingRow } from "../../components/patterns/AppLoader";
import { ColumnFilterRow, type FilterCell } from "../../components/patterns/ColumnFilterRow";
import { ColumnVisibilityMenu } from "../../components/patterns/ColumnVisibilityMenu";
import { EmptyState } from "../../components/patterns/EmptyState";
import { useI18n } from "../../lib/i18n";
import { useTableColumns, type ColumnDef } from "../../lib/useTableColumns";
import { cn } from "../../lib/utils";
import type { EntryStatus } from "./ledgerApi";

interface TextFilters {
  text: Record<string, string>;
  setTextValue: (key: string, value: string) => void;
}

interface RangeFilters {
  range: Record<string, { min: string; max: string }>;
  setRangeValue: (key: string, part: "min" | "max", value: string) => void;
}

export function textFilter(filters: TextFilters, key: string, placeholder: string): FilterCell {
  return { type: "text", value: filters.text[key] ?? "", onChange: (value) => filters.setTextValue(key, value), placeholder };
}

export function rangeFilter(filters: RangeFilters, key: string): FilterCell {
  return {
    type: "range",
    min: filters.range[key]?.min ?? "",
    max: filters.range[key]?.max ?? "",
    onMinChange: (value) => filters.setRangeValue(key, "min", value),
    onMaxChange: (value) => filters.setRangeValue(key, "max", value),
  };
}

export function EntryStatusBadge({ status }: { status: EntryStatus }) {
  const { t } = useI18n();
  if (status === "posted") return <Badge variant="success">{t("finance.entries.status.posted")}</Badge>;
  if (status === "reversed") return <Badge variant="warning">{t("finance.entries.status.reversed")}</Badge>;
  return <Badge>{t("finance.entries.status.draft")}</Badge>;
}

/**
 * The ledger screens' table: header, ColumnFilterRow and body all come from one ColumnDef array
 * (useTableColumns: per-user widths, visibility and sorting), with an optional totals row. The page
 * keeps the filtering (FilterTabs + useColumnFilters) and passes the filtered rows in.
 */
export function LedgerTable<Row>({
  tableKey,
  columns,
  rows,
  rowKey,
  isLoading,
  loading = "loader",
  emptyIcon,
  emptyTitle,
  emptyDescription,
  toolbar,
  footer,
  onRowClick,
}: {
  tableKey: string;
  columns: ColumnDef<Row>[];
  rows: Row[];
  rowKey: (row: Row) => string;
  isLoading: boolean;
  /** "loader" for the screen's main table (its one branded loader), "skeleton" for any other table on it. */
  loading?: "loader" | "skeleton";
  emptyIcon: ReactNode;
  emptyTitle: string;
  emptyDescription: string;
  toolbar?: ReactNode;
  /** Content of each visible column's cell in the totals row, by column key. */
  footer?: (columnKey: string) => ReactNode;
  onRowClick?: (row: Row) => void;
}) {
  const { visibleColumns, colWidths, isVisible, toggleVisible, getWidth, setWidth, resetAll, sortDirectionFor, toggleSort, sortRows } =
    useTableColumns(tableKey, columns);
  const sorted = sortRows(rows);
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3 px-6">
        {toolbar}
        <div className="ml-auto">
          <ColumnVisibilityMenu columns={columns} isVisible={isVisible} onToggle={toggleVisible} onReset={resetAll} />
        </div>
      </div>
      <Table colWidths={colWidths}>
        <TableHeader>
          <TableRow>
            {visibleColumns.map((column) => (
              <ResizableTableHead
                key={column.key}
                width={getWidth(column.key)}
                onResize={(width) => setWidth(column.key, width)}
                className={column.headerClassName}
                sortDirection={sortDirectionFor(column.key)}
                onSort={column.sortValue ? () => toggleSort(column.key) : undefined}
              >
                {column.header}
              </ResizableTableHead>
            ))}
          </TableRow>
          <ColumnFilterRow cells={visibleColumns.map((column) => column.filterCell ?? { type: "blank" })} />
        </TableHeader>
        <TableBody>
          {isLoading && loading === "loader" && <TableLoadingRow colSpan={visibleColumns.length} />}
          {isLoading && loading === "skeleton" && (
            <TableRow>
              <TableCell colSpan={visibleColumns.length}>
                <Skeleton className="h-6 w-full" />
              </TableCell>
            </TableRow>
          )}
          {!isLoading && rows.length === 0 && (
            <TableRow>
              <TableCell colSpan={visibleColumns.length} className="p-0">
                <EmptyState icon={emptyIcon} title={emptyTitle} description={emptyDescription} />
              </TableCell>
            </TableRow>
          )}
          {!isLoading &&
            sorted.map((row) => (
              <TableRow
                key={rowKey(row)}
                className={cn(onRowClick && "cursor-pointer hover:bg-muted/50")}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
              >
                {visibleColumns.map((column) => (
                  <TableCell key={column.key} className={column.cellClassName}>
                    {column.cell(row)}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          {!isLoading && rows.length > 0 && footer && (
            <TableRow className="bg-muted/40 font-semibold">
              {visibleColumns.map((column) => (
                <TableCell key={column.key} className={column.cellClassName}>
                  {footer(column.key)}
                </TableCell>
              ))}
            </TableRow>
          )}
        </TableBody>
      </Table>
    </div>
  );
}
```

- [ ] **Step 3: Add the Chart of accounts screen**

`frontend/src/features/finance/AccountsPage.tsx`:

```tsx
import { useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ListTree, Pencil, Plus, WandSparkles } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../lib/auth";
import { useI18n, type TranslationKey } from "../../lib/i18n";
import { useColumnFilters, type FilterField } from "../../lib/useColumnFilters";
import type { ColumnDef } from "../../lib/useTableColumns";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../components/ui/dialog";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select } from "../../components/ui/select";
import { FilterTabs } from "../../components/patterns/FilterTabs";
import { LedgerTable, textFilter } from "./LedgerTable";
import { errorText } from "./ledgerFormat";
import {
  ACCOUNT_TYPES,
  LEDGER_KEYS,
  createAccount,
  listAccounts,
  setupLedger,
  updateAccount,
  type AccountType,
  type LedgerAccount,
} from "./ledgerApi";

export const ACCOUNT_TYPE_KEYS: Record<AccountType, TranslationKey> = {
  asset: "finance.accounts.type.asset",
  liability: "finance.accounts.type.liability",
  equity: "finance.accounts.type.equity",
  income: "finance.accounts.type.income",
  expense: "finance.accounts.type.expense",
};

const CLASSES = ["1", "2", "3", "4", "5", "6", "7", "8", "9"] as const;
type ClassFilter = "all" | (typeof CLASSES)[number];

export function AccountsPage() {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [classFilter, setClassFilter] = useState<ClassFilter>("all");
  const [editing, setEditing] = useState<LedgerAccount | "new" | null>(null);
  const { data: accounts = [], isLoading } = useQuery({ queryKey: LEDGER_KEYS.accounts, queryFn: () => listAccounts(token) });

  const setupMutation = useMutation({
    mutationFn: () => setupLedger(token),
    onSuccess: () => {
      for (const queryKey of [LEDGER_KEYS.accounts, LEDGER_KEYS.journals, LEDGER_KEYS.rules]) {
        void queryClient.invalidateQueries({ queryKey });
      }
      toast.success(t("finance.accounts.setupDone"));
    },
    onError: (error) => toast.error(t("finance.accounts.setupError"), { description: errorText(error) }),
  });

  const fields: FilterField<LedgerAccount>[] = [
    { key: "code", kind: "text", getValue: (account) => account.code },
    { key: "name", kind: "text", getValue: (account) => account.name },
    { key: "account_type", kind: "text", getValue: (account) => t(ACCOUNT_TYPE_KEYS[account.account_type]) },
    { key: "parent_code", kind: "text", getValue: (account) => account.parent_code ?? "" },
  ];
  const columnFilters = useColumnFilters(fields);
  const byClass = classFilter === "all" ? accounts : accounts.filter((account) => String(account.class_no) === classFilter);
  const rows = columnFilters.apply(byClass);

  const columns: ColumnDef<LedgerAccount>[] = [
    {
      key: "code",
      header: t("finance.accounts.column.code"),
      defaultWidth: 120,
      cell: (account) => (
        <span className="font-mono tabular-nums" style={{ paddingLeft: `${(account.code.length - 1) * 10}px` }}>
          {account.code}
        </span>
      ),
      filterCell: textFilter(columnFilters, "code", t("finance.accounts.column.code")),
      sortValue: (account) => account.code,
    },
    {
      key: "name",
      header: t("finance.accounts.column.name"),
      defaultWidth: 340,
      cell: (account) => <span className={account.is_postable ? undefined : "font-semibold"}>{account.name}</span>,
      filterCell: textFilter(columnFilters, "name", t("finance.accounts.column.name")),
      sortValue: (account) => account.name,
    },
    {
      key: "account_type",
      header: t("finance.accounts.column.type"),
      defaultWidth: 140,
      cell: (account) => t(ACCOUNT_TYPE_KEYS[account.account_type]),
      filterCell: textFilter(columnFilters, "account_type", t("finance.accounts.column.type")),
      sortValue: (account) => account.account_type,
    },
    {
      key: "is_postable",
      header: t("finance.accounts.column.postable"),
      defaultWidth: 130,
      cell: (account) =>
        account.is_postable ? (
          <Badge variant="success">{t("finance.accounts.postable")}</Badge>
        ) : (
          <Badge>{t("finance.accounts.heading")}</Badge>
        ),
      sortValue: (account) => account.is_postable,
    },
    {
      key: "parent_code",
      header: t("finance.accounts.column.parent"),
      defaultWidth: 110,
      cell: (account) => <span className="font-mono">{account.parent_code ?? "—"}</span>,
      filterCell: textFilter(columnFilters, "parent_code", t("finance.accounts.column.parent")),
      sortValue: (account) => account.parent_code ?? "",
    },
    {
      key: "actions",
      header: t("finance.column.action"),
      defaultWidth: 120,
      alwaysVisible: true,
      headerClassName: "text-right",
      cell: (account) =>
        hasPermission("finance.admin_accounts") ? (
          <div className="flex justify-end">
            <Button size="sm" variant="outline" onClick={() => setEditing(account)}>
              <Pencil className="h-3.5 w-3.5" />
              {t("common.edit")}
            </Button>
          </div>
        ) : null,
    },
  ];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">{t("finance.accounts.title")}</h1>
          <p className="text-sm text-muted-foreground">{t("finance.accounts.subtitle")}</p>
        </div>
        <div className="flex gap-2">
          {hasPermission("finance.admin_accounts") && (
            <Button variant="outline" onClick={() => setupMutation.mutate()} disabled={setupMutation.isPending}>
              <WandSparkles className="h-4 w-4" />
              {t("finance.accounts.setup")}
            </Button>
          )}
          {hasPermission("finance.manage_accounts") && (
            <Button onClick={() => setEditing("new")}>
              <Plus className="h-4 w-4" />
              {t("finance.accounts.new")}
            </Button>
          )}
        </div>
      </div>
      <Card>
        <CardHeader>
          <CardTitle>{t("finance.accounts.tableTitle")}</CardTitle>
        </CardHeader>
        <CardContent className="p-0 pb-2">
          <LedgerTable
            tableKey="finance.accounts"
            columns={columns}
            rows={rows}
            rowKey={(account) => account.code}
            isLoading={isLoading}
            emptyIcon={<ListTree className="h-5 w-5" />}
            emptyTitle={t("finance.accounts.emptyTitle")}
            emptyDescription={t("finance.accounts.emptyDescription")}
            toolbar={
              <>
                <FilterTabs
                  value={classFilter}
                  onChange={setClassFilter}
                  options={[
                    { value: "all", label: t("common.all") },
                    ...CLASSES.map((classNo) => ({ value: classNo, label: `${t("finance.accounts.classShort")} ${classNo}` })),
                  ]}
                />
                {columnFilters.isActive && (
                  <Button variant="ghost" size="sm" onClick={columnFilters.reset}>
                    {t("common.clearFilters")}
                  </Button>
                )}
              </>
            }
          />
        </CardContent>
      </Card>
      {editing !== null && (
        <AccountDialog account={editing === "new" ? null : editing} accounts={accounts} onClose={() => setEditing(null)} />
      )}
    </div>
  );
}

function AccountDialog({
  account,
  accounts,
  onClose,
}: {
  account: LedgerAccount | null;
  accounts: LedgerAccount[];
  onClose: () => void;
}) {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const schema = useMemo(
    () =>
      z.object({
        code: z.string().trim().regex(/^[1-9][0-9]{0,9}$/, t("finance.accounts.codeInvalid")),
        name: z.string().trim().min(1, t("common.required")),
        account_type: z.enum(ACCOUNT_TYPES),
        is_postable: z.boolean(),
        parent_code: z.string(),
      }),
    [t],
  );
  type AccountForm = z.infer<typeof schema>;
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<AccountForm>({
    resolver: zodResolver(schema),
    defaultValues: account
      ? {
          code: account.code,
          name: account.name,
          account_type: account.account_type,
          is_postable: account.is_postable,
          parent_code: account.parent_code ?? "",
        }
      : { code: "", name: "", account_type: "asset", is_postable: true, parent_code: "" },
  });
  const mutation = useMutation({
    mutationFn: (form: AccountForm) =>
      account
        ? updateAccount(token, account.code, {
            name: form.name,
            account_type: form.account_type,
            is_postable: form.is_postable,
            parent_code: form.parent_code,
          })
        : createAccount(token, {
            code: form.code,
            name: form.name,
            account_type: form.account_type,
            is_postable: form.is_postable,
            parent_code: form.parent_code || null,
          }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: LEDGER_KEYS.accounts });
      toast.success(t(account ? "finance.accounts.updated" : "finance.accounts.created"));
      onClose();
    },
    onError: (error) => toast.error(t("finance.accounts.saveError"), { description: errorText(error) }),
  });
  const parents = accounts.filter((candidate) => candidate.code !== account?.code);

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t(account ? "finance.accounts.editTitle" : "finance.accounts.newTitle")}</DialogTitle>
          <DialogDescription>{t("finance.accounts.dialogDescription")}</DialogDescription>
        </DialogHeader>
        <form className="space-y-4" onSubmit={handleSubmit((form) => mutation.mutate(form))}>
          <div className="grid grid-cols-3 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="account_code">{t("finance.accounts.column.code")}</Label>
              {/* readOnly, not disabled: a disabled field is left out of the submitted values. */}
              <Input id="account_code" readOnly={account !== null} {...register("code")} />
              {errors.code && <p className="text-sm text-destructive">{errors.code.message}</p>}
            </div>
            <div className="col-span-2 space-y-1.5">
              <Label htmlFor="account_name">{t("finance.accounts.column.name")}</Label>
              <Input id="account_name" {...register("name")} />
              {errors.name && <p className="text-sm text-destructive">{errors.name.message}</p>}
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="account_type">{t("finance.accounts.column.type")}</Label>
              <Select id="account_type" {...register("account_type")}>
                {ACCOUNT_TYPES.map((type) => (
                  <option key={type} value={type}>
                    {t(ACCOUNT_TYPE_KEYS[type])}
                  </option>
                ))}
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="account_parent">{t("finance.accounts.column.parent")}</Label>
              <Select id="account_parent" {...register("parent_code")}>
                <option value="">{t("common.none")}</option>
                {parents.map((candidate) => (
                  <option key={candidate.code} value={candidate.code}>
                    {candidate.code} · {candidate.name}
                  </option>
                ))}
              </Select>
            </div>
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" className="h-4 w-4" {...register("is_postable")} />
            {t("finance.accounts.postableHint")}
          </label>
          <Button type="submit" className="w-full" disabled={mutation.isPending}>
            {mutation.isPending ? t("common.saving") : t("common.save")}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
```

- [ ] **Step 4: Add the Posting rules screen**

`frontend/src/features/finance/PostingRulesPage.tsx`:

```tsx
import { useEffect, useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, GitBranch, Pencil, Plus } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../lib/auth";
import { useI18n, type TranslationKey } from "../../lib/i18n";
import { useColumnFilters, type FilterField } from "../../lib/useColumnFilters";
import type { ColumnDef } from "../../lib/useTableColumns";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../components/ui/dialog";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select } from "../../components/ui/select";
import { FilterTabs } from "../../components/patterns/FilterTabs";
import { LedgerTable, textFilter } from "./LedgerTable";
import { errorText } from "./ledgerFormat";
import {
  LEDGER_KEYS,
  RULE_KINDS,
  RULE_SOURCES,
  confirmPostingRule,
  createPostingRule,
  listAccounts,
  listJournals,
  listPostingRules,
  updatePostingRule,
  type PostingRule,
  type RuleSource,
  type RuleStatus,
} from "./ledgerApi";

export const SOURCE_KEYS: Record<RuleSource, TranslationKey> = {
  payroll: "finance.rules.source.payroll",
  invoice: "finance.rules.source.invoice",
};

export const KIND_KEYS: Record<string, TranslationKey> = {
  earning: "finance.rules.kind.earning",
  deduction: "finance.rules.kind.deduction",
  employee_contribution: "finance.rules.kind.employee_contribution",
  employer_contribution: "finance.rules.kind.employer_contribution",
  employer_charge: "finance.rules.kind.employer_charge",
  tax: "finance.rules.kind.tax",
  net: "finance.rules.kind.net",
  payment: "finance.rules.kind.payment",
  issued: "finance.rules.kind.issued",
  paid: "finance.rules.kind.paid",
};

export function kindLabel(t: (key: TranslationKey) => string, kind: string): string {
  const key = KIND_KEYS[kind];
  return key ? t(key) : kind;
}

export function PostingRulesPage() {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const canManage = hasPermission("finance.manage_posting_rules");
  const [sourceFilter, setSourceFilter] = useState<"all" | RuleSource>("all");
  const [statusFilter, setStatusFilter] = useState<"all" | RuleStatus>("all");
  const [editing, setEditing] = useState<PostingRule | "new" | null>(null);
  const { data: rules = [], isLoading } = useQuery({ queryKey: LEDGER_KEYS.rules, queryFn: () => listPostingRules(token) });

  const confirmMutation = useMutation({
    mutationFn: (id: string) => confirmPostingRule(token, id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: LEDGER_KEYS.rules });
      toast.success(t("finance.rules.confirmed"));
    },
    onError: (error) => toast.error(t("finance.rules.confirmError"), { description: errorText(error) }),
  });

  const fields: FilterField<PostingRule>[] = [
    { key: "source_kind", kind: "text", getValue: (rule) => kindLabel(t, rule.source_kind) },
    { key: "code", kind: "text", getValue: (rule) => rule.code },
    { key: "debit_account_code", kind: "text", getValue: (rule) => rule.debit_account_code ?? "" },
    { key: "credit_account_code", kind: "text", getValue: (rule) => rule.credit_account_code ?? "" },
    { key: "journal_code", kind: "text", getValue: (rule) => rule.journal_code ?? "" },
  ];
  const columnFilters = useColumnFilters(fields);
  const rows = columnFilters.apply(
    rules.filter(
      (rule) =>
        (sourceFilter === "all" || rule.source === sourceFilter) && (statusFilter === "all" || rule.status === statusFilter),
    ),
  );
  const toConfirm = rules.filter((rule) => rule.status === "to_confirm").length;
  const accountCell = (code: string | null) => <span className="font-mono">{code ?? "—"}</span>;

  const columns: ColumnDef<PostingRule>[] = [
    {
      key: "source",
      header: t("finance.rules.column.source"),
      defaultWidth: 110,
      cell: (rule) => t(SOURCE_KEYS[rule.source]),
      sortValue: (rule) => rule.source,
    },
    {
      key: "source_kind",
      header: t("finance.rules.column.kind"),
      defaultWidth: 200,
      cell: (rule) => kindLabel(t, rule.source_kind),
      filterCell: textFilter(columnFilters, "source_kind", t("finance.rules.column.kind")),
      sortValue: (rule) => rule.source_kind,
    },
    {
      key: "code",
      header: t("finance.rules.column.code"),
      defaultWidth: 130,
      cell: (rule) => <span className="font-mono">{rule.code === "*" ? t("finance.rules.anyCode") : rule.code}</span>,
      filterCell: textFilter(columnFilters, "code", t("finance.rules.column.code")),
      sortValue: (rule) => rule.code,
    },
    {
      key: "debit_account_code",
      header: t("finance.rules.column.debit"),
      defaultWidth: 110,
      cell: (rule) => accountCell(rule.debit_account_code),
      filterCell: textFilter(columnFilters, "debit_account_code", t("finance.rules.column.debit")),
      sortValue: (rule) => rule.debit_account_code ?? "",
    },
    {
      key: "credit_account_code",
      header: t("finance.rules.column.credit"),
      defaultWidth: 110,
      cell: (rule) => accountCell(rule.credit_account_code),
      filterCell: textFilter(columnFilters, "credit_account_code", t("finance.rules.column.credit")),
      sortValue: (rule) => rule.credit_account_code ?? "",
    },
    {
      key: "journal_code",
      header: t("finance.rules.column.journal"),
      defaultWidth: 100,
      cell: (rule) => accountCell(rule.journal_code),
      filterCell: textFilter(columnFilters, "journal_code", t("finance.rules.column.journal")),
      sortValue: (rule) => rule.journal_code ?? "",
    },
    {
      key: "status",
      header: t("finance.rules.column.status"),
      defaultWidth: 130,
      cell: (rule) =>
        rule.status === "confirmed" ? (
          <Badge variant="success">{t("finance.rules.status.confirmed")}</Badge>
        ) : (
          <Badge variant="warning">{t("finance.rules.status.to_confirm")}</Badge>
        ),
      sortValue: (rule) => rule.status,
    },
    {
      key: "actions",
      header: t("finance.column.action"),
      defaultWidth: 220,
      alwaysVisible: true,
      headerClassName: "text-right",
      cell: (rule) =>
        canManage ? (
          <div className="flex justify-end gap-2">
            <Button size="sm" variant="outline" onClick={() => setEditing(rule)}>
              <Pencil className="h-3.5 w-3.5" />
              {t("common.edit")}
            </Button>
            {rule.status === "to_confirm" && (
              <Button
                size="sm"
                variant="outline"
                disabled={confirmMutation.isPending}
                onClick={() => confirmMutation.mutate(rule.id)}
              >
                <Check className="h-3.5 w-3.5" />
                {t("finance.rules.confirm")}
              </Button>
            )}
          </div>
        ) : null,
    },
  ];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">{t("finance.rules.title")}</h1>
          <p className="text-sm text-muted-foreground">{t("finance.rules.subtitle")}</p>
        </div>
        {canManage && (
          <Button onClick={() => setEditing("new")}>
            <Plus className="h-4 w-4" />
            {t("finance.rules.new")}
          </Button>
        )}
      </div>
      {toConfirm > 0 && (
        <div className="rounded-md border border-warning/30 bg-warning-soft px-4 py-3 text-sm text-warning">
          {toConfirm} {t("finance.rules.toConfirmBanner")}
        </div>
      )}
      <Card>
        <CardHeader>
          <CardTitle>{t("finance.rules.tableTitle")}</CardTitle>
        </CardHeader>
        <CardContent className="p-0 pb-2">
          <LedgerTable
            tableKey="finance.postingRules"
            columns={columns}
            rows={rows}
            rowKey={(rule) => rule.id}
            isLoading={isLoading}
            emptyIcon={<GitBranch className="h-5 w-5" />}
            emptyTitle={t("finance.rules.emptyTitle")}
            emptyDescription={t("finance.rules.emptyDescription")}
            toolbar={
              <>
                <FilterTabs
                  value={sourceFilter}
                  onChange={setSourceFilter}
                  options={[
                    { value: "all", label: t("common.all") },
                    ...RULE_SOURCES.map((source) => ({ value: source, label: t(SOURCE_KEYS[source]) })),
                  ]}
                />
                <FilterTabs
                  value={statusFilter}
                  onChange={setStatusFilter}
                  options={[
                    { value: "all", label: t("common.all") },
                    { value: "to_confirm", label: t("finance.rules.status.to_confirm") },
                    { value: "confirmed", label: t("finance.rules.status.confirmed") },
                  ]}
                />
                {columnFilters.isActive && (
                  <Button variant="ghost" size="sm" onClick={columnFilters.reset}>
                    {t("common.clearFilters")}
                  </Button>
                )}
              </>
            }
          />
        </CardContent>
      </Card>
      {editing !== null && <RuleDialog rule={editing === "new" ? null : editing} onClose={() => setEditing(null)} />}
    </div>
  );
}

function RuleDialog({ rule, onClose }: { rule: PostingRule | null; onClose: () => void }) {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const { data: accounts = [] } = useQuery({ queryKey: LEDGER_KEYS.accounts, queryFn: () => listAccounts(token) });
  const { data: journals = [] } = useQuery({ queryKey: LEDGER_KEYS.journals, queryFn: () => listJournals(token) });
  const postable = accounts.filter((account) => account.is_postable);
  const schema = useMemo(
    () =>
      z
        .object({
          source: z.enum(RULE_SOURCES),
          source_kind: z.string().min(1, t("common.required")),
          code: z.string().trim().min(1, t("common.required")),
          debit_account_code: z.string(),
          credit_account_code: z.string(),
          journal_code: z.string(),
        })
        .refine((values) => values.debit_account_code !== "" || values.credit_account_code !== "", {
          message: t("finance.rules.needsAccount"),
          path: ["debit_account_code"],
        }),
    [t],
  );
  type RuleForm = z.infer<typeof schema>;
  const {
    register,
    handleSubmit,
    watch,
    setValue,
    getValues,
    formState: { errors },
  } = useForm<RuleForm>({
    resolver: zodResolver(schema),
    defaultValues: rule
      ? {
          source: rule.source,
          source_kind: rule.source_kind,
          code: rule.code,
          debit_account_code: rule.debit_account_code ?? "",
          credit_account_code: rule.credit_account_code ?? "",
          journal_code: rule.journal_code ?? "",
        }
      : {
          source: "payroll",
          source_kind: "employee_contribution",
          code: "",
          debit_account_code: "",
          credit_account_code: "",
          journal_code: "",
        },
  });
  const source = watch("source");
  useEffect(() => {
    if (!RULE_KINDS[source].includes(getValues("source_kind"))) setValue("source_kind", RULE_KINDS[source][0]);
  }, [source, getValues, setValue]);

  const mutation = useMutation({
    mutationFn: (values: RuleForm) =>
      rule
        ? updatePostingRule(token, rule.id, {
            debit_account_code: values.debit_account_code,
            credit_account_code: values.credit_account_code,
            journal_code: values.journal_code,
          })
        : createPostingRule(token, {
            source: values.source,
            source_kind: values.source_kind,
            code: values.code,
            debit_account_code: values.debit_account_code || null,
            credit_account_code: values.credit_account_code || null,
            journal_code: values.journal_code || null,
          }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: LEDGER_KEYS.rules });
      toast.success(t(rule ? "finance.rules.updated" : "finance.rules.created"));
      onClose();
    },
    onError: (error) => toast.error(t("finance.rules.saveError"), { description: errorText(error) }),
  });

  const accountOptions = (
    <>
      <option value="">{t("common.none")}</option>
      {postable.map((account) => (
        <option key={account.code} value={account.code}>
          {account.code} · {account.name}
        </option>
      ))}
    </>
  );

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t(rule ? "finance.rules.editTitle" : "finance.rules.newTitle")}</DialogTitle>
          <DialogDescription>{t("finance.rules.dialogDescription")}</DialogDescription>
        </DialogHeader>
        <form className="space-y-4" onSubmit={handleSubmit((values) => mutation.mutate(values))}>
          {rule ? (
            // Source, kind and code are the rule's key: shown, not edited (they stay in the form values).
            <p className="text-sm">
              <span className="font-medium">{t(SOURCE_KEYS[rule.source])}</span> · {kindLabel(t, rule.source_kind)} ·{" "}
              <span className="font-mono">{rule.code === "*" ? t("finance.rules.anyCode") : rule.code}</span>
            </p>
          ) : (
            <div className="grid grid-cols-3 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="rule_source">{t("finance.rules.column.source")}</Label>
                <Select id="rule_source" {...register("source")}>
                  {RULE_SOURCES.map((option) => (
                    <option key={option} value={option}>
                      {t(SOURCE_KEYS[option])}
                    </option>
                  ))}
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="rule_kind">{t("finance.rules.column.kind")}</Label>
                <Select id="rule_kind" {...register("source_kind")}>
                  {RULE_KINDS[source].map((kind) => (
                    <option key={kind} value={kind}>
                      {kindLabel(t, kind)}
                    </option>
                  ))}
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="rule_code">{t("finance.rules.column.code")}</Label>
                <Input id="rule_code" placeholder="*" {...register("code")} />
                {errors.code && <p className="text-sm text-destructive">{errors.code.message}</p>}
              </div>
            </div>
          )}
          <div className="grid grid-cols-3 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="rule_debit">{t("finance.rules.column.debit")}</Label>
              <Select id="rule_debit" {...register("debit_account_code")}>
                {accountOptions}
              </Select>
              {errors.debit_account_code && <p className="text-sm text-destructive">{errors.debit_account_code.message}</p>}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="rule_credit">{t("finance.rules.column.credit")}</Label>
              <Select id="rule_credit" {...register("credit_account_code")}>
                {accountOptions}
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="rule_journal">{t("finance.rules.column.journal")}</Label>
              <Select id="rule_journal" {...register("journal_code")}>
                <option value="">{t("common.none")}</option>
                {journals.map((journal) => (
                  <option key={journal.code} value={journal.code}>
                    {journal.code} · {journal.name}
                  </option>
                ))}
              </Select>
            </div>
          </div>
          <Button type="submit" className="w-full" disabled={mutation.isPending}>
            {mutation.isPending ? t("common.saving") : t("common.save")}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
```

- [ ] **Step 5: Wire the routes and the sidebar**

`frontend/src/routes/router.tsx` — add the imports next to the `FinanceInvoicesPage` import:

```tsx
import { AccountsPage } from "../features/finance/AccountsPage";
import { PostingRulesPage } from "../features/finance/PostingRulesPage";
```

and in `protectedChildren`, right after `{ path: "/finance", element: <FinanceInvoicesPage /> },`:

```tsx
  { path: "/finance/accounts", element: <AccountsPage /> },
  { path: "/finance/posting-rules", element: <PostingRulesPage /> },
```

`frontend/src/routes/Sidebar.tsx` — add `GitBranch` and `ListTree` to the `lucide-react` import list; in the `nav.commerce` group change the finance item to

```tsx
      { to: "/finance", labelKey: "nav.finance", icon: Wallet, exact: true },
```

(so it no longer lights up on `/finance/accounts`), and add this group right after the `nav.commerce` group:

```tsx
  {
    labelKey: "nav.accounting",
    items: [
      { to: "/finance/accounts", labelKey: "nav.chartOfAccounts", icon: ListTree, permission: "finance.view_ledger" },
      { to: "/finance/posting-rules", labelKey: "nav.postingRules", icon: GitBranch, permission: "finance.view_ledger" },
    ],
  },
```

- [ ] **Step 6: Add the strings**

`frontend/src/lib/i18n.tsx` — at the end of the `en` object (just before `} as const;`):

```ts
  "nav.accounting": "Accounting",
  "nav.chartOfAccounts": "Chart of accounts",
  "nav.postingRules": "Posting rules",
  "finance.accounts.title": "Chart of accounts",
  "finance.accounts.subtitle": "SYSCOHADA accounts. Headings group the accounts that entries are posted to.",
  "finance.accounts.tableTitle": "Accounts",
  "finance.accounts.new": "New account",
  "finance.accounts.newTitle": "New account",
  "finance.accounts.editTitle": "Edit account",
  "finance.accounts.dialogDescription": "The number starts with its class digit and extends its parent's number. It cannot change once created.",
  "finance.accounts.setup": "Install SYSCOHADA chart",
  "finance.accounts.setupDone": "SYSCOHADA chart, journals and default posting rules installed",
  "finance.accounts.setupError": "Could not install the chart",
  "finance.accounts.created": "Account created",
  "finance.accounts.updated": "Account updated",
  "finance.accounts.saveError": "Could not save the account",
  "finance.accounts.codeInvalid": "1 to 10 digits, not starting with 0",
  "finance.accounts.column.code": "Number",
  "finance.accounts.column.name": "Name",
  "finance.accounts.column.type": "Type",
  "finance.accounts.column.postable": "Posting",
  "finance.accounts.column.parent": "Parent",
  "finance.accounts.postable": "Postable",
  "finance.accounts.heading": "Heading",
  "finance.accounts.postableHint": "Entries can be posted to this account (untick for a heading)",
  "finance.accounts.classShort": "Class",
  "finance.accounts.emptyTitle": "No accounts yet",
  "finance.accounts.emptyDescription": "Install the SYSCOHADA chart to start.",
  "finance.accounts.type.asset": "Asset",
  "finance.accounts.type.liability": "Liability",
  "finance.accounts.type.equity": "Equity",
  "finance.accounts.type.income": "Income",
  "finance.accounts.type.expense": "Expense",
  "finance.rules.title": "Posting rules",
  "finance.rules.subtitle": "Which accounts a payroll line or an invoice is posted to. \"*\" covers every code of its kind that has no rule of its own.",
  "finance.rules.tableTitle": "Rules",
  "finance.rules.new": "New rule",
  "finance.rules.newTitle": "New posting rule",
  "finance.rules.editTitle": "Edit posting rule",
  "finance.rules.dialogDescription": "A rule posts to a debit account, a credit account, or both. Payment and invoice rules need both and a journal. Any change sends the rule back to confirmation.",
  "finance.rules.toConfirmBanner": "rule(s) still to be confirmed by the accountant. Postings already use them; confirm each one once checked.",
  "finance.rules.anyCode": "* (any)",
  "finance.rules.confirm": "Confirm",
  "finance.rules.confirmed": "Rule confirmed",
  "finance.rules.confirmError": "Could not confirm the rule",
  "finance.rules.created": "Rule created",
  "finance.rules.updated": "Rule updated",
  "finance.rules.saveError": "Could not save the rule",
  "finance.rules.needsAccount": "Choose a debit or a credit account",
  "finance.rules.emptyTitle": "No posting rules",
  "finance.rules.emptyDescription": "Install the SYSCOHADA chart from the chart of accounts to get the default rules.",
  "finance.rules.column.source": "Source",
  "finance.rules.column.kind": "Kind",
  "finance.rules.column.code": "Code",
  "finance.rules.column.debit": "Debit",
  "finance.rules.column.credit": "Credit",
  "finance.rules.column.journal": "Journal",
  "finance.rules.column.status": "Status",
  "finance.rules.source.payroll": "Payroll",
  "finance.rules.source.invoice": "Invoices",
  "finance.rules.status.to_confirm": "To confirm",
  "finance.rules.status.confirmed": "Confirmed",
  "finance.rules.kind.earning": "Earning",
  "finance.rules.kind.deduction": "Deduction",
  "finance.rules.kind.employee_contribution": "Employee contribution",
  "finance.rules.kind.employer_contribution": "Employer contribution",
  "finance.rules.kind.employer_charge": "Employer tax",
  "finance.rules.kind.tax": "Income tax (ITS)",
  "finance.rules.kind.net": "Net pay",
  "finance.rules.kind.payment": "Payment",
  "finance.rules.kind.issued": "Invoice issued",
  "finance.rules.kind.paid": "Invoice paid",
  "finance.entries.status.draft": "Draft",
  "finance.entries.status.posted": "Posted",
  "finance.entries.status.reversed": "Reversed",
```

and at the end of the `fr` object (just before the `};` that precedes `const dictionaries`):

```ts
  "nav.accounting": "Comptabilité",
  "nav.chartOfAccounts": "Plan comptable",
  "nav.postingRules": "Règles d'imputation",
  "finance.accounts.title": "Plan comptable",
  "finance.accounts.subtitle": "Comptes SYSCOHADA. Les comptes de regroupement rassemblent les comptes imputables.",
  "finance.accounts.tableTitle": "Comptes",
  "finance.accounts.new": "Nouveau compte",
  "finance.accounts.newTitle": "Nouveau compte",
  "finance.accounts.editTitle": "Modifier le compte",
  "finance.accounts.dialogDescription": "Le numéro commence par le chiffre de sa classe et prolonge celui de son parent. Il ne change plus une fois créé.",
  "finance.accounts.setup": "Installer le plan SYSCOHADA",
  "finance.accounts.setupDone": "Plan SYSCOHADA, journaux et règles d'imputation par défaut installés",
  "finance.accounts.setupError": "Impossible d'installer le plan comptable",
  "finance.accounts.created": "Compte créé",
  "finance.accounts.updated": "Compte modifié",
  "finance.accounts.saveError": "Impossible d'enregistrer le compte",
  "finance.accounts.codeInvalid": "1 à 10 chiffres, sans commencer par 0",
  "finance.accounts.column.code": "Numéro",
  "finance.accounts.column.name": "Intitulé",
  "finance.accounts.column.type": "Nature",
  "finance.accounts.column.postable": "Imputation",
  "finance.accounts.column.parent": "Parent",
  "finance.accounts.postable": "Imputable",
  "finance.accounts.heading": "Regroupement",
  "finance.accounts.postableHint": "Des écritures peuvent être passées sur ce compte (décochez pour un compte de regroupement)",
  "finance.accounts.classShort": "Classe",
  "finance.accounts.emptyTitle": "Aucun compte",
  "finance.accounts.emptyDescription": "Installez le plan SYSCOHADA pour commencer.",
  "finance.accounts.type.asset": "Actif",
  "finance.accounts.type.liability": "Passif",
  "finance.accounts.type.equity": "Capitaux propres",
  "finance.accounts.type.income": "Produit",
  "finance.accounts.type.expense": "Charge",
  "finance.rules.title": "Règles d'imputation",
  "finance.rules.subtitle": "Sur quels comptes une ligne de paie ou une facture est comptabilisée. « * » couvre chaque code de son type qui n'a pas sa propre règle.",
  "finance.rules.tableTitle": "Règles",
  "finance.rules.new": "Nouvelle règle",
  "finance.rules.newTitle": "Nouvelle règle d'imputation",
  "finance.rules.editTitle": "Modifier la règle d'imputation",
  "finance.rules.dialogDescription": "Une règle impute un compte au débit, au crédit, ou les deux. Les règles de paiement et de facture demandent les deux et un journal. Toute modification renvoie la règle à confirmer.",
  "finance.rules.toConfirmBanner": "règle(s) encore à confirmer par le comptable. Les imputations les utilisent déjà ; confirmez chacune une fois vérifiée.",
  "finance.rules.anyCode": "* (tous)",
  "finance.rules.confirm": "Confirmer",
  "finance.rules.confirmed": "Règle confirmée",
  "finance.rules.confirmError": "Impossible de confirmer la règle",
  "finance.rules.created": "Règle créée",
  "finance.rules.updated": "Règle modifiée",
  "finance.rules.saveError": "Impossible d'enregistrer la règle",
  "finance.rules.needsAccount": "Choisissez un compte au débit ou au crédit",
  "finance.rules.emptyTitle": "Aucune règle d'imputation",
  "finance.rules.emptyDescription": "Installez le plan SYSCOHADA depuis le plan comptable pour obtenir les règles par défaut.",
  "finance.rules.column.source": "Source",
  "finance.rules.column.kind": "Type",
  "finance.rules.column.code": "Code",
  "finance.rules.column.debit": "Débit",
  "finance.rules.column.credit": "Crédit",
  "finance.rules.column.journal": "Journal",
  "finance.rules.column.status": "Statut",
  "finance.rules.source.payroll": "Paie",
  "finance.rules.source.invoice": "Factures",
  "finance.rules.status.to_confirm": "À confirmer",
  "finance.rules.status.confirmed": "Confirmée",
  "finance.rules.kind.earning": "Gain",
  "finance.rules.kind.deduction": "Retenue",
  "finance.rules.kind.employee_contribution": "Cotisation salariale",
  "finance.rules.kind.employer_contribution": "Cotisation patronale",
  "finance.rules.kind.employer_charge": "Taxe patronale",
  "finance.rules.kind.tax": "Impôt sur salaire (ITS)",
  "finance.rules.kind.net": "Net à payer",
  "finance.rules.kind.payment": "Paiement",
  "finance.rules.kind.issued": "Facture émise",
  "finance.rules.kind.paid": "Facture réglée",
  "finance.entries.status.draft": "Brouillon",
  "finance.entries.status.posted": "Comptabilisée",
  "finance.entries.status.reversed": "Extournée",
```

- [ ] **Step 7: Type-check**

Run (from `frontend/`): `npx tsc -b --force`
Expected: no errors.

- [ ] **Step 8: Check the two screens in the browser**

Give the demo user the ledger permissions and the SYSCOHADA seed on the dev database (the seed script of Task 15 does the same idempotently), from `backend/`:

```bash
PYTHONUTF8=1 .venv/Scripts/python - <<'EOF'
from dotenv import load_dotenv
load_dotenv("../.env")
from core.db import get_connection
from modules.finance.api.chart_setup_service import ChartSetupService

PERMISSIONS = [
    "finance.view_ledger", "finance.manage_entries", "finance.admin_entries", "finance.manage_accounts",
    "finance.admin_accounts", "finance.admin_periods", "finance.manage_posting_rules",
]
with get_connection() as connection:
    user_id, tenant_id = connection.execute(
        "SELECT id, tenant_id FROM core.users WHERE email = 'demo@sonalim-erp.local'"
    ).fetchone()
    for permission in PERMISSIONS:
        connection.execute(
            "INSERT INTO core.user_permissions (user_id, permission) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (user_id, permission),
        )
    print(ChartSetupService(connection).ensure_defaults(tenant_id=tenant_id, actor_id=user_id))
    connection.commit()
EOF
```

Start the API and `npm run dev`, log in again as `demo@sonalim-erp.local` / `demo1234` (the session carries the permissions granted at login) and check, in English then in French: the "Accounting" group shows Chart of accounts and Posting rules; `/finance` (Invoices) is no longer highlighted on those pages; the class pills and the column filters narrow the accounts; editing 571's name saves and the number field is read-only; the posting rules list shows the "to confirm" banner, confirming one removes it from the count, editing a rule brings it back.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/features/finance/ledgerApi.ts frontend/src/features/finance/ledgerFormat.ts frontend/src/features/finance/LedgerTable.tsx frontend/src/features/finance/AccountsPage.tsx frontend/src/features/finance/PostingRulesPage.tsx frontend/src/routes/router.tsx frontend/src/routes/Sidebar.tsx frontend/src/lib/i18n.tsx
git commit -m "feat(finance): chart of accounts and posting rules screens

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12: Journal entries screen (journal listing, manual OD entries, refused postings)

**Files:**
- Create: `frontend/src/features/finance/EntriesPage.tsx`
- Modify: `frontend/src/routes/router.tsx` (one route)
- Modify: `frontend/src/routes/Sidebar.tsx` (the "Accounting" group)
- Modify: `frontend/src/lib/i18n.tsx`

**Interfaces:**
- Consumes (Task 11): `listEntries`, `getEntry`, `createEntry`, `updateEntry`, `deleteEntry`, `postEntry`, `reverseEntry`, `listJournals`, `listAccounts`, `listPostingFailures`, `retryPostingFailure`, `LEDGER_KEYS`, `invalidateLedgerData`, types; `LedgerTable`, `textFilter`, `rangeFilter`, `EntryStatusBadge`; `formatAmount`, `formatAmountCell`, `formatDate`, `todayIso`, `monthStartIso`, `monthEndIso`, `errorText`; `DateRangeFilter` (`components/patterns/DateRangeFilter.tsx`).
- Produces: `EntriesPage` at `/finance/entries`; the query string `?entry=<id>` opens that entry's detail (Tasks 13 and 14 link to it); `FAILURE_KIND_KEYS` and `failureMessage(failure, language)` exported for Task 14.

- [ ] **Step 1: Write the screen**

`frontend/src/features/finance/EntriesPage.tsx`:

```tsx
import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useFieldArray, useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen, Pencil, Plus, RotateCcw, Send, Trash2, TriangleAlert } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../lib/auth";
import { useI18n, type TranslationKey } from "../../lib/i18n";
import { useColumnFilters, type FilterField } from "../../lib/useColumnFilters";
import type { ColumnDef } from "../../lib/useTableColumns";
import { Button } from "../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../components/ui/dialog";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select } from "../../components/ui/select";
import { Skeleton } from "../../components/ui/skeleton";
import { DateRangeFilter } from "../../components/patterns/DateRangeFilter";
import { FilterTabs } from "../../components/patterns/FilterTabs";
import { EntryStatusBadge, LedgerTable, rangeFilter, textFilter } from "./LedgerTable";
import { errorText, formatAmount, formatAmountCell, formatDate, monthEndIso, monthStartIso, todayIso } from "./ledgerFormat";
import {
  LEDGER_KEYS,
  createEntry,
  deleteEntry,
  getEntry,
  invalidateLedgerData,
  listAccounts,
  listEntries,
  listJournals,
  listPostingFailures,
  postEntry,
  retryPostingFailure,
  reverseEntry,
  updateEntry,
  type EntryFilters,
  type EntryInput,
  type EntryStatus,
  type Journal,
  type JournalEntry,
  type JournalEntryDetail,
  type PostingFailure,
} from "./ledgerApi";

export const FAILURE_KIND_KEYS: Record<string, TranslationKey> = {
  payroll_run: "finance.failures.kind.payroll_run",
  payroll_payment: "finance.failures.kind.payroll_payment",
  payroll_reversal: "finance.failures.kind.payroll_reversal",
  invoice_issued: "finance.failures.kind.invoice_issued",
  invoice_paid: "finance.failures.kind.invoice_paid",
};

/** The refusal in the language the user picked (French falls back to English if none was stored). */
export function failureMessage(failure: PostingFailure, language: string): string {
  return language === "fr" && failure.error_message_fr ? failure.error_message_fr : failure.error_message;
}

type StatusFilter = "all" | EntryStatus;

export function EntriesPage() {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const [searchParams, setSearchParams] = useSearchParams();
  const defaultRange = { from: monthStartIso(), to: monthEndIso() };
  const [range, setRange] = useState(defaultRange);
  const [journalCode, setJournalCode] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [formEntry, setFormEntry] = useState<JournalEntryDetail | "new" | null>(null);
  const openEntryId = searchParams.get("entry");
  const filters: EntryFilters = { date_from: range.from, date_to: range.to, journal_code: journalCode || undefined };
  const { data: entries = [], isLoading } = useQuery({
    queryKey: LEDGER_KEYS.entryList(filters),
    queryFn: () => listEntries(token, filters),
  });
  const { data: journals = [] } = useQuery({ queryKey: LEDGER_KEYS.journals, queryFn: () => listJournals(token) });

  const openEntry = (id: string | null) => {
    const next = new URLSearchParams(searchParams);
    if (id) next.set("entry", id);
    else next.delete("entry");
    setSearchParams(next, { replace: true });
  };

  const fields: FilterField<JournalEntry>[] = [
    { key: "number", kind: "text", getValue: (entry) => entry.number ?? "" },
    { key: "label", kind: "text", getValue: (entry) => entry.label },
    { key: "reference", kind: "text", getValue: (entry) => entry.reference ?? "" },
    { key: "total_debit", kind: "range", getValue: (entry) => entry.total_debit },
  ];
  const columnFilters = useColumnFilters(fields);
  const rows = columnFilters.apply(statusFilter === "all" ? entries : entries.filter((entry) => entry.status === statusFilter));
  const total = rows.reduce((sum, entry) => sum + entry.total_debit, 0);

  const columns: ColumnDef<JournalEntry>[] = [
    {
      key: "entry_date",
      header: t("finance.entries.column.date"),
      defaultWidth: 110,
      cell: (entry) => formatDate(entry.entry_date),
      sortValue: (entry) => entry.entry_date,
    },
    {
      key: "number",
      header: t("finance.entries.column.number"),
      defaultWidth: 170,
      cell: (entry) => <span className="font-mono">{entry.number ?? "—"}</span>,
      filterCell: textFilter(columnFilters, "number", t("finance.entries.column.number")),
      sortValue: (entry) => entry.number ?? "",
    },
    {
      key: "journal_code",
      header: t("finance.entries.column.journal"),
      defaultWidth: 90,
      cell: (entry) => <span className="font-mono">{entry.journal_code}</span>,
      sortValue: (entry) => entry.journal_code,
    },
    {
      key: "label",
      header: t("finance.entries.column.label"),
      defaultWidth: 280,
      cell: (entry) => entry.label,
      filterCell: textFilter(columnFilters, "label", t("finance.entries.column.label")),
      sortValue: (entry) => entry.label,
    },
    {
      key: "reference",
      header: t("finance.entries.column.reference"),
      defaultWidth: 150,
      cell: (entry) => <span className="text-muted-foreground">{entry.reference ?? ""}</span>,
      filterCell: textFilter(columnFilters, "reference", t("finance.entries.column.reference")),
      sortValue: (entry) => entry.reference ?? "",
    },
    {
      key: "status",
      header: t("finance.entries.column.status"),
      defaultWidth: 130,
      cell: (entry) => <EntryStatusBadge status={entry.status} />,
      sortValue: (entry) => entry.status,
    },
    {
      key: "total_debit",
      header: t("finance.entries.column.amount"),
      defaultWidth: 150,
      headerClassName: "text-right",
      cellClassName: "text-right tabular-nums",
      cell: (entry) => formatAmount(entry.total_debit),
      filterCell: rangeFilter(columnFilters, "total_debit"),
      sortValue: (entry) => entry.total_debit,
    },
  ];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">{t("finance.entries.title")}</h1>
          <p className="text-sm text-muted-foreground">{t("finance.entries.subtitle")}</p>
        </div>
        {hasPermission("finance.manage_entries") && (
          <Button onClick={() => setFormEntry("new")}>
            <Plus className="h-4 w-4" />
            {t("finance.entries.new")}
          </Button>
        )}
      </div>
      <PostingFailuresCard />
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center gap-3">
            <CardTitle>{t("finance.entries.tableTitle")}</CardTitle>
            <DateRangeFilter
              from={range.from}
              to={range.to}
              onChange={setRange}
              onReset={() => setRange(defaultRange)}
              isDefault={range.from === defaultRange.from && range.to === defaultRange.to}
            />
            <div className="w-56">
              <Select value={journalCode} onChange={(event) => setJournalCode(event.target.value)} aria-label={t("finance.entries.column.journal")}>
                <option value="">{t("finance.entries.allJournals")}</option>
                {journals.map((journal) => (
                  <option key={journal.code} value={journal.code}>
                    {journal.code} · {journal.name}
                  </option>
                ))}
              </Select>
            </div>
          </div>
        </CardHeader>
        <CardContent className="p-0 pb-2">
          <LedgerTable
            tableKey="finance.entries"
            columns={columns}
            rows={rows}
            rowKey={(entry) => entry.id}
            isLoading={isLoading}
            emptyIcon={<BookOpen className="h-5 w-5" />}
            emptyTitle={t("finance.entries.emptyTitle")}
            emptyDescription={t("finance.entries.emptyDescription")}
            onRowClick={(entry) => openEntry(entry.id)}
            footer={(key) => (key === "label" ? t("finance.entries.total") : key === "total_debit" ? formatAmount(total) : "")}
            toolbar={
              <>
                <FilterTabs
                  value={statusFilter}
                  onChange={setStatusFilter}
                  options={[
                    { value: "all", label: t("common.all") },
                    { value: "draft", label: t("finance.entries.status.draft") },
                    { value: "posted", label: t("finance.entries.status.posted") },
                    { value: "reversed", label: t("finance.entries.status.reversed") },
                  ]}
                />
                {columnFilters.isActive && (
                  <Button variant="ghost" size="sm" onClick={columnFilters.reset}>
                    {t("common.clearFilters")}
                  </Button>
                )}
              </>
            }
          />
        </CardContent>
      </Card>
      {openEntryId && (
        <EntryDetailDialog
          entryId={openEntryId}
          onClose={() => openEntry(null)}
          onEdit={(entry) => {
            openEntry(null);
            setFormEntry(entry);
          }}
        />
      )}
      {formEntry !== null && (
        <EntryFormDialog entry={formEntry === "new" ? null : formEntry} journals={journals} onClose={() => setFormEntry(null)} />
      )}
    </div>
  );
}

function PostingFailuresCard() {
  const { session, hasPermission } = useAuth();
  const { t, language } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [moduleFilter, setModuleFilter] = useState<"all" | "payroll" | "finance">("all");
  const { data: failures = [], isLoading } = useQuery({ queryKey: LEDGER_KEYS.failures, queryFn: () => listPostingFailures(token) });
  const retryMutation = useMutation({
    mutationFn: (id: string) => retryPostingFailure(token, id),
    onSuccess: () => {
      invalidateLedgerData(queryClient);
      toast.success(t("finance.failures.retried"));
    },
    onError: (error) => toast.error(t("finance.failures.retryError"), { description: errorText(error) }),
  });
  const fields: FilterField<PostingFailure>[] = [
    { key: "source_id", kind: "text", getValue: (failure) => failure.source_id },
    { key: "message", kind: "text", getValue: (failure) => failureMessage(failure, language) },
  ];
  const columnFilters = useColumnFilters(fields);
  const rows = columnFilters.apply(
    moduleFilter === "all" ? failures : failures.filter((failure) => failure.source_module === moduleFilter),
  );
  const columns: ColumnDef<PostingFailure>[] = [
    {
      key: "failed_at",
      header: t("finance.failures.column.failedAt"),
      defaultWidth: 110,
      cell: (failure) => formatDate(failure.failed_at),
      sortValue: (failure) => failure.failed_at,
    },
    {
      key: "source_kind",
      header: t("finance.failures.column.kind"),
      defaultWidth: 170,
      cell: (failure) => (FAILURE_KIND_KEYS[failure.source_kind] ? t(FAILURE_KIND_KEYS[failure.source_kind]) : failure.source_kind),
      sortValue: (failure) => failure.source_kind,
    },
    {
      key: "source_id",
      header: t("finance.failures.column.source"),
      defaultWidth: 240,
      cell: (failure) => <span className="font-mono text-xs">{failure.source_id}</span>,
      filterCell: textFilter(columnFilters, "source_id", t("finance.failures.column.source")),
      sortValue: (failure) => failure.source_id,
    },
    {
      key: "message",
      header: t("finance.failures.column.reason"),
      defaultWidth: 380,
      cell: (failure) => failureMessage(failure, language),
      filterCell: textFilter(columnFilters, "message", t("finance.failures.column.reason")),
    },
    {
      key: "actions",
      header: t("finance.column.action"),
      defaultWidth: 120,
      alwaysVisible: true,
      headerClassName: "text-right",
      cell: (failure) =>
        hasPermission("finance.manage_entries") ? (
          <div className="flex justify-end">
            <Button size="sm" variant="outline" disabled={retryMutation.isPending} onClick={() => retryMutation.mutate(failure.id)}>
              <RotateCcw className="h-3.5 w-3.5" />
              {t("finance.failures.retry")}
            </Button>
          </div>
        ) : null,
    },
  ];
  if (!isLoading && failures.length === 0) return null;
  return (
    <Card className="border-destructive/30">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <TriangleAlert className="h-4 w-4 text-destructive" />
          {t("finance.failures.title")}
        </CardTitle>
        <p className="text-sm text-muted-foreground">{t("finance.failures.subtitle")}</p>
      </CardHeader>
      <CardContent className="p-0 pb-2">
        <LedgerTable
          tableKey="finance.postingFailures"
          columns={columns}
          rows={rows}
          rowKey={(failure) => failure.id}
          isLoading={isLoading}
          loading="skeleton"
          emptyIcon={<TriangleAlert className="h-5 w-5" />}
          emptyTitle={t("finance.failures.emptyTitle")}
          emptyDescription={t("finance.failures.emptyDescription")}
          toolbar={
            <>
              <FilterTabs
                value={moduleFilter}
                onChange={setModuleFilter}
                options={[
                  { value: "all", label: t("common.all") },
                  { value: "payroll", label: t("finance.rules.source.payroll") },
                  { value: "finance", label: t("finance.rules.source.invoice") },
                ]}
              />
              {columnFilters.isActive && (
                <Button variant="ghost" size="sm" onClick={columnFilters.reset}>
                  {t("common.clearFilters")}
                </Button>
              )}
            </>
          }
        />
      </CardContent>
    </Card>
  );
}

function EntryDetailDialog({
  entryId,
  onClose,
  onEdit,
}: {
  entryId: string;
  onClose: () => void;
  onEdit: (entry: JournalEntryDetail) => void;
}) {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [reverseDate, setReverseDate] = useState(todayIso());
  const { data: entry, isLoading } = useQuery({ queryKey: LEDGER_KEYS.entry(entryId), queryFn: () => getEntry(token, entryId) });
  const onError = (message: TranslationKey) => (error: unknown) => toast.error(t(message), { description: errorText(error) });
  const postMutation = useMutation({
    mutationFn: () => postEntry(token, entryId),
    onSuccess: () => {
      invalidateLedgerData(queryClient);
      toast.success(t("finance.entries.postedToast"));
    },
    onError: onError("finance.entries.postError"),
  });
  const deleteMutation = useMutation({
    mutationFn: () => deleteEntry(token, entryId),
    onSuccess: () => {
      invalidateLedgerData(queryClient);
      toast.success(t("finance.entries.deleted"));
      onClose();
    },
    onError: onError("finance.entries.deleteError"),
  });
  const reverseMutation = useMutation({
    mutationFn: () => reverseEntry(token, entryId, reverseDate),
    onSuccess: () => {
      invalidateLedgerData(queryClient);
      toast.success(t("finance.entries.reversedToast"));
    },
    onError: onError("finance.entries.reverseError"),
  });

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>
            {entry?.number ?? t("finance.entries.draftTitle")} {entry && <EntryStatusBadge status={entry.status} />}
          </DialogTitle>
          <DialogDescription>
            {entry ? `${entry.journal_code} · ${formatDate(entry.entry_date)} · ${entry.label}` : ""}
          </DialogDescription>
        </DialogHeader>
        {isLoading || !entry ? (
          <Skeleton className="h-40 w-full" />
        ) : (
          <div className="space-y-4">
            {entry.reference && (
              <p className="text-sm text-muted-foreground">
                {t("finance.entries.column.reference")} : {entry.reference}
              </p>
            )}
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-muted-foreground">
                  <th className="py-1.5">{t("finance.entries.line.account")}</th>
                  <th className="py-1.5">{t("finance.entries.line.label")}</th>
                  <th className="py-1.5 text-right">{t("finance.entries.line.debit")}</th>
                  <th className="py-1.5 text-right">{t("finance.entries.line.credit")}</th>
                </tr>
              </thead>
              <tbody>
                {entry.lines.map((line) => (
                  <tr key={line.line_no} className="border-b border-border/60">
                    <td className="py-1.5">
                      <span className="font-mono">{line.account_code}</span> {line.account_name}
                    </td>
                    <td className="py-1.5 text-muted-foreground">{[line.label, line.partner_name].filter(Boolean).join(" · ")}</td>
                    <td className="py-1.5 text-right tabular-nums">{formatAmountCell(line.debit)}</td>
                    <td className="py-1.5 text-right tabular-nums">{formatAmountCell(line.credit)}</td>
                  </tr>
                ))}
                <tr className="font-semibold">
                  <td className="py-1.5" colSpan={2}>
                    {t("finance.entries.total")}
                  </td>
                  <td className="py-1.5 text-right tabular-nums">{formatAmount(entry.total_debit)}</td>
                  <td className="py-1.5 text-right tabular-nums">{formatAmount(entry.total_credit)}</td>
                </tr>
              </tbody>
            </table>
            <div className="flex flex-wrap items-center justify-end gap-2">
              {entry.status === "draft" && hasPermission("finance.manage_entries") && (
                <Button variant="outline" disabled={deleteMutation.isPending} onClick={() => deleteMutation.mutate()}>
                  <Trash2 className="h-4 w-4" />
                  {t("common.delete")}
                </Button>
              )}
              {entry.status === "draft" && hasPermission("finance.admin_entries") && (
                <Button variant="outline" onClick={() => onEdit(entry)}>
                  <Pencil className="h-4 w-4" />
                  {t("common.edit")}
                </Button>
              )}
              {entry.status === "draft" && hasPermission("finance.manage_entries") && (
                <Button disabled={postMutation.isPending} onClick={() => postMutation.mutate()}>
                  <Send className="h-4 w-4" />
                  {t("finance.entries.post")}
                </Button>
              )}
              {entry.status === "posted" && hasPermission("finance.admin_entries") && (
                <>
                  <Label htmlFor="reverse_date" className="text-sm text-muted-foreground">
                    {t("finance.entries.reverseOn")}
                  </Label>
                  <Input
                    id="reverse_date"
                    type="date"
                    className="h-9 w-auto"
                    value={reverseDate}
                    onChange={(event) => setReverseDate(event.target.value)}
                  />
                  <Button variant="outline" disabled={reverseMutation.isPending} onClick={() => reverseMutation.mutate()}>
                    <RotateCcw className="h-4 w-4" />
                    {t("finance.entries.reverse")}
                  </Button>
                </>
              )}
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

const EMPTY_LINE = { account_code: "", debit: 0, credit: 0, label: "" };

function EntryFormDialog({ entry, journals, onClose }: { entry: JournalEntryDetail | null; journals: Journal[]; onClose: () => void }) {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const { data: accounts = [] } = useQuery({ queryKey: LEDGER_KEYS.accounts, queryFn: () => listAccounts(token) });
  const postable = accounts.filter((account) => account.is_postable);
  const schema = useMemo(
    () =>
      z.object({
        journal_code: z.string().min(1, t("common.required")),
        entry_date: z.string().min(1, t("common.required")),
        label: z.string().trim().min(1, t("common.required")),
        reference: z.string(),
        lines: z
          .array(
            z.object({
              account_code: z.string().min(1, t("common.required")),
              debit: z.coerce.number().int(t("common.wholeNumberOnly")).min(0),
              credit: z.coerce.number().int(t("common.wholeNumberOnly")).min(0),
              label: z.string(),
            }),
          )
          .min(2, t("finance.entries.needsTwoLines")),
      }),
    [t],
  );
  type EntryForm = z.infer<typeof schema>;
  const {
    register,
    control,
    handleSubmit,
    watch,
    formState: { errors },
  } = useForm<EntryForm>({
    resolver: zodResolver(schema),
    defaultValues: entry
      ? {
          journal_code: entry.journal_code,
          entry_date: entry.entry_date,
          label: entry.label,
          reference: entry.reference ?? "",
          lines: entry.lines.map((line) => ({
            account_code: line.account_code,
            debit: line.debit,
            credit: line.credit,
            label: line.label ?? "",
          })),
        }
      : { journal_code: "OD", entry_date: todayIso(), label: "", reference: "", lines: [EMPTY_LINE, EMPTY_LINE] },
  });
  const { fields, append, remove } = useFieldArray({ control, name: "lines" });
  const lines = watch("lines");
  const totalDebit = lines.reduce((sum, line) => sum + (Number(line.debit) || 0), 0);
  const totalCredit = lines.reduce((sum, line) => sum + (Number(line.credit) || 0), 0);

  const mutation = useMutation({
    mutationFn: (values: EntryForm) => {
      const input: EntryInput = {
        journal_code: values.journal_code,
        entry_date: values.entry_date,
        label: values.label,
        reference: values.reference || null,
        lines: values.lines.map((line) => ({
          account_code: line.account_code,
          debit: line.debit,
          credit: line.credit,
          label: line.label || null,
        })),
      };
      return entry ? updateEntry(token, entry.id, input) : createEntry(token, input);
    },
    onSuccess: () => {
      invalidateLedgerData(queryClient);
      toast.success(t(entry ? "finance.entries.updated" : "finance.entries.created"));
      onClose();
    },
    onError: (error) => toast.error(t("finance.entries.saveError"), { description: errorText(error) }),
  });

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-4xl">
        <DialogHeader>
          <DialogTitle>{t(entry ? "finance.entries.editTitle" : "finance.entries.newTitle")}</DialogTitle>
          <DialogDescription>{t("finance.entries.dialogDescription")}</DialogDescription>
        </DialogHeader>
        <form className="space-y-4" onSubmit={handleSubmit((values) => mutation.mutate(values))}>
          <div className="grid grid-cols-4 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="entry_journal">{t("finance.entries.column.journal")}</Label>
              <Select id="entry_journal" {...register("journal_code")}>
                {journals.map((journal) => (
                  <option key={journal.code} value={journal.code}>
                    {journal.code} · {journal.name}
                  </option>
                ))}
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="entry_date">{t("finance.entries.column.date")}</Label>
              <Input id="entry_date" type="date" {...register("entry_date")} />
              {errors.entry_date && <p className="text-sm text-destructive">{errors.entry_date.message}</p>}
            </div>
            <div className="col-span-2 space-y-1.5">
              <Label htmlFor="entry_label">{t("finance.entries.column.label")}</Label>
              <Input id="entry_label" {...register("label")} />
              {errors.label && <p className="text-sm text-destructive">{errors.label.message}</p>}
            </div>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="entry_reference">{t("finance.entries.column.reference")}</Label>
            <Input id="entry_reference" {...register("reference")} />
          </div>
          <div className="space-y-2">
            {fields.map((field, index) => (
              <div key={field.id} className="grid grid-cols-12 items-start gap-2">
                <div className="col-span-4">
                  <Select aria-label={t("finance.entries.line.account")} {...register(`lines.${index}.account_code` as const)}>
                    <option value="">{t("finance.entries.line.account")}</option>
                    {postable.map((account) => (
                      <option key={account.code} value={account.code}>
                        {account.code} · {account.name}
                      </option>
                    ))}
                  </Select>
                  {errors.lines?.[index]?.account_code && (
                    <p className="text-xs text-destructive">{errors.lines[index]?.account_code?.message}</p>
                  )}
                </div>
                <Input className="col-span-3" placeholder={t("finance.entries.line.label")} {...register(`lines.${index}.label` as const)} />
                <Input
                  className="col-span-2 text-right"
                  type="number"
                  min={0}
                  step={1}
                  placeholder={t("finance.entries.line.debit")}
                  {...register(`lines.${index}.debit` as const)}
                />
                <Input
                  className="col-span-2 text-right"
                  type="number"
                  min={0}
                  step={1}
                  placeholder={t("finance.entries.line.credit")}
                  {...register(`lines.${index}.credit` as const)}
                />
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="col-span-1"
                  onClick={() => remove(index)}
                  aria-label={t("common.delete")}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              </div>
            ))}
            {errors.lines?.message && <p className="text-sm text-destructive">{errors.lines.message}</p>}
            <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
              <Button type="button" variant="outline" size="sm" onClick={() => append({ ...EMPTY_LINE })}>
                <Plus className="h-3.5 w-3.5" />
                {t("finance.entries.addLine")}
              </Button>
              <span className={totalDebit === totalCredit ? "text-muted-foreground" : "font-medium text-warning"}>
                {t("finance.entries.line.debit")} {formatAmount(totalDebit)} · {t("finance.entries.line.credit")}{" "}
                {formatAmount(totalCredit)}
                {totalDebit !== totalCredit && ` · ${t("finance.entries.difference")} ${formatAmount(Math.abs(totalDebit - totalCredit))}`}
              </span>
            </div>
          </div>
          <Button type="submit" className="w-full" disabled={mutation.isPending}>
            {mutation.isPending ? t("common.saving") : t("finance.entries.saveDraft")}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
```

- [ ] **Step 2: Wire the route and the sidebar**

`frontend/src/routes/router.tsx` — import `import { EntriesPage } from "../features/finance/EntriesPage";` and add after the `/finance/accounts` route:

```tsx
  { path: "/finance/entries", element: <EntriesPage /> },
```

`frontend/src/routes/Sidebar.tsx` — add `BookOpen` to the `lucide-react` import and replace the `nav.accounting` group with:

```tsx
  {
    labelKey: "nav.accounting",
    items: [
      { to: "/finance/entries", labelKey: "nav.ledgerEntries", icon: BookOpen, permission: "finance.view_ledger" },
      { to: "/finance/accounts", labelKey: "nav.chartOfAccounts", icon: ListTree, permission: "finance.view_ledger" },
      { to: "/finance/posting-rules", labelKey: "nav.postingRules", icon: GitBranch, permission: "finance.view_ledger" },
    ],
  },
```

- [ ] **Step 3: Add the strings**

End of the `en` object (`finance.column.action` already exists — the Invoices page uses it — so it is not added again):

```ts
  "nav.ledgerEntries": "Journal entries",
  "finance.entries.title": "Journal entries",
  "finance.entries.subtitle": "Every entry of the ledger, by journal. Payroll and invoices post here on their own; manual entries go through a draft.",
  "finance.entries.tableTitle": "Entries",
  "finance.entries.allJournals": "All journals",
  "finance.entries.new": "New entry",
  "finance.entries.newTitle": "New manual entry",
  "finance.entries.editTitle": "Edit draft entry",
  "finance.entries.draftTitle": "Draft entry",
  "finance.entries.dialogDescription": "Saved as a draft; it counts in no report until it is posted. Debits must equal credits to post.",
  "finance.entries.saveDraft": "Save draft",
  "finance.entries.addLine": "Add line",
  "finance.entries.difference": "difference",
  "finance.entries.needsTwoLines": "An entry needs at least two lines",
  "finance.entries.total": "Total",
  "finance.entries.post": "Post",
  "finance.entries.reverse": "Reverse",
  "finance.entries.reverseOn": "Reversal date",
  "finance.entries.created": "Draft saved",
  "finance.entries.updated": "Draft updated",
  "finance.entries.saveError": "Could not save the entry",
  "finance.entries.postedToast": "Entry posted",
  "finance.entries.postError": "Could not post the entry",
  "finance.entries.deleted": "Draft deleted",
  "finance.entries.deleteError": "Could not delete the draft",
  "finance.entries.reversedToast": "Entry reversed",
  "finance.entries.reverseError": "Could not reverse the entry",
  "finance.entries.emptyTitle": "No entries in this range",
  "finance.entries.emptyDescription": "Change the dates or the journal, or write a manual entry.",
  "finance.entries.column.date": "Date",
  "finance.entries.column.number": "Number",
  "finance.entries.column.journal": "Journal",
  "finance.entries.column.label": "Label",
  "finance.entries.column.reference": "Reference",
  "finance.entries.column.status": "Status",
  "finance.entries.column.amount": "Amount (F CFA)",
  "finance.entries.line.account": "Account",
  "finance.entries.line.label": "Line label",
  "finance.entries.line.debit": "Debit",
  "finance.entries.line.credit": "Credit",
  "finance.failures.title": "Postings refused",
  "finance.failures.subtitle": "Automatic postings the ledger refused. Fix the cause (reopen the period, add the rule), then retry.",
  "finance.failures.retry": "Retry",
  "finance.failures.retried": "Posted",
  "finance.failures.retryError": "Still refused",
  "finance.failures.emptyTitle": "Nothing refused",
  "finance.failures.emptyDescription": "Every automatic posting went through.",
  "finance.failures.column.failedAt": "Refused on",
  "finance.failures.column.kind": "Posting",
  "finance.failures.column.source": "Source",
  "finance.failures.column.reason": "Reason",
  "finance.failures.kind.payroll_run": "Payroll run",
  "finance.failures.kind.payroll_payment": "Payroll payment",
  "finance.failures.kind.payroll_reversal": "Payroll reversal",
  "finance.failures.kind.invoice_issued": "Invoice issued",
  "finance.failures.kind.invoice_paid": "Invoice paid",
```

End of the `fr` object:

```ts
  "nav.ledgerEntries": "Écritures",
  "finance.entries.title": "Écritures comptables",
  "finance.entries.subtitle": "Toutes les écritures du grand livre, par journal. La paie et les factures s'y comptabilisent seules ; les écritures manuelles passent par un brouillon.",
  "finance.entries.tableTitle": "Écritures",
  "finance.entries.allJournals": "Tous les journaux",
  "finance.entries.new": "Nouvelle écriture",
  "finance.entries.newTitle": "Nouvelle écriture manuelle",
  "finance.entries.editTitle": "Modifier le brouillon",
  "finance.entries.draftTitle": "Brouillon d'écriture",
  "finance.entries.dialogDescription": "Enregistrée en brouillon ; elle ne compte dans aucun état avant d'être comptabilisée. Les débits doivent égaler les crédits pour comptabiliser.",
  "finance.entries.saveDraft": "Enregistrer le brouillon",
  "finance.entries.addLine": "Ajouter une ligne",
  "finance.entries.difference": "écart",
  "finance.entries.needsTwoLines": "Une écriture compte au moins deux lignes",
  "finance.entries.total": "Total",
  "finance.entries.post": "Comptabiliser",
  "finance.entries.reverse": "Extourner",
  "finance.entries.reverseOn": "Date d'extourne",
  "finance.entries.created": "Brouillon enregistré",
  "finance.entries.updated": "Brouillon modifié",
  "finance.entries.saveError": "Impossible d'enregistrer l'écriture",
  "finance.entries.postedToast": "Écriture comptabilisée",
  "finance.entries.postError": "Impossible de comptabiliser l'écriture",
  "finance.entries.deleted": "Brouillon supprimé",
  "finance.entries.deleteError": "Impossible de supprimer le brouillon",
  "finance.entries.reversedToast": "Écriture extournée",
  "finance.entries.reverseError": "Impossible d'extourner l'écriture",
  "finance.entries.emptyTitle": "Aucune écriture sur cette période",
  "finance.entries.emptyDescription": "Changez les dates ou le journal, ou passez une écriture manuelle.",
  "finance.entries.column.date": "Date",
  "finance.entries.column.number": "Numéro",
  "finance.entries.column.journal": "Journal",
  "finance.entries.column.label": "Libellé",
  "finance.entries.column.reference": "Référence",
  "finance.entries.column.status": "Statut",
  "finance.entries.column.amount": "Montant (F CFA)",
  "finance.entries.line.account": "Compte",
  "finance.entries.line.label": "Libellé de ligne",
  "finance.entries.line.debit": "Débit",
  "finance.entries.line.credit": "Crédit",
  "finance.failures.title": "Imputations refusées",
  "finance.failures.subtitle": "Imputations automatiques refusées par le grand livre. Corrigez la cause (rouvrir la période, ajouter la règle), puis relancez.",
  "finance.failures.retry": "Relancer",
  "finance.failures.retried": "Comptabilisée",
  "finance.failures.retryError": "Toujours refusée",
  "finance.failures.emptyTitle": "Aucun refus",
  "finance.failures.emptyDescription": "Toutes les imputations automatiques sont passées.",
  "finance.failures.column.failedAt": "Refusée le",
  "finance.failures.column.kind": "Imputation",
  "finance.failures.column.source": "Source",
  "finance.failures.column.reason": "Motif",
  "finance.failures.kind.payroll_run": "Paie",
  "finance.failures.kind.payroll_payment": "Règlement de paie",
  "finance.failures.kind.payroll_reversal": "Extourne de paie",
  "finance.failures.kind.invoice_issued": "Facture émise",
  "finance.failures.kind.invoice_paid": "Facture réglée",
```

- [ ] **Step 4: Type-check**

Run (from `frontend/`): `npx tsc -b --force`
Expected: no errors.

- [ ] **Step 5: Check the screen in the browser**

With the API and `npm run dev` running and the demo user logged in again (permissions from Task 11 Step 8): write a draft OD entry 641 / 521 for 150 000 with the two sides unequal — the form shows the difference and "Post" is refused with the bilingual `ENTRY_UNBALANCED` message; edit it to balance, post it (a number `OD-<year>-000001` appears); reverse it; filter by journal, status, number and amount; switch to French and check every label. Open `/finance/entries?entry=<id>` directly: the detail opens.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/finance/EntriesPage.tsx frontend/src/routes/router.tsx frontend/src/routes/Sidebar.tsx frontend/src/lib/i18n.tsx
git commit -m "feat(finance): journal entries screen with manual entries and refused postings

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 13: Trial balance (with 42x/43x/44x balances), General ledger and Periods screens

**Files:**
- Create: `frontend/src/features/finance/TrialBalancePage.tsx`
- Create: `frontend/src/features/finance/GeneralLedgerPage.tsx`
- Create: `frontend/src/features/finance/PeriodsPage.tsx`
- Modify: `frontend/src/routes/router.tsx` (three routes)
- Modify: `frontend/src/routes/Sidebar.tsx` (the "Accounting" group, final form)
- Modify: `frontend/src/lib/i18n.tsx`

**Interfaces:**
- Consumes (Task 11): `getTrialBalance`, `getBalances`, `getGeneralLedger`, `listAccounts`, `listPeriods`, `openFiscalYear`, `closePeriod`, `reopenPeriod`, `LEDGER_KEYS`, `invalidateLedgerData`, types; `LedgerTable`, `textFilter`, `rangeFilter`; format helpers incl. `yearStartIso`, `formatMonth`; `DateRangeFilter`. Task 12's `/finance/entries?entry=<id>` deep link.
- Produces: `TrialBalancePage` (`/finance/trial-balance`), `GeneralLedgerPage` (`/finance/ledger`, query `?account=&from=&to=`), `PeriodsPage` (`/finance/periods`).

- [ ] **Step 1: Write the trial balance screen**

`frontend/src/features/finance/TrialBalancePage.tsx`:

```tsx
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Scale } from "lucide-react";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import { useColumnFilters, type FilterField } from "../../lib/useColumnFilters";
import type { ColumnDef } from "../../lib/useTableColumns";
import { Button } from "../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { DateRangeFilter } from "../../components/patterns/DateRangeFilter";
import { FilterTabs } from "../../components/patterns/FilterTabs";
import { LedgerTable, rangeFilter, textFilter } from "./LedgerTable";
import { formatAmount, formatAmountCell, monthEndIso, yearStartIso } from "./ledgerFormat";
import {
  LEDGER_KEYS,
  getBalances,
  getTrialBalance,
  type AccountBalance,
  type TrialBalanceAmounts,
  type TrialBalanceRow,
} from "./ledgerApi";

const AMOUNT_KEYS: (keyof TrialBalanceAmounts)[] = [
  "opening_debit",
  "opening_credit",
  "period_debit",
  "period_credit",
  "closing_debit",
  "closing_credit",
];

export function TrialBalancePage() {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const navigate = useNavigate();
  const defaultRange = { from: yearStartIso(), to: monthEndIso() };
  const [range, setRange] = useState(defaultRange);
  const [classFilter, setClassFilter] = useState<string>("all");
  const { data, isLoading } = useQuery({
    queryKey: LEDGER_KEYS.trialBalance(range.from, range.to),
    queryFn: () => getTrialBalance(token, range.from, range.to),
  });
  const allRows = data?.rows ?? [];
  const classes = [...new Set(allRows.map((row) => String(row.class_no)))].sort();

  const fields: FilterField<TrialBalanceRow>[] = [
    { key: "account_code", kind: "text", getValue: (row) => row.account_code },
    { key: "account_name", kind: "text", getValue: (row) => row.account_name },
    { key: "closing_debit", kind: "range", getValue: (row) => row.closing_debit },
    { key: "closing_credit", kind: "range", getValue: (row) => row.closing_credit },
  ];
  const columnFilters = useColumnFilters(fields);
  const rows = columnFilters.apply(classFilter === "all" ? allRows : allRows.filter((row) => String(row.class_no) === classFilter));
  // Totals of the rows shown, so a filtered view still adds up; unfiltered they equal the server's totals.
  const totals = Object.fromEntries(AMOUNT_KEYS.map((key) => [key, rows.reduce((sum, row) => sum + row[key], 0)])) as Record<
    keyof TrialBalanceAmounts,
    number
  >;

  const amountColumn = (key: keyof TrialBalanceAmounts, header: string, withFilter = false): ColumnDef<TrialBalanceRow> => ({
    key,
    header,
    defaultWidth: 130,
    headerClassName: "text-right",
    cellClassName: "text-right tabular-nums",
    cell: (row) => formatAmountCell(row[key]),
    filterCell: withFilter ? rangeFilter(columnFilters, key) : undefined,
    sortValue: (row) => row[key],
  });
  const columns: ColumnDef<TrialBalanceRow>[] = [
    {
      key: "account_code",
      header: t("finance.accounts.column.code"),
      defaultWidth: 110,
      cell: (row) => (
        <button
          type="button"
          className="font-mono text-primary hover:underline"
          onClick={() => navigate(`/finance/ledger?account=${row.account_code}&from=${range.from}&to=${range.to}`)}
        >
          {row.account_code}
        </button>
      ),
      filterCell: textFilter(columnFilters, "account_code", t("finance.accounts.column.code")),
      sortValue: (row) => row.account_code,
    },
    {
      key: "account_name",
      header: t("finance.accounts.column.name"),
      defaultWidth: 280,
      cell: (row) => row.account_name,
      filterCell: textFilter(columnFilters, "account_name", t("finance.accounts.column.name")),
      sortValue: (row) => row.account_name,
    },
    amountColumn("opening_debit", t("finance.trialBalance.openingDebit")),
    amountColumn("opening_credit", t("finance.trialBalance.openingCredit")),
    amountColumn("period_debit", t("finance.trialBalance.periodDebit")),
    amountColumn("period_credit", t("finance.trialBalance.periodCredit")),
    amountColumn("closing_debit", t("finance.trialBalance.closingDebit"), true),
    amountColumn("closing_credit", t("finance.trialBalance.closingCredit"), true),
  ];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">{t("finance.trialBalance.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("finance.trialBalance.subtitle")}</p>
      </div>
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center gap-3">
            <CardTitle>{t("finance.trialBalance.tableTitle")}</CardTitle>
            <DateRangeFilter
              from={range.from}
              to={range.to}
              onChange={setRange}
              onReset={() => setRange(defaultRange)}
              isDefault={range.from === defaultRange.from && range.to === defaultRange.to}
            />
          </div>
        </CardHeader>
        <CardContent className="p-0 pb-2">
          <LedgerTable
            tableKey="finance.trialBalance"
            columns={columns}
            rows={rows}
            rowKey={(row) => row.account_code}
            isLoading={isLoading}
            emptyIcon={<Scale className="h-5 w-5" />}
            emptyTitle={t("finance.trialBalance.emptyTitle")}
            emptyDescription={t("finance.trialBalance.emptyDescription")}
            footer={(key) =>
              key === "account_name"
                ? t("finance.entries.total")
                : AMOUNT_KEYS.includes(key as keyof TrialBalanceAmounts)
                  ? formatAmount(totals[key as keyof TrialBalanceAmounts])
                  : ""
            }
            toolbar={
              <>
                <FilterTabs
                  value={classFilter}
                  onChange={setClassFilter}
                  options={[
                    { value: "all", label: t("common.all") },
                    ...classes.map((classNo) => ({ value: classNo, label: `${t("finance.accounts.classShort")} ${classNo}` })),
                  ]}
                />
                {columnFilters.isActive && (
                  <Button variant="ghost" size="sm" onClick={columnFilters.reset}>
                    {t("common.clearFilters")}
                  </Button>
                )}
              </>
            }
          />
        </CardContent>
      </Card>
      <BalancesCard asOf={range.to} />
    </div>
  );
}

const GROUPS = ["42", "43", "44"] as const;

function BalancesCard({ asOf }: { asOf: string }) {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const [group, setGroup] = useState<"all" | (typeof GROUPS)[number]>("all");
  const { data: balances = [], isLoading } = useQuery({ queryKey: LEDGER_KEYS.balances(asOf), queryFn: () => getBalances(token, asOf) });
  const fields: FilterField<AccountBalance>[] = [
    { key: "account_code", kind: "text", getValue: (row) => row.account_code },
    { key: "account_name", kind: "text", getValue: (row) => row.account_name },
    { key: "owed", kind: "range", getValue: (row) => row.owed },
  ];
  const columnFilters = useColumnFilters(fields);
  const rows = columnFilters.apply(group === "all" ? balances : balances.filter((row) => row.account_code.startsWith(group)));
  const columns: ColumnDef<AccountBalance>[] = [
    {
      key: "account_code",
      header: t("finance.accounts.column.code"),
      defaultWidth: 110,
      cell: (row) => <span className="font-mono">{row.account_code}</span>,
      filterCell: textFilter(columnFilters, "account_code", t("finance.accounts.column.code")),
      sortValue: (row) => row.account_code,
    },
    {
      key: "account_name",
      header: t("finance.accounts.column.name"),
      defaultWidth: 300,
      cell: (row) => row.account_name,
      filterCell: textFilter(columnFilters, "account_name", t("finance.accounts.column.name")),
      sortValue: (row) => row.account_name,
    },
    {
      key: "debit",
      header: t("finance.entries.line.debit"),
      defaultWidth: 130,
      headerClassName: "text-right",
      cellClassName: "text-right tabular-nums",
      cell: (row) => formatAmountCell(row.debit),
      sortValue: (row) => row.debit,
    },
    {
      key: "credit",
      header: t("finance.entries.line.credit"),
      defaultWidth: 130,
      headerClassName: "text-right",
      cellClassName: "text-right tabular-nums",
      cell: (row) => formatAmountCell(row.credit),
      sortValue: (row) => row.credit,
    },
    {
      key: "owed",
      header: t("finance.balances.owed"),
      defaultWidth: 150,
      headerClassName: "text-right",
      cellClassName: "text-right tabular-nums font-medium",
      cell: (row) => formatAmount(row.owed),
      filterCell: rangeFilter(columnFilters, "owed"),
      sortValue: (row) => row.owed,
    },
  ];
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("finance.balances.title")}</CardTitle>
        <p className="text-sm text-muted-foreground">{t("finance.balances.subtitle")}</p>
      </CardHeader>
      <CardContent className="p-0 pb-2">
        <LedgerTable
          tableKey="finance.balances"
          columns={columns}
          rows={rows}
          rowKey={(row) => row.account_code}
          isLoading={isLoading}
          loading="skeleton"
          emptyIcon={<Scale className="h-5 w-5" />}
          emptyTitle={t("finance.balances.emptyTitle")}
          emptyDescription={t("finance.balances.emptyDescription")}
          footer={(key) => (key === "account_name" ? t("finance.entries.total") : key === "owed" ? formatAmount(rows.reduce((sum, row) => sum + row.owed, 0)) : "")}
          toolbar={
            <>
              <FilterTabs
                value={group}
                onChange={setGroup}
                options={[
                  { value: "all", label: t("common.all") },
                  { value: "42", label: t("finance.balances.group42") },
                  { value: "43", label: t("finance.balances.group43") },
                  { value: "44", label: t("finance.balances.group44") },
                ]}
              />
              {columnFilters.isActive && (
                <Button variant="ghost" size="sm" onClick={columnFilters.reset}>
                  {t("common.clearFilters")}
                </Button>
              )}
            </>
          }
        />
      </CardContent>
    </Card>
  );
}
```

- [ ] **Step 2: Write the general ledger screen**

`frontend/src/features/finance/GeneralLedgerPage.tsx`:

```tsx
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { BookText } from "lucide-react";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import { useColumnFilters, type FilterField } from "../../lib/useColumnFilters";
import type { ColumnDef } from "../../lib/useTableColumns";
import { Button } from "../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Select } from "../../components/ui/select";
import { DateRangeFilter } from "../../components/patterns/DateRangeFilter";
import { EmptyState } from "../../components/patterns/EmptyState";
import { FilterTabs } from "../../components/patterns/FilterTabs";
import { LedgerTable, rangeFilter, textFilter } from "./LedgerTable";
import { formatAmount, formatAmountCell, formatDate, monthEndIso, yearStartIso } from "./ledgerFormat";
import { LEDGER_KEYS, getGeneralLedger, listAccounts, type GeneralLedgerLine } from "./ledgerApi";

export function GeneralLedgerPage() {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const [searchParams, setSearchParams] = useSearchParams();
  const defaultRange = { from: yearStartIso(), to: monthEndIso() };
  const account = searchParams.get("account") ?? "";
  const from = searchParams.get("from") ?? defaultRange.from;
  const to = searchParams.get("to") ?? defaultRange.to;
  const [journalFilter, setJournalFilter] = useState<string>("all");
  const setParams = (next: { account?: string; from?: string; to?: string }) => {
    const params = new URLSearchParams(searchParams);
    for (const [key, value] of Object.entries(next)) {
      if (value) params.set(key, value);
      else params.delete(key);
    }
    setSearchParams(params, { replace: true });
  };
  const { data: accounts = [] } = useQuery({ queryKey: LEDGER_KEYS.accounts, queryFn: () => listAccounts(token) });
  const { data: ledger, isLoading } = useQuery({
    queryKey: LEDGER_KEYS.generalLedger(account, from, to),
    queryFn: () => getGeneralLedger(token, account, from, to),
    enabled: account !== "",
  });
  const lines = ledger?.lines ?? [];
  const journalCodes = [...new Set(lines.map((line) => line.journal_code))].sort();
  const fields: FilterField<GeneralLedgerLine>[] = [
    { key: "number", kind: "text", getValue: (line) => line.number },
    { key: "label", kind: "text", getValue: (line) => line.label },
    { key: "debit", kind: "range", getValue: (line) => line.debit },
    { key: "credit", kind: "range", getValue: (line) => line.credit },
  ];
  const columnFilters = useColumnFilters(fields);
  const rows = columnFilters.apply(journalFilter === "all" ? lines : lines.filter((line) => line.journal_code === journalFilter));
  const columns: ColumnDef<GeneralLedgerLine>[] = [
    {
      key: "entry_date",
      header: t("finance.entries.column.date"),
      defaultWidth: 110,
      cell: (line) => formatDate(line.entry_date),
      sortValue: (line) => line.entry_date,
    },
    {
      key: "number",
      header: t("finance.entries.column.number"),
      defaultWidth: 170,
      cell: (line) => (
        <Link to={`/finance/entries?entry=${line.entry_id}`} className="font-mono text-primary hover:underline">
          {line.number}
        </Link>
      ),
      filterCell: textFilter(columnFilters, "number", t("finance.entries.column.number")),
      sortValue: (line) => line.number,
    },
    {
      key: "journal_code",
      header: t("finance.entries.column.journal"),
      defaultWidth: 90,
      cell: (line) => <span className="font-mono">{line.journal_code}</span>,
      sortValue: (line) => line.journal_code,
    },
    {
      key: "label",
      header: t("finance.entries.column.label"),
      defaultWidth: 280,
      cell: (line) => line.label,
      filterCell: textFilter(columnFilters, "label", t("finance.entries.column.label")),
      sortValue: (line) => line.label,
    },
    {
      key: "debit",
      header: t("finance.entries.line.debit"),
      defaultWidth: 130,
      headerClassName: "text-right",
      cellClassName: "text-right tabular-nums",
      cell: (line) => formatAmountCell(line.debit),
      filterCell: rangeFilter(columnFilters, "debit"),
      sortValue: (line) => line.debit,
    },
    {
      key: "credit",
      header: t("finance.entries.line.credit"),
      defaultWidth: 130,
      headerClassName: "text-right",
      cellClassName: "text-right tabular-nums",
      cell: (line) => formatAmountCell(line.credit),
      filterCell: rangeFilter(columnFilters, "credit"),
      sortValue: (line) => line.credit,
    },
    {
      key: "balance",
      header: t("finance.generalLedger.balance"),
      defaultWidth: 140,
      headerClassName: "text-right",
      cellClassName: "text-right tabular-nums",
      cell: (line) => formatAmount(line.balance),
    },
  ];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">{t("finance.generalLedger.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("finance.generalLedger.subtitle")}</p>
      </div>
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center gap-3">
            <div className="w-72">
              <Select value={account} onChange={(event) => setParams({ account: event.target.value })} aria-label={t("finance.generalLedger.account")}>
                <option value="">{t("finance.generalLedger.pickAccount")}</option>
                {accounts
                  .filter((candidate) => candidate.is_postable)
                  .map((candidate) => (
                    <option key={candidate.code} value={candidate.code}>
                      {candidate.code} · {candidate.name}
                    </option>
                  ))}
              </Select>
            </div>
            <DateRangeFilter
              from={from}
              to={to}
              onChange={(range) => setParams({ from: range.from, to: range.to })}
              onReset={() => setParams({ from: "", to: "" })}
              isDefault={from === defaultRange.from && to === defaultRange.to}
            />
          </div>
          {ledger && (
            <div className="grid grid-cols-2 gap-3 pt-3 text-sm sm:grid-cols-4">
              <div>
                <p className="text-muted-foreground">{t("finance.generalLedger.opening")}</p>
                <p className="font-semibold tabular-nums">{formatAmount(ledger.opening_balance)}</p>
              </div>
              <div>
                <p className="text-muted-foreground">{t("finance.generalLedger.totalDebit")}</p>
                <p className="font-semibold tabular-nums">{formatAmount(ledger.total_debit)}</p>
              </div>
              <div>
                <p className="text-muted-foreground">{t("finance.generalLedger.totalCredit")}</p>
                <p className="font-semibold tabular-nums">{formatAmount(ledger.total_credit)}</p>
              </div>
              <div>
                <p className="text-muted-foreground">{t("finance.generalLedger.closing")}</p>
                <p className="font-semibold tabular-nums">{formatAmount(ledger.closing_balance)}</p>
              </div>
            </div>
          )}
        </CardHeader>
        <CardContent className="p-0 pb-2">
          {account === "" ? (
            <EmptyState
              icon={<BookText className="h-5 w-5" />}
              title={t("finance.generalLedger.pickAccount")}
              description={t("finance.generalLedger.pickAccountHint")}
            />
          ) : (
            <LedgerTable
              tableKey="finance.generalLedger"
              columns={columns}
              rows={rows}
              rowKey={(line) => `${line.entry_id}-${line.number}-${line.debit}-${line.credit}-${line.balance}`}
              isLoading={isLoading}
              emptyIcon={<BookText className="h-5 w-5" />}
              emptyTitle={t("finance.generalLedger.emptyTitle")}
              emptyDescription={t("finance.generalLedger.emptyDescription")}
              toolbar={
                <>
                  <FilterTabs
                    value={journalFilter}
                    onChange={setJournalFilter}
                    options={[{ value: "all", label: t("common.all") }, ...journalCodes.map((code) => ({ value: code, label: code }))]}
                  />
                  {columnFilters.isActive && (
                    <Button variant="ghost" size="sm" onClick={columnFilters.reset}>
                      {t("common.clearFilters")}
                    </Button>
                  )}
                </>
              }
            />
          )}
        </CardContent>
      </Card>
    </div>
  );
}
```

- [ ] **Step 3: Write the periods screen**

`frontend/src/features/finance/PeriodsPage.tsx`:

```tsx
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarRange, Lock, LockOpen } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import { useColumnFilters, type FilterField } from "../../lib/useColumnFilters";
import type { ColumnDef } from "../../lib/useTableColumns";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Input } from "../../components/ui/input";
import { FilterTabs } from "../../components/patterns/FilterTabs";
import { LedgerTable, textFilter } from "./LedgerTable";
import { errorText, formatDate, formatMonth } from "./ledgerFormat";
import {
  LEDGER_KEYS,
  closePeriod,
  invalidateLedgerData,
  listPeriods,
  openFiscalYear,
  reopenPeriod,
  type AccountingPeriod,
  type PeriodStatus,
} from "./ledgerApi";

export function PeriodsPage() {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const canAdmin = hasPermission("finance.admin_periods");
  const [yearFilter, setYearFilter] = useState<string>("all");
  const [statusFilter, setStatusFilter] = useState<"all" | PeriodStatus>("all");
  const [newYear, setNewYear] = useState(String(new Date().getFullYear()));
  const { data: periods = [], isLoading } = useQuery({ queryKey: LEDGER_KEYS.periods, queryFn: () => listPeriods(token) });
  const years = [...new Set(periods.map((period) => String(period.year)))].sort().reverse();

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: LEDGER_KEYS.periods });
    invalidateLedgerData(queryClient);
  };
  const openYearMutation = useMutation({
    mutationFn: () => openFiscalYear(token, Number(newYear)),
    onSuccess: () => {
      refresh();
      toast.success(t("finance.periods.yearOpened"));
    },
    onError: (error) => toast.error(t("finance.periods.yearError"), { description: errorText(error) }),
  });
  const statusMutation = useMutation({
    mutationFn: ({ period, close }: { period: string; close: boolean }) =>
      close ? closePeriod(token, period) : reopenPeriod(token, period),
    onSuccess: (_, { close }) => {
      refresh();
      toast.success(t(close ? "finance.periods.closedToast" : "finance.periods.reopenedToast"));
    },
    onError: (error) => toast.error(t("finance.periods.statusError"), { description: errorText(error) }),
  });

  const fields: FilterField<AccountingPeriod>[] = [{ key: "period", kind: "text", getValue: (row) => formatMonth(row.period) }];
  const columnFilters = useColumnFilters(fields);
  const rows = columnFilters.apply(
    periods.filter(
      (row) => (yearFilter === "all" || String(row.year) === yearFilter) && (statusFilter === "all" || row.status === statusFilter),
    ),
  );
  const columns: ColumnDef<AccountingPeriod>[] = [
    {
      key: "period",
      header: t("finance.periods.column.period"),
      defaultWidth: 200,
      cell: (row) => <span className="capitalize">{formatMonth(row.period)}</span>,
      filterCell: textFilter(columnFilters, "period", t("finance.periods.column.period")),
      sortValue: (row) => row.period,
    },
    {
      key: "status",
      header: t("finance.periods.column.status"),
      defaultWidth: 130,
      cell: (row) =>
        row.status === "open" ? (
          <Badge variant="success">{t("finance.periods.status.open")}</Badge>
        ) : (
          <Badge>{t("finance.periods.status.closed")}</Badge>
        ),
      sortValue: (row) => row.status,
    },
    {
      key: "closed_at",
      header: t("finance.periods.column.closedAt"),
      defaultWidth: 140,
      cell: (row) => (row.closed_at ? formatDate(row.closed_at) : "—"),
      sortValue: (row) => row.closed_at ?? "",
    },
    {
      key: "actions",
      header: t("finance.column.action"),
      defaultWidth: 140,
      alwaysVisible: true,
      headerClassName: "text-right",
      cell: (row) =>
        canAdmin ? (
          <div className="flex justify-end">
            {row.status === "open" ? (
              <Button
                size="sm"
                variant="outline"
                disabled={statusMutation.isPending}
                onClick={() => {
                  if (window.confirm(t("finance.periods.closeConfirm"))) statusMutation.mutate({ period: row.period, close: true });
                }}
              >
                <Lock className="h-3.5 w-3.5" />
                {t("finance.periods.close")}
              </Button>
            ) : (
              <Button
                size="sm"
                variant="outline"
                disabled={statusMutation.isPending}
                onClick={() => statusMutation.mutate({ period: row.period, close: false })}
              >
                <LockOpen className="h-3.5 w-3.5" />
                {t("finance.periods.reopen")}
              </Button>
            )}
          </div>
        ) : null,
    },
  ];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">{t("finance.periods.title")}</h1>
          <p className="text-sm text-muted-foreground">{t("finance.periods.subtitle")}</p>
        </div>
        {canAdmin && (
          <div className="flex items-center gap-2">
            <Input
              type="number"
              min={2000}
              max={2100}
              className="h-9 w-24"
              value={newYear}
              onChange={(event) => setNewYear(event.target.value)}
              aria-label={t("finance.periods.year")}
            />
            <Button onClick={() => openYearMutation.mutate()} disabled={openYearMutation.isPending}>
              <CalendarRange className="h-4 w-4" />
              {t("finance.periods.openYear")}
            </Button>
          </div>
        )}
      </div>
      <Card>
        <CardHeader>
          <CardTitle>{t("finance.periods.tableTitle")}</CardTitle>
        </CardHeader>
        <CardContent className="p-0 pb-2">
          <LedgerTable
            tableKey="finance.periods"
            columns={columns}
            rows={rows}
            rowKey={(row) => row.period}
            isLoading={isLoading}
            emptyIcon={<CalendarRange className="h-5 w-5" />}
            emptyTitle={t("finance.periods.emptyTitle")}
            emptyDescription={t("finance.periods.emptyDescription")}
            toolbar={
              <>
                <FilterTabs
                  value={yearFilter}
                  onChange={setYearFilter}
                  options={[{ value: "all", label: t("common.all") }, ...years.map((year) => ({ value: year, label: year }))]}
                />
                <FilterTabs
                  value={statusFilter}
                  onChange={setStatusFilter}
                  options={[
                    { value: "all", label: t("common.all") },
                    { value: "open", label: t("finance.periods.status.open") },
                    { value: "closed", label: t("finance.periods.status.closed") },
                  ]}
                />
                {columnFilters.isActive && (
                  <Button variant="ghost" size="sm" onClick={columnFilters.reset}>
                    {t("common.clearFilters")}
                  </Button>
                )}
              </>
            }
          />
        </CardContent>
      </Card>
    </div>
  );
}
```

- [ ] **Step 4: Wire the routes and the final sidebar group**

`frontend/src/routes/router.tsx` — import the three pages from `../features/finance/TrialBalancePage`, `../features/finance/GeneralLedgerPage`, `../features/finance/PeriodsPage`, and add after the `/finance/entries` route:

```tsx
  { path: "/finance/trial-balance", element: <TrialBalancePage /> },
  { path: "/finance/ledger", element: <GeneralLedgerPage /> },
  { path: "/finance/periods", element: <PeriodsPage /> },
```

`frontend/src/routes/Sidebar.tsx` — add `Scale`, `BookText`, `CalendarRange` to the `lucide-react` import and replace the `nav.accounting` group with:

```tsx
  {
    labelKey: "nav.accounting",
    items: [
      { to: "/finance/entries", labelKey: "nav.ledgerEntries", icon: BookOpen, permission: "finance.view_ledger" },
      { to: "/finance/trial-balance", labelKey: "nav.trialBalance", icon: Scale, permission: "finance.view_ledger" },
      { to: "/finance/ledger", labelKey: "nav.generalLedger", icon: BookText, permission: "finance.view_ledger" },
      { to: "/finance/accounts", labelKey: "nav.chartOfAccounts", icon: ListTree, permission: "finance.view_ledger" },
      { to: "/finance/periods", labelKey: "nav.accountingPeriods", icon: CalendarRange, permission: "finance.view_ledger" },
      { to: "/finance/posting-rules", labelKey: "nav.postingRules", icon: GitBranch, permission: "finance.view_ledger" },
    ],
  },
```

- [ ] **Step 5: Add the strings**

End of the `en` object:

```ts
  "nav.trialBalance": "Trial balance",
  "nav.generalLedger": "General ledger",
  "nav.accountingPeriods": "Periods",
  "finance.trialBalance.title": "Trial balance",
  "finance.trialBalance.subtitle": "Posted entries only. Opening = everything booked before the range; a reversed entry and its reversal cancel out.",
  "finance.trialBalance.tableTitle": "Balance by account",
  "finance.trialBalance.openingDebit": "Opening debit",
  "finance.trialBalance.openingCredit": "Opening credit",
  "finance.trialBalance.periodDebit": "Debit",
  "finance.trialBalance.periodCredit": "Credit",
  "finance.trialBalance.closingDebit": "Closing debit",
  "finance.trialBalance.closingCredit": "Closing credit",
  "finance.trialBalance.emptyTitle": "Nothing posted up to this date",
  "finance.trialBalance.emptyDescription": "Widen the range, or post entries first.",
  "finance.balances.title": "Owed to staff, social bodies and the State",
  "finance.balances.subtitle": "Balances of accounts 42, 43 and 44 on the last day of the range (credit minus debit).",
  "finance.balances.owed": "Owed (F CFA)",
  "finance.balances.group42": "42 Staff",
  "finance.balances.group43": "43 Social bodies",
  "finance.balances.group44": "44 State",
  "finance.balances.emptyTitle": "No accounts 42, 43 or 44",
  "finance.balances.emptyDescription": "Install the SYSCOHADA chart from the chart of accounts.",
  "finance.generalLedger.title": "General ledger",
  "finance.generalLedger.subtitle": "Every posted line of one account, with its running balance (debit minus credit).",
  "finance.generalLedger.account": "Account",
  "finance.generalLedger.pickAccount": "Choose an account",
  "finance.generalLedger.pickAccountHint": "Pick an account, or open one from the trial balance.",
  "finance.generalLedger.balance": "Balance",
  "finance.generalLedger.opening": "Opening balance",
  "finance.generalLedger.totalDebit": "Total debit",
  "finance.generalLedger.totalCredit": "Total credit",
  "finance.generalLedger.closing": "Closing balance",
  "finance.generalLedger.emptyTitle": "No lines in this range",
  "finance.generalLedger.emptyDescription": "Nothing was posted to this account between these dates.",
  "finance.periods.title": "Accounting periods",
  "finance.periods.subtitle": "A fiscal year is a calendar year of twelve months. Nothing can be posted into a closed month.",
  "finance.periods.tableTitle": "Months",
  "finance.periods.year": "Year",
  "finance.periods.openYear": "Open fiscal year",
  "finance.periods.yearOpened": "Fiscal year opened",
  "finance.periods.yearError": "Could not open the fiscal year",
  "finance.periods.close": "Close",
  "finance.periods.reopen": "Reopen",
  "finance.periods.closeConfirm": "Close this month? Nothing can be posted into it until it is reopened.",
  "finance.periods.closedToast": "Month closed",
  "finance.periods.reopenedToast": "Month reopened",
  "finance.periods.statusError": "Could not change the month",
  "finance.periods.column.period": "Month",
  "finance.periods.column.status": "Status",
  "finance.periods.column.closedAt": "Closed on",
  "finance.periods.status.open": "Open",
  "finance.periods.status.closed": "Closed",
  "finance.periods.emptyTitle": "No fiscal year yet",
  "finance.periods.emptyDescription": "Open the current fiscal year to start posting.",
```

End of the `fr` object:

```ts
  "nav.trialBalance": "Balance générale",
  "nav.generalLedger": "Grand livre",
  "nav.accountingPeriods": "Périodes",
  "finance.trialBalance.title": "Balance générale",
  "finance.trialBalance.subtitle": "Écritures comptabilisées seulement. À-nouveau = tout ce qui est comptabilisé avant la période ; une écriture extournée et son extourne s'annulent.",
  "finance.trialBalance.tableTitle": "Solde par compte",
  "finance.trialBalance.openingDebit": "À-nouveau débit",
  "finance.trialBalance.openingCredit": "À-nouveau crédit",
  "finance.trialBalance.periodDebit": "Débit",
  "finance.trialBalance.periodCredit": "Crédit",
  "finance.trialBalance.closingDebit": "Solde débiteur",
  "finance.trialBalance.closingCredit": "Solde créditeur",
  "finance.trialBalance.emptyTitle": "Rien de comptabilisé jusqu'à cette date",
  "finance.trialBalance.emptyDescription": "Élargissez la période, ou comptabilisez d'abord des écritures.",
  "finance.balances.title": "Dû au personnel, aux organismes sociaux et à l'État",
  "finance.balances.subtitle": "Soldes des comptes 42, 43 et 44 au dernier jour de la période (crédit moins débit).",
  "finance.balances.owed": "Dû (F CFA)",
  "finance.balances.group42": "42 Personnel",
  "finance.balances.group43": "43 Organismes sociaux",
  "finance.balances.group44": "44 État",
  "finance.balances.emptyTitle": "Aucun compte 42, 43 ou 44",
  "finance.balances.emptyDescription": "Installez le plan SYSCOHADA depuis le plan comptable.",
  "finance.generalLedger.title": "Grand livre",
  "finance.generalLedger.subtitle": "Toutes les lignes comptabilisées d'un compte, avec le solde progressif (débit moins crédit).",
  "finance.generalLedger.account": "Compte",
  "finance.generalLedger.pickAccount": "Choisissez un compte",
  "finance.generalLedger.pickAccountHint": "Choisissez un compte, ou ouvrez-en un depuis la balance générale.",
  "finance.generalLedger.balance": "Solde",
  "finance.generalLedger.opening": "Solde d'ouverture",
  "finance.generalLedger.totalDebit": "Total débit",
  "finance.generalLedger.totalCredit": "Total crédit",
  "finance.generalLedger.closing": "Solde de clôture",
  "finance.generalLedger.emptyTitle": "Aucune ligne sur cette période",
  "finance.generalLedger.emptyDescription": "Rien n'a été comptabilisé sur ce compte entre ces dates.",
  "finance.periods.title": "Périodes comptables",
  "finance.periods.subtitle": "Un exercice est une année civile de douze mois. Rien ne peut être comptabilisé dans un mois clôturé.",
  "finance.periods.tableTitle": "Mois",
  "finance.periods.year": "Année",
  "finance.periods.openYear": "Ouvrir l'exercice",
  "finance.periods.yearOpened": "Exercice ouvert",
  "finance.periods.yearError": "Impossible d'ouvrir l'exercice",
  "finance.periods.close": "Clôturer",
  "finance.periods.reopen": "Rouvrir",
  "finance.periods.closeConfirm": "Clôturer ce mois ? Plus rien ne pourra y être comptabilisé avant sa réouverture.",
  "finance.periods.closedToast": "Mois clôturé",
  "finance.periods.reopenedToast": "Mois rouvert",
  "finance.periods.statusError": "Impossible de changer le mois",
  "finance.periods.column.period": "Mois",
  "finance.periods.column.status": "Statut",
  "finance.periods.column.closedAt": "Clôturé le",
  "finance.periods.status.open": "Ouvert",
  "finance.periods.status.closed": "Clôturé",
  "finance.periods.emptyTitle": "Aucun exercice",
  "finance.periods.emptyDescription": "Ouvrez l'exercice en cours pour commencer à comptabiliser.",
```

- [ ] **Step 6: Type-check**

Run (from `frontend/`): `npx tsc -b --force`
Expected: no errors.

- [ ] **Step 7: Check the screens in the browser**

Demo user logged in again (Task 11 Step 8). Periods: open the current year (12 open months), close this month, try to post a draft from the Entries screen — refused with "la période … est clôturée" in French — then reopen. Trial balance: the totals row has equal debit and credit columns, clicking an account number opens the general ledger on that account and range; the 42/43/44 card shows what is owed. General ledger: the running balance ends on the closing balance shown above the table; the entry number links back to the entry. Check each screen in English and French.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/features/finance/TrialBalancePage.tsx frontend/src/features/finance/GeneralLedgerPage.tsx frontend/src/features/finance/PeriodsPage.tsx frontend/src/routes/router.tsx frontend/src/routes/Sidebar.tsx frontend/src/lib/i18n.tsx
git commit -m "feat(finance): trial balance, general ledger and accounting periods screens

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 14: Posted / not posted on the payroll run page

**Files:**
- Create: `frontend/src/features/finance/LedgerPostingStatus.tsx`
- Modify: the payroll run page — the component phase 3 mounted at `/payroll/runs/:id` (find it with `grep -n "payroll/runs/:id" frontend/src/routes/router.tsx`; its file is in `frontend/src/features/payroll/`)
- Modify: `frontend/src/lib/i18n.tsx`

**Interfaces:**
- Consumes: `getSourcePostings`, `retryPostingFailure`, `LEDGER_KEYS.source`, `invalidateLedgerData` (Task 11), `EntryStatusBadge` (Task 11), `failureMessage` (Task 12), `formatDate`, `formatXof`, `errorText`; backend `GET /finance/ledger/sources/payroll/{run_id}` (Task 10, open to `finance.view_ledger` or `payroll.view_runs`), which returns `LedgerQueryService.entries_for_source` plus the source's posting failures.
- Produces: `LedgerPostingStatus({ runId, runStatus })` — renders nothing for runs that are not `approved`, `paid` or `reversed`, or for users with neither permission.

- [ ] **Step 1: Write the component**

`frontend/src/features/finance/LedgerPostingStatus.tsx`:

```tsx
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleCheck, Clock, RotateCcw, TriangleAlert } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../lib/auth";
import { useI18n, type TranslationKey } from "../../lib/i18n";
import { cn } from "../../lib/utils";
import { Button } from "../../components/ui/button";
import { Skeleton } from "../../components/ui/skeleton";
import { EntryStatusBadge } from "./LedgerTable";
import { failureMessage } from "./EntriesPage";
import { errorText, formatDate, formatXof } from "./ledgerFormat";
import { LEDGER_KEYS, getSourcePostings, invalidateLedgerData, retryPostingFailure } from "./ledgerApi";

/** Run statuses after which the ledger is expected to hold the run (the approval event posts it). */
const POSTED_RUN_STATUSES = ["approved", "paid", "reversed"];

type PostingState = "posted" | "pending" | "refused";

const STATE_KEYS: Record<PostingState, TranslationKey> = {
  posted: "finance.posting.state.posted",
  pending: "finance.posting.state.pending",
  refused: "finance.posting.state.refused",
};

/** What the ledger holds for one payroll run: its entries, or why they were refused. */
export function LedgerPostingStatus({ runId, runStatus }: { runId: string; runStatus: string }) {
  const { session, hasPermission } = useAuth();
  const { t, language } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const canRead = hasPermission("finance.view_ledger") || hasPermission("payroll.view_runs");
  const expected = POSTED_RUN_STATUSES.includes(runStatus);
  const { data, isLoading } = useQuery({
    queryKey: LEDGER_KEYS.source("payroll", runId),
    queryFn: () => getSourcePostings(token, "payroll", runId),
    enabled: canRead && expected,
  });
  const retryMutation = useMutation({
    mutationFn: (id: string) => retryPostingFailure(token, id),
    onSuccess: () => {
      invalidateLedgerData(queryClient);
      toast.success(t("finance.failures.retried"));
    },
    onError: (error) => toast.error(t("finance.failures.retryError"), { description: errorText(error) }),
  });

  if (!canRead || !expected) return null;
  if (isLoading || !data) return <Skeleton className="h-16 w-full" />;

  const openFailures = data.failures.filter((failure) => failure.status === "open");
  const booked = data.entries.filter((entry) => entry.status !== "draft");
  const state: PostingState = openFailures.length > 0 ? "refused" : booked.length > 0 ? "posted" : "pending";
  const Icon = state === "posted" ? CircleCheck : state === "refused" ? TriangleAlert : Clock;

  return (
    <div
      className={cn(
        "rounded-lg border p-4 text-sm",
        state === "posted" && "border-success/30 bg-success-soft",
        state === "refused" && "border-destructive/30 bg-destructive-soft",
        state === "pending" && "border-warning/30 bg-warning-soft",
      )}
    >
      <div className="flex items-center gap-2 font-medium">
        <Icon className="h-4 w-4" />
        {t(STATE_KEYS[state])}
      </div>
      {state === "pending" && <p className="mt-1 text-muted-foreground">{t("finance.posting.pendingHint")}</p>}
      {openFailures.map((failure) => (
        <div key={failure.id} className="mt-2 flex flex-wrap items-center gap-2">
          <span>{failureMessage(failure, language)}</span>
          {hasPermission("finance.manage_entries") && (
            <Button size="sm" variant="outline" disabled={retryMutation.isPending} onClick={() => retryMutation.mutate(failure.id)}>
              <RotateCcw className="h-3.5 w-3.5" />
              {t("finance.failures.retry")}
            </Button>
          )}
        </div>
      ))}
      {booked.length > 0 && (
        <ul className="mt-2 space-y-1">
          {booked.map((entry) => (
            <li key={entry.id} className="flex flex-wrap items-center gap-2">
              {hasPermission("finance.view_ledger") ? (
                <Link to={`/finance/entries?entry=${entry.id}`} className="font-mono text-primary hover:underline">
                  {entry.number}
                </Link>
              ) : (
                <span className="font-mono">{entry.number}</span>
              )}
              <span className="text-muted-foreground">
                {entry.journal_code} · {formatDate(entry.entry_date)} · {formatXof(entry.total_debit)}
              </span>
              <EntryStatusBadge status={entry.status} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Mount it on the run page**

Open the payroll run page component (Files above). Add `import { LedgerPostingStatus } from "../finance/LedgerPostingStatus";` and render

```tsx
<LedgerPostingStatus runId={run.id} runStatus={run.status} />
```

directly under the run's header / status line (above the payslip table), where `run` is the run object the page already loads (use the page's own variable name if it differs; the props are the run's `id` and `status`). The component hides itself before approval, so no condition is needed around it.

- [ ] **Step 3: Add the strings**

End of the `en` object:

```ts
  "finance.posting.state.posted": "Posted to the ledger",
  "finance.posting.state.pending": "Not posted yet",
  "finance.posting.state.refused": "Not posted: the ledger refused it",
  "finance.posting.pendingHint": "The ledger posts the run a few seconds after approval. If this stays, check that the event worker is running.",
```

End of the `fr` object:

```ts
  "finance.posting.state.posted": "Comptabilisée au grand livre",
  "finance.posting.state.pending": "Pas encore comptabilisée",
  "finance.posting.state.refused": "Non comptabilisée : refusée par le grand livre",
  "finance.posting.pendingHint": "Le grand livre comptabilise la paie quelques secondes après l'approbation. Si ce message reste, vérifiez que le worker d'événements tourne.",
```

- [ ] **Step 4: Type-check**

Run (from `frontend/`): `npx tsc -b --force`
Expected: no errors.

- [ ] **Step 5: Check it in the browser**

After Task 15's seed (or with an approved run and the worker running): open the seeded run's page — it shows "Posted to the ledger" with its PAIE entry number linking to the entry, and a reversed run lists both the entry and its reversal. A user with only `payroll.view_runs` sees the status without the link; a run still `calculated` shows nothing. The refused state (red, reason in the chosen language, "Retry") renders from the same data as the Entries screen's "Postings refused" card; to see it on dev, close the run's month on the Periods screen before running Task 15's seed for that run — the seed prints the refusal and the page shows it until the month is reopened and "Retry" is pressed.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/finance/LedgerPostingStatus.tsx frontend/src/lib/i18n.tsx <the run page file found in Files above>
git commit -m "feat(payroll): show on the run page whether the ledger posted the run

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 15: Seed the demo ledger and post the seeded payroll run

**Files:**
- Create: `backend/scripts/seed_finance_ledger.py`
- Test: `backend/scripts/test_seed_finance_ledger.py`

**Interfaces:**
- Consumes: `scripts.seed_common` (`TENANT`, `actor_id`, `run`), `ChartSetupService.ensure_defaults`, `PeriodService.open_fiscal_year`, `PostingRuleService.create_rule` / `.list_rules`, `ledger_event_postings.post_for_event` / `source_of`, `PostingFailureService.record`, `payroll_ledger_service.last_day_of` and `PAYROLL_API_FACTORY` (the real `PayrollPostingService`), and — dev script only, like the other seeders — `payroll.runs (id, tenant_id, period, status)` from phase 3 and `events.outbox`.
- Produces: a demo tenant with the chart, journals, default rules (`to_confirm`), AMO code rules, open fiscal years, the demo user's seven ledger permissions, the seeded payroll run(s) posted (PAIE, plus BNQ/CAI when paid, plus reversals when reversed) and the tenant's issued/paid invoices posted (VTE/BNQ). Pure helper `amo_rules(posting_lines) -> list[tuple[str, str, str | None, str]]`.

- [ ] **Step 1: Write the failing test of the pure helper**

`backend/scripts/test_seed_finance_ledger.py`:

```python
"""The seed's one decision: which contribution codes get an AMO rule (433), from the codes a run uses."""
from decimal import Decimal

from scripts.seed_finance_ledger import amo_rules


def test_amo_contribution_codes_get_a_433_rule_once():
    lines = [
        {"source_kind": "employee_contribution", "code": "AMO_EE", "amount": Decimal(100), "employee_id": "e1"},
        {"source_kind": "employee_contribution", "code": "AMO_EE", "amount": Decimal(100), "employee_id": "e2"},
        {"source_kind": "employer_contribution", "code": "amo_er", "amount": Decimal(150), "employee_id": "e1"},
        {"source_kind": "employee_contribution", "code": "INPS_EE", "amount": Decimal(300), "employee_id": "e1"},
        {"source_kind": "earning", "code": "AMO_BONUS", "amount": Decimal(5), "employee_id": "e1"},
    ]
    assert amo_rules(lines) == [
        ("employee_contribution", "AMO_EE", None, "433"),
        ("employer_contribution", "amo_er", "664", "433"),
    ]
```

- [ ] **Step 2: Run it to verify it fails**

Run (from `backend/`): `.venv/Scripts/python -m pytest scripts/test_seed_finance_ledger.py -q`
Expected: collection error `No module named 'scripts.seed_finance_ledger'`.

- [ ] **Step 3: Write the seed script**

`backend/scripts/seed_finance_ledger.py`:

```python
"""Give the demo tenant a SYSCOHADA ledger and post the seeded payroll run(s) and invoices into it.

    cd backend
    PYTHONPATH=. .venv/Scripts/python.exe scripts/seed_finance_ledger.py --dry-run
    PYTHONPATH=. .venv/Scripts/python.exe scripts/seed_finance_ledger.py

Idempotent — a second run adds nothing:
1. grants the demo user the seven ledger permissions;
2. installs the chart, the journals and the default posting rules (all `to_confirm`);
3. opens the fiscal years the data falls in (and the current one);
4. adds `to_confirm` rules sending AMO contributions to 433, for the contribution codes the seeded runs
   actually use whose code contains "AMO" — the codes belong to payroll, so they are printed for the
   accountant to check, like every other rule;
5. posts every seeded payroll run that got past calculation through the path the worker uses
   (`post_for_event` with a `payroll.run.approved` envelope, then `paid` / `reversed` when the run is),
   and replays the tenant's `finance.invoice.issued` / `paid` outbox envelopes, oldest first;
6. records and prints every refusal (it then shows on the run page and on the Entries screen).

Dev shortcut, not a business rule: the seeded rule set is a draft, so the demo run cannot be approved;
a `calculated` run is posted as if approved so the ledger screens hold a real payroll entry. The run's
own status is not touched. Reading `payroll.runs` and `events.outbox` directly is allowed here only
because this is a dev seeder, like the other scripts in this folder.
"""
from __future__ import annotations

import datetime

from ulid import ULID

from core.domain.result import Err
from modules.finance.api import payroll_ledger_service
from modules.finance.api.chart_setup_service import ChartSetupService
from modules.finance.api.ledger_event_postings import post_for_event, source_of
from modules.finance.api.period_service import PeriodService
from modules.finance.api.posting_failure_service import PostingFailureService
from modules.finance.api.posting_rule_service import PostingRuleService
from scripts.seed_common import TENANT, actor_id, run

LEDGER_PERMISSIONS = [
    "finance.view_ledger",
    "finance.manage_entries",
    "finance.admin_entries",
    "finance.manage_accounts",
    "finance.admin_accounts",
    "finance.admin_periods",
    "finance.manage_posting_rules",
]
POSTED_RUN_STATUSES = ("calculated", "approved", "paid", "reversed")
AMO_ACCOUNTS = {"employee_contribution": (None, "433"), "employer_contribution": ("664", "433")}


def amo_rules(posting_lines: list[dict]) -> list[tuple[str, str, str | None, str]]:
    """(source_kind, code, debit, credit) for each AMO contribution code the run uses, once each."""
    rules: list[tuple[str, str, str | None, str]] = []
    for line in posting_lines:
        kind, code = line["source_kind"], str(line["code"])
        if kind in AMO_ACCOUNTS and "AMO" in code.upper():
            debit, credit = AMO_ACCOUNTS[kind]
            rule = (kind, code, debit, credit)
            if rule not in rules:
                rules.append(rule)
    return rules


def _envelope(event_type: str, payload: dict, occurred_at: datetime.datetime) -> dict:
    return {
        "event_id": str(ULID()),
        "event_type": event_type,
        "event_version": "1.0",
        "occurred_at": occurred_at.isoformat(),
        "producer": "seed",
        "tenant_id": TENANT,
        "correlation_id": str(ULID()),
        "causation_id": None,
        "payload": payload,
    }


def _post(conn, envelope: dict) -> bool:
    result = post_for_event(conn, envelope)
    source_module, source_id, source_kind = source_of(envelope)
    if isinstance(result, Err):
        PostingFailureService(conn).record(
            tenant_id=TENANT, source_module=source_module, source_id=source_id,
            source_kind=source_kind, envelope=envelope, err=result,
        )
        print(f"  REFUSED {envelope['event_type']} {source_id}: {result.code} — {result.message}")
        return False
    for entry in result.value:
        print(f"  {entry['number']:<18} {entry['journal_code']:<4} {entry['entry_date']} {entry['label']} ({int(entry['total_debit'])} F CFA)")
    return True


def work(conn, args) -> int:
    actor = actor_id(conn)
    for permission in LEDGER_PERMISSIONS:
        conn.execute(
            "INSERT INTO core.user_permissions (user_id, permission) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (actor, permission),
        )
    print("setup:", ChartSetupService(conn).ensure_defaults(tenant_id=TENANT, actor_id=actor))

    runs = conn.execute(
        "SELECT id, period, status FROM payroll.runs WHERE tenant_id = %s AND status = ANY(%s) ORDER BY period, id",
        (TENANT, list(POSTED_RUN_STATUSES)),
    ).fetchall()
    invoice_envelopes = [
        row[0]
        for row in conn.execute(
            """
            SELECT payload FROM events.outbox
            WHERE tenant_id = %s AND event_type IN ('finance.invoice.issued', 'finance.invoice.paid')
            ORDER BY created_at
            """,
            (TENANT,),
        ).fetchall()
    ]

    years = {datetime.date.today().year} | {period.year for _, period, _ in runs}
    years |= {datetime.datetime.fromisoformat(envelope["occurred_at"]).year for envelope in invoice_envelopes}
    periods = PeriodService(conn)
    for year in sorted(years):
        opened = periods.open_fiscal_year(tenant_id=TENANT, actor_id=actor, year=year)
        print(f"fiscal year {year}:", "opened" if not isinstance(opened, Err) else opened.code)

    payroll_api = payroll_ledger_service.PAYROLL_API_FACTORY(conn)
    rules = PostingRuleService(conn)
    for run_id, _, _ in runs:
        for kind, code, debit, credit in amo_rules(payroll_api.posting_lines(tenant_id=TENANT, run_id=run_id)):
            created = rules.create_rule(
                tenant_id=TENANT, actor_id=actor, source="payroll", source_kind=kind, code=code,
                debit_account_code=debit, credit_account_code=credit,
            )
            print(f"AMO rule {kind} {code}:", "added" if not isinstance(created, Err) else created.code)

    refused = 0
    for run_id, period, status in runs:
        print(f"payroll run {run_id} ({period:%m/%Y}, {status})")
        last_day = payroll_ledger_service.last_day_of(period)
        at = datetime.datetime.combine(min(last_day, datetime.date.today()), datetime.time(12, 0), datetime.timezone.utc)
        payload = {"run_id": run_id, "period": period.isoformat(), "run_type": "regular"}
        steps = ["payroll.run.approved"]
        if status in ("paid", "reversed"):
            steps.append("payroll.run.paid")
        if status == "reversed":
            steps.append("payroll.run.reversed")
        for event_type in steps:
            refused += not _post(conn, _envelope(event_type, payload, at))

    print(f"invoices: {len(invoice_envelopes)} event(s) to replay")
    for envelope in invoice_envelopes:
        refused += not _post(conn, envelope)

    print("\nposting rules (to be ticked by the accountant):")
    for rule in rules.list_rules(tenant_id=TENANT):
        print(
            f"  {rule['source']:<8} {rule['source_kind']:<22} {rule['code']:<10} "
            f"D {rule['debit_account_code'] or '-':<5} C {rule['credit_account_code'] or '-':<5} "
            f"{rule['journal_code'] or '':<4} {rule['status']}"
        )
    print(f"\n{len(runs)} payroll run(s), {len(invoice_envelopes)} invoice event(s), {refused} refusal(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(run("Seed the SYSCOHADA ledger of the demo tenant and post its payroll and invoices.", work))
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/Scripts/python -m pytest scripts/test_seed_finance_ledger.py -q`
Expected: PASS.

- [ ] **Step 5: Dry-run, then seed the dev database**

Run (from `backend/`, after phase 3's `scripts/seed_hr_payroll.py` has seeded its run):
`PYTHONUTF8=1 PYTHONPATH=. .venv/Scripts/python.exe scripts/seed_finance_ledger.py --dry-run`
Expected: the setup counts, the fiscal years opened, one PAIE entry per seeded run (`PAIE-<year>-000001` …), VTE/BNQ entries for the replayed invoices (non-XOF or unissued ones print `REFUSED … CURRENCY_NOT_XOF` / `INVOICE_NOT_POSTED`), the rule table, and "DRY RUN: everything above was rolled back".
Then the same command without `--dry-run`, and once more: the second run prints setup counts of 0, `FISCAL_YEAR_EXISTS`, `POSTING_RULE_EXISTS`, and the same entry numbers (nothing posted twice).

- [ ] **Step 6: Check the screens with the data**

Log in again as `demo@sonalim-erp.local` / `demo1234`: the Trial balance totals balance and the 42/43/44 card shows net pay (422), contributions (431/433) and ITS (447) owed; the payroll run page (Task 14) shows "Posted to the ledger" with the PAIE entry; the Entries screen filtered on PAIE lists it.

- [ ] **Step 7: Commit**

```bash
git add backend/scripts/seed_finance_ledger.py backend/scripts/test_seed_finance_ledger.py
git commit -m "chore(seed): SYSCOHADA ledger for the demo tenant with the seeded payroll posted

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Self-review notes

- **Spec coverage (Phase 4):** accounts + chart seed → Tasks 3, 7; journals PAIE/VTE/ACH/BNQ/CAI/OD → Task 3; fiscal years and periods open/closed + close/reopen → Tasks 3, 10, 13; entries and lines, balanced builder, immutable posted entries, deferred balance trigger → Tasks 1, 4; posting rules `(source, source_kind, code)` with `'*'` and the to-confirm default payroll mapping → Tasks 2, 3, 7; consumers for `payroll.run.approved/paid/reversed` and `finance.invoice.issued/paid`, idempotent on `event_id` and `(source_module, source_id, kind)`, each with a deliver-twice test → Tasks 5, 6; `PERIOD_CLOSED` refusal with dead-letter and "not posted" reason → Tasks 3, 4, 5, 14; manual OD entries draft → posted behind `finance.manage_entries` → Tasks 8, 10, 12; trial balance, general ledger, journal listing, 42x/43x/44x balances → Tasks 8, 9, 10, 12, 13; `finance.journal_entry.posted` in the catalog → Task 4; `LedgerQueryService.entries_for_source` → Task 8; permissions → Task 3; six screens → Tasks 11–13; run page status → Task 14; seed → Task 15.
- **Error codes from the spec used here:** `ENTRY_UNBALANCED`, `PERIOD_CLOSED`, `ACCOUNT_NOT_POSTABLE`, `POSTING_RULE_MISSING`; the other new codes are listed under "Decisions".
- **Names checked across tasks:** `LedgerPostingService.post_entry / post_draft / reverse_entry / insert_draft / check_draft / check_postable / lines_of / find_by_source / load_accounts / journal_codes`; `PostingRuleService.rules_for / list_rules / create_rule / update_rule / confirm_rule`; `PostingFailureService.record / resolve / cancel_for_source / get / list_failures / failures_for_source`; `post_for_event`, `source_of`, `occurred_on`, `retry_failure`; `PAYROLL_API_FACTORY`, `last_day_of`; entry source kinds `payroll_run`, `payroll_payment_<method>`, `invoice_issued`, `invoice_paid` and `<kind>_reversal`; failure kinds `payroll_run`, `payroll_payment`, `payroll_reversal`, `invoice_issued`, `invoice_paid`; frontend `LEDGER_KEYS`, `invalidateLedgerData`, `LedgerTable`, `textFilter`, `rangeFilter`, `EntryStatusBadge`, `failureMessage`.
- **Known dependency on phase 3 not visible from here:** the run page file name (Task 14 finds it through the router) and the `payroll.runs` columns `id, tenant_id, period, status` read by the seed (spec wording).
