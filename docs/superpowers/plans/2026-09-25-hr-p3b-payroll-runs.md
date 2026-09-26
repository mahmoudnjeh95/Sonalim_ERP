# HR Phase 3b — Payroll runs, payouts, declarations, screens Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the payroll engine of plan 3a into a working monthly payroll: runs (regular and off-cycle) calculated from hr's contract snapshot and closed presence month, one-off inputs, advances and loans, final settlements, payslips with printable HTML, payouts (bank CSV per bank template, mobile-money CSV per operator, cash sheet with billetage), INPS/AMO/ITS/employer-tax declarations and the annual recap, the `payroll.run.*` events, the contract services `PayrollPostingService` and `PayrollReportService`, the `/payroll/*` screens, and a Mali **draft** seed.

**Architecture:** Services in `backend/modules/payroll/api/` persist runs/payslips with raw SQL and call the pure engine (`domain/engine.py`, plan 3a). hr is read **only** through `PayrollSnapshotService.employees_for_period` and `PresenceService.month_summary / is_month_closed` (contract), injected into the services so tests pass fakes. Status changes write the transactional outbox (`core.events.outbox.publish_event`) in the same transaction and are audited. The React feature folder `frontend/src/features/payroll/` holds the pages, a TanStack Query `api.ts`, and print pages rendered outside the app layout.

**Tech Stack:** Python 3.11, FastAPI, psycopg 3, `decimal.Decimal`, pytest; React 18 + TypeScript, TanStack Query, React Router, React Hook Form + Zod, Tailwind + the repo's Radix primitives.

**Spec:** `docs/superpowers/specs/2026-09-25-hr-payroll-finance-design.md` (Phase 3), contract `docs/superpowers/plans/2026-09-25-hr-payroll-finance-interfaces.md`. **Depends on:** `docs/superpowers/plans/2026-09-25-hr-p3a-payroll-engine.md` (all 11 tasks merged) and hr phases 1–2.

**Scope of this file (Tasks 1–13):** every backend piece — runs, inputs, advances/loans, final settlements, approval/reversal with events, payouts, payslip reads/print/edit, declarations, and the two contract services. It is complete and independently mergeable: each task ends green with no skips, and the API surface it produces is exactly what a frontend or a later phase needs. **Continuation plan** `docs/superpowers/plans/2026-09-25-hr-p3c-payroll-frontend-seed.md` (not yet written) covers the `/payroll/*` screens and the Mali draft seed script named in the Goal above — write it before demoing the module to the client; every backend route it will call already exists and is tested here.

## Global Constraints

- Money is `NUMERIC(18,0)` XOF in the database, `Decimal` in Python, integers in JSON; "F CFA" in the UI.
- A period is a `datetime.date` equal to the first day of the month (`YYYY-MM-01` over HTTP).
- hr is reached only through `modules/hr/api/payroll_snapshot_service.py::PayrollSnapshotService.employees_for_period(*, tenant_id, period, employee_ids=None)` and `modules/hr/api/presence_service.py::PresenceService.month_summary(*, tenant_id, period, employee_ids=None)` / `.is_month_closed(*, tenant_id, period)`; both constructed with the connection (`Service(connection)`). Payroll never reads `hr.*` tables.
- Spec rules: "Calculate: requires the presence month closed (`PRESENCE_NOT_CLOSED`); recomputes all payslips of the run; idempotent. Approve: requires `payroll.approve_runs`, a user different from the one who calculated (`SAME_USER_APPROVAL`), a confirmed rule set; locks the run and publishes `payroll.run.approved`. Mark paid: after payouts are generated and confirmed, publishes `payroll.run.paid`. Reverse: only an approved/paid run … via `payroll.run.reversed`." Net never negative (`NET_NEGATIVE` → carried and reported).
- Events (thin payloads, in `backend/events/CATALOG.md`): `payroll.run.approved {run_id, period, run_type}`, `payroll.run.paid {run_id, period}`, `payroll.run.reversed {run_id, period}`; `correlation_id` = the run id.
- Contract services: `PayrollPostingService.posting_lines / payment_lines` and `PayrollReportService.cost_by_department / payslips_for_employee`, shapes exactly as the contract.
- Routes exactly as the contract: `/payroll/runs`, `/payroll/runs/:id`, `/payroll/payslips/:id`, `/payroll/payslips/:id/print`, `/payroll/inputs`, `/payroll/rules` (extra print routes are private to this phase).
- Every mutation calls `record_audit()`; every refusal is `Err(code, message, message_fr)`; the bilingual guard `core/test_error_translations.py` stays green.
- Frontend: every string through `useI18n()` with **both** `en` and `fr` keys in `frontend/src/lib/i18n.tsx`; every list uses `FilterTabs` (closed-value columns) + `ColumnFilterRow` + `useTableColumns` (via `PayrollTable`); server state only via TanStack Query; page tab bars in `StickyTabBar`; one branded loader per screen. Verify with `npx tsc -b --force` from `frontend/`.
- No Mali value anywhere except `backend/scripts/payroll_mali_rules.py`, where each value is marked "to confirm by accountant"; the seeded rule set is `draft`.
- Tests: from `backend/`, `.venv/Scripts/python -m pytest <path> -q`; integration tests use the `db` fixture and must not skip.
- Shared working tree: never `git stash`; `git add` only the files the task lists.

## Review Focus

1. **The rule set changes after a run was calculated** (confirmed later, edited and re-confirmed, or a newer set now applies) — expected: approval refused with `RULESET_NOT_CONFIRMED` until the run is recalculated. Test: Task 8 `test_a_rule_set_confirmed_after_calculation_needs_a_recalculation`.
2. **HR reopens the presence month after the run was calculated** — expected: approval refused with `PRESENCE_NOT_CLOSED`. Test: Task 8 `test_approval_is_refused_when_presence_was_reopened`.
3. **Reversing a run whose carried deduction a later run already took** — expected: refused (`RUN_LOCKED`) when the later run is approved or paid (no double recovery); a later *calculated* run goes back to draft. Test: Task 8 `test_a_run_whose_carry_a_later_approved_run_took_cannot_be_reversed`.
4. **Payment details corrected after payouts were generated, or shares that do not add up to 100 %** — expected: generated (unconfirmed) batches are dropped and regenerated from the corrected payslip; after a confirmation the change is refused (`PAYOUT_CONFIRMED`); bad shares are refused naming the employee (`PAYOUT_SPLIT_INVALID`). Tests: Task 9 `test_a_bad_split_names_the_employee`, Task 10 `test_payment_details_can_be_corrected_until_a_batch_is_confirmed`.
5. **An employee terminated mid-month and settled in an off-cycle run** — expected: the regular run of that month leaves them out (no double salary) as long as the off-cycle run is not reversed. Test: Task 7 `test_the_regular_run_leaves_out_an_employee_settled_off_cycle`.

---

## File Structure (this plan)

```
backend/modules/payroll/
  migrations/0002_payroll_runs.sql      runs, run_inputs, final_settlements, payslips, payslip_lines, carry_forwards
  migrations/0003_payroll_advances_loans.sql
  migrations/0004_payroll_payouts.sql   bank_file_templates, payout_batches, payout_lines
  domain/loans.py, snapshot_mapping.py, payouts.py, variance.py, declarations.py (+ test_*.py)
  api/run_state.py          lock_run, locked, not_found, invalidate (shared by services)
  api/run_service.py        create/list/get/update/delete, calculate, final settlements, approve, reverse, mark_paid
  api/input_service.py      run inputs, advances, loans, due deductions
  api/company.py            company header (core.companies + payroll.settings)
  api/payslip_service.py    payslip reads, print data, certificate, admin edit, variance
  api/payout_service.py     bank templates, payout batches, files, cash sheet
  api/declaration_service.py
  api/posting_service.py    PayrollPostingService (contract)
  api/report_service.py     PayrollReportService (contract)
  api/routes_runs.py, routes_inputs.py, routes_payouts.py, routes_declarations.py
  api/testing_support.py    (modify) fakes for hr, run/payslip inserts, approved_run()
  api/test_*_integration.py
backend/events/CATALOG.md                       (modify)
backend/modules/hr/api/router.py               (modify, Task 21) legacy payroll routes removed
backend/scripts/payroll_mali_rules.py          Mali DRAFT values, each "to confirm by accountant"
backend/scripts/seed_hr_payroll.py             (modify, Task 22)
frontend/src/features/payroll/
  api.ts, format.ts, PayrollStatusBadge.tsx, DraftRuleSetBanner.tsx, PayrollTable.tsx
  RulesPage.tsx, rules/{ruleTables.ts, SettingsCard.tsx, RuleSetDialog.tsx, CopyRuleSetDialog.tsx, RuleRowsTable.tsx, RuleRowDialog.tsx}
  InputsPage.tsx, inputs/{RunInputsTab.tsx, AdvancesTab.tsx, LoansTab.tsx, EmployeeSelect.tsx}
  RunsPage.tsx, RunDialog.tsx, DeclarationTable.tsx, AnnualRecapTab.tsx
  RunPage.tsx, run/{PayslipsPanel.tsx, VariancePanel.tsx, SettlementsPanel.tsx, ReverseDialog.tsx, PayoutsPanel.tsx, BankTemplatesDialog.tsx, DeclarationsPanel.tsx}
  PayslipPage.tsx, PayslipEditDialog.tsx
  print/{PrintShell.tsx, PayslipDocument.tsx, WorkCertificate.tsx, PayslipPrintPage.tsx, RunPrintPage.tsx, CashSheetPrintPage.tsx, DeclarationPrintPage.tsx}
frontend/src/routes/router.tsx, frontend/src/routes/Sidebar.tsx, frontend/src/lib/i18n.tsx   (modify)
```

---

### Task 1: Loan schedule and hr snapshot mapping (pure)

**Files:**
- Create: `backend/modules/payroll/domain/loans.py`, `backend/modules/payroll/domain/snapshot_mapping.py`
- Test: `backend/modules/payroll/domain/test_loans.py`, `backend/modules/payroll/domain/test_snapshot_mapping.py`

**Interfaces:**
- Consumes: `EmployeeInput`, `ContractComponent`, `PresenceInput` (3a Task 2).
- Produces:
  - `loans.Instalment(seq: int, period: date, amount: Decimal)`; `loans.add_months(period, months) -> date`; `loans.instalment_schedule(principal: Decimal, count: int, first_period: date) -> list[Instalment]` (raises `ValueError` when `count < 1` or `principal < count`).
  - `snapshot_mapping.PRESENCE_FIELDS`; `snapshot_mapping.employee_input(snapshot: dict) -> EmployeeInput`; `snapshot_mapping.presence_input(summary: dict | None) -> PresenceInput`. These are the only code that knows the contract's dict keys.

- [ ] **Step 1: Write the failing tests**

Create `backend/modules/payroll/domain/test_loans.py`:

```python
from datetime import date
from decimal import Decimal

import pytest

from modules.payroll.domain.loans import Instalment, add_months, instalment_schedule

D = Decimal


def test_the_last_instalment_takes_the_rounding_remainder():
    assert instalment_schedule(D(100000), 3, date(2026, 9, 1)) == [
        Instalment(1, date(2026, 9, 1), D(33333)),
        Instalment(2, date(2026, 10, 1), D(33333)),
        Instalment(3, date(2026, 11, 1), D(33334)),
    ]


def test_an_even_split_across_a_year_change():
    schedule = instalment_schedule(D(90000), 3, date(2026, 11, 1))
    assert [(item.period, item.amount) for item in schedule] == [
        (date(2026, 11, 1), D(30000)), (date(2026, 12, 1), D(30000)), (date(2027, 1, 1), D(30000)),
    ]


def test_add_months_goes_both_ways():
    assert add_months(date(2026, 1, 1), -1) == date(2025, 12, 1)
    assert add_months(date(2026, 12, 1), 13) == date(2028, 1, 1)


def test_a_loan_needs_at_least_one_franc_per_instalment():
    with pytest.raises(ValueError):
        instalment_schedule(D(2), 3, date(2026, 9, 1))
    with pytest.raises(ValueError):
        instalment_schedule(D(100), 0, date(2026, 9, 1))
```

Create `backend/modules/payroll/domain/test_snapshot_mapping.py`:

```python
from datetime import date
from decimal import Decimal

from modules.payroll.domain.inputs import ContractComponent, EmployeeInput, PresenceInput
from modules.payroll.domain.snapshot_mapping import employee_input, presence_input

D = Decimal


def _snapshot(**changes):
    snapshot = {
        "employee_id": "E1", "employee_no": "M-001", "full_name": "Awa Traoré", "department_id": "D1",
        "position_id": None, "grade_id": None, "hire_date": date(2020, 3, 1), "termination_date": None,
        "termination_reason": None, "tax_dependants": 2,
        "contract": {
            "id": "C1", "contract_type": "cdi", "base_salary": D("250000"), "weekly_hours": D(40),
            "pay_frequency": "monthly", "start_date": date(2021, 1, 1), "end_date": None,
            "components": [
                {"component_code": "TRANSPORT", "amount": D("15000"), "rate": None},
                {"component_code": "RESPONSIBILITY", "amount": None, "rate": D("2.5")},
            ],
        },
        "payment_methods": [],
    }
    snapshot.update(changes)
    return snapshot


def test_the_contract_snapshot_becomes_the_engine_employee():
    assert employee_input(_snapshot()) == EmployeeInput(
        employee_id="E1", base_salary=D(250000), pay_frequency="monthly", hire_date=date(2020, 3, 1),
        contract_start=date(2021, 1, 1), contract_end=None, termination_date=None, tax_dependants=2,
        components=(ContractComponent("TRANSPORT", amount=D(15000), rate=None),
                    ContractComponent("RESPONSIBILITY", amount=None, rate=D("2.5"))),
    )


def test_a_termination_date_is_carried():
    assert employee_input(_snapshot(termination_date=date(2026, 9, 15))).termination_date == date(2026, 9, 15)


def test_a_missing_presence_summary_counts_as_nothing_recorded():
    assert presence_input(None) == PresenceInput()


def test_presence_keeps_the_engine_fields_and_ignores_the_rest():
    summary = {"employee_id": "E1", "scheduled_days": 22, "worked_days": 20, "unpaid_absence_days": 1,
               "paid_leave_days": 1, "sick_days": 0, "holiday_days": 0, "holidays_worked_days": 0,
               "ot_minutes_day": 90, "ot_minutes_night": 0, "ot_minutes_rest_holiday": 0,
               "night_minutes": 480, "late_minutes": 12}
    assert presence_input(summary) == PresenceInput(scheduled_days=22, worked_days=20, unpaid_absence_days=1,
                                                    paid_leave_days=1, ot_minutes_day=90)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python -m pytest modules/payroll/domain/test_loans.py modules/payroll/domain/test_snapshot_mapping.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'modules.payroll.domain.loans'`.

- [ ] **Step 3: Write `loans.py`**

```python
"""Loan instalments: the principal split in whole francs, the remainder on the last instalment."""
from __future__ import annotations

import datetime
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Instalment:
    seq: int
    period: datetime.date
    amount: Decimal


def add_months(period: datetime.date, months: int) -> datetime.date:
    index = period.year * 12 + (period.month - 1) + months
    return datetime.date(index // 12, index % 12 + 1, 1)


def instalment_schedule(principal: Decimal, count: int, first_period: datetime.date) -> list[Instalment]:
    if count < 1 or principal < count:
        raise ValueError("a loan needs at least one instalment of at least one franc")
    each = principal // count
    last = principal - each * (count - 1)
    return [
        Instalment(seq=number + 1, period=add_months(first_period, number), amount=last if number == count - 1 else each)
        for number in range(count)
    ]
```

- [ ] **Step 4: Write `snapshot_mapping.py`**

```python
"""hr's contract-shaped dicts -> engine inputs. The only place that knows the contract's key names
(docs/superpowers/plans/2026-09-25-hr-payroll-finance-interfaces.md, "Phase 1 → Phase 3")."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from modules.payroll.domain.inputs import ContractComponent, EmployeeInput, PresenceInput

PRESENCE_FIELDS = (
    "scheduled_days", "worked_days", "unpaid_absence_days", "paid_leave_days", "sick_days", "holiday_days",
    "holidays_worked_days", "ot_minutes_day", "ot_minutes_night", "ot_minutes_rest_holiday",
)


def _decimal(value: Any) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def employee_input(snapshot: dict[str, Any]) -> EmployeeInput:
    contract = snapshot["contract"]
    return EmployeeInput(
        employee_id=snapshot["employee_id"],
        base_salary=Decimal(str(contract["base_salary"])),
        pay_frequency=contract["pay_frequency"],
        hire_date=snapshot["hire_date"],
        contract_start=contract["start_date"],
        contract_end=contract.get("end_date"),
        termination_date=snapshot.get("termination_date"),
        tax_dependants=int(snapshot.get("tax_dependants") or 0),
        components=tuple(
            ContractComponent(component_code=item["component_code"], amount=_decimal(item.get("amount")), rate=_decimal(item.get("rate")))
            for item in contract.get("components") or []
        ),
    )


def presence_input(summary: dict[str, Any] | None) -> PresenceInput:
    if summary is None:
        return PresenceInput()
    return PresenceInput(**{field: int(summary.get(field) or 0) for field in PRESENCE_FIELDS})
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest modules/payroll/domain/test_loans.py modules/payroll/domain/test_snapshot_mapping.py -q`
Expected: `8 passed`.

- [ ] **Step 6: Commit**

```bash
git add backend/modules/payroll/domain/loans.py backend/modules/payroll/domain/snapshot_mapping.py backend/modules/payroll/domain/test_loans.py backend/modules/payroll/domain/test_snapshot_mapping.py
git commit -m "feat(payroll): loan schedule and hr snapshot mapping

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Payout arithmetic and files (pure)

**Files:**
- Create: `backend/modules/payroll/domain/payouts.py`
- Test: `backend/modules/payroll/domain/test_payouts.py`

**Interfaces:**
- Produces: `XOF_DENOMINATIONS`, `METHODS`, `BANK_TEMPLATE_FIELDS`, `DELIMITERS`; `PayoutShare(method, group_key, amount, details)`; `validate_methods(methods: list[dict]) -> Result[list[dict]]` (`PAYOUT_SPLIT_INVALID`); `group_key(method: dict) -> str` (bank name / operator upper-cased, `"CASH"`); `split_net(net: Decimal, methods) -> Result[list[PayoutShare]]`; `billetage(amount: Decimal, denominations=XOF_DENOMINATIONS) -> tuple[dict[int, int], Decimal]`; `render_bank_csv(template: dict, lines: list[dict], period: date) -> str`; `render_mobile_csv(lines: list[dict]) -> str`; `validate_bank_template(values: dict) -> Result[dict]` (`TEMPLATE_INVALID`, bank name upper-cased so it matches `group_key`).
- A payout line dict is `{"employee_no", "full_name", "amount": Decimal, "details": {"bank_name", "account_no", "mobile_operator", "mobile_number"}}`.

Spec: "Bank: CSV with configurable column template per bank. Mobile money: CSV (operator, number, name, amount) per operator. Cash: printable sheet with signature column and a note/coin breakdown (billetage) total." Net splits by `share_percent` (contract `payment_methods`); whole francs, the primary method takes the rounding remainder.

- [ ] **Step 1: Write the failing tests**

Create `backend/modules/payroll/domain/test_payouts.py`:

```python
from datetime import date
from decimal import Decimal

from core.domain.result import Err, Ok
from modules.payroll.domain.payouts import billetage, render_bank_csv, render_mobile_csv, split_net, validate_bank_template

D = Decimal
BANK = {"method": "bank", "bank_name": "BDM", "account_no": "ML-0123", "mobile_operator": None,
        "mobile_number": None, "share_percent": 100, "is_primary": True}
MOBILE = {"method": "mobile_money", "bank_name": None, "account_no": None, "mobile_operator": "Orange Money",
          "mobile_number": "+22370000000", "share_percent": 40, "is_primary": False}
LINE = {"employee_no": "M-001", "full_name": "Awa Traoré", "amount": D(376035),
        "details": {"bank_name": "BDM", "account_no": "ML-0123", "mobile_operator": "Orange Money", "mobile_number": "+22370000000"}}


def test_one_method_takes_the_whole_net():
    result = split_net(D(376035), [BANK])
    assert isinstance(result, Ok)
    assert [(share.method, share.group_key, share.amount) for share in result.value] == [("bank", "BDM", D(376035))]


def test_other_methods_round_down_and_the_primary_takes_the_rest():
    result = split_net(D(100001), [{**BANK, "bank_name": "Ecobank", "share_percent": 60}, MOBILE])
    assert [(share.method, share.group_key, share.amount) for share in result.value] == [
        ("mobile_money", "ORANGE MONEY", D(40000)), ("bank", "ECOBANK", D(60001)),
    ]


def test_shares_must_add_up_to_one_hundred():
    result = split_net(D(1000), [{**BANK, "share_percent": 50}])
    assert isinstance(result, Err) and result.code == "PAYOUT_SPLIT_INVALID" and "100" in result.message_fr


def test_a_bank_payment_needs_an_account_and_a_payslip_needs_a_method():
    assert isinstance(split_net(D(1000), [{**BANK, "account_no": None}]), Err)
    assert isinstance(split_net(D(1000), []), Err)


def test_nothing_to_pay_gives_no_share():
    assert split_net(D(0), [BANK]).value == []


def test_billetage_counts_notes_and_coins():
    counts, remainder = billetage(D(37340))
    assert {value: count for value, count in counts.items() if count} == {10000: 3, 5000: 1, 2000: 1, 250: 1, 50: 1, 25: 1, 10: 1, 5: 1}
    assert remainder == 0 and sum(value * count for value, count in counts.items()) == 37340


def test_the_bank_file_follows_its_template():
    template = {"bank_name": "BDM", "delimiter": ";", "include_header": True, "columns": [
        {"header": "Compte", "field": "account_no"}, {"header": "Montant", "field": "amount"}, {"header": "Libellé", "field": "reference"},
    ]}
    assert render_bank_csv(template, [LINE], date(2026, 9, 1)) == "Compte;Montant;Libellé\r\nML-0123;376035;PAIE 2026-09 M-001\r\n"


def test_the_mobile_money_file_has_operator_number_name_amount():
    assert render_mobile_csv([{**LINE, "amount": D(50000)}]) == "operator;number;name;amount\r\nOrange Money;+22370000000;Awa Traoré;50000\r\n"


def test_a_template_names_known_fields_only():
    ok = validate_bank_template({"bank_name": " bdm ", "columns": [{"header": "Compte", "field": "account_no"}]})
    assert isinstance(ok, Ok)
    assert ok.value == {"bank_name": "BDM", "delimiter": ";", "include_header": True, "columns": [{"header": "Compte", "field": "account_no"}]}
    assert isinstance(validate_bank_template({"bank_name": "BDM", "columns": [{"header": "x", "field": "salary"}]}), Err)
    assert isinstance(validate_bank_template({"bank_name": "BDM", "columns": []}), Err)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python -m pytest modules/payroll/domain/test_payouts.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'modules.payroll.domain.payouts'`.

- [ ] **Step 3: Write `payouts.py`**

```python
"""Paying the net: split by payment method, cash note-and-coin count, bank and mobile-money files."""
from __future__ import annotations

import csv
import datetime
import io
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from typing import Any

from core.domain.result import Err, Ok, Result

# Notes and coins the BCEAO issues for the franc CFA (XOF) — a fact of the currency, not a payroll
# rule. 500 exists as a note and as a coin and is counted once.
XOF_DENOMINATIONS = (10000, 5000, 2000, 1000, 500, 250, 200, 100, 50, 25, 10, 5, 1)
METHODS = ("bank", "mobile_money", "cash")
BANK_TEMPLATE_FIELDS = ("employee_no", "full_name", "bank_name", "account_no", "amount", "period", "reference")
DELIMITERS = (";", ",", "\t", "|")
MOBILE_HEADER = ("operator", "number", "name", "amount")
_DETAIL_KEYS = ("bank_name", "account_no", "mobile_operator", "mobile_number")


@dataclass(frozen=True)
class PayoutShare:
    method: str
    group_key: str
    amount: Decimal
    details: dict[str, Any]


def _split_error(english: str, french: str) -> Err:
    return Err("PAYOUT_SPLIT_INVALID", english, french)


def validate_methods(methods: list[dict[str, Any]]) -> Result[list[dict[str, Any]]]:
    if not methods:
        return _split_error("no payment method", "aucun moyen de paiement")
    clean: list[dict[str, Any]] = []
    total = Decimal(0)
    for raw in methods:
        method = raw.get("method")
        if method not in METHODS:
            return _split_error(f"unknown payment method {method}", f"moyen de paiement inconnu {method}")
        share = Decimal(str(raw.get("share_percent") or 0))
        if share <= 0:
            return _split_error("each share is above 0 %", "chaque part est supérieure à 0 %")
        if method == "bank" and not (raw.get("bank_name") and raw.get("account_no")):
            return _split_error("a bank payment needs the bank and the account number",
                                "un virement demande la banque et le numéro de compte")
        if method == "mobile_money" and not (raw.get("mobile_operator") and raw.get("mobile_number")):
            return _split_error("a mobile-money payment needs the operator and the number",
                                "un paiement mobile demande l'opérateur et le numéro")
        total += share
        clean.append({"method": method, **{key: raw.get(key) for key in _DETAIL_KEYS},
                      "share_percent": share, "is_primary": bool(raw.get("is_primary"))})
    if total != 100:
        return _split_error(f"shares add up to {total} %, not 100 %", f"les parts totalisent {total} %, pas 100 %")
    return Ok(clean)


def group_key(method: dict[str, Any]) -> str:
    if method["method"] == "bank":
        return str(method["bank_name"]).strip().upper()
    if method["method"] == "mobile_money":
        return str(method["mobile_operator"]).strip().upper()
    return "CASH"


def split_net(net: Decimal, methods: list[dict[str, Any]]) -> Result[list[PayoutShare]]:
    checked = validate_methods(methods)
    if isinstance(checked, Err):
        return checked
    ordered = sorted(checked.value, key=lambda method: method["is_primary"])  # the primary (else the last) goes last
    shares: list[PayoutShare] = []
    paid = Decimal(0)
    for index, method in enumerate(ordered):
        if index == len(ordered) - 1:
            amount = net - paid
        else:
            amount = (net * method["share_percent"] / 100).to_integral_value(rounding=ROUND_DOWN)
            paid += amount
        if amount > 0:
            shares.append(PayoutShare(method=method["method"], group_key=group_key(method), amount=amount,
                                      details={key: method[key] for key in _DETAIL_KEYS}))
    return Ok(shares)


def billetage(amount: Decimal, denominations: tuple[int, ...] = XOF_DENOMINATIONS) -> tuple[dict[int, int], Decimal]:
    left = amount
    counts: dict[int, int] = {}
    for value in denominations:
        count = int(left // value)
        counts[value] = count
        left -= count * value
    return counts, left


def _writer(delimiter: str) -> tuple[io.StringIO, Any]:
    buffer = io.StringIO()
    return buffer, csv.writer(buffer, delimiter=delimiter, lineterminator="\r\n")


def render_bank_csv(template: dict[str, Any], lines: list[dict[str, Any]], period: datetime.date) -> str:
    buffer, writer = _writer(template["delimiter"])
    if template["include_header"]:
        writer.writerow([column["header"] for column in template["columns"]])
    for line in lines:
        details = line.get("details") or {}
        values = {
            "employee_no": line["employee_no"], "full_name": line["full_name"],
            "bank_name": details.get("bank_name") or "", "account_no": details.get("account_no") or "",
            "amount": str(int(line["amount"])), "period": f"{period:%Y-%m}",
            "reference": f"PAIE {period:%Y-%m} {line['employee_no']}",
        }
        writer.writerow([values[column["field"]] for column in template["columns"]])
    return buffer.getvalue()


def render_mobile_csv(lines: list[dict[str, Any]]) -> str:
    buffer, writer = _writer(";")
    writer.writerow(MOBILE_HEADER)
    for line in lines:
        details = line.get("details") or {}
        writer.writerow([details.get("mobile_operator") or "", details.get("mobile_number") or "",
                         line["full_name"], str(int(line["amount"]))])
    return buffer.getvalue()


def _template_error(english: str, french: str) -> Err:
    return Err("TEMPLATE_INVALID", english, french)


def validate_bank_template(values: dict[str, Any]) -> Result[dict[str, Any]]:
    bank_name = str(values.get("bank_name") or "").strip().upper()
    if not bank_name:
        return _template_error("the bank name is required", "le nom de la banque est obligatoire")
    delimiter = values.get("delimiter") or ";"
    if delimiter not in DELIMITERS:
        return _template_error("the delimiter is ; , tab or |", "le séparateur est ; , tabulation ou |")
    include_header = values.get("include_header", True)
    if not isinstance(include_header, bool):
        return _template_error("include_header is true or false", "include_header vaut vrai ou faux")
    columns = values.get("columns")
    if not isinstance(columns, list) or not columns:
        return _template_error("a template needs at least one column", "un modèle demande au moins une colonne")
    clean: list[dict[str, str]] = []
    allowed = ", ".join(BANK_TEMPLATE_FIELDS)
    for column in columns:
        column = column if isinstance(column, dict) else {}
        header = str(column.get("header") or "").strip()
        field = column.get("field")
        if not header or field not in BANK_TEMPLATE_FIELDS:
            return _template_error(f"each column has a header and one of: {allowed}", f"chaque colonne a un en-tête et l'un de : {allowed}")
        clean.append({"header": header, "field": field})
    return Ok({"bank_name": bank_name, "delimiter": delimiter, "include_header": include_header, "columns": clean})
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest modules/payroll/domain/test_payouts.py -q`
Expected: `9 passed`.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/payroll/domain/payouts.py backend/modules/payroll/domain/test_payouts.py
git commit -m "feat(payroll): payout split, billetage and bank / mobile-money files

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Month-on-month variance and declarations (pure)

**Files:**
- Create: `backend/modules/payroll/domain/variance.py`, `backend/modules/payroll/domain/declarations.py`
- Test: `backend/modules/payroll/domain/test_variance.py`, `backend/modules/payroll/domain/test_declarations.py`

**Interfaces:**
- Produces:
  - `variance.VarianceRow(employee_id, employee_no, full_name, previous_gross, current_gross, previous_net, current_net)` with properties `change` (`"new"|"left"|"changed"|"same"`), `delta_gross`, `delta_net`; `variance.compare(current: Sequence[dict], previous: Sequence[dict]) -> list[VarianceRow]` (dicts: `employee_id, employee_no, full_name, gross, net`), sorted by |Δ net| descending then name. No threshold: the reader judges (memory rule "no invented thresholds").
  - `declarations.EMPLOYER_TAXES`; `Declaration(code, columns: tuple[str, ...], rows: tuple[dict, ...], totals: dict[str, Decimal])`; `available_codes(payslips) -> list[str]`; `build_declaration(code, payslips) -> Declaration | None`; `annual_recap(payslips) -> Declaration` (code `"ANNUAL"`); `to_csv(declaration) -> str` (`;`, header row, one row per employee, a `TOTAL` row).
  - A declaration payslip dict: `employee_id, employee_no, full_name, identifiers: {"inps_no", "amo_no"}, period, gross, employee_contrib, employer_contrib, its, net, lines: [{section, code, base, amount, declaration_code}]`.

Spec: "Monthly reports from payslips: INPS (per employee contributable base and contributions), AMO, ITS withheld, employer taxes. Exported as CSV + printable page. Annual per-employee recap (gross, contributions, ITS)". Codes are data: contribution `declaration_code` (INPS, AMO…), tax codes (ITS), and `EMPLOYER_TAXES` for every employer charge. Payslips of one employee in the month (regular + off-cycle) add up into one row.

- [ ] **Step 1: Write the failing tests**

Create `backend/modules/payroll/domain/test_variance.py`:

```python
from decimal import Decimal

from modules.payroll.domain.variance import compare

D = Decimal


def row(employee_id, gross, net):
    return {"employee_id": employee_id, "employee_no": employee_id, "full_name": f"Name {employee_id}", "gross": D(gross), "net": D(net)}


CURRENT = [row("A", 100, 80), row("B", 200, 150), row("C", 50, 40)]
PREVIOUS = [row("B", 200, 150), row("C", 60, 45), row("D", 70, 60)]


def test_each_employee_is_new_left_changed_or_same():
    rows = {item.employee_id: item for item in compare(CURRENT, PREVIOUS)}
    assert {key: item.change for key, item in rows.items()} == {"A": "new", "B": "same", "C": "changed", "D": "left"}
    assert (rows["C"].delta_gross, rows["C"].delta_net) == (D(-10), D(-5))
    assert rows["D"].delta_net == D(-60) and rows["A"].previous_net is None


def test_rows_come_by_the_size_of_the_net_change():
    assert [item.employee_id for item in compare(CURRENT, PREVIOUS)] == ["A", "D", "C", "B"]
```

Create `backend/modules/payroll/domain/test_declarations.py`:

```python
from datetime import date
from decimal import Decimal

from modules.payroll.domain.declarations import annual_recap, available_codes, build_declaration, to_csv

D = Decimal


def line(section, code, amount, base=None, declaration=None):
    return {"section": section, "code": code, "amount": D(amount), "base": None if base is None else D(base), "declaration_code": declaration}


def payslip(employee_id, *, lines, gross=0, period=date(2026, 9, 1), identifiers=None, net=0, its=0, employee_contrib=0, employer_contrib=0):
    return {"employee_id": employee_id, "employee_no": f"M-{employee_id}", "full_name": f"Name {employee_id}",
            "identifiers": identifiers or {}, "period": period, "gross": D(gross), "net": D(net), "its": D(its),
            "employee_contrib": D(employee_contrib), "employer_contrib": D(employer_contrib), "lines": lines}


A = payslip("1", gross=300000, identifiers={"inps_no": "INPS-1"}, lines=[
    line("employee_contribution", "PENSION", 10800, 300000, "INPS"),
    line("employer_contribution", "PENSION", 16200, 300000, "INPS"),
    line("employer_contribution", "FAMILY", 24000, 300000, "INPS"),
    line("employee_contribution", "AMO", 9180, 300000, "AMO"),
    line("tax", "ITS", 12000, 250000),
    line("employer_charge", "TL", 3000, 300000, "TL"),
])
B_REGULAR = payslip("2", gross=200000, lines=[
    line("employee_contribution", "PENSION", 7200, 200000, "INPS"),
    line("employer_contribution", "PENSION", 10800, 200000, "INPS"),
    line("tax", "ITS", 5000, 150000),
])
B_OFF_CYCLE = payslip("2", gross=50000, lines=[
    line("employee_contribution", "PENSION", 1800, 50000, "INPS"),
    line("employer_contribution", "PENSION", 2700, 50000, "INPS"),
])


def test_codes_come_from_the_lines():
    assert available_codes([A, B_REGULAR]) == ["AMO", "EMPLOYER_TAXES", "INPS", "ITS"]


def test_a_contribution_declaration_adds_up_each_employee_across_payslips():
    declaration = build_declaration("INPS", [A, B_REGULAR, B_OFF_CYCLE])
    assert declaration.columns == ("employee_no", "full_name", "identifier", "base", "FAMILY_employee", "PENSION_employee",
                                   "FAMILY_employer", "PENSION_employer", "total")
    first, second = declaration.rows
    assert (first["identifier"], first["base"], first["PENSION_employee"], first["FAMILY_employer"], first["total"]) == (
        "INPS-1", D(300000), D(10800), D(24000), D(51000))
    assert (second["base"], second["PENSION_employee"], second["total"]) == (D(250000), D(9000), D(22500))
    assert declaration.totals["total"] == D(73500)


def test_the_tax_declaration_lists_taxable_and_tax():
    declaration = build_declaration("ITS", [A, B_REGULAR])
    assert [(row["employee_no"], row["taxable"], row["amount"]) for row in declaration.rows] == [
        ("M-1", D(250000), D(12000)), ("M-2", D(150000), D(5000))]


def test_employer_taxes_group_every_employer_charge():
    declaration = build_declaration("EMPLOYER_TAXES", [A, B_REGULAR])
    assert declaration.columns == ("employee_no", "full_name", "gross", "TL", "total")
    assert [(row["employee_no"], row["TL"]) for row in declaration.rows] == [("M-1", D(3000))]


def test_an_unknown_code_gives_nothing():
    assert build_declaration("CNSS", [A]) is None


def test_the_csv_ends_with_a_total_row():
    assert to_csv(build_declaration("ITS", [A, B_REGULAR])).splitlines() == [
        "employee_no;full_name;taxable;amount", "M-1;Name 1;250000;12000", "M-2;Name 2;150000;5000", "TOTAL;;400000;17000"]


def test_the_annual_recap_counts_months_and_adds_amounts():
    january = payslip("1", gross=300000, period=date(2026, 1, 1), lines=[], net=250000, its=12000)
    february = payslip("1", gross=310000, period=date(2026, 2, 1), lines=[], net=255000, its=13000)
    recap = annual_recap([january, february])
    assert (recap.rows[0]["months"], recap.rows[0]["gross"], recap.rows[0]["its"], recap.rows[0]["net"]) == (
        2, D(610000), D(25000), D(505000))
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python -m pytest modules/payroll/domain/test_variance.py modules/payroll/domain/test_declarations.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'modules.payroll.domain.variance'`.

- [ ] **Step 3: Write `variance.py`**

```python
"""A run compared with the previous month's approved run, employee by employee.

No threshold decides what is "abnormal": rows are sorted by the size of the net change and the
payroll officer judges (every figure comes from a recorded payslip).
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

ZERO = Decimal(0)


@dataclass(frozen=True)
class VarianceRow:
    employee_id: str
    employee_no: str
    full_name: str
    previous_gross: Decimal | None
    current_gross: Decimal | None
    previous_net: Decimal | None
    current_net: Decimal | None

    @property
    def change(self) -> str:
        if self.previous_net is None:
            return "new"
        if self.current_net is None:
            return "left"
        unchanged = self.previous_gross == self.current_gross and self.previous_net == self.current_net
        return "same" if unchanged else "changed"

    @property
    def delta_gross(self) -> Decimal:
        return (self.current_gross or ZERO) - (self.previous_gross or ZERO)

    @property
    def delta_net(self) -> Decimal:
        return (self.current_net or ZERO) - (self.previous_net or ZERO)


def compare(current: Sequence[dict[str, Any]], previous: Sequence[dict[str, Any]]) -> list[VarianceRow]:
    now = {row["employee_id"]: row for row in current}
    before = {row["employee_id"]: row for row in previous}
    rows: list[VarianceRow] = []
    for employee_id in now.keys() | before.keys():
        this_month, last_month = now.get(employee_id), before.get(employee_id)
        label = this_month or last_month
        rows.append(VarianceRow(
            employee_id=employee_id, employee_no=label["employee_no"], full_name=label["full_name"],
            previous_gross=None if last_month is None else last_month["gross"],
            current_gross=None if this_month is None else this_month["gross"],
            previous_net=None if last_month is None else last_month["net"],
            current_net=None if this_month is None else this_month["net"],
        ))
    return sorted(rows, key=lambda row: (-abs(row.delta_net), row.full_name))
```

- [ ] **Step 4: Write `declarations.py`**

```python
"""Monthly declarations from payslip lines, and the annual recap.

A declaration code comes from the rule set: a contribution's declaration_code (e.g. INPS, AMO), a
tax code (e.g. ITS), or EMPLOYER_TAXES for every employer charge. The payslips of one employee in
the month (regular + off-cycle) add up into one row.
"""
from __future__ import annotations

import csv
import io
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

EMPLOYER_TAXES = "EMPLOYER_TAXES"
_CONTRIBUTIONS = ("employee_contribution", "employer_contribution")
ZERO = Decimal(0)


@dataclass(frozen=True)
class Declaration:
    code: str
    columns: tuple[str, ...]
    rows: tuple[dict[str, Any], ...]
    totals: dict[str, Decimal]


def available_codes(payslips: Sequence[dict[str, Any]]) -> list[str]:
    codes: set[str] = set()
    for payslip in payslips:
        for line in payslip["lines"]:
            if line["section"] in _CONTRIBUTIONS and line["declaration_code"]:
                codes.add(line["declaration_code"])
            elif line["section"] == "tax":
                codes.add(line["code"])
            elif line["section"] == "employer_charge":
                codes.add(EMPLOYER_TAXES)
    return sorted(codes)


def _by_employee(payslips: Sequence[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for payslip in payslips:
        grouped.setdefault(payslip["employee_id"], []).append(payslip)
    return sorted(grouped.values(), key=lambda group: group[0]["employee_no"])


def _start(group: list[dict[str, Any]]) -> dict[str, Any]:
    return {"employee_no": group[0]["employee_no"], "full_name": group[0]["full_name"]}


def _totals(columns: tuple[str, ...], rows: list[dict[str, Any]], first_numeric: int) -> dict[str, Decimal]:
    return {column: sum((row[column] for row in rows), ZERO) for column in columns[first_numeric:]}


def _sum(lines: list[dict[str, Any]], **match: Any) -> Decimal:
    return sum((line["amount"] for line in lines if all(line[key] == value for key, value in match.items())), ZERO)


def _contribution(code: str, payslips: Sequence[dict[str, Any]]) -> Declaration:
    def matching(payslip: dict[str, Any]) -> list[dict[str, Any]]:
        return [line for line in payslip["lines"] if line["section"] in _CONTRIBUTIONS and line["declaration_code"] == code]

    codes = sorted({line["code"] for payslip in payslips for line in matching(payslip)})
    columns = ("employee_no", "full_name", "identifier", "base",
               *[f"{item}_employee" for item in codes], *[f"{item}_employer" for item in codes], "total")
    rows: list[dict[str, Any]] = []
    for group in _by_employee(payslips):
        chunks = [matching(payslip) for payslip in group]
        lines = [line for chunk in chunks for line in chunk]
        if not lines:
            continue
        identifiers = group[0].get("identifiers") or {}
        # the contributable salary before ceilings: the highest base of the group, per payslip
        row = {**_start(group), "identifier": identifiers.get(f"{code.lower()}_no") or "",
               "base": sum((max(line["base"] or ZERO for line in chunk) for chunk in chunks if chunk), ZERO)}
        for item in codes:
            row[f"{item}_employee"] = _sum(lines, code=item, section="employee_contribution")
            row[f"{item}_employer"] = _sum(lines, code=item, section="employer_contribution")
        row["total"] = sum((line["amount"] for line in lines), ZERO)
        rows.append(row)
    return Declaration(code=code, columns=columns, rows=tuple(rows), totals=_totals(columns, rows, 3))


def _tax(code: str, payslips: Sequence[dict[str, Any]]) -> Declaration:
    columns = ("employee_no", "full_name", "taxable", "amount")
    rows: list[dict[str, Any]] = []
    for group in _by_employee(payslips):
        lines = [line for payslip in group for line in payslip["lines"] if line["section"] == "tax" and line["code"] == code]
        if lines:
            rows.append({**_start(group), "taxable": sum((line["base"] or ZERO for line in lines), ZERO),
                         "amount": sum((line["amount"] for line in lines), ZERO)})
    return Declaration(code=code, columns=columns, rows=tuple(rows), totals=_totals(columns, rows, 2))


def _employer_taxes(payslips: Sequence[dict[str, Any]]) -> Declaration:
    codes = sorted({line["code"] for payslip in payslips for line in payslip["lines"] if line["section"] == "employer_charge"})
    columns = ("employee_no", "full_name", "gross", *codes, "total")
    rows: list[dict[str, Any]] = []
    for group in _by_employee(payslips):
        lines = [line for payslip in group for line in payslip["lines"] if line["section"] == "employer_charge"]
        if not lines:
            continue
        row = {**_start(group), "gross": sum((payslip["gross"] for payslip in group), ZERO)}
        for item in codes:
            row[item] = _sum(lines, code=item)
        row["total"] = sum((line["amount"] for line in lines), ZERO)
        rows.append(row)
    return Declaration(code=EMPLOYER_TAXES, columns=columns, rows=tuple(rows), totals=_totals(columns, rows, 2))


def build_declaration(code: str, payslips: Sequence[dict[str, Any]]) -> Declaration | None:
    if code not in available_codes(payslips):
        return None
    if code == EMPLOYER_TAXES:
        return _employer_taxes(payslips)
    is_tax = any(line["section"] == "tax" and line["code"] == code for payslip in payslips for line in payslip["lines"])
    return _tax(code, payslips) if is_tax else _contribution(code, payslips)


def annual_recap(payslips: Sequence[dict[str, Any]]) -> Declaration:
    columns = ("employee_no", "full_name", "months", "gross", "employee_contrib", "employer_contrib", "its", "net")
    rows: list[dict[str, Any]] = []
    for group in _by_employee(payslips):
        row = {**_start(group), "months": len({payslip["period"] for payslip in group})}
        for column in columns[3:]:
            row[column] = sum((payslip[column] for payslip in group), ZERO)
        rows.append(row)
    return Declaration(code="ANNUAL", columns=columns, rows=tuple(rows), totals=_totals(columns, rows, 3))


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return str(int(value)) if value == value.to_integral_value() else str(value)
    return str(value)


def to_csv(declaration: Declaration) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    writer.writerow(declaration.columns)
    for row in declaration.rows:
        writer.writerow([_cell(row[column]) for column in declaration.columns])
    writer.writerow(["TOTAL" if index == 0 else _cell(declaration.totals.get(column, "")) if column in declaration.totals else ""
                     for index, column in enumerate(declaration.columns)])
    return buffer.getvalue()
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest modules/payroll/domain/test_variance.py modules/payroll/domain/test_declarations.py -q`
Expected: `9 passed`.

- [ ] **Step 6: Commit**

```bash
git add backend/modules/payroll/domain/variance.py backend/modules/payroll/domain/declarations.py backend/modules/payroll/domain/test_variance.py backend/modules/payroll/domain/test_declarations.py
git commit -m "feat(payroll): month-on-month variance and declaration builders

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---
### Task 4: Runs table, `RunService` basics, reopening a rule set, test fakes for hr

**Files:**
- Create: `backend/modules/payroll/migrations/0002_payroll_runs.sql`
- Create: `backend/modules/payroll/api/run_state.py`
- Create: `backend/modules/payroll/api/run_service.py`
- Modify: `backend/modules/payroll/api/rule_set_service.py` (add `reopen_rule_set`)
- Modify: `backend/modules/payroll/api/routes_rules.py` (add the reopen route right after the confirm route, before the generic `{kind}` routes)
- Modify: `backend/modules/payroll/api/testing_support.py` (hr fakes, `insert_run`, `insert_payslip`)
- Test: `backend/modules/payroll/api/test_run_service_integration.py`

**Interfaces:**
- Consumes: `RuleSetService.in_force` (3a Task 10); `PayrollSnapshotService`, `PresenceService` (hr, contract).
- Produces:
  - Tables `payroll.runs`, `payroll.run_inputs`, `payroll.final_settlements`, `payroll.payslips`, `payroll.payslip_lines`, `payroll.carry_forwards` (columns below).
  - `run_state.EDITABLE = ("draft", "calculated")`, `run_state.lock_run(connection, tenant_id, run_id) -> dict | None` (FOR UPDATE), `run_state.not_found() -> Err`, `run_state.locked(status) -> Err` (`RUN_LOCKED`), `run_state.invalidate(connection, run_id) -> bool` (a calculated run goes back to draft and loses its payslips).
  - `RunService(connection, *, snapshots=None, presence=None)` with `list_runs(*, tenant_id, status=None) -> list[dict]`, `get_run(*, tenant_id, run_id) -> dict | None` (adds `presence_closed` for a regular run and `rule_set_in_force {id, name, status} | None`), `create_run(*, tenant_id, actor_id, period, run_type, label=None, employee_ids=None) -> Result[dict]`, `update_run(*, tenant_id, actor_id, run_id, changes: dict) -> Result[dict]` (keys `label`, `employee_ids`), `delete_run(*, tenant_id, actor_id, run_id) -> Result[dict]`.
  - `RuleSetService.reopen_rule_set(*, tenant_id, actor_id, rule_set_id) -> Result[dict]` (`RULESET_IN_USE` once an approved/paid run used it); route `POST /payroll/rule-sets/{id}/reopen` (`payroll.confirm_rules`).
  - `testing_support.FakeSnapshots(employees)`, `FakePresence(summaries=None, *, closed=True)`, `presence_summary(**counts) -> dict`, `snapshot(employee_id, *, employee_no, full_name, ...) -> dict`, `insert_run(connection, *, tenant_id, actor_id, period, status="draft", run_type="regular", rule_set_id=None) -> str`, `insert_payslip(connection, *, tenant_id, run_id, employee_id, rule_set_id, gross=0, net=0) -> str`.
- Error codes: `NOT_FOUND`, `RUN_INVALID`, `DUPLICATE_RUN`, `RUN_LOCKED`, `RULESET_IN_USE`.

Resolved ambiguity: the spec gives runs no edit action. Edit-in-place here is limited to the label and (off-cycle) the employee list, under `payroll.calculate_runs`, while the run is draft/calculated; a calculated run whose scope changes goes back to draft. An approved run never changes (reverse it instead).

- [ ] **Step 1: Write the migration**

Create `backend/modules/payroll/migrations/0002_payroll_runs.sql`:

```sql
-- Payroll runs and payslips. employee_id is hr's id kept as opaque text (no cross-module FK);
-- employee_no / full_name are copies taken at calculation time so a payslip reads on its own.
CREATE TABLE IF NOT EXISTS payroll.runs (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    period DATE NOT NULL CHECK (EXTRACT(DAY FROM period) = 1),
    run_type TEXT NOT NULL CHECK (run_type IN ('regular', 'off_cycle')),
    label TEXT,
    employee_ids TEXT[],
    rule_set_id TEXT REFERENCES payroll.rule_sets (id),
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'calculated', 'approved', 'paid', 'reversed')),
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    calculated_by TEXT,
    calculated_at TIMESTAMPTZ,
    approved_by TEXT,
    approved_at TIMESTAMPTZ,
    paid_by TEXT,
    paid_at TIMESTAMPTZ,
    reversed_by TEXT,
    reversed_at TIMESTAMPTZ,
    reversal_reason TEXT,
    CHECK (run_type = 'off_cycle' OR employee_ids IS NULL)
);
-- One regular run per month; a reversed one frees the month.
CREATE UNIQUE INDEX IF NOT EXISTS payroll_runs_one_regular_per_period
    ON payroll.runs (tenant_id, period) WHERE run_type = 'regular' AND status <> 'reversed';
CREATE INDEX IF NOT EXISTS payroll_runs_period_idx ON payroll.runs (tenant_id, period DESC);

CREATE TABLE IF NOT EXISTS payroll.run_inputs (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    run_id TEXT NOT NULL REFERENCES payroll.runs (id) ON DELETE CASCADE,
    employee_id TEXT NOT NULL,
    employee_no TEXT NOT NULL,
    full_name TEXT NOT NULL,
    component_code TEXT NOT NULL,
    qty NUMERIC(12, 2) CHECK (qty >= 0),
    amount NUMERIC(18, 0) CHECK (amount >= 0),
    note TEXT,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (qty IS NOT NULL OR amount IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS payroll_run_inputs_run_idx ON payroll.run_inputs (run_id, employee_id);

CREATE TABLE IF NOT EXISTS payroll.final_settlements (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    run_id TEXT NOT NULL REFERENCES payroll.runs (id) ON DELETE CASCADE,
    employee_id TEXT NOT NULL,
    employee_no TEXT NOT NULL,
    full_name TEXT NOT NULL,
    unused_leave_days NUMERIC(6, 2) NOT NULL DEFAULT 0 CHECK (unused_leave_days >= 0),
    notice_months NUMERIC(5, 2) NOT NULL DEFAULT 0 CHECK (notice_months >= 0),
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (run_id, employee_id)
);

CREATE TABLE IF NOT EXISTS payroll.payslips (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    run_id TEXT NOT NULL REFERENCES payroll.runs (id) ON DELETE CASCADE,
    employee_id TEXT NOT NULL,
    employee_no TEXT NOT NULL,
    full_name TEXT NOT NULL,
    department_id TEXT,
    rule_set_id TEXT NOT NULL REFERENCES payroll.rule_sets (id),
    rule_set_status TEXT NOT NULL CHECK (rule_set_status IN ('draft', 'confirmed')),
    snapshot JSONB NOT NULL,
    gross NUMERIC(18, 0) NOT NULL,
    contributable NUMERIC(18, 0) NOT NULL,
    taxable NUMERIC(18, 0) NOT NULL,
    employee_contrib NUMERIC(18, 0) NOT NULL,
    employer_contrib NUMERIC(18, 0) NOT NULL,
    employer_charges NUMERIC(18, 0) NOT NULL,
    its NUMERIC(18, 0) NOT NULL,
    deductions NUMERIC(18, 0) NOT NULL,
    net NUMERIC(18, 0) NOT NULL CHECK (net >= 0),
    employer_cost NUMERIC(18, 0) NOT NULL,
    warnings JSONB NOT NULL DEFAULT '[]'::jsonb,
    note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (run_id, employee_id)
);
CREATE INDEX IF NOT EXISTS payroll_payslips_employee_idx ON payroll.payslips (tenant_id, employee_id);

CREATE TABLE IF NOT EXISTS payroll.payslip_lines (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    payslip_id TEXT NOT NULL REFERENCES payroll.payslips (id) ON DELETE CASCADE,
    line_no INTEGER NOT NULL,
    section TEXT NOT NULL CHECK (section IN ('earning', 'employee_contribution', 'relief', 'tax', 'deduction',
                                             'employer_contribution', 'employer_charge')),
    code TEXT NOT NULL,
    name_en TEXT NOT NULL,
    name_fr TEXT NOT NULL,
    base NUMERIC(18, 0),
    qty NUMERIC(12, 2),
    rate NUMERIC(9, 4),
    amount NUMERIC(18, 0) NOT NULL,
    taxable BOOLEAN NOT NULL DEFAULT FALSE,
    contributable BOOLEAN NOT NULL DEFAULT FALSE,
    declaration_code TEXT,
    source_kind TEXT,
    source_id TEXT,
    UNIQUE (payslip_id, line_no)
);

-- A deduction the net could not cover, owed on a later payslip. Deleted with the payslip that
-- produced it (recalculation); released when the payslip that took it is deleted.
CREATE TABLE IF NOT EXISTS payroll.carry_forwards (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    employee_id TEXT NOT NULL,
    component_code TEXT NOT NULL,
    amount NUMERIC(18, 0) NOT NULL CHECK (amount > 0),
    source_kind TEXT NOT NULL CHECK (source_kind IN ('carry_forward', 'loan_instalment', 'advance', 'input')),
    source_id TEXT,
    source_payslip_id TEXT NOT NULL REFERENCES payroll.payslips (id) ON DELETE CASCADE,
    consumed_by_payslip_id TEXT REFERENCES payroll.payslips (id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS payroll_carry_forwards_open_idx ON payroll.carry_forwards (tenant_id, employee_id) WHERE consumed_by_payslip_id IS NULL;
```

- [ ] **Step 2: Add the hr fakes and insert helpers to `testing_support.py`**

Append to `backend/modules/payroll/api/testing_support.py` (and add `from decimal import Decimal` to its imports):

```python
class FakeSnapshots:
    """Stands in for hr's PayrollSnapshotService with contract-shaped dicts."""

    def __init__(self, employees: list[dict[str, Any]]) -> None:
        self.employees = employees

    def employees_for_period(self, *, tenant_id: str, period: datetime.date,
                             employee_ids: list[str] | None = None) -> list[dict[str, Any]]:
        return [employee for employee in self.employees if employee_ids is None or employee["employee_id"] in employee_ids]


PRESENCE_KEYS = (
    "scheduled_days", "worked_days", "unpaid_absence_days", "paid_leave_days", "sick_days", "holiday_days",
    "holidays_worked_days", "ot_minutes_day", "ot_minutes_night", "ot_minutes_rest_holiday", "night_minutes", "late_minutes",
)


def presence_summary(**counts: int) -> dict[str, int]:
    return {key: counts.get(key, 0) for key in PRESENCE_KEYS}


class FakePresence:
    """Stands in for hr's PresenceService: month summaries by employee, and whether the month is closed."""

    def __init__(self, summaries: dict[str, dict[str, int]] | None = None, *, closed: bool = True) -> None:
        self.summaries = summaries or {}
        self.closed = closed

    def month_summary(self, *, tenant_id: str, period: datetime.date, employee_ids: list[str] | None = None) -> list[dict[str, Any]]:
        ids = employee_ids if employee_ids is not None else list(self.summaries)
        return [{"employee_id": employee_id, **presence_summary(**self.summaries[employee_id])}
                for employee_id in ids if employee_id in self.summaries]

    def is_month_closed(self, *, tenant_id: str, period: datetime.date) -> bool:
        return self.closed


def snapshot(employee_id: str, *, employee_no: str, full_name: str, base_salary: Decimal = Decimal(400000),
             pay_frequency: str = "monthly", hire_date: datetime.date = datetime.date(2026, 9, 1),
             contract_start: datetime.date | None = None, contract_end: datetime.date | None = None,
             termination_date: datetime.date | None = None, termination_reason: str | None = None,
             department_id: str | None = "dept-a", tax_dependants: int = 0,
             components: tuple[dict[str, Any], ...] = (), payment_methods: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """One employee exactly as PayrollSnapshotService.employees_for_period returns it (contract shape)."""
    return {
        "employee_id": employee_id, "employee_no": employee_no, "full_name": full_name,
        "department_id": department_id, "position_id": None, "grade_id": None,
        "hire_date": hire_date, "termination_date": termination_date, "termination_reason": termination_reason,
        "tax_dependants": tax_dependants,
        "contract": {"id": f"contract-{employee_id}", "contract_type": "cdi", "base_salary": base_salary,
                     "weekly_hours": Decimal(40), "pay_frequency": pay_frequency,
                     "start_date": contract_start or hire_date, "end_date": contract_end,
                     "components": [dict(component) for component in components]},
        "payment_methods": payment_methods if payment_methods is not None else [
            {"method": "bank", "bank_name": "BDM", "account_no": f"ML-{employee_no}", "mobile_operator": None,
             "mobile_number": None, "share_percent": Decimal(100), "is_primary": True}],
    }


def insert_run(connection, *, tenant_id: str, actor_id: str, period: datetime.date, status: str = "draft",
               run_type: str = "regular", rule_set_id: str | None = None) -> str:
    """A run row in any status, for tests that need history without calculating it."""
    run_id = str(ULID())
    calculated = status != "draft"
    approved = status in ("approved", "paid", "reversed")
    connection.execute(
        """
        INSERT INTO payroll.runs (id, tenant_id, period, run_type, status, rule_set_id, created_by,
                                  calculated_by, calculated_at, approved_by, approved_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, CASE WHEN %s THEN clock_timestamp() END, %s, CASE WHEN %s THEN clock_timestamp() END)
        """,
        (run_id, tenant_id, period, run_type, status, rule_set_id, actor_id,
         actor_id if calculated else None, calculated, actor_id if approved else None, approved),
    )
    return run_id


def insert_payslip(connection, *, tenant_id: str, run_id: str, employee_id: str, rule_set_id: str,
                   gross: Decimal = Decimal(0), net: Decimal = Decimal(0)) -> str:
    payslip_id = str(ULID())
    connection.execute(
        """
        INSERT INTO payroll.payslips (id, tenant_id, run_id, employee_id, employee_no, full_name, rule_set_id,
            rule_set_status, snapshot, gross, contributable, taxable, employee_contrib, employer_contrib,
            employer_charges, its, deductions, net, employer_cost)
        VALUES (%s, %s, %s, %s, %s, %s, %s, 'confirmed', '{}'::jsonb, %s, 0, 0, 0, 0, 0, 0, 0, %s, %s)
        """,
        (payslip_id, tenant_id, run_id, employee_id, employee_id, employee_id, rule_set_id, gross, net, gross),
    )
    return payslip_id
```

- [ ] **Step 3: Write the failing integration tests**

Create `backend/modules/payroll/api/test_run_service_integration.py`:

```python
"""Runs against a real database: one regular run per month, edits while open, reopening rules."""
from __future__ import annotations

import datetime

import pytest

from core.domain.result import Err, Ok
from modules.payroll.api.rule_set_service import RuleSetService
from modules.payroll.api.run_service import RunService
from modules.payroll.api.testing_support import (
    FakePresence, FakeSnapshots, insert_run, make_user, set_country, store_rule_set,
)

TENANT = "payroll-runs-test"
SEPT = datetime.date(2031, 9, 1)


@pytest.fixture
def world(db):
    actor = make_user(db, TENANT)
    set_country(db, tenant_id=TENANT, actor_id=actor)
    rule_set_id = store_rule_set(db, tenant_id=TENANT, actor_id=actor, valid_from=datetime.date(2031, 1, 1))
    service = RunService(db, snapshots=FakeSnapshots([]), presence=FakePresence(closed=True))
    return {"db": db, "actor": actor, "service": service, "rule_set_id": rule_set_id}


def _create(world, **changes):
    values = {"period": SEPT, "run_type": "regular"} | changes
    return world["service"].create_run(tenant_id=TENANT, actor_id=world["actor"], **values)


def test_a_regular_run_starts_as_a_draft_and_shows_what_it_will_use(world):
    created = _create(world)
    assert isinstance(created, Ok)
    run = created.value
    assert (run["status"], run["run_type"], run["payslip_count"], run["presence_closed"]) == ("draft", "regular", 0, True)
    assert run["rule_set_in_force"] == {"id": world["rule_set_id"], "name": "Synthetic test rules", "status": "confirmed"}


def test_one_regular_run_per_month_but_any_number_of_off_cycle_runs(world):
    _create(world)
    again = _create(world)
    assert isinstance(again, Err) and again.code == "DUPLICATE_RUN" and "09/2031" in again.message_fr
    assert isinstance(_create(world, run_type="off_cycle", employee_ids=["E1"]), Ok)
    assert isinstance(_create(world, run_type="off_cycle", employee_ids=["E2"]), Ok)
    assert len(world["service"].list_runs(tenant_id=TENANT)) == 3


def test_a_reversed_regular_run_frees_its_month(world):
    insert_run(world["db"], tenant_id=TENANT, actor_id=world["actor"], period=SEPT, status="reversed", rule_set_id=world["rule_set_id"])
    assert isinstance(_create(world), Ok)


def test_bad_runs_are_refused_in_both_languages(world):
    for changes in ({"period": datetime.date(2031, 9, 15)}, {"run_type": "bonus"}, {"employee_ids": ["E1"]}):
        refused = _create(world, **changes)
        assert isinstance(refused, Err) and refused.code == "RUN_INVALID" and refused.message_fr


def test_an_open_run_can_be_relabelled_and_deleted_with_an_audit_trail(world):
    run_id = _create(world, run_type="off_cycle", employee_ids=["E1"]).value["id"]
    service = world["service"]
    updated = service.update_run(tenant_id=TENANT, actor_id=world["actor"], run_id=run_id, changes={"label": "Correction", "employee_ids": ["E2", "E1"]})
    assert isinstance(updated, Ok) and updated.value["label"] == "Correction" and updated.value["employee_ids"] == ["E1", "E2"]
    assert isinstance(service.delete_run(tenant_id=TENANT, actor_id=world["actor"], run_id=run_id), Ok)
    actions = [row[0] for row in world["db"].execute(
        "SELECT action FROM core.audit_log WHERE entity_id = %s ORDER BY occurred_at, action", (run_id,)).fetchall()]
    assert set(actions) == {"payroll_run.created", "payroll_run.updated", "payroll_run.deleted"}


def test_an_approved_run_cannot_be_edited_or_deleted(world):
    run_id = insert_run(world["db"], tenant_id=TENANT, actor_id=world["actor"], period=SEPT, status="approved", rule_set_id=world["rule_set_id"])
    service = world["service"]
    assert service.update_run(tenant_id=TENANT, actor_id=world["actor"], run_id=run_id, changes={"label": "x"}).code == "RUN_LOCKED"
    assert service.delete_run(tenant_id=TENANT, actor_id=world["actor"], run_id=run_id).code == "RUN_LOCKED"


def test_reopening_a_rule_set_is_refused_once_an_approved_run_used_it(world):
    rules = RuleSetService(world["db"])
    reopened = rules.reopen_rule_set(tenant_id=TENANT, actor_id=world["actor"], rule_set_id=world["rule_set_id"])
    assert isinstance(reopened, Ok) and reopened.value["status"] == "draft" and reopened.value["confirmed_at"] is None
    assert isinstance(rules.confirm_rule_set(tenant_id=TENANT, actor_id=world["actor"], rule_set_id=world["rule_set_id"]), Ok)
    insert_run(world["db"], tenant_id=TENANT, actor_id=world["actor"], period=SEPT, status="approved", rule_set_id=world["rule_set_id"])
    refused = rules.reopen_rule_set(tenant_id=TENANT, actor_id=world["actor"], rule_set_id=world["rule_set_id"])
    assert isinstance(refused, Err) and refused.code == "RULESET_IN_USE" and "09/2031" in refused.message_fr
```

- [ ] **Step 4: Apply the migration and run the tests to verify they fail**

Run:
```
.venv/Scripts/python -c "import app.main; from core.migrations.runner import apply_all_migrations; apply_all_migrations()"
.venv/Scripts/python -m pytest modules/payroll/api/test_run_service_integration.py -q
```
Expected: FAIL — `ModuleNotFoundError: No module named 'modules.payroll.api.run_service'`.

- [ ] **Step 5: Write `run_state.py`**

```python
"""Run status rules shared by every service that touches a run."""
from __future__ import annotations

from typing import Any

import psycopg

from core.domain.result import Err
from modules.payroll.api.rows import fetch_one

EDITABLE = ("draft", "calculated")
STATUS_FR = {"draft": "brouillon", "calculated": "calculée", "approved": "approuvée", "paid": "payée", "reversed": "extournée"}
_COLUMNS = ("id, tenant_id, period, run_type, label, employee_ids, rule_set_id, status, created_by, "
            "calculated_by, calculated_at, approved_by, approved_at")


def lock_run(connection: psycopg.Connection, tenant_id: str, run_id: str) -> dict[str, Any] | None:
    return fetch_one(connection, f"SELECT {_COLUMNS} FROM payroll.runs WHERE tenant_id = %s AND id = %s FOR UPDATE", (tenant_id, run_id))


def not_found() -> Err:
    return Err("NOT_FOUND", "payroll run not found", "paie introuvable")


def locked(status: str) -> Err:
    return Err("RUN_LOCKED", f"the run is {status}; it can no longer change",
               f"la paie est {STATUS_FR.get(status, status)} ; elle ne peut plus changer")


def invalidate(connection: psycopg.Connection, run_id: str) -> bool:
    """A calculated run whose inputs changed goes back to draft and loses its payslips; what they
    had deducted (advances, instalments, carried amounts) is released by ON DELETE SET NULL."""
    changed = connection.execute(
        "UPDATE payroll.runs SET status = 'draft', rule_set_id = NULL, calculated_by = NULL, calculated_at = NULL "
        "WHERE id = %s AND status = 'calculated' RETURNING id",
        (run_id,),
    ).fetchone()
    if changed is not None:
        connection.execute("DELETE FROM payroll.payslips WHERE run_id = %s", (run_id,))
    return changed is not None
```

- [ ] **Step 6: Write `run_service.py` (basics)**

```python
"""Payroll runs: one regular run per month, any number of off-cycle runs (final settlements,
corrections). draft -> calculated -> approved -> paid, or reversed from approved/paid.

hr is reached only through its api services (contract), injected so tests pass fakes.
"""
from __future__ import annotations

import datetime
from typing import Any

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.hr.api.payroll_snapshot_service import PayrollSnapshotService
from modules.hr.api.presence_service import PresenceService
from modules.payroll.api.rows import fetch_all, fetch_one, jsonable
from modules.payroll.api.rule_set_service import RuleSetService
from modules.payroll.api.run_state import EDITABLE, invalidate, lock_run, locked, not_found

RUN_TYPES = ("regular", "off_cycle")
RUN_SELECT = """
    SELECT r.id, r.period, r.run_type, r.label, r.employee_ids, r.rule_set_id, rs.status AS rule_set_status, r.status,
           r.created_by, r.created_at, r.calculated_by, r.calculated_at, r.approved_by, r.approved_at,
           r.paid_by, r.paid_at, r.reversed_by, r.reversed_at, r.reversal_reason,
           COUNT(p.id) AS payslip_count, COALESCE(SUM(p.gross), 0) AS gross, COALESCE(SUM(p.net), 0) AS net,
           COALESCE(SUM(p.employer_cost), 0) AS employer_cost,
           COUNT(p.id) FILTER (WHERE jsonb_array_length(p.warnings) > 0) AS warning_count
    FROM payroll.runs r
    LEFT JOIN payroll.rule_sets rs ON rs.id = r.rule_set_id
    LEFT JOIN payroll.payslips p ON p.run_id = r.id
"""
RUN_GROUP = " GROUP BY r.id, rs.status"


def _run_problem(period: datetime.date, run_type: str, employee_ids: list[str] | None) -> Err | None:
    if period.day != 1:
        return Err("RUN_INVALID", "the period is the first day of a month", "la période est le premier jour d'un mois")
    if run_type not in RUN_TYPES:
        return Err("RUN_INVALID", "a run is regular or off_cycle", "une paie est normale (regular) ou hors cycle (off_cycle)")
    if run_type == "regular" and employee_ids:
        return Err("RUN_INVALID", "a regular run pays everyone; choose employees on an off-cycle run",
                   "une paie normale paie tout le monde ; choisissez des employés sur une paie hors cycle")
    return None


def _ids(employee_ids: list[str] | None) -> list[str] | None:
    return sorted(set(employee_ids)) if employee_ids else None


class RunService:
    def __init__(self, connection: psycopg.Connection, *, snapshots: Any = None, presence: Any = None) -> None:
        self.connection = connection
        self.snapshots = snapshots if snapshots is not None else PayrollSnapshotService(connection)
        self.presence = presence if presence is not None else PresenceService(connection)

    def list_runs(self, *, tenant_id: str, status: str | None = None) -> list[dict[str, Any]]:
        clauses, params = ["r.tenant_id = %s"], [tenant_id]
        if status:
            clauses.append("r.status = %s")
            params.append(status)
        sql = RUN_SELECT + " WHERE " + " AND ".join(clauses) + RUN_GROUP + " ORDER BY r.period DESC, r.created_at DESC"
        return jsonable(fetch_all(self.connection, sql, params))

    def get_run(self, *, tenant_id: str, run_id: str) -> dict[str, Any] | None:
        row = fetch_one(self.connection, RUN_SELECT + " WHERE r.tenant_id = %s AND r.id = %s" + RUN_GROUP, (tenant_id, run_id))
        if row is None:
            return None
        document = jsonable(row)
        document["presence_closed"] = (
            self.presence.is_month_closed(tenant_id=tenant_id, period=row["period"]) if row["run_type"] == "regular" else None
        )
        in_force = RuleSetService(self.connection).in_force(tenant_id=tenant_id, period=row["period"])
        document["rule_set_in_force"] = None if isinstance(in_force, Err) else {
            "id": in_force.value["id"], "name": in_force.value["name"], "status": in_force.value["status"]}
        return document

    def create_run(self, *, tenant_id: str, actor_id: str, period: datetime.date, run_type: str,
                   label: str | None = None, employee_ids: list[str] | None = None) -> Result[dict[str, Any]]:
        problem = _run_problem(period, run_type, employee_ids)
        if problem is not None:
            return problem
        run_id = str(ULID())
        try:
            with self.connection.transaction():
                self.connection.execute(
                    "INSERT INTO payroll.runs (id, tenant_id, period, run_type, label, employee_ids, created_by) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (run_id, tenant_id, period, run_type, label, _ids(employee_ids), actor_id),
                )
        except psycopg.errors.UniqueViolation:
            return Err("DUPLICATE_RUN", f"a regular run already exists for {period:%Y-%m}",
                       f"une paie normale existe déjà pour {period:%m/%Y}")
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="payroll_run.created",
                     entity_type="payroll_run", entity_id=run_id,
                     payload={"period": period.isoformat(), "run_type": run_type, "label": label, "employee_ids": _ids(employee_ids)})
        return Ok(self.get_run(tenant_id=tenant_id, run_id=run_id))

    def update_run(self, *, tenant_id: str, actor_id: str, run_id: str, changes: dict[str, Any]) -> Result[dict[str, Any]]:
        run = lock_run(self.connection, tenant_id, run_id)
        if run is None:
            return not_found()
        if run["status"] not in EDITABLE:
            return locked(run["status"])
        unknown = sorted(set(changes) - {"label", "employee_ids"})
        if unknown:
            return Err("RUN_INVALID", f"unknown fields: {', '.join(unknown)}", f"champs inconnus : {', '.join(unknown)}")
        label = changes.get("label", run["label"])
        employee_ids = changes.get("employee_ids", run["employee_ids"])
        problem = _run_problem(run["period"], run["run_type"], employee_ids)
        if problem is not None:
            return problem
        self.connection.execute("UPDATE payroll.runs SET label = %s, employee_ids = %s WHERE id = %s", (label, _ids(employee_ids), run_id))
        if "employee_ids" in changes:
            invalidate(self.connection, run_id)
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="payroll_run.updated",
                     entity_type="payroll_run", entity_id=run_id, payload={"changes": jsonable(changes)})
        return Ok(self.get_run(tenant_id=tenant_id, run_id=run_id))

    def delete_run(self, *, tenant_id: str, actor_id: str, run_id: str) -> Result[dict[str, Any]]:
        run = lock_run(self.connection, tenant_id, run_id)
        if run is None:
            return not_found()
        if run["status"] not in EDITABLE:
            return locked(run["status"])
        self.connection.execute("DELETE FROM payroll.runs WHERE id = %s", (run_id,))
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="payroll_run.deleted",
                     entity_type="payroll_run", entity_id=run_id,
                     payload={"period": run["period"].isoformat(), "run_type": run["run_type"], "status": run["status"]})
        return Ok({"id": run_id})
```

- [ ] **Step 7: Add `reopen_rule_set` to `RuleSetService`**

In `backend/modules/payroll/api/rule_set_service.py`, add after `confirm_rule_set`:

```python
    def reopen_rule_set(self, *, tenant_id: str, actor_id: str, rule_set_id: str) -> Result[dict[str, Any]]:
        header = self._header(tenant_id, rule_set_id, lock=True)
        if header is None:
            return _not_found("rule set", "jeu de règles")
        if header["status"] != "confirmed":
            return Err("RULE_INVALID", "this rule set is already a draft", "ce jeu de règles est déjà un brouillon")
        used = fetch_one(
            self.connection,
            "SELECT period FROM payroll.runs WHERE rule_set_id = %s AND status IN ('approved', 'paid') ORDER BY period LIMIT 1",
            (rule_set_id,),
        )
        if used is not None:
            return Err("RULESET_IN_USE", f"the {used['period']:%Y-%m} run was approved with this rule set; copy it to a new draft instead",
                       f"la paie de {used['period']:%m/%Y} a été approuvée avec ce jeu de règles ; copiez-le plutôt en brouillon")
        self.connection.execute(
            "UPDATE payroll.rule_sets SET status = 'draft', confirmed_by = NULL, confirmed_at = NULL WHERE id = %s", (rule_set_id,))
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="rule_set.reopened",
                     entity_type="rule_set", entity_id=rule_set_id, payload={"from_status": "confirmed", "to_status": "draft"})
        return Ok(self.get_rule_set(tenant_id=tenant_id, rule_set_id=rule_set_id))
```

In `backend/modules/payroll/api/routes_rules.py`, add right after the `confirm_rule_set` route (and before the "Generic rule-table routes" comment):

```python
@router.post("/rule-sets/{rule_set_id}/reopen")
def reopen_rule_set(rule_set_id: str, tenant: TenantContext = Depends(require_permission("payroll.confirm_rules"))):
    with http.get_connection() as connection:
        result = RuleSetService(connection).reopen_rule_set(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, rule_set_id=rule_set_id)
        return http.finish(connection, result)
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest modules/payroll/api/test_run_service_integration.py modules/payroll/api/test_rules_router_integration.py -q`
Expected: all pass (7 + 5), no skips.

- [ ] **Step 9: Commit**

```bash
git add backend/modules/payroll/migrations/0002_payroll_runs.sql backend/modules/payroll/api/run_state.py backend/modules/payroll/api/run_service.py backend/modules/payroll/api/rule_set_service.py backend/modules/payroll/api/routes_rules.py backend/modules/payroll/api/testing_support.py backend/modules/payroll/api/test_run_service_integration.py
git commit -m "feat(payroll): payroll runs and payslip tables, run service basics, rule-set reopen

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Monthly inputs, advances and loans

**Files:**
- Create: `backend/modules/payroll/migrations/0003_payroll_advances_loans.sql`
- Create: `backend/modules/payroll/api/input_service.py`
- Test: `backend/modules/payroll/api/test_input_service_integration.py`

**Interfaces:**
- Consumes: `run_state.*` (Task 4), `RuleSetService.in_force/load`, `instalment_schedule` (Task 1), `OneOffInput`, `SYSTEM_COMPONENTS`, `ADVANCE`, `LOAN`.
- Produces: `InputService(connection, *, snapshots=None)` with
  - `input_components(*, tenant_id, run_id) -> Result[list[dict]]` (`code, name_en, name_fr, kind, formula_type, default_amount` of every earning/deduction that may be typed: formula `fixed|qty_x_rate|per_day`, not a system code)
  - `list_run_inputs(*, tenant_id, run_id)`, `add_run_input(*, tenant_id, actor_id, run_id, employee_id, component_code, qty=None, amount=None, note=None)`, `update_run_input(*, tenant_id, actor_id, input_id, changes)`, `delete_run_input(*, tenant_id, actor_id, input_id)`
  - `run_inputs_by_employee(*, tenant_id, run_id) -> dict[str, list[OneOffInput]]`
  - `list_advances(*, tenant_id, status=None)`, `create_advance(*, tenant_id, actor_id, employee_id, amount, requested_on, deduct_period, note=None)`, `update_advance(*, tenant_id, actor_id, advance_id, changes)`, `approve_advance(...)`, `cancel_advance(...)`
  - `list_loans(*, tenant_id, status=None)` (each with `instalments` and `remaining`), `create_loan(*, tenant_id, actor_id, employee_id, principal, instalment_count, first_period, note=None)`, `update_loan(*, tenant_id, actor_id, loan_id, changes)`, `cancel_loan(...)`
  - `due_deductions(*, tenant_id, period, employee_ids: list[str], settle_ids: set[str]) -> dict[str, list[OneOffInput]]` — carried amounts from approved/paid runs, instalments of active loans due by the period, approved advances due by the period; for `settle_ids` (final settlement) every open instalment and advance regardless of period.
- Error codes: `NOT_FOUND`, `INPUT_INVALID`, `RUN_LOCKED`.

Resolved ambiguity: the spec's permission list has no `admin_inputs`; inputs, advances and loans are created and edited under `payroll.manage_inputs`. What an approved/paid run has already deducted is frozen (`RUN_LOCKED`) because the money moved; a change touching a *calculated* run sends that run back to draft (it must be recalculated).

- [ ] **Step 1: Write the migration**

Create `backend/modules/payroll/migrations/0003_payroll_advances_loans.sql`:

```sql
-- Salary advances and loans. Deduction is recorded by the payslip that took it (ON DELETE SET NULL
-- releases it when that payslip is recalculated away).
CREATE TABLE IF NOT EXISTS payroll.advances (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    employee_id TEXT NOT NULL,
    employee_no TEXT NOT NULL,
    full_name TEXT NOT NULL,
    amount NUMERIC(18, 0) NOT NULL CHECK (amount > 0),
    requested_on DATE NOT NULL,
    deduct_period DATE NOT NULL CHECK (EXTRACT(DAY FROM deduct_period) = 1),
    status TEXT NOT NULL DEFAULT 'requested' CHECK (status IN ('requested', 'approved', 'cancelled')),
    approved_by TEXT,
    approved_at TIMESTAMPTZ,
    note TEXT,
    deducted_payslip_id TEXT REFERENCES payroll.payslips (id) ON DELETE SET NULL,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS payroll_advances_employee_idx ON payroll.advances (tenant_id, employee_id);

CREATE TABLE IF NOT EXISTS payroll.loans (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    employee_id TEXT NOT NULL,
    employee_no TEXT NOT NULL,
    full_name TEXT NOT NULL,
    principal NUMERIC(18, 0) NOT NULL CHECK (principal > 0),
    instalment_count INTEGER NOT NULL CHECK (instalment_count >= 1),
    first_period DATE NOT NULL CHECK (EXTRACT(DAY FROM first_period) = 1),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'cancelled')),
    note TEXT,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS payroll.loan_instalments (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    loan_id TEXT NOT NULL REFERENCES payroll.loans (id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    period DATE NOT NULL,
    amount NUMERIC(18, 0) NOT NULL CHECK (amount > 0),
    payslip_id TEXT REFERENCES payroll.payslips (id) ON DELETE SET NULL,
    UNIQUE (loan_id, seq)
);
```

- [ ] **Step 2: Write the failing integration tests**

Create `backend/modules/payroll/api/test_input_service_integration.py`:

```python
"""Inputs, advances and loans against a real database."""
from __future__ import annotations

import datetime
from decimal import Decimal

import pytest

from core.domain.result import Err, Ok
from modules.payroll.api.input_service import InputService
from modules.payroll.api.testing_support import (
    FakeSnapshots, insert_payslip, insert_run, make_user, set_country, snapshot, store_rule_set,
)

TENANT = "payroll-inputs-test"
SEPT = datetime.date(2031, 9, 1)
OCT = datetime.date(2031, 10, 1)
D = Decimal


@pytest.fixture
def world(db):
    actor = make_user(db, TENANT)
    set_country(db, tenant_id=TENANT, actor_id=actor)
    rule_set_id = store_rule_set(db, tenant_id=TENANT, actor_id=actor, valid_from=datetime.date(2031, 1, 1))
    employees = [snapshot("E1", employee_no="M-001", full_name="Awa Traoré"), snapshot("E2", employee_no="M-002", full_name="Moussa Keita")]
    service = InputService(db, snapshots=FakeSnapshots(employees))
    return {"db": db, "actor": actor, "rule_set_id": rule_set_id, "service": service}


def _run(world, status="draft"):
    return insert_run(world["db"], tenant_id=TENANT, actor_id=world["actor"], period=SEPT, status=status,
                      rule_set_id=None if status == "draft" else world["rule_set_id"])


def test_a_monthly_input_is_stored_with_the_employee_name(world):
    run_id = _run(world)
    added = world["service"].add_run_input(tenant_id=TENANT, actor_id=world["actor"], run_id=run_id, employee_id="E1",
                                           component_code="bonus", amount=D(25000), note="Prime qualité")
    assert isinstance(added, Ok) and added.value["component_code"] == "BONUS" and added.value["full_name"] == "Awa Traoré"
    grouped = world["service"].run_inputs_by_employee(tenant_id=TENANT, run_id=run_id)
    assert [(item.component_code, item.amount, item.source_kind) for item in grouped["E1"]] == [("BONUS", D(25000), "input")]


def test_only_typed_components_can_be_inputs(world):
    run_id = _run(world)
    offered = world["service"].input_components(tenant_id=TENANT, run_id=run_id).value
    assert {item["code"] for item in offered} == {"HOUSING", "TRANSPORT", "MEAL", "BONUS", "CANTEEN"}
    for code in ("BASE", "SENIORITY", "NOPE"):
        refused = world["service"].add_run_input(tenant_id=TENANT, actor_id=world["actor"], run_id=run_id, employee_id="E1", component_code=code, amount=D(1))
        assert isinstance(refused, Err) and refused.code == "INPUT_INVALID", code


def test_an_input_needs_an_amount_or_a_quantity_and_a_contract(world):
    run_id = _run(world)
    service = world["service"]
    assert service.add_run_input(tenant_id=TENANT, actor_id=world["actor"], run_id=run_id, employee_id="E1", component_code="BONUS").code == "INPUT_INVALID"
    assert service.add_run_input(tenant_id=TENANT, actor_id=world["actor"], run_id=run_id, employee_id="E9", component_code="BONUS", amount=D(1)).code == "NOT_FOUND"


def test_changing_an_input_sends_a_calculated_run_back_to_draft(world):
    run_id = _run(world, status="calculated")
    insert_payslip(world["db"], tenant_id=TENANT, run_id=run_id, employee_id="E1", rule_set_id=world["rule_set_id"])
    world["service"].add_run_input(tenant_id=TENANT, actor_id=world["actor"], run_id=run_id, employee_id="E1", component_code="BONUS", amount=D(5000))
    status, payslips = world["db"].execute(
        "SELECT r.status, (SELECT count(*) FROM payroll.payslips WHERE run_id = r.id) FROM payroll.runs r WHERE r.id = %s", (run_id,)).fetchone()
    assert (status, payslips) == ("draft", 0)


def test_an_approved_run_takes_no_more_inputs(world):
    run_id = _run(world, status="approved")
    refused = world["service"].add_run_input(tenant_id=TENANT, actor_id=world["actor"], run_id=run_id, employee_id="E1", component_code="BONUS", amount=D(1))
    assert isinstance(refused, Err) and refused.code == "RUN_LOCKED"


def test_an_advance_is_due_from_its_month_once_approved(world):
    service = world["service"]
    advance = service.create_advance(tenant_id=TENANT, actor_id=world["actor"], employee_id="E1", amount=D(50000),
                                     requested_on=datetime.date(2031, 9, 3), deduct_period=OCT).value
    assert advance["status"] == "requested"
    assert service.due_deductions(tenant_id=TENANT, period=OCT, employee_ids=["E1"], settle_ids=set()) == {}
    assert service.approve_advance(tenant_id=TENANT, actor_id=world["actor"], advance_id=advance["id"]).value["status"] == "approved"
    assert service.due_deductions(tenant_id=TENANT, period=SEPT, employee_ids=["E1"], settle_ids=set()) == {}
    due = service.due_deductions(tenant_id=TENANT, period=OCT, employee_ids=["E1"], settle_ids=set())
    assert [(item.component_code, item.amount, item.source_kind, item.source_id) for item in due["E1"]] == [
        ("ADVANCE", D(50000), "advance", advance["id"])]
    settling = service.due_deductions(tenant_id=TENANT, period=SEPT, employee_ids=["E1"], settle_ids={"E1"})
    assert [item.source_id for item in settling["E1"]] == [advance["id"]]


def test_an_advance_deducted_by_an_approved_run_is_frozen(world):
    service = world["service"]
    advance = service.create_advance(tenant_id=TENANT, actor_id=world["actor"], employee_id="E1", amount=D(50000),
                                     requested_on=datetime.date(2031, 9, 3), deduct_period=SEPT).value
    run_id = _run(world, status="approved")
    payslip_id = insert_payslip(world["db"], tenant_id=TENANT, run_id=run_id, employee_id="E1", rule_set_id=world["rule_set_id"])
    world["db"].execute("UPDATE payroll.advances SET status = 'approved', deducted_payslip_id = %s WHERE id = %s", (payslip_id, advance["id"]))
    assert service.update_advance(tenant_id=TENANT, actor_id=world["actor"], advance_id=advance["id"], changes={"amount": D(1)}).code == "RUN_LOCKED"
    assert service.cancel_advance(tenant_id=TENANT, actor_id=world["actor"], advance_id=advance["id"]).code == "RUN_LOCKED"
    listed = service.list_advances(tenant_id=TENANT)[0]
    assert (listed["deducted_run_id"], listed["deducted_run_status"]) == (run_id, "approved")


def test_a_loan_is_split_into_monthly_instalments(world):
    service = world["service"]
    loan = service.create_loan(tenant_id=TENANT, actor_id=world["actor"], employee_id="E2", principal=D(100000),
                               instalment_count=3, first_period=SEPT).value
    assert [(item["seq"], item["amount"]) for item in loan["instalments"]] == [(1, 33333), (2, 33333), (3, 33334)]
    assert loan["remaining"] == 100000
    due = service.due_deductions(tenant_id=TENANT, period=SEPT, employee_ids=["E2"], settle_ids=set())
    assert [(item.component_code, item.amount) for item in due["E2"]] == [("LOAN", D(33333))]
    settling = service.due_deductions(tenant_id=TENANT, period=SEPT, employee_ids=["E2"], settle_ids={"E2"})
    assert len(settling["E2"]) == 3


def test_a_cancelled_loan_drops_its_open_instalments(world):
    service = world["service"]
    loan = service.create_loan(tenant_id=TENANT, actor_id=world["actor"], employee_id="E2", principal=D(90000), instalment_count=3, first_period=SEPT).value
    cancelled = service.cancel_loan(tenant_id=TENANT, actor_id=world["actor"], loan_id=loan["id"])
    assert isinstance(cancelled, Ok) and cancelled.value["status"] == "cancelled" and cancelled.value["instalments"] == []
    assert service.due_deductions(tenant_id=TENANT, period=SEPT, employee_ids=["E2"], settle_ids=set()) == {}


def test_a_loan_needs_a_franc_per_instalment(world):
    refused = world["service"].create_loan(tenant_id=TENANT, actor_id=world["actor"], employee_id="E2", principal=D(2), instalment_count=3, first_period=SEPT)
    assert isinstance(refused, Err) and refused.code == "INPUT_INVALID" and refused.message_fr
```

- [ ] **Step 3: Apply the migration and run the tests to verify they fail**

Run:
```
.venv/Scripts/python -c "import app.main; from core.migrations.runner import apply_all_migrations; apply_all_migrations()"
.venv/Scripts/python -m pytest modules/payroll/api/test_input_service_integration.py -q
```
Expected: FAIL — `ModuleNotFoundError: No module named 'modules.payroll.api.input_service'`.

- [ ] **Step 4: Write `input_service.py`**

```python
"""Monthly inputs (bonus, canteen…), salary advances and loans — the one-off lines of a payslip.

Writes need payroll.manage_inputs (checked by the routes). What an approved or paid run already
deducted is frozen (RUN_LOCKED); a change that touches a calculated run sends it back to draft.
"""
from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.hr.api.payroll_snapshot_service import PayrollSnapshotService
from modules.payroll.api.rows import fetch_all, fetch_one, jsonable
from modules.payroll.api.rule_set_service import RuleSetService
from modules.payroll.api.run_state import EDITABLE, invalidate, lock_run, locked, not_found
from modules.payroll.domain.inputs import OneOffInput
from modules.payroll.domain.loans import instalment_schedule
from modules.payroll.domain.rules import ADVANCE, LOAN, SYSTEM_COMPONENTS

INPUT_FORMULAS = ("fixed", "qty_x_rate", "per_day")
_INPUT_COLUMNS = "id, run_id, employee_id, employee_no, full_name, component_code, qty, amount, note, created_by, created_at"
_ADVANCE_SELECT = """
    SELECT a.id, a.employee_id, a.employee_no, a.full_name, a.amount, a.requested_on, a.deduct_period, a.status,
           a.approved_by, a.approved_at, a.note, a.deducted_payslip_id, a.created_by, a.created_at,
           r.id AS deducted_run_id, r.period AS deducted_period, r.status AS deducted_run_status
    FROM payroll.advances a
    LEFT JOIN payroll.payslips p ON p.id = a.deducted_payslip_id
    LEFT JOIN payroll.runs r ON r.id = p.run_id
"""
_LOAN_COLUMNS = "id, employee_id, employee_no, full_name, principal, instalment_count, first_period, status, note, created_by, created_at"


def _invalid(english: str, french: str) -> Err:
    return Err("INPUT_INVALID", english, french)


def _amount_problem(qty: Decimal | None, amount: Decimal | None) -> Err | None:
    if qty is None and amount is None:
        return _invalid("give a quantity or an amount", "indiquez une quantité ou un montant")
    if (qty is not None and qty < 0) or (amount is not None and amount < 0):
        return _invalid("quantities and amounts are not negative", "les quantités et montants ne sont pas négatifs")
    if amount is not None and amount != amount.to_integral_value():
        return _invalid("the amount is in whole francs", "le montant s'exprime en francs entiers")
    return None


def _money_problem(amount: Decimal, name_en: str, name_fr: str) -> Err | None:
    if amount is None or amount <= 0 or amount != amount.to_integral_value():
        return _invalid(f"the {name_en} is a positive whole number of francs", f"le {name_fr} est un nombre entier positif de francs")
    return None


def _period_problem(period: datetime.date) -> Err | None:
    if period.day != 1:
        return _invalid("a payroll month is the first day of the month", "un mois de paie est le premier jour du mois")
    return None


class InputService:
    def __init__(self, connection: psycopg.Connection, *, snapshots: Any = None) -> None:
        self.connection = connection
        self.snapshots = snapshots if snapshots is not None else PayrollSnapshotService(connection)

    # -- shared checks ------------------------------------------------------------------------
    def _employee(self, tenant_id: str, period: datetime.date, employee_id: str) -> dict[str, Any] | None:
        found = self.snapshots.employees_for_period(tenant_id=tenant_id, period=period, employee_ids=[employee_id])
        return found[0] if found else None

    @staticmethod
    def _no_contract(period: datetime.date) -> Err:
        return Err("NOT_FOUND", f"this employee has no contract in {period:%Y-%m}", f"cet employé n'a pas de contrat en {period:%m/%Y}")

    def _typed_components(self, tenant_id: str, period: datetime.date) -> Result[dict[str, Any]]:
        rule_sets = RuleSetService(self.connection)
        in_force = rule_sets.in_force(tenant_id=tenant_id, period=period)
        if isinstance(in_force, Err):
            return in_force
        rules = rule_sets.load(tenant_id=tenant_id, rule_set_id=in_force.value["id"])
        return Ok({component.code: component for component in rules.components
                   if component.kind in ("earning", "deduction") and component.formula_type in INPUT_FORMULAS
                   and component.code not in SYSTEM_COMPONENTS})

    def _release(self, payslip_id: str | None) -> Err | None:
        """Frozen once an approved/paid run deducted it; a calculated run that took it goes back to draft."""
        if payslip_id is None:
            return None
        run = fetch_one(self.connection, "SELECT r.id, r.status FROM payroll.payslips p JOIN payroll.runs r ON r.id = p.run_id WHERE p.id = %s", (payslip_id,))
        if run is None:
            return None
        if run["status"] in ("approved", "paid"):
            return Err("RUN_LOCKED", "an approved run already deducted it; it can no longer change",
                       "une paie approuvée l'a déjà retenu ; il ne peut plus changer")
        invalidate(self.connection, run["id"])
        return None

    # -- monthly inputs -----------------------------------------------------------------------
    def input_components(self, *, tenant_id: str, run_id: str) -> Result[list[dict[str, Any]]]:
        run = fetch_one(self.connection, "SELECT period FROM payroll.runs WHERE tenant_id = %s AND id = %s", (tenant_id, run_id))
        if run is None:
            return not_found()
        typed = self._typed_components(tenant_id, run["period"])
        if isinstance(typed, Err):
            return typed
        return Ok([jsonable({"code": c.code, "name_en": c.name_en, "name_fr": c.name_fr, "kind": c.kind,
                             "formula_type": c.formula_type, "default_amount": c.default_amount})
                   for c in sorted(typed.value.values(), key=lambda item: (item.display_order, item.code))])

    def list_run_inputs(self, *, tenant_id: str, run_id: str) -> list[dict[str, Any]]:
        return jsonable(fetch_all(self.connection, f"SELECT {_INPUT_COLUMNS} FROM payroll.run_inputs WHERE tenant_id = %s AND run_id = %s ORDER BY full_name, component_code",
                                  (tenant_id, run_id)))

    def _input(self, tenant_id: str, input_id: str) -> dict[str, Any] | None:
        return fetch_one(self.connection, f"SELECT {_INPUT_COLUMNS} FROM payroll.run_inputs WHERE tenant_id = %s AND id = %s", (tenant_id, input_id))

    def _check_input(self, tenant_id: str, period: datetime.date, code: str, qty, amount) -> Err | None:
        problem = _amount_problem(qty, amount)
        if problem is not None:
            return problem
        typed = self._typed_components(tenant_id, period)
        if isinstance(typed, Err):
            return typed
        if code not in typed.value:
            return _invalid(f"{code} cannot be typed as a monthly input", f"{code} ne se saisit pas en variable du mois")
        return None

    def add_run_input(self, *, tenant_id: str, actor_id: str, run_id: str, employee_id: str, component_code: str,
                      qty: Decimal | None = None, amount: Decimal | None = None, note: str | None = None) -> Result[dict[str, Any]]:
        run = lock_run(self.connection, tenant_id, run_id)
        if run is None:
            return not_found()
        if run["status"] not in EDITABLE:
            return locked(run["status"])
        code = component_code.strip().upper()
        problem = self._check_input(tenant_id, run["period"], code, qty, amount)
        if problem is not None:
            return problem
        employee = self._employee(tenant_id, run["period"], employee_id)
        if employee is None:
            return self._no_contract(run["period"])
        input_id = str(ULID())
        self.connection.execute(
            "INSERT INTO payroll.run_inputs (id, tenant_id, run_id, employee_id, employee_no, full_name, component_code, qty, amount, note, created_by) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (input_id, tenant_id, run_id, employee_id, employee["employee_no"], employee["full_name"], code, qty, amount, note, actor_id),
        )
        invalidate(self.connection, run_id)
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="run_input.created", entity_type="run_input",
                     entity_id=input_id, payload=jsonable({"run_id": run_id, "employee_id": employee_id, "component_code": code, "qty": qty, "amount": amount}))
        return Ok(jsonable(self._input(tenant_id, input_id)))

    def update_run_input(self, *, tenant_id: str, actor_id: str, input_id: str, changes: dict[str, Any]) -> Result[dict[str, Any]]:
        current = self._input(tenant_id, input_id)
        if current is None:
            return Err("NOT_FOUND", "input not found", "variable introuvable")
        unknown = sorted(set(changes) - {"component_code", "qty", "amount", "note"})
        if unknown:
            return _invalid(f"unknown fields: {', '.join(unknown)}", f"champs inconnus : {', '.join(unknown)}")
        run = lock_run(self.connection, tenant_id, current["run_id"])
        if run["status"] not in EDITABLE:
            return locked(run["status"])
        merged = {key: current[key] for key in ("component_code", "qty", "amount", "note")} | changes
        code = str(merged["component_code"]).strip().upper()
        problem = self._check_input(tenant_id, run["period"], code, merged["qty"], merged["amount"])
        if problem is not None:
            return problem
        self.connection.execute("UPDATE payroll.run_inputs SET component_code = %s, qty = %s, amount = %s, note = %s WHERE id = %s",
                                (code, merged["qty"], merged["amount"], merged["note"], input_id))
        invalidate(self.connection, current["run_id"])
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="run_input.updated", entity_type="run_input",
                     entity_id=input_id, payload={"changes": jsonable(changes)})
        return Ok(jsonable(self._input(tenant_id, input_id)))

    def delete_run_input(self, *, tenant_id: str, actor_id: str, input_id: str) -> Result[dict[str, Any]]:
        current = self._input(tenant_id, input_id)
        if current is None:
            return Err("NOT_FOUND", "input not found", "variable introuvable")
        run = lock_run(self.connection, tenant_id, current["run_id"])
        if run["status"] not in EDITABLE:
            return locked(run["status"])
        self.connection.execute("DELETE FROM payroll.run_inputs WHERE id = %s", (input_id,))
        invalidate(self.connection, current["run_id"])
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="run_input.deleted", entity_type="run_input",
                     entity_id=input_id, payload=jsonable({key: current[key] for key in ("run_id", "employee_id", "component_code", "qty", "amount")}))
        return Ok({"id": input_id})

    def run_inputs_by_employee(self, *, tenant_id: str, run_id: str) -> dict[str, list[OneOffInput]]:
        grouped: dict[str, list[OneOffInput]] = {}
        rows = fetch_all(self.connection, "SELECT id, employee_id, component_code, qty, amount FROM payroll.run_inputs WHERE tenant_id = %s AND run_id = %s ORDER BY created_at, id",
                         (tenant_id, run_id))
        for row in rows:
            grouped.setdefault(row["employee_id"], []).append(
                OneOffInput(component_code=row["component_code"], qty=row["qty"], amount=row["amount"], source_kind="input", source_id=row["id"]))
        return grouped

    # -- advances -----------------------------------------------------------------------------
    def list_advances(self, *, tenant_id: str, status: str | None = None) -> list[dict[str, Any]]:
        clauses, params = ["a.tenant_id = %s"], [tenant_id]
        if status:
            clauses.append("a.status = %s")
            params.append(status)
        return jsonable(fetch_all(self.connection, _ADVANCE_SELECT + " WHERE " + " AND ".join(clauses) + " ORDER BY a.deduct_period DESC, a.full_name", params))

    def _advance(self, tenant_id: str, advance_id: str, *, lock: bool = False) -> dict[str, Any] | None:
        sql = "SELECT * FROM payroll.advances WHERE tenant_id = %s AND id = %s" + (" FOR UPDATE" if lock else "")
        return fetch_one(self.connection, sql, (tenant_id, advance_id))

    def _advance_view(self, tenant_id: str, advance_id: str) -> dict[str, Any]:
        return jsonable(fetch_one(self.connection, _ADVANCE_SELECT + " WHERE a.tenant_id = %s AND a.id = %s", (tenant_id, advance_id)))

    def create_advance(self, *, tenant_id: str, actor_id: str, employee_id: str, amount: Decimal, requested_on: datetime.date,
                       deduct_period: datetime.date, note: str | None = None) -> Result[dict[str, Any]]:
        problem = _money_problem(amount, "amount", "montant") or _period_problem(deduct_period)
        if problem is not None:
            return problem
        employee = self._employee(tenant_id, deduct_period, employee_id)
        if employee is None:
            return self._no_contract(deduct_period)
        advance_id = str(ULID())
        self.connection.execute(
            "INSERT INTO payroll.advances (id, tenant_id, employee_id, employee_no, full_name, amount, requested_on, deduct_period, note, created_by) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (advance_id, tenant_id, employee_id, employee["employee_no"], employee["full_name"], amount, requested_on, deduct_period, note, actor_id),
        )
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="advance.created", entity_type="advance", entity_id=advance_id,
                     payload=jsonable({"employee_id": employee_id, "amount": amount, "deduct_period": deduct_period}))
        return Ok(self._advance_view(tenant_id, advance_id))

    def update_advance(self, *, tenant_id: str, actor_id: str, advance_id: str, changes: dict[str, Any]) -> Result[dict[str, Any]]:
        current = self._advance(tenant_id, advance_id, lock=True)
        if current is None:
            return Err("NOT_FOUND", "advance not found", "avance introuvable")
        if current["status"] == "cancelled":
            return _invalid("a cancelled advance cannot change", "une avance annulée ne peut plus changer")
        unknown = sorted(set(changes) - {"amount", "requested_on", "deduct_period", "note"})
        if unknown:
            return _invalid(f"unknown fields: {', '.join(unknown)}", f"champs inconnus : {', '.join(unknown)}")
        released = self._release(current["deducted_payslip_id"])
        if released is not None:
            return released
        merged = {key: current[key] for key in ("amount", "requested_on", "deduct_period", "note")} | changes
        problem = _money_problem(merged["amount"], "amount", "montant") or _period_problem(merged["deduct_period"])
        if problem is not None:
            return problem
        self.connection.execute("UPDATE payroll.advances SET amount = %s, requested_on = %s, deduct_period = %s, note = %s WHERE id = %s",
                                (merged["amount"], merged["requested_on"], merged["deduct_period"], merged["note"], advance_id))
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="advance.updated", entity_type="advance",
                     entity_id=advance_id, payload={"changes": jsonable(changes)})
        return Ok(self._advance_view(tenant_id, advance_id))

    def approve_advance(self, *, tenant_id: str, actor_id: str, advance_id: str) -> Result[dict[str, Any]]:
        current = self._advance(tenant_id, advance_id, lock=True)
        if current is None:
            return Err("NOT_FOUND", "advance not found", "avance introuvable")
        if current["status"] != "requested":
            return _invalid("only a requested advance can be approved", "seule une avance demandée peut être approuvée")
        self.connection.execute("UPDATE payroll.advances SET status = 'approved', approved_by = %s, approved_at = NOW() WHERE id = %s", (actor_id, advance_id))
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="advance.approved", entity_type="advance",
                     entity_id=advance_id, payload={"from_status": "requested", "to_status": "approved"})
        return Ok(self._advance_view(tenant_id, advance_id))

    def cancel_advance(self, *, tenant_id: str, actor_id: str, advance_id: str) -> Result[dict[str, Any]]:
        current = self._advance(tenant_id, advance_id, lock=True)
        if current is None:
            return Err("NOT_FOUND", "advance not found", "avance introuvable")
        if current["status"] == "cancelled":
            return _invalid("this advance is already cancelled", "cette avance est déjà annulée")
        released = self._release(current["deducted_payslip_id"])
        if released is not None:
            return released
        self.connection.execute("UPDATE payroll.advances SET status = 'cancelled', deducted_payslip_id = NULL WHERE id = %s", (advance_id,))
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="advance.cancelled", entity_type="advance",
                     entity_id=advance_id, payload={"from_status": current["status"], "to_status": "cancelled"})
        return Ok(self._advance_view(tenant_id, advance_id))

    # -- loans --------------------------------------------------------------------------------
    def list_loans(self, *, tenant_id: str, status: str | None = None, loan_id: str | None = None) -> list[dict[str, Any]]:
        clauses, params = ["tenant_id = %s"], [tenant_id]
        if status:
            clauses.append("status = %s")
            params.append(status)
        if loan_id:
            clauses.append("id = %s")
            params.append(loan_id)
        loans = fetch_all(self.connection, f"SELECT {_LOAN_COLUMNS} FROM payroll.loans WHERE {' AND '.join(clauses)} ORDER BY first_period DESC, full_name", params)
        instalments = fetch_all(
            self.connection,
            """
            SELECT i.id, i.loan_id, i.seq, i.period, i.amount, r.id AS run_id, r.status AS run_status
            FROM payroll.loan_instalments i
            JOIN payroll.loans l ON l.id = i.loan_id
            LEFT JOIN payroll.payslips p ON p.id = i.payslip_id
            LEFT JOIN payroll.runs r ON r.id = p.run_id
            WHERE l.tenant_id = %s
            ORDER BY i.loan_id, i.seq
            """,
            (tenant_id,),
        )
        by_loan: dict[str, list[dict[str, Any]]] = {}
        for item in instalments:
            item["deducted"] = item["run_status"] in ("approved", "paid")
            by_loan.setdefault(item["loan_id"], []).append(item)
        for loan in loans:
            loan["instalments"] = by_loan.get(loan["id"], [])
            loan["remaining"] = (sum((item["amount"] for item in loan["instalments"] if not item["deducted"]), Decimal(0))
                                 if loan["status"] == "active" else Decimal(0))
        return jsonable(loans)

    def _loan(self, tenant_id: str, loan_id: str) -> dict[str, Any] | None:
        return fetch_one(self.connection, f"SELECT {_LOAN_COLUMNS} FROM payroll.loans WHERE tenant_id = %s AND id = %s FOR UPDATE", (tenant_id, loan_id))

    def _schedule(self, tenant_id: str, loan_id: str, principal: Decimal, count: int, first_period: datetime.date) -> None:
        for item in instalment_schedule(principal, count, first_period):
            self.connection.execute("INSERT INTO payroll.loan_instalments (id, tenant_id, loan_id, seq, period, amount) VALUES (%s, %s, %s, %s, %s, %s)",
                                    (str(ULID()), tenant_id, loan_id, item.seq, item.period, item.amount))

    @staticmethod
    def _loan_problem(principal: Decimal, count: int, first_period: datetime.date) -> Err | None:
        problem = _money_problem(principal, "principal", "capital") or _period_problem(first_period)
        if problem is not None:
            return problem
        if count < 1 or principal < count:
            return _invalid("a loan has at least one instalment of at least one franc", "un prêt a au moins une échéance d'au moins un franc")
        return None

    def create_loan(self, *, tenant_id: str, actor_id: str, employee_id: str, principal: Decimal, instalment_count: int,
                    first_period: datetime.date, note: str | None = None) -> Result[dict[str, Any]]:
        problem = self._loan_problem(principal, instalment_count, first_period)
        if problem is not None:
            return problem
        employee = self._employee(tenant_id, first_period, employee_id)
        if employee is None:
            return self._no_contract(first_period)
        loan_id = str(ULID())
        self.connection.execute(
            "INSERT INTO payroll.loans (id, tenant_id, employee_id, employee_no, full_name, principal, instalment_count, first_period, note, created_by) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (loan_id, tenant_id, employee_id, employee["employee_no"], employee["full_name"], principal, instalment_count, first_period, note, actor_id),
        )
        self._schedule(tenant_id, loan_id, principal, instalment_count, first_period)
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="loan.created", entity_type="loan", entity_id=loan_id,
                     payload=jsonable({"employee_id": employee_id, "principal": principal, "instalment_count": instalment_count, "first_period": first_period}))
        return Ok(self.list_loans(tenant_id=tenant_id, loan_id=loan_id)[0])

    def _release_instalments(self, loan_id: str) -> Err | None:
        taken = fetch_all(self.connection, "SELECT r.id, r.status FROM payroll.loan_instalments i JOIN payroll.payslips p ON p.id = i.payslip_id "
                                           "JOIN payroll.runs r ON r.id = p.run_id WHERE i.loan_id = %s", (loan_id,))
        if any(run["status"] in ("approved", "paid") for run in taken):
            return Err("RUN_LOCKED", "instalments were already deducted; cancel the loan and open a new one for the balance",
                       "des échéances ont déjà été retenues ; annulez le prêt et ouvrez-en un nouveau pour le solde")
        for run in taken:
            invalidate(self.connection, run["id"])
        return None

    def update_loan(self, *, tenant_id: str, actor_id: str, loan_id: str, changes: dict[str, Any]) -> Result[dict[str, Any]]:
        current = self._loan(tenant_id, loan_id)
        if current is None:
            return Err("NOT_FOUND", "loan not found", "prêt introuvable")
        if current["status"] == "cancelled":
            return _invalid("a cancelled loan cannot change", "un prêt annulé ne peut plus changer")
        unknown = sorted(set(changes) - {"principal", "instalment_count", "first_period", "note"})
        if unknown:
            return _invalid(f"unknown fields: {', '.join(unknown)}", f"champs inconnus : {', '.join(unknown)}")
        merged = {key: current[key] for key in ("principal", "instalment_count", "first_period", "note")} | changes
        problem = self._loan_problem(merged["principal"], int(merged["instalment_count"]), merged["first_period"])
        if problem is not None:
            return problem
        released = self._release_instalments(loan_id)
        if released is not None:
            return released
        self.connection.execute("DELETE FROM payroll.loan_instalments WHERE loan_id = %s", (loan_id,))
        self.connection.execute("UPDATE payroll.loans SET principal = %s, instalment_count = %s, first_period = %s, note = %s WHERE id = %s",
                                (merged["principal"], merged["instalment_count"], merged["first_period"], merged["note"], loan_id))
        self._schedule(tenant_id, loan_id, merged["principal"], int(merged["instalment_count"]), merged["first_period"])
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="loan.updated", entity_type="loan", entity_id=loan_id,
                     payload={"changes": jsonable(changes)})
        return Ok(self.list_loans(tenant_id=tenant_id, loan_id=loan_id)[0])

    def cancel_loan(self, *, tenant_id: str, actor_id: str, loan_id: str) -> Result[dict[str, Any]]:
        current = self._loan(tenant_id, loan_id)
        if current is None:
            return Err("NOT_FOUND", "loan not found", "prêt introuvable")
        if current["status"] == "cancelled":
            return _invalid("this loan is already cancelled", "ce prêt est déjà annulé")
        calculated = fetch_all(self.connection, "SELECT DISTINCT r.id FROM payroll.loan_instalments i JOIN payroll.payslips p ON p.id = i.payslip_id "
                                                "JOIN payroll.runs r ON r.id = p.run_id WHERE i.loan_id = %s AND r.status = 'calculated'", (loan_id,))
        for run in calculated:
            invalidate(self.connection, run["id"])
        # instalments an approved run deducted stay as history; the open ones go
        self.connection.execute("DELETE FROM payroll.loan_instalments WHERE loan_id = %s AND payslip_id IS NULL", (loan_id,))
        self.connection.execute("UPDATE payroll.loans SET status = 'cancelled' WHERE id = %s", (loan_id,))
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="loan.cancelled", entity_type="loan", entity_id=loan_id,
                     payload={"from_status": "active", "to_status": "cancelled"})
        return Ok(self.list_loans(tenant_id=tenant_id, loan_id=loan_id)[0])

    # -- what the engine is offered ---------------------------------------------------------------
    def due_deductions(self, *, tenant_id: str, period: datetime.date, employee_ids: list[str],
                       settle_ids: set[str]) -> dict[str, list[OneOffInput]]:
        if not employee_ids:
            return {}
        settle = sorted(settle_ids)
        grouped: dict[str, list[OneOffInput]] = {}

        def add(employee_id: str, item: OneOffInput) -> None:
            grouped.setdefault(employee_id, []).append(item)

        carried = fetch_all(
            self.connection,
            """
            SELECT cf.id, cf.employee_id, cf.component_code, cf.amount
            FROM payroll.carry_forwards cf
            JOIN payroll.payslips p ON p.id = cf.source_payslip_id
            JOIN payroll.runs r ON r.id = p.run_id
            WHERE cf.tenant_id = %s AND cf.consumed_by_payslip_id IS NULL AND r.status IN ('approved', 'paid')
              AND cf.employee_id = ANY(%s::text[])
            ORDER BY cf.created_at, cf.id
            """,
            (tenant_id, employee_ids),
        )
        for row in carried:
            add(row["employee_id"], OneOffInput(row["component_code"], amount=row["amount"], source_kind="carry_forward", source_id=row["id"]))
        instalments = fetch_all(
            self.connection,
            """
            SELECT i.id, l.employee_id, i.amount
            FROM payroll.loan_instalments i JOIN payroll.loans l ON l.id = i.loan_id
            WHERE l.tenant_id = %s AND l.status = 'active' AND i.payslip_id IS NULL AND l.employee_id = ANY(%s::text[])
              AND (i.period <= %s OR l.employee_id = ANY(%s::text[]))
            ORDER BY i.period, i.seq
            """,
            (tenant_id, employee_ids, period, settle),
        )
        for row in instalments:
            add(row["employee_id"], OneOffInput(LOAN, amount=row["amount"], source_kind="loan_instalment", source_id=row["id"]))
        advances = fetch_all(
            self.connection,
            """
            SELECT id, employee_id, amount FROM payroll.advances
            WHERE tenant_id = %s AND status = 'approved' AND deducted_payslip_id IS NULL AND employee_id = ANY(%s::text[])
              AND (deduct_period <= %s OR employee_id = ANY(%s::text[]))
            ORDER BY deduct_period, created_at
            """,
            (tenant_id, employee_ids, period, settle),
        )
        for row in advances:
            add(row["employee_id"], OneOffInput(ADVANCE, amount=row["amount"], source_kind="advance", source_id=row["id"]))
        return grouped
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest modules/payroll/api/test_input_service_integration.py core/test_error_translations.py -q`
Expected: `11 passed`, no skips.

- [ ] **Step 6: Commit**

```bash
git add backend/modules/payroll/migrations/0003_payroll_advances_loans.sql backend/modules/payroll/api/input_service.py backend/modules/payroll/api/test_input_service_integration.py
git commit -m "feat(payroll): monthly inputs, salary advances and loans

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Calculating a run

**Files:**
- Modify: `backend/modules/payroll/api/run_service.py` (add `calculate` and its helpers)
- Test: `backend/modules/payroll/api/test_calculate_integration.py`, `backend/modules/payroll/api/test_hr_contract_integration.py`

**Interfaces:**
- Consumes: `calculate_payslip` (3a), `employee_input`, `presence_input` (Task 1), `InputService.run_inputs_by_employee / due_deductions` (Task 5), `reference_salary`, `years_of_service` (3a Task 8), `monthly_equivalent`, `period_end` (3a Task 4).
- Produces: `RunService.calculate(*, tenant_id, actor_id, run_id) -> Result[dict]` — refuses `PRESENCE_NOT_CLOSED` (regular runs), `RULESET_MISSING`, `RUN_LOCKED`, `RUN_EMPTY` (off-cycle without employee); deletes and rewrites every payslip of the run (idempotent); regular runs leave out employees settled in another non-reversed off-cycle run of the month; off-cycle runs pay salary only to employees with a final settlement and otherwise only their typed inputs; each payslip stores `snapshot = {employee, presence, inputs, settlement, payment_methods, rule_set}`; carried amounts go to `payroll.carry_forwards`; the advances / instalments / carried amounts offered to the engine are marked as taken by the payslip; `calculated_at = clock_timestamp()`; audit `payroll_run.calculated`.
- Helpers used by Task 7: `_settlements(tenant_id, run_id) -> dict[str, dict]`, `_settled_elsewhere(tenant_id, period, run_id) -> set[str]`, `_settlement_input(tenant_id, rules, employee, row, period) -> SettlementInput | None`.

- [ ] **Step 1: Write the failing tests**

Create `backend/modules/payroll/api/test_calculate_integration.py`:

```python
"""Calculating runs against a real database, with hr replaced by contract-shaped fakes.

Rules are the synthetic test set (plan 3a, domain/synthetic.py); the first employee reproduces the
golden full-month payslip, so its net is the hand-computed 376 035.
"""
from __future__ import annotations

import datetime
from decimal import Decimal

import pytest

from core.domain.result import Err, Ok
from modules.payroll.api.input_service import InputService
from modules.payroll.api.run_service import RunService
from modules.payroll.api.testing_support import (
    FakePresence, FakeSnapshots, make_user, set_country, snapshot, store_rule_set,
)

TENANT = "payroll-calculate-test"
SEPT = datetime.date(2031, 9, 1)
OCT = datetime.date(2031, 10, 1)
D = Decimal

EMPLOYEES = [
    snapshot("E1", employee_no="M-001", full_name="Awa Traoré", hire_date=datetime.date(2026, 9, 1), tax_dependants=2,
             components=({"component_code": "HOUSING", "amount": D(30000), "rate": None},
                         {"component_code": "TRANSPORT", "amount": D(10000), "rate": None})),
    snapshot("E3", employee_no="M-003", full_name="Oumar Diarra", base_salary=D(100000), hire_date=datetime.date(2031, 1, 1)),
]
SUMMARIES = {"E1": {"scheduled_days": 22, "worked_days": 22, "ot_minutes_day": 600},
             "E3": {"scheduled_days": 22, "worked_days": 22}}


@pytest.fixture
def world(db):
    actor = make_user(db, TENANT)
    set_country(db, tenant_id=TENANT, actor_id=actor)
    rule_set_id = store_rule_set(db, tenant_id=TENANT, actor_id=actor, valid_from=datetime.date(2031, 1, 1))
    snapshots, presence = FakeSnapshots(EMPLOYEES), FakePresence(SUMMARIES, closed=True)
    runs = RunService(db, snapshots=snapshots, presence=presence)
    inputs = InputService(db, snapshots=snapshots)
    return {"db": db, "actor": actor, "rule_set_id": rule_set_id, "runs": runs, "inputs": inputs, "presence": presence}


def _regular(world, period=SEPT):
    return world["runs"].create_run(tenant_id=TENANT, actor_id=world["actor"], period=period, run_type="regular").value["id"]


def _approved_advance(world, employee_id, amount, period=SEPT):
    advance = world["inputs"].create_advance(tenant_id=TENANT, actor_id=world["actor"], employee_id=employee_id, amount=D(amount),
                                             requested_on=period, deduct_period=period).value
    world["inputs"].approve_advance(tenant_id=TENANT, actor_id=world["actor"], advance_id=advance["id"])
    return advance["id"]


def _calculate(world, run_id):
    return world["runs"].calculate(tenant_id=TENANT, actor_id=world["actor"], run_id=run_id)


def _payslip(world, run_id, employee_id):
    return world["db"].execute(
        "SELECT id, gross, net, deductions, warnings, rule_set_status, snapshot FROM payroll.payslips WHERE run_id = %s AND employee_id = %s",
        (run_id, employee_id)).fetchone()


def test_calculation_waits_for_the_presence_month_to_be_closed(world):
    world["presence"].closed = False
    refused = _calculate(world, _regular(world))
    assert isinstance(refused, Err) and refused.code == "PRESENCE_NOT_CLOSED" and "09/2031" in refused.message_fr


def test_no_rule_set_no_calculation(world):
    refused = _calculate(world, _regular(world, period=datetime.date(2030, 12, 1)))
    assert isinstance(refused, Err) and refused.code == "RULESET_MISSING"


def test_one_payslip_per_employee_with_lines_and_the_inputs_it_used(world):
    advance_id = _approved_advance(world, "E1", 50000)
    run_id = _regular(world)
    calculated = _calculate(world, run_id)
    assert isinstance(calculated, Ok)
    assert (calculated.value["status"], calculated.value["payslip_count"], calculated.value["calculated_by"]) == ("calculated", 2, world["actor"])
    payslip_id, gross, net, deductions, warnings, rule_set_status, document = _payslip(world, run_id, "E1")
    assert (gross, net, deductions, warnings, rule_set_status) == (D(497500), D(376035), D(50000), [], "confirmed")
    assert document["employee"]["employee_no"] == "M-001" and document["presence"]["ot_minutes_day"] == 600
    assert document["rule_set"]["status"] == "confirmed" and document["payment_methods"][0]["bank_name"] == "BDM"
    assert [item["source_kind"] for item in document["inputs"]] == ["advance"]
    lines = world["db"].execute("SELECT count(*) FROM payroll.payslip_lines WHERE payslip_id = %s", (payslip_id,)).fetchone()[0]
    assert lines > 5
    taken = world["db"].execute("SELECT deducted_payslip_id FROM payroll.advances WHERE id = %s", (advance_id,)).fetchone()[0]
    assert taken == payslip_id


def test_calculating_again_gives_the_same_payslips(world):
    advance_id = _approved_advance(world, "E1", 50000)
    run_id = _regular(world)
    _calculate(world, run_id)
    _calculate(world, run_id)
    assert world["db"].execute("SELECT count(*) FROM payroll.payslips WHERE run_id = %s", (run_id,)).fetchone()[0] == 2
    payslip_id, _, net, *_ = _payslip(world, run_id, "E1")
    assert net == D(376035)
    assert world["db"].execute("SELECT deducted_payslip_id FROM payroll.advances WHERE id = %s", (advance_id,)).fetchone()[0] == payslip_id


def test_a_draft_rule_set_can_be_calculated_and_the_payslip_says_so(world):
    world["db"].execute("UPDATE payroll.rule_sets SET status = 'draft', confirmed_by = NULL, confirmed_at = NULL WHERE id = %s", (world["rule_set_id"],))
    run_id = _regular(world)
    assert isinstance(_calculate(world, run_id), Ok)
    assert _payslip(world, run_id, "E1")[5] == "draft"


def test_what_the_net_cannot_cover_is_carried_to_a_later_run_once_approved(world):
    _approved_advance(world, "E3", 120000)
    september = _regular(world)
    _calculate(world, september)
    payslip_id, _, net, deductions, warnings, *_ = _payslip(world, september, "E3")
    assert (net, deductions, warnings) == (D(0), D(93000), ["NET_NEGATIVE"])
    carry = world["db"].execute("SELECT id, component_code, amount, source_kind FROM payroll.carry_forwards WHERE source_payslip_id = %s", (payslip_id,)).fetchone()
    assert carry[1:] == ("ADVANCE", D(27000), "advance")

    october = _regular(world, period=OCT)
    _calculate(world, october)
    assert _payslip(world, october, "E3")[3] == D(0)  # September is not approved yet: nothing is owed

    world["db"].execute("UPDATE payroll.runs SET status = 'approved', approved_by = 'someone', approved_at = NOW() WHERE id = %s", (september,))
    _calculate(world, october)
    october_payslip, _, _, deductions, *_ = _payslip(world, october, "E3")
    assert deductions == D(27000)
    assert world["db"].execute("SELECT consumed_by_payslip_id FROM payroll.carry_forwards WHERE id = %s", (carry[0],)).fetchone()[0] == october_payslip


def test_an_off_cycle_run_pays_only_its_typed_inputs(world):
    run_id = world["runs"].create_run(tenant_id=TENANT, actor_id=world["actor"], period=SEPT, run_type="off_cycle", employee_ids=["E1"]).value["id"]
    world["inputs"].add_run_input(tenant_id=TENANT, actor_id=world["actor"], run_id=run_id, employee_id="E1", component_code="BONUS", amount=D(25000))
    assert isinstance(_calculate(world, run_id), Ok)
    rows = world["db"].execute("SELECT employee_id, gross, net FROM payroll.payslips WHERE run_id = %s", (run_id,)).fetchall()
    assert rows == [("E1", D(25000), D(23250))]


def test_an_approved_run_is_not_recalculated(world):
    run_id = _regular(world)
    _calculate(world, run_id)
    world["db"].execute("UPDATE payroll.runs SET status = 'approved' WHERE id = %s", (run_id,))
    assert _calculate(world, run_id).code == "RUN_LOCKED"
```

Create `backend/modules/payroll/api/test_hr_contract_integration.py`:

```python
"""Pins the hr services payroll depends on to the cross-phase contract's names and shapes."""
from __future__ import annotations

import datetime

from modules.hr.api.payroll_snapshot_service import PayrollSnapshotService
from modules.hr.api.presence_service import PresenceService

EMPTY_TENANT = "payroll-contract-empty-tenant"
PERIOD = datetime.date(2031, 9, 1)


def test_the_snapshot_service_answers_with_the_contract_keywords(db):
    assert PayrollSnapshotService(db).employees_for_period(tenant_id=EMPTY_TENANT, period=PERIOD, employee_ids=None) == []


def test_the_presence_service_answers_with_the_contract_keywords(db):
    presence = PresenceService(db)
    assert presence.month_summary(tenant_id=EMPTY_TENANT, period=PERIOD, employee_ids=[]) == []
    assert presence.is_month_closed(tenant_id=EMPTY_TENANT, period=PERIOD) in (True, False)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python -m pytest modules/payroll/api/test_calculate_integration.py modules/payroll/api/test_hr_contract_integration.py -q`
Expected: the calculate tests FAIL — `AttributeError: 'RunService' object has no attribute 'calculate'`; the contract tests PASS (phases 1–2 merged). If a contract test fails, stop: phase 1/2 did not ship the contract and must be fixed first.

- [ ] **Step 3: Add `calculate` to `RunService`**

In `backend/modules/payroll/api/run_service.py`, extend the imports:

```python
from dataclasses import asdict

from psycopg.types.json import Jsonb

from modules.payroll.api.input_service import InputService
from modules.payroll.domain.earnings import monthly_equivalent, period_end
from modules.payroll.domain.engine import PayslipResult, calculate_payslip
from modules.payroll.domain.inputs import EmployeeInput, OneOffInput, SettlementInput
from modules.payroll.domain.rules import RuleSet
from modules.payroll.domain.settlement import reference_salary, years_of_service
from modules.payroll.domain.snapshot_mapping import employee_input, presence_input
```

and add these methods to the `RunService` class:

```python
    # -- calculation -----------------------------------------------------------------------------
    def calculate(self, *, tenant_id: str, actor_id: str, run_id: str) -> Result[dict[str, Any]]:
        run = lock_run(self.connection, tenant_id, run_id)
        if run is None:
            return not_found()
        if run["status"] not in EDITABLE:
            return locked(run["status"])
        period = run["period"]
        regular = run["run_type"] == "regular"
        if regular and not self.presence.is_month_closed(tenant_id=tenant_id, period=period):
            return Err("PRESENCE_NOT_CLOSED", f"presence for {period:%Y-%m} is not closed; close the month in HR first",
                       f"la présence de {period:%m/%Y} n'est pas clôturée ; clôturez d'abord le mois dans RH")
        rule_sets = RuleSetService(self.connection)
        in_force = rule_sets.in_force(tenant_id=tenant_id, period=period)
        if isinstance(in_force, Err):
            return in_force
        rules = rule_sets.load(tenant_id=tenant_id, rule_set_id=in_force.value["id"])

        settlements = self._settlements(tenant_id, run_id)
        scope = None if regular else sorted(set(run["employee_ids"] or []) | set(settlements))
        if scope == []:
            return Err("RUN_EMPTY", "choose at least one employee for an off-cycle run", "choisissez au moins un employé pour une paie hors cycle")
        snapshots = self.snapshots.employees_for_period(tenant_id=tenant_id, period=period, employee_ids=scope)
        if regular:
            settled = self._settled_elsewhere(tenant_id, period, run_id)
            snapshots = [item for item in snapshots if item["employee_id"] not in settled]
        ids = [item["employee_id"] for item in snapshots]
        summaries = ({row["employee_id"]: row for row in self.presence.month_summary(tenant_id=tenant_id, period=period, employee_ids=ids)}
                     if ids else {})

        self.connection.execute("DELETE FROM payroll.payslips WHERE run_id = %s", (run_id,))
        inputs = InputService(self.connection, snapshots=self.snapshots)
        typed = inputs.run_inputs_by_employee(tenant_id=tenant_id, run_id=run_id)
        salaried = set(ids) if regular else set(settlements) & set(ids)
        deductions = inputs.due_deductions(tenant_id=tenant_id, period=period, employee_ids=sorted(salaried), settle_ids=set(settlements))

        written = 0
        for item in snapshots:
            employee_id = item["employee_id"]
            one_offs = typed.get(employee_id, []) + deductions.get(employee_id, [])
            include_salary = employee_id in salaried
            if not include_salary and not one_offs:
                continue
            employee = employee_input(item)
            settlement = self._settlement_input(tenant_id, rules, employee, settlements.get(employee_id), period)
            result = calculate_payslip(employee=employee, presence=presence_input(summaries.get(employee_id)), rules=rules,
                                       period=period, inputs=one_offs, settlement=settlement, include_salary=include_salary)
            if isinstance(result, Err):
                return Err(result.code, f"{item['full_name']}: {result.message}", f"{item['full_name']} : {result.message_fr}")
            self._write_payslip(tenant_id, run_id, rules, item, summaries.get(employee_id), one_offs, settlement, result.value)
            written += 1

        self.connection.execute(
            "UPDATE payroll.runs SET status = 'calculated', rule_set_id = %s, calculated_by = %s, calculated_at = clock_timestamp() WHERE id = %s",
            (rules.id, actor_id, run_id),
        )
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="payroll_run.calculated",
                     entity_type="payroll_run", entity_id=run_id,
                     payload={"from_status": run["status"], "to_status": "calculated", "rule_set_id": rules.id,
                              "rule_set_status": rules.status, "payslips": written})
        return Ok(self.get_run(tenant_id=tenant_id, run_id=run_id))

    def _write_payslip(self, tenant_id: str, run_id: str, rules: RuleSet, employee: dict[str, Any], summary: dict[str, Any] | None,
                       one_offs: list[OneOffInput], settlement: SettlementInput | None, result: PayslipResult) -> str:
        payslip_id = str(ULID())
        totals = result.totals
        document = {
            "employee": jsonable({key: value for key, value in employee.items() if key != "payment_methods"}),
            "presence": jsonable(summary or {}),
            "inputs": [jsonable(asdict(item)) for item in one_offs],
            "settlement": None if settlement is None else jsonable(asdict(settlement)),
            "payment_methods": jsonable(employee.get("payment_methods") or []),
            "rule_set": {"id": rules.id, "status": rules.status, "valid_from": rules.valid_from.isoformat()},
        }
        self.connection.execute(
            """
            INSERT INTO payroll.payslips (id, tenant_id, run_id, employee_id, employee_no, full_name, department_id, rule_set_id,
                rule_set_status, snapshot, gross, contributable, taxable, employee_contrib, employer_contrib, employer_charges,
                its, deductions, net, employer_cost, warnings)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (payslip_id, tenant_id, run_id, employee["employee_id"], employee["employee_no"], employee["full_name"],
             employee.get("department_id"), rules.id, rules.status, Jsonb(document), totals.gross, totals.contributable,
             totals.taxable, totals.employee_contrib, totals.employer_contrib, totals.employer_charges, totals.tax,
             totals.deductions, totals.net, totals.employer_cost, Jsonb(list(result.warnings))),
        )
        for number, line in enumerate(result.lines, start=1):
            self.connection.execute(
                """
                INSERT INTO payroll.payslip_lines (id, tenant_id, payslip_id, line_no, section, code, name_en, name_fr, base, qty,
                    rate, amount, taxable, contributable, declaration_code, source_kind, source_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (str(ULID()), tenant_id, payslip_id, number, line.section, line.code, line.name_en, line.name_fr, line.base,
                 line.qty, line.rate, line.amount, line.taxable, line.contributable, line.declaration_code, line.source_kind, line.source_id),
            )
        for carry in result.carry_forwards:
            self.connection.execute(
                "INSERT INTO payroll.carry_forwards (id, tenant_id, employee_id, component_code, amount, source_kind, source_id, source_payslip_id) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (str(ULID()), tenant_id, employee["employee_id"], carry.component_code, carry.amount, carry.source_kind, carry.source_id, payslip_id),
            )
        # Every advance / instalment / carried amount offered to the engine is settled by this payslip:
        # deducted in full, cut with the rest carried, or carried whole (the new carry row holds what is owed).
        marks = {"advance": "UPDATE payroll.advances SET deducted_payslip_id = %s WHERE id = %s",
                 "loan_instalment": "UPDATE payroll.loan_instalments SET payslip_id = %s WHERE id = %s",
                 "carry_forward": "UPDATE payroll.carry_forwards SET consumed_by_payslip_id = %s WHERE id = %s"}
        for item in one_offs:
            if item.source_kind in marks and item.source_id:
                self.connection.execute(marks[item.source_kind], (payslip_id, item.source_id))
        return payslip_id

    def _settlements(self, tenant_id: str, run_id: str) -> dict[str, dict[str, Any]]:
        rows = fetch_all(self.connection,
                         "SELECT id, employee_id, employee_no, full_name, unused_leave_days, notice_months FROM payroll.final_settlements "
                         "WHERE tenant_id = %s AND run_id = %s", (tenant_id, run_id))
        return {row["employee_id"]: row for row in rows}

    def _settled_elsewhere(self, tenant_id: str, period: datetime.date, run_id: str) -> set[str]:
        rows = self.connection.execute(
            """
            SELECT fs.employee_id FROM payroll.final_settlements fs JOIN payroll.runs r ON r.id = fs.run_id
            WHERE r.tenant_id = %s AND r.period = %s AND r.status <> 'reversed' AND r.id <> %s
            """,
            (tenant_id, period, run_id),
        ).fetchall()
        return {row[0] for row in rows}

    def _settlement_input(self, tenant_id: str, rules: RuleSet, employee: EmployeeInput, row: dict[str, Any] | None,
                          period: datetime.date) -> SettlementInput | None:
        if row is None:
            return None
        history = self.connection.execute(
            """
            SELECT p.gross FROM payroll.payslips p JOIN payroll.runs r ON r.id = p.run_id
            WHERE p.tenant_id = %s AND p.employee_id = %s AND r.run_type = 'regular' AND r.status IN ('approved', 'paid') AND r.period < %s
            ORDER BY r.period DESC LIMIT %s
            """,
            (tenant_id, employee.employee_id, period, rules.settlement_reference_months),
        ).fetchall()
        reference = reference_salary([gross for (gross,) in history], months=rules.settlement_reference_months,
                                     fallback=monthly_equivalent(employee, rules))
        end = employee.termination_date or period_end(period)
        return SettlementInput(reference_salary=reference, years_of_service=years_of_service(employee.hire_date, end),
                               unused_leave_days=row["unused_leave_days"], notice_months=row["notice_months"])
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest modules/payroll -q`
Expected: all pass, no skips (`test_calculate_integration.py` adds 8 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/modules/payroll/api/run_service.py backend/modules/payroll/api/test_calculate_integration.py backend/modules/payroll/api/test_hr_contract_integration.py
git commit -m "feat(payroll): calculate runs from hr snapshots, presence and inputs

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---
### Task 7: Final settlements on off-cycle runs

**Files:**
- Modify: `backend/modules/payroll/api/run_service.py` (add settlement methods)
- Test: `backend/modules/payroll/api/test_final_settlement_integration.py`

**Interfaces:**
- Consumes: `_settlements`, `_settled_elsewhere`, `_settlement_input` (Task 6), `invalidate`, `period_end`.
- Produces on `RunService`: `list_final_settlements(*, tenant_id, run_id) -> list[dict]`, `add_final_settlement(*, tenant_id, actor_id, run_id, employee_id, unused_leave_days=Decimal(0), notice_months=Decimal(0)) -> Result[dict]`, `update_final_settlement(*, tenant_id, actor_id, run_id, settlement_id, changes) -> Result[dict]`, `remove_final_settlement(*, tenant_id, actor_id, run_id, settlement_id) -> Result[dict]`.
- Error codes: `SETTLEMENT_INVALID`, `DUPLICATE_SETTLEMENT`, `NOT_FOUND`, `RUN_LOCKED`.

Spec: "Final settlement: off-cycle payslip with prorated salary, unused paid-leave indemnity, notice indemnity, severance (formula components from the rule set), certificate of work (printable)". hr's termination (phase 1) "flags the employee for a final settlement in the next payroll run"; the payroll officer adds the settlement to an off-cycle run of the **termination month** and types the two facts payroll cannot know: unused paid-leave days and months of notice not worked (hr exposes no leave balance in the contract). Reference salary and years of service are computed (Task 6).

- [ ] **Step 1: Write the failing tests**

Create `backend/modules/payroll/api/test_final_settlement_integration.py`:

```python
"""Final settlements: off-cycle only, only for someone leaving that month, never paid twice."""
from __future__ import annotations

import datetime
from decimal import Decimal

import pytest

from core.domain.result import Err, Ok
from modules.payroll.api.run_service import RunService
from modules.payroll.api.testing_support import (
    FakePresence, FakeSnapshots, insert_payslip, insert_run, make_user, set_country, snapshot, store_rule_set,
)

TENANT = "payroll-settlement-test"
SEPT = datetime.date(2031, 9, 1)
D = Decimal
EMPLOYEES = [
    snapshot("E1", employee_no="M-001", full_name="Awa Traoré"),
    snapshot("E9", employee_no="M-009", full_name="Seydou Coulibaly", base_salary=D(300000), hire_date=datetime.date(2019, 9, 15),
             termination_date=datetime.date(2031, 9, 15), termination_reason="resignation"),
]
SUMMARIES = {"E1": {"scheduled_days": 22, "worked_days": 22}, "E9": {"scheduled_days": 10, "worked_days": 10}}


@pytest.fixture
def world(db):
    actor = make_user(db, TENANT)
    set_country(db, tenant_id=TENANT, actor_id=actor)
    rule_set_id = store_rule_set(db, tenant_id=TENANT, actor_id=actor, valid_from=datetime.date(2019, 1, 1))
    runs = RunService(db, snapshots=FakeSnapshots(EMPLOYEES), presence=FakePresence(SUMMARIES))
    return {"db": db, "actor": actor, "rule_set_id": rule_set_id, "runs": runs}


def _run(world, run_type="off_cycle"):
    return world["runs"].create_run(tenant_id=TENANT, actor_id=world["actor"], period=SEPT, run_type=run_type).value["id"]


def _settle(world, run_id, employee_id="E9", leave=D(10), notice=D(1)):
    return world["runs"].add_final_settlement(tenant_id=TENANT, actor_id=world["actor"], run_id=run_id, employee_id=employee_id,
                                              unused_leave_days=leave, notice_months=notice)


def _payslip_employees(world, run_id):
    return sorted(row[0] for row in world["db"].execute("SELECT employee_id FROM payroll.payslips WHERE run_id = %s", (run_id,)).fetchall())


def test_a_final_settlement_goes_on_an_off_cycle_run(world):
    refused = _settle(world, _run(world, run_type="regular"))
    assert isinstance(refused, Err) and refused.code == "SETTLEMENT_INVALID" and refused.message_fr


def test_only_someone_leaving_that_month_can_be_settled(world):
    refused = _settle(world, _run(world), employee_id="E1")
    assert isinstance(refused, Err) and refused.code == "SETTLEMENT_INVALID" and "Awa Traoré" in refused.message


def test_the_settlement_payslip_pays_the_month_to_the_exit_date_and_the_indemnities(world):
    run_id = _run(world)
    settled = _settle(world, run_id)
    assert isinstance(settled, Ok) and settled.value["full_name"] == "Seydou Coulibaly"
    assert isinstance(world["runs"].calculate(tenant_id=TENANT, actor_id=world["actor"], run_id=run_id), Ok)
    gross, net, document = world["db"].execute(
        "SELECT gross, net, snapshot FROM payroll.payslips WHERE run_id = %s AND employee_id = 'E9'", (run_id,)).fetchone()
    # the golden final settlement of plan 3a Task 9: 12 years, 10 of 20 days, 10 leave days, 1 month notice
    assert (gross, net) == (D(1462500), D(1355280))
    assert document["settlement"] == {"reference_salary": 300000, "years_of_service": 12, "unused_leave_days": 10, "notice_months": 1}
    assert _payslip_employees(world, run_id) == ["E9"]


def test_the_regular_run_leaves_out_an_employee_settled_off_cycle(world):
    off_cycle = _run(world)
    _settle(world, off_cycle)
    regular = _run(world, run_type="regular")
    world["runs"].calculate(tenant_id=TENANT, actor_id=world["actor"], run_id=regular)
    assert _payslip_employees(world, regular) == ["E1"]
    world["db"].execute("UPDATE payroll.runs SET status = 'reversed' WHERE id = %s", (off_cycle,))
    world["runs"].calculate(tenant_id=TENANT, actor_id=world["actor"], run_id=regular)
    assert _payslip_employees(world, regular) == ["E1", "E9"]


def test_the_reference_salary_averages_the_approved_regular_months(world):
    for month in (7, 8):
        history = insert_run(world["db"], tenant_id=TENANT, actor_id=world["actor"], period=datetime.date(2031, month, 1),
                             status="approved", rule_set_id=world["rule_set_id"])
        insert_payslip(world["db"], tenant_id=TENANT, run_id=history, employee_id="E9", rule_set_id=world["rule_set_id"], gross=D(330000))
    run_id = _run(world)
    _settle(world, run_id)
    world["runs"].calculate(tenant_id=TENANT, actor_id=world["actor"], run_id=run_id)
    document = world["db"].execute("SELECT snapshot FROM payroll.payslips WHERE run_id = %s", (run_id,)).fetchone()[0]
    assert document["settlement"]["reference_salary"] == 330000


def test_changing_or_removing_a_settlement_sends_a_calculated_run_back_to_draft(world):
    run_id = _run(world)
    settlement_id = _settle(world, run_id).value["id"]
    world["runs"].calculate(tenant_id=TENANT, actor_id=world["actor"], run_id=run_id)
    updated = world["runs"].update_final_settlement(tenant_id=TENANT, actor_id=world["actor"], run_id=run_id,
                                                    settlement_id=settlement_id, changes={"notice_months": D(2)})
    assert isinstance(updated, Ok) and updated.value["notice_months"] == 2
    assert world["runs"].get_run(tenant_id=TENANT, run_id=run_id)["status"] == "draft"
    assert isinstance(world["runs"].remove_final_settlement(tenant_id=TENANT, actor_id=world["actor"], run_id=run_id, settlement_id=settlement_id), Ok)
    assert world["runs"].list_final_settlements(tenant_id=TENANT, run_id=run_id) == []


def test_one_settlement_per_employee_and_run(world):
    run_id = _run(world)
    _settle(world, run_id)
    again = _settle(world, run_id)
    assert isinstance(again, Err) and again.code == "DUPLICATE_SETTLEMENT"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python -m pytest modules/payroll/api/test_final_settlement_integration.py -q`
Expected: FAIL — `AttributeError: 'RunService' object has no attribute 'add_final_settlement'`.

- [ ] **Step 3: Add the settlement methods to `RunService`**

Add `from decimal import Decimal` to the imports of `run_service.py`, then add to the class:

```python
    # -- final settlements ---------------------------------------------------------------------
    _SETTLEMENT_COLUMNS = "id, run_id, employee_id, employee_no, full_name, unused_leave_days, notice_months, created_by, created_at"

    def list_final_settlements(self, *, tenant_id: str, run_id: str) -> list[dict[str, Any]]:
        return jsonable(fetch_all(self.connection,
                                  f"SELECT {self._SETTLEMENT_COLUMNS} FROM payroll.final_settlements WHERE tenant_id = %s AND run_id = %s ORDER BY full_name",
                                  (tenant_id, run_id)))

    def _settlement(self, tenant_id: str, run_id: str, settlement_id: str) -> dict[str, Any] | None:
        return fetch_one(self.connection,
                         f"SELECT {self._SETTLEMENT_COLUMNS} FROM payroll.final_settlements WHERE tenant_id = %s AND run_id = %s AND id = %s",
                         (tenant_id, run_id, settlement_id))

    @staticmethod
    def _settlement_problem(unused_leave_days: Decimal, notice_months: Decimal) -> Err | None:
        if unused_leave_days is None or notice_months is None or unused_leave_days < 0 or notice_months < 0:
            return Err("SETTLEMENT_INVALID", "leave days and notice months are zero or more",
                       "les jours de congé et les mois de préavis sont positifs ou nuls")
        return None

    def _open_off_cycle(self, tenant_id: str, run_id: str) -> Result[dict[str, Any]]:
        run = lock_run(self.connection, tenant_id, run_id)
        if run is None:
            return not_found()
        if run["status"] not in EDITABLE:
            return locked(run["status"])
        if run["run_type"] != "off_cycle":
            return Err("SETTLEMENT_INVALID", "a final settlement goes on an off-cycle run", "un solde de tout compte se fait sur une paie hors cycle")
        return Ok(run)

    def add_final_settlement(self, *, tenant_id: str, actor_id: str, run_id: str, employee_id: str,
                             unused_leave_days: Decimal = Decimal(0), notice_months: Decimal = Decimal(0)) -> Result[dict[str, Any]]:
        opened = self._open_off_cycle(tenant_id, run_id)
        if isinstance(opened, Err):
            return opened
        run = opened.value
        problem = self._settlement_problem(unused_leave_days, notice_months)
        if problem is not None:
            return problem
        period = run["period"]
        found = self.snapshots.employees_for_period(tenant_id=tenant_id, period=period, employee_ids=[employee_id])
        if not found:
            return Err("NOT_FOUND", f"this employee has no contract in {period:%Y-%m}", f"cet employé n'a pas de contrat en {period:%m/%Y}")
        employee = found[0]
        termination = employee.get("termination_date")
        if termination is None or not period <= termination <= period_end(period):
            return Err("SETTLEMENT_INVALID",
                       f"{employee['full_name']} has no exit date in {period:%Y-%m}; record the termination in HR first",
                       f"{employee['full_name']} n'a pas de date de sortie en {period:%m/%Y} ; enregistrez d'abord la sortie dans RH")
        settlement_id = str(ULID())
        try:
            with self.connection.transaction():
                self.connection.execute(
                    "INSERT INTO payroll.final_settlements (id, tenant_id, run_id, employee_id, employee_no, full_name, unused_leave_days, notice_months, created_by) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (settlement_id, tenant_id, run_id, employee_id, employee["employee_no"], employee["full_name"], unused_leave_days, notice_months, actor_id),
                )
        except psycopg.errors.UniqueViolation:
            return Err("DUPLICATE_SETTLEMENT", "this employee is already settled in this run", "cet employé a déjà un solde dans cette paie")
        self.connection.execute("UPDATE payroll.runs SET employee_ids = %s WHERE id = %s",
                                (sorted(set(run["employee_ids"] or []) | {employee_id}), run_id))
        invalidate(self.connection, run_id)
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="final_settlement.created",
                     entity_type="final_settlement", entity_id=settlement_id,
                     payload=jsonable({"run_id": run_id, "employee_id": employee_id, "unused_leave_days": unused_leave_days,
                                       "notice_months": notice_months, "termination_date": termination}))
        return Ok(jsonable(self._settlement(tenant_id, run_id, settlement_id)))

    def update_final_settlement(self, *, tenant_id: str, actor_id: str, run_id: str, settlement_id: str,
                                changes: dict[str, Any]) -> Result[dict[str, Any]]:
        opened = self._open_off_cycle(tenant_id, run_id)
        if isinstance(opened, Err):
            return opened
        current = self._settlement(tenant_id, run_id, settlement_id)
        if current is None:
            return Err("NOT_FOUND", "final settlement not found", "solde de tout compte introuvable")
        unknown = sorted(set(changes) - {"unused_leave_days", "notice_months"})
        if unknown:
            return Err("SETTLEMENT_INVALID", f"unknown fields: {', '.join(unknown)}", f"champs inconnus : {', '.join(unknown)}")
        merged = {key: current[key] for key in ("unused_leave_days", "notice_months")} | changes
        problem = self._settlement_problem(merged["unused_leave_days"], merged["notice_months"])
        if problem is not None:
            return problem
        self.connection.execute("UPDATE payroll.final_settlements SET unused_leave_days = %s, notice_months = %s WHERE id = %s",
                                (merged["unused_leave_days"], merged["notice_months"], settlement_id))
        invalidate(self.connection, run_id)
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="final_settlement.updated",
                     entity_type="final_settlement", entity_id=settlement_id, payload={"changes": jsonable(changes)})
        return Ok(jsonable(self._settlement(tenant_id, run_id, settlement_id)))

    def remove_final_settlement(self, *, tenant_id: str, actor_id: str, run_id: str, settlement_id: str) -> Result[dict[str, Any]]:
        opened = self._open_off_cycle(tenant_id, run_id)
        if isinstance(opened, Err):
            return opened
        current = self._settlement(tenant_id, run_id, settlement_id)
        if current is None:
            return Err("NOT_FOUND", "final settlement not found", "solde de tout compte introuvable")
        self.connection.execute("DELETE FROM payroll.final_settlements WHERE id = %s", (settlement_id,))
        invalidate(self.connection, run_id)
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="final_settlement.deleted",
                     entity_type="final_settlement", entity_id=settlement_id,
                     payload=jsonable({key: current[key] for key in ("run_id", "employee_id", "unused_leave_days", "notice_months")}))
        return Ok({"id": settlement_id})
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest modules/payroll/api/test_final_settlement_integration.py modules/payroll/api/test_calculate_integration.py -q`
Expected: all pass (7 + 8), no skips.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/payroll/api/run_service.py backend/modules/payroll/api/test_final_settlement_integration.py
git commit -m "feat(payroll): final settlements on off-cycle runs

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Approving and reversing runs, with outbox events

**Files:**
- Modify: `backend/modules/payroll/api/run_service.py` (add `approve`, `reverse`, `_publish`)
- Modify: `backend/modules/payroll/api/testing_support.py` (add `approved_run`)
- Modify: `backend/events/CATALOG.md`
- Test: `backend/modules/payroll/api/test_approval_integration.py`

**Interfaces:**
- Consumes: `core.events.outbox.publish_event`, `RuleSetService.in_force`, `run_state.invalidate`.
- Produces on `RunService`:
  - `approve(*, tenant_id, actor_id, run_id) -> Result[dict]` — `RUN_NOT_CALCULATED` (draft), `RUN_LOCKED` (approved/paid/reversed), `SAME_USER_APPROVAL`, `RULESET_NOT_CONFIRMED` (draft rule set, confirmed after the calculation, or another rule set now in force), `PRESENCE_NOT_CLOSED` (regular run, month reopened); publishes `payroll.run.approved {run_id, period, run_type}`.
  - `reverse(*, tenant_id, actor_id, run_id, reason) -> Result[dict]` — `RUN_INVALID` (no reason), `RUN_NOT_REVERSIBLE`, `RUN_LOCKED` (a later approved/paid run took one of its carried amounts); releases advances, instalments and carried amounts; later *calculated* runs that took its carried amounts go back to draft; publishes `payroll.run.reversed {run_id, period}`.
  - `_publish(tenant_id, event_type, run_id, payload)` (correlation id = run id; also used by `mark_paid`, Task 9).
- `testing_support.approved_run(connection, *, tenant_id, calculator, approver, period, snapshots, presence) -> str`.

- [ ] **Step 1: Write the failing tests**

Create `backend/modules/payroll/api/test_approval_integration.py`:

```python
"""Approval and reversal: four-eyes, confirmed rules, closed presence, events, release of deductions."""
from __future__ import annotations

import datetime
from decimal import Decimal

import pytest

from core.domain.result import Err, Ok
from modules.payroll.api.input_service import InputService
from modules.payroll.api.rule_set_service import RuleSetService
from modules.payroll.api.run_service import RunService
from modules.payroll.api.testing_support import (
    FakePresence, FakeSnapshots, make_user, set_country, snapshot, store_rule_set,
)

TENANT = "payroll-approval-test"
SEPT = datetime.date(2031, 9, 1)
OCT = datetime.date(2031, 10, 1)
D = Decimal
EMPLOYEES = [snapshot("E1", employee_no="M-001", full_name="Awa Traoré"),
             snapshot("E3", employee_no="M-003", full_name="Oumar Diarra", base_salary=D(100000), hire_date=datetime.date(2031, 1, 1))]
SUMMARIES = {"E1": {"scheduled_days": 22, "worked_days": 22}, "E3": {"scheduled_days": 22, "worked_days": 22}}


@pytest.fixture
def world(db):
    calculator, approver = make_user(db, TENANT), make_user(db, TENANT)
    set_country(db, tenant_id=TENANT, actor_id=calculator)
    rule_set_id = store_rule_set(db, tenant_id=TENANT, actor_id=calculator, valid_from=datetime.date(2031, 1, 1))
    snapshots, presence = FakeSnapshots(EMPLOYEES), FakePresence(SUMMARIES)
    return {"db": db, "a": calculator, "b": approver, "rule_set_id": rule_set_id, "presence": presence,
            "runs": RunService(db, snapshots=snapshots, presence=presence), "inputs": InputService(db, snapshots=snapshots)}


def _calculated(world, period=SEPT):
    run_id = world["runs"].create_run(tenant_id=TENANT, actor_id=world["a"], period=period, run_type="regular").value["id"]
    assert isinstance(world["runs"].calculate(tenant_id=TENANT, actor_id=world["a"], run_id=run_id), Ok)
    return run_id


def _approve(world, run_id, actor="b"):
    return world["runs"].approve(tenant_id=TENANT, actor_id=world[actor], run_id=run_id)


def _event(world, event_type, run_id):
    row = world["db"].execute(
        "SELECT payload FROM events.outbox WHERE event_type = %s AND payload->'payload'->>'run_id' = %s", (event_type, run_id)).fetchone()
    return None if row is None else row[0]


def _draft_rules(world):
    world["db"].execute("UPDATE payroll.rule_sets SET status = 'draft', confirmed_by = NULL, confirmed_at = NULL WHERE id = %s", (world["rule_set_id"],))


def test_the_person_who_calculated_cannot_approve(world):
    refused = _approve(world, _calculated(world), actor="a")
    assert isinstance(refused, Err) and refused.code == "SAME_USER_APPROVAL" and refused.message_fr


def test_a_draft_run_is_calculated_before_approval(world):
    run_id = world["runs"].create_run(tenant_id=TENANT, actor_id=world["a"], period=SEPT, run_type="regular").value["id"]
    assert _approve(world, run_id).code == "RUN_NOT_CALCULATED"


def test_a_draft_rule_set_blocks_approval(world):
    _draft_rules(world)
    refused = _approve(world, _calculated(world))
    assert isinstance(refused, Err) and refused.code == "RULESET_NOT_CONFIRMED"


def test_a_rule_set_confirmed_after_calculation_needs_a_recalculation(world):
    _draft_rules(world)
    run_id = _calculated(world)
    RuleSetService(world["db"]).confirm_rule_set(tenant_id=TENANT, actor_id=world["b"], rule_set_id=world["rule_set_id"])
    refused = _approve(world, run_id)
    assert isinstance(refused, Err) and refused.code == "RULESET_NOT_CONFIRMED" and "recalculate" in refused.message
    world["runs"].calculate(tenant_id=TENANT, actor_id=world["a"], run_id=run_id)
    assert isinstance(_approve(world, run_id), Ok)


def test_a_newer_rule_set_in_force_needs_a_recalculation(world):
    run_id = _calculated(world)
    store_rule_set(world["db"], tenant_id=TENANT, actor_id=world["a"], valid_from=SEPT, name="Newer")
    assert _approve(world, run_id).code == "RULESET_NOT_CONFIRMED"


def test_approval_is_refused_when_presence_was_reopened(world):
    run_id = _calculated(world)
    world["presence"].closed = False
    assert _approve(world, run_id).code == "PRESENCE_NOT_CLOSED"


def test_approval_locks_the_run_publishes_the_event_and_is_audited(world):
    run_id = _calculated(world)
    approved = _approve(world, run_id)
    assert isinstance(approved, Ok) and approved.value["status"] == "approved" and approved.value["approved_by"] == world["b"]
    envelope = _event(world, "payroll.run.approved", run_id)
    assert envelope["payload"] == {"run_id": run_id, "period": "2031-09-01", "run_type": "regular"}
    assert envelope["producer"] == "payroll" and envelope["correlation_id"] == run_id
    assert world["db"].execute("SELECT count(*) FROM core.audit_log WHERE entity_id = %s AND action = 'payroll_run.approved'", (run_id,)).fetchone()[0] == 1
    assert world["runs"].calculate(tenant_id=TENANT, actor_id=world["a"], run_id=run_id).code == "RUN_LOCKED"


def test_reversal_needs_a_reason_and_an_approved_run(world):
    run_id = _calculated(world)
    assert world["runs"].reverse(tenant_id=TENANT, actor_id=world["b"], run_id=run_id, reason="Erreur").code == "RUN_NOT_REVERSIBLE"
    _approve(world, run_id)
    assert world["runs"].reverse(tenant_id=TENANT, actor_id=world["b"], run_id=run_id, reason="  ").code == "RUN_INVALID"


def test_reversal_releases_deductions_frees_the_month_and_publishes_the_event(world):
    advance = world["inputs"].create_advance(tenant_id=TENANT, actor_id=world["a"], employee_id="E1", amount=D(50000),
                                             requested_on=SEPT, deduct_period=SEPT).value
    world["inputs"].approve_advance(tenant_id=TENANT, actor_id=world["a"], advance_id=advance["id"])
    run_id = _calculated(world)
    _approve(world, run_id)
    reversed_run = world["runs"].reverse(tenant_id=TENANT, actor_id=world["b"], run_id=run_id, reason="Wrong month")
    assert isinstance(reversed_run, Ok) and reversed_run.value["status"] == "reversed" and reversed_run.value["reversal_reason"] == "Wrong month"
    assert world["db"].execute("SELECT deducted_payslip_id FROM payroll.advances WHERE id = %s", (advance["id"],)).fetchone()[0] is None
    assert _event(world, "payroll.run.reversed", run_id)["payload"] == {"run_id": run_id, "period": "2031-09-01"}
    assert isinstance(world["runs"].create_run(tenant_id=TENANT, actor_id=world["a"], period=SEPT, run_type="regular"), Ok)


def _carry_then_october(world):
    advance = world["inputs"].create_advance(tenant_id=TENANT, actor_id=world["a"], employee_id="E3", amount=D(120000),
                                             requested_on=SEPT, deduct_period=SEPT).value
    world["inputs"].approve_advance(tenant_id=TENANT, actor_id=world["a"], advance_id=advance["id"])
    september = _calculated(world)
    _approve(world, september)
    return september, _calculated(world, period=OCT)


def test_a_run_whose_carry_a_later_approved_run_took_cannot_be_reversed(world):
    september, october = _carry_then_october(world)
    _approve(world, october)
    refused = world["runs"].reverse(tenant_id=TENANT, actor_id=world["b"], run_id=september, reason="x")
    assert isinstance(refused, Err) and refused.code == "RUN_LOCKED" and "10/2031" in refused.message_fr


def test_reversing_sends_a_later_calculated_run_that_took_its_carry_back_to_draft(world):
    september, october = _carry_then_october(world)
    assert isinstance(world["runs"].reverse(tenant_id=TENANT, actor_id=world["b"], run_id=september, reason="x"), Ok)
    assert world["runs"].get_run(tenant_id=TENANT, run_id=october)["status"] == "draft"
    assert world["db"].execute("SELECT count(*) FROM payroll.carry_forwards WHERE tenant_id = %s", (TENANT,)).fetchone()[0] == 0
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python -m pytest modules/payroll/api/test_approval_integration.py -q`
Expected: FAIL — `AttributeError: 'RunService' object has no attribute 'approve'`.

- [ ] **Step 3: Add `approve`, `reverse` and `_publish` to `RunService`**

Add `from core.events.outbox import publish_event` to the imports of `run_service.py`, then add to the class:

```python
    # -- approval and reversal ------------------------------------------------------------------
    def _publish(self, tenant_id: str, event_type: str, run_id: str, payload: dict[str, Any]) -> None:
        publish_event(self.connection, event_type=event_type, producer="payroll", tenant_id=tenant_id,
                      correlation_id=run_id, payload=payload)

    def approve(self, *, tenant_id: str, actor_id: str, run_id: str) -> Result[dict[str, Any]]:
        run = lock_run(self.connection, tenant_id, run_id)
        if run is None:
            return not_found()
        if run["status"] in ("approved", "paid", "reversed"):
            return locked(run["status"])
        if run["status"] != "calculated":
            return Err("RUN_NOT_CALCULATED", "calculate the run before approving it", "calculez la paie avant de l'approuver")
        if run["calculated_by"] == actor_id:
            return Err("SAME_USER_APPROVAL", "the person who calculated the run cannot approve it",
                       "la personne qui a calculé la paie ne peut pas l'approuver")
        rule_set = fetch_one(self.connection, "SELECT status, confirmed_at FROM payroll.rule_sets WHERE id = %s", (run["rule_set_id"],))
        if rule_set["status"] != "confirmed":
            return Err("RULESET_NOT_CONFIRMED", "the rule set used is a draft; the accountant confirms it, then recalculate and approve",
                       "le jeu de règles utilisé est un brouillon ; le comptable le confirme, puis recalculez et approuvez")
        if rule_set["confirmed_at"] > run["calculated_at"]:
            return Err("RULESET_NOT_CONFIRMED", "the rule set was confirmed after this calculation; recalculate before approving",
                       "le jeu de règles a été confirmé après ce calcul ; recalculez avant d'approuver")
        in_force = RuleSetService(self.connection).in_force(tenant_id=tenant_id, period=run["period"])
        if isinstance(in_force, Err) or in_force.value["id"] != run["rule_set_id"]:
            return Err("RULESET_NOT_CONFIRMED", "another rule set now applies to this month; recalculate before approving",
                       "un autre jeu de règles s'applique désormais à ce mois ; recalculez avant d'approuver")
        if run["run_type"] == "regular" and not self.presence.is_month_closed(tenant_id=tenant_id, period=run["period"]):
            return Err("PRESENCE_NOT_CLOSED", "presence was reopened after the calculation; close it again, recalculate, then approve",
                       "la présence a été rouverte après le calcul ; clôturez-la de nouveau, recalculez, puis approuvez")
        self.connection.execute("UPDATE payroll.runs SET status = 'approved', approved_by = %s, approved_at = clock_timestamp() WHERE id = %s",
                                (actor_id, run_id))
        self._publish(tenant_id, "payroll.run.approved", run_id,
                      {"run_id": run_id, "period": run["period"].isoformat(), "run_type": run["run_type"]})
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="payroll_run.approved",
                     entity_type="payroll_run", entity_id=run_id, payload={"from_status": "calculated", "to_status": "approved"})
        return Ok(self.get_run(tenant_id=tenant_id, run_id=run_id))

    def reverse(self, *, tenant_id: str, actor_id: str, run_id: str, reason: str) -> Result[dict[str, Any]]:
        if not (reason or "").strip():
            return Err("RUN_INVALID", "give the reason for the reversal", "indiquez le motif de l'extourne")
        run = lock_run(self.connection, tenant_id, run_id)
        if run is None:
            return not_found()
        if run["status"] not in ("approved", "paid"):
            return Err("RUN_NOT_REVERSIBLE", "only an approved or paid run can be reversed", "seule une paie approuvée ou payée peut être extournée")
        takers = fetch_all(
            self.connection,
            """
            SELECT DISTINCT later.id, later.period, later.status
            FROM payroll.carry_forwards cf
            JOIN payroll.payslips source ON source.id = cf.source_payslip_id
            JOIN payroll.payslips taker ON taker.id = cf.consumed_by_payslip_id
            JOIN payroll.runs later ON later.id = taker.run_id
            WHERE source.run_id = %s
            """,
            (run_id,),
        )
        final = [taker for taker in takers if taker["status"] in ("approved", "paid")]
        if final:
            periods = ", ".join(sorted({f"{taker['period']:%m/%Y}" for taker in final}))
            return Err("RUN_LOCKED", f"a later approved run ({periods}) already deducted amounts carried from this run; reverse it first",
                       f"une paie approuvée plus récente ({periods}) a déjà retenu des montants reportés de cette paie ; extournez-la d'abord")
        for taker in takers:
            invalidate(self.connection, taker["id"])
        own = "SELECT id FROM payroll.payslips WHERE run_id = %s"
        self.connection.execute(f"UPDATE payroll.advances SET deducted_payslip_id = NULL WHERE deducted_payslip_id IN ({own})", (run_id,))
        self.connection.execute(f"UPDATE payroll.loan_instalments SET payslip_id = NULL WHERE payslip_id IN ({own})", (run_id,))
        self.connection.execute(f"UPDATE payroll.carry_forwards SET consumed_by_payslip_id = NULL WHERE consumed_by_payslip_id IN ({own})", (run_id,))
        self.connection.execute(f"DELETE FROM payroll.carry_forwards WHERE source_payslip_id IN ({own})", (run_id,))
        self.connection.execute(
            "UPDATE payroll.runs SET status = 'reversed', reversed_by = %s, reversed_at = clock_timestamp(), reversal_reason = %s WHERE id = %s",
            (actor_id, reason.strip(), run_id))
        self._publish(tenant_id, "payroll.run.reversed", run_id, {"run_id": run_id, "period": run["period"].isoformat()})
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="payroll_run.reversed",
                     entity_type="payroll_run", entity_id=run_id,
                     payload={"from_status": run["status"], "to_status": "reversed", "reason": reason.strip()})
        return Ok(self.get_run(tenant_id=tenant_id, run_id=run_id))
```

- [ ] **Step 4: Add `approved_run` to `testing_support.py`**

```python
def approved_run(connection, *, tenant_id: str, calculator: str, approver: str, period: datetime.date,
                 snapshots: Any, presence: Any) -> str:
    """A regular run calculated by one user and approved by another (four-eyes)."""
    from modules.payroll.api.run_service import RunService

    runs = RunService(connection, snapshots=snapshots, presence=presence)
    run_id = runs.create_run(tenant_id=tenant_id, actor_id=calculator, period=period, run_type="regular").value["id"]
    calculated = runs.calculate(tenant_id=tenant_id, actor_id=calculator, run_id=run_id)
    assert isinstance(calculated, Ok), calculated
    approved = runs.approve(tenant_id=tenant_id, actor_id=approver, run_id=run_id)
    assert isinstance(approved, Ok), approved
    return run_id
```

- [ ] **Step 5: Register the events**

Append these rows to the table in `backend/events/CATALOG.md` (after the `qc.*` rows):

```markdown
| `payroll.run.approved` | 1.0 | payroll | finance | `run_id`, `period`, `run_type` — a run's payslips are final (four-eyes, confirmed rule set, closed presence); finance posts the PAIE entry from `PayrollPostingService.posting_lines` |
| `payroll.run.paid` | 1.0 | payroll | finance | `run_id`, `period` — every payout batch of the run is confirmed; finance clears 422 from `PayrollPostingService.payment_lines` |
| `payroll.run.reversed` | 1.0 | payroll | finance | `run_id`, `period` — an approved or paid run was cancelled; its deductions are released; finance posts the mirror entry |
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest modules/payroll core/test_error_translations.py -q`
Expected: all pass (`test_approval_integration.py` adds 11), no skips.

- [ ] **Step 7: Commit**

```bash
git add backend/modules/payroll/api/run_service.py backend/modules/payroll/api/testing_support.py backend/modules/payroll/api/test_approval_integration.py backend/events/CATALOG.md
git commit -m "feat(payroll): four-eyes approval and reversal with outbox events

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Payouts — bank files, mobile money, cash sheet, marking a run paid

**Files:**
- Create: `backend/modules/payroll/migrations/0004_payroll_payouts.sql`
- Create: `backend/modules/payroll/api/company.py`
- Create: `backend/modules/payroll/api/payout_service.py`
- Create: `backend/modules/payroll/api/routes_payouts.py`
- Modify: `backend/modules/payroll/api/http.py` (add `csv_response`)
- Modify: `backend/modules/payroll/api/router.py` (include payouts routes)
- Modify: `backend/modules/payroll/api/run_service.py` (add `mark_paid`)
- Test: `backend/modules/payroll/api/test_payouts_integration.py`

**Interfaces:**
- Consumes: `split_net`, `billetage`, `render_bank_csv`, `render_mobile_csv`, `validate_bank_template`, `XOF_DENOMINATIONS` (Task 2); `lock_run`, `locked`, `not_found`; `RunService._publish`.
- Produces:
  - Tables `payroll.bank_file_templates`, `payroll.payout_batches`, `payroll.payout_lines`.
  - `company.company_header(connection, tenant_id) -> dict` (`name` from `core.companies`, `address`, `employer_inps_no`, `employer_tax_id` from `payroll.settings`).
  - `PayoutService(connection)`: `list_templates(*, tenant_id)`, `create_template(*, tenant_id, actor_id, values: dict)`, `update_template(*, tenant_id, actor_id, template_id, changes: dict)`, `delete_template(*, tenant_id, actor_id, template_id)`, `generate(*, tenant_id, actor_id, run_id) -> Result[list[dict]]`, `list_batches(*, tenant_id, run_id) -> list[dict]`, `confirm_batch(*, tenant_id, actor_id, batch_id)`, `batch_file(*, tenant_id, batch_id) -> Result[tuple[str, str]]` (file name, CSV text), `cash_sheet(*, tenant_id, batch_id) -> Result[dict]`.
  - `RunService.mark_paid(*, tenant_id, actor_id, run_id) -> Result[dict]` — `RUN_NOT_APPROVED`, `RUN_LOCKED`, `PAYOUT_INCOMPLETE`; publishes `payroll.run.paid {run_id, period}`.
  - `http.csv_response(file_name, text) -> Response` (UTF-8 with BOM so Excel reads accents).
  - Routes: `GET/POST /payroll/bank-file-templates` (view_runs / pay_runs), `PATCH/DELETE /payroll/bank-file-templates/{id}` (pay_runs), `POST /payroll/runs/{id}/payouts` (pay_runs), `GET /payroll/runs/{id}/payouts` (view_runs), `POST /payroll/payout-batches/{id}/confirm`, `GET /payroll/payout-batches/{id}/file`, `GET /payroll/payout-batches/{id}/cash-sheet`, `POST /payroll/runs/{id}/mark-paid` (all pay_runs).
- Error codes: `RUN_NOT_APPROVED`, `PAYOUT_CONFIRMED`, `PAYOUT_SPLIT_INVALID`, `PAYOUT_INVALID`, `PAYOUT_INCOMPLETE`, `TEMPLATE_INVALID`, `TEMPLATE_MISSING`, `DUPLICATE_TEMPLATE`, `NOT_FOUND`.

Spec: `payout_batches (run, method, status generated/confirmed, file ref)` and `payout_lines (employee, method details snapshot, amount)`. One batch per method and bank / operator (the bank file template and the mobile operator's upload both need one file each); cash is one batch printed as a sheet. Regenerating replaces unconfirmed batches; after any confirmation payouts are frozen.

- [ ] **Step 1: Write the migration**

Create `backend/modules/payroll/migrations/0004_payroll_payouts.sql`:

```sql
CREATE TABLE IF NOT EXISTS payroll.bank_file_templates (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    bank_name TEXT NOT NULL,           -- upper-case, matched against the payout batch's group_key
    delimiter TEXT NOT NULL DEFAULT ';',
    include_header BOOLEAN NOT NULL DEFAULT TRUE,
    columns JSONB NOT NULL,            -- [{"header": "...", "field": "account_no" | "amount" | ...}]
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, bank_name)
);

CREATE TABLE IF NOT EXISTS payroll.payout_batches (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    run_id TEXT NOT NULL REFERENCES payroll.runs (id),
    method TEXT NOT NULL CHECK (method IN ('bank', 'mobile_money', 'cash')),
    group_key TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'generated' CHECK (status IN ('generated', 'confirmed')),
    file_name TEXT NOT NULL,
    total NUMERIC(18, 0) NOT NULL,
    line_count INTEGER NOT NULL,
    generated_by TEXT NOT NULL,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    confirmed_by TEXT,
    confirmed_at TIMESTAMPTZ,
    UNIQUE (run_id, method, group_key)
);

CREATE TABLE IF NOT EXISTS payroll.payout_lines (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    batch_id TEXT NOT NULL REFERENCES payroll.payout_batches (id) ON DELETE CASCADE,
    payslip_id TEXT NOT NULL REFERENCES payroll.payslips (id),
    employee_id TEXT NOT NULL,
    employee_no TEXT NOT NULL,
    full_name TEXT NOT NULL,
    details JSONB NOT NULL,
    amount NUMERIC(18, 0) NOT NULL CHECK (amount > 0)
);
CREATE INDEX IF NOT EXISTS payroll_payout_lines_batch_idx ON payroll.payout_lines (batch_id);
```

- [ ] **Step 2: Write the failing tests**

Create `backend/modules/payroll/api/test_payouts_integration.py`:

```python
"""Payouts from an approved run: one batch per method and bank/operator, files, cash sheet, paid."""
from __future__ import annotations

import datetime
from decimal import Decimal

import pytest

from core.domain.result import Err, Ok
from modules.payroll.api.payout_service import PayoutService
from modules.payroll.api.run_service import RunService
from modules.payroll.api.testing_support import (
    FakePresence, FakeSnapshots, approved_run, make_user, set_country, snapshot, store_rule_set,
)

TENANT = "payroll-payouts-test"
SEPT = datetime.date(2031, 9, 1)
D = Decimal


def _methods(*items):
    return [dict(zip(("method", "bank_name", "account_no", "mobile_operator", "mobile_number", "share_percent", "is_primary"), item)) for item in items]


EMPLOYEES = [
    snapshot("E1", employee_no="M-001", full_name="Awa Traoré"),
    snapshot("E2", employee_no="M-002", full_name="Moussa Keita", payment_methods=_methods(
        ("bank", "Ecobank", "EC-2", None, None, D(60), True), ("mobile_money", None, None, "Orange Money", "+22370000002", D(40), False))),
    snapshot("E4", employee_no="M-004", full_name="Fanta Sidibé", payment_methods=_methods(("cash", None, None, None, None, D(100), True))),
]
SUMMARIES = {key: {"scheduled_days": 22, "worked_days": 22} for key in ("E1", "E2", "E4", "E5")}


@pytest.fixture
def world(db):
    calculator, approver = make_user(db, TENANT), make_user(db, TENANT)
    set_country(db, tenant_id=TENANT, actor_id=calculator)
    store_rule_set(db, tenant_id=TENANT, actor_id=calculator, valid_from=datetime.date(2031, 1, 1))
    return {"db": db, "a": calculator, "b": approver, "payouts": PayoutService(db)}


def _approved(world, employees=EMPLOYEES):
    snapshots, presence = FakeSnapshots(employees), FakePresence(SUMMARIES)
    run_id = approved_run(world["db"], tenant_id=TENANT, calculator=world["a"], approver=world["b"], period=SEPT,
                          snapshots=snapshots, presence=presence)
    return run_id, RunService(world["db"], snapshots=snapshots, presence=presence)


def _net(world, run_id, employee_id):
    return world["db"].execute("SELECT net FROM payroll.payslips WHERE run_id = %s AND employee_id = %s", (run_id, employee_id)).fetchone()[0]


def test_payouts_wait_for_an_approved_run(world):
    snapshots, presence = FakeSnapshots(EMPLOYEES), FakePresence(SUMMARIES)
    runs = RunService(world["db"], snapshots=snapshots, presence=presence)
    run_id = runs.create_run(tenant_id=TENANT, actor_id=world["a"], period=SEPT, run_type="regular").value["id"]
    runs.calculate(tenant_id=TENANT, actor_id=world["a"], run_id=run_id)
    assert world["payouts"].generate(tenant_id=TENANT, actor_id=world["a"], run_id=run_id).code == "RUN_NOT_APPROVED"


def test_one_batch_per_method_and_bank_or_operator_adding_up_to_the_nets(world):
    run_id, _ = _approved(world)
    batches = world["payouts"].generate(tenant_id=TENANT, actor_id=world["a"], run_id=run_id).value
    assert {(batch["method"], batch["group_key"]) for batch in batches} == {
        ("bank", "BDM"), ("bank", "ECOBANK"), ("mobile_money", "ORANGE MONEY"), ("cash", "CASH")}
    total_net = sum(_net(world, run_id, employee) for employee in ("E1", "E2", "E4"))
    assert sum(batch["total"] for batch in batches) == total_net
    mobile = next(batch for batch in batches if batch["method"] == "mobile_money")
    assert mobile["total"] == int(_net(world, run_id, "E2") * 40 // 100)


def test_the_bank_file_needs_its_template_and_follows_it(world):
    run_id, _ = _approved(world)
    batches = world["payouts"].generate(tenant_id=TENANT, actor_id=world["a"], run_id=run_id).value
    bdm = next(batch for batch in batches if batch["group_key"] == "BDM")
    missing = world["payouts"].batch_file(tenant_id=TENANT, batch_id=bdm["id"])
    assert isinstance(missing, Err) and missing.code == "TEMPLATE_MISSING" and "BDM" in missing.message_fr
    world["payouts"].create_template(tenant_id=TENANT, actor_id=world["a"], values={
        "bank_name": "bdm", "columns": [{"header": "Compte", "field": "account_no"}, {"header": "Montant", "field": "amount"}]})
    file_name, text = world["payouts"].batch_file(tenant_id=TENANT, batch_id=bdm["id"]).value
    assert file_name == "paie-2031-09-bank-bdm.csv"
    assert text.splitlines() == ["Compte;Montant", f"ML-M-001;{int(_net(world, run_id, 'E1'))}"]


def test_mobile_money_has_its_file_and_cash_its_sheet(world):
    run_id, _ = _approved(world)
    batches = {batch["method"]: batch for batch in world["payouts"].generate(tenant_id=TENANT, actor_id=world["a"], run_id=run_id).value}
    _, text = world["payouts"].batch_file(tenant_id=TENANT, batch_id=batches["mobile_money"]["id"]).value
    assert text.startswith("operator;number;name;amount\r\nOrange Money;+22370000002;Moussa Keita;")
    assert world["payouts"].batch_file(tenant_id=TENANT, batch_id=batches["cash"]["id"]).code == "PAYOUT_INVALID"
    sheet = world["payouts"].cash_sheet(tenant_id=TENANT, batch_id=batches["cash"]["id"]).value
    line = sheet["lines"][0]
    assert line["full_name"] == "Fanta Sidibé"
    assert sum(int(value) * count for value, count in line["counts"].items()) + line["remainder"] == line["amount"]
    assert sheet["totals"]["amount"] == line["amount"]


def test_a_run_is_paid_once_every_batch_is_confirmed(world):
    run_id, runs = _approved(world)
    batches = world["payouts"].generate(tenant_id=TENANT, actor_id=world["a"], run_id=run_id).value
    assert runs.mark_paid(tenant_id=TENANT, actor_id=world["a"], run_id=run_id).code == "PAYOUT_INCOMPLETE"
    for batch in batches:
        assert isinstance(world["payouts"].confirm_batch(tenant_id=TENANT, actor_id=world["a"], batch_id=batch["id"]), Ok)
    paid = runs.mark_paid(tenant_id=TENANT, actor_id=world["a"], run_id=run_id)
    assert isinstance(paid, Ok) and paid.value["status"] == "paid"
    envelope = world["db"].execute("SELECT payload FROM events.outbox WHERE event_type = 'payroll.run.paid' AND payload->'payload'->>'run_id' = %s",
                                   (run_id,)).fetchone()[0]
    assert envelope["payload"] == {"run_id": run_id, "period": "2031-09-01"}


def test_confirmed_payouts_are_not_regenerated(world):
    run_id, _ = _approved(world)
    first = world["payouts"].generate(tenant_id=TENANT, actor_id=world["a"], run_id=run_id).value[0]
    world["payouts"].confirm_batch(tenant_id=TENANT, actor_id=world["a"], batch_id=first["id"])
    assert world["payouts"].generate(tenant_id=TENANT, actor_id=world["a"], run_id=run_id).code == "PAYOUT_CONFIRMED"


def test_a_bad_split_names_the_employee(world):
    broken = snapshot("E5", employee_no="M-005", full_name="Kadiatou Sanogo",
                      payment_methods=_methods(("bank", "BDM", "ML-5", None, None, D(50), True)))
    run_id, _ = _approved(world, employees=[EMPLOYEES[0], broken])
    refused = world["payouts"].generate(tenant_id=TENANT, actor_id=world["a"], run_id=run_id)
    assert isinstance(refused, Err) and refused.code == "PAYOUT_SPLIT_INVALID" and "Kadiatou Sanogo" in refused.message_fr
```

- [ ] **Step 3: Apply the migration and run the tests to verify they fail**

Run:
```
.venv/Scripts/python -c "import app.main; from core.migrations.runner import apply_all_migrations; apply_all_migrations()"
.venv/Scripts/python -m pytest modules/payroll/api/test_payouts_integration.py -q
```
Expected: FAIL — `ModuleNotFoundError: No module named 'modules.payroll.api.payout_service'`.

- [ ] **Step 4: Write `company.py`**

```python
"""The employer block printed on payslips, cash sheets and declarations."""
from __future__ import annotations

from typing import Any

import psycopg

from modules.payroll.api.rule_set_service import RuleSetService


def company_header(connection: psycopg.Connection, tenant_id: str) -> dict[str, Any]:
    row = connection.execute("SELECT name FROM core.companies WHERE tenant_id = %s ORDER BY created_at LIMIT 1", (tenant_id,)).fetchone()
    settings = RuleSetService(connection).get_settings(tenant_id=tenant_id) or {}
    return {"name": row[0] if row else None, "address": settings.get("company_address"),
            "employer_inps_no": settings.get("employer_inps_no"), "employer_tax_id": settings.get("employer_tax_id")}
```

- [ ] **Step 5: Write `payout_service.py`**

```python
"""Payout batches for an approved run: bank files per bank template, mobile money per operator,
cash sheets with the note-and-coin count. Generated batches can be regenerated until one is
confirmed; confirming every batch is what lets the run be marked paid (RunService.mark_paid)."""
from __future__ import annotations

import re
from typing import Any

import psycopg
from psycopg.types.json import Jsonb
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.payroll.api.company import company_header
from modules.payroll.api.rows import fetch_all, fetch_one, jsonable
from modules.payroll.api.run_state import lock_run, locked, not_found
from modules.payroll.domain.payouts import (
    XOF_DENOMINATIONS, billetage, render_bank_csv, render_mobile_csv, split_net, validate_bank_template,
)

_BATCH_COLUMNS = ("b.id, b.run_id, b.method, b.group_key, b.status, b.file_name, b.total, b.line_count, "
                  "b.generated_by, b.generated_at, b.confirmed_by, b.confirmed_at")


def _slug(key: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", key).strip("-").lower() or "batch"


class PayoutService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    # -- bank file templates ----------------------------------------------------------------
    def list_templates(self, *, tenant_id: str) -> list[dict[str, Any]]:
        return fetch_all(self.connection, "SELECT id, bank_name, delimiter, include_header, columns FROM payroll.bank_file_templates "
                                          "WHERE tenant_id = %s ORDER BY bank_name", (tenant_id,))

    def _template(self, tenant_id: str, template_id: str) -> dict[str, Any] | None:
        return fetch_one(self.connection, "SELECT id, bank_name, delimiter, include_header, columns FROM payroll.bank_file_templates "
                                          "WHERE tenant_id = %s AND id = %s", (tenant_id, template_id))

    def _save_template(self, tenant_id: str, template_id: str | None, clean: dict[str, Any], actor_id: str) -> Result[str]:
        try:
            with self.connection.transaction():
                if template_id is None:
                    template_id = str(ULID())
                    self.connection.execute(
                        "INSERT INTO payroll.bank_file_templates (id, tenant_id, bank_name, delimiter, include_header, columns, created_by) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                        (template_id, tenant_id, clean["bank_name"], clean["delimiter"], clean["include_header"], Jsonb(clean["columns"]), actor_id))
                else:
                    self.connection.execute(
                        "UPDATE payroll.bank_file_templates SET bank_name = %s, delimiter = %s, include_header = %s, columns = %s WHERE id = %s",
                        (clean["bank_name"], clean["delimiter"], clean["include_header"], Jsonb(clean["columns"]), template_id))
        except psycopg.errors.UniqueViolation:
            return Err("DUPLICATE_TEMPLATE", f"{clean['bank_name']} already has a template", f"{clean['bank_name']} a déjà un modèle")
        return Ok(template_id)

    def create_template(self, *, tenant_id: str, actor_id: str, values: dict[str, Any]) -> Result[dict[str, Any]]:
        checked = validate_bank_template(values)
        if isinstance(checked, Err):
            return checked
        saved = self._save_template(tenant_id, None, checked.value, actor_id)
        if isinstance(saved, Err):
            return saved
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="bank_file_template.created",
                     entity_type="bank_file_template", entity_id=saved.value, payload=checked.value)
        return Ok(self._template(tenant_id, saved.value))

    def update_template(self, *, tenant_id: str, actor_id: str, template_id: str, changes: dict[str, Any]) -> Result[dict[str, Any]]:
        current = self._template(tenant_id, template_id)
        if current is None:
            return Err("NOT_FOUND", "bank file template not found", "modèle de fichier bancaire introuvable")
        checked = validate_bank_template({**current, **changes})
        if isinstance(checked, Err):
            return checked
        saved = self._save_template(tenant_id, template_id, checked.value, actor_id)
        if isinstance(saved, Err):
            return saved
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="bank_file_template.updated",
                     entity_type="bank_file_template", entity_id=template_id, payload={"changes": jsonable(changes)})
        return Ok(self._template(tenant_id, template_id))

    def delete_template(self, *, tenant_id: str, actor_id: str, template_id: str) -> Result[dict[str, Any]]:
        current = self._template(tenant_id, template_id)
        if current is None:
            return Err("NOT_FOUND", "bank file template not found", "modèle de fichier bancaire introuvable")
        self.connection.execute("DELETE FROM payroll.bank_file_templates WHERE id = %s", (template_id,))
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="bank_file_template.deleted",
                     entity_type="bank_file_template", entity_id=template_id, payload=current)
        return Ok({"id": template_id})

    # -- batches ----------------------------------------------------------------------------------
    def list_batches(self, *, tenant_id: str, run_id: str) -> list[dict[str, Any]]:
        return jsonable(fetch_all(self.connection, f"SELECT {_BATCH_COLUMNS} FROM payroll.payout_batches b WHERE b.tenant_id = %s AND b.run_id = %s "
                                                   "ORDER BY b.method, b.group_key", (tenant_id, run_id)))

    def _batch(self, tenant_id: str, batch_id: str, *, lock: bool = False) -> dict[str, Any] | None:
        return fetch_one(self.connection, f"SELECT {_BATCH_COLUMNS}, r.period FROM payroll.payout_batches b JOIN payroll.runs r ON r.id = b.run_id "
                                          "WHERE b.tenant_id = %s AND b.id = %s" + (" FOR UPDATE OF b" if lock else ""), (tenant_id, batch_id))

    def _lines(self, batch_id: str) -> list[dict[str, Any]]:
        return fetch_all(self.connection, "SELECT employee_id, employee_no, full_name, details, amount FROM payroll.payout_lines "
                                          "WHERE batch_id = %s ORDER BY full_name", (batch_id,))

    def generate(self, *, tenant_id: str, actor_id: str, run_id: str) -> Result[list[dict[str, Any]]]:
        run = lock_run(self.connection, tenant_id, run_id)
        if run is None:
            return not_found()
        if run["status"] in ("paid", "reversed"):
            return locked(run["status"])
        if run["status"] != "approved":
            return Err("RUN_NOT_APPROVED", "payouts are generated for an approved run", "les paiements se génèrent pour une paie approuvée")
        confirmed = self.connection.execute("SELECT 1 FROM payroll.payout_batches WHERE run_id = %s AND status = 'confirmed' LIMIT 1", (run_id,)).fetchone()
        if confirmed is not None:
            return Err("PAYOUT_CONFIRMED", "a batch of this run is already confirmed; payouts can no longer be regenerated",
                       "un lot de cette paie est déjà confirmé ; les paiements ne peuvent plus être régénérés")
        self.connection.execute("DELETE FROM payroll.payout_batches WHERE run_id = %s", (run_id,))
        payslips = fetch_all(self.connection, "SELECT id, employee_id, employee_no, full_name, net, snapshot->'payment_methods' AS methods "
                                              "FROM payroll.payslips WHERE run_id = %s AND net > 0 ORDER BY full_name", (run_id,))
        groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
        problems: list[tuple[str, Err]] = []
        for payslip in payslips:
            split = split_net(payslip["net"], payslip["methods"] or [])
            if isinstance(split, Err):
                problems.append((payslip["full_name"], split))
                continue
            for share in split.value:
                groups.setdefault((share.method, share.group_key), []).append(
                    {"payslip_id": payslip["id"], "employee_id": payslip["employee_id"], "employee_no": payslip["employee_no"],
                     "full_name": payslip["full_name"], "details": share.details, "amount": share.amount})
        if problems:
            return Err("PAYOUT_SPLIT_INVALID", "; ".join(f"{name}: {err.message}" for name, err in problems),
                       "; ".join(f"{name} : {err.message_fr}" for name, err in problems))
        for (method, key), lines in sorted(groups.items()):
            batch_id = str(ULID())
            file_name = f"paie-{run['period']:%Y-%m}-{method}-{_slug(key)}.csv"
            self.connection.execute(
                "INSERT INTO payroll.payout_batches (id, tenant_id, run_id, method, group_key, file_name, total, line_count, generated_by) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (batch_id, tenant_id, run_id, method, key, file_name, sum(line["amount"] for line in lines), len(lines), actor_id))
            for line in lines:
                self.connection.execute(
                    "INSERT INTO payroll.payout_lines (id, tenant_id, batch_id, payslip_id, employee_id, employee_no, full_name, details, amount) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (str(ULID()), tenant_id, batch_id, line["payslip_id"], line["employee_id"], line["employee_no"], line["full_name"],
                     Jsonb(line["details"]), line["amount"]))
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="payout_batches.generated",
                     entity_type="payroll_run", entity_id=run_id,
                     payload={"batches": len(groups), "total": int(sum(payslip["net"] for payslip in payslips))})
        return Ok(self.list_batches(tenant_id=tenant_id, run_id=run_id))

    def confirm_batch(self, *, tenant_id: str, actor_id: str, batch_id: str) -> Result[dict[str, Any]]:
        batch = self._batch(tenant_id, batch_id, lock=True)
        if batch is None:
            return Err("NOT_FOUND", "payout batch not found", "lot de paiement introuvable")
        if batch["status"] == "confirmed":
            return Err("PAYOUT_CONFIRMED", "this batch is already confirmed", "ce lot est déjà confirmé")
        self.connection.execute("UPDATE payroll.payout_batches SET status = 'confirmed', confirmed_by = %s, confirmed_at = NOW() WHERE id = %s",
                                (actor_id, batch_id))
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="payout_batch.confirmed", entity_type="payout_batch",
                     entity_id=batch_id, payload={"from_status": "generated", "to_status": "confirmed", "total": int(batch["total"])})
        return Ok(jsonable(self._batch(tenant_id, batch_id)))

    def batch_file(self, *, tenant_id: str, batch_id: str) -> Result[tuple[str, str]]:
        batch = self._batch(tenant_id, batch_id)
        if batch is None:
            return Err("NOT_FOUND", "payout batch not found", "lot de paiement introuvable")
        lines = self._lines(batch_id)
        if batch["method"] == "cash":
            return Err("PAYOUT_INVALID", "a cash batch is paid from the printed cash sheet", "un lot en espèces se paie avec la feuille de caisse imprimée")
        if batch["method"] == "mobile_money":
            return Ok((batch["file_name"], render_mobile_csv(lines)))
        template = fetch_one(self.connection, "SELECT bank_name, delimiter, include_header, columns FROM payroll.bank_file_templates "
                                              "WHERE tenant_id = %s AND bank_name = %s", (tenant_id, batch["group_key"]))
        if template is None:
            return Err("TEMPLATE_MISSING", f"no bank file template for {batch['group_key']}; add one in the payouts tab",
                       f"aucun modèle de fichier bancaire pour {batch['group_key']} ; ajoutez-en un dans l'onglet paiements")
        return Ok((batch["file_name"], render_bank_csv(template, lines, batch["period"])))

    def cash_sheet(self, *, tenant_id: str, batch_id: str) -> Result[dict[str, Any]]:
        batch = self._batch(tenant_id, batch_id)
        if batch is None:
            return Err("NOT_FOUND", "payout batch not found", "lot de paiement introuvable")
        if batch["method"] != "cash":
            return Err("PAYOUT_INVALID", "only a cash batch has a cash sheet", "seul un lot en espèces a une feuille de caisse")
        lines = []
        totals = {str(value): 0 for value in XOF_DENOMINATIONS}
        remainder_total = 0
        for line in self._lines(batch_id):
            counts, remainder = billetage(line["amount"])
            for value, count in counts.items():
                totals[str(value)] += count
            remainder_total += int(remainder)
            lines.append({"employee_no": line["employee_no"], "full_name": line["full_name"], "amount": int(line["amount"]),
                          "counts": {str(value): count for value, count in counts.items()}, "remainder": int(remainder)})
        return Ok({"batch": jsonable({key: value for key, value in batch.items() if key != "period"}), "period": batch["period"].isoformat(),
                   "company": company_header(self.connection, tenant_id), "denominations": list(XOF_DENOMINATIONS), "lines": lines,
                   "totals": {"amount": int(batch["total"]), "counts": totals, "remainder": remainder_total}})
```

- [ ] **Step 6: Add `mark_paid` to `RunService`**

```python
    def mark_paid(self, *, tenant_id: str, actor_id: str, run_id: str) -> Result[dict[str, Any]]:
        run = lock_run(self.connection, tenant_id, run_id)
        if run is None:
            return not_found()
        if run["status"] in ("paid", "reversed"):
            return locked(run["status"])
        if run["status"] != "approved":
            return Err("RUN_NOT_APPROVED", "only an approved run can be marked paid", "seule une paie approuvée peut être marquée payée")
        batches = fetch_all(self.connection, "SELECT status, total FROM payroll.payout_batches WHERE run_id = %s", (run_id,))
        payable = self.connection.execute("SELECT COALESCE(SUM(net), 0) FROM payroll.payslips WHERE run_id = %s AND net > 0", (run_id,)).fetchone()[0]
        complete = all(batch["status"] == "confirmed" for batch in batches) and sum(batch["total"] for batch in batches) == payable
        if not complete or (payable > 0 and not batches):
            return Err("PAYOUT_INCOMPLETE", "generate and confirm every payout batch before marking the run paid",
                       "générez et confirmez tous les lots de paiement avant de marquer la paie payée")
        self.connection.execute("UPDATE payroll.runs SET status = 'paid', paid_by = %s, paid_at = clock_timestamp() WHERE id = %s", (actor_id, run_id))
        self._publish(tenant_id, "payroll.run.paid", run_id, {"run_id": run_id, "period": run["period"].isoformat()})
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="payroll_run.paid", entity_type="payroll_run",
                     entity_id=run_id, payload={"from_status": "approved", "to_status": "paid", "total": int(payable)})
        return Ok(self.get_run(tenant_id=tenant_id, run_id=run_id))
```

- [ ] **Step 7: Add `csv_response` to `http.py`**

Add `from fastapi import Response` to the imports and:

```python
def csv_response(file_name: str, text: str) -> Response:
    """CSV as a download; the byte-order mark makes Excel read the accents as UTF-8."""
    return Response(content="﻿" + text, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{file_name}"'})
```

- [ ] **Step 8: Write `routes_payouts.py` and include it**

```python
"""HTTP routes for bank file templates, payout batches and marking a run paid."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, status

from core.tenancy import TenantContext, require_permission
from modules.payroll.api import http
from modules.payroll.api.payout_service import PayoutService
from modules.payroll.api.run_service import RunService

router = APIRouter()


@router.get("/bank-file-templates")
def list_templates(tenant: TenantContext = Depends(require_permission("payroll.view_runs"))):
    with http.get_connection() as connection:
        return PayoutService(connection).list_templates(tenant_id=tenant.tenant_id)


@router.post("/bank-file-templates", status_code=status.HTTP_201_CREATED)
def create_template(values: dict[str, Any] = Body(...), tenant: TenantContext = Depends(require_permission("payroll.pay_runs"))):
    with http.get_connection() as connection:
        return http.finish(connection, PayoutService(connection).create_template(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, values=values))


@router.patch("/bank-file-templates/{template_id}")
def update_template(template_id: str, changes: dict[str, Any] = Body(...), tenant: TenantContext = Depends(require_permission("payroll.pay_runs"))):
    with http.get_connection() as connection:
        result = PayoutService(connection).update_template(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, template_id=template_id, changes=changes)
        return http.finish(connection, result)


@router.delete("/bank-file-templates/{template_id}")
def delete_template(template_id: str, tenant: TenantContext = Depends(require_permission("payroll.pay_runs"))):
    with http.get_connection() as connection:
        return http.finish(connection, PayoutService(connection).delete_template(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, template_id=template_id))


@router.post("/runs/{run_id}/payouts")
def generate_payouts(run_id: str, tenant: TenantContext = Depends(require_permission("payroll.pay_runs"))):
    with http.get_connection() as connection:
        return http.finish(connection, PayoutService(connection).generate(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, run_id=run_id))


@router.get("/runs/{run_id}/payouts")
def list_payouts(run_id: str, tenant: TenantContext = Depends(require_permission("payroll.view_runs"))):
    with http.get_connection() as connection:
        return PayoutService(connection).list_batches(tenant_id=tenant.tenant_id, run_id=run_id)


@router.post("/payout-batches/{batch_id}/confirm")
def confirm_batch(batch_id: str, tenant: TenantContext = Depends(require_permission("payroll.pay_runs"))):
    with http.get_connection() as connection:
        return http.finish(connection, PayoutService(connection).confirm_batch(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, batch_id=batch_id))


@router.get("/payout-batches/{batch_id}/file")
def batch_file(batch_id: str, tenant: TenantContext = Depends(require_permission("payroll.pay_runs"))):
    with http.get_connection() as connection:
        file_name, text = http.finish(connection, PayoutService(connection).batch_file(tenant_id=tenant.tenant_id, batch_id=batch_id))
    return http.csv_response(file_name, text)


@router.get("/payout-batches/{batch_id}/cash-sheet")
def cash_sheet(batch_id: str, tenant: TenantContext = Depends(require_permission("payroll.pay_runs"))):
    with http.get_connection() as connection:
        return http.finish(connection, PayoutService(connection).cash_sheet(tenant_id=tenant.tenant_id, batch_id=batch_id))


@router.post("/runs/{run_id}/mark-paid")
def mark_paid(run_id: str, tenant: TenantContext = Depends(require_permission("payroll.pay_runs"))):
    with http.get_connection() as connection:
        return http.finish(connection, RunService(connection).mark_paid(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, run_id=run_id))
```

In `backend/modules/payroll/api/router.py` add `from modules.payroll.api.routes_payouts import router as payouts_router` and `router.include_router(payouts_router)` after the rules include.

- [ ] **Step 9: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest modules/payroll core/test_error_translations.py -q`
Expected: all pass (`test_payouts_integration.py` adds 7), no skips.

- [ ] **Step 10: Commit**

```bash
git add backend/modules/payroll/migrations/0004_payroll_payouts.sql backend/modules/payroll/api/company.py backend/modules/payroll/api/payout_service.py backend/modules/payroll/api/routes_payouts.py backend/modules/payroll/api/http.py backend/modules/payroll/api/router.py backend/modules/payroll/api/run_service.py backend/modules/payroll/api/test_payouts_integration.py
git commit -m "feat(payroll): payout batches, bank and mobile-money files, cash sheet, mark paid

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Payslip reads, print data, work certificate, admin edit, variance

**Files:**
- Create: `backend/modules/payroll/api/payslip_service.py`
- Test: `backend/modules/payroll/api/test_payslip_service_integration.py`

**Interfaces:**
- Consumes: `company_header` (Task 9), `validate_methods` (Task 2), `compare` (Task 3), `add_months` (Task 1), `locked`.
- Produces `PayslipService(connection)`:
  - `list_payslips(*, tenant_id, run_id) -> list[dict]` — `id, run_id, employee_id, employee_no, full_name, department_id, gross, contributable, taxable, employee_contrib, employer_contrib, employer_charges, its, deductions, net, employer_cost, warnings, rule_set_status, note`
  - `get_payslip(*, tenant_id, payslip_id) -> dict | None` — the above + `snapshot, period, run_type, run_status, lines [{line_no, section, code, name_en, name_fr, base, qty, rate, amount}], company`
  - `run_print(*, tenant_id, run_id) -> dict | None` — `{run: {id, period, run_type, label, status}, company, payslips: [get_payslip-shaped]}`
  - `certificate(*, tenant_id, payslip_id) -> Result[dict]` — only for a payslip carrying a final settlement: `company, full_name, employee_no, hire_date, termination_date, termination_reason, position_id, contract_type, issued_on`
  - `admin_update_payslip(*, tenant_id, actor_id, payslip_id, changes) -> Result[dict]` — keys `note`, `payment_methods`; refused `RUN_LOCKED` once the run is paid/reversed; payment details refused `PAYOUT_CONFIRMED` once a batch is confirmed, `PAYOUT_SPLIT_INVALID` when shares are wrong; a change of payment details drops the run's unconfirmed batches (regenerate).
  - `variance(*, tenant_id, run_id) -> dict | None` — `{previous_run_id, previous_period, rows: [{employee_id, employee_no, full_name, previous_gross, current_gross, previous_net, current_net, delta_gross, delta_net, change}], totals: {previous_gross, current_gross, previous_net, current_net}}`, previous = the approved/paid regular run of the month before.

Resolved ambiguity: `payroll.admin_payslips` is the only `admin_*` payroll permission in the spec; it gates the edit-in-place of a payslip, limited to what can change without recomputing money: the note and the payment details snapshot (a new bank account after calculation). Amounts change only by recalculation or reversal.

- [ ] **Step 1: Write the failing tests**

Create `backend/modules/payroll/api/test_payslip_service_integration.py`:

```python
"""Payslip reads, print data, certificate, admin edit and month-on-month variance."""
from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from modules.payroll.api.input_service import InputService
from modules.payroll.api.payout_service import PayoutService
from modules.payroll.api.payslip_service import PayslipService
from modules.payroll.api.run_service import RunService
from modules.payroll.api.testing_support import (
    FakePresence, FakeSnapshots, approved_run, make_user, set_country, snapshot, store_rule_set,
)

TENANT = "payroll-payslips-test"
AUG, SEPT = datetime.date(2031, 8, 1), datetime.date(2031, 9, 1)
D = Decimal
# hired long enough ago that August and September fall on the same seniority step
EMPLOYEES = [snapshot("E1", employee_no="M-001", full_name="Awa Traoré", hire_date=datetime.date(2020, 1, 1)),
             snapshot("E2", employee_no="M-002", full_name="Moussa Keita", hire_date=datetime.date(2020, 1, 1))]
SUMMARIES = {"E1": {"scheduled_days": 22, "worked_days": 22}, "E2": {"scheduled_days": 22, "worked_days": 22}}
NEW_BANK = [{"method": "bank", "bank_name": "Ecobank", "account_no": "EC-9", "mobile_operator": None, "mobile_number": None,
             "share_percent": 100, "is_primary": True}]


@pytest.fixture
def world(db):
    a, b = make_user(db, TENANT), make_user(db, TENANT)
    set_country(db, tenant_id=TENANT, actor_id=a)
    store_rule_set(db, tenant_id=TENANT, actor_id=a, valid_from=datetime.date(2031, 1, 1))
    db.execute("INSERT INTO core.companies (id, tenant_id, name) VALUES (%s, %s, 'Sonalim SA')", (str(ULID()), TENANT))
    snapshots, presence = FakeSnapshots(EMPLOYEES), FakePresence(SUMMARIES)
    return {"db": db, "a": a, "b": b, "snapshots": snapshots, "presence": presence, "payslips": PayslipService(db)}


def _approved(world, period=SEPT):
    return approved_run(world["db"], tenant_id=TENANT, calculator=world["a"], approver=world["b"], period=period,
                        snapshots=world["snapshots"], presence=world["presence"])


def _payslip_id(world, run_id, employee_id="E1"):
    return world["db"].execute("SELECT id FROM payroll.payslips WHERE run_id = %s AND employee_id = %s", (run_id, employee_id)).fetchone()[0]


def test_a_payslip_reads_with_its_lines_run_and_company(world):
    run_id = _approved(world)
    payslip = world["payslips"].get_payslip(tenant_id=TENANT, payslip_id=_payslip_id(world, run_id))
    assert (payslip["period"], payslip["run_status"], payslip["full_name"]) == ("2031-09-01", "approved", "Awa Traoré")
    assert payslip["company"]["name"] == "Sonalim SA"
    assert [line["line_no"] for line in payslip["lines"]] == sorted(line["line_no"] for line in payslip["lines"])
    assert payslip["lines"][0]["code"] == "BASE" and payslip["lines"][0]["amount"] == 400000


def test_the_whole_run_prints_in_name_order(world):
    document = world["payslips"].run_print(tenant_id=TENANT, run_id=_approved(world))
    assert [payslip["full_name"] for payslip in document["payslips"]] == ["Awa Traoré", "Moussa Keita"]
    assert all(payslip["lines"] for payslip in document["payslips"])


def test_payment_details_can_be_corrected_until_a_batch_is_confirmed(world):
    run_id = _approved(world)
    payslip_id = _payslip_id(world, run_id)
    payouts = PayoutService(world["db"])
    payouts.generate(tenant_id=TENANT, actor_id=world["a"], run_id=run_id)
    bad = world["payslips"].admin_update_payslip(tenant_id=TENANT, actor_id=world["a"], payslip_id=payslip_id,
                                                 changes={"payment_methods": [{**NEW_BANK[0], "share_percent": 50}]})
    assert isinstance(bad, Err) and bad.code == "PAYOUT_SPLIT_INVALID"
    fixed = world["payslips"].admin_update_payslip(tenant_id=TENANT, actor_id=world["a"], payslip_id=payslip_id,
                                                   changes={"payment_methods": NEW_BANK, "note": "New account from 15 Sept"})
    assert isinstance(fixed, Ok) and fixed.value["snapshot"]["payment_methods"][0]["bank_name"] == "Ecobank"
    assert payouts.list_batches(tenant_id=TENANT, run_id=run_id) == []  # stale batches dropped
    batches = payouts.generate(tenant_id=TENANT, actor_id=world["a"], run_id=run_id).value
    assert "ECOBANK" in {batch["group_key"] for batch in batches}
    payouts.confirm_batch(tenant_id=TENANT, actor_id=world["a"], batch_id=batches[0]["id"])
    frozen = world["payslips"].admin_update_payslip(tenant_id=TENANT, actor_id=world["a"], payslip_id=payslip_id, changes={"payment_methods": NEW_BANK})
    assert isinstance(frozen, Err) and frozen.code == "PAYOUT_CONFIRMED"
    audit = world["db"].execute("SELECT count(*) FROM core.audit_log WHERE entity_id = %s AND action = 'payslip.updated'", (payslip_id,)).fetchone()[0]
    assert audit == 1


def test_a_paid_run_payslip_cannot_be_edited(world):
    run_id = _approved(world)
    world["db"].execute("UPDATE payroll.runs SET status = 'paid' WHERE id = %s", (run_id,))
    refused = world["payslips"].admin_update_payslip(tenant_id=TENANT, actor_id=world["a"], payslip_id=_payslip_id(world, run_id), changes={"note": "x"})
    assert isinstance(refused, Err) and refused.code == "RUN_LOCKED"


def test_only_a_final_settlement_has_a_work_certificate(world):
    run_id = _approved(world)
    refused = world["payslips"].certificate(tenant_id=TENANT, payslip_id=_payslip_id(world, run_id))
    assert isinstance(refused, Err) and refused.code == "NOT_FOUND"
    leaving = snapshot("E9", employee_no="M-009", full_name="Seydou Coulibaly", hire_date=datetime.date(2019, 9, 15),
                       termination_date=datetime.date(2031, 9, 15), termination_reason="resignation")
    runs = RunService(world["db"], snapshots=FakeSnapshots([leaving]), presence=FakePresence({"E9": {"scheduled_days": 10, "worked_days": 10}}))
    off_cycle = runs.create_run(tenant_id=TENANT, actor_id=world["a"], period=SEPT, run_type="off_cycle").value["id"]
    runs.add_final_settlement(tenant_id=TENANT, actor_id=world["a"], run_id=off_cycle, employee_id="E9")
    runs.calculate(tenant_id=TENANT, actor_id=world["a"], run_id=off_cycle)
    certificate = world["payslips"].certificate(tenant_id=TENANT, payslip_id=_payslip_id(world, off_cycle, "E9")).value
    assert (certificate["full_name"], certificate["hire_date"], certificate["termination_date"], certificate["termination_reason"]) == (
        "Seydou Coulibaly", "2019-09-15", "2031-09-15", "resignation")


def test_variance_compares_with_last_months_approved_run(world):
    august = _approved(world, period=AUG)
    runs = RunService(world["db"], snapshots=world["snapshots"], presence=world["presence"])
    september = runs.create_run(tenant_id=TENANT, actor_id=world["a"], period=SEPT, run_type="regular").value["id"]
    InputService(world["db"], snapshots=world["snapshots"]).add_run_input(
        tenant_id=TENANT, actor_id=world["a"], run_id=september, employee_id="E1", component_code="BONUS", amount=D(25000))
    runs.calculate(tenant_id=TENANT, actor_id=world["a"], run_id=september)
    variance = world["payslips"].variance(tenant_id=TENANT, run_id=september)
    assert (variance["previous_run_id"], variance["previous_period"]) == (august, "2031-08-01")
    rows = {row["employee_id"]: row for row in variance["rows"]}
    assert (rows["E1"]["change"], rows["E1"]["delta_gross"]) == ("changed", 25000)
    assert rows["E2"]["change"] == "same" and variance["rows"][0]["employee_id"] == "E1"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python -m pytest modules/payroll/api/test_payslip_service_integration.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'modules.payroll.api.payslip_service'`.

- [ ] **Step 3: Write `payslip_service.py`**

```python
"""Payslips as people read them: detail, print data, the work certificate, the admin edit, and the
comparison with last month."""
from __future__ import annotations

import datetime
from dataclasses import asdict
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.payroll.api.company import company_header
from modules.payroll.api.rows import fetch_all, fetch_one, jsonable
from modules.payroll.api.run_state import locked
from modules.payroll.domain.loans import add_months
from modules.payroll.domain.payouts import validate_methods
from modules.payroll.domain.variance import compare

_COLUMNS = ("p.id, p.run_id, p.employee_id, p.employee_no, p.full_name, p.department_id, p.gross, p.contributable, p.taxable, "
            "p.employee_contrib, p.employer_contrib, p.employer_charges, p.its, p.deductions, p.net, p.employer_cost, "
            "p.warnings, p.rule_set_status, p.note")
_DETAIL = f"SELECT {_COLUMNS}, p.snapshot, r.period, r.run_type, r.status AS run_status FROM payroll.payslips p JOIN payroll.runs r ON r.id = p.run_id"
_LINES = "SELECT payslip_id, line_no, section, code, name_en, name_fr, base, qty, rate, amount FROM payroll.payslip_lines"


class PayslipService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    def list_payslips(self, *, tenant_id: str, run_id: str) -> list[dict[str, Any]]:
        return jsonable(fetch_all(self.connection, f"SELECT {_COLUMNS} FROM payroll.payslips p WHERE p.tenant_id = %s AND p.run_id = %s ORDER BY p.full_name",
                                  (tenant_id, run_id)))

    def _with_lines(self, payslips: list[dict[str, Any]], company: dict[str, Any]) -> list[dict[str, Any]]:
        if not payslips:
            return []
        lines = fetch_all(self.connection, _LINES + " WHERE payslip_id = ANY(%s::text[]) ORDER BY payslip_id, line_no",
                          ([payslip["id"] for payslip in payslips],))
        by_payslip: dict[str, list[dict[str, Any]]] = {}
        for line in lines:
            by_payslip.setdefault(line.pop("payslip_id"), []).append(line)
        documents = []
        for payslip in payslips:
            document = jsonable(payslip)
            document["lines"] = jsonable(by_payslip.get(payslip["id"], []))
            document["company"] = company
            documents.append(document)
        return documents

    def get_payslip(self, *, tenant_id: str, payslip_id: str) -> dict[str, Any] | None:
        row = fetch_one(self.connection, _DETAIL + " WHERE p.tenant_id = %s AND p.id = %s", (tenant_id, payslip_id))
        if row is None:
            return None
        return self._with_lines([row], company_header(self.connection, tenant_id))[0]

    def run_print(self, *, tenant_id: str, run_id: str) -> dict[str, Any] | None:
        run = fetch_one(self.connection, "SELECT id, period, run_type, label, status FROM payroll.runs WHERE tenant_id = %s AND id = %s", (tenant_id, run_id))
        if run is None:
            return None
        rows = fetch_all(self.connection, _DETAIL + " WHERE p.tenant_id = %s AND p.run_id = %s ORDER BY p.full_name", (tenant_id, run_id))
        company = company_header(self.connection, tenant_id)
        return {"run": jsonable(run), "company": company, "payslips": self._with_lines(rows, company)}

    def certificate(self, *, tenant_id: str, payslip_id: str) -> Result[dict[str, Any]]:
        payslip = self.get_payslip(tenant_id=tenant_id, payslip_id=payslip_id)
        if payslip is None or not payslip["snapshot"].get("settlement"):
            return Err("NOT_FOUND", "no work certificate: this payslip is not a final settlement",
                       "pas de certificat de travail : ce bulletin n'est pas un solde de tout compte")
        employee = payslip["snapshot"]["employee"]
        return Ok({"company": payslip["company"], "full_name": payslip["full_name"], "employee_no": payslip["employee_no"],
                   "hire_date": employee.get("hire_date"), "termination_date": employee.get("termination_date"),
                   "termination_reason": employee.get("termination_reason"), "position_id": employee.get("position_id"),
                   "contract_type": (employee.get("contract") or {}).get("contract_type"),
                   "issued_on": datetime.date.today().isoformat()})

    def admin_update_payslip(self, *, tenant_id: str, actor_id: str, payslip_id: str, changes: dict[str, Any]) -> Result[dict[str, Any]]:
        row = fetch_one(self.connection, "SELECT p.id, p.run_id, p.snapshot, p.note, r.status FROM payroll.payslips p JOIN payroll.runs r ON r.id = p.run_id "
                                         "WHERE p.tenant_id = %s AND p.id = %s FOR UPDATE OF p", (tenant_id, payslip_id))
        if row is None:
            return Err("NOT_FOUND", "payslip not found", "bulletin introuvable")
        unknown = sorted(set(changes) - {"note", "payment_methods"})
        if unknown:
            return Err("PAYSLIP_INVALID", f"only the note and the payment details can be edited ({', '.join(unknown)})",
                       f"seuls la note et les coordonnées de paiement se modifient ({', '.join(unknown)})")
        if row["status"] in ("paid", "reversed"):
            return locked(row["status"])
        snapshot = dict(row["snapshot"])
        if "payment_methods" in changes:
            checked = validate_methods(changes["payment_methods"] or [])
            if isinstance(checked, Err):
                return checked
            confirmed = self.connection.execute("SELECT 1 FROM payroll.payout_batches WHERE run_id = %s AND status = 'confirmed' LIMIT 1",
                                                (row["run_id"],)).fetchone()
            if confirmed is not None:
                return Err("PAYOUT_CONFIRMED", "a payout batch of this run is confirmed; payment details can no longer change",
                           "un lot de paiement de cette paie est confirmé ; les coordonnées de paiement ne peuvent plus changer")
            snapshot["payment_methods"] = jsonable(checked.value)
            self.connection.execute("DELETE FROM payroll.payout_batches WHERE run_id = %s", (row["run_id"],))
        note = changes.get("note", row["note"])
        self.connection.execute("UPDATE payroll.payslips SET note = %s, snapshot = %s WHERE id = %s", (note, Jsonb(snapshot), payslip_id))
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="payslip.updated", entity_type="payslip",
                     entity_id=payslip_id, payload={"changes": jsonable(changes)})
        return Ok(self.get_payslip(tenant_id=tenant_id, payslip_id=payslip_id))

    def variance(self, *, tenant_id: str, run_id: str) -> dict[str, Any] | None:
        run = fetch_one(self.connection, "SELECT id, period FROM payroll.runs WHERE tenant_id = %s AND id = %s", (tenant_id, run_id))
        if run is None:
            return None
        previous_period = add_months(run["period"], -1)
        previous_run = fetch_one(self.connection, "SELECT id FROM payroll.runs WHERE tenant_id = %s AND period = %s AND run_type = 'regular' "
                                                  "AND status IN ('approved', 'paid') ORDER BY approved_at DESC LIMIT 1", (tenant_id, previous_period))
        figures = "SELECT employee_id, employee_no, full_name, gross, net FROM payroll.payslips WHERE run_id = %s"
        current = fetch_all(self.connection, figures, (run_id,))
        previous = fetch_all(self.connection, figures, (previous_run["id"],)) if previous_run else []
        rows = [{**asdict(row), "delta_gross": row.delta_gross, "delta_net": row.delta_net, "change": row.change}
                for row in compare(current, previous)]
        zero = Decimal(0)
        totals = {"previous_gross": sum((row["gross"] for row in previous), zero), "current_gross": sum((row["gross"] for row in current), zero),
                  "previous_net": sum((row["net"] for row in previous), zero), "current_net": sum((row["net"] for row in current), zero)}
        return jsonable({"previous_run_id": previous_run["id"] if previous_run else None, "previous_period": previous_period,
                         "rows": rows, "totals": totals})
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest modules/payroll/api/test_payslip_service_integration.py core/test_error_translations.py -q`
Expected: `7 passed`, no skips.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/payroll/api/payslip_service.py backend/modules/payroll/api/test_payslip_service_integration.py
git commit -m "feat(payroll): payslip reads, print data, work certificate, admin edit, variance

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---
### Task 11: HTTP routes for runs, payslips, inputs, advances and loans

**Files:**
- Create: `backend/modules/payroll/api/routes_runs.py`, `backend/modules/payroll/api/routes_inputs.py`
- Modify: `backend/modules/payroll/api/router.py` (include both)
- Modify: `backend/modules/payroll/api/testing_support.py` (add `WrappedConnection`)
- Test: `backend/modules/payroll/api/test_runs_router_integration.py`

**Interfaces:**
- Consumes: `RunService`, `InputService`, `PayslipService`, `http.*`.
- Produces (all under `/payroll`):

| Method | Path | Permission |
|---|---|---|
| GET | `/employees?period=YYYY-MM-01` | `payroll.view_runs` (id, number, name, department, exit date — no salary) |
| GET / POST | `/runs` (`?status=`) | `view_runs` / `calculate_runs` |
| GET / PATCH / DELETE | `/runs/{id}` | `view_runs` / `calculate_runs` / `calculate_runs` |
| POST | `/runs/{id}/calculate` | `calculate_runs` |
| POST | `/runs/{id}/approve` | `approve_runs` |
| POST | `/runs/{id}/reverse` (`{reason}`) | `reverse_runs` |
| GET | `/runs/{id}/payslips`, `/runs/{id}/variance`, `/runs/{id}/print` | `view_runs` |
| GET / POST | `/runs/{id}/final-settlements` | `view_runs` / `calculate_runs` |
| PATCH / DELETE | `/runs/{id}/final-settlements/{sid}` | `calculate_runs` |
| GET | `/payslips/{id}`, `/payslips/{id}/certificate` | `view_runs` |
| PATCH | `/payslips/{id}` (`note`, `payment_methods`) | `admin_payslips` |
| GET | `/runs/{id}/input-components`, `/runs/{id}/inputs` | `view_runs` |
| POST | `/runs/{id}/inputs` | `manage_inputs` |
| PATCH / DELETE | `/run-inputs/{id}` | `manage_inputs` |
| GET / POST | `/advances` (`?status=`) | `view_runs` / `manage_inputs` |
| PATCH | `/advances/{id}`; POST `/advances/{id}/approve`, `/advances/{id}/cancel` | `manage_inputs` |
| GET / POST | `/loans` (`?status=`) | `view_runs` / `manage_inputs` |
| PATCH | `/loans/{id}`; POST `/loans/{id}/cancel` | `manage_inputs` |

  PATCH bodies are dumped with `exclude_unset=True`, so a field left out is unchanged and a sent `null` clears it.
- `testing_support.WrappedConnection(connection)` — the fixture's connection with `commit`/`rollback` as no-ops and context-manager support.

- [ ] **Step 1: Add `WrappedConnection` to `testing_support.py`**

```python
class WrappedConnection:
    """The `db` fixture's connection for router tests: the routes' commit/rollback become no-ops so
    the fixture's final rollback still undoes everything."""

    def __init__(self, connection) -> None:
        self._connection = connection

    def __getattr__(self, name: str):
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

- [ ] **Step 2: Write the failing router tests**

Create `backend/modules/payroll/api/test_runs_router_integration.py`:

```python
"""Runs, payslips and inputs over HTTP: who may do what, four-eyes, statuses of refusals."""
from __future__ import annotations

import datetime

import pytest
from fastapi import FastAPI

pytest.importorskip("httpx", reason="the FastAPI test client needs httpx (requirements-dev.txt)")
from fastapi.testclient import TestClient  # noqa: E402

from core.tenancy import TenantContext, require_session  # noqa: E402
from modules.payroll.api import http  # noqa: E402
from modules.payroll.api.router import router  # noqa: E402
from modules.payroll.api.testing_support import (  # noqa: E402
    FakePresence, FakeSnapshots, WrappedConnection, make_user, set_country, snapshot, store_rule_set,
)

TENANT = "payroll-runs-router-test"
EMPLOYEES = [snapshot("E1", employee_no="M-001", full_name="Awa Traoré")]
SUMMARIES = {"E1": {"scheduled_days": 22, "worked_days": 22}}


@pytest.fixture
def world(db, monkeypatch):
    a, b = make_user(db, TENANT), make_user(db, TENANT)
    set_country(db, tenant_id=TENANT, actor_id=a)
    store_rule_set(db, tenant_id=TENANT, actor_id=a, valid_from=datetime.date(2031, 1, 1))
    wrapped = WrappedConnection(db)
    monkeypatch.setattr(http, "get_connection", lambda: wrapped)
    monkeypatch.setattr("core.tenancy.get_connection", lambda: wrapped)
    snapshots, presence = FakeSnapshots(EMPLOYEES), FakePresence(SUMMARIES)
    for module in ("modules.payroll.api.run_service", "modules.payroll.api.input_service"):
        monkeypatch.setattr(f"{module}.PayrollSnapshotService", lambda connection: snapshots)
    monkeypatch.setattr("modules.payroll.api.run_service.PresenceService", lambda connection: presence)
    current = {"user": a}
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_session] = lambda: TenantContext(tenant_id=TENANT, user_id=current["user"], session_token="t")

    def grant(user: str, *permissions: str) -> None:
        for permission in permissions:
            db.execute("INSERT INTO core.user_permissions (user_id, permission) VALUES (%s, %s)", (user, permission))

    return {"client": TestClient(app), "grant": grant, "a": a, "b": b, "current": current}


def _calculated_run(world) -> str:
    client = world["client"]
    created = client.post("/payroll/runs", json={"period": "2031-09-01", "run_type": "regular"})
    assert created.status_code == 201, created.text
    run_id = created.json()["id"]
    calculated = client.post(f"/payroll/runs/{run_id}/calculate")
    assert calculated.status_code == 200 and calculated.json()["status"] == "calculated", calculated.text
    return run_id


def test_the_run_lifecycle_follows_rights_and_four_eyes(world):
    world["grant"](world["a"], "payroll.view_runs", "payroll.calculate_runs")
    run_id = _calculated_run(world)
    client = world["client"]
    assert client.post(f"/payroll/runs/{run_id}/approve").status_code == 403
    world["grant"](world["a"], "payroll.approve_runs")
    same_user = client.post(f"/payroll/runs/{run_id}/approve")
    assert same_user.status_code == 409 and same_user.json()["detail"]["code"] == "SAME_USER_APPROVAL"
    world["grant"](world["b"], "payroll.view_runs", "payroll.approve_runs")
    world["current"]["user"] = world["b"]
    approved = client.post(f"/payroll/runs/{run_id}/approve")
    assert approved.status_code == 200 and approved.json()["status"] == "approved"
    assert client.post(f"/payroll/runs/{run_id}/reverse", json={"reason": "x"}).status_code == 403


def test_reading_payslips_and_variance_needs_view_runs(world):
    world["grant"](world["a"], "payroll.view_runs", "payroll.calculate_runs")
    run_id = _calculated_run(world)
    client = world["client"]
    payslips = client.get(f"/payroll/runs/{run_id}/payslips")
    assert payslips.status_code == 200 and payslips.json()[0]["employee_no"] == "M-001"
    payslip = client.get(f"/payroll/payslips/{payslips.json()[0]['id']}")
    assert payslip.status_code == 200 and payslip.json()["lines"]
    assert client.get(f"/payroll/runs/{run_id}/variance").json()["rows"][0]["change"] == "new"
    world["current"]["user"] = world["b"]
    assert client.get(f"/payroll/runs/{run_id}/payslips").status_code == 403


def test_editing_a_payslip_needs_admin_payslips(world):
    world["grant"](world["a"], "payroll.view_runs", "payroll.calculate_runs")
    run_id = _calculated_run(world)
    client = world["client"]
    payslip_id = client.get(f"/payroll/runs/{run_id}/payslips").json()[0]["id"]
    assert client.patch(f"/payroll/payslips/{payslip_id}", json={"note": "checked"}).status_code == 403
    world["grant"](world["a"], "payroll.admin_payslips")
    edited = client.patch(f"/payroll/payslips/{payslip_id}", json={"note": "checked"})
    assert edited.status_code == 200 and edited.json()["note"] == "checked"


def test_the_employee_list_carries_no_salary(world):
    world["grant"](world["a"], "payroll.view_runs")
    rows = world["client"].get("/payroll/employees", params={"period": "2031-09-01"}).json()
    assert rows == [{"employee_id": "E1", "employee_no": "M-001", "full_name": "Awa Traoré", "department_id": "dept-a", "termination_date": None}]


def test_inputs_need_manage_inputs_and_a_bad_input_is_422(world):
    world["grant"](world["a"], "payroll.view_runs", "payroll.calculate_runs")
    client = world["client"]
    run_id = client.post("/payroll/runs", json={"period": "2031-09-01", "run_type": "regular"}).json()["id"]
    body = {"employee_id": "E1", "component_code": "BONUS", "amount": 25000}
    assert client.post(f"/payroll/runs/{run_id}/inputs", json=body).status_code == 403
    world["grant"](world["a"], "payroll.manage_inputs")
    assert client.post(f"/payroll/runs/{run_id}/inputs", json=body).status_code == 201
    refused = client.post(f"/payroll/runs/{run_id}/inputs", json={**body, "component_code": "BASE"})
    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "INPUT_INVALID"
    assert [item["code"] for item in client.get(f"/payroll/runs/{run_id}/input-components").json()] == ["HOUSING", "TRANSPORT", "MEAL", "BONUS", "CANTEEN"]
```

- [ ] **Step 3: Run them to verify they fail**

Run: `.venv/Scripts/python -m pytest modules/payroll/api/test_runs_router_integration.py -q`
Expected: FAIL — 404 on `POST /payroll/runs` (routes not declared).

- [ ] **Step 4: Write `routes_runs.py`**

```python
"""HTTP routes for runs, payslips and final settlements (Payroll → Runs)."""
from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel

from core.tenancy import TenantContext, require_permission
from modules.payroll.api import http, run_service
from modules.payroll.api.payslip_service import PayslipService
from modules.payroll.api.run_service import RunService

router = APIRouter()


class RunBody(BaseModel):
    period: datetime.date
    run_type: str
    label: str | None = None
    employee_ids: list[str] | None = None


class RunPatch(BaseModel):
    label: str | None = None
    employee_ids: list[str] | None = None


class ReverseBody(BaseModel):
    reason: str


class SettlementBody(BaseModel):
    employee_id: str
    unused_leave_days: Decimal = Decimal(0)
    notice_months: Decimal = Decimal(0)


class SettlementPatch(BaseModel):
    unused_leave_days: Decimal | None = None
    notice_months: Decimal | None = None


class PayslipPatch(BaseModel):
    note: str | None = None
    payment_methods: list[dict[str, Any]] | None = None


VIEW = require_permission("payroll.view_runs")
CALCULATE = require_permission("payroll.calculate_runs")


@router.get("/employees")
def employees(period: datetime.date, tenant: TenantContext = Depends(VIEW)):
    """Who can appear on a payslip that month — names only; salaries stay behind the payslips."""
    with http.get_connection() as connection:
        found = run_service.PayrollSnapshotService(connection).employees_for_period(tenant_id=tenant.tenant_id, period=period, employee_ids=None)
    keys = ("employee_id", "employee_no", "full_name", "department_id", "termination_date")
    return [{key: (item.get(key).isoformat() if key == "termination_date" and item.get(key) else item.get(key)) for key in keys}
            for item in sorted(found, key=lambda employee: employee["full_name"])]


@router.get("/runs")
def list_runs(status_filter: str | None = None, tenant: TenantContext = Depends(VIEW)):
    with http.get_connection() as connection:
        return RunService(connection).list_runs(tenant_id=tenant.tenant_id, status=status_filter)


@router.post("/runs", status_code=status.HTTP_201_CREATED)
def create_run(body: RunBody, tenant: TenantContext = Depends(CALCULATE)):
    with http.get_connection() as connection:
        return http.finish(connection, RunService(connection).create_run(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, **body.model_dump()))


@router.get("/runs/{run_id}")
def get_run(run_id: str, tenant: TenantContext = Depends(VIEW)):
    with http.get_connection() as connection:
        return http.found(RunService(connection).get_run(tenant_id=tenant.tenant_id, run_id=run_id), "payroll run", "paie")


@router.patch("/runs/{run_id}")
def update_run(run_id: str, body: RunPatch, tenant: TenantContext = Depends(CALCULATE)):
    with http.get_connection() as connection:
        result = RunService(connection).update_run(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, run_id=run_id,
                                                   changes=body.model_dump(exclude_unset=True))
        return http.finish(connection, result)


@router.delete("/runs/{run_id}")
def delete_run(run_id: str, tenant: TenantContext = Depends(CALCULATE)):
    with http.get_connection() as connection:
        return http.finish(connection, RunService(connection).delete_run(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, run_id=run_id))


@router.post("/runs/{run_id}/calculate")
def calculate_run(run_id: str, tenant: TenantContext = Depends(CALCULATE)):
    with http.get_connection() as connection:
        return http.finish(connection, RunService(connection).calculate(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, run_id=run_id))


@router.post("/runs/{run_id}/approve")
def approve_run(run_id: str, tenant: TenantContext = Depends(require_permission("payroll.approve_runs"))):
    with http.get_connection() as connection:
        return http.finish(connection, RunService(connection).approve(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, run_id=run_id))


@router.post("/runs/{run_id}/reverse")
def reverse_run(run_id: str, body: ReverseBody, tenant: TenantContext = Depends(require_permission("payroll.reverse_runs"))):
    with http.get_connection() as connection:
        result = RunService(connection).reverse(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, run_id=run_id, reason=body.reason)
        return http.finish(connection, result)


@router.get("/runs/{run_id}/payslips")
def run_payslips(run_id: str, tenant: TenantContext = Depends(VIEW)):
    with http.get_connection() as connection:
        return PayslipService(connection).list_payslips(tenant_id=tenant.tenant_id, run_id=run_id)


@router.get("/runs/{run_id}/variance")
def run_variance(run_id: str, tenant: TenantContext = Depends(VIEW)):
    with http.get_connection() as connection:
        return http.found(PayslipService(connection).variance(tenant_id=tenant.tenant_id, run_id=run_id), "payroll run", "paie")


@router.get("/runs/{run_id}/print")
def run_print(run_id: str, tenant: TenantContext = Depends(VIEW)):
    with http.get_connection() as connection:
        return http.found(PayslipService(connection).run_print(tenant_id=tenant.tenant_id, run_id=run_id), "payroll run", "paie")


@router.get("/runs/{run_id}/final-settlements")
def list_settlements(run_id: str, tenant: TenantContext = Depends(VIEW)):
    with http.get_connection() as connection:
        return RunService(connection).list_final_settlements(tenant_id=tenant.tenant_id, run_id=run_id)


@router.post("/runs/{run_id}/final-settlements", status_code=status.HTTP_201_CREATED)
def add_settlement(run_id: str, body: SettlementBody, tenant: TenantContext = Depends(CALCULATE)):
    with http.get_connection() as connection:
        result = RunService(connection).add_final_settlement(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, run_id=run_id, **body.model_dump())
        return http.finish(connection, result)


@router.patch("/runs/{run_id}/final-settlements/{settlement_id}")
def update_settlement(run_id: str, settlement_id: str, body: SettlementPatch, tenant: TenantContext = Depends(CALCULATE)):
    with http.get_connection() as connection:
        result = RunService(connection).update_final_settlement(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, run_id=run_id,
                                                                settlement_id=settlement_id, changes=body.model_dump(exclude_unset=True))
        return http.finish(connection, result)


@router.delete("/runs/{run_id}/final-settlements/{settlement_id}")
def remove_settlement(run_id: str, settlement_id: str, tenant: TenantContext = Depends(CALCULATE)):
    with http.get_connection() as connection:
        result = RunService(connection).remove_final_settlement(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, run_id=run_id,
                                                                settlement_id=settlement_id)
        return http.finish(connection, result)


@router.get("/payslips/{payslip_id}")
def get_payslip(payslip_id: str, tenant: TenantContext = Depends(VIEW)):
    with http.get_connection() as connection:
        return http.found(PayslipService(connection).get_payslip(tenant_id=tenant.tenant_id, payslip_id=payslip_id), "payslip", "bulletin")


@router.patch("/payslips/{payslip_id}")
def update_payslip(payslip_id: str, body: PayslipPatch, tenant: TenantContext = Depends(require_permission("payroll.admin_payslips"))):
    with http.get_connection() as connection:
        result = PayslipService(connection).admin_update_payslip(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, payslip_id=payslip_id,
                                                                 changes=body.model_dump(exclude_unset=True))
        return http.finish(connection, result)


@router.get("/payslips/{payslip_id}/certificate")
def certificate(payslip_id: str, tenant: TenantContext = Depends(VIEW)):
    with http.get_connection() as connection:
        return http.finish(connection, PayslipService(connection).certificate(tenant_id=tenant.tenant_id, payslip_id=payslip_id))
```

Note: `list_runs` takes the query parameter `status_filter` (the hr router's convention; `status` is the imported FastAPI module).

- [ ] **Step 5: Write `routes_inputs.py`**

```python
"""HTTP routes for monthly inputs, advances and loans (Payroll → Inputs)."""
from __future__ import annotations

import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel

from core.tenancy import TenantContext, require_permission
from modules.payroll.api import http
from modules.payroll.api.input_service import InputService

router = APIRouter()
VIEW = require_permission("payroll.view_runs")
MANAGE = require_permission("payroll.manage_inputs")


class InputBody(BaseModel):
    employee_id: str
    component_code: str
    qty: Decimal | None = None
    amount: Decimal | None = None
    note: str | None = None


class InputPatch(BaseModel):
    component_code: str | None = None
    qty: Decimal | None = None
    amount: Decimal | None = None
    note: str | None = None


class AdvanceBody(BaseModel):
    employee_id: str
    amount: Decimal
    requested_on: datetime.date
    deduct_period: datetime.date
    note: str | None = None


class AdvancePatch(BaseModel):
    amount: Decimal | None = None
    requested_on: datetime.date | None = None
    deduct_period: datetime.date | None = None
    note: str | None = None


class LoanBody(BaseModel):
    employee_id: str
    principal: Decimal
    instalment_count: int
    first_period: datetime.date
    note: str | None = None


class LoanPatch(BaseModel):
    principal: Decimal | None = None
    instalment_count: int | None = None
    first_period: datetime.date | None = None
    note: str | None = None


@router.get("/runs/{run_id}/input-components")
def input_components(run_id: str, tenant: TenantContext = Depends(VIEW)):
    with http.get_connection() as connection:
        return http.finish(connection, InputService(connection).input_components(tenant_id=tenant.tenant_id, run_id=run_id))


@router.get("/runs/{run_id}/inputs")
def list_inputs(run_id: str, tenant: TenantContext = Depends(VIEW)):
    with http.get_connection() as connection:
        return InputService(connection).list_run_inputs(tenant_id=tenant.tenant_id, run_id=run_id)


@router.post("/runs/{run_id}/inputs", status_code=status.HTTP_201_CREATED)
def add_input(run_id: str, body: InputBody, tenant: TenantContext = Depends(MANAGE)):
    with http.get_connection() as connection:
        result = InputService(connection).add_run_input(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, run_id=run_id, **body.model_dump())
        return http.finish(connection, result)


@router.patch("/run-inputs/{input_id}")
def update_input(input_id: str, body: InputPatch, tenant: TenantContext = Depends(MANAGE)):
    with http.get_connection() as connection:
        result = InputService(connection).update_run_input(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, input_id=input_id,
                                                           changes=body.model_dump(exclude_unset=True))
        return http.finish(connection, result)


@router.delete("/run-inputs/{input_id}")
def delete_input(input_id: str, tenant: TenantContext = Depends(MANAGE)):
    with http.get_connection() as connection:
        return http.finish(connection, InputService(connection).delete_run_input(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, input_id=input_id))


@router.get("/advances")
def list_advances(status_filter: str | None = None, tenant: TenantContext = Depends(VIEW)):
    with http.get_connection() as connection:
        return InputService(connection).list_advances(tenant_id=tenant.tenant_id, status=status_filter)


@router.post("/advances", status_code=status.HTTP_201_CREATED)
def create_advance(body: AdvanceBody, tenant: TenantContext = Depends(MANAGE)):
    with http.get_connection() as connection:
        return http.finish(connection, InputService(connection).create_advance(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, **body.model_dump()))


@router.patch("/advances/{advance_id}")
def update_advance(advance_id: str, body: AdvancePatch, tenant: TenantContext = Depends(MANAGE)):
    with http.get_connection() as connection:
        result = InputService(connection).update_advance(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, advance_id=advance_id,
                                                         changes=body.model_dump(exclude_unset=True))
        return http.finish(connection, result)


@router.post("/advances/{advance_id}/approve")
def approve_advance(advance_id: str, tenant: TenantContext = Depends(MANAGE)):
    with http.get_connection() as connection:
        return http.finish(connection, InputService(connection).approve_advance(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, advance_id=advance_id))


@router.post("/advances/{advance_id}/cancel")
def cancel_advance(advance_id: str, tenant: TenantContext = Depends(MANAGE)):
    with http.get_connection() as connection:
        return http.finish(connection, InputService(connection).cancel_advance(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, advance_id=advance_id))


@router.get("/loans")
def list_loans(status_filter: str | None = None, tenant: TenantContext = Depends(VIEW)):
    with http.get_connection() as connection:
        return InputService(connection).list_loans(tenant_id=tenant.tenant_id, status=status_filter)


@router.post("/loans", status_code=status.HTTP_201_CREATED)
def create_loan(body: LoanBody, tenant: TenantContext = Depends(MANAGE)):
    with http.get_connection() as connection:
        return http.finish(connection, InputService(connection).create_loan(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, **body.model_dump()))


@router.patch("/loans/{loan_id}")
def update_loan(loan_id: str, body: LoanPatch, tenant: TenantContext = Depends(MANAGE)):
    with http.get_connection() as connection:
        result = InputService(connection).update_loan(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, loan_id=loan_id,
                                                      changes=body.model_dump(exclude_unset=True))
        return http.finish(connection, result)


@router.post("/loans/{loan_id}/cancel")
def cancel_loan(loan_id: str, tenant: TenantContext = Depends(MANAGE)):
    with http.get_connection() as connection:
        return http.finish(connection, InputService(connection).cancel_loan(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, loan_id=loan_id))
```

- [ ] **Step 6: Include both routers**

`backend/modules/payroll/api/router.py` becomes:

```python
"""Every payroll endpoint hangs off this router; each area adds its own sub-router here."""
from __future__ import annotations

from fastapi import APIRouter

from modules.payroll.api.routes_inputs import router as inputs_router
from modules.payroll.api.routes_payouts import router as payouts_router
from modules.payroll.api.routes_rules import router as rules_router
from modules.payroll.api.routes_runs import router as runs_router

router = APIRouter(prefix="/payroll", tags=["payroll"])
router.include_router(rules_router)
router.include_router(runs_router)
router.include_router(inputs_router)
router.include_router(payouts_router)
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest modules/payroll core/test_error_translations.py -q`
Expected: all pass (`test_runs_router_integration.py` adds 5), no skips.

- [ ] **Step 8: Commit**

```bash
git add backend/modules/payroll/api/routes_runs.py backend/modules/payroll/api/routes_inputs.py backend/modules/payroll/api/router.py backend/modules/payroll/api/testing_support.py backend/modules/payroll/api/test_runs_router_integration.py
git commit -m "feat(payroll): HTTP routes for runs, payslips, inputs, advances and loans

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12: Declarations and the annual recap

**Files:**
- Create: `backend/modules/payroll/api/declaration_service.py`, `backend/modules/payroll/api/routes_declarations.py`
- Modify: `backend/modules/payroll/api/router.py` (include the declarations router)
- Test: `backend/modules/payroll/api/test_declarations_integration.py`

**Interfaces:**
- Consumes: `available_codes`, `build_declaration`, `annual_recap`, `to_csv`, `Declaration` (Task 3); `http.csv_response` (Task 9).
- Produces:
  - `DeclarationService(connection)`: `codes(*, tenant_id, period) -> list[str]`, `declaration(*, tenant_id, period, code) -> Result[Declaration]` (`NOT_FOUND` for a code with no line that month), `annual(*, tenant_id, year) -> Declaration`. Only payslips of **approved or paid** runs count (a calculated run is not final; a reversed one never happened).
  - `declaration_json(declaration, **extra) -> dict` (`code, columns, rows, totals` + extra keys, JSON-safe).
  - Routes (all `payroll.view_declarations`): `GET /payroll/declarations/codes?period=`, `GET /payroll/declarations?period=&code=&format=json|csv`, `GET /payroll/declarations/annual?year=&format=json|csv`. CSV file names `<code>-<YYYY-MM>.csv` and `recap-annuel-<year>.csv`.
- Identifiers on INPS/AMO rows come from `snapshot.employee.inps_no` / `amo_no` when hr's snapshot carries them (the contract does not list them — blank otherwise; see self-review).

- [ ] **Step 1: Write the failing tests**

Create `backend/modules/payroll/api/test_declarations_integration.py`:

```python
"""Declarations are built from approved or paid payslips only."""
from __future__ import annotations

import datetime

import pytest

from core.domain.result import Err
from modules.payroll.api.declaration_service import DeclarationService
from modules.payroll.api.run_service import RunService
from modules.payroll.api.testing_support import (
    FakePresence, FakeSnapshots, approved_run, make_user, set_country, snapshot, store_rule_set,
)
from modules.payroll.domain.declarations import to_csv

TENANT = "payroll-declarations-test"
SEPT, OCT = datetime.date(2031, 9, 1), datetime.date(2031, 10, 1)
EMPLOYEES = [snapshot("E1", employee_no="M-001", full_name="Awa Traoré", hire_date=datetime.date(2020, 1, 1)),
             snapshot("E2", employee_no="M-002", full_name="Moussa Keita", hire_date=datetime.date(2020, 1, 1))]
SUMMARIES = {"E1": {"scheduled_days": 22, "worked_days": 22}, "E2": {"scheduled_days": 22, "worked_days": 22}}


@pytest.fixture
def world(db):
    a, b = make_user(db, TENANT), make_user(db, TENANT)
    set_country(db, tenant_id=TENANT, actor_id=a)
    store_rule_set(db, tenant_id=TENANT, actor_id=a, valid_from=datetime.date(2031, 1, 1))
    snapshots, presence = FakeSnapshots(EMPLOYEES), FakePresence(SUMMARIES)
    september = approved_run(db, tenant_id=TENANT, calculator=a, approver=b, period=SEPT, snapshots=snapshots, presence=presence)
    runs = RunService(db, snapshots=snapshots, presence=presence)
    october = runs.create_run(tenant_id=TENANT, actor_id=a, period=OCT, run_type="regular").value["id"]
    runs.calculate(tenant_id=TENANT, actor_id=a, run_id=october)  # calculated, not approved: not declared
    return {"db": db, "september": september, "service": DeclarationService(db)}


def test_the_codes_of_the_month_come_from_the_rule_set_lines(world):
    assert world["service"].codes(tenant_id=TENANT, period=SEPT) == ["EMPLOYER_TAXES", "HEALTH", "SOCIAL", "TAX"]
    assert world["service"].codes(tenant_id=TENANT, period=OCT) == []


def test_a_contribution_declaration_lists_each_employee_with_base_and_shares(world):
    declaration = world["service"].declaration(tenant_id=TENANT, period=SEPT, code="SOCIAL").value
    assert declaration.columns == ("employee_no", "full_name", "identifier", "base", "PENSION_employee", "PENSION_employer", "total")
    assert [row["employee_no"] for row in declaration.rows] == ["M-001", "M-002"]
    first = declaration.rows[0]
    assert first["total"] == first["PENSION_employee"] + first["PENSION_employer"]


def test_an_unknown_code_is_not_found(world):
    refused = world["service"].declaration(tenant_id=TENANT, period=SEPT, code="CNSS")
    assert isinstance(refused, Err) and refused.code == "NOT_FOUND" and refused.message_fr


def test_a_reversed_run_is_not_declared(world):
    world["db"].execute("UPDATE payroll.runs SET status = 'reversed' WHERE id = %s", (world["september"],))
    assert world["service"].codes(tenant_id=TENANT, period=SEPT) == []


def test_the_annual_recap_counts_the_approved_months(world):
    recap = world["service"].annual(tenant_id=TENANT, year=2031)
    assert [(row["employee_no"], row["months"]) for row in recap.rows] == [("M-001", 1), ("M-002", 1)]
    assert to_csv(recap).splitlines()[0] == "employee_no;full_name;months;gross;employee_contrib;employer_contrib;its;net"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python -m pytest modules/payroll/api/test_declarations_integration.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'modules.payroll.api.declaration_service'`.

- [ ] **Step 3: Write `declaration_service.py`**

```python
"""Monthly declarations (INPS, AMO, ITS, employer taxes — codes come from the rule set) and the
annual recap, built from the payslips of approved or paid runs."""
from __future__ import annotations

import datetime
from typing import Any

import psycopg

from core.domain.result import Err, Ok, Result
from modules.payroll.api.rows import fetch_all, jsonable
from modules.payroll.domain.declarations import Declaration, annual_recap, available_codes, build_declaration


def declaration_json(declaration: Declaration, **extra: Any) -> dict[str, Any]:
    return jsonable({"code": declaration.code, "columns": list(declaration.columns), "rows": list(declaration.rows),
                     "totals": declaration.totals, **extra})


class DeclarationService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    def _payslips(self, tenant_id: str, where: str, params: tuple) -> list[dict[str, Any]]:
        payslips = fetch_all(
            self.connection,
            f"""
            SELECT p.id, p.employee_id, p.employee_no, p.full_name, p.snapshot->'employee' AS employee, r.period,
                   p.gross, p.employee_contrib, p.employer_contrib, p.its, p.net
            FROM payroll.payslips p JOIN payroll.runs r ON r.id = p.run_id
            WHERE p.tenant_id = %s AND r.status IN ('approved', 'paid') AND {where}
            ORDER BY p.employee_no
            """,
            (tenant_id, *params),
        )
        lines = fetch_all(self.connection, "SELECT payslip_id, section, code, base, amount, declaration_code FROM payroll.payslip_lines "
                                           "WHERE payslip_id = ANY(%s::text[])", ([payslip["id"] for payslip in payslips],)) if payslips else []
        by_payslip: dict[str, list[dict[str, Any]]] = {}
        for line in lines:
            by_payslip.setdefault(line.pop("payslip_id"), []).append(line)
        for payslip in payslips:
            employee = payslip.pop("employee") or {}
            payslip["identifiers"] = {"inps_no": employee.get("inps_no"), "amo_no": employee.get("amo_no")}
            payslip["lines"] = by_payslip.get(payslip["id"], [])
        return payslips

    def codes(self, *, tenant_id: str, period: datetime.date) -> list[str]:
        return available_codes(self._payslips(tenant_id, "r.period = %s", (period,)))

    def declaration(self, *, tenant_id: str, period: datetime.date, code: str) -> Result[Declaration]:
        built = build_declaration(code, self._payslips(tenant_id, "r.period = %s", (period,)))
        if built is None:
            return Err("NOT_FOUND", f"nothing to declare for {code} in {period:%Y-%m}", f"rien à déclarer pour {code} en {period:%m/%Y}")
        return Ok(built)

    def annual(self, *, tenant_id: str, year: int) -> Declaration:
        return annual_recap(self._payslips(tenant_id, "r.period >= %s AND r.period < %s",
                                           (datetime.date(year, 1, 1), datetime.date(year + 1, 1, 1))))
```

- [ ] **Step 4: Write `routes_declarations.py` and include it**

```python
"""HTTP routes for the monthly declarations and the annual recap (JSON or CSV)."""
from __future__ import annotations

import datetime
from typing import Literal

from fastapi import APIRouter, Depends

from core.tenancy import TenantContext, require_permission
from modules.payroll.api import http
from modules.payroll.api.declaration_service import DeclarationService, declaration_json
from modules.payroll.domain.declarations import to_csv

router = APIRouter()
VIEW = require_permission("payroll.view_declarations")


@router.get("/declarations/codes")
def declaration_codes(period: datetime.date, tenant: TenantContext = Depends(VIEW)):
    with http.get_connection() as connection:
        return DeclarationService(connection).codes(tenant_id=tenant.tenant_id, period=period)


@router.get("/declarations/annual")
def annual_recap(year: int, format: Literal["json", "csv"] = "json", tenant: TenantContext = Depends(VIEW)):
    with http.get_connection() as connection:
        recap = DeclarationService(connection).annual(tenant_id=tenant.tenant_id, year=year)
    if format == "csv":
        return http.csv_response(f"recap-annuel-{year}.csv", to_csv(recap))
    return declaration_json(recap, year=year)


@router.get("/declarations")
def declaration(period: datetime.date, code: str, format: Literal["json", "csv"] = "json", tenant: TenantContext = Depends(VIEW)):
    with http.get_connection() as connection:
        built = http.finish(connection, DeclarationService(connection).declaration(tenant_id=tenant.tenant_id, period=period, code=code))
    if format == "csv":
        return http.csv_response(f"{code.lower()}-{period:%Y-%m}.csv", to_csv(built))
    return declaration_json(built, period=period)
```

In `router.py` add `from modules.payroll.api.routes_declarations import router as declarations_router` and `router.include_router(declarations_router)`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest modules/payroll/api/test_declarations_integration.py core/test_error_translations.py -q`
Expected: `6 passed`, no skips.

- [ ] **Step 6: Commit**

```bash
git add backend/modules/payroll/api/declaration_service.py backend/modules/payroll/api/routes_declarations.py backend/modules/payroll/api/router.py backend/modules/payroll/api/test_declarations_integration.py
git commit -m "feat(payroll): monthly declarations and annual recap, JSON and CSV

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 13: Contract services — `PayrollPostingService` and `PayrollReportService`

**Files:**
- Create: `backend/modules/payroll/api/posting_service.py`, `backend/modules/payroll/api/report_service.py`
- Test: `backend/modules/payroll/api/test_contract_services_integration.py`

**Interfaces (exactly the cross-phase contract):**
- `PayrollPostingService(connection)`:
  - `posting_lines(*, tenant_id, run_id) -> list[dict]` — dicts `source_kind` in `'earning'|'deduction'|'employee_contribution'|'employer_contribution'|'employer_charge'|'tax'|'net'`, `code` (component / contribution / tax code, `'NET'` for net), `amount: Decimal` (positive), `employee_id`. Informational `relief` lines are not posted. A negative earning (unpaid absence) is folded into the same employee's `BASE` row, so every amount is positive and, per employee, `Σ earning = Σ deduction + Σ employee_contribution + Σ tax + net`.
  - `payment_lines(*, tenant_id, run_id) -> list[dict]` — `method` in `'bank'|'mobile_money'|'cash'`, `amount: Decimal`, `employee_id` (from the run's payout lines).
- `PayrollReportService(connection)`:
  - `cost_by_department(*, tenant_id, period_from, period_to) -> list[dict]` — `period (date), department_id, headcount (int), gross (Decimal), employer_cost (Decimal)` over approved/paid runs.
  - `payslips_for_employee(*, tenant_id, employee_id) -> list[dict]` — `payslip_id, run_id, period, run_type, run_status, gross, net, rule_set_status` of approved/paid runs, newest first (phase 5 self-service shows only final payslips).
- Both declared in `module.json` `provides_api` (3a Task 1).

- [ ] **Step 1: Write the failing tests**

Create `backend/modules/payroll/api/test_contract_services_integration.py`:

```python
"""The services finance (phase 4) and the HR dashboard / self-service (phase 5) call."""
from __future__ import annotations

import datetime
from collections import defaultdict
from decimal import Decimal

import pytest

from modules.payroll.api.payout_service import PayoutService
from modules.payroll.api.posting_service import PayrollPostingService
from modules.payroll.api.report_service import PayrollReportService
from modules.payroll.api.run_service import RunService
from modules.payroll.api.testing_support import (
    FakePresence, FakeSnapshots, approved_run, make_user, set_country, snapshot, store_rule_set,
)

TENANT = "payroll-contract-services-test"
SEPT, OCT = datetime.date(2031, 9, 1), datetime.date(2031, 10, 1)
D = Decimal
EMPLOYEES = [
    snapshot("E1", employee_no="M-001", full_name="Awa Traoré", department_id="dept-a", tax_dependants=2,
             components=({"component_code": "HOUSING", "amount": D(30000), "rate": None},)),
    snapshot("E2", employee_no="M-002", full_name="Moussa Keita", department_id="dept-b"),
]
SUMMARIES = {"E1": {"scheduled_days": 22, "worked_days": 22, "ot_minutes_day": 600},
             "E2": {"scheduled_days": 22, "worked_days": 20, "unpaid_absence_days": 2}}


@pytest.fixture
def world(db):
    a, b = make_user(db, TENANT), make_user(db, TENANT)
    set_country(db, tenant_id=TENANT, actor_id=a)
    store_rule_set(db, tenant_id=TENANT, actor_id=a, valid_from=datetime.date(2031, 1, 1))
    snapshots, presence = FakeSnapshots(EMPLOYEES), FakePresence(SUMMARIES)
    september = approved_run(db, tenant_id=TENANT, calculator=a, approver=b, period=SEPT, snapshots=snapshots, presence=presence)
    runs = RunService(db, snapshots=snapshots, presence=presence)
    october = runs.create_run(tenant_id=TENANT, actor_id=a, period=OCT, run_type="regular").value["id"]
    runs.calculate(tenant_id=TENANT, actor_id=a, run_id=october)
    return {"db": db, "a": a, "september": september, "october": october}


def test_posting_lines_are_positive_and_balance_per_employee(world):
    lines = PayrollPostingService(world["db"]).posting_lines(tenant_id=TENANT, run_id=world["september"])
    assert lines and all(line["amount"] > 0 for line in lines)
    assert {line["source_kind"] for line in lines} == {"earning", "employee_contribution", "employer_contribution", "employer_charge", "tax", "net"}
    sums: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
    for line in lines:
        sums[(line["employee_id"], line["source_kind"])] += line["amount"]
    for employee in ("E1", "E2"):
        credit = sum(sums[(employee, kind)] for kind in ("deduction", "employee_contribution", "tax", "net"))
        assert sums[(employee, "earning")] == credit, employee


def test_unpaid_absence_is_folded_into_the_base_row(world):
    lines = PayrollPostingService(world["db"]).posting_lines(tenant_id=TENANT, run_id=world["september"])
    earnings = {line["code"]: line["amount"] for line in lines if line["employee_id"] == "E2" and line["source_kind"] == "earning"}
    assert "UNPAID_ABSENCE" not in earnings and earnings["BASE"] == D(360000)
    net = world["db"].execute("SELECT net FROM payroll.payslips WHERE run_id = %s AND employee_id = 'E1'", (world["september"],)).fetchone()[0]
    assert {"source_kind": "net", "code": "NET", "amount": net, "employee_id": "E1"} in lines


def test_payment_lines_follow_the_payout_batches(world):
    PayoutService(world["db"]).generate(tenant_id=TENANT, actor_id=world["a"], run_id=world["september"])
    lines = PayrollPostingService(world["db"]).payment_lines(tenant_id=TENANT, run_id=world["september"])
    nets = world["db"].execute("SELECT SUM(net) FROM payroll.payslips WHERE run_id = %s", (world["september"],)).fetchone()[0]
    assert {line["method"] for line in lines} == {"bank"} and sum(line["amount"] for line in lines) == nets


def test_cost_by_department_counts_only_final_runs(world):
    rows = PayrollReportService(world["db"]).cost_by_department(tenant_id=TENANT, period_from=SEPT, period_to=OCT)
    assert [(row["period"], row["department_id"], row["headcount"]) for row in rows] == [(SEPT, "dept-a", 1), (SEPT, "dept-b", 1)]
    assert all(row["employer_cost"] > row["gross"] > 0 for row in rows)


def test_an_employee_sees_only_final_payslips(world):
    payslips = PayrollReportService(world["db"]).payslips_for_employee(tenant_id=TENANT, employee_id="E1")
    assert [(item["run_id"], item["period"], item["run_status"]) for item in payslips] == [(world["september"], SEPT, "approved")]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python -m pytest modules/payroll/api/test_contract_services_integration.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'modules.payroll.api.posting_service'`.

- [ ] **Step 3: Write `posting_service.py`**

```python
"""What finance posts for a payroll run (cross-phase contract, phase 3 -> phase 4).

posting_lines: one row per (employee, source_kind, code), amounts positive. An earning line with a
negative amount (unpaid absence) is folded into the same employee's BASE row, so that per employee
sum(earning) = sum(deduction) + sum(employee_contribution) + sum(tax) + net, and employer
contributions / charges are posted on their own (expense against liability).
payment_lines: how the net left the company, from the run's payout lines.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

import psycopg

from modules.payroll.api.rows import fetch_all
from modules.payroll.domain.rules import BASE

ZERO = Decimal(0)


class PayrollPostingService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    def posting_lines(self, *, tenant_id: str, run_id: str) -> list[dict[str, Any]]:
        rows = fetch_all(
            self.connection,
            """
            SELECT p.employee_id, l.section, l.code, SUM(l.amount) AS amount
            FROM payroll.payslip_lines l JOIN payroll.payslips p ON p.id = l.payslip_id
            WHERE p.tenant_id = %s AND p.run_id = %s AND l.section <> 'relief'
            GROUP BY p.employee_id, l.section, l.code
            """,
            (tenant_id, run_id),
        )
        totals: dict[tuple[str, str, str], Decimal] = {}
        for row in rows:
            code = BASE if row["section"] == "earning" and row["amount"] < 0 else row["code"]
            key = (row["employee_id"], row["section"], code)
            totals[key] = totals.get(key, ZERO) + row["amount"]
        nets = fetch_all(self.connection, "SELECT employee_id, net FROM payroll.payslips WHERE tenant_id = %s AND run_id = %s AND net > 0",
                         (tenant_id, run_id))
        for row in nets:
            totals[(row["employee_id"], "net", "NET")] = row["net"]
        return [{"source_kind": kind, "code": code, "amount": amount, "employee_id": employee_id}
                for (employee_id, kind, code), amount in sorted(totals.items()) if amount > 0]

    def payment_lines(self, *, tenant_id: str, run_id: str) -> list[dict[str, Any]]:
        rows = fetch_all(
            self.connection,
            """
            SELECT b.method, l.employee_id, SUM(l.amount) AS amount
            FROM payroll.payout_lines l JOIN payroll.payout_batches b ON b.id = l.batch_id
            WHERE b.tenant_id = %s AND b.run_id = %s
            GROUP BY b.method, l.employee_id
            ORDER BY l.employee_id, b.method
            """,
            (tenant_id, run_id),
        )
        return [{"method": row["method"], "amount": row["amount"], "employee_id": row["employee_id"]} for row in rows]
```

- [ ] **Step 4: Write `report_service.py`**

```python
"""Payroll figures for the HR dashboard and self-service (cross-phase contract, phase 3 -> phase 5).
Only approved or paid runs count: a calculated run is not final and a reversed one never happened."""
from __future__ import annotations

import datetime
from typing import Any

import psycopg

from modules.payroll.api.rows import fetch_all


class PayrollReportService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    def cost_by_department(self, *, tenant_id: str, period_from: datetime.date, period_to: datetime.date) -> list[dict[str, Any]]:
        return fetch_all(
            self.connection,
            """
            SELECT r.period, p.department_id, COUNT(DISTINCT p.employee_id)::int AS headcount,
                   SUM(p.gross) AS gross, SUM(p.employer_cost) AS employer_cost
            FROM payroll.payslips p JOIN payroll.runs r ON r.id = p.run_id
            WHERE p.tenant_id = %s AND r.status IN ('approved', 'paid') AND r.period BETWEEN %s AND %s
            GROUP BY r.period, p.department_id
            ORDER BY r.period, p.department_id
            """,
            (tenant_id, period_from, period_to),
        )

    def payslips_for_employee(self, *, tenant_id: str, employee_id: str) -> list[dict[str, Any]]:
        return fetch_all(
            self.connection,
            """
            SELECT p.id AS payslip_id, p.run_id, r.period, r.run_type, r.status AS run_status, p.gross, p.net, p.rule_set_status
            FROM payroll.payslips p JOIN payroll.runs r ON r.id = p.run_id
            WHERE p.tenant_id = %s AND p.employee_id = %s AND r.status IN ('approved', 'paid')
            ORDER BY r.period DESC, r.created_at DESC
            """,
            (tenant_id, employee_id),
        )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest modules/payroll -q`
Expected: all pass (`test_contract_services_integration.py` adds 5), no skips.

- [ ] **Step 6: Commit**

```bash
git add backend/modules/payroll/api/posting_service.py backend/modules/payroll/api/report_service.py backend/modules/payroll/api/test_contract_services_integration.py
git commit -m "feat(payroll): PayrollPostingService and PayrollReportService contract services

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Self-review (3b, Tasks 1–13)

**1. Spec coverage.** Runs draft→calculated→approved→paid/reversed, regular + off-cycle (Tasks 4, 6, 8);
`run_inputs` (Task 5); advances + loans + instalments (Task 5); final settlement off-cycle with prorated
salary, leave/notice/severance indemnities and a certificate of work (Tasks 7, 10); `PRESENCE_NOT_CLOSED`,
`SAME_USER_APPROVAL`, `RULESET_NOT_CONFIRMED`, `RUN_LOCKED`, `NET_NEGATIVE` carry (Tasks 6, 8); payslips +
lines with the input snapshot, idempotent recalculation (Task 6); printable payslip data and whole-run print
(Task 10 serves the JSON; the `/payroll/payslips/:id/print` and run-print React pages are named explicitly as
Task 14+ of the not-yet-written continuation plan, `2026-09-25-hr-p3c-payroll-frontend-seed.md`); payout
batches with bank CSV per template, mobile-money CSV per operator, cash sheet with billetage (Task 9); events
`payroll.run.approved/paid/reversed` via outbox + `CATALOG.md` (Task 8); `PayrollPostingService` and
`PayrollReportService` exactly per contract (Task 13); INPS/AMO/ITS/employer-tax declarations + annual recap,
CSV and JSON (Task 12); HTTP routes for every service, permissioned per the spec's list (Task 11).
**Not in this file** (see the Scope note above): the `/payroll/*` frontend screens and the Mali draft seed —
both still owed by `2026-09-25-hr-p3c-payroll-frontend-seed.md`, which this plan names as the explicit
continuation rather than silently dropping them.

**2. Placeholder scan.** No `TODO`/`TBD`/"add validation" placeholders; every step has runnable code. One
loose end deliberately flagged rather than papered over: `DeclarationService._payslips` reads
`inps_no`/`amo_no` from `snapshot.employee`, but the phase 1→3 contract's employee dict (see the interfaces
file) does not list those keys among the fields it promises — they exist on `hr.employees` per the spec's
Phase 1 section but are not yet in `PayrollSnapshotService`'s contract shape. The declaration still works
(the identifier column is blank until phase 1 adds the field, tested indirectly by
`test_a_contribution_declaration_lists_each_employee_with_base_and_shares` not asserting a value for it) —
this is called out here rather than assumed silently correct.

**3. Type consistency.** `OneOffInput.source_kind` values (`"input" | "advance" | "loan_instalment" |
"carry_forward"`) are the same set from `domain/inputs.SOURCE_KINDS` (3a) through `net.deduction_lines`
ordering (3a), `InputService.due_deductions` (Task 5), `RunService._write_payslip`'s `marks` dict (Task 6) and
`payroll.carry_forwards.source_kind`'s CHECK constraint (Task 4) — one vocabulary, never renamed en route.
`RunService.calculate`/`approve`/`reverse`/`mark_paid` all return the same `get_run(...)` shape (Task 4's
`RUN_SELECT`), so a frontend polling after any action sees one consistent run document. `PayslipService`,
`DeclarationService` and `PayrollPostingService` each read `payroll.payslip_lines` with the same column names
the engine wrote in 3a's `PayslipLine` (`section, code, base, qty, rate, amount, declaration_code`) — no
independent second schema for "what a line looks like".

**4. Review Focus.** Each of the five items has its owning task and test, listed with the section itself
above; re-confirmed here: (1) rule set re-confirmed after calculation → Task 8
`test_a_rule_set_confirmed_after_calculation_needs_a_recalculation`; (2) presence reopened after calculation →
Task 8 `test_approval_is_refused_when_presence_was_reopened`; (3) reversal blocked by a later approved run's
carried deduction → Task 8 `test_a_run_whose_carry_a_later_approved_run_took_cannot_be_reversed` (and the
companion `test_reversing_sends_a_later_calculated_run_that_took_its_carry_back_to_draft` for the non-final
case); (4) payment details corrected before/after confirmation → Task 9
`test_confirmed_payouts_are_not_regenerated` + Task 10 `test_payment_details_can_be_corrected_until_a_batch_is_confirmed`,
and bad shares named per employee → Task 9 `test_a_bad_split_names_the_employee`; (5) an employee settled
off-cycle mid-month is left out of the regular run → Task 7 `test_the_regular_run_leaves_out_an_employee_settled_off_cycle`.
No gaps found beyond the frontend/seed scope split already called out in section 1.

---

## Self-review (3a, recap)

Plan 3a's own self-review is at the end of `2026-09-25-hr-p3a-payroll-engine.md`. Restated briefly for this
combined report: every rule table, engine step (proration, contributable base with ceilings, contributions,
taxable/ITS with family relief, net-negative carry, employer cost, rounding per rule set) and the
draft/confirmed lifecycle are covered by Tasks 1–11, with golden tests on a synthetic (non-Mali) rule set: no
placeholders, no Mali value anywhere in `domain/` or its tests, and the `RuleSet`/`PayslipLine` types 3b
Task 1 (`snapshot_mapping.py`) and Task 6 (`calculate` orchestration) consume match exactly what 3a Task 2 and
Task 9 define.
