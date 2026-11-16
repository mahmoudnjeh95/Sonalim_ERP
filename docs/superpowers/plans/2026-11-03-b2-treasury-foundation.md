# B2 — Treasury foundation (module + master data) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or superpowers:executing-plans. Read `2026-11-03-treasury-interfaces.md` first.

**Goal:** Create the `treasury` module with banks, branches, treasury accounts (bank, cash register, mobile money), account movements, and its configuration (cash limit, alert offsets), plus the settings screens.

**Architecture:** New module `backend/modules/treasury/` laid out like `maintenance` (`domain/`, `api/`, `events/`, `migrations/`, `module.json`). Domain validators are pure. Balances change only through `AccountMovementService`, which B3/B4 reuse.

## Decisions

1. One generic **treasury account** table with `kind IN ('bank','cash','mobile_money')`, so receipts/disbursements reference one thing. Bank accounts link to a branch; mobile-money accounts carry `operator` (Orange Money / Moov Money, free text allowed) and `phone` — one account per operator (confirmed decision 3).
2. Each account has an optional `ledger_account_code` (e.g. `521`, `571`, `552`), stored now and used by B6.
3. Account-number/IBAN format is not hard-coded: `treasury.account_format_rules (country, kind, regex, hint_en, hint_fr)`, none seeded as mandatory. Account number and IBAN are unique per tenant (`ACCOUNT_NUMBER_DUPLICATE`).
4. Opening balance is editable until the first movement, then `ACCOUNT_LOCKED` (the spec says this for cash registers; applying it to every kind is the safer rule).
5. `treasury.settings (tenant_id, key, value_json)`: `cash_payment_limit` (null → no cap, confirmed decision 4), `prior_year_invoice_cutoff` (null). `treasury.alert_rules (direction, method, offset_days)` seeded with the manual's values, editable: received cheque +1, received draft +15, issued cheque −1, issued draft −15 (days relative to due date; confirmed decision 5).
6. An account with movements cannot be deleted; deactivate instead (`is_active`). Overdraft allowed only on bank accounts with `allow_overdraft`.

## Tasks

### Task 1 — Module scaffold
- [ ] Create `modules/treasury/{__init__.py,module.json,api/,domain/,events/,migrations/}` per the contract (depends `core`, optional `finance`, `procurement`; permissions from the contract). Register in `MODULE_ORDER` after `procurement` and everywhere `maintenance` is wired. Boot the app (`run` skill) and confirm `core.module_migrations` records treasury. Commit.

### Task 2 — Domain validators
- [ ] `domain/accounts.py` + `test_accounts.py`, failing tests first: `validate_account(kind, fields, format_rules)` (bank needs branch + number + currency; mobile money needs operator + phone; cash needs name + currency); `apply_movement(balance, signed_amount, allow_negative)` → `INSUFFICIENT_BALANCE` when it would go negative on a non-overdraft account; `normalize_iban`. Implement; commit.

### Task 3 — Migration `0001_treasury_master_data.sql`
- [ ] Tables: `banks (id, tenant_id, name, code, swift, country, is_active)`, `bank_branches (id, bank_id, name, city, address, phone)`, `accounts (id, tenant_id, kind, name, currency, account_number, iban, branch_id NULL, operator NULL, phone NULL, opening_balance, balance, allow_overdraft, ledger_account_code NULL, is_active, created_at)`, `account_movements (id, tenant_id, account_id, amount SIGNED, balance_after, source_type, source_id, occurred_on, note, created_by, created_at)`, `settings`, `alert_rules` (seeded with the four rows), `account_format_rules`. Unique `(tenant_id, account_number)` and `(tenant_id, iban)` where not null; index on `account_movements (account_id, occurred_on)`.
- [ ] Apply; commit.

### Task 4 — Services and router
- [ ] Failing integration tests: bank/branch CRUD; account create per kind with validation errors; duplicate number/IBAN refused; opening balance editable then `ACCOUNT_LOCKED` after a movement; `AccountMovementService.post(account_id, signed_amount, source_type, source_id, occurred_on)` updates the balance atomically under a row lock and writes a movement; overdraft rules; deactivate vs delete; settings get/set (`admin_config`); alert rules list/update.
- [ ] Implement `BankService`, `AccountService`, `AccountMovementService`, `SettingsService`. Router `/treasury/banks`, `/branches`, `/accounts`, `/accounts/{id}/movements`, `/settings`, `/alert-rules`. Permissions `view`, `manage_accounts`, `admin_config`. Audit every mutation; French error messages. Commit.

### Task 5 — Frontend
- [ ] `features/treasury/` with `api.ts` and `TreasuryPage.tsx` (tabs: Accounts, Banks & branches, Settings); account dialog with kind-specific fields; movements drawer per account; balances in F CFA; settings form for cash limit and alert offsets. Route + sidebar + permission gating; i18n en+fr; `npx tsc -b --force`. Commit.

### Task 6 — Handoff
- [ ] Run `modules/treasury` + `core` tests (report skips); grant permissions to the demo user; do not push.
