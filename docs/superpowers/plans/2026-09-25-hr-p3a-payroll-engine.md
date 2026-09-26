# HR Phase 3a — Payroll engine (module skeleton, rule tables, pure engine) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create the new `payroll` module with its configurable, effective-dated rule tables (rule sets, components, contributions, tax brackets, reliefs, seniority, overtime and severance scales), a pure, step-by-step tested payroll engine, and the service + HTTP routes that manage rule sets (draft → confirmed).

**Architecture:** `backend/modules/payroll/` is a new bounded context (FastAPI + raw psycopg SQL). Every statutory number is a row in `payroll.*`, never code. The engine (`payroll/domain/*.py`) is pure: it takes an employee snapshot, a presence summary, a loaded `RuleSet` and one-off inputs and returns ordered payslip lines, totals and carry-forwards. `RuleSetService` stores/validates/confirms rule sets and loads them into the domain `RuleSet`. Runs, payslips, payouts, declarations and the frontend are **Phase 3b** (`docs/superpowers/plans/2026-09-25-hr-p3b-payroll-runs.md`), which depends on this plan.

**Tech Stack:** Python 3.11, FastAPI, psycopg 3 (raw SQL), `decimal.Decimal`, pytest; PostgreSQL.

**Spec:** `docs/superpowers/specs/2026-09-25-hr-payroll-finance-design.md` (section "Phase 3 — Payroll"), cross-phase contract `docs/superpowers/plans/2026-09-25-hr-payroll-finance-interfaces.md`.

**Split notice:** Phase 3 is 33 tasks, so it is split in two plans that run in order:
- **3a (this file):** module skeleton, rule tables, pure engine, rule-set service and routes — Tasks 1–11.
- **3b:** `docs/superpowers/plans/2026-09-25-hr-p3b-payroll-runs.md` — runs, inputs, advances/loans, final settlement, payslips + print, payouts, declarations, events, `PayrollPostingService`/`PayrollReportService`, frontend, seed — Tasks 1–22.

Phases 1 and 2 (hr employee core, presence & leave) are assumed merged. This plan (3a) does not call them yet; 3b does, through `PayrollSnapshotService` and `PresenceService` exactly as the contract defines.

## Global Constraints

- Money columns are `NUMERIC(18,0)` in XOF; Python uses `decimal.Decimal`, never `float`. JSON responses give money as integers (`api/rows.py::jsonable`).
- A "period" is a `datetime.date` equal to the first day of the month.
- "Every rate, ceiling, bracket, relief and account number named below is **seed data, not code**" — no Mali value may appear anywhere under `backend/modules/payroll/`. Engine tests use the synthetic rule set (`domain/synthetic.py`, round numbers, not Mali).
- A rule set carries `status in ('draft', 'confirmed')` and `confirmed_by/at`. A run may be calculated on a draft rule set; approval is refused with `RULESET_NOT_CONFIRMED` (3b).
- "Rounding of every computed line is a rule-set setting (`round_to` = 1 by default, `round_mode` = half_up); the ITS may round down to a multiple of 10 or 100 if the accountant says so — this is also data" → `round_to`/`round_mode` for lines, `tax_round_to`/`tax_round_mode` for the tax.
- Rates are stored as the accountant writes them, in percent: `3.6` means 3.6 %. Overtime `multiplier` is the total pay factor (`1.5` = 150 % of the hourly rate).
- Every mutation calls `record_audit()` in the same transaction; every refusal is `Err(code, message, message_fr)` (guard test `core/test_error_translations.py` fails otherwise).
- Payroll never reads another module's tables: hr data only through hr's api services (3b); `employee_id` is an opaque `TEXT` with no foreign key. Only shared-kernel tables (`core.users`, `core.companies`, `core.audit_log`) may be read directly.
- Migrations: payroll uses `0001_*`+; `"payroll"` sits in `MODULE_ORDER` right after `"hr"`; an applied migration is never edited.
- Permission codes exactly: `payroll.view_runs`, `payroll.calculate_runs`, `payroll.approve_runs`, `payroll.pay_runs`, `payroll.reverse_runs`, `payroll.manage_inputs`, `payroll.view_rules`, `payroll.manage_rules`, `payroll.confirm_rules`, `payroll.view_declarations`, `payroll.admin_payslips`.
- Tests: domain tests next to the code (`*/domain/test_*.py`, no DB); integration tests `*_integration.py` with the `db` fixture. Run from `backend/`: `.venv/Scripts/python -m pytest <path> -q`. A green run full of "skipped" means no database was reachable — nothing was tested.
- Shared working tree: never `git stash`; `git add` only the files the task lists.

## Review Focus

1. **A rule set changed after payslips were computed from it** — expected: only drafts are editable; a confirmed set answers `RULESET_LOCKED` to every edit/add/delete, and `confirmed_at` is stamped with `clock_timestamp()` so 3b can refuse approving a run calculated before the confirmation. Test: Task 10 `test_a_confirmed_rule_set_is_locked`.
2. **Tax brackets with a gap, an overlap, a closed last bracket or mixed annual/monthly amounts** — expected: confirmation refused with `RULESET_INCOMPLETE` naming the problem, never a silently wrong ITS. Test: Task 3 `test_bracket_gaps_overlaps_and_mixed_periods_block_confirmation`.
3. **More unpaid absence days than days paid in the month** (new hire absent) — expected: the absence line takes at most the base earned; gross never goes negative. Test: Task 4 `test_unpaid_absence_never_takes_more_than_the_base_earned`.
4. **A daily-paid contract** (`pay_frequency='daily'`, `base_salary` is a day rate) — expected: paid per worked + paid-leave + paid-holiday day, overtime hourly rate from rate × working days ÷ working hours; never treated as a monthly salary. Tests: Task 4 `test_a_daily_rate_is_paid_per_worked_leave_and_holiday_day`, Task 9 `test_golden_daily_worker`.
5. **More tax dependants than the last family-relief step** — expected: the last step applies (the scale's maximum), not zero. Test: Task 6 `test_dependants_beyond_the_last_step_keep_the_last_step`.

---

## File Structure (this plan)

```
backend/modules/payroll/
  __init__.py
  module.json                       manifest: deps core+hr, APIs, events, permissions
  test_manifest.py                  manifest / MODULE_ORDER / permission catalog (no DB)
  migrations/0001_payroll_rules.sql settings + rule tables
  domain/
    __init__.py
    money.py        round_amount, percent_of
    inputs.py       engine value objects: EmployeeInput, PresenceInput, OneOffInput, SettlementInput, PayslipLine
    rules.py        RuleSet + rule value objects, system component codes, RuleSetIncomplete/ComponentMisuse
    synthetic.py    synthetic (round-number, NOT Mali) rule set + employee factory for tests
    rule_validation.py  row validators + check_complete (confirm gate) + relief parameter parsing
    earnings.py     step 1: base proration, unpaid absence, seniority, overtime, components, inputs
    contributions.py step 2-3: contributable base, ceilings, employee/employer contributions
    tax.py          step 4: taxable, professional relief, brackets (annualised), family relief
    net.py          step 5-6: deductions, net floor + carry-forward, employer charges, totals
    settlement.py   final settlement: service years, reference salary, leave/notice/severance
    engine.py       calculate_payslip orchestration
    test_*.py       one test file per module above + test_engine_golden.py
  api/
    __init__.py
    rows.py         fetch_all / fetch_one / jsonable
    http.py         get_connection (patch point), fail(), finish(), found()
    rule_set_service.py  settings, rule sets, child rows, confirm, load, in_force
    testing_support.py   helpers shared by integration tests (users, synthetic rule set in DB)
    routes_rules.py /payroll/settings, /payroll/rule-sets/**
    router.py       APIRouter(prefix="/payroll") including the sub-routers
    test_schema_integration.py, test_rule_set_service_integration.py, test_rules_router_integration.py
backend/core/migrations/runner.py   (modify) MODULE_ORDER + dir
backend/core/permissions_registry.py (modify) MODULE_LABELS["payroll"]
backend/app/main.py                  (modify) include payroll router
```

---

### Task 1: Module skeleton, rule tables, permissions, wiring

**Files:**
- Create: `backend/modules/payroll/__init__.py`, `backend/modules/payroll/domain/__init__.py`, `backend/modules/payroll/api/__init__.py` (all empty)
- Create: `backend/modules/payroll/module.json`
- Create: `backend/modules/payroll/migrations/0001_payroll_rules.sql`
- Create: `backend/modules/payroll/api/router.py`
- Create: `backend/modules/payroll/test_manifest.py`
- Create: `backend/modules/payroll/api/test_schema_integration.py`
- Modify: `backend/core/migrations/runner.py` (the `MODULE_MIGRATION_DIRS` dict and `MODULE_ORDER`)
- Modify: `backend/core/permissions_registry.py` (`MODULE_LABELS`)
- Modify: `backend/app/main.py` (router import + include)

**Interfaces:**
- Produces: schema `payroll` with tables `settings`, `rule_sets`, `components`, `contributions`, `tax_brackets`, `tax_reliefs`, `seniority_scale`, `overtime_rates`, `severance_scale` (columns below are the contract for every later task); `modules.payroll.api.router.router` (`APIRouter(prefix="/payroll")`).

- [ ] **Step 1: Write the failing manifest test**

Create `backend/modules/payroll/test_manifest.py`:

```python
"""The payroll module is declared like every other module: manifest, load order, permissions."""
from __future__ import annotations

import json
import pathlib

from core.migrations.runner import MODULE_MIGRATION_DIRS, MODULE_ORDER
from core.permissions_registry import MODULE_LABELS, permission_catalog

MODULE_DIR = pathlib.Path(__file__).resolve().parent

PERMISSIONS = [
    "payroll.view_runs",
    "payroll.calculate_runs",
    "payroll.approve_runs",
    "payroll.pay_runs",
    "payroll.reverse_runs",
    "payroll.manage_inputs",
    "payroll.view_rules",
    "payroll.manage_rules",
    "payroll.confirm_rules",
    "payroll.view_declarations",
    "payroll.admin_payslips",
]


def test_payroll_migrates_right_after_hr():
    assert MODULE_ORDER.index("payroll") == MODULE_ORDER.index("hr") + 1
    assert MODULE_MIGRATION_DIRS["payroll"].resolve() == MODULE_DIR / "migrations"


def test_the_manifest_declares_the_spec_permissions_and_contract():
    manifest = json.loads((MODULE_DIR / "module.json").read_text(encoding="utf-8"))
    assert manifest["name"] == "payroll"
    assert manifest["depends"] == ["core", "hr"]
    assert manifest["permissions"] == PERMISSIONS
    assert set(manifest["provides_api"]) == {"PayrollPostingService", "PayrollReportService"}
    assert manifest["publishes_events"] == ["payroll.run.approved", "payroll.run.paid", "payroll.run.reversed"]


def test_payroll_permissions_are_grantable_and_have_a_role_label():
    granted = {entry["permission"] for entry in permission_catalog() if entry["module"] == "payroll"}
    assert granted == set(PERMISSIONS)
    assert MODULE_LABELS["payroll"] == "Paie"
```

- [ ] **Step 2: Run it to verify it fails**

Run (from `backend/`): `.venv/Scripts/python -m pytest modules/payroll/test_manifest.py -q`
Expected: FAIL — `ValueError: 'payroll' is not in list` (and `FileNotFoundError` for `module.json`).

- [ ] **Step 3: Create the manifest, package files and router**

Create empty `backend/modules/payroll/__init__.py`, `backend/modules/payroll/domain/__init__.py`, `backend/modules/payroll/api/__init__.py`.

Create `backend/modules/payroll/module.json`:

```json
{
  "name": "payroll",
  "version": "0.1.0",
  "depends": ["core", "hr"],
  "optional_depends": [],
  "provides_api": ["PayrollPostingService", "PayrollReportService"],
  "publishes_events": ["payroll.run.approved", "payroll.run.paid", "payroll.run.reversed"],
  "subscribes_events": [],
  "migrations_path": "./migrations",
  "permissions": [
    "payroll.view_runs",
    "payroll.calculate_runs",
    "payroll.approve_runs",
    "payroll.pay_runs",
    "payroll.reverse_runs",
    "payroll.manage_inputs",
    "payroll.view_rules",
    "payroll.manage_rules",
    "payroll.confirm_rules",
    "payroll.view_declarations",
    "payroll.admin_payslips"
  ]
}
```

Create `backend/modules/payroll/api/router.py`:

```python
"""Every payroll endpoint hangs off this router; each area adds its own sub-router here."""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/payroll", tags=["payroll"])
```

- [ ] **Step 4: Register the module**

In `backend/core/migrations/runner.py`, add the payroll entry right after the `"hr"` entry of `MODULE_MIGRATION_DIRS`:

```python
    "hr": REPO_ROOT / "modules" / "hr" / "migrations",
    "payroll": REPO_ROOT / "modules" / "payroll" / "migrations",
```

and replace the `MODULE_ORDER` line (and extend its comment) with:

```python
# payroll runs right after hr: its rows carry hr employee ids as opaque text (no foreign key)
# and it reads hr only through hr's api services, so hr's schema must exist first.
MODULE_ORDER = ["core", "warehouse", "production", "crm", "sales", "finance", "hr", "payroll", "procurement", "qc", "maintenance"]
```

In `backend/core/permissions_registry.py`, add to `MODULE_LABELS` (keep alphabetical order):

```python
    "maintenance": "Maintenance",
    "payroll": "Paie",
    "procurement": "Achats",
```

In `backend/app/main.py`, add the import after `from modules.hr.api.router import router as hr_router`:

```python
from modules.payroll.api.router import router as payroll_router
```

and the include after `app.include_router(hr_router)`:

```python
app.include_router(payroll_router)
```

- [ ] **Step 5: Write the rule-table migration**

Create `backend/modules/payroll/migrations/0001_payroll_rules.sql`:

```sql
-- Payroll rule tables. Every statutory number (rate, ceiling, bracket, relief, scale) lives in
-- these rows, never in code. Rates are percent as written by the accountant (3.6 = 3.6 %).
CREATE SCHEMA IF NOT EXISTS payroll;

-- One row per tenant: which country's rule sets apply, and the employer identifiers printed on
-- payslips and declarations. The company name itself is core.companies.name.
CREATE TABLE IF NOT EXISTS payroll.settings (
    tenant_id TEXT PRIMARY KEY,
    country TEXT NOT NULL CHECK (country ~ '^[A-Z]{2}$'),
    company_address TEXT,
    employer_inps_no TEXT,
    employer_tax_id TEXT,
    updated_by TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS payroll.rule_sets (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    country TEXT NOT NULL CHECK (country ~ '^[A-Z]{2}$'),
    name TEXT NOT NULL,
    valid_from DATE NOT NULL CHECK (EXTRACT(DAY FROM valid_from) = 1),
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'confirmed')),
    confirmed_by TEXT,
    confirmed_at TIMESTAMPTZ,
    round_to INTEGER NOT NULL DEFAULT 1 CHECK (round_to >= 1),
    round_mode TEXT NOT NULL DEFAULT 'half_up' CHECK (round_mode IN ('half_up', 'down', 'up')),
    tax_round_to INTEGER NOT NULL DEFAULT 1 CHECK (tax_round_to >= 1),
    tax_round_mode TEXT NOT NULL DEFAULT 'half_up' CHECK (tax_round_mode IN ('half_up', 'down', 'up')),
    working_days_per_month NUMERIC(5, 2) NOT NULL CHECK (working_days_per_month > 0),
    working_hours_per_month NUMERIC(6, 2) NOT NULL CHECK (working_hours_per_month > 0),
    -- months of gross averaged into the final-settlement reference salary: a rule value like the
    -- others (the default is only a starting point; the accountant confirms it with the set)
    settlement_reference_months INTEGER NOT NULL DEFAULT 12 CHECK (settlement_reference_months >= 1),
    notes TEXT,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, country, valid_from),
    CHECK ((status = 'confirmed') = (confirmed_at IS NOT NULL AND confirmed_by IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS payroll_rule_sets_lookup_idx ON payroll.rule_sets (tenant_id, country, valid_from DESC);

CREATE TABLE IF NOT EXISTS payroll.components (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    rule_set_id TEXT NOT NULL REFERENCES payroll.rule_sets (id) ON DELETE CASCADE,
    code TEXT NOT NULL,
    name_en TEXT NOT NULL,
    name_fr TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('earning', 'deduction', 'employer_charge')),
    taxable BOOLEAN NOT NULL DEFAULT FALSE,
    contributable BOOLEAN NOT NULL DEFAULT FALSE,
    formula_type TEXT NOT NULL CHECK (formula_type IN ('fixed', 'rate_x_base', 'qty_x_rate', 'per_day')),
    base_ref TEXT CHECK (base_ref IN ('base_salary', 'earned_base', 'gross', 'contributable')),
    default_amount NUMERIC(18, 0),
    default_rate NUMERIC(9, 4),
    display_order INTEGER NOT NULL DEFAULT 100,
    payslip_section TEXT NOT NULL DEFAULT 'earnings' CHECK (payslip_section IN ('earnings', 'deductions', 'employer')),
    declaration_code TEXT,
    UNIQUE (rule_set_id, code)
);

CREATE TABLE IF NOT EXISTS payroll.contributions (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    rule_set_id TEXT NOT NULL REFERENCES payroll.rule_sets (id) ON DELETE CASCADE,
    code TEXT NOT NULL,
    name_en TEXT NOT NULL,
    name_fr TEXT NOT NULL,
    base TEXT NOT NULL CHECK (base IN ('gross', 'contributable')),
    employee_rate NUMERIC(7, 4) NOT NULL DEFAULT 0 CHECK (employee_rate BETWEEN 0 AND 100),
    employer_rate NUMERIC(7, 4) NOT NULL DEFAULT 0 CHECK (employer_rate BETWEEN 0 AND 100),
    ceiling_monthly NUMERIC(18, 0) CHECK (ceiling_monthly > 0),
    deductible_from_taxable BOOLEAN NOT NULL DEFAULT TRUE,
    declaration_code TEXT NOT NULL,
    liability_account_code TEXT,
    display_order INTEGER NOT NULL DEFAULT 100,
    UNIQUE (rule_set_id, code)
);

CREATE TABLE IF NOT EXISTS payroll.tax_brackets (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    rule_set_id TEXT NOT NULL REFERENCES payroll.rule_sets (id) ON DELETE CASCADE,
    tax_code TEXT NOT NULL,
    lower_bound NUMERIC(18, 0) NOT NULL CHECK (lower_bound >= 0),
    upper_bound NUMERIC(18, 0) CHECK (upper_bound > lower_bound),
    rate NUMERIC(7, 4) NOT NULL CHECK (rate BETWEEN 0 AND 100),
    annualised BOOLEAN NOT NULL DEFAULT FALSE,
    UNIQUE (rule_set_id, tax_code, lower_bound)
);

-- parameters (JSON, decimals as strings):
--   family:                {"mode": "percent_of_tax"|"amount", "steps": [{"dependants": 1, "value": "10"}], "cap_monthly": null|"..."}
--   professional_expenses: {"percent": "10", "cap_monthly": null|"..."}
CREATE TABLE IF NOT EXISTS payroll.tax_reliefs (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    rule_set_id TEXT NOT NULL REFERENCES payroll.rule_sets (id) ON DELETE CASCADE,
    tax_code TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('family', 'professional_expenses')),
    parameters JSONB NOT NULL,
    UNIQUE (rule_set_id, tax_code, kind)
);

CREATE TABLE IF NOT EXISTS payroll.seniority_scale (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    rule_set_id TEXT NOT NULL REFERENCES payroll.rule_sets (id) ON DELETE CASCADE,
    years_from INTEGER NOT NULL CHECK (years_from >= 0),
    percent NUMERIC(7, 4) NOT NULL CHECK (percent BETWEEN 0 AND 100),
    UNIQUE (rule_set_id, years_from)
);

CREATE TABLE IF NOT EXISTS payroll.overtime_rates (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    rule_set_id TEXT NOT NULL REFERENCES payroll.rule_sets (id) ON DELETE CASCADE,
    band_code TEXT NOT NULL CHECK (band_code IN ('day', 'night', 'rest_holiday')),
    multiplier NUMERIC(6, 4) NOT NULL CHECK (multiplier >= 1),
    UNIQUE (rule_set_id, band_code)
);

-- Severance is tiered: each year of service inside [years_from, next years_from) earns
-- percent_per_year % of the reference monthly salary.
CREATE TABLE IF NOT EXISTS payroll.severance_scale (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    rule_set_id TEXT NOT NULL REFERENCES payroll.rule_sets (id) ON DELETE CASCADE,
    years_from INTEGER NOT NULL CHECK (years_from >= 0),
    percent_per_year NUMERIC(7, 4) NOT NULL CHECK (percent_per_year BETWEEN 0 AND 100),
    UNIQUE (rule_set_id, years_from)
);
```

- [ ] **Step 6: Write the schema integration test**

Create `backend/modules/payroll/api/test_schema_integration.py`:

```python
"""The rule tables refuse what the engine could not read.

The migration file is executed inside the test transaction (it is idempotent), so the test
holds whether or not the development database has applied it yet.
"""
from __future__ import annotations

import pathlib

import psycopg
import pytest
from ulid import ULID

MIGRATION = pathlib.Path(__file__).resolve().parents[1] / "migrations" / "0001_payroll_rules.sql"
TENANT = "payroll-schema-test"


def _migrate(db) -> None:
    db.execute(MIGRATION.read_text(encoding="utf-8"))


def _rule_set(db, valid_from: str = "2031-01-01") -> str:
    rule_set_id = str(ULID())
    db.execute(
        """
        INSERT INTO payroll.rule_sets
            (id, tenant_id, country, name, valid_from, working_days_per_month, working_hours_per_month, created_by)
        VALUES (%s, %s, 'ZZ', 'Schema test', %s, 20, 160, 'tester')
        """,
        (rule_set_id, TENANT, valid_from),
    )
    return rule_set_id


def test_a_new_rule_set_is_a_draft_rounded_to_the_franc(db):
    _migrate(db)
    rule_set_id = _rule_set(db)
    row = db.execute(
        "SELECT status, round_to, round_mode, tax_round_to, tax_round_mode, settlement_reference_months"
        " FROM payroll.rule_sets WHERE id = %s",
        (rule_set_id,),
    ).fetchone()
    assert row == ("draft", 1, "half_up", 1, "half_up", 12)


def test_a_rule_set_starts_on_the_first_of_a_month(db):
    _migrate(db)
    with pytest.raises(psycopg.errors.CheckViolation):
        _rule_set(db, valid_from="2031-01-15")


def test_confirmed_needs_who_and_when(db):
    _migrate(db)
    rule_set_id = _rule_set(db)
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute("UPDATE payroll.rule_sets SET status = 'confirmed' WHERE id = %s", (rule_set_id,))


def test_a_component_code_is_unique_within_its_rule_set(db):
    _migrate(db)
    rule_set_id = _rule_set(db)
    insert = """
        INSERT INTO payroll.components (id, tenant_id, rule_set_id, code, name_en, name_fr, kind, formula_type)
        VALUES (%s, %s, %s, 'BASE', 'Base salary', 'Salaire de base', 'earning', 'fixed')
    """
    db.execute(insert, (str(ULID()), TENANT, rule_set_id))
    with pytest.raises(psycopg.errors.UniqueViolation):
        db.execute(insert, (str(ULID()), TENANT, rule_set_id))
```

- [ ] **Step 7: Apply the migration to the dev database and run the tests**

Run (from `backend/`):
```
.venv/Scripts/python -c "import app.main; from core.migrations.runner import apply_all_migrations; apply_all_migrations()"
.venv/Scripts/python -m pytest modules/payroll/test_manifest.py modules/payroll/api/test_schema_integration.py -q
```
Expected: `7 passed` (no skips; if the schema tests skip, start PostgreSQL and rerun).

- [ ] **Step 8: Commit**

```bash
git add backend/modules/payroll/__init__.py backend/modules/payroll/domain/__init__.py backend/modules/payroll/api/__init__.py backend/modules/payroll/module.json backend/modules/payroll/migrations/0001_payroll_rules.sql backend/modules/payroll/api/router.py backend/modules/payroll/test_manifest.py backend/modules/payroll/api/test_schema_integration.py backend/core/migrations/runner.py backend/core/permissions_registry.py backend/app/main.py
git commit -m "feat(payroll): new payroll module with rule tables and permissions

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Money rounding, engine value objects, rule set, synthetic test rules

**Files:**
- Create: `backend/modules/payroll/domain/money.py`
- Create: `backend/modules/payroll/domain/inputs.py`
- Create: `backend/modules/payroll/domain/rules.py`
- Create: `backend/modules/payroll/domain/synthetic.py`
- Test: `backend/modules/payroll/domain/test_money.py`, `backend/modules/payroll/domain/test_rules.py`

**Interfaces:**
- Produces:
  - `money.round_amount(value: Decimal, *, round_to: int = 1, mode: str = "half_up") -> Decimal`; `money.percent_of(amount: Decimal, percent: Decimal) -> Decimal`; constants `ZERO`, `HUNDRED`, `ROUND_MODES`.
  - `inputs`: `ContractComponent(component_code, amount=None, rate=None)`, `EmployeeInput(employee_id, base_salary, pay_frequency, hire_date, contract_start, contract_end=None, termination_date=None, tax_dependants=0, components=())`, `PresenceInput(scheduled_days=0, worked_days=0, unpaid_absence_days=0, paid_leave_days=0, sick_days=0, holiday_days=0, holidays_worked_days=0, ot_minutes_day=0, ot_minutes_night=0, ot_minutes_rest_holiday=0)`, `OneOffInput(component_code, qty=None, amount=None, source_kind="input", source_id=None)`, `SettlementInput(reference_salary, years_of_service, unused_leave_days=0, notice_months=0)`, `PayslipLine(section, code, name_en, name_fr, amount, base=None, qty=None, rate=None, taxable=False, contributable=False, deductible=False, declaration_code=None, display_order=100, source_kind=None, source_id=None)`, `SECTIONS`, `SOURCE_KINDS`, `section_total(lines, section) -> Decimal`.
  - `rules`: codes `BASE, UNPAID_ABSENCE, SENIORITY, OT_DAY, OT_NIGHT, OT_REST_HOLIDAY, ADVANCE, LOAN, LEAVE_INDEMNITY, NOTICE_INDEMNITY, SEVERANCE`, `OVERTIME_BANDS`, `OVERTIME_CODES`, `SYSTEM_COMPONENTS: dict[str, tuple[kind, formula_type]]`; exceptions `RuleSetIncomplete(what_en, what_fr)`, `ComponentMisuse(message_en, message_fr)`; dataclasses `ComponentRule`, `ContributionRule`, `TaxBracket(tax_code, lower, upper, rate, annualised)`, `FamilyReliefStep(dependants, value)`, `FamilyRelief(tax_code, mode, steps, cap_monthly)`, `ProfessionalRelief(tax_code, percent, cap_monthly)`, `SeniorityStep(years_from, percent)`, `OvertimeRate(band_code, multiplier)`, `SeveranceStep(years_from, percent_per_year)`, `RuleSet(id, country, valid_from, status, round_to, round_mode, tax_round_to, tax_round_mode, working_days_per_month, working_hours_per_month, settlement_reference_months=12, components=(), contributions=(), tax_brackets=(), family_reliefs=(), professional_reliefs=(), seniority_scale=(), overtime_rates=(), severance_scale=())` with `component`, `require`, `overtime_multiplier`, `tax_codes`, `brackets_for`, `family_relief`, `professional_relief`, `employer_charges`, `round`, `round_tax`.
  - `synthetic.synthetic_rule_set(*, status="confirmed", annualised=False) -> RuleSet`, `synthetic.synthetic_employee(**changes) -> EmployeeInput`, `synthetic.D` (= `Decimal`).

- [ ] **Step 1: Write the failing tests**

Create `backend/modules/payroll/domain/test_money.py`:

```python
from decimal import Decimal

import pytest

from modules.payroll.domain.money import percent_of, round_amount

D = Decimal


def test_half_up_rounds_halves_away_from_zero_on_both_signs():
    assert round_amount(D("2.5")) == 3
    assert round_amount(D("-2.5")) == -3
    assert round_amount(D("2.49")) == 2


def test_down_to_tens_truncates_toward_zero():
    assert round_amount(D("46675"), round_to=10, mode="down") == D("46670")
    assert round_amount(D("-46675"), round_to=10, mode="down") == D("-46670")


def test_up_to_hundreds_goes_away_from_zero():
    assert round_amount(D("101"), round_to=100, mode="up") == 200


def test_an_exact_multiple_is_unchanged():
    assert round_amount(D("500"), round_to=100, mode="up") == 500


def test_a_bad_step_or_mode_is_a_programming_error():
    with pytest.raises(ValueError):
        round_amount(D("1"), round_to=0)
    with pytest.raises(ValueError):
        round_amount(D("1"), mode="banker")


def test_percent_is_read_as_written():
    assert percent_of(D("487500"), D("3.6")) == D("17550")
```

Create `backend/modules/payroll/domain/test_rules.py`:

```python
from dataclasses import replace
from decimal import Decimal

import pytest

from modules.payroll.domain.rules import BASE, RuleSetIncomplete
from modules.payroll.domain.synthetic import synthetic_rule_set

D = Decimal


def test_require_names_the_missing_component_in_both_languages():
    rules = synthetic_rule_set()
    assert rules.require(BASE).kind == "earning"
    with pytest.raises(RuleSetIncomplete) as missing:
        rules.require("NOPE")
    assert (missing.value.what_en, missing.value.what_fr) == ("component NOPE", "rubrique NOPE")


def test_overtime_multiplier_by_band():
    rules = synthetic_rule_set()
    assert rules.overtime_multiplier("day") == D("1.5")
    assert rules.overtime_multiplier("night") == D(2)


def test_a_band_without_rate_makes_the_rule_set_incomplete():
    rules = replace(synthetic_rule_set(), overtime_rates=())
    with pytest.raises(RuleSetIncomplete):
        rules.overtime_multiplier("day")


def test_brackets_come_back_sorted_per_tax_code():
    rules = synthetic_rule_set()
    assert rules.tax_codes() == ("TAX",)
    assert [bracket.lower for bracket in rules.brackets_for("TAX")] == [0, 100000, 300000]


def test_the_annualised_variant_uses_yearly_bounds():
    brackets = synthetic_rule_set(annualised=True).brackets_for("TAX")
    assert [(b.lower, b.upper) for b in brackets] == [(0, 1200000), (1200000, 3600000), (3600000, None)]
    assert all(b.annualised for b in brackets)


def test_lines_and_tax_round_with_their_own_settings():
    rules = synthetic_rule_set()
    assert rules.round(D("10687.5")) == 10688
    assert rules.round_tax(D("37345.7")) == 37340


def test_employer_charges_are_the_employer_charge_components():
    assert [component.code for component in synthetic_rule_set().employer_charges()] == ["EMP_TAX"]


def test_reliefs_are_found_by_tax_code():
    rules = synthetic_rule_set()
    assert rules.family_relief("TAX").mode == "percent_of_tax"
    assert rules.professional_relief("TAX").cap_monthly == D(20000)
    assert rules.family_relief("OTHER") is None
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python -m pytest modules/payroll/domain/test_money.py modules/payroll/domain/test_rules.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'modules.payroll.domain.money'`.

- [ ] **Step 3: Write `money.py`**

```python
"""XOF amounts: whole francs, Decimal only, rounded the way the rule set says."""
from __future__ import annotations

from decimal import ROUND_DOWN, ROUND_HALF_UP, ROUND_UP, Decimal

ZERO = Decimal(0)
HUNDRED = Decimal(100)
ROUND_MODES = ("half_up", "down", "up")
_ROUNDING = {"half_up": ROUND_HALF_UP, "down": ROUND_DOWN, "up": ROUND_UP}


def round_amount(value: Decimal, *, round_to: int = 1, mode: str = "half_up") -> Decimal:
    """Round to a multiple of `round_to` francs.

    'down' goes toward zero, 'up' away from zero, 'half_up' to the nearest multiple with halves
    away from zero — the same on both signs, so a negative line (unpaid absence) rounds like its
    positive twin.
    """
    if round_to < 1:
        raise ValueError("round_to must be at least 1")
    if mode not in _ROUNDING:
        raise ValueError(f"unknown round mode {mode!r}")
    step = Decimal(round_to)
    return (value / step).quantize(Decimal(1), rounding=_ROUNDING[mode]) * step


def percent_of(amount: Decimal, percent: Decimal) -> Decimal:
    """`percent` is written the way the accountant writes it: 3.6 means 3.6 %. Not rounded."""
    return amount * percent / HUNDRED
```

- [ ] **Step 4: Write `inputs.py`**

```python
"""What the engine is given and what it gives back — plain values, no database."""
from __future__ import annotations

import datetime
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

# Payslip order: what is earned, what the employee pays, the tax walk, what is withheld, then
# the employer's side (not part of the net).
SECTIONS = (
    "earning",
    "employee_contribution",
    "relief",
    "tax",
    "deduction",
    "employer_contribution",
    "employer_charge",
)
# Where a deduction comes from, in the order they are taken when the net runs short.
SOURCE_KINDS = ("carry_forward", "loan_instalment", "advance", "input")


@dataclass(frozen=True)
class ContractComponent:
    """A recurring component written on the contract (hr.contract_components)."""

    component_code: str
    amount: Decimal | None = None
    rate: Decimal | None = None


@dataclass(frozen=True)
class EmployeeInput:
    employee_id: str
    base_salary: Decimal  # monthly salary, or the day rate when pay_frequency == 'daily'
    pay_frequency: str  # 'monthly' | 'daily'
    hire_date: datetime.date
    contract_start: datetime.date
    contract_end: datetime.date | None = None
    termination_date: datetime.date | None = None
    tax_dependants: int = 0
    components: tuple[ContractComponent, ...] = ()


@dataclass(frozen=True)
class PresenceInput:
    """hr's PresenceService.month_summary for one employee (all counts are ints)."""

    scheduled_days: int = 0
    worked_days: int = 0
    unpaid_absence_days: int = 0
    paid_leave_days: int = 0
    sick_days: int = 0
    holiday_days: int = 0
    holidays_worked_days: int = 0
    ot_minutes_day: int = 0
    ot_minutes_night: int = 0
    ot_minutes_rest_holiday: int = 0


@dataclass(frozen=True)
class OneOffInput:
    """A monthly input (bonus, canteen…), an advance, a loan instalment or a carried amount."""

    component_code: str
    qty: Decimal | None = None
    amount: Decimal | None = None
    source_kind: str = "input"
    source_id: str | None = None


@dataclass(frozen=True)
class SettlementInput:
    reference_salary: Decimal
    years_of_service: Decimal
    unused_leave_days: Decimal = Decimal(0)
    notice_months: Decimal = Decimal(0)


@dataclass(frozen=True)
class PayslipLine:
    section: str
    code: str
    name_en: str
    name_fr: str
    amount: Decimal
    base: Decimal | None = None
    qty: Decimal | None = None
    rate: Decimal | None = None
    taxable: bool = False
    contributable: bool = False
    deductible: bool = False  # employee contribution that lowers the taxable base
    declaration_code: str | None = None
    display_order: int = 100
    source_kind: str | None = None
    source_id: str | None = None


def section_total(lines: Iterable[PayslipLine], section: str) -> Decimal:
    return sum((line.amount for line in lines if line.section == section), Decimal(0))
```

- [ ] **Step 5: Write `rules.py`**

```python
"""A rule set as the engine reads it.

Values come from payroll.* rows (loaded by RuleSetService.load); nothing statutory is written
here. Only the component *codes* the engine computes itself are fixed, because the engine needs
to know which row holds the base salary, the overtime bands, and so on.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass
from decimal import Decimal

from modules.payroll.domain.money import round_amount

BASE = "BASE"
UNPAID_ABSENCE = "UNPAID_ABSENCE"
SENIORITY = "SENIORITY"
OT_DAY = "OT_DAY"
OT_NIGHT = "OT_NIGHT"
OT_REST_HOLIDAY = "OT_REST_HOLIDAY"
ADVANCE = "ADVANCE"
LOAN = "LOAN"
LEAVE_INDEMNITY = "LEAVE_INDEMNITY"
NOTICE_INDEMNITY = "NOTICE_INDEMNITY"
SEVERANCE = "SEVERANCE"

OVERTIME_BANDS = ("day", "night", "rest_holiday")
OVERTIME_CODES = {"day": OT_DAY, "night": OT_NIGHT, "rest_holiday": OT_REST_HOLIDAY}

# Components the engine computes itself: code -> (kind, formula_type). A rule set must hold all
# of them before it can be confirmed; their flags (taxable, contributable) and names are data.
SYSTEM_COMPONENTS: dict[str, tuple[str, str]] = {
    BASE: ("earning", "fixed"),
    UNPAID_ABSENCE: ("earning", "per_day"),
    SENIORITY: ("earning", "rate_x_base"),
    OT_DAY: ("earning", "qty_x_rate"),
    OT_NIGHT: ("earning", "qty_x_rate"),
    OT_REST_HOLIDAY: ("earning", "qty_x_rate"),
    LEAVE_INDEMNITY: ("earning", "per_day"),
    NOTICE_INDEMNITY: ("earning", "fixed"),
    SEVERANCE: ("earning", "fixed"),
    ADVANCE: ("deduction", "fixed"),
    LOAN: ("deduction", "fixed"),
}


class RuleSetIncomplete(Exception):
    """The rule set lacks something the payslip needs (a component, an overtime rate…)."""

    def __init__(self, what_en: str, what_fr: str) -> None:
        super().__init__(what_en)
        self.what_en = what_en
        self.what_fr = what_fr


class ComponentMisuse(Exception):
    """A component is used in a way its formula cannot compute (e.g. a qty × rate on a contract)."""

    def __init__(self, message_en: str, message_fr: str) -> None:
        super().__init__(message_en)
        self.message_en = message_en
        self.message_fr = message_fr


@dataclass(frozen=True)
class ComponentRule:
    code: str
    name_en: str
    name_fr: str
    kind: str  # earning | deduction | employer_charge
    taxable: bool
    contributable: bool
    formula_type: str  # fixed | rate_x_base | qty_x_rate | per_day
    base_ref: str | None = None  # base_salary | earned_base | gross | contributable
    default_amount: Decimal | None = None
    default_rate: Decimal | None = None
    display_order: int = 100
    payslip_section: str = "earnings"
    declaration_code: str | None = None


@dataclass(frozen=True)
class ContributionRule:
    code: str
    name_en: str
    name_fr: str
    base: str  # gross | contributable
    employee_rate: Decimal
    employer_rate: Decimal
    ceiling_monthly: Decimal | None
    deductible_from_taxable: bool
    declaration_code: str
    liability_account_code: str | None = None
    display_order: int = 100


@dataclass(frozen=True)
class TaxBracket:
    tax_code: str
    lower: Decimal
    upper: Decimal | None
    rate: Decimal
    annualised: bool


@dataclass(frozen=True)
class FamilyReliefStep:
    dependants: int
    value: Decimal  # percent of the tax, or an amount per month, depending on the relief mode


@dataclass(frozen=True)
class FamilyRelief:
    tax_code: str
    mode: str  # percent_of_tax | amount
    steps: tuple[FamilyReliefStep, ...]
    cap_monthly: Decimal | None = None


@dataclass(frozen=True)
class ProfessionalRelief:
    tax_code: str
    percent: Decimal
    cap_monthly: Decimal | None = None


@dataclass(frozen=True)
class SeniorityStep:
    years_from: int
    percent: Decimal


@dataclass(frozen=True)
class OvertimeRate:
    band_code: str
    multiplier: Decimal


@dataclass(frozen=True)
class SeveranceStep:
    years_from: int
    percent_per_year: Decimal


@dataclass(frozen=True)
class RuleSet:
    id: str
    country: str
    valid_from: datetime.date
    status: str
    round_to: int
    round_mode: str
    tax_round_to: int
    tax_round_mode: str
    working_days_per_month: Decimal
    working_hours_per_month: Decimal
    settlement_reference_months: int = 12
    components: tuple[ComponentRule, ...] = ()
    contributions: tuple[ContributionRule, ...] = ()
    tax_brackets: tuple[TaxBracket, ...] = ()
    family_reliefs: tuple[FamilyRelief, ...] = ()
    professional_reliefs: tuple[ProfessionalRelief, ...] = ()
    seniority_scale: tuple[SeniorityStep, ...] = ()
    overtime_rates: tuple[OvertimeRate, ...] = ()
    severance_scale: tuple[SeveranceStep, ...] = ()

    def component(self, code: str) -> ComponentRule | None:
        return next((component for component in self.components if component.code == code), None)

    def require(self, code: str) -> ComponentRule:
        component = self.component(code)
        if component is None:
            raise RuleSetIncomplete(f"component {code}", f"rubrique {code}")
        return component

    def overtime_multiplier(self, band: str) -> Decimal:
        rate = next((rate for rate in self.overtime_rates if rate.band_code == band), None)
        if rate is None:
            raise RuleSetIncomplete(f"overtime rate for band {band}", f"taux d'heures supplémentaires de la tranche {band}")
        return rate.multiplier

    def tax_codes(self) -> tuple[str, ...]:
        return tuple(sorted({bracket.tax_code for bracket in self.tax_brackets}))

    def brackets_for(self, tax_code: str) -> tuple[TaxBracket, ...]:
        return tuple(sorted((b for b in self.tax_brackets if b.tax_code == tax_code), key=lambda b: b.lower))

    def family_relief(self, tax_code: str) -> FamilyRelief | None:
        return next((relief for relief in self.family_reliefs if relief.tax_code == tax_code), None)

    def professional_relief(self, tax_code: str) -> ProfessionalRelief | None:
        return next((relief for relief in self.professional_reliefs if relief.tax_code == tax_code), None)

    def employer_charges(self) -> tuple[ComponentRule, ...]:
        charges = [component for component in self.components if component.kind == "employer_charge"]
        return tuple(sorted(charges, key=lambda component: (component.display_order, component.code)))

    def round(self, value: Decimal) -> Decimal:
        return round_amount(value, round_to=self.round_to, mode=self.round_mode)

    def round_tax(self, value: Decimal) -> Decimal:
        return round_amount(value, round_to=self.tax_round_to, mode=self.tax_round_mode)
```

- [ ] **Step 6: Write `synthetic.py` (test rules — round numbers, deliberately not Mali)**

```python
"""A synthetic rule set with round numbers, for engine tests only.

It is NOT the Mali rule set and must never be used to pay anyone: its numbers are chosen so a
payslip can be computed by hand. The Mali draft values live in scripts/payroll_mali_rules.py
and are corrected there by the accountant without touching these tests.
"""
from __future__ import annotations

import datetime
from dataclasses import replace
from decimal import Decimal

from modules.payroll.domain.inputs import EmployeeInput
from modules.payroll.domain.rules import (
    ComponentRule,
    ContributionRule,
    FamilyRelief,
    FamilyReliefStep,
    OvertimeRate,
    ProfessionalRelief,
    RuleSet,
    SeniorityStep,
    SeveranceStep,
    TaxBracket,
)

D = Decimal

_MONTHLY_BRACKETS = ((0, 100000, 0), (100000, 300000, 10), (300000, None, 20))


def _component(code, name_en, name_fr, kind, *, taxable=False, contributable=False, formula="fixed",
               base_ref=None, amount=None, rate=None, order=100, section=None, declaration=None) -> ComponentRule:
    default_section = {"earning": "earnings", "deduction": "deductions", "employer_charge": "employer"}[kind]
    return ComponentRule(
        code=code, name_en=name_en, name_fr=name_fr, kind=kind, taxable=taxable, contributable=contributable,
        formula_type=formula, base_ref=base_ref,
        default_amount=None if amount is None else D(amount), default_rate=None if rate is None else D(rate),
        display_order=order, payslip_section=section or default_section, declaration_code=declaration,
    )


def synthetic_rule_set(*, status: str = "confirmed", annualised: bool = False) -> RuleSet:
    factor = 12 if annualised else 1
    brackets = tuple(
        TaxBracket(tax_code="TAX", lower=D(lower * factor), upper=None if upper is None else D(upper * factor),
                   rate=D(rate), annualised=annualised)
        for lower, upper, rate in _MONTHLY_BRACKETS
    )
    return RuleSet(
        id="synthetic",
        country="ZZ",
        valid_from=datetime.date(2020, 1, 1),
        status=status,
        round_to=1,
        round_mode="half_up",
        tax_round_to=10,
        tax_round_mode="down",
        working_days_per_month=D(20),
        working_hours_per_month=D(160),
        components=(
            _component("BASE", "Base salary", "Salaire de base", "earning", taxable=True, contributable=True, order=10),
            _component("UNPAID_ABSENCE", "Unpaid absence", "Absence non payée", "earning", taxable=True, contributable=True, formula="per_day", order=11),
            _component("SENIORITY", "Seniority bonus", "Prime d'ancienneté", "earning", taxable=True, contributable=True, formula="rate_x_base", base_ref="earned_base", order=20),
            _component("OT_DAY", "Overtime (day)", "Heures supplémentaires (jour)", "earning", taxable=True, contributable=True, formula="qty_x_rate", order=30),
            _component("OT_NIGHT", "Overtime (night)", "Heures supplémentaires (nuit)", "earning", taxable=True, contributable=True, formula="qty_x_rate", order=31),
            _component("OT_REST_HOLIDAY", "Overtime (rest day / holiday)", "Heures supplémentaires (repos / férié)", "earning", taxable=True, contributable=True, formula="qty_x_rate", order=32),
            _component("HOUSING", "Housing allowance", "Indemnité de logement", "earning", taxable=True, contributable=True, order=40),
            _component("TRANSPORT", "Transport allowance", "Indemnité de transport", "earning", order=41),
            _component("MEAL", "Meal allowance", "Prime de panier", "earning", formula="per_day", amount=500, order=42),
            _component("BONUS", "Bonus", "Prime exceptionnelle", "earning", taxable=True, contributable=True, order=50),
            _component("LEAVE_INDEMNITY", "Paid-leave indemnity", "Indemnité compensatrice de congés", "earning", taxable=True, contributable=True, formula="per_day", order=60),
            _component("NOTICE_INDEMNITY", "Notice indemnity", "Indemnité de préavis", "earning", taxable=True, contributable=True, order=61),
            _component("SEVERANCE", "Severance pay", "Indemnité de licenciement", "earning", order=62),
            _component("ADVANCE", "Salary advance", "Avance sur salaire", "deduction", order=80),
            _component("LOAN", "Loan instalment", "Échéance de prêt", "deduction", order=81),
            _component("CANTEEN", "Canteen", "Cantine", "deduction", order=82),
            _component("EMP_TAX", "Employer payroll tax", "Taxe patronale", "employer_charge", formula="rate_x_base", base_ref="gross", rate=2, order=90, declaration="EMP_TAX"),
        ),
        contributions=(
            ContributionRule(code="PENSION", name_en="Pension", name_fr="Retraite", base="contributable",
                             employee_rate=D(5), employer_rate=D(10), ceiling_monthly=D(500000),
                             deductible_from_taxable=True, declaration_code="SOCIAL", display_order=10),
            ContributionRule(code="HEALTH", name_en="Health", name_fr="Santé", base="contributable",
                             employee_rate=D(2), employer_rate=D(3), ceiling_monthly=None,
                             deductible_from_taxable=True, declaration_code="HEALTH", display_order=20),
        ),
        tax_brackets=brackets,
        family_reliefs=(
            FamilyRelief(tax_code="TAX", mode="percent_of_tax",
                         steps=(FamilyReliefStep(1, D(10)), FamilyReliefStep(2, D(20))), cap_monthly=None),
        ),
        professional_reliefs=(ProfessionalRelief(tax_code="TAX", percent=D(10), cap_monthly=D(20000)),),
        seniority_scale=(SeniorityStep(3, D(3)), SeniorityStep(5, D(5))),
        overtime_rates=(OvertimeRate("day", D("1.5")), OvertimeRate("night", D(2)), OvertimeRate("rest_holiday", D(2))),
        severance_scale=(SeveranceStep(0, D(20)), SeveranceStep(5, D(25)), SeveranceStep(10, D(30))),
    )


def synthetic_employee(**changes) -> EmployeeInput:
    """400 000 a month, hired 2021-09-01, no end, no dependants — tests change what they need."""
    base = EmployeeInput(
        employee_id="E1",
        base_salary=D(400000),
        pay_frequency="monthly",
        hire_date=datetime.date(2021, 9, 1),
        contract_start=datetime.date(2021, 9, 1),
    )
    return replace(base, **changes)
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest modules/payroll/domain/test_money.py modules/payroll/domain/test_rules.py -q`
Expected: `14 passed`.

- [ ] **Step 8: Commit**

```bash
git add backend/modules/payroll/domain/money.py backend/modules/payroll/domain/inputs.py backend/modules/payroll/domain/rules.py backend/modules/payroll/domain/synthetic.py backend/modules/payroll/domain/test_money.py backend/modules/payroll/domain/test_rules.py
git commit -m "feat(payroll): money rounding, engine inputs and rule-set value objects

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Rule row validation and the confirmation gate

**Files:**
- Create: `backend/modules/payroll/domain/rule_validation.py`
- Test: `backend/modules/payroll/domain/test_rule_validation.py`

**Interfaces:**
- Consumes: `rules.*` (Task 2), `money.ROUND_MODES`, `core.domain.result.Err/Ok/Result`.
- Produces (all return `Result[dict]` with the cleaned row, or `Err("RULE_INVALID", en, fr)`):
  `validate_rule_set_header(values)`, `validate_component(values)`, `validate_contribution(values)`, `validate_tax_bracket(values)`, `validate_tax_relief(values)`, `validate_seniority_step(values)`, `validate_overtime_rate(values)`, `validate_severance_step(values)`;
  `relief_from_parameters(tax_code: str, kind: str, parameters: dict) -> FamilyRelief | ProfessionalRelief` (raises `ValueError` on bad data);
  `relief_parameters(relief: FamilyRelief | ProfessionalRelief) -> dict` (inverse, decimals as strings);
  `check_complete(rule_set: RuleSet) -> list[tuple[str, str]]` (English, French problem pairs; empty = confirmable);
  constant `COUNTRY` (compiled regex `^[A-Z]{2}$`).
- Cleaned-row keys equal the DB column names of Task 1 (e.g. brackets use `lower_bound`/`upper_bound`).

- [ ] **Step 1: Write the failing tests**

Create `backend/modules/payroll/domain/test_rule_validation.py`:

```python
import datetime
from dataclasses import replace
from decimal import Decimal

from core.domain.result import Err, Ok
from modules.payroll.domain.rule_validation import (
    check_complete,
    relief_from_parameters,
    relief_parameters,
    validate_component,
    validate_contribution,
    validate_rule_set_header,
    validate_tax_bracket,
    validate_tax_relief,
)
from modules.payroll.domain.rules import TaxBracket
from modules.payroll.domain.synthetic import synthetic_rule_set

D = Decimal


def _component(**changes):
    values = {"code": "housing", "name_en": "Housing", "name_fr": "Logement", "kind": "earning", "formula_type": "fixed",
              "taxable": True, "contributable": True}
    values.update(changes)
    return values


def test_a_header_gets_its_defaults():
    result = validate_rule_set_header({"country": "ml", "name": "Mali 2026", "valid_from": datetime.date(2026, 1, 1),
                                       "working_days_per_month": "26", "working_hours_per_month": 173.33})
    assert isinstance(result, Ok)
    assert result.value["country"] == "ML"
    assert (result.value["round_to"], result.value["round_mode"]) == (1, "half_up")
    assert result.value["settlement_reference_months"] == 12
    assert result.value["working_hours_per_month"] == D("173.33")


def test_a_header_starting_mid_month_is_refused_in_both_languages():
    result = validate_rule_set_header({"country": "ML", "name": "x", "valid_from": datetime.date(2026, 1, 15),
                                       "working_days_per_month": 26, "working_hours_per_month": 173})
    assert isinstance(result, Err) and result.code == "RULE_INVALID"
    assert "first day" in result.message and "premier jour" in result.message_fr


def test_a_component_code_is_normalised_to_upper_case():
    result = validate_component(_component())
    assert isinstance(result, Ok) and result.value["code"] == "HOUSING"
    assert result.value["payslip_section"] == "earnings"


def test_a_rate_x_base_component_needs_its_base():
    result = validate_component(_component(formula_type="rate_x_base"))
    assert isinstance(result, Err) and "base" in result.message


def test_an_earning_cannot_be_computed_on_the_gross():
    result = validate_component(_component(formula_type="rate_x_base", base_ref="gross"))
    assert isinstance(result, Err)


def test_a_system_code_keeps_the_kind_the_engine_expects():
    result = validate_component(_component(code="ADVANCE"))
    assert isinstance(result, Err) and "ADVANCE" in result.message


def test_only_earnings_carry_tax_and_contribution_flags():
    result = validate_component(_component(code="CANTEEN", kind="deduction"))
    assert isinstance(result, Ok)
    assert (result.value["taxable"], result.value["contributable"]) == (False, False)


def test_a_contribution_rate_is_a_percent_and_a_ceiling_is_whole_francs():
    base = {"code": "PENSION", "name_en": "Pension", "name_fr": "Retraite", "base": "contributable",
            "employee_rate": "5", "employer_rate": "10", "declaration_code": "social"}
    assert isinstance(validate_contribution(base), Ok)
    assert isinstance(validate_contribution({**base, "employee_rate": 120}), Err)
    refused = validate_contribution({**base, "ceiling_monthly": "1000.5"})
    assert isinstance(refused, Err) and "francs entiers" in refused.message_fr


def test_a_bracket_upper_bound_is_above_its_lower_bound():
    assert isinstance(validate_tax_bracket({"tax_code": "its", "lower_bound": 0, "upper_bound": 100, "rate": 5}), Ok)
    assert isinstance(validate_tax_bracket({"tax_code": "ITS", "lower_bound": 100, "upper_bound": 100, "rate": 5}), Err)


def test_relief_parameters_are_parsed_and_normalised():
    result = validate_tax_relief({"tax_code": "TAX", "kind": "family", "parameters": {
        "mode": "percent_of_tax", "steps": [{"dependants": 2, "value": 20}, {"dependants": 1, "value": "10"}]}})
    assert isinstance(result, Ok)
    assert result.value["parameters"] == {"mode": "percent_of_tax", "cap_monthly": None,
                                          "steps": [{"dependants": 1, "value": "10"}, {"dependants": 2, "value": "20"}]}
    assert isinstance(validate_tax_relief({"tax_code": "TAX", "kind": "family", "parameters": {"mode": "amount", "steps": []}}), Err)
    assert isinstance(validate_tax_relief({"tax_code": "TAX", "kind": "professional_expenses", "parameters": {"percent": 150}}), Err)


def test_relief_parameters_round_trip():
    relief = synthetic_rule_set().family_relief("TAX")
    assert relief_from_parameters("TAX", "family", relief_parameters(relief)) == relief


def test_the_synthetic_rule_set_is_complete():
    assert check_complete(synthetic_rule_set()) == []


def test_a_missing_system_component_or_band_blocks_confirmation():
    rules = synthetic_rule_set()
    problems = check_complete(replace(rules, components=tuple(c for c in rules.components if c.code != "SEVERANCE"),
                                      overtime_rates=rules.overtime_rates[:2]))
    assert ("component SEVERANCE is missing", "la rubrique SEVERANCE manque") in problems
    assert any("rest_holiday" in english for english, _ in problems)


def test_bracket_gaps_overlaps_and_mixed_periods_block_confirmation():
    rules = synthetic_rule_set()
    gap = (TaxBracket("TAX", D(0), D(100000), D(0), False), TaxBracket("TAX", D(150000), None, D(10), False))
    assert any("gap or overlap" in english for english, _ in check_complete(replace(rules, tax_brackets=gap)))
    closed = (TaxBracket("TAX", D(0), D(100000), D(0), False),)
    assert any("open-ended" in english for english, _ in check_complete(replace(rules, tax_brackets=closed)))
    mixed = (TaxBracket("TAX", D(0), D(100000), D(0), False), TaxBracket("TAX", D(100000), None, D(10), True))
    assert any("annual and monthly" in english for english, _ in check_complete(replace(rules, tax_brackets=mixed)))
    late_start = (TaxBracket("TAX", D(10), None, D(10), False),)
    assert any("not 0" in english for english, _ in check_complete(replace(rules, tax_brackets=late_start)))
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python -m pytest modules/payroll/domain/test_rule_validation.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'modules.payroll.domain.rule_validation'`.

- [ ] **Step 3: Write `rule_validation.py`**

```python
"""Checks on rule rows before they are stored, and on a whole rule set before it is confirmed.

Each validator takes the values an admin typed (strings, ints, floats or Decimals) and returns
the cleaned row, keyed by the DB column names, or Err("RULE_INVALID", english, french).
"""
from __future__ import annotations

import datetime
import re
from decimal import Decimal, InvalidOperation
from typing import Any

from core.domain.result import Err, Ok, Result
from modules.payroll.domain.money import ROUND_MODES
from modules.payroll.domain.rules import (
    OVERTIME_BANDS,
    SYSTEM_COMPONENTS,
    FamilyRelief,
    FamilyReliefStep,
    ProfessionalRelief,
    RuleSet,
)

CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,31}$")
COUNTRY = re.compile(r"^[A-Z]{2}$")
COMPONENT_KINDS = ("earning", "deduction", "employer_charge")
FORMULA_TYPES = ("fixed", "rate_x_base", "qty_x_rate", "per_day")
BASE_REFS = ("base_salary", "earned_base", "gross", "contributable")
PAYSLIP_SECTIONS = ("earnings", "deductions", "employer")
CONTRIBUTION_BASES = ("gross", "contributable")
RELIEF_KINDS = ("family", "professional_expenses")
FAMILY_MODES = ("percent_of_tax", "amount")
_SECTION_FOR_KIND = {"earning": "earnings", "deduction": "deductions", "employer_charge": "employer"}
_HUNDRED = Decimal(100)


class _Invalid(ValueError):
    def __init__(self, english: str, french: str) -> None:
        super().__init__(english)
        self.english = english
        self.french = french


def _refused(problem: _Invalid) -> Err:
    return Err("RULE_INVALID", problem.english, problem.french)


def _missing(values: dict[str, Any], name: str) -> bool:
    raw = values.get(name)
    return raw is None or (isinstance(raw, str) and raw.strip() == "")


def _decimal(values, name, *, required=True, minimum=None, maximum=None) -> Decimal | None:
    if _missing(values, name):
        if required:
            raise _Invalid(f"{name} is required", f"{name} est obligatoire")
        return None
    raw = values[name]
    if isinstance(raw, bool):
        raise _Invalid(f"{name} must be a number", f"{name} doit être un nombre")
    try:
        value = raw if isinstance(raw, Decimal) else Decimal(str(raw).strip().replace(",", "."))
    except (InvalidOperation, ValueError):
        raise _Invalid(f"{name} must be a number", f"{name} doit être un nombre") from None
    if not value.is_finite():
        raise _Invalid(f"{name} must be a number", f"{name} doit être un nombre")
    if minimum is not None and value < minimum:
        raise _Invalid(f"{name} must be at least {minimum}", f"{name} doit être au moins {minimum}")
    if maximum is not None and value > maximum:
        raise _Invalid(f"{name} must be at most {maximum}", f"{name} doit être au plus {maximum}")
    return value


def _money(values, name, *, required=True, minimum=Decimal(0)) -> Decimal | None:
    value = _decimal(values, name, required=required, minimum=minimum)
    if value is not None and value != value.to_integral_value():
        raise _Invalid(f"{name} is in whole francs", f"{name} s'exprime en francs entiers")
    return value


def _percent(values, name, *, required=True) -> Decimal | None:
    return _decimal(values, name, required=required, minimum=Decimal(0), maximum=_HUNDRED)


def _integer(values, name, *, minimum=0, default=None) -> int:
    if _missing(values, name):
        if default is None:
            raise _Invalid(f"{name} is required", f"{name} est obligatoire")
        return default
    value = _decimal(values, name, minimum=Decimal(minimum))
    if value != value.to_integral_value():
        raise _Invalid(f"{name} must be a whole number", f"{name} doit être un nombre entier")
    return int(value)


def _text(values, name, *, required=True) -> str | None:
    if _missing(values, name):
        if required:
            raise _Invalid(f"{name} is required", f"{name} est obligatoire")
        return None
    return str(values[name]).strip()


def _code(values, name, *, required=True) -> str | None:
    text = _text(values, name, required=required)
    if text is None:
        return None
    code = text.upper()
    if not CODE.match(code):
        raise _Invalid(f"{name} uses capitals, digits and _ (e.g. OT_DAY)",
                       f"{name} s'écrit en majuscules, chiffres et _ (ex. OT_DAY)")
    return code


def _choice(values, name, choices, *, default=None, required=True) -> str | None:
    if _missing(values, name):
        if default is not None:
            return default
        if required:
            raise _Invalid(f"{name} is required", f"{name} est obligatoire")
        return None
    value = str(values[name]).strip()
    if value not in choices:
        allowed = ", ".join(choices)
        raise _Invalid(f"{name} must be one of {allowed}", f"{name} doit valoir l'une de ces valeurs : {allowed}")
    return value


def _flag(values, name, *, default=False) -> bool:
    raw = values.get(name, default)
    if raw is None:
        return default
    if not isinstance(raw, bool):
        raise _Invalid(f"{name} is true or false", f"{name} vaut vrai ou faux")
    return raw


def validate_rule_set_header(values: dict[str, Any]) -> Result[dict[str, Any]]:
    try:
        country = (_text(values, "country") or "").upper()
        if not COUNTRY.match(country):
            raise _Invalid("country is a two-letter ISO code (e.g. ML)", "le pays est un code ISO à deux lettres (ex. ML)")
        valid_from = values.get("valid_from")
        if not isinstance(valid_from, datetime.date) or valid_from.day != 1:
            raise _Invalid("valid_from is the first day of a month", "valid_from est le premier jour d'un mois")
        return Ok({
            "country": country,
            "name": _text(values, "name"),
            "valid_from": valid_from,
            "round_to": _integer(values, "round_to", minimum=1, default=1),
            "round_mode": _choice(values, "round_mode", ROUND_MODES, default="half_up"),
            "tax_round_to": _integer(values, "tax_round_to", minimum=1, default=1),
            "tax_round_mode": _choice(values, "tax_round_mode", ROUND_MODES, default="half_up"),
            "working_days_per_month": _decimal(values, "working_days_per_month", minimum=Decimal(1), maximum=Decimal(31)),
            "working_hours_per_month": _decimal(values, "working_hours_per_month", minimum=Decimal(1), maximum=Decimal(744)),
            "settlement_reference_months": _integer(values, "settlement_reference_months", minimum=1, default=12),
            "notes": _text(values, "notes", required=False),
        })
    except _Invalid as problem:
        return _refused(problem)


def validate_component(values: dict[str, Any]) -> Result[dict[str, Any]]:
    try:
        code = _code(values, "code")
        kind = _choice(values, "kind", COMPONENT_KINDS)
        formula = _choice(values, "formula_type", FORMULA_TYPES)
        base_ref = _choice(values, "base_ref", BASE_REFS, required=False)
        if formula == "rate_x_base" and base_ref is None:
            raise _Invalid("a rate_x_base component needs its base (base_ref)",
                           "une rubrique taux × base doit indiquer sa base (base_ref)")
        if kind == "earning" and base_ref in ("gross", "contributable"):
            raise _Invalid("an earning cannot be computed on the gross it is part of",
                           "un gain ne peut pas être calculé sur le brut dont il fait partie")
        if kind == "employer_charge" and formula not in ("fixed", "rate_x_base"):
            raise _Invalid("an employer charge is fixed or a rate × base", "une charge patronale est fixe ou un taux × base")
        if code in SYSTEM_COMPONENTS and SYSTEM_COMPONENTS[code] != (kind, formula):
            expected_kind, expected_formula = SYSTEM_COMPONENTS[code]
            raise _Invalid(f"{code} is computed by the engine as {expected_kind} / {expected_formula}",
                           f"{code} est calculée par le moteur en {expected_kind} / {expected_formula}")
        is_earning = kind == "earning"
        return Ok({
            "code": code,
            "name_en": _text(values, "name_en"),
            "name_fr": _text(values, "name_fr"),
            "kind": kind,
            "taxable": _flag(values, "taxable") if is_earning else False,
            "contributable": _flag(values, "contributable") if is_earning else False,
            "formula_type": formula,
            "base_ref": base_ref,
            "default_amount": _money(values, "default_amount", required=False),
            "default_rate": _percent(values, "default_rate", required=False),
            "display_order": _integer(values, "display_order", minimum=0, default=100),
            "payslip_section": _choice(values, "payslip_section", PAYSLIP_SECTIONS, default=_SECTION_FOR_KIND[kind]),
            "declaration_code": _code(values, "declaration_code", required=False),
        })
    except _Invalid as problem:
        return _refused(problem)


def validate_contribution(values: dict[str, Any]) -> Result[dict[str, Any]]:
    try:
        return Ok({
            "code": _code(values, "code"),
            "name_en": _text(values, "name_en"),
            "name_fr": _text(values, "name_fr"),
            "base": _choice(values, "base", CONTRIBUTION_BASES),
            "employee_rate": _percent(values, "employee_rate", required=False) or Decimal(0),
            "employer_rate": _percent(values, "employer_rate", required=False) or Decimal(0),
            "ceiling_monthly": _money(values, "ceiling_monthly", required=False, minimum=Decimal(1)),
            "deductible_from_taxable": _flag(values, "deductible_from_taxable", default=True),
            "declaration_code": _code(values, "declaration_code"),
            "liability_account_code": _text(values, "liability_account_code", required=False),
            "display_order": _integer(values, "display_order", minimum=0, default=100),
        })
    except _Invalid as problem:
        return _refused(problem)


def validate_tax_bracket(values: dict[str, Any]) -> Result[dict[str, Any]]:
    try:
        lower = _money(values, "lower_bound")
        upper = _money(values, "upper_bound", required=False)
        if upper is not None and upper <= lower:
            raise _Invalid("upper_bound must be above lower_bound", "upper_bound doit être supérieur à lower_bound")
        return Ok({
            "tax_code": _code(values, "tax_code"),
            "lower_bound": lower,
            "upper_bound": upper,
            "rate": _percent(values, "rate"),
            "annualised": _flag(values, "annualised"),
        })
    except _Invalid as problem:
        return _refused(problem)


def _family_relief(tax_code: str, parameters: dict[str, Any]) -> FamilyRelief:
    mode = _choice(parameters, "mode", FAMILY_MODES)
    raw_steps = parameters.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise _Invalid("a family relief needs at least one step {dependants, value}",
                       "une réduction pour charges de famille demande au moins un palier {dependants, value}")
    steps: list[FamilyReliefStep] = []
    for raw in raw_steps:
        if not isinstance(raw, dict):
            raise _Invalid("each step is {dependants, value}", "chaque palier est {dependants, value}")
        value = _percent(raw, "value") if mode == "percent_of_tax" else _money(raw, "value")
        steps.append(FamilyReliefStep(dependants=_integer(raw, "dependants", minimum=0), value=value))
    if len({step.dependants for step in steps}) != len(steps):
        raise _Invalid("two steps have the same number of dependants", "deux paliers ont le même nombre de personnes à charge")
    return FamilyRelief(tax_code=tax_code, mode=mode, steps=tuple(sorted(steps, key=lambda step: step.dependants)),
                        cap_monthly=_money(parameters, "cap_monthly", required=False))


def _professional_relief(tax_code: str, parameters: dict[str, Any]) -> ProfessionalRelief:
    return ProfessionalRelief(tax_code=tax_code, percent=_percent(parameters, "percent"),
                              cap_monthly=_money(parameters, "cap_monthly", required=False))


def relief_from_parameters(tax_code: str, kind: str, parameters: dict[str, Any]) -> FamilyRelief | ProfessionalRelief:
    """Stored JSON -> domain relief. Raises ValueError (an _Invalid) on data that was never validated."""
    if kind == "family":
        return _family_relief(tax_code, parameters)
    if kind == "professional_expenses":
        return _professional_relief(tax_code, parameters)
    raise _Invalid(f"unknown relief kind {kind}", f"type d'abattement inconnu {kind}")


def relief_parameters(relief: FamilyRelief | ProfessionalRelief) -> dict[str, Any]:
    """Domain relief -> the JSON stored in payroll.tax_reliefs.parameters (decimals as strings)."""
    cap = None if relief.cap_monthly is None else str(relief.cap_monthly)
    if isinstance(relief, FamilyRelief):
        return {"mode": relief.mode, "cap_monthly": cap,
                "steps": [{"dependants": step.dependants, "value": str(step.value)} for step in relief.steps]}
    return {"percent": str(relief.percent), "cap_monthly": cap}


def validate_tax_relief(values: dict[str, Any]) -> Result[dict[str, Any]]:
    try:
        tax_code = _code(values, "tax_code")
        kind = _choice(values, "kind", RELIEF_KINDS)
        parameters = values.get("parameters")
        if not isinstance(parameters, dict):
            raise _Invalid("parameters is a JSON object", "parameters est un objet JSON")
        relief = relief_from_parameters(tax_code, kind, parameters)
        return Ok({"tax_code": tax_code, "kind": kind, "parameters": relief_parameters(relief)})
    except _Invalid as problem:
        return _refused(problem)


def validate_seniority_step(values: dict[str, Any]) -> Result[dict[str, Any]]:
    try:
        return Ok({"years_from": _integer(values, "years_from", minimum=0), "percent": _percent(values, "percent")})
    except _Invalid as problem:
        return _refused(problem)


def validate_overtime_rate(values: dict[str, Any]) -> Result[dict[str, Any]]:
    try:
        return Ok({
            "band_code": _choice(values, "band_code", OVERTIME_BANDS),
            "multiplier": _decimal(values, "multiplier", minimum=Decimal(1), maximum=Decimal(10)),
        })
    except _Invalid as problem:
        return _refused(problem)


def validate_severance_step(values: dict[str, Any]) -> Result[dict[str, Any]]:
    try:
        return Ok({"years_from": _integer(values, "years_from", minimum=0),
                   "percent_per_year": _percent(values, "percent_per_year")})
    except _Invalid as problem:
        return _refused(problem)


def _bound(value: Decimal | None) -> str:
    return "∞" if value is None else str(value)


def check_complete(rule_set: RuleSet) -> list[tuple[str, str]]:
    """What stops this rule set from being confirmed, as (english, french) pairs."""
    problems: list[tuple[str, str]] = []
    codes = {component.code for component in rule_set.components}
    for code in SYSTEM_COMPONENTS:
        if code not in codes:
            problems.append((f"component {code} is missing", f"la rubrique {code} manque"))
    bands = {rate.band_code for rate in rule_set.overtime_rates}
    for band in OVERTIME_BANDS:
        if band not in bands:
            problems.append((f"the overtime rate for band {band} is missing",
                             f"le taux d'heures supplémentaires de la tranche {band} manque"))
    tax_codes = rule_set.tax_codes()
    if not tax_codes:
        problems.append(("there is no tax bracket", "il n'y a aucune tranche d'impôt"))
    for tax_code in tax_codes:
        brackets = rule_set.brackets_for(tax_code)
        if len({bracket.annualised for bracket in brackets}) > 1:
            problems.append((f"{tax_code}: brackets mix annual and monthly amounts",
                             f"{tax_code} : les tranches mélangent montants annuels et mensuels"))
        if brackets[0].lower != 0:
            problems.append((f"{tax_code}: the first bracket starts at {brackets[0].lower}, not 0",
                             f"{tax_code} : la première tranche commence à {brackets[0].lower}, pas à 0"))
        for previous, current in zip(brackets, brackets[1:]):
            if previous.upper != current.lower:
                problems.append((f"{tax_code}: gap or overlap between {_bound(previous.upper)} and {current.lower}",
                                 f"{tax_code} : trou ou chevauchement entre {_bound(previous.upper)} et {current.lower}"))
        if brackets[-1].upper is not None:
            problems.append((f"{tax_code}: the last bracket must be open-ended",
                             f"{tax_code} : la dernière tranche doit être sans plafond"))
    for relief in (*rule_set.family_reliefs, *rule_set.professional_reliefs):
        if relief.tax_code not in tax_codes:
            problems.append((f"a relief refers to tax {relief.tax_code}, which has no bracket",
                             f"un abattement vise l'impôt {relief.tax_code}, qui n'a pas de tranche"))
    return problems
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest modules/payroll/domain/test_rule_validation.py -q`
Expected: `14 passed`.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/payroll/domain/rule_validation.py backend/modules/payroll/domain/test_rule_validation.py
git commit -m "feat(payroll): validate rule rows and gate rule-set confirmation

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---
### Task 4: Engine step 1 — earnings up to the gross

**Files:**
- Create: `backend/modules/payroll/domain/earnings.py`
- Test: `backend/modules/payroll/domain/test_earnings.py`

**Interfaces:**
- Consumes: `inputs.*`, `rules.*`, `money.percent_of/ZERO` (Task 2).
- Produces:
  - `period_end(period) -> date`, `employment_end(employee) -> date | None`, `covers_whole_month(employee, period) -> bool`
  - `coverage_factor(employee, presence, rules, period) -> Decimal` (1, or scheduled days ÷ working days per month, capped at 1)
  - `monthly_equivalent(employee, rules) -> Decimal`, `hourly_rate(employee, rules) -> Decimal`
  - `earning_line(rule, amount, *, base=None, qty=None, rate=None, source_kind=None, source_id=None) -> PayslipLine`
  - `base_salary_lines(employee, presence, rules, period) -> list[PayslipLine]` (BASE, and UNPAID_ABSENCE as a negative earning)
  - `earned_base(lines) -> Decimal` (BASE + UNPAID_ABSENCE)
  - `completed_years(start, on) -> int`, `seniority_line(employee, earned, rules, period) -> PayslipLine | None`
  - `overtime_lines(employee, presence, rules) -> list[PayslipLine]`
  - `contract_component_lines(employee, presence, rules, period, *, earned) -> list[PayslipLine]`
  - `one_off_amount(rule, item, presence) -> tuple[Decimal, Decimal | None, Decimal | None]` (amount, base, qty) — reused by `net.py`
  - `input_earning_lines(inputs, presence, rules) -> list[PayslipLine]`
- Raises `RuleSetIncomplete` / `ComponentMisuse` (turned into `Err` by the engine, Task 9).

Rules encoded here (from the spec, step 1): a month not fully inside the contract pays `base × min(scheduled_days, working_days_per_month) ÷ working_days_per_month` (presence counts scheduled days only while the contract runs); unpaid absence is taken off at `base ÷ working_days_per_month` per day, never more than the base earned; a daily contract pays the day rate per worked + paid-leave + paid-holiday day; seniority is `percent × earned base`, the percent of the highest step reached on the last day of the period (or of employment); overtime is `minutes ÷ 60 × hourly rate × band multiplier` with `hourly = monthly equivalent ÷ working_hours_per_month`; fixed contract allowances follow the same coverage factor.

- [ ] **Step 1: Write the failing tests**

Create `backend/modules/payroll/domain/test_earnings.py`:

```python
from datetime import date
from decimal import Decimal

import pytest

from modules.payroll.domain.earnings import (
    base_salary_lines,
    contract_component_lines,
    earned_base,
    input_earning_lines,
    overtime_lines,
    seniority_line,
)
from modules.payroll.domain.inputs import ContractComponent, OneOffInput, PresenceInput
from modules.payroll.domain.rules import ComponentMisuse, RuleSetIncomplete
from modules.payroll.domain.synthetic import synthetic_employee, synthetic_rule_set

D = Decimal
SEPT = date(2026, 9, 1)
RULES = synthetic_rule_set()
FULL = PresenceInput(scheduled_days=22, worked_days=22)


def amounts(lines):
    return {line.code: line.amount for line in lines}


def test_a_full_month_pays_the_whole_base():
    assert amounts(base_salary_lines(synthetic_employee(), FULL, RULES, SEPT)) == {"BASE": D(400000)}


def test_a_mid_month_hire_is_paid_scheduled_days_over_working_days():
    hired = synthetic_employee(hire_date=date(2026, 9, 11), contract_start=date(2026, 9, 11))
    lines = base_salary_lines(hired, PresenceInput(scheduled_days=14, worked_days=14), RULES, SEPT)
    assert amounts(lines) == {"BASE": D(280000)}
    assert lines[0].qty == D(14)


def test_an_exit_mid_month_is_prorated_the_same_way():
    leaving = synthetic_employee(termination_date=date(2026, 9, 15))
    assert amounts(base_salary_lines(leaving, PresenceInput(scheduled_days=10, worked_days=10), RULES, SEPT)) == {"BASE": D(200000)}


def test_more_scheduled_days_than_the_monthly_basis_never_pay_more_than_the_base():
    hired = synthetic_employee(hire_date=date(2026, 9, 2), contract_start=date(2026, 9, 2))
    assert amounts(base_salary_lines(hired, PresenceInput(scheduled_days=25), RULES, SEPT)) == {"BASE": D(400000)}


def test_unpaid_absence_days_are_taken_off_at_the_daily_rate():
    lines = base_salary_lines(synthetic_employee(), PresenceInput(scheduled_days=22, worked_days=20, unpaid_absence_days=2), RULES, SEPT)
    assert amounts(lines) == {"BASE": D(400000), "UNPAID_ABSENCE": D(-40000)}
    assert earned_base(lines) == D(360000)


def test_unpaid_absence_never_takes_more_than_the_base_earned():
    hired = synthetic_employee(hire_date=date(2026, 9, 25), contract_start=date(2026, 9, 25))
    lines = base_salary_lines(hired, PresenceInput(scheduled_days=3, unpaid_absence_days=5), RULES, SEPT)
    assert amounts(lines) == {"BASE": D(60000), "UNPAID_ABSENCE": D(-60000)}
    assert earned_base(lines) == 0


def test_a_daily_rate_is_paid_per_worked_leave_and_holiday_day():
    daily = synthetic_employee(base_salary=D(10000), pay_frequency="daily")
    presence = PresenceInput(scheduled_days=22, worked_days=18, paid_leave_days=1, holiday_days=1, unpaid_absence_days=2)
    assert amounts(base_salary_lines(daily, presence, RULES, SEPT)) == {"BASE": D(200000)}


def test_seniority_uses_the_highest_step_reached_by_the_end_of_the_month():
    assert seniority_line(synthetic_employee(hire_date=date(2021, 9, 1)), D(400000), RULES, SEPT).amount == D(20000)
    assert seniority_line(synthetic_employee(hire_date=date(2021, 10, 1)), D(400000), RULES, SEPT).amount == D(12000)
    assert seniority_line(synthetic_employee(hire_date=date(2024, 1, 1)), D(400000), RULES, SEPT) is None


def test_seniority_is_counted_up_to_the_exit_date():
    leaving = synthetic_employee(hire_date=date(2021, 9, 20), termination_date=date(2026, 9, 15))
    assert seniority_line(leaving, D(400000), RULES, SEPT).amount == D(12000)


def test_overtime_is_hours_times_hourly_rate_times_band_multiplier():
    lines = overtime_lines(synthetic_employee(), PresenceInput(ot_minutes_day=600, ot_minutes_night=90), RULES)
    assert amounts(lines) == {"OT_DAY": D(37500), "OT_NIGHT": D(7500)}
    assert [line.qty for line in lines] == [D("10.00"), D("1.50")]


def test_a_daily_workers_hourly_rate_comes_from_the_day_rate():
    daily = synthetic_employee(base_salary=D(10000), pay_frequency="daily")
    assert amounts(overtime_lines(daily, PresenceInput(ot_minutes_night=90), RULES)) == {"OT_NIGHT": D(3750)}


def test_contract_components_follow_their_formula_and_the_month_coverage():
    hired = synthetic_employee(hire_date=date(2026, 9, 11), contract_start=date(2026, 9, 11),
                               components=(ContractComponent("HOUSING", amount=D(30000)), ContractComponent("MEAL")))
    lines = contract_component_lines(hired, PresenceInput(scheduled_days=14, worked_days=12), RULES, SEPT, earned=D(280000))
    assert amounts(lines) == {"HOUSING": D(21000), "MEAL": D(6000)}


def test_a_contract_component_unknown_to_the_rule_set_is_reported():
    ghost = synthetic_employee(components=(ContractComponent("GHOST", amount=D(1)),))
    with pytest.raises(RuleSetIncomplete):
        contract_component_lines(ghost, FULL, RULES, SEPT, earned=D(400000))


def test_a_deduction_cannot_be_written_on_a_contract():
    with pytest.raises(ComponentMisuse):
        contract_component_lines(synthetic_employee(components=(ContractComponent("CANTEEN", amount=D(1)),)), FULL, RULES, SEPT, earned=D(400000))


def test_monthly_inputs_become_earning_lines_and_deductions_are_left_for_later():
    inputs = [OneOffInput("BONUS", amount=D(25000)), OneOffInput("MEAL", qty=D(5)), OneOffInput("ADVANCE", amount=D(1))]
    assert amounts(input_earning_lines(inputs, FULL, RULES)) == {"BONUS": D(25000), "MEAL": D(2500)}


def test_a_computed_component_cannot_be_typed_as_an_input():
    with pytest.raises(ComponentMisuse):
        input_earning_lines([OneOffInput("SENIORITY", amount=D(1))], FULL, RULES)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python -m pytest modules/payroll/domain/test_earnings.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'modules.payroll.domain.earnings'`.

- [ ] **Step 3: Write `earnings.py`**

```python
"""Step 1 of a payslip: everything the employee earns, up to the gross."""
from __future__ import annotations

import calendar
import datetime
from collections.abc import Iterable, Sequence
from decimal import Decimal

from modules.payroll.domain.inputs import EmployeeInput, OneOffInput, PayslipLine, PresenceInput
from modules.payroll.domain.money import ZERO, percent_of
from modules.payroll.domain.rules import (
    BASE,
    OVERTIME_BANDS,
    OVERTIME_CODES,
    SENIORITY,
    UNPAID_ABSENCE,
    ComponentMisuse,
    ComponentRule,
    RuleSet,
)

_HOURS = Decimal("0.01")


def period_end(period: datetime.date) -> datetime.date:
    return period.replace(day=calendar.monthrange(period.year, period.month)[1])


def employment_end(employee: EmployeeInput) -> datetime.date | None:
    ends = [day for day in (employee.contract_end, employee.termination_date) if day is not None]
    return min(ends) if ends else None


def covers_whole_month(employee: EmployeeInput, period: datetime.date) -> bool:
    end = employment_end(employee)
    return employee.contract_start <= period and (end is None or end >= period_end(period))


def coverage_factor(employee: EmployeeInput, presence: PresenceInput, rules: RuleSet, period: datetime.date) -> Decimal:
    """1 for a whole month; otherwise the scheduled days inside the contract over the rule set's
    working days per month, capped at 1 (presence only schedules days while the contract runs)."""
    if covers_whole_month(employee, period):
        return Decimal(1)
    return min(Decimal(presence.scheduled_days), rules.working_days_per_month) / rules.working_days_per_month


def monthly_equivalent(employee: EmployeeInput, rules: RuleSet) -> Decimal:
    if employee.pay_frequency == "daily":
        return employee.base_salary * rules.working_days_per_month
    return employee.base_salary


def hourly_rate(employee: EmployeeInput, rules: RuleSet) -> Decimal:
    return monthly_equivalent(employee, rules) / rules.working_hours_per_month


def earning_line(rule: ComponentRule, amount: Decimal, *, base: Decimal | None = None, qty: Decimal | None = None,
                 rate: Decimal | None = None, source_kind: str | None = None, source_id: str | None = None) -> PayslipLine:
    return PayslipLine(
        section="earning", code=rule.code, name_en=rule.name_en, name_fr=rule.name_fr, amount=amount,
        base=base, qty=qty, rate=rate, taxable=rule.taxable, contributable=rule.contributable,
        declaration_code=rule.declaration_code, display_order=rule.display_order,
        source_kind=source_kind, source_id=source_id,
    )


def base_salary_lines(employee: EmployeeInput, presence: PresenceInput, rules: RuleSet, period: datetime.date) -> list[PayslipLine]:
    base_rule = rules.require(BASE)
    if employee.pay_frequency == "daily":
        paid_days = presence.worked_days + presence.paid_leave_days + presence.holiday_days
        return [earning_line(base_rule, rules.round(employee.base_salary * paid_days), base=employee.base_salary, qty=Decimal(paid_days))]

    factor = coverage_factor(employee, presence, rules, period)
    base_amount = rules.round(employee.base_salary * factor)
    qty = None if factor == 1 else min(Decimal(presence.scheduled_days), rules.working_days_per_month)
    lines = [earning_line(base_rule, base_amount, base=employee.base_salary, qty=qty)]
    if presence.unpaid_absence_days > 0:
        absence_rule = rules.require(UNPAID_ABSENCE)
        day_rate = employee.base_salary / rules.working_days_per_month
        taken = min(rules.round(day_rate * presence.unpaid_absence_days), base_amount)
        lines.append(earning_line(absence_rule, -taken, base=rules.round(day_rate), qty=Decimal(presence.unpaid_absence_days)))
    return lines


def earned_base(lines: Iterable[PayslipLine]) -> Decimal:
    return sum((line.amount for line in lines if line.code in (BASE, UNPAID_ABSENCE)), ZERO)


def completed_years(start: datetime.date, on: datetime.date) -> int:
    return max(on.year - start.year - ((on.month, on.day) < (start.month, start.day)), 0)


def _seniority_date(employee: EmployeeInput, period: datetime.date) -> datetime.date:
    end = employment_end(employee)
    last = period_end(period)
    return last if end is None or end > last else end


def seniority_line(employee: EmployeeInput, earned: Decimal, rules: RuleSet, period: datetime.date) -> PayslipLine | None:
    years = completed_years(employee.hire_date, _seniority_date(employee, period))
    reached = [step for step in rules.seniority_scale if step.years_from <= years]
    if not reached or earned <= 0:
        return None
    percent = max(reached, key=lambda step: step.years_from).percent
    if percent == 0:
        return None
    return earning_line(rules.require(SENIORITY), rules.round(percent_of(earned, percent)), base=earned, qty=Decimal(years), rate=percent)


def overtime_lines(employee: EmployeeInput, presence: PresenceInput, rules: RuleSet) -> list[PayslipLine]:
    minutes = {"day": presence.ot_minutes_day, "night": presence.ot_minutes_night, "rest_holiday": presence.ot_minutes_rest_holiday}
    hourly = hourly_rate(employee, rules)
    lines: list[PayslipLine] = []
    for band in OVERTIME_BANDS:
        if minutes[band] <= 0:
            continue
        rule = rules.require(OVERTIME_CODES[band])
        multiplier = rules.overtime_multiplier(band)
        hours = Decimal(minutes[band]) / 60
        lines.append(earning_line(rule, rules.round(hours * hourly * multiplier), base=rules.round(hourly),
                                  qty=hours.quantize(_HOURS), rate=multiplier))
    return lines


def _first(*values: Decimal | None) -> Decimal:
    return next((value for value in values if value is not None), ZERO)


def contract_component_lines(employee: EmployeeInput, presence: PresenceInput, rules: RuleSet, period: datetime.date,
                             *, earned: Decimal) -> list[PayslipLine]:
    factor = coverage_factor(employee, presence, rules, period)
    lines: list[PayslipLine] = []
    for item in employee.components:
        rule = rules.require(item.component_code)
        if rule.kind != "earning":
            raise ComponentMisuse(f"{rule.code} is not an earning; only earnings are written on a contract",
                                  f"{rule.code} n'est pas un gain ; seuls les gains s'inscrivent sur un contrat")
        if rule.formula_type == "fixed":
            amount = _first(item.amount, rule.default_amount)
            lines.append(earning_line(rule, rules.round(amount * factor), base=amount))
        elif rule.formula_type == "rate_x_base":
            rate = _first(item.rate, rule.default_rate)
            base = earned if rule.base_ref == "earned_base" else monthly_equivalent(employee, rules) * factor
            lines.append(earning_line(rule, rules.round(percent_of(base, rate)), base=rules.round(base), rate=rate))
        elif rule.formula_type == "per_day":
            per_day = _first(item.amount, rule.default_amount)
            lines.append(earning_line(rule, rules.round(per_day * presence.worked_days), base=per_day, qty=Decimal(presence.worked_days)))
        else:
            raise ComponentMisuse(f"{rule.code} is a quantity × rate; type its quantity as a monthly input",
                                  f"{rule.code} est une quantité × taux ; saisissez sa quantité en variable du mois")
    return [line for line in lines if line.amount != 0]


def one_off_amount(rule: ComponentRule, item: OneOffInput, presence: PresenceInput) -> tuple[Decimal, Decimal | None, Decimal | None]:
    """(amount, base, qty) of a typed input, by its component's formula."""
    if rule.formula_type == "fixed":
        return _first(item.amount, rule.default_amount), None, None
    if rule.formula_type == "qty_x_rate":
        unit = _first(item.amount, rule.default_amount)
        qty = _first(item.qty)
        return qty * unit, unit, qty
    if rule.formula_type == "per_day":
        unit = _first(item.amount, rule.default_amount)
        days = item.qty if item.qty is not None else Decimal(presence.worked_days)
        return unit * days, unit, days
    raise ComponentMisuse(f"{rule.code} is computed from a base; it cannot be typed as an input",
                          f"{rule.code} se calcule sur une base ; elle ne se saisit pas en variable")


def input_earning_lines(inputs: Sequence[OneOffInput], presence: PresenceInput, rules: RuleSet) -> list[PayslipLine]:
    lines: list[PayslipLine] = []
    for item in inputs:
        rule = rules.require(item.component_code)
        if rule.kind != "earning":
            continue
        amount, base, qty = one_off_amount(rule, item, presence)
        rounded = rules.round(amount)
        if rounded != 0:
            lines.append(earning_line(rule, rounded, base=base, qty=qty, source_kind=item.source_kind, source_id=item.source_id))
    return lines
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest modules/payroll/domain/test_earnings.py -q`
Expected: `16 passed`.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/payroll/domain/earnings.py backend/modules/payroll/domain/test_earnings.py
git commit -m "feat(payroll): engine step 1, earnings up to the gross

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Engine steps 2–3 — contributable base, ceilings, contributions

**Files:**
- Create: `backend/modules/payroll/domain/contributions.py`
- Test: `backend/modules/payroll/domain/test_contributions.py`

**Interfaces:**
- Consumes: `PayslipLine`, `RuleSet`, `ContributionRule`, `percent_of`.
- Produces: `contributable_earnings(lines) -> Decimal` (never below 0), `contribution_base(rule, *, gross, contributable) -> Decimal`, `contribution_lines(rules, *, gross, contributable) -> list[PayslipLine]` (sections `employee_contribution` / `employer_contribution`, `deductible` set from `deductible_from_taxable` on the employee side, `declaration_code` from the rule).

- [ ] **Step 1: Write the failing tests**

Create `backend/modules/payroll/domain/test_contributions.py`:

```python
from dataclasses import replace
from decimal import Decimal

from modules.payroll.domain.contributions import contributable_earnings, contribution_lines
from modules.payroll.domain.inputs import PayslipLine
from modules.payroll.domain.rules import ContributionRule
from modules.payroll.domain.synthetic import synthetic_rule_set

D = Decimal
RULES = synthetic_rule_set()


def earning(code, amount, *, contributable=False):
    return PayslipLine(section="earning", code=code, name_en=code, name_fr=code, amount=D(amount), contributable=contributable)


def test_only_contributable_earnings_count_and_the_base_never_goes_negative():
    assert contributable_earnings([earning("BASE", 400000, contributable=True), earning("TRANSPORT", 10000)]) == D(400000)
    assert contributable_earnings([earning("UNPAID_ABSENCE", -5, contributable=True)]) == 0


def test_a_ceiling_caps_the_base_of_that_contribution_only():
    lines = contribution_lines(RULES, gross=D(610000), contributable=D(600000))
    got = {(line.section, line.code): (line.base, line.amount) for line in lines}
    assert got == {
        ("employee_contribution", "PENSION"): (D(500000), D(25000)),
        ("employer_contribution", "PENSION"): (D(500000), D(50000)),
        ("employee_contribution", "HEALTH"): (D(600000), D(12000)),
        ("employer_contribution", "HEALTH"): (D(600000), D(18000)),
    }


def test_a_contribution_on_gross_ignores_the_contributable_flag():
    solidarity = ContributionRule(code="SOLIDARITY", name_en="Solidarity", name_fr="Solidarité", base="gross",
                                  employee_rate=D(1), employer_rate=D(0), ceiling_monthly=None,
                                  deductible_from_taxable=False, declaration_code="SOL")
    lines = contribution_lines(replace(RULES, contributions=(solidarity,)), gross=D(410000), contributable=D(400000))
    assert [(line.section, line.amount, line.deductible, line.declaration_code) for line in lines] == [
        ("employee_contribution", D(4100), False, "SOL")
    ]


def test_employee_contributions_say_whether_they_lower_the_taxable_base():
    lines = contribution_lines(RULES, gross=D(100000), contributable=D(100000))
    assert all(line.deductible for line in lines if line.section == "employee_contribution")
    assert not any(line.deductible for line in lines if line.section == "employer_contribution")


def test_no_base_no_contribution():
    assert contribution_lines(RULES, gross=D(0), contributable=D(0)) == []
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python -m pytest modules/payroll/domain/test_contributions.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'modules.payroll.domain.contributions'`.

- [ ] **Step 3: Write `contributions.py`**

```python
"""Steps 2 and 3: the contributable base, each contribution's ceiling, employee and employer shares."""
from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal

from modules.payroll.domain.inputs import PayslipLine
from modules.payroll.domain.money import ZERO, percent_of
from modules.payroll.domain.rules import ContributionRule, RuleSet


def contributable_earnings(lines: Iterable[PayslipLine]) -> Decimal:
    total = sum((line.amount for line in lines if line.section == "earning" and line.contributable), ZERO)
    return max(total, ZERO)


def contribution_base(rule: ContributionRule, *, gross: Decimal, contributable: Decimal) -> Decimal:
    base = max(gross if rule.base == "gross" else contributable, ZERO)
    return base if rule.ceiling_monthly is None else min(base, rule.ceiling_monthly)


def contribution_lines(rules: RuleSet, *, gross: Decimal, contributable: Decimal) -> list[PayslipLine]:
    lines: list[PayslipLine] = []
    for rule in sorted(rules.contributions, key=lambda item: (item.display_order, item.code)):
        base = contribution_base(rule, gross=gross, contributable=contributable)
        if base <= 0:
            continue
        for section, rate in (("employee_contribution", rule.employee_rate), ("employer_contribution", rule.employer_rate)):
            amount = rules.round(percent_of(base, rate))
            if amount == 0:
                continue
            lines.append(PayslipLine(
                section=section, code=rule.code, name_en=rule.name_en, name_fr=rule.name_fr, amount=amount,
                base=base, rate=rate,
                deductible=section == "employee_contribution" and rule.deductible_from_taxable,
                declaration_code=rule.declaration_code, display_order=rule.display_order,
            ))
    return lines
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest modules/payroll/domain/test_contributions.py -q`
Expected: `5 passed`.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/payroll/domain/contributions.py backend/modules/payroll/domain/test_contributions.py
git commit -m "feat(payroll): engine steps 2-3, contributable base and contributions

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Engine step 4 — taxable base, brackets, reliefs, tax rounding

**Files:**
- Create: `backend/modules/payroll/domain/tax.py`
- Test: `backend/modules/payroll/domain/test_tax.py`

**Interfaces:**
- Consumes: `PayslipLine`, `RuleSet`, `TaxBracket`, `FamilyRelief`, `ProfessionalRelief`, `percent_of`.
- Produces: `taxable_earnings(lines)`, `deductible_contributions(lines)`, `professional_relief_amount(relief, base) -> Decimal`, `bracket_tax(brackets, amount) -> Decimal` (unrounded, progressive), `family_relief_amount(relief, tax, dependants, *, months=1) -> Decimal` (never above the tax), `tax_lines(rules, lines, dependants) -> list[PayslipLine]` — per tax code: an informational `relief` line `<TAX>_PROF_RELIEF`, a `relief` line `<TAX>_FAMILY_RELIEF` (monthly), and the `tax` line `<TAX>` whose `base` is the taxable amount and whose amount is rounded with `round_tax`.

Walk (spec step 4): `taxable = taxable earnings − deductible employee contributions − professional relief`; tax from the brackets — on `taxable × 12` when the brackets are annual, then the family relief (steps by number of dependants; the last step applies beyond it), then `÷ 12`, then the tax rounding.

- [ ] **Step 1: Write the failing tests**

Create `backend/modules/payroll/domain/test_tax.py`:

```python
from decimal import Decimal

from modules.payroll.domain.inputs import PayslipLine
from modules.payroll.domain.rules import FamilyRelief, FamilyReliefStep
from modules.payroll.domain.synthetic import synthetic_rule_set
from modules.payroll.domain.tax import bracket_tax, family_relief_amount, professional_relief_amount, tax_lines

D = Decimal
RULES = synthetic_rule_set()


def earning(code, amount, *, taxable=False):
    return PayslipLine(section="earning", code=code, name_en=code, name_fr=code, amount=D(amount), taxable=taxable)


def contribution(code, amount):
    return PayslipLine(section="employee_contribution", code=code, name_en=code, name_fr=code, amount=D(amount), deductible=True)


GOLDEN_LINES = [earning("BASE", 487500, taxable=True), earning("TRANSPORT", 10000),
                contribution("PENSION", 24375), contribution("HEALTH", 9750)]


def test_progressive_brackets():
    brackets = RULES.brackets_for("TAX")
    assert bracket_tax(brackets, D(90000)) == 0
    assert bracket_tax(brackets, D(300000)) == D(20000)
    assert bracket_tax(brackets, D(433375)) == D(46675)


def test_annual_brackets_give_the_same_tax_on_twelve_months():
    annual = synthetic_rule_set(annualised=True).brackets_for("TAX")
    assert bracket_tax(annual, D(433375) * 12) / 12 == D(46675)


def test_professional_relief_is_a_percent_with_a_cap():
    relief = RULES.professional_relief("TAX")
    assert professional_relief_amount(relief, D(453375)) == D(20000)
    assert professional_relief_amount(relief, D(150000)) == D(15000)


def test_family_relief_uses_the_step_for_the_dependants():
    relief = RULES.family_relief("TAX")
    assert family_relief_amount(relief, D(46675), 0) == 0
    assert family_relief_amount(relief, D(46675), 1) == D("4667.5")
    assert family_relief_amount(relief, D(46675), 2) == D(9335)


def test_dependants_beyond_the_last_step_keep_the_last_step():
    assert family_relief_amount(RULES.family_relief("TAX"), D(46675), 7) == D(9335)


def test_an_amount_relief_is_monthly_and_never_exceeds_the_tax():
    relief = FamilyRelief(tax_code="TAX", mode="amount", steps=(FamilyReliefStep(1, D(3000)),))
    assert family_relief_amount(relief, D(10000), 1) == D(3000)
    assert family_relief_amount(relief, D(120000), 1, months=12) == D(36000)
    assert family_relief_amount(relief, D(2000), 1) == D(2000)


def test_a_cap_limits_the_family_relief():
    relief = FamilyRelief(tax_code="TAX", mode="percent_of_tax", steps=(FamilyReliefStep(1, D(50)),), cap_monthly=D(1000))
    assert family_relief_amount(relief, D(10000), 1) == D(1000)


def test_tax_lines_walk_from_taxable_earnings_to_the_rounded_tax():
    got = {line.code: line for line in tax_lines(RULES, GOLDEN_LINES, dependants=2)}
    assert got["TAX_PROF_RELIEF"].amount == D(20000) and got["TAX_PROF_RELIEF"].section == "relief"
    assert got["TAX_FAMILY_RELIEF"].amount == D(9335)
    assert (got["TAX"].base, got["TAX"].amount, got["TAX"].section) == (D(433375), D(37340), "tax")


def test_an_annualised_rule_set_gives_the_same_monthly_tax():
    got = {line.code: line.amount for line in tax_lines(synthetic_rule_set(annualised=True), GOLDEN_LINES, dependants=2)}
    assert (got["TAX_FAMILY_RELIEF"], got["TAX"]) == (D(9335), D(37340))


def test_tax_rounding_follows_the_rule_set_not_the_line_rounding():
    lines = [earning("BASE", 261000, taxable=True), contribution("PENSION", 13050), contribution("HEALTH", 5220)]
    got = {line.code: line.amount for line in tax_lines(RULES, lines, dependants=1)}
    assert got["TAX_FAMILY_RELIEF"] == D(1227)
    assert got["TAX"] == D(11040)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python -m pytest modules/payroll/domain/test_tax.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'modules.payroll.domain.tax'`.

- [ ] **Step 3: Write `tax.py`**

```python
"""Step 4: from taxable earnings to the tax withheld (the ITS in Mali), with its reliefs."""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from decimal import Decimal

from modules.payroll.domain.inputs import PayslipLine
from modules.payroll.domain.money import ZERO, percent_of
from modules.payroll.domain.rules import FamilyRelief, ProfessionalRelief, RuleSet, TaxBracket

PROFESSIONAL_RELIEF_NAMES = ("Professional expenses relief", "Abattement pour frais professionnels")
FAMILY_RELIEF_NAMES = ("Family relief", "Réduction pour charges de famille")


def taxable_earnings(lines: Iterable[PayslipLine]) -> Decimal:
    return sum((line.amount for line in lines if line.section == "earning" and line.taxable), ZERO)


def deductible_contributions(lines: Iterable[PayslipLine]) -> Decimal:
    return sum((line.amount for line in lines if line.section == "employee_contribution" and line.deductible), ZERO)


def professional_relief_amount(relief: ProfessionalRelief, base: Decimal) -> Decimal:
    amount = percent_of(max(base, ZERO), relief.percent)
    return amount if relief.cap_monthly is None else min(amount, relief.cap_monthly)


def bracket_tax(brackets: Sequence[TaxBracket], amount: Decimal) -> Decimal:
    """Progressive tax on `amount` (brackets sorted by lower bound). Not rounded."""
    tax = ZERO
    for bracket in brackets:
        if amount <= bracket.lower:
            break
        top = amount if bracket.upper is None else min(amount, bracket.upper)
        tax += percent_of(top - bracket.lower, bracket.rate)
    return tax


def family_relief_amount(relief: FamilyRelief, tax: Decimal, dependants: int, *, months: int = 1) -> Decimal:
    """Relief for `dependants` on a tax computed over `months` months; the last step applies beyond it."""
    reached = [step for step in relief.steps if step.dependants <= dependants]
    if not reached or tax <= 0:
        return ZERO
    step = max(reached, key=lambda item: item.dependants)
    amount = percent_of(tax, step.value) if relief.mode == "percent_of_tax" else step.value * months
    if relief.cap_monthly is not None:
        amount = min(amount, relief.cap_monthly * months)
    return min(amount, tax)


def _relief_line(code: str, names: tuple[str, str], amount: Decimal, *, base: Decimal | None = None,
                 qty: Decimal | None = None, rate: Decimal | None = None) -> PayslipLine:
    return PayslipLine(section="relief", code=code, name_en=names[0], name_fr=names[1], amount=amount,
                       base=base, qty=qty, rate=rate)


def tax_lines(rules: RuleSet, lines: Sequence[PayslipLine], dependants: int) -> list[PayslipLine]:
    net_taxable = max(taxable_earnings(lines) - deductible_contributions(lines), ZERO)
    out: list[PayslipLine] = []
    for tax_code in rules.tax_codes():
        professional = rules.professional_relief(tax_code)
        professional_amount = rules.round(professional_relief_amount(professional, net_taxable)) if professional else ZERO
        if professional_amount > 0:
            out.append(_relief_line(f"{tax_code}_PROF_RELIEF", PROFESSIONAL_RELIEF_NAMES, professional_amount,
                                    base=net_taxable, rate=professional.percent))
        taxable = net_taxable - professional_amount
        brackets = rules.brackets_for(tax_code)
        months = 12 if brackets[0].annualised else 1
        tax = bracket_tax(brackets, taxable * months)
        family = rules.family_relief(tax_code)
        relief = family_relief_amount(family, tax, dependants, months=months) if family else ZERO
        if relief > 0:
            out.append(_relief_line(f"{tax_code}_FAMILY_RELIEF", FAMILY_RELIEF_NAMES, rules.round(relief / months),
                                    qty=Decimal(dependants)))
        out.append(PayslipLine(section="tax", code=tax_code, name_en=tax_code, name_fr=tax_code,
                               amount=rules.round_tax((tax - relief) / months), base=taxable,
                               declaration_code=tax_code, display_order=0))
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest modules/payroll/domain/test_tax.py -q`
Expected: `10 passed`.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/payroll/domain/tax.py backend/modules/payroll/domain/test_tax.py
git commit -m "feat(payroll): engine step 4, taxable base, brackets and reliefs

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Engine steps 5–6 — deductions, net floor with carry-forward, employer charges, totals

**Files:**
- Create: `backend/modules/payroll/domain/net.py`
- Test: `backend/modules/payroll/domain/test_net.py`

**Interfaces:**
- Consumes: `one_off_amount` (Task 4), `contributable_earnings` (Task 5), `PayslipLine`, `SOURCE_KINDS`, `section_total`.
- Produces:
  - `CarryForward(component_code: str, amount: Decimal, source_kind: str, source_id: str | None)` (frozen dataclass)
  - `PayslipTotals(gross, contributable, taxable, employee_contrib, employer_contrib, employer_charges, tax, deductions, net, employer_cost)` (frozen dataclass, all `Decimal`)
  - `deduction_lines(inputs, presence, rules) -> list[PayslipLine]` — ordered carry_forward → loan_instalment → advance → input
  - `apply_net_floor(available: Decimal, deductions) -> tuple[list[PayslipLine], list[CarryForward]]`
  - `employer_charge_lines(rules, *, gross, contributable, earned, include_fixed=True) -> list[PayslipLine]`
  - `payslip_totals(lines) -> PayslipTotals` (`net = gross − employee_contrib − tax − deductions`; `employer_cost = gross + employer_contrib + employer_charges`)

Rule (spec step 5): the net is never negative. Deductions are taken in priority order; the first one that would push the net below zero is cut to what is left, and its remainder plus every later deduction becomes a `CarryForward` for next month (reported with warning `NET_NEGATIVE` by the engine).

- [ ] **Step 1: Write the failing tests**

Create `backend/modules/payroll/domain/test_net.py`:

```python
from decimal import Decimal

from modules.payroll.domain.inputs import OneOffInput, PayslipLine, PresenceInput
from modules.payroll.domain.net import (
    CarryForward,
    PayslipTotals,
    apply_net_floor,
    deduction_lines,
    employer_charge_lines,
    payslip_totals,
)
from modules.payroll.domain.synthetic import synthetic_rule_set

D = Decimal
RULES = synthetic_rule_set()


def deduction(code, amount, kind, source_id):
    return PayslipLine(section="deduction", code=code, name_en=code, name_fr=code, amount=D(amount),
                       source_kind=kind, source_id=source_id)


def line(section, code, amount, **extra):
    return PayslipLine(section=section, code=code, name_en=code, name_fr=code, amount=D(amount), **extra)


def test_deductions_come_in_priority_order_and_earnings_are_ignored():
    inputs = [
        OneOffInput("CANTEEN", amount=D(3000), source_id="r1"),
        OneOffInput("ADVANCE", amount=D(50000), source_kind="advance", source_id="a1"),
        OneOffInput("LOAN", amount=D(20000), source_kind="loan_instalment", source_id="i1"),
        OneOffInput("CANTEEN", amount=D(5000), source_kind="carry_forward", source_id="c1"),
        OneOffInput("BONUS", amount=D(9)),
    ]
    lines = deduction_lines(inputs, PresenceInput(), RULES)
    assert [(item.code, item.source_kind) for item in lines] == [
        ("CANTEEN", "carry_forward"), ("LOAN", "loan_instalment"), ("ADVANCE", "advance"), ("CANTEEN", "input"),
    ]


def test_deductions_that_fit_are_all_kept():
    kept, carried = apply_net_floor(D(100000), [deduction("LOAN", 20000, "loan_instalment", "i1")])
    assert [item.amount for item in kept] == [D(20000)] and carried == []


def test_the_overflowing_deduction_is_cut_and_the_rest_carried():
    kept, carried = apply_net_floor(D(93000), [
        deduction("CANTEEN", 5000, "carry_forward", "c1"),
        deduction("LOAN", 20000, "loan_instalment", "i1"),
        deduction("ADVANCE", 90000, "advance", "a1"),
        deduction("CANTEEN", 3000, "input", "r1"),
    ])
    assert [(item.code, item.amount) for item in kept] == [("CANTEEN", 5000), ("LOAN", 20000), ("ADVANCE", 68000)]
    assert carried == [CarryForward("ADVANCE", D(22000), "advance", "a1"), CarryForward("CANTEEN", D(3000), "input", "r1")]


def test_nothing_left_means_everything_is_carried():
    kept, carried = apply_net_floor(D(0), [deduction("LOAN", 20000, "loan_instalment", "i1")])
    assert kept == [] and carried == [CarryForward("LOAN", D(20000), "loan_instalment", "i1")]


def test_employer_charges_apply_their_rate_to_their_base():
    lines = employer_charge_lines(RULES, gross=D(497500), contributable=D(487500), earned=D(400000))
    assert [(item.code, item.base, item.amount, item.declaration_code) for item in lines] == [
        ("EMP_TAX", D(497500), D(9950), "EMP_TAX")
    ]


def test_totals_add_up():
    lines = [
        line("earning", "BASE", 400000, taxable=True, contributable=True),
        line("earning", "TRANSPORT", 10000),
        line("employee_contribution", "PENSION", 30000),
        line("employer_contribution", "PENSION", 60000),
        line("tax", "TAX", 20000, base=D(300000)),
        line("deduction", "ADVANCE", 50000),
        line("employer_charge", "EMP_TAX", 8000),
    ]
    assert payslip_totals(lines) == PayslipTotals(
        gross=D(410000), contributable=D(400000), taxable=D(300000), employee_contrib=D(30000),
        employer_contrib=D(60000), employer_charges=D(8000), tax=D(20000), deductions=D(50000),
        net=D(310000), employer_cost=D(478000),
    )
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python -m pytest modules/payroll/domain/test_net.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'modules.payroll.domain.net'`.

- [ ] **Step 3: Write `net.py`**

```python
"""Steps 5 and 6: what is withheld, the net (never below zero), the employer's charges and cost."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from decimal import Decimal

from modules.payroll.domain.contributions import contributable_earnings
from modules.payroll.domain.earnings import one_off_amount
from modules.payroll.domain.inputs import SOURCE_KINDS, OneOffInput, PayslipLine, PresenceInput, section_total
from modules.payroll.domain.money import ZERO, percent_of
from modules.payroll.domain.rules import RuleSet


@dataclass(frozen=True)
class CarryForward:
    """A deduction (or its remainder) the net could not cover, owed next month."""

    component_code: str
    amount: Decimal
    source_kind: str
    source_id: str | None


@dataclass(frozen=True)
class PayslipTotals:
    gross: Decimal
    contributable: Decimal
    taxable: Decimal
    employee_contrib: Decimal
    employer_contrib: Decimal
    employer_charges: Decimal
    tax: Decimal
    deductions: Decimal
    net: Decimal
    employer_cost: Decimal


def deduction_lines(inputs: Sequence[OneOffInput], presence: PresenceInput, rules: RuleSet) -> list[PayslipLine]:
    lines: list[PayslipLine] = []
    for item in inputs:
        rule = rules.require(item.component_code)
        if rule.kind != "deduction":
            continue
        amount, base, qty = one_off_amount(rule, item, presence)
        rounded = rules.round(amount)
        if rounded <= 0:
            continue
        lines.append(PayslipLine(
            section="deduction", code=rule.code, name_en=rule.name_en, name_fr=rule.name_fr, amount=rounded,
            base=base, qty=qty, declaration_code=rule.declaration_code, display_order=rule.display_order,
            source_kind=item.source_kind, source_id=item.source_id,
        ))
    return sorted(lines, key=lambda line: SOURCE_KINDS.index(line.source_kind or "input"))


def apply_net_floor(available: Decimal, deductions: Sequence[PayslipLine]) -> tuple[list[PayslipLine], list[CarryForward]]:
    """Take deductions in order while the net stays at or above zero; carry the overflow."""
    kept: list[PayslipLine] = []
    carried: list[CarryForward] = []
    left = max(available, ZERO)
    for line in deductions:
        if line.amount <= left:
            kept.append(line)
            left -= line.amount
            continue
        if left > 0:
            kept.append(replace(line, amount=left))
        carried.append(CarryForward(line.code, line.amount - left, line.source_kind or "input", line.source_id))
        left = ZERO
    return kept, carried


def employer_charge_lines(rules: RuleSet, *, gross: Decimal, contributable: Decimal, earned: Decimal,
                          include_fixed: bool = True) -> list[PayslipLine]:
    """Employer charges (payroll taxes). A fixed charge is per regular payslip, so a correction
    payslip (include_fixed=False) only carries the rate-based ones."""
    bases = {"gross": gross, "contributable": contributable, "earned_base": earned, "base_salary": earned}
    lines: list[PayslipLine] = []
    for rule in rules.employer_charges():
        if rule.formula_type == "rate_x_base":
            base = max(bases[rule.base_ref or "gross"], ZERO)
            rate = rule.default_rate or ZERO
            amount = rules.round(percent_of(base, rate))
        elif include_fixed:
            base, rate, amount = None, None, rules.round(rule.default_amount or ZERO)
        else:
            continue
        if amount == 0:
            continue
        lines.append(PayslipLine(
            section="employer_charge", code=rule.code, name_en=rule.name_en, name_fr=rule.name_fr, amount=amount,
            base=base, rate=rate, declaration_code=rule.declaration_code or rule.code, display_order=rule.display_order,
        ))
    return lines


def payslip_totals(lines: Sequence[PayslipLine]) -> PayslipTotals:
    gross = section_total(lines, "earning")
    employee_contrib = section_total(lines, "employee_contribution")
    employer_contrib = section_total(lines, "employer_contribution")
    employer_charges = section_total(lines, "employer_charge")
    tax = section_total(lines, "tax")
    deductions = section_total(lines, "deduction")
    taxable = max((line.base for line in lines if line.section == "tax" and line.base is not None), default=ZERO)
    return PayslipTotals(
        gross=gross,
        contributable=contributable_earnings(lines),
        taxable=taxable,
        employee_contrib=employee_contrib,
        employer_contrib=employer_contrib,
        employer_charges=employer_charges,
        tax=tax,
        deductions=deductions,
        net=gross - employee_contrib - tax - deductions,
        employer_cost=gross + employer_contrib + employer_charges,
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest modules/payroll/domain/test_net.py -q`
Expected: `6 passed`.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/payroll/domain/net.py backend/modules/payroll/domain/test_net.py
git commit -m "feat(payroll): engine steps 5-6, net floor with carry-forward and employer cost

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---
### Task 8: Final settlement arithmetic

**Files:**
- Create: `backend/modules/payroll/domain/settlement.py`
- Test: `backend/modules/payroll/domain/test_settlement.py`

**Interfaces:**
- Consumes: `earning_line` (Task 4), `SettlementInput`, `RuleSet`, `SeveranceStep`, codes `LEAVE_INDEMNITY`, `NOTICE_INDEMNITY`, `SEVERANCE`.
- Produces: `completed_months(start, end) -> int`, `years_of_service(hire_date, end_date) -> Decimal` (whole months ÷ 12), `reference_salary(recent_gross: Sequence[Decimal], *, months: int, fallback: Decimal) -> Decimal` (average of the first `months` values — callers pass newest first — else `fallback`), `severance_amount(scale, years, reference) -> Decimal` (tiered), `leave_indemnity(reference, unused_days, rules) -> Decimal`, `notice_indemnity(reference, months) -> Decimal`, `settlement_lines(rules, settlement) -> list[PayslipLine]`.

Spec: "Final settlement: off-cycle payslip with prorated salary, unused paid-leave indemnity, notice indemnity, severance (formula components from the rule set)". The three components are rule-set rows (their taxable/contributable flags are data); the severance scale and the averaging window (`rule_sets.settlement_reference_months`) are rule-set data too.

- [ ] **Step 1: Write the failing tests**

Create `backend/modules/payroll/domain/test_settlement.py`:

```python
from datetime import date
from decimal import Decimal

from modules.payroll.domain.inputs import SettlementInput
from modules.payroll.domain.rules import SeveranceStep
from modules.payroll.domain.settlement import (
    leave_indemnity,
    notice_indemnity,
    reference_salary,
    settlement_lines,
    severance_amount,
    years_of_service,
)
from modules.payroll.domain.synthetic import synthetic_rule_set

D = Decimal
RULES = synthetic_rule_set()


def test_years_of_service_count_whole_months():
    assert years_of_service(date(2014, 9, 15), date(2026, 9, 15)) == D(12)
    assert years_of_service(date(2014, 9, 16), date(2026, 9, 15)) == D(143) / 12


def test_reference_salary_averages_the_most_recent_months_else_the_fallback():
    assert reference_salary([D(300000), D(330000)], months=12, fallback=D(1)) == D(315000)
    assert reference_salary([], months=12, fallback=D(250000)) == D(250000)
    assert reference_salary([D(100)] * 12 + [D(10**9)], months=12, fallback=D(1)) == D(100)
    assert reference_salary([D(100), D(300)], months=1, fallback=D(1)) == D(100)


def test_severance_is_tiered_by_years_of_service():
    assert severance_amount(RULES.severance_scale, D(12), D(300000)) == D(855000)
    assert severance_amount(RULES.severance_scale, D(3), D(300000)) == D(180000)
    assert severance_amount((), D(12), D(300000)) == 0


def test_a_scale_starting_after_year_zero_pays_nothing_before_it():
    scale = (SeveranceStep(1, D(20)),)
    assert severance_amount(scale, D("0.5"), D(300000)) == 0
    assert severance_amount(scale, D(2), D(300000)) == D(60000)


def test_leave_and_notice_indemnities():
    assert leave_indemnity(D(300000), D(10), RULES) == D(150000)
    assert notice_indemnity(D(300000), D("1.5")) == D(450000)


def test_settlement_lines_carry_the_rule_set_flags():
    lines = settlement_lines(RULES, SettlementInput(reference_salary=D(300000), years_of_service=D(12),
                                                    unused_leave_days=D(10), notice_months=D(1)))
    assert [(line.code, line.amount, line.taxable) for line in lines] == [
        ("LEAVE_INDEMNITY", D(150000), True), ("NOTICE_INDEMNITY", D(300000), True), ("SEVERANCE", D(855000), False),
    ]


def test_nothing_owed_gives_no_line():
    assert settlement_lines(RULES, SettlementInput(reference_salary=D(300000), years_of_service=D(0))) == []
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python -m pytest modules/payroll/domain/test_settlement.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'modules.payroll.domain.settlement'`.

- [ ] **Step 3: Write `settlement.py`**

```python
"""Final settlement: years of service, the reference salary, and the three indemnities."""
from __future__ import annotations

import datetime
from collections.abc import Sequence
from decimal import Decimal

from modules.payroll.domain.earnings import earning_line
from modules.payroll.domain.inputs import PayslipLine, SettlementInput
from modules.payroll.domain.money import ZERO, percent_of
from modules.payroll.domain.rules import LEAVE_INDEMNITY, NOTICE_INDEMNITY, SEVERANCE, RuleSet, SeveranceStep

_QTY = Decimal("0.01")


def completed_months(start: datetime.date, end: datetime.date) -> int:
    months = (end.year - start.year) * 12 + (end.month - start.month) - (1 if end.day < start.day else 0)
    return max(months, 0)


def years_of_service(hire_date: datetime.date, end_date: datetime.date) -> Decimal:
    return Decimal(completed_months(hire_date, end_date)) / 12


def reference_salary(recent_gross: Sequence[Decimal], *, months: int, fallback: Decimal) -> Decimal:
    """Average of the `months` most recent monthly gross amounts (newest first); `fallback` if none."""
    window = list(recent_gross)[:months]
    return sum(window, ZERO) / len(window) if window else fallback


def severance_amount(scale: Sequence[SeveranceStep], years: Decimal, reference: Decimal) -> Decimal:
    """Each year inside [years_from, next years_from) earns percent_per_year % of the reference."""
    steps = sorted(scale, key=lambda step: step.years_from)
    total = ZERO
    for index, step in enumerate(steps):
        lower = Decimal(step.years_from)
        if years <= lower:
            break
        upper = Decimal(steps[index + 1].years_from) if index + 1 < len(steps) else None
        span = (years if upper is None else min(years, upper)) - lower
        total += span * percent_of(reference, step.percent_per_year)
    return total


def leave_indemnity(reference: Decimal, unused_days: Decimal, rules: RuleSet) -> Decimal:
    return reference / rules.working_days_per_month * unused_days


def notice_indemnity(reference: Decimal, months: Decimal) -> Decimal:
    return reference * months


def settlement_lines(rules: RuleSet, settlement: SettlementInput) -> list[PayslipLine]:
    reference = settlement.reference_salary
    owed = (
        (LEAVE_INDEMNITY, leave_indemnity(reference, settlement.unused_leave_days, rules), settlement.unused_leave_days),
        (NOTICE_INDEMNITY, notice_indemnity(reference, settlement.notice_months), settlement.notice_months),
        (SEVERANCE, severance_amount(rules.severance_scale, settlement.years_of_service, reference), settlement.years_of_service),
    )
    lines: list[PayslipLine] = []
    for code, amount, qty in owed:
        rounded = rules.round(amount)
        if rounded <= 0:
            continue
        lines.append(earning_line(rules.require(code), rounded, base=rules.round(reference), qty=qty.quantize(_QTY)))
    return lines
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest modules/payroll/domain/test_settlement.py -q`
Expected: `7 passed`.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/payroll/domain/settlement.py backend/modules/payroll/domain/test_settlement.py
git commit -m "feat(payroll): final settlement indemnities from rule-set scales

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: The engine — `calculate_payslip` and golden payslips

**Files:**
- Create: `backend/modules/payroll/domain/engine.py`
- Test: `backend/modules/payroll/domain/test_engine_golden.py`

**Interfaces:**
- Consumes: Tasks 2, 4–8.
- Produces:
  - `PayslipResult(lines: tuple[PayslipLine, ...], totals: PayslipTotals, carry_forwards: tuple[CarryForward, ...], warnings: tuple[str, ...])`
  - `calculate_payslip(*, employee: EmployeeInput, presence: PresenceInput, rules: RuleSet, period: date, inputs: Sequence[OneOffInput] = (), settlement: SettlementInput | None = None, include_salary: bool = True) -> Result[PayslipResult]`
    - `include_salary=False` = a correction payslip in an off-cycle run: only the typed inputs (and settlement, if any) are paid.
    - Errors: `Err("COMPONENT_MISSING", "the rule set has no <what>", "le jeu de règles n'a pas de <quoi>")`, `Err("COMPONENT_INVALID", …)`.
    - `warnings == ("NET_NEGATIVE",)` when something was carried to next month.
  - `order_lines(lines) -> list[PayslipLine]` (by `SECTIONS`, then display order, then code; stable).

- [ ] **Step 1: Write the failing golden tests**

Create `backend/modules/payroll/domain/test_engine_golden.py`:

```python
"""Golden payslips computed by hand from the SYNTHETIC rule set (round numbers, not Mali).

The spec asks for golden tests from three real payslips once the accountant provides them; until
then these pin the arithmetic. Each docstring spells the sum out so a reviewer can redo it.
Synthetic rules: 20 working days, 160 h; PENSION 5 % / 10 % capped 500 000; HEALTH 2 % / 3 %;
TAX monthly 0 % to 100 000, 10 % to 300 000, 20 % above; professional relief 10 % capped 20 000;
family relief 10 % (1 dependant), 20 % (2+); tax rounded down to 10; employer tax 2 % of gross.
"""
from dataclasses import replace
from datetime import date
from decimal import Decimal

from core.domain.result import Err, Ok
from modules.payroll.domain.engine import calculate_payslip
from modules.payroll.domain.inputs import SECTIONS, ContractComponent, OneOffInput, PresenceInput, SettlementInput
from modules.payroll.domain.net import CarryForward
from modules.payroll.domain.synthetic import synthetic_employee, synthetic_rule_set

D = Decimal
SEPT = date(2026, 9, 1)
FULL = PresenceInput(scheduled_days=22, worked_days=22)


def totals(result):
    assert isinstance(result, Ok), result
    t = result.value.totals
    return {"gross": t.gross, "employee_contrib": t.employee_contrib, "tax": t.tax, "deductions": t.deductions,
            "net": t.net, "employer_contrib": t.employer_contrib, "employer_charges": t.employer_charges,
            "employer_cost": t.employer_cost}


def line_amounts(result):
    return {(line.section, line.code): line.amount for line in result.value.lines}


def _full_month(rules):
    employee = synthetic_employee(tax_dependants=2, components=(ContractComponent("HOUSING", amount=D(30000)),
                                                                ContractComponent("TRANSPORT", amount=D(10000))))
    return calculate_payslip(employee=employee, presence=replace(FULL, ot_minutes_day=600), rules=rules, period=SEPT,
                             inputs=[OneOffInput("ADVANCE", amount=D(50000), source_kind="advance", source_id="a1")])


FULL_MONTH_TOTALS = {"gross": D(497500), "employee_contrib": D(34125), "tax": D(37340), "deductions": D(50000),
                     "net": D(376035), "employer_contrib": D(63375), "employer_charges": D(9950), "employer_cost": D(570825)}


def test_golden_full_month_with_overtime_allowances_dependants_and_an_advance():
    """BASE 400 000; seniority 5 y → 5 % = 20 000; HOUSING 30 000; TRANSPORT 10 000 (neither taxable
    nor contributable); OT day 10 h × 2 500 × 1.5 = 37 500 → gross 497 500.
    Contributable 487 500: PENSION 24 375 / 48 750; HEALTH 9 750 / 14 625.
    Taxable 487 500 − 34 125 = 453 375 − 20 000 (10 % capped) = 433 375; tax 20 000 + 20 % × 133 375
    = 46 675; 2 dependants −20 % → 37 340. Net 497 500 − 34 125 − 37 340 − 50 000 = 376 035.
    Employer tax 9 950; cost 497 500 + 63 375 + 9 950 = 570 825."""
    result = _full_month(synthetic_rule_set())
    assert totals(result) == FULL_MONTH_TOTALS
    amounts = line_amounts(result)
    assert amounts[("earning", "SENIORITY")] == D(20000)
    assert amounts[("relief", "TAX_PROF_RELIEF")] == D(20000)
    assert amounts[("relief", "TAX_FAMILY_RELIEF")] == D(9335)
    assert result.value.warnings == () and result.value.carry_forwards == ()
    sections = [line.section for line in result.value.lines]
    assert sections == sorted(sections, key=SECTIONS.index)


def test_golden_annual_brackets_give_the_same_payslip():
    assert totals(_full_month(synthetic_rule_set(annualised=True))) == FULL_MONTH_TOTALS


def test_golden_mid_month_hire_with_unpaid_absence():
    """Hired 11 Sept, 14 of 20 days: BASE 280 000; 2 unpaid days −40 000; HOUSING 21 000; TRANSPORT
    7 000 → gross 268 000. Contributable 261 000: PENSION 13 050 / 26 100; HEALTH 5 220 / 7 830.
    Taxable 242 730 − 20 000 = 222 730; tax 12 273; 1 dependant −10 % = 11 045.7 → 11 040.
    Net 268 000 − 18 270 − 11 040 = 238 690. Employer tax 5 360; cost 307 290."""
    employee = synthetic_employee(hire_date=date(2026, 9, 11), contract_start=date(2026, 9, 11), tax_dependants=1,
                                  components=(ContractComponent("HOUSING", amount=D(30000)),
                                              ContractComponent("TRANSPORT", amount=D(10000))))
    result = calculate_payslip(employee=employee, presence=PresenceInput(scheduled_days=14, worked_days=12, unpaid_absence_days=2),
                               rules=synthetic_rule_set(), period=SEPT)
    assert totals(result) == {"gross": D(268000), "employee_contrib": D(18270), "tax": D(11040), "deductions": D(0),
                              "net": D(238690), "employer_contrib": D(33930), "employer_charges": D(5360),
                              "employer_cost": D(307290)}


def test_golden_daily_worker():
    """Day rate 10 000 × (18 worked + 1 leave + 1 holiday) = 200 000; seniority 6 y → 5 % = 10 000;
    MEAL 500 × 18 = 9 000 (neither taxable nor contributable); OT night 1.5 h × (200 000 / 160 = 1 250)
    × 2 = 3 750 → gross 222 750. Contributable 213 750: PENSION 10 688 / 21 375; HEALTH 4 275 / 6 413.
    Taxable 213 750 − 14 963 = 198 787 − 19 879 (10 %) = 178 908; tax 7 890.8 → 7 890.
    Net 222 750 − 14 963 − 7 890 = 199 897. Employer tax 4 455; cost 254 993."""
    employee = synthetic_employee(base_salary=D(10000), pay_frequency="daily", hire_date=date(2020, 3, 1),
                                  contract_start=date(2020, 3, 1), components=(ContractComponent("MEAL"),))
    presence = PresenceInput(scheduled_days=22, worked_days=18, paid_leave_days=1, holiday_days=1, ot_minutes_night=90)
    result = calculate_payslip(employee=employee, presence=presence, rules=synthetic_rule_set(), period=SEPT)
    assert totals(result) == {"gross": D(222750), "employee_contrib": D(14963), "tax": D(7890), "deductions": D(0),
                              "net": D(199897), "employer_contrib": D(27788), "employer_charges": D(4455),
                              "employer_cost": D(254993)}


def test_golden_net_negative_carries_the_overflow():
    """Gross 100 000; contributions 7 000; taxable 93 000 − 9 300 = 83 700 → no tax. Available 93 000:
    carried canteen 5 000, loan 20 000, then the 90 000 advance only fits 68 000 → 22 000 carried."""
    employee = synthetic_employee(base_salary=D(100000), hire_date=date(2026, 1, 1), contract_start=date(2026, 1, 1))
    inputs = [
        OneOffInput("ADVANCE", amount=D(90000), source_kind="advance", source_id="a1"),
        OneOffInput("LOAN", amount=D(20000), source_kind="loan_instalment", source_id="i1"),
        OneOffInput("CANTEEN", amount=D(5000), source_kind="carry_forward", source_id="c1"),
    ]
    result = calculate_payslip(employee=employee, presence=FULL, rules=synthetic_rule_set(), period=SEPT, inputs=inputs)
    assert totals(result) == {"gross": D(100000), "employee_contrib": D(7000), "tax": D(0), "deductions": D(93000),
                              "net": D(0), "employer_contrib": D(13000), "employer_charges": D(2000),
                              "employer_cost": D(115000)}
    assert result.value.carry_forwards == (CarryForward("ADVANCE", D(22000), "advance", "a1"),)
    assert result.value.warnings == ("NET_NEGATIVE",)


def test_golden_final_settlement():
    """Leaves 15 Sept after 12 years, 10 of 20 days: BASE 150 000; seniority 5 % = 7 500; leave 10 d ×
    15 000 = 150 000; notice 1 month 300 000; severance 5×20 % + 5×25 % + 2×30 % of 300 000 = 855 000
    (not taxable, not contributable) → gross 1 462 500. Contributable 607 500: PENSION capped 500 000
    → 25 000 / 50 000; HEALTH 12 150 / 18 225. Taxable 570 350 − 20 000 = 550 350; tax 20 000 + 20 % ×
    250 350 = 70 070. Net 1 462 500 − 37 150 − 70 070 = 1 355 280. Employer tax 29 250; cost 1 559 975."""
    employee = synthetic_employee(base_salary=D(300000), hire_date=date(2014, 9, 15), contract_start=date(2014, 9, 15),
                                  termination_date=date(2026, 9, 15))
    settlement = SettlementInput(reference_salary=D(300000), years_of_service=D(12), unused_leave_days=D(10), notice_months=D(1))
    result = calculate_payslip(employee=employee, presence=PresenceInput(scheduled_days=10, worked_days=10),
                               rules=synthetic_rule_set(), period=SEPT, settlement=settlement)
    assert totals(result) == {"gross": D(1462500), "employee_contrib": D(37150), "tax": D(70070), "deductions": D(0),
                              "net": D(1355280), "employer_contrib": D(68225), "employer_charges": D(29250),
                              "employer_cost": D(1559975)}


def test_golden_correction_payslip_pays_only_the_typed_inputs():
    """Bonus 25 000 alone: PENSION 1 250 / 2 500; HEALTH 500 / 750; taxable 23 250 − 2 325 → no tax.
    Net 23 250; employer tax 500; cost 28 750."""
    result = calculate_payslip(employee=synthetic_employee(), presence=FULL, rules=synthetic_rule_set(), period=SEPT,
                               inputs=[OneOffInput("BONUS", amount=D(25000))], include_salary=False)
    assert totals(result) == {"gross": D(25000), "employee_contrib": D(1750), "tax": D(0), "deductions": D(0),
                              "net": D(23250), "employer_contrib": D(3250), "employer_charges": D(500),
                              "employer_cost": D(28750)}
    assert ("earning", "BASE") not in line_amounts(result)


def test_a_missing_component_is_a_bilingual_refusal():
    rules = synthetic_rule_set()
    rules = replace(rules, components=tuple(component for component in rules.components if component.code != "OT_NIGHT"))
    result = calculate_payslip(employee=synthetic_employee(), presence=replace(FULL, ot_minutes_night=60), rules=rules, period=SEPT)
    assert isinstance(result, Err) and result.code == "COMPONENT_MISSING"
    assert (result.message, result.message_fr) == ("the rule set has no component OT_NIGHT", "le jeu de règles n'a pas de rubrique OT_NIGHT")


def test_a_misused_component_is_a_bilingual_refusal():
    employee = synthetic_employee(components=(ContractComponent("CANTEEN", amount=D(1)),))
    result = calculate_payslip(employee=employee, presence=FULL, rules=synthetic_rule_set(), period=SEPT)
    assert isinstance(result, Err) and result.code == "COMPONENT_INVALID" and result.message_fr
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python -m pytest modules/payroll/domain/test_engine_golden.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'modules.payroll.domain.engine'`.

- [ ] **Step 3: Write `engine.py`**

```python
"""The payroll engine: one employee, one month, one rule set -> ordered payslip lines and totals.

Pure (no database, no clock). Each step lives in its own module and is tested alone; this file only
runs them in the spec's order:
  1 earnings -> gross        (earnings.py, settlement.py)
  2 contributable base       (contributions.py)
  3 contributions            (contributions.py)
  4 taxable and tax          (tax.py)
  5 deductions -> net >= 0   (net.py; the overflow is carried and reported as NET_NEGATIVE)
  6 employer cost            (net.py)
"""
from __future__ import annotations

import datetime
from collections.abc import Sequence
from dataclasses import dataclass

from core.domain.result import Err, Ok, Result
from modules.payroll.domain.contributions import contributable_earnings, contribution_lines
from modules.payroll.domain.earnings import (
    base_salary_lines,
    contract_component_lines,
    earned_base,
    input_earning_lines,
    overtime_lines,
    seniority_line,
)
from modules.payroll.domain.inputs import (
    SECTIONS,
    EmployeeInput,
    OneOffInput,
    PayslipLine,
    PresenceInput,
    SettlementInput,
    section_total,
)
from modules.payroll.domain.money import ZERO
from modules.payroll.domain.net import (
    CarryForward,
    PayslipTotals,
    apply_net_floor,
    deduction_lines,
    employer_charge_lines,
    payslip_totals,
)
from modules.payroll.domain.rules import ComponentMisuse, RuleSet, RuleSetIncomplete
from modules.payroll.domain.settlement import settlement_lines
from modules.payroll.domain.tax import tax_lines


@dataclass(frozen=True)
class PayslipResult:
    lines: tuple[PayslipLine, ...]
    totals: PayslipTotals
    carry_forwards: tuple[CarryForward, ...]
    warnings: tuple[str, ...]


def order_lines(lines: Sequence[PayslipLine]) -> list[PayslipLine]:
    return sorted(lines, key=lambda line: (SECTIONS.index(line.section), line.display_order, line.code))


def calculate_payslip(
    *,
    employee: EmployeeInput,
    presence: PresenceInput,
    rules: RuleSet,
    period: datetime.date,
    inputs: Sequence[OneOffInput] = (),
    settlement: SettlementInput | None = None,
    include_salary: bool = True,
) -> Result[PayslipResult]:
    try:
        return Ok(_calculate(employee, presence, rules, period, tuple(inputs), settlement, include_salary))
    except RuleSetIncomplete as missing:
        return Err("COMPONENT_MISSING", f"the rule set has no {missing.what_en}", f"le jeu de règles n'a pas de {missing.what_fr}")
    except ComponentMisuse as misuse:
        return Err("COMPONENT_INVALID", misuse.message_en, misuse.message_fr)


def _calculate(employee: EmployeeInput, presence: PresenceInput, rules: RuleSet, period: datetime.date,
               inputs: tuple[OneOffInput, ...], settlement: SettlementInput | None, include_salary: bool) -> PayslipResult:
    lines: list[PayslipLine] = []
    earned = ZERO
    if include_salary:
        lines += base_salary_lines(employee, presence, rules, period)
        earned = earned_base(lines)
        seniority = seniority_line(employee, earned, rules, period)
        if seniority is not None:
            lines.append(seniority)
        lines += contract_component_lines(employee, presence, rules, period, earned=earned)
        lines += overtime_lines(employee, presence, rules)
    if settlement is not None:
        lines += settlement_lines(rules, settlement)
    lines += input_earning_lines(inputs, presence, rules)

    gross = section_total(lines, "earning")
    contributable = contributable_earnings(lines)
    lines += contribution_lines(rules, gross=gross, contributable=contributable)
    lines += tax_lines(rules, lines, employee.tax_dependants)

    available = gross - section_total(lines, "employee_contribution") - section_total(lines, "tax")
    kept, carried = apply_net_floor(available, deduction_lines(inputs, presence, rules))
    lines += kept
    lines += employer_charge_lines(rules, gross=gross, contributable=contributable, earned=earned, include_fixed=include_salary)

    ordered = tuple(order_lines(lines))
    return PayslipResult(
        lines=ordered,
        totals=payslip_totals(ordered),
        carry_forwards=tuple(carried),
        warnings=("NET_NEGATIVE",) if carried else (),
    )
```

- [ ] **Step 4: Run the golden tests and the whole domain suite**

Run: `.venv/Scripts/python -m pytest modules/payroll/domain -q`
Expected: `81 passed` (6 money + 8 rules + 14 validation + 16 earnings + 5 contributions + 10 tax + 6 net + 7 settlement + 9 golden), no failure, no skip.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/payroll/domain/engine.py backend/modules/payroll/domain/test_engine_golden.py
git commit -m "feat(payroll): calculate_payslip engine with golden payslips on synthetic rules

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: `RuleSetService` — payroll country, rule sets, rows, confirmation, loading

**Files:**
- Create: `backend/modules/payroll/api/rows.py`
- Create: `backend/modules/payroll/api/rule_set_service.py`
- Create: `backend/modules/payroll/api/testing_support.py`
- Test: `backend/modules/payroll/api/test_rule_set_service_integration.py`

**Interfaces:**
- Consumes: validators and `check_complete`, `relief_from_parameters`, `relief_parameters` (Task 3); rule dataclasses (Task 2); `core.audit.record_audit`.
- Produces:
  - `rows.fetch_all(connection, sql, params=()) -> list[dict]`, `rows.fetch_one(...) -> dict | None`, `rows.jsonable(value)` (Decimal → int when whole else float; date/datetime → ISO string; recursive).
  - `rule_set_service.CHILD_KINDS: dict[str, ChildSpec]` with kinds `components, contributions, tax_brackets, tax_reliefs, seniority_scale, overtime_rates, severance_scale`; `HEADER_COLUMNS`.
  - `RuleSetService(connection)`:
    - `get_settings(*, tenant_id) -> dict | None`; `save_settings(*, tenant_id, actor_id, country, company_address=None, employer_inps_no=None, employer_tax_id=None) -> Result[dict]`
    - `list_rule_sets(*, tenant_id) -> list[dict]`; `get_rule_set(*, tenant_id, rule_set_id) -> dict | None` (header + one list per kind)
    - `create_rule_set(*, tenant_id, actor_id, country, name, valid_from, working_days_per_month, working_hours_per_month, round_to=1, round_mode="half_up", tax_round_to=1, tax_round_mode="half_up", settlement_reference_months=12, notes=None) -> Result[dict]`
    - `update_rule_set(*, tenant_id, actor_id, rule_set_id, changes: dict) -> Result[dict]` — `changes` holds only the fields sent (a sent `null` clears a nullable field)
    - `delete_rule_set(*, tenant_id, actor_id, rule_set_id) -> Result[dict]`
    - `copy_rule_set(*, tenant_id, actor_id, rule_set_id, valid_from, name) -> Result[dict]`
    - `confirm_rule_set(*, tenant_id, actor_id, rule_set_id) -> Result[dict]` (stamps `confirmed_at = clock_timestamp()`)
    - `list_children(*, tenant_id, rule_set_id, kind) -> list[dict]`; `add_child(*, tenant_id, actor_id, rule_set_id, kind, values: dict) -> Result[dict]`; `update_child(*, tenant_id, actor_id, rule_set_id, kind, row_id, changes: dict) -> Result[dict]`; `delete_child(*, tenant_id, actor_id, rule_set_id, kind, row_id) -> Result[dict]`
    - `load(*, tenant_id, rule_set_id) -> RuleSet | None`
    - `in_force(*, tenant_id, period) -> Result[dict]` (raw header row of the latest rule set of the tenant's payroll country with `valid_from <= period`; `RULESET_MISSING` otherwise)
  - `testing_support`: `TEST_COUNTRY = "ZZ"`, `make_user(connection, tenant_id) -> str`, `rule_rows(rules) -> dict[str, list[dict]]`, `store_rule_set(connection, *, tenant_id, actor_id, valid_from, rules=None, confirm=True, country="ZZ", name=...) -> str`, `set_country(connection, *, tenant_id, actor_id, country="ZZ") -> None`.
- Error codes: `NOT_FOUND`, `RULE_INVALID`, `DUPLICATE_RULESET`, `DUPLICATE_RULE`, `RULESET_LOCKED`, `RULESET_INCOMPLETE`, `RULESET_IN_USE`, `RULESET_MISSING`.

Edit permission (resolved ambiguity): the spec's permission list has no `admin_rules`; rule rows are edited in place under `payroll.manage_rules` while the set is a **draft**, and a confirmed set is frozen (`RULESET_LOCKED`) because payslips were computed from it. To change confirmed rules: copy to a new draft (new `valid_from`) or reopen (3b, refused once an approved run used it).

- [ ] **Step 1: Write the failing integration tests**

Create `backend/modules/payroll/api/test_rule_set_service_integration.py`:

```python
"""Rule sets against a real database: validation, duplicates, confirmation lock, loading, in force."""
from __future__ import annotations

import datetime
from decimal import Decimal

import pytest

from core.domain.result import Err, Ok
from modules.payroll.api.rule_set_service import CHILD_KINDS, RuleSetService
from modules.payroll.api.testing_support import TEST_COUNTRY, make_user, set_country, store_rule_set
from modules.payroll.domain.synthetic import synthetic_rule_set

TENANT = "payroll-rules-test"
D = Decimal
JAN = datetime.date(2031, 1, 1)


@pytest.fixture
def actor(db):
    return make_user(db, TENANT)


def _create(db, actor, valid_from=JAN):
    return RuleSetService(db).create_rule_set(
        tenant_id=TENANT, actor_id=actor, country=TEST_COUNTRY, name="Test", valid_from=valid_from,
        working_days_per_month=D(20), working_hours_per_month=D(160),
    )


def test_a_new_rule_set_is_an_empty_draft(db, actor):
    created = _create(db, actor)
    assert isinstance(created, Ok)
    assert created.value["status"] == "draft" and created.value["components"] == []
    assert (created.value["working_hours_per_month"], created.value["settlement_reference_months"]) == (160, 12)


def test_two_rule_sets_cannot_start_the_same_month_in_one_country(db, actor):
    _create(db, actor)
    again = _create(db, actor)
    assert isinstance(again, Err) and again.code == "DUPLICATE_RULESET" and again.message_fr


def test_a_row_is_validated_before_it_is_stored(db, actor):
    rule_set_id = _create(db, actor).value["id"]
    refused = RuleSetService(db).add_child(
        tenant_id=TENANT, actor_id=actor, rule_set_id=rule_set_id, kind="components",
        values={"code": "SEN2", "name_en": "x", "name_fr": "x", "kind": "earning", "formula_type": "rate_x_base"},
    )
    assert isinstance(refused, Err) and refused.code == "RULE_INVALID" and "base" in refused.message_fr


def test_a_duplicate_row_is_refused_and_the_transaction_goes_on(db, actor):
    service = RuleSetService(db)
    rule_set_id = _create(db, actor).value["id"]
    values = {"band_code": "day", "multiplier": "1.5"}
    assert isinstance(service.add_child(tenant_id=TENANT, actor_id=actor, rule_set_id=rule_set_id, kind="overtime_rates", values=values), Ok)
    again = service.add_child(tenant_id=TENANT, actor_id=actor, rule_set_id=rule_set_id, kind="overtime_rates", values=values)
    assert isinstance(again, Err) and again.code == "DUPLICATE_RULE"
    assert len(service.list_children(tenant_id=TENANT, rule_set_id=rule_set_id, kind="overtime_rates")) == 1


def test_confirming_an_incomplete_rule_set_says_what_is_missing(db, actor):
    rule_set_id = _create(db, actor).value["id"]
    refused = RuleSetService(db).confirm_rule_set(tenant_id=TENANT, actor_id=actor, rule_set_id=rule_set_id)
    assert isinstance(refused, Err) and refused.code == "RULESET_INCOMPLETE"
    assert "component BASE is missing" in refused.message and "la rubrique BASE manque" in refused.message_fr


def test_confirmation_is_stamped_and_audited(db, actor):
    rule_set_id = store_rule_set(db, tenant_id=TENANT, actor_id=actor, valid_from=JAN)
    document = RuleSetService(db).get_rule_set(tenant_id=TENANT, rule_set_id=rule_set_id)
    assert document["status"] == "confirmed" and document["confirmed_by"] == actor and document["confirmed_at"]
    audit = db.execute(
        "SELECT payload FROM core.audit_log WHERE entity_id = %s AND action = 'rule_set.confirmed'", (rule_set_id,)
    ).fetchone()
    assert audit == ({"from_status": "draft", "to_status": "confirmed"},)


def test_a_confirmed_rule_set_is_locked(db, actor):
    service = RuleSetService(db)
    rule_set_id = store_rule_set(db, tenant_id=TENANT, actor_id=actor, valid_from=JAN)
    component_id = service.list_children(tenant_id=TENANT, rule_set_id=rule_set_id, kind="components")[0]["id"]
    attempts = [
        service.update_rule_set(tenant_id=TENANT, actor_id=actor, rule_set_id=rule_set_id, changes={"name": "Changed"}),
        service.add_child(tenant_id=TENANT, actor_id=actor, rule_set_id=rule_set_id, kind="seniority_scale", values={"years_from": 20, "percent": 9}),
        service.update_child(tenant_id=TENANT, actor_id=actor, rule_set_id=rule_set_id, kind="components", row_id=component_id, changes={"taxable": False}),
        service.delete_child(tenant_id=TENANT, actor_id=actor, rule_set_id=rule_set_id, kind="components", row_id=component_id),
        service.delete_rule_set(tenant_id=TENANT, actor_id=actor, rule_set_id=rule_set_id),
    ]
    assert [getattr(result, "code", None) for result in attempts] == ["RULESET_LOCKED"] * 5


def test_load_gives_back_the_rules_that_were_stored(db, actor):
    expected = synthetic_rule_set()
    rule_set_id = store_rule_set(db, tenant_id=TENANT, actor_id=actor, valid_from=JAN)
    loaded = RuleSetService(db).load(tenant_id=TENANT, rule_set_id=rule_set_id)
    assert loaded.require("HOUSING") == expected.require("HOUSING")
    assert loaded.brackets_for("TAX") == expected.brackets_for("TAX")
    assert loaded.family_relief("TAX") == expected.family_relief("TAX")
    assert loaded.professional_relief("TAX") == expected.professional_relief("TAX")
    assert sorted(loaded.contributions, key=lambda c: c.code) == sorted(expected.contributions, key=lambda c: c.code)
    assert (loaded.round_to, loaded.tax_round_to, loaded.tax_round_mode, loaded.status) == (1, 10, "down", "confirmed")


def test_the_rule_set_in_force_is_the_latest_started_by_the_period(db, actor):
    set_country(db, tenant_id=TENANT, actor_id=actor)
    first = _create(db, actor, valid_from=JAN).value["id"]
    second = _create(db, actor, valid_from=datetime.date(2031, 10, 1)).value["id"]
    service = RuleSetService(db)
    assert service.in_force(tenant_id=TENANT, period=datetime.date(2031, 9, 1)).value["id"] == first
    assert service.in_force(tenant_id=TENANT, period=datetime.date(2031, 10, 1)).value["id"] == second
    missing = service.in_force(tenant_id=TENANT, period=datetime.date(2030, 12, 1))
    assert isinstance(missing, Err) and missing.code == "RULESET_MISSING" and "12/2030" in missing.message_fr


def test_without_a_payroll_country_no_rule_set_applies(db, actor):
    _create(db, actor)
    missing = RuleSetService(db).in_force(tenant_id=TENANT, period=JAN)
    assert isinstance(missing, Err) and missing.code == "RULESET_MISSING"


def test_copy_makes_an_editable_draft_with_every_row(db, actor):
    service = RuleSetService(db)
    source = store_rule_set(db, tenant_id=TENANT, actor_id=actor, valid_from=JAN)
    copied = service.copy_rule_set(tenant_id=TENANT, actor_id=actor, rule_set_id=source, valid_from=datetime.date(2032, 1, 1), name="2032 draft")
    assert isinstance(copied, Ok) and copied.value["status"] == "draft"
    original = service.get_rule_set(tenant_id=TENANT, rule_set_id=source)
    for kind in CHILD_KINDS:
        assert len(copied.value[kind]) == len(original[kind]), kind


def test_an_edit_keeps_unsent_fields_and_can_clear_a_nullable_one(db, actor):
    service = RuleSetService(db)
    rule_set_id = store_rule_set(db, tenant_id=TENANT, actor_id=actor, valid_from=JAN, confirm=False)
    pension = next(row for row in service.list_children(tenant_id=TENANT, rule_set_id=rule_set_id, kind="contributions") if row["code"] == "PENSION")
    updated = service.update_child(tenant_id=TENANT, actor_id=actor, rule_set_id=rule_set_id, kind="contributions",
                                   row_id=pension["id"], changes={"ceiling_monthly": None})
    assert isinstance(updated, Ok)
    assert updated.value["ceiling_monthly"] is None and updated.value["employee_rate"] == 5
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python -m pytest modules/payroll/api/test_rule_set_service_integration.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'modules.payroll.api.rule_set_service'`.

- [ ] **Step 3: Write `rows.py`**

```python
"""Row helpers: dicts from cursors, and JSON-safe values (money as integers)."""
from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

import psycopg


def fetch_all(connection: psycopg.Connection, sql: str, params: tuple | list = ()) -> list[dict[str, Any]]:
    cursor = connection.execute(sql, params)
    names = [column.name for column in cursor.description or []]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def fetch_one(connection: psycopg.Connection, sql: str, params: tuple | list = ()) -> dict[str, Any] | None:
    rows = fetch_all(connection, sql, params)
    return rows[0] if rows else None


def jsonable(value: Any) -> Any:
    """Decimal -> int when whole (money, counts), float otherwise (rates); dates -> ISO strings."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    return value
```

- [ ] **Step 4: Write `rule_set_service.py`**

```python
"""Rule sets: the payroll country, the effective-dated rule tables, and their confirmation.

A draft rule set is edited in place (payroll.manage_rules). Confirming it (payroll.confirm_rules)
checks it is complete and freezes it: every change is then refused with RULESET_LOCKED, because
payslips are computed from it. Table and column names below are constants, never user input.
"""
from __future__ import annotations

import datetime
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.types.json import Jsonb
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.payroll.api.rows import fetch_all, fetch_one, jsonable
from modules.payroll.domain.rule_validation import (
    COUNTRY,
    check_complete,
    relief_from_parameters,
    validate_component,
    validate_contribution,
    validate_overtime_rate,
    validate_rule_set_header,
    validate_seniority_step,
    validate_severance_step,
    validate_tax_bracket,
    validate_tax_relief,
)
from modules.payroll.domain.rules import (
    ComponentRule,
    ContributionRule,
    FamilyRelief,
    OvertimeRate,
    ProfessionalRelief,
    RuleSet,
    SeniorityStep,
    SeveranceStep,
    TaxBracket,
)


@dataclass(frozen=True)
class ChildSpec:
    table: str
    columns: tuple[str, ...]
    validate: Callable[[dict[str, Any]], Result[dict[str, Any]]]
    order_by: str
    label_en: str
    label_fr: str
    json_columns: tuple[str, ...] = ()


CHILD_KINDS: dict[str, ChildSpec] = {
    "components": ChildSpec(
        "payroll.components",
        ("code", "name_en", "name_fr", "kind", "taxable", "contributable", "formula_type", "base_ref",
         "default_amount", "default_rate", "display_order", "payslip_section", "declaration_code"),
        validate_component, "display_order, code", "component", "rubrique"),
    "contributions": ChildSpec(
        "payroll.contributions",
        ("code", "name_en", "name_fr", "base", "employee_rate", "employer_rate", "ceiling_monthly",
         "deductible_from_taxable", "declaration_code", "liability_account_code", "display_order"),
        validate_contribution, "display_order, code", "contribution", "cotisation"),
    "tax_brackets": ChildSpec(
        "payroll.tax_brackets", ("tax_code", "lower_bound", "upper_bound", "rate", "annualised"),
        validate_tax_bracket, "tax_code, lower_bound", "tax bracket", "tranche d'impôt"),
    "tax_reliefs": ChildSpec(
        "payroll.tax_reliefs", ("tax_code", "kind", "parameters"),
        validate_tax_relief, "tax_code, kind", "tax relief", "abattement", json_columns=("parameters",)),
    "seniority_scale": ChildSpec(
        "payroll.seniority_scale", ("years_from", "percent"),
        validate_seniority_step, "years_from", "seniority step", "palier d'ancienneté"),
    "overtime_rates": ChildSpec(
        "payroll.overtime_rates", ("band_code", "multiplier"),
        validate_overtime_rate, "band_code", "overtime rate", "taux d'heures supplémentaires"),
    "severance_scale": ChildSpec(
        "payroll.severance_scale", ("years_from", "percent_per_year"),
        validate_severance_step, "years_from", "severance step", "palier d'indemnité de licenciement"),
}

HEADER_COLUMNS = (
    "country", "name", "valid_from", "round_to", "round_mode", "tax_round_to", "tax_round_mode",
    "working_days_per_month", "working_hours_per_month", "settlement_reference_months", "notes",
)
_HEADER_SELECT = (
    f"SELECT id, status, confirmed_by, confirmed_at, created_by, created_at, {', '.join(HEADER_COLUMNS)} "
    "FROM payroll.rule_sets"
)


def _not_found(what_en: str, what_fr: str) -> Err:
    return Err("NOT_FOUND", f"{what_en} not found", f"{what_fr} introuvable")


def _locked() -> Err:
    return Err("RULESET_LOCKED", "a confirmed rule set cannot be changed; copy it to a new draft or reopen it",
               "un jeu de règles confirmé ne peut pas être modifié ; copiez-le en brouillon ou rouvrez-le")


def _duplicate(spec: ChildSpec) -> Err:
    return Err("DUPLICATE_RULE", f"duplicate {spec.label_en} in this rule set", f"{spec.label_fr} en double dans ce jeu de règles")


def _duplicate_start(clean: dict[str, Any]) -> Err:
    country, start = clean["country"], clean["valid_from"]
    return Err("DUPLICATE_RULESET", f"a {country} rule set already starts in {start:%Y-%m}",
               f"un jeu de règles {country} commence déjà en {start:%m/%Y}")


class RuleSetService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    # -- payroll country and employer identifiers -------------------------------------------
    def get_settings(self, *, tenant_id: str) -> dict[str, Any] | None:
        return fetch_one(
            self.connection,
            "SELECT tenant_id, country, company_address, employer_inps_no, employer_tax_id FROM payroll.settings WHERE tenant_id = %s",
            (tenant_id,),
        )

    def save_settings(self, *, tenant_id: str, actor_id: str, country: str, company_address: str | None = None,
                      employer_inps_no: str | None = None, employer_tax_id: str | None = None) -> Result[dict[str, Any]]:
        code = (country or "").strip().upper()
        if not COUNTRY.match(code):
            return Err("RULE_INVALID", "country is a two-letter ISO code (e.g. ML)", "le pays est un code ISO à deux lettres (ex. ML)")
        self.connection.execute(
            """
            INSERT INTO payroll.settings (tenant_id, country, company_address, employer_inps_no, employer_tax_id, updated_by)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id) DO UPDATE SET
                country = EXCLUDED.country, company_address = EXCLUDED.company_address,
                employer_inps_no = EXCLUDED.employer_inps_no, employer_tax_id = EXCLUDED.employer_tax_id,
                updated_by = EXCLUDED.updated_by, updated_at = NOW()
            """,
            (tenant_id, code, company_address, employer_inps_no, employer_tax_id, actor_id),
        )
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="payroll_settings.updated",
                     entity_type="payroll_settings", entity_id=tenant_id,
                     payload={"country": code, "company_address": company_address,
                              "employer_inps_no": employer_inps_no, "employer_tax_id": employer_tax_id})
        return Ok(self.get_settings(tenant_id=tenant_id))

    # -- rule set headers ------------------------------------------------------------------------
    def _header(self, tenant_id: str, rule_set_id: str, *, lock: bool = False) -> dict[str, Any] | None:
        return fetch_one(self.connection, _HEADER_SELECT + " WHERE tenant_id = %s AND id = %s" + (" FOR UPDATE" if lock else ""),
                         (tenant_id, rule_set_id))

    def list_rule_sets(self, *, tenant_id: str) -> list[dict[str, Any]]:
        return jsonable(fetch_all(self.connection, _HEADER_SELECT + " WHERE tenant_id = %s ORDER BY country, valid_from DESC", (tenant_id,)))

    def get_rule_set(self, *, tenant_id: str, rule_set_id: str) -> dict[str, Any] | None:
        header = self._header(tenant_id, rule_set_id)
        if header is None:
            return None
        document = jsonable(header)
        for kind in CHILD_KINDS:
            document[kind] = self.list_children(tenant_id=tenant_id, rule_set_id=rule_set_id, kind=kind)
        return document

    def create_rule_set(self, *, tenant_id: str, actor_id: str, country: str, name: str, valid_from: datetime.date,
                        working_days_per_month, working_hours_per_month, round_to: int = 1, round_mode: str = "half_up",
                        tax_round_to: int = 1, tax_round_mode: str = "half_up", settlement_reference_months: int = 12,
                        notes: str | None = None) -> Result[dict[str, Any]]:
        checked = validate_rule_set_header({
            "country": country, "name": name, "valid_from": valid_from, "round_to": round_to, "round_mode": round_mode,
            "tax_round_to": tax_round_to, "tax_round_mode": tax_round_mode,
            "working_days_per_month": working_days_per_month, "working_hours_per_month": working_hours_per_month,
            "settlement_reference_months": settlement_reference_months, "notes": notes,
        })
        if isinstance(checked, Err):
            return checked
        clean = checked.value
        rule_set_id = str(ULID())
        try:
            with self.connection.transaction():
                self.connection.execute(
                    f"INSERT INTO payroll.rule_sets (id, tenant_id, created_by, {', '.join(HEADER_COLUMNS)}) "
                    f"VALUES (%s, %s, %s, {', '.join(['%s'] * len(HEADER_COLUMNS))})",
                    (rule_set_id, tenant_id, actor_id, *(clean[column] for column in HEADER_COLUMNS)),
                )
        except psycopg.errors.UniqueViolation:
            return _duplicate_start(clean)
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="rule_set.created",
                     entity_type="rule_set", entity_id=rule_set_id,
                     payload={"country": clean["country"], "valid_from": clean["valid_from"].isoformat(), "name": clean["name"]})
        return Ok(self.get_rule_set(tenant_id=tenant_id, rule_set_id=rule_set_id))

    def update_rule_set(self, *, tenant_id: str, actor_id: str, rule_set_id: str, changes: dict[str, Any]) -> Result[dict[str, Any]]:
        header = self._header(tenant_id, rule_set_id, lock=True)
        if header is None:
            return _not_found("rule set", "jeu de règles")
        if header["status"] == "confirmed":
            return _locked()
        unknown = sorted(set(changes) - set(HEADER_COLUMNS))
        if unknown:
            return Err("RULE_INVALID", f"unknown fields: {', '.join(unknown)}", f"champs inconnus : {', '.join(unknown)}")
        checked = validate_rule_set_header({**{column: header[column] for column in HEADER_COLUMNS}, **changes})
        if isinstance(checked, Err):
            return checked
        clean = checked.value
        try:
            with self.connection.transaction():
                self.connection.execute(
                    f"UPDATE payroll.rule_sets SET {', '.join(f'{column} = %s' for column in HEADER_COLUMNS)} WHERE id = %s",
                    (*(clean[column] for column in HEADER_COLUMNS), rule_set_id),
                )
        except psycopg.errors.UniqueViolation:
            return _duplicate_start(clean)
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="rule_set.updated",
                     entity_type="rule_set", entity_id=rule_set_id,
                     payload={"changes": jsonable({column: clean[column] for column in changes})})
        return Ok(self.get_rule_set(tenant_id=tenant_id, rule_set_id=rule_set_id))

    def delete_rule_set(self, *, tenant_id: str, actor_id: str, rule_set_id: str) -> Result[dict[str, Any]]:
        header = self._header(tenant_id, rule_set_id, lock=True)
        if header is None:
            return _not_found("rule set", "jeu de règles")
        if header["status"] == "confirmed":
            return _locked()
        try:
            with self.connection.transaction():
                self.connection.execute("DELETE FROM payroll.rule_sets WHERE id = %s", (rule_set_id,))
        except psycopg.errors.ForeignKeyViolation:
            return Err("RULESET_IN_USE", "payroll runs were calculated with this rule set; it cannot be deleted",
                       "des paies ont été calculées avec ce jeu de règles ; il ne peut pas être supprimé")
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="rule_set.deleted",
                     entity_type="rule_set", entity_id=rule_set_id,
                     payload={"country": header["country"], "valid_from": header["valid_from"].isoformat(),
                              "name": header["name"], "status": header["status"]})
        return Ok({"id": rule_set_id})

    def copy_rule_set(self, *, tenant_id: str, actor_id: str, rule_set_id: str, valid_from: datetime.date,
                      name: str) -> Result[dict[str, Any]]:
        source = self._header(tenant_id, rule_set_id)
        if source is None:
            return _not_found("rule set", "jeu de règles")
        kept = {column: source[column] for column in HEADER_COLUMNS if column not in ("name", "valid_from")}
        created = self.create_rule_set(tenant_id=tenant_id, actor_id=actor_id, name=name, valid_from=valid_from, **kept)
        if isinstance(created, Err):
            return created
        new_id = created.value["id"]
        for spec in CHILD_KINDS.values():
            rows = fetch_all(self.connection, f"SELECT {', '.join(spec.columns)} FROM {spec.table} WHERE rule_set_id = %s", (rule_set_id,))
            for row in rows:
                self._insert_child(tenant_id, new_id, spec, row)
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="rule_set.copied",
                     entity_type="rule_set", entity_id=new_id, payload={"from_rule_set_id": rule_set_id})
        return Ok(self.get_rule_set(tenant_id=tenant_id, rule_set_id=new_id))

    def confirm_rule_set(self, *, tenant_id: str, actor_id: str, rule_set_id: str) -> Result[dict[str, Any]]:
        header = self._header(tenant_id, rule_set_id, lock=True)
        if header is None:
            return _not_found("rule set", "jeu de règles")
        if header["status"] == "confirmed":
            return Err("RULESET_LOCKED", "this rule set is already confirmed", "ce jeu de règles est déjà confirmé")
        problems = check_complete(self.load(tenant_id=tenant_id, rule_set_id=rule_set_id))
        if problems:
            return Err("RULESET_INCOMPLETE", "; ".join(english for english, _ in problems), "; ".join(french for _, french in problems))
        # clock_timestamp, not NOW(): approval compares it with the run's calculation time, and both
        # may happen inside one transaction (tests, seed scripts).
        self.connection.execute(
            "UPDATE payroll.rule_sets SET status = 'confirmed', confirmed_by = %s, confirmed_at = clock_timestamp() WHERE id = %s",
            (actor_id, rule_set_id),
        )
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="rule_set.confirmed",
                     entity_type="rule_set", entity_id=rule_set_id, payload={"from_status": "draft", "to_status": "confirmed"})
        return Ok(self.get_rule_set(tenant_id=tenant_id, rule_set_id=rule_set_id))

    # -- rule rows --------------------------------------------------------------------------------
    def list_children(self, *, tenant_id: str, rule_set_id: str, kind: str) -> list[dict[str, Any]]:
        spec = CHILD_KINDS[kind]
        return jsonable(fetch_all(
            self.connection,
            f"SELECT id, {', '.join(spec.columns)} FROM {spec.table} WHERE tenant_id = %s AND rule_set_id = %s ORDER BY {spec.order_by}",
            (tenant_id, rule_set_id),
        ))

    def _child(self, tenant_id: str, spec: ChildSpec, row_id: str) -> dict[str, Any] | None:
        return fetch_one(self.connection, f"SELECT id, rule_set_id, {', '.join(spec.columns)} FROM {spec.table} WHERE tenant_id = %s AND id = %s",
                         (tenant_id, row_id))

    def _insert_child(self, tenant_id: str, rule_set_id: str, spec: ChildSpec, clean: dict[str, Any]) -> str:
        row_id = str(ULID())
        values = [Jsonb(clean[column]) if column in spec.json_columns else clean[column] for column in spec.columns]
        self.connection.execute(
            f"INSERT INTO {spec.table} (id, tenant_id, rule_set_id, {', '.join(spec.columns)}) "
            f"VALUES (%s, %s, %s, {', '.join(['%s'] * len(spec.columns))})",
            (row_id, tenant_id, rule_set_id, *values),
        )
        return row_id

    def _editable(self, tenant_id: str, rule_set_id: str, kind: str) -> Result[ChildSpec]:
        spec = CHILD_KINDS.get(kind)
        if spec is None:
            return _not_found(f"rule table {kind}", f"table de règles {kind}")
        header = self._header(tenant_id, rule_set_id, lock=True)
        if header is None:
            return _not_found("rule set", "jeu de règles")
        if header["status"] == "confirmed":
            return _locked()
        return Ok(spec)

    def add_child(self, *, tenant_id: str, actor_id: str, rule_set_id: str, kind: str, values: dict[str, Any]) -> Result[dict[str, Any]]:
        editable = self._editable(tenant_id, rule_set_id, kind)
        if isinstance(editable, Err):
            return editable
        spec = editable.value
        checked = spec.validate(values)
        if isinstance(checked, Err):
            return checked
        try:
            with self.connection.transaction():
                row_id = self._insert_child(tenant_id, rule_set_id, spec, checked.value)
        except psycopg.errors.UniqueViolation:
            return _duplicate(spec)
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="rule_set.row_added",
                     entity_type="rule_set", entity_id=rule_set_id,
                     payload={"kind": kind, "row_id": row_id, "values": jsonable(checked.value)})
        return Ok(jsonable(self._child(tenant_id, spec, row_id)))

    def update_child(self, *, tenant_id: str, actor_id: str, rule_set_id: str, kind: str, row_id: str,
                     changes: dict[str, Any]) -> Result[dict[str, Any]]:
        editable = self._editable(tenant_id, rule_set_id, kind)
        if isinstance(editable, Err):
            return editable
        spec = editable.value
        current = self._child(tenant_id, spec, row_id)
        if current is None or current["rule_set_id"] != rule_set_id:
            return _not_found(spec.label_en, spec.label_fr)
        checked = spec.validate({**{column: current[column] for column in spec.columns}, **changes})
        if isinstance(checked, Err):
            return checked
        clean = checked.value
        values = [Jsonb(clean[column]) if column in spec.json_columns else clean[column] for column in spec.columns]
        try:
            with self.connection.transaction():
                self.connection.execute(
                    f"UPDATE {spec.table} SET {', '.join(f'{column} = %s' for column in spec.columns)} WHERE id = %s",
                    (*values, row_id),
                )
        except psycopg.errors.UniqueViolation:
            return _duplicate(spec)
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="rule_set.row_updated",
                     entity_type="rule_set", entity_id=rule_set_id,
                     payload={"kind": kind, "row_id": row_id, "changes": jsonable({c: clean[c] for c in changes if c in clean})})
        return Ok(jsonable(self._child(tenant_id, spec, row_id)))

    def delete_child(self, *, tenant_id: str, actor_id: str, rule_set_id: str, kind: str, row_id: str) -> Result[dict[str, Any]]:
        editable = self._editable(tenant_id, rule_set_id, kind)
        if isinstance(editable, Err):
            return editable
        spec = editable.value
        current = self._child(tenant_id, spec, row_id)
        if current is None or current["rule_set_id"] != rule_set_id:
            return _not_found(spec.label_en, spec.label_fr)
        self.connection.execute(f"DELETE FROM {spec.table} WHERE id = %s", (row_id,))
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="rule_set.row_deleted",
                     entity_type="rule_set", entity_id=rule_set_id,
                     payload={"kind": kind, "row_id": row_id, "row": jsonable({c: current[c] for c in spec.columns})})
        return Ok({"id": row_id})

    # -- what the engine reads --------------------------------------------------------------------
    def load(self, *, tenant_id: str, rule_set_id: str) -> RuleSet | None:
        header = self._header(tenant_id, rule_set_id)
        if header is None:
            return None
        rows = {
            kind: fetch_all(self.connection,
                            f"SELECT {', '.join(spec.columns)} FROM {spec.table} WHERE tenant_id = %s AND rule_set_id = %s ORDER BY {spec.order_by}",
                            (tenant_id, rule_set_id))
            for kind, spec in CHILD_KINDS.items()
        }
        reliefs = [relief_from_parameters(row["tax_code"], row["kind"], row["parameters"]) for row in rows["tax_reliefs"]]
        return RuleSet(
            id=header["id"], country=header["country"], valid_from=header["valid_from"], status=header["status"],
            round_to=header["round_to"], round_mode=header["round_mode"],
            tax_round_to=header["tax_round_to"], tax_round_mode=header["tax_round_mode"],
            working_days_per_month=header["working_days_per_month"],
            working_hours_per_month=header["working_hours_per_month"],
            settlement_reference_months=header["settlement_reference_months"],
            components=tuple(ComponentRule(**row) for row in rows["components"]),
            contributions=tuple(ContributionRule(**row) for row in rows["contributions"]),
            tax_brackets=tuple(TaxBracket(tax_code=row["tax_code"], lower=row["lower_bound"], upper=row["upper_bound"],
                                          rate=row["rate"], annualised=row["annualised"]) for row in rows["tax_brackets"]),
            family_reliefs=tuple(relief for relief in reliefs if isinstance(relief, FamilyRelief)),
            professional_reliefs=tuple(relief for relief in reliefs if isinstance(relief, ProfessionalRelief)),
            seniority_scale=tuple(SeniorityStep(**row) for row in rows["seniority_scale"]),
            overtime_rates=tuple(OvertimeRate(**row) for row in rows["overtime_rates"]),
            severance_scale=tuple(SeveranceStep(**row) for row in rows["severance_scale"]),
        )

    def in_force(self, *, tenant_id: str, period: datetime.date) -> Result[dict[str, Any]]:
        settings = self.get_settings(tenant_id=tenant_id)
        if settings is None:
            return Err("RULESET_MISSING", "set the payroll country first (Payroll → Rules)",
                       "renseignez d'abord le pays de paie (Paie → Règles)")
        country = settings["country"]
        row = fetch_one(
            self.connection,
            _HEADER_SELECT + " WHERE tenant_id = %s AND country = %s AND valid_from <= %s ORDER BY valid_from DESC LIMIT 1",
            (tenant_id, country, period),
        )
        if row is None:
            return Err("RULESET_MISSING", f"no {country} rule set applies to {period:%Y-%m}",
                       f"aucun jeu de règles {country} ne s'applique à {period:%m/%Y}")
        return Ok(row)
```

- [ ] **Step 5: Write `testing_support.py`**

```python
"""Helpers the payroll integration tests share. Not imported by production code."""
from __future__ import annotations

import datetime
from dataclasses import asdict
from typing import Any

from ulid import ULID

from core.domain.result import Ok
from modules.payroll.api.rule_set_service import RuleSetService
from modules.payroll.domain.rule_validation import relief_parameters
from modules.payroll.domain.rules import RuleSet
from modules.payroll.domain.synthetic import synthetic_rule_set

TEST_COUNTRY = "ZZ"  # ISO "user-assigned" code: never a real payroll country


def make_user(connection, tenant_id: str) -> str:
    user_id = str(ULID())
    connection.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (user_id, tenant_id, f"{user_id}@test.local"),
    )
    return user_id


def rule_rows(rules: RuleSet) -> dict[str, list[dict[str, Any]]]:
    """The domain rule set as the values an admin would type, table by table."""
    return {
        "components": [asdict(component) for component in rules.components],
        "contributions": [asdict(contribution) for contribution in rules.contributions],
        "tax_brackets": [{"tax_code": b.tax_code, "lower_bound": b.lower, "upper_bound": b.upper, "rate": b.rate,
                          "annualised": b.annualised} for b in rules.tax_brackets],
        "tax_reliefs": [{"tax_code": r.tax_code, "kind": "family", "parameters": relief_parameters(r)} for r in rules.family_reliefs]
        + [{"tax_code": r.tax_code, "kind": "professional_expenses", "parameters": relief_parameters(r)} for r in rules.professional_reliefs],
        "seniority_scale": [asdict(step) for step in rules.seniority_scale],
        "overtime_rates": [asdict(rate) for rate in rules.overtime_rates],
        "severance_scale": [asdict(step) for step in rules.severance_scale],
    }


def store_rule_set(connection, *, tenant_id: str, actor_id: str, valid_from: datetime.date, rules: RuleSet | None = None,
                   confirm: bool = True, country: str = TEST_COUNTRY, name: str = "Synthetic test rules") -> str:
    rules = rules or synthetic_rule_set()
    service = RuleSetService(connection)
    created = service.create_rule_set(
        tenant_id=tenant_id, actor_id=actor_id, country=country, name=name, valid_from=valid_from,
        working_days_per_month=rules.working_days_per_month, working_hours_per_month=rules.working_hours_per_month,
        round_to=rules.round_to, round_mode=rules.round_mode, tax_round_to=rules.tax_round_to,
        tax_round_mode=rules.tax_round_mode, settlement_reference_months=rules.settlement_reference_months,
    )
    assert isinstance(created, Ok), created
    rule_set_id = created.value["id"]
    for kind, rows in rule_rows(rules).items():
        for values in rows:
            added = service.add_child(tenant_id=tenant_id, actor_id=actor_id, rule_set_id=rule_set_id, kind=kind, values=values)
            assert isinstance(added, Ok), added
    if confirm:
        confirmed = service.confirm_rule_set(tenant_id=tenant_id, actor_id=actor_id, rule_set_id=rule_set_id)
        assert isinstance(confirmed, Ok), confirmed
    return rule_set_id


def set_country(connection, *, tenant_id: str, actor_id: str, country: str = TEST_COUNTRY) -> None:
    saved = RuleSetService(connection).save_settings(tenant_id=tenant_id, actor_id=actor_id, country=country)
    assert isinstance(saved, Ok), saved
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest modules/payroll/api/test_rule_set_service_integration.py core/test_error_translations.py -q`
Expected: `13 passed` (12 rule-set tests + the bilingual guard), no skips.

- [ ] **Step 7: Commit**

```bash
git add backend/modules/payroll/api/rows.py backend/modules/payroll/api/rule_set_service.py backend/modules/payroll/api/testing_support.py backend/modules/payroll/api/test_rule_set_service_integration.py
git commit -m "feat(payroll): rule-set service with draft editing, confirmation lock and loading

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: Rules HTTP routes

**Files:**
- Create: `backend/modules/payroll/api/http.py`
- Create: `backend/modules/payroll/api/routes_rules.py`
- Modify: `backend/modules/payroll/api/router.py`
- Test: `backend/modules/payroll/api/test_rules_router_integration.py`

**Interfaces:**
- Consumes: `RuleSetService`, `CHILD_KINDS` (Task 10).
- Produces:
  - `http.get_connection` (re-export of `core.db.get_connection`; routes call `http.get_connection()` so router tests patch one name), `http.status_for(err) -> int` (`NOT_FOUND`→404; `DUPLICATE_*` and the conflict codes `RULESET_LOCKED, RULESET_IN_USE, RULESET_NOT_CONFIRMED, RUN_LOCKED, RUN_NOT_CALCULATED, RUN_NOT_APPROVED, RUN_NOT_REVERSIBLE, SAME_USER_APPROVAL, PRESENCE_NOT_CLOSED, PAYOUT_CONFIRMED, PAYOUT_INCOMPLETE`→409; everything else 422), `http.fail(err) -> NoReturn`, `http.finish(connection, result) -> value` (commit, or rollback + raise), `http.found(value, what_en, what_fr) -> value` (404 when None).
  - Routes (all under `/payroll`):

| Method | Path | Permission |
|---|---|---|
| GET | `/settings` | `payroll.view_rules` |
| PUT | `/settings` | `payroll.manage_rules` |
| GET | `/rule-sets` | `payroll.view_rules` |
| POST | `/rule-sets` | `payroll.manage_rules` |
| GET | `/rule-sets/{id}` | `payroll.view_rules` |
| PATCH | `/rule-sets/{id}` | `payroll.manage_rules` |
| DELETE | `/rule-sets/{id}` | `payroll.manage_rules` |
| POST | `/rule-sets/{id}/copy` | `payroll.manage_rules` |
| POST | `/rule-sets/{id}/confirm` | `payroll.confirm_rules` |
| GET | `/rule-sets/{id}/{kind}` | `payroll.view_rules` |
| POST | `/rule-sets/{id}/{kind}` | `payroll.manage_rules` |
| PATCH | `/rule-sets/{id}/{kind}/{row_id}` | `payroll.manage_rules` |
| DELETE | `/rule-sets/{id}/{kind}/{row_id}` | `payroll.manage_rules` |

  Fixed-word routes (`copy`, `confirm`, and 3b's `reopen`) are declared **before** the generic `{kind}` routes, since FastAPI matches in declaration order.

- [ ] **Step 1: Write the failing router tests**

Create `backend/modules/payroll/api/test_rules_router_integration.py`:

```python
"""The rules endpoints over HTTP: rights per action, and refusal codes mapped to statuses.

A throwaway FastAPI app carries the payroll router; the session is overridden and every
connection is the `db` fixture's rolled-back one (commit/rollback are no-ops).
"""
from __future__ import annotations

import datetime

import pytest
from fastapi import FastAPI

pytest.importorskip("httpx", reason="the FastAPI test client needs httpx (requirements-dev.txt)")
from fastapi.testclient import TestClient  # noqa: E402

from core.tenancy import TenantContext, require_session  # noqa: E402
from modules.payroll.api import http  # noqa: E402
from modules.payroll.api.router import router  # noqa: E402
from modules.payroll.api.testing_support import make_user, store_rule_set  # noqa: E402

TENANT = "payroll-rules-router-test"
BODY = {"country": "ZZ", "name": "Router test", "valid_from": "2031-01-01",
        "working_days_per_month": 20, "working_hours_per_month": 160}


class _Connection:
    """The fixture's connection, with the transaction left to the fixture."""

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


@pytest.fixture
def world(db, monkeypatch):
    user = make_user(db, TENANT)
    wrapped = _Connection(db)
    monkeypatch.setattr(http, "get_connection", lambda: wrapped)
    monkeypatch.setattr("core.tenancy.get_connection", lambda: wrapped)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_session] = lambda: TenantContext(tenant_id=TENANT, user_id=user, session_token="t")

    def grant(*permissions: str) -> None:
        for permission in permissions:
            db.execute("INSERT INTO core.user_permissions (user_id, permission) VALUES (%s, %s)", (user, permission))

    return {"client": TestClient(app), "grant": grant, "db": db, "user": user}


def test_reading_the_rules_needs_view_rules(world):
    assert world["client"].get("/payroll/rule-sets").status_code == 403
    world["grant"]("payroll.view_rules")
    assert world["client"].get("/payroll/rule-sets").status_code == 200


def test_creating_and_confirming_need_their_own_rights(world):
    client = world["client"]
    world["grant"]("payroll.view_rules", "payroll.manage_rules")
    created = client.post("/payroll/rule-sets", json=BODY)
    assert created.status_code == 201, created.text
    rule_set_id = created.json()["id"]
    row = client.post(f"/payroll/rule-sets/{rule_set_id}/overtime_rates", json={"band_code": "day", "multiplier": 1.5})
    assert row.status_code == 201, row.text
    assert client.post(f"/payroll/rule-sets/{rule_set_id}/confirm").status_code == 403
    world["grant"]("payroll.confirm_rules")
    refused = client.post(f"/payroll/rule-sets/{rule_set_id}/confirm")
    assert refused.status_code == 422
    assert refused.json()["detail"]["code"] == "RULESET_INCOMPLETE" and refused.json()["detail"]["message_fr"]


def test_a_confirmed_rule_set_answers_409(world):
    world["grant"]("payroll.view_rules", "payroll.manage_rules")
    rule_set_id = store_rule_set(world["db"], tenant_id=TENANT, actor_id=world["user"], valid_from=datetime.date(2031, 1, 1))
    response = world["client"].patch(f"/payroll/rule-sets/{rule_set_id}", json={"name": "x"})
    assert response.status_code == 409 and response.json()["detail"]["code"] == "RULESET_LOCKED"


def test_a_duplicate_start_answers_409_and_an_unknown_table_404(world):
    client = world["client"]
    world["grant"]("payroll.view_rules", "payroll.manage_rules")
    first = client.post("/payroll/rule-sets", json=BODY)
    assert client.post("/payroll/rule-sets", json=BODY).status_code == 409
    assert client.get(f"/payroll/rule-sets/{first.json()['id']}/nonsense").status_code == 404


def test_settings_round_trip(world):
    world["grant"]("payroll.view_rules", "payroll.manage_rules")
    saved = world["client"].put("/payroll/settings", json={"country": "zz", "employer_inps_no": "123"})
    assert saved.status_code == 200 and saved.json()["country"] == "ZZ"
    assert world["client"].get("/payroll/settings").json()["employer_inps_no"] == "123"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python -m pytest modules/payroll/api/test_rules_router_integration.py -q`
Expected: FAIL — `ImportError: cannot import name 'http' from 'modules.payroll.api'`.

- [ ] **Step 3: Write `http.py`**

```python
"""What every payroll route shares.

Routes open connections through `http.get_connection()` (never a direct import), so router tests
patch this one name. `finish` commits a successful write, or rolls it back and raises its refusal
as {"code", "message", "message_fr"} with the right status.
"""
from __future__ import annotations

from typing import NoReturn, TypeVar

from fastapi import HTTPException, status

from core.db import get_connection as get_connection  # noqa: PLC0414 - re-exported patch point
from core.domain.result import Err, Result, err_detail

T = TypeVar("T")

CONFLICT_CODES = frozenset({
    "RULESET_LOCKED", "RULESET_IN_USE", "RULESET_NOT_CONFIRMED",
    "RUN_LOCKED", "RUN_NOT_CALCULATED", "RUN_NOT_APPROVED", "RUN_NOT_REVERSIBLE",
    "SAME_USER_APPROVAL", "PRESENCE_NOT_CLOSED", "PAYOUT_CONFIRMED", "PAYOUT_INCOMPLETE",
})


def status_for(err: Err) -> int:
    if err.code == "NOT_FOUND":
        return status.HTTP_404_NOT_FOUND
    if err.code in CONFLICT_CODES or err.code.startswith("DUPLICATE"):
        return status.HTTP_409_CONFLICT
    return status.HTTP_422_UNPROCESSABLE_ENTITY


def fail(err: Err) -> NoReturn:
    raise HTTPException(status_for(err), err_detail(err))


def finish(connection, result: Result[T]) -> T:
    if isinstance(result, Err):
        connection.rollback()
        fail(result)
    connection.commit()
    return result.value


def found(value: T | None, what_en: str, what_fr: str) -> T:
    if value is None:
        fail(Err("NOT_FOUND", f"{what_en} not found", f"{what_fr} introuvable"))
    return value
```

- [ ] **Step 4: Write `routes_rules.py`**

```python
"""HTTP routes for the payroll country and the rule sets (Payroll → Rules)."""
from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Body, Depends, status
from pydantic import BaseModel

from core.domain.result import Err
from core.tenancy import TenantContext, require_permission
from modules.payroll.api import http
from modules.payroll.api.rule_set_service import CHILD_KINDS, RuleSetService

router = APIRouter()


class SettingsBody(BaseModel):
    country: str
    company_address: str | None = None
    employer_inps_no: str | None = None
    employer_tax_id: str | None = None


class RuleSetBody(BaseModel):
    country: str
    name: str
    valid_from: datetime.date
    working_days_per_month: Decimal
    working_hours_per_month: Decimal
    round_to: int = 1
    round_mode: str = "half_up"
    tax_round_to: int = 1
    tax_round_mode: str = "half_up"
    settlement_reference_months: int = 12
    notes: str | None = None


class RuleSetPatch(BaseModel):
    country: str | None = None
    name: str | None = None
    valid_from: datetime.date | None = None
    working_days_per_month: Decimal | None = None
    working_hours_per_month: Decimal | None = None
    round_to: int | None = None
    round_mode: str | None = None
    tax_round_to: int | None = None
    tax_round_mode: str | None = None
    settlement_reference_months: int | None = None
    notes: str | None = None


class CopyBody(BaseModel):
    valid_from: datetime.date
    name: str


def _known_kind(kind: str) -> None:
    if kind not in CHILD_KINDS:
        http.fail(Err("NOT_FOUND", f"unknown rule table {kind}", f"table de règles inconnue {kind}"))


@router.get("/settings")
def get_settings(tenant: TenantContext = Depends(require_permission("payroll.view_rules"))):
    with http.get_connection() as connection:
        return RuleSetService(connection).get_settings(tenant_id=tenant.tenant_id)


@router.put("/settings")
def save_settings(body: SettingsBody, tenant: TenantContext = Depends(require_permission("payroll.manage_rules"))):
    with http.get_connection() as connection:
        result = RuleSetService(connection).save_settings(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, **body.model_dump())
        return http.finish(connection, result)


@router.get("/rule-sets")
def list_rule_sets(tenant: TenantContext = Depends(require_permission("payroll.view_rules"))):
    with http.get_connection() as connection:
        return RuleSetService(connection).list_rule_sets(tenant_id=tenant.tenant_id)


@router.post("/rule-sets", status_code=status.HTTP_201_CREATED)
def create_rule_set(body: RuleSetBody, tenant: TenantContext = Depends(require_permission("payroll.manage_rules"))):
    with http.get_connection() as connection:
        result = RuleSetService(connection).create_rule_set(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, **body.model_dump())
        return http.finish(connection, result)


@router.get("/rule-sets/{rule_set_id}")
def get_rule_set(rule_set_id: str, tenant: TenantContext = Depends(require_permission("payroll.view_rules"))):
    with http.get_connection() as connection:
        document = RuleSetService(connection).get_rule_set(tenant_id=tenant.tenant_id, rule_set_id=rule_set_id)
        return http.found(document, "rule set", "jeu de règles")


@router.patch("/rule-sets/{rule_set_id}")
def update_rule_set(rule_set_id: str, body: RuleSetPatch, tenant: TenantContext = Depends(require_permission("payroll.manage_rules"))):
    with http.get_connection() as connection:
        result = RuleSetService(connection).update_rule_set(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, rule_set_id=rule_set_id,
            changes=body.model_dump(exclude_unset=True),
        )
        return http.finish(connection, result)


@router.delete("/rule-sets/{rule_set_id}")
def delete_rule_set(rule_set_id: str, tenant: TenantContext = Depends(require_permission("payroll.manage_rules"))):
    with http.get_connection() as connection:
        result = RuleSetService(connection).delete_rule_set(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, rule_set_id=rule_set_id)
        return http.finish(connection, result)


@router.post("/rule-sets/{rule_set_id}/copy", status_code=status.HTTP_201_CREATED)
def copy_rule_set(rule_set_id: str, body: CopyBody, tenant: TenantContext = Depends(require_permission("payroll.manage_rules"))):
    with http.get_connection() as connection:
        result = RuleSetService(connection).copy_rule_set(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, rule_set_id=rule_set_id,
            valid_from=body.valid_from, name=body.name,
        )
        return http.finish(connection, result)


@router.post("/rule-sets/{rule_set_id}/confirm")
def confirm_rule_set(rule_set_id: str, tenant: TenantContext = Depends(require_permission("payroll.confirm_rules"))):
    with http.get_connection() as connection:
        result = RuleSetService(connection).confirm_rule_set(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, rule_set_id=rule_set_id)
        return http.finish(connection, result)


# Generic rule-table routes stay LAST: "/rule-sets/{id}/{kind}" would otherwise swallow copy/confirm/reopen.
@router.get("/rule-sets/{rule_set_id}/{kind}")
def list_rule_rows(rule_set_id: str, kind: str, tenant: TenantContext = Depends(require_permission("payroll.view_rules"))):
    _known_kind(kind)
    with http.get_connection() as connection:
        return RuleSetService(connection).list_children(tenant_id=tenant.tenant_id, rule_set_id=rule_set_id, kind=kind)


@router.post("/rule-sets/{rule_set_id}/{kind}", status_code=status.HTTP_201_CREATED)
def add_rule_row(rule_set_id: str, kind: str, values: dict[str, Any] = Body(...),
                 tenant: TenantContext = Depends(require_permission("payroll.manage_rules"))):
    _known_kind(kind)
    with http.get_connection() as connection:
        result = RuleSetService(connection).add_child(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, rule_set_id=rule_set_id, kind=kind, values=values,
        )
        return http.finish(connection, result)


@router.patch("/rule-sets/{rule_set_id}/{kind}/{row_id}")
def update_rule_row(rule_set_id: str, kind: str, row_id: str, changes: dict[str, Any] = Body(...),
                    tenant: TenantContext = Depends(require_permission("payroll.manage_rules"))):
    _known_kind(kind)
    with http.get_connection() as connection:
        result = RuleSetService(connection).update_child(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, rule_set_id=rule_set_id, kind=kind,
            row_id=row_id, changes=changes,
        )
        return http.finish(connection, result)


@router.delete("/rule-sets/{rule_set_id}/{kind}/{row_id}")
def delete_rule_row(rule_set_id: str, kind: str, row_id: str,
                    tenant: TenantContext = Depends(require_permission("payroll.manage_rules"))):
    _known_kind(kind)
    with http.get_connection() as connection:
        result = RuleSetService(connection).delete_child(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, rule_set_id=rule_set_id, kind=kind, row_id=row_id,
        )
        return http.finish(connection, result)
```

- [ ] **Step 5: Include the rules routes in the payroll router**

Replace `backend/modules/payroll/api/router.py` with:

```python
"""Every payroll endpoint hangs off this router; each area adds its own sub-router here."""
from __future__ import annotations

from fastapi import APIRouter

from modules.payroll.api.routes_rules import router as rules_router

router = APIRouter(prefix="/payroll", tags=["payroll"])
router.include_router(rules_router)
```

- [ ] **Step 6: Run the router tests, the payroll suite and the bilingual guard**

Run: `.venv/Scripts/python -m pytest modules/payroll core/test_error_translations.py -q`
Expected: every test passes, **no skips** (router tests need `httpx`; if they skip, `pip install -r requirements-dev.txt` into `.venv`).

- [ ] **Step 7: Check the app still starts**

Run: `.venv/Scripts/python -c "import app.main; print(sorted({r.path for r in app.main.app.routes if r.path.startswith('/payroll')})[:3])"`
Expected: prints `['/payroll/rule-sets', '/payroll/rule-sets/{rule_set_id}', '/payroll/rule-sets/{rule_set_id}/confirm']`.

- [ ] **Step 8: Commit**

```bash
git add backend/modules/payroll/api/http.py backend/modules/payroll/api/routes_rules.py backend/modules/payroll/api/router.py backend/modules/payroll/api/test_rules_router_integration.py
git commit -m "feat(payroll): rules and payroll-country HTTP routes

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Self-review (3a)

- **Spec coverage (Phase 3 "Rule tables" + "Engine")**: rule_sets with country/valid_from/status/confirmed_by/at/round_to/round_mode/working days & hours (Task 1, 10); components with kind/taxable/contributable/formula/base/display order/payslip section (Tasks 1, 3); contributions with base/employee & employer rate/ceiling/liability account (Tasks 1, 3, 5); tax brackets with annualised (Tasks 1, 3, 6); reliefs family & professional expenses as JSON parameters (Tasks 1, 3, 6); seniority scale and overtime rates by band `day/night/rest_holiday` (Tasks 1, 4); engine steps 1–6 each tested alone (Tasks 4–7), proration, rounding, net-negative carry (Tasks 2, 4, 7), golden tests on a synthetic rule set (Task 9); final-settlement formulas (Task 8); draft/confirmed with confirmation gate (Tasks 3, 10, 11). Runs, approval (`RULESET_NOT_CONFIRMED`), payslips, payouts, declarations, events, contract services, frontend and the Mali seed are in plan 3b.
- **Additions beyond the spec's column lists, and why**: `payroll.settings` (which country's rules apply + employer identifiers on payslips/declarations), `tax_round_to/tax_round_mode` (the spec's "ITS may round down to 10 or 100 — also data"), `settlement_reference_months` and `payroll.severance_scale` (the spec makes severance "formula components from the rule set"; the averaging window and the tiers are statutory, so they are data), `deductible_from_taxable` and `declaration_code` on contributions (step 4 needs "deductible employee contributions"; declarations group INPS/AMO by it).
- **Placeholders**: none; every code step is complete.
- **Type consistency**: `PayslipLine` fields are used identically in Tasks 4–9; `RuleSet.settlement_reference_months` is consumed by 3b; `CHILD_KINDS` keys match the route `{kind}` values and the frontend kinds in 3b.
