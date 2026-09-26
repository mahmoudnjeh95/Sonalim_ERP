# HR Phase 5 — Analytics & Employee Self-Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give HR a month dashboard in which every figure comes from a recorded field, and give each employee linked to a user account a read-only `/me` space (their file, their own payslips, their leave balance and leave requests) that can never show another employee's data.

**Architecture:** The dashboard arithmetic is pure code in `hr/domain/dashboard.py` and `hr/domain/expiry.py`, tested without a database. A thin `HrAnalyticsService` combines the phase 1–3 contract services: `PayrollSnapshotService`, `PresenceService` and `PayrollReportService`. `payroll` already depends on `hr`, so hr reaches payroll only through a lazy import in `hr/api/payroll_bridge.py`, and hr lists payroll under `optional_depends`. Self-service always finds the employee from the session user through `EmployeeService.get_by_user` and never takes an employee id from the caller. Payroll gets one guard, `require_payslip_reader`, so its existing print route also serves the payslip's owner. The frontend pages live under `features/hr/` and follow the house rules: one branded loader per screen, Skeleton for the blocks inside it, and useTableColumns, FilterTabs and ColumnFilterRow on every table.

**Tech Stack:** FastAPI, raw SQL via psycopg, pytest (`db` fixture); React 18 + TS, TanStack Query v5, Recharts, React Hook Form + Zod, Tailwind + `components/ui`.

**Spec:** `docs/superpowers/specs/2026-09-25-hr-payroll-finance-design.md` (section "Phase 5 — HR analytics & self-service", plus "Permissions" and "Errors") and the cross-phase contract `docs/superpowers/plans/2026-09-25-hr-payroll-finance-interfaces.md`. The executor reads both.

## Global Constraints

- Phases 1–4 are merged. From other phases, use only the contract services: `PayrollSnapshotService.employees_for_period`, `PresenceService.month_summary` / `is_month_closed`, `EmployeeService.get_by_user`, `PayrollReportService.cost_by_department` / `payslips_for_employee`. Never read another module's tables. Hr reads its own tables freely.
- Money is `NUMERIC(18,0)` XOF. Python uses `decimal.Decimal`, never float. The UI prints amounts as whole francs followed by `F CFA`.
- A "period" is a `datetime.date` equal to the first day of the month.
- "Every figure comes from a recorded field listed above; no targets invented" (spec, phase 5). There are no thresholds and no good/bad colours. A change is shown with its sign in one neutral colour.
- Every refusal is `Err(code, message, message_fr)`. Routers raise `HTTPException(status, err_detail(err))`.
- Every user-facing string has an `en` and an `fr` key in `frontend/src/lib/i18n.tsx`. `tsc` fails when the `fr` key is missing.
- Every table uses `useTableColumns` + `ColumnVisibilityMenu`, `FilterTabs` for closed enums, and `ColumnFilterRow`/`useColumnFilters` for text and number columns.
- One branded loader (`AppLoader`) per screen, shown on the first load only. Blocks inside the screen use `Skeleton` and stay mounted while data changes.
- Self-service identifies the employee **only** from the session's user. No `/me` endpoint accepts an employee id.
- Hr migrations for this phase start at `0020_*`. Never edit a migration that has already been applied.
- Every mutation is audited. The only mutation in this phase is creating a leave request, which goes through phase 2's `LeaveRequestService` (`modules/hr/api/leave_service.py`), and that service audits it.
- No new events. `backend/events/CATALOG.md` is unchanged.
- Backend commands run from `backend/`: `.venv/Scripts/python -m pytest <path> -q`. Frontend check, from `frontend/`: `npx tsc -b --force`. An integration run where everything is *skipped* tested nothing: check that the DB is reachable.
- Commit after every task. The message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never push, since a push to `huge_production_migration` deploys. Never `git stash`, because the working tree is shared.

## Review Focus

1. **A self-service user opens a colleague's payslip by typing its id into the print URL** (`/payroll/payslips/{colleague_id}/print`, which calls payroll's payslip GET). Expected: 404 `NOT_FOUND`, and the payslip's existence is not revealed. Pinned by Task 7: `test_an_employee_never_reads_a_colleagues_payslip` and `test_the_real_payslip_route_refuses_a_colleague`.
2. **A client sends another employee's id to `/me`**, as `?employee_id=` on `/hr/me/payslips` or as `employee_id` in the leave-request body. Expected: the query parameter is ignored and only the caller's own payslips come back; the body is refused with a 422 and nothing is written. Pinned by Task 6: `test_asking_for_a_colleague_still_returns_only_my_payslips` and `test_an_employee_id_in_the_leave_body_is_refused`.
3. **A month with no presence recorded, or with presence still open.** Expected: the absence rate shows "—" and never 0 %, and the page says presence is not closed yet. Pinned by Task 1 (`test_absence_rate_is_unknown_not_zero_when_nothing_was_scheduled`) and Task 3 (`test_the_merged_services_answer_for_a_tenant_with_no_data`).
4. **A dashboard viewer without the right to see pay, or a deployment without the payroll module.** Expected: the payroll block explains why it is empty, payroll is never queried for that user, and no zero amounts appear. Pinned by Task 3 (`test_payroll_cost_is_not_read_for_a_user_who_may_not_see_pay`, `test_payroll_cost_is_unavailable_without_the_payroll_module`) and Task 4 (`test_payroll_cost_is_asked_for_only_when_the_user_may_see_pay`).
5. **The running month, or a hand-typed mid-month or future period.** Expected: the running month's headcount is counted as of today, not as of the month's last day; a mid-month or future period gets a bilingual 422. Pinned by Task 1 (`test_the_running_month_is_counted_as_of_today`, `test_a_period_is_the_first_day_of_a_month_that_has_started`) and Task 4 (`test_a_mid_month_period_is_refused_in_both_languages`).

---

## Before you start: contract check (read-only, ~10 minutes)

Phases 1–3 were planned in parallel with this one. This plan uses the names from the contract file. Where the contract says nothing, it also relies on the names the spec gives. Check each row below against the merged code before Task 1:

```bash
cd backend
grep -rn "def employees_for_period\|def month_summary\|def is_month_closed\|def get_by_user\|def cost_by_department\|def payslips_for_employee\|class LeaveRequestService\|class EmployeeService" modules/hr/api modules/payroll/api
grep -n "    def " modules/hr/api/leave_service.py
grep -rn "horizon" modules/hr/migrations
grep -n "hr\.\(settings\|employee_documents\|positions\|leave_types\|leave_balances\)" -A 14 modules/hr/migrations/*.sql
grep -n "ALTER TABLE hr\.\(employees\|contracts\|leave_requests\)" -A 20 modules/hr/migrations/*.sql
grep -n "payroll\.\(runs\|payslips\)" -A 20 modules/payroll/migrations/*.sql
grep -n "payslips/" -A 3 modules/payroll/api/router.py
grep -n "payslips/:id/print" ../frontend/src/routes/router.tsx
grep -n "def main\|__main__\|TENANT" scripts/seed_hr_payroll.py
```

| # | Assumed by this plan | Used in |
|---|---|---|
| A1 | `PayrollSnapshotService(connection)` in `modules/hr/api/payroll_snapshot_service.py`; `employees_for_period(*, tenant_id, period, employee_ids=None)`; dict keys as in the contract | Tasks 3, 5 |
| A2 | `PresenceService(connection)` in `modules/hr/api/presence_service.py`; `month_summary(*, tenant_id, period, employee_ids=None)`, `is_month_closed(*, tenant_id, period)` | Task 3 |
| A3 | `EmployeeService(connection).get_by_user(*, tenant_id, user_id) -> dict | None`, importable from `modules.hr.api.service`; the dict has `id`, `department_id`, `position_id` and the phase 1 identity columns by their spec names (`birth_date`, `national_id`, …) | Tasks 5, 7 |
| A4 | `PayrollReportService(connection)` in `modules/payroll/api/report_service.py`. `cost_by_department(*, tenant_id, period_from, period_to)` rows have `period` as a `date`. `payslips_for_employee(*, tenant_id, employee_id)` rows have `id, employee_id, period, run_type, run_status, gross, net` | Tasks 3, 5 |
| A5 | `hr.settings` has one row per tenant (`tenant_id` unique) with `contract_expiry_horizon_days` and `trial_end_horizon_days` | Task 2 |
| A6 | `hr.contracts` has `trial_end_date` and `status` (`'active'` for the contract in force). `hr.employees.status` allows `'terminated'` and has `user_id`. `hr.employee_documents (id, tenant_id, employee_id, kind, expires_on)`. `hr.positions (id, tenant_id, title)` | Tasks 2, 5 |
| A7 | `hr.leave_types (id, tenant_id, code, name, paid, accrual_days_per_month)`, `hr.leave_balances (id, tenant_id, employee_id, leave_type_id, year, accrued, taken, adjusted)`, `hr.leave_requests.leave_type_id / days / half_day` | Tasks 5, 6 |
| A8 | `LeaveRequestService(connection)` in `modules/hr/api/leave_service.py` (phase 2's file map names this class and file). This plan calls its create method as `create_request(*, tenant_id, actor_id, employee_id, leave_type_id, start_date, end_date, half_day, reason) -> Result[dict]`, and the returned dict has `id` | Tasks 5, 6 |
| A9 | `payroll.payslips (id, tenant_id, run_id, employee_id)` and `payroll.runs (id, tenant_id, status)`, with statuses `draft/calculated/approved/paid/reversed` | Task 7 |
| A10 | The payroll router serves the payslip the print page reads at `GET /payroll/payslips/{payslip_id}`, guarded by `require_permission("payroll.view_runs")` | Task 7 |
| A11 | `backend/scripts/seed_hr_payroll.py` guards its seeding with `if __name__ == "__main__":` and seeds tenant `"demo"` | Task 10 |

Rules:
- **Renamed** (for example a different module path, or a column called `trial_ends_on`): use the merged name everywhere this plan uses the assumed one. The plan's logic does not change.
- **A4 missing keys:** if `payslips_for_employee` lacks `employee_id` or `run_status`, add them to that method's SELECT as extra keys, without renaming existing ones. Add a line to its existing test in `modules/payroll/api/`, and commit that fix with Task 5. This is an additive change to a public api.
- **A5:** if phase 1 already has a document horizon column, drop `0020_hr_document_expiry_horizon.sql` from Task 2 and use phase 1's column in `HrExpiryService`.
- **A7/A8:** if `create_request` needs more setup to accept a request (for example a schedule assignment so it can count working days), add that setup to the `world` fixture of Task 6's test. Do not change phase 2's code.
- **A contract item is missing entirely** (not just renamed): stop and report. Do not read another module's tables to work around it.

## File map

| File | Responsibility |
|---|---|
| `backend/modules/hr/domain/dashboard.py` (create) | Pure month arithmetic: period checks, headcount, movements, absence rate, overtime, payroll by department, variance, department names |
| `backend/modules/hr/domain/test_dashboard.py` (create) | Tests for the above; no DB |
| `backend/modules/hr/domain/expiry.py` (create) | Pure rules for what falls due inside the hr.settings horizons |
| `backend/modules/hr/domain/test_expiry.py` (create) | Tests for the above; no DB |
| `backend/modules/hr/migrations/0020_hr_document_expiry_horizon.sql` (create) | Nullable document horizon in `hr.settings` |
| `backend/modules/hr/api/expiry_service.py` (create) | `HrExpiryService`: loads settings, contracts and documents; applies `expiry.py` |
| `backend/modules/hr/api/test_expiry_service_integration.py` (create) | `HrExpiryService` against the merged schema |
| `backend/modules/hr/api/payroll_bridge.py` (create) | Lazy, optional access to `PayrollReportService` |
| `backend/modules/hr/api/analytics_service.py` (create) | `HrAnalyticsService`: combines the three contract sources into one dashboard month |
| `backend/modules/hr/api/test_analytics_service_integration.py` (create) | Service tests (fakes + one smoke test with the real services) |
| `backend/modules/hr/module.json` (modify) | `optional_depends: ["payroll"]`, new `provides_api` entries |
| `backend/modules/hr/api/router.py` (modify) | `/hr/dashboard/summary`, `/hr/dashboard/expiring`, `/hr/me/*`; `NO_EMPLOYEE_LINK` → 404 |
| `backend/modules/hr/api/test_dashboard_router_integration.py` (create) | Dashboard endpoints over HTTP |
| `backend/modules/hr/domain/self_service.py` (create) | Pure selection: file view, own approved payslips, leave balance lines |
| `backend/modules/hr/domain/test_self_service.py` (create) | Tests for the above; no DB |
| `backend/modules/hr/api/self_service.py` (create) | `SelfServiceService`: the caller's own file, payslips, leave, leave request |
| `backend/modules/hr/api/test_self_service_integration.py` (create) | Service-level isolation tests |
| `backend/modules/hr/api/test_self_service_router_integration.py` (create) | `/hr/me` over HTTP: permission, own-only, body refusal |
| `backend/modules/payroll/domain/payslip_access.py` (create) | Pure rule: who may read one payslip |
| `backend/modules/payroll/domain/test_payslip_access.py` (create) | Tests for the above |
| `backend/modules/payroll/api/payslip_access.py` (create) | `require_payslip_reader` FastAPI dependency |
| `backend/modules/payroll/api/test_payslip_access_integration.py` (create) | The guard over HTTP, including the real payroll route |
| `backend/modules/payroll/api/router.py` (modify) | Single-payslip GETs use `require_payslip_reader` |
| `frontend/src/features/hr/api.ts` (modify) | Dashboard and `/me` types and fetchers |
| `frontend/src/features/hr/format.ts` (create) | Number, money, date and variance formatting; contract-type labels |
| `frontend/src/features/hr/dashboard/HrDashboardPage.tsx` (create) | `/hr/dashboard` screen |
| `frontend/src/features/hr/dashboard/KpiTile.tsx` (create) | Figure + neutral month-on-month change |
| `frontend/src/features/hr/dashboard/PayrollCostTable.tsx` (create) | Payroll cost by department table |
| `frontend/src/features/hr/dashboard/ExpiryTable.tsx` (create) | Contracts/trials/documents falling due table |
| `frontend/src/features/hr/me/MyPage.tsx` (create) | `/me` screen with tabs |
| `frontend/src/features/hr/me/MyFileTab.tsx` (create) | Read-only employee file |
| `frontend/src/features/hr/me/MyPayslipsTab.tsx` (create) | Own payslips + print links |
| `frontend/src/features/hr/me/MyLeaveTab.tsx` (create) | Balances, request form, own requests |
| `frontend/src/routes/router.tsx`, `frontend/src/routes/Sidebar.tsx`, `frontend/src/lib/i18n.tsx` (modify) | Routes, nav entries, strings |
| `backend/scripts/seed_hr_payroll.py` (modify) | Link the demo login to an employee; grant `hr.self_service` |
| `backend/scripts/test_seed_hr_self_service_integration.py` (create) | The seed link is idempotent |

---

### Task 1: Dashboard arithmetic (pure domain)

**Files:**
- Create: `backend/modules/hr/domain/dashboard.py`
- Test: `backend/modules/hr/domain/test_dashboard.py`

**Interfaces:**
- Consumes: `core.domain.result.Err/Ok/Result`; the dict shapes of contract A1, A2 and A4 (`cost_by_department` rows).
- Produces (used by Task 3):
  - `validate_period(period: date, *, today: date) -> Result[date]`: codes `INVALID_PERIOD`, `PERIOD_IN_FUTURE`
  - `previous_period(period: date) -> date`, `last_day(period: date) -> date`
  - `build_summary(*, period, today, snapshot, previous_snapshot, presence, previous_presence, payroll_rows: list[dict] | None) -> dict`
  - `attach_department_names(summary: dict, names: dict[str, str]) -> dict`
  - `variance(current, previous) -> {"current", "previous", "delta", "delta_pct"}`
  - `OVERTIME_BANDS = ("day", "night", "rest_holiday")`

- [ ] **Step 1: Write the failing tests**

`backend/modules/hr/domain/test_dashboard.py`:

```python
"""The HR dashboard's arithmetic, on plain dicts shaped like the hr and payroll api return them."""
from __future__ import annotations

import datetime
from decimal import Decimal

from core.domain.result import Err, Ok
from modules.hr.domain.dashboard import (
    absence,
    active_on,
    attach_department_names,
    build_summary,
    headcount,
    last_day,
    movements,
    overtime_minutes,
    payroll_by_department,
    previous_period,
    validate_period,
    variance,
)

SEPT = datetime.date(2026, 9, 1)
AUG = datetime.date(2026, 8, 1)
TODAY = datetime.date(2026, 9, 25)


def _employee(employee_id, *, department_id="D1", contract_type="cdi", hire=datetime.date(2025, 1, 6),
              start=None, end=None, left=None, reason=None):
    return {
        "employee_id": employee_id, "employee_no": employee_id, "full_name": f"Name {employee_id}",
        "department_id": department_id, "position_id": None, "grade_id": None,
        "hire_date": hire, "termination_date": left, "termination_reason": reason, "tax_dependants": 0,
        "contract": {
            "id": f"C-{employee_id}", "contract_type": contract_type, "base_salary": Decimal("150000"),
            "weekly_hours": Decimal("40"), "pay_frequency": "monthly",
            "start_date": start or hire, "end_date": end, "components": [],
        },
        "payment_methods": [],
    }


def _presence(employee_id, *, scheduled=22, unpaid=0, day=0, night=0, rest=0):
    return {
        "employee_id": employee_id, "scheduled_days": scheduled, "worked_days": scheduled - unpaid,
        "unpaid_absence_days": unpaid, "paid_leave_days": 0, "sick_days": 0, "holiday_days": 0,
        "holidays_worked_days": 0, "ot_minutes_day": day, "ot_minutes_night": night,
        "ot_minutes_rest_holiday": rest, "night_minutes": 0, "late_minutes": 0,
    }


def test_a_period_is_the_first_day_of_a_month_that_has_started():
    assert validate_period(SEPT, today=TODAY) == Ok(SEPT)
    mid = validate_period(datetime.date(2026, 9, 15), today=TODAY)
    assert isinstance(mid, Err) and mid.code == "INVALID_PERIOD" and mid.message_fr
    future = validate_period(datetime.date(2026, 10, 1), today=TODAY)
    assert isinstance(future, Err) and future.code == "PERIOD_IN_FUTURE" and future.message_fr


def test_month_arithmetic_crosses_years_and_leap_februaries():
    assert previous_period(datetime.date(2026, 1, 1)) == datetime.date(2025, 12, 1)
    assert last_day(datetime.date(2028, 2, 1)) == datetime.date(2028, 2, 29)
    assert last_day(datetime.date(2026, 12, 1)) == datetime.date(2026, 12, 31)


def test_under_contract_means_the_contract_covers_the_day_and_the_employee_had_not_left():
    day = datetime.date(2026, 9, 30)
    assert active_on(_employee("A"), day)
    assert not active_on(_employee("B", end=datetime.date(2026, 9, 29)), day)
    assert not active_on(_employee("C", hire=datetime.date(2026, 10, 1)), day)
    assert not active_on(_employee("D", left=datetime.date(2026, 9, 12)), day)
    assert active_on(_employee("E", left=day), day)  # leaves at the end of that day: still counted on it


def test_headcount_groups_by_department_and_contract_type_largest_first():
    snapshot = [
        _employee("A"), _employee("B"),
        _employee("C", department_id="D2", contract_type="cdd"),
        _employee("D", department_id=None, contract_type="daily"),
        _employee("E", left=datetime.date(2026, 9, 3)),
    ]
    result = headcount(snapshot, datetime.date(2026, 9, 30))
    assert result["total"] == 4
    assert result["by_department"] == [
        {"department_id": "D1", "count": 2},
        {"department_id": None, "count": 1},
        {"department_id": "D2", "count": 1},
    ]
    assert result["by_contract_type"] == [
        {"contract_type": "cdi", "count": 2},
        {"contract_type": "cdd", "count": 1},
        {"contract_type": "daily", "count": 1},
    ]


def test_movements_are_hires_and_exits_dated_inside_the_month():
    snapshot = [
        _employee("A", hire=datetime.date(2026, 9, 14)),
        _employee("B", hire=datetime.date(2026, 8, 31)),
        _employee("C", left=datetime.date(2026, 9, 30), reason="resignation"),
        _employee("D", left=datetime.date(2026, 10, 1)),
    ]
    result = movements(snapshot, SEPT)
    assert [row["employee_id"] for row in result["hires"]] == ["A"]
    assert result["hires"][0]["date"] == datetime.date(2026, 9, 14)
    assert [(row["employee_id"], row["reason"]) for row in result["exits"]] == [("C", "resignation")]


def test_absence_rate_is_unpaid_absence_days_over_scheduled_days():
    result = absence([_presence("A", scheduled=22, unpaid=2), _presence("B", scheduled=22, unpaid=0)])
    assert result == {"unpaid_absence_days": 2, "scheduled_days": 44, "rate": Decimal("0.0455")}


def test_absence_rate_is_unknown_not_zero_when_nothing_was_scheduled():
    assert absence([])["rate"] is None
    assert absence([_presence("A", scheduled=0)])["rate"] is None


def test_overtime_minutes_are_summed_per_band():
    result = overtime_minutes([_presence("A", day=90, night=30), _presence("B", day=30, rest=480)])
    assert result == {"day": 120, "night": 30, "rest_holiday": 480}


def test_variance_needs_both_months_and_a_non_zero_base_for_a_percentage():
    assert variance(12, 10) == {"current": 12, "previous": 10, "delta": 2, "delta_pct": Decimal("20.0")}
    assert variance(3, 0) == {"current": 3, "previous": 0, "delta": 3, "delta_pct": None}
    assert variance(None, Decimal("0.05"))["delta"] is None
    assert variance(Decimal("0.03"), Decimal("0.05"))["delta"] == Decimal("-0.02")


def test_payroll_cost_is_split_into_this_month_and_the_previous_one():
    rows = [
        {"period": SEPT, "department_id": "D1", "headcount": 10, "gross": Decimal("1500000"), "employer_cost": Decimal("1800000")},
        {"period": AUG, "department_id": "D1", "headcount": 9, "gross": Decimal("1350000"), "employer_cost": Decimal("1620000")},
        {"period": AUG, "department_id": "D2", "headcount": 1, "gross": Decimal("200000"), "employer_cost": Decimal("240000")},
        {"period": datetime.date(2026, 7, 1), "department_id": "D1", "headcount": 99, "gross": Decimal("1"), "employer_cost": Decimal("1")},
    ]
    result = payroll_by_department(rows, SEPT)
    d1, d2 = result["departments"]
    assert d1["department_id"] == "D1" and d1["current"]["gross"] == Decimal("1500000")
    assert d1["variance"]["gross"]["delta"] == Decimal("150000")
    assert d2["current"] == {"headcount": 0, "gross": Decimal(0), "employer_cost": Decimal(0)}
    assert d2["previous"]["employer_cost"] == Decimal("240000")
    assert result["totals"]["current"]["employer_cost"] == Decimal("1800000")
    assert result["totals"]["previous"]["gross"] == Decimal("1550000")
    assert result["totals"]["variance"]["gross"]["delta"] == Decimal("-50000")
    assert result["totals"]["variance"]["headcount"]["delta"] == 0


def test_the_running_month_is_counted_as_of_today():
    snapshot = [_employee("A"), _employee("B", hire=datetime.date(2026, 9, 28))]  # B starts after today
    summary = build_summary(
        period=SEPT, today=TODAY, snapshot=snapshot, previous_snapshot=[_employee("A")],
        presence=[], previous_presence=[], payroll_rows=None,
    )
    assert summary["headcount"]["as_of"] == TODAY
    assert summary["headcount"]["total"] == 1
    assert summary["headcount"]["variance"]["delta"] == 0
    assert summary["absence"]["rate"] is None
    assert summary["payroll"] is None


def test_a_past_month_is_counted_on_its_last_day_and_compared_on_every_measure():
    summary = build_summary(
        period=AUG, today=TODAY,
        snapshot=[_employee("A"), _employee("B", hire=datetime.date(2026, 8, 3))],
        previous_snapshot=[_employee("A")],
        presence=[_presence("A", unpaid=1, day=60), _presence("B", day=30)],
        previous_presence=[_presence("A", day=30)],
        payroll_rows=[],
    )
    assert summary["headcount"]["as_of"] == datetime.date(2026, 8, 31)
    assert summary["movements"]["variance"]["hires"] == variance(1, 0)
    assert summary["overtime_minutes"]["total"] == variance(90, 30)
    assert summary["overtime_minutes"]["variance"]["day"]["delta"] == 60
    assert summary["payroll"]["departments"] == []
    assert summary["payroll"]["totals"]["current"]["gross"] == 0


def test_department_names_are_attached_and_a_missing_department_stays_unnamed():
    summary = build_summary(
        period=AUG, today=TODAY,
        snapshot=[_employee("A", hire=datetime.date(2026, 8, 3)), _employee("B", department_id=None)],
        previous_snapshot=[], presence=[], previous_presence=[],
        payroll_rows=[{"period": AUG, "department_id": "D9", "headcount": 1, "gross": Decimal("1"), "employer_cost": Decimal("1")}],
    )
    named = attach_department_names(summary, {"D1": "Production"})
    assert {row["department_id"]: row["department_name"] for row in named["headcount"]["by_department"]} == {
        "D1": "Production", None: None,
    }
    assert named["movements"]["hires"][0]["department_name"] == "Production"
    assert named["payroll"]["departments"][0]["department_name"] is None  # D9 is gone from hr
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest modules/hr/domain/test_dashboard.py -q`
Expected: collection error `ModuleNotFoundError: No module named 'modules.hr.domain.dashboard'`.

- [ ] **Step 3: Write the implementation**

`backend/modules/hr/domain/dashboard.py`:

```python
"""Pure arithmetic behind the HR dashboard.

Every figure is a count or a sum of a recorded field, set against the same figure for the
previous month. There is no target, threshold or good/bad judgement here: the data holds none
(spec, phase 5: "no targets invented").

Inputs are the plain dicts the public api services return:
- PayrollSnapshotService.employees_for_period -> employee dicts with the contract nested,
- PresenceService.month_summary               -> one dict per employee, int day/minute counts,
- PayrollReportService.cost_by_department     -> {period, department_id, headcount, gross, employer_cost}.
Nothing here touches a database.
"""
from __future__ import annotations

import datetime
from collections import Counter
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable

from core.domain.result import Err, Ok, Result

OVERTIME_BANDS: tuple[str, ...] = ("day", "night", "rest_holiday")
PAYROLL_MEASURES: tuple[str, ...] = ("headcount", "gross", "employer_cost")
_ZERO = Decimal(0)
_RATE_STEP = Decimal("0.0001")
_PCT_STEP = Decimal("0.1")


def validate_period(period: datetime.date, *, today: datetime.date) -> Result[datetime.date]:
    """A dashboard month is the first day of a month that has already started."""
    if period.day != 1:
        return Err(
            "INVALID_PERIOD",
            "period must be the first day of a month",
            "la période doit être le premier jour d'un mois",
        )
    if period > today.replace(day=1):
        return Err(
            "PERIOD_IN_FUTURE",
            "the dashboard cannot show a month that has not started",
            "le tableau de bord ne peut pas afficher un mois qui n'a pas commencé",
        )
    return Ok(period)


def previous_period(period: datetime.date) -> datetime.date:
    return (period - datetime.timedelta(days=1)).replace(day=1)


def last_day(period: datetime.date) -> datetime.date:
    following = (period.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
    return following - datetime.timedelta(days=1)


def in_period(day: datetime.date | None, period: datetime.date) -> bool:
    return day is not None and period <= day <= last_day(period)


def active_on(employee: dict, day: datetime.date) -> bool:
    """Under contract on `day`: the contract covers the day and the employee had not left before it."""
    contract = employee["contract"]
    if contract["start_date"] > day:
        return False
    if contract["end_date"] is not None and contract["end_date"] < day:
        return False
    left = employee["termination_date"]
    return left is None or left >= day


def _ranked(counts: Counter, key: str) -> list[dict]:
    """Largest group first; among equals, by value, with the unassigned group (None) first."""
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0] or ""))
    return [{key: value, "count": count} for value, count in ordered]


def headcount(snapshot: Iterable[dict], as_of: datetime.date) -> dict:
    active = [employee for employee in snapshot if active_on(employee, as_of)]
    return {
        "as_of": as_of,
        "total": len(active),
        "by_department": _ranked(Counter(e["department_id"] for e in active), "department_id"),
        "by_contract_type": _ranked(Counter(e["contract"]["contract_type"] for e in active), "contract_type"),
    }


def _movement(employee: dict, day: datetime.date) -> dict:
    return {
        "employee_id": employee["employee_id"],
        "employee_no": employee["employee_no"],
        "full_name": employee["full_name"],
        "department_id": employee["department_id"],
        "date": day,
    }


def _by_date(row: dict) -> tuple:
    return (row["date"], row["full_name"])


def movements(snapshot: Iterable[dict], period: datetime.date) -> dict:
    """Hires: hire_date inside the month. Exits: termination_date inside the month."""
    employees = list(snapshot)
    hires = [_movement(e, e["hire_date"]) for e in employees if in_period(e["hire_date"], period)]
    exits = [
        {**_movement(e, e["termination_date"]), "reason": e["termination_reason"]}
        for e in employees
        if in_period(e["termination_date"], period)
    ]
    return {"hires": sorted(hires, key=_by_date), "exits": sorted(exits, key=_by_date)}


def absence(summaries: Iterable[dict]) -> dict:
    """Unpaid absence days over scheduled days; None, never 0, when nothing was scheduled."""
    rows = list(summaries)
    unpaid = sum(int(row["unpaid_absence_days"]) for row in rows)
    scheduled = sum(int(row["scheduled_days"]) for row in rows)
    rate = None if scheduled == 0 else (Decimal(unpaid) / Decimal(scheduled)).quantize(_RATE_STEP, ROUND_HALF_UP)
    return {"unpaid_absence_days": unpaid, "scheduled_days": scheduled, "rate": rate}


def overtime_minutes(summaries: Iterable[dict]) -> dict[str, int]:
    rows = list(summaries)
    return {band: sum(int(row[f"ot_minutes_{band}"]) for row in rows) for band in OVERTIME_BANDS}


def variance(current, previous) -> dict:
    """Change against the previous month: no delta without both months, no percentage on a zero base."""
    if current is None or previous is None:
        return {"current": current, "previous": previous, "delta": None, "delta_pct": None}
    delta = current - previous
    delta_pct = (
        None if previous == 0
        else (Decimal(delta) * 100 / Decimal(previous)).quantize(_PCT_STEP, ROUND_HALF_UP)
    )
    return {"current": current, "previous": previous, "delta": delta, "delta_pct": delta_pct}


def _empty_side() -> dict:
    return {"headcount": 0, "gross": _ZERO, "employer_cost": _ZERO}


def payroll_by_department(rows: Iterable[dict], period: datetime.date) -> dict:
    """Payroll cost of `period` and of the month before, per department, with totals."""
    sides = {period: "current", previous_period(period): "previous"}
    departments: dict[str | None, dict] = {}
    for row in rows:
        side = sides.get(row["period"])
        if side is None:
            continue
        slot = departments.setdefault(
            row["department_id"],
            {"department_id": row["department_id"], "current": _empty_side(), "previous": _empty_side()},
        )
        slot[side]["headcount"] += int(row["headcount"])
        slot[side]["gross"] += Decimal(row["gross"])
        slot[side]["employer_cost"] += Decimal(row["employer_cost"])
    ordered = sorted(
        departments.values(),
        key=lambda d: (-d["current"]["gross"], -d["previous"]["gross"], d["department_id"] or ""),
    )
    for department in ordered:
        department["variance"] = {
            measure: variance(department["current"][measure], department["previous"][measure])
            for measure in ("gross", "employer_cost")
        }
    totals: dict = {"current": _empty_side(), "previous": _empty_side()}
    for department in ordered:
        for side in ("current", "previous"):
            for measure in PAYROLL_MEASURES:
                totals[side][measure] += department[side][measure]
    totals["variance"] = {m: variance(totals["current"][m], totals["previous"][m]) for m in PAYROLL_MEASURES}
    return {"departments": ordered, "totals": totals}


def build_summary(
    *,
    period: datetime.date,
    today: datetime.date,
    snapshot: Iterable[dict],
    previous_snapshot: Iterable[dict],
    presence: Iterable[dict],
    previous_presence: Iterable[dict],
    payroll_rows: Iterable[dict] | None,
) -> dict:
    """The dashboard month. The running month is counted as of today, a past month on its last day.
    `payroll_rows=None` means payroll is not shown (no right to see pay, or no payroll module)."""
    previous = previous_period(period)
    snapshot, previous_snapshot = list(snapshot), list(previous_snapshot)
    presence, previous_presence = list(presence), list(previous_presence)
    current_count = headcount(snapshot, min(last_day(period), today))
    previous_count = headcount(previous_snapshot, last_day(previous))
    current_moves = movements(snapshot, period)
    previous_moves = movements(previous_snapshot, previous)
    current_absence, previous_absence = absence(presence), absence(previous_presence)
    current_ot, previous_ot = overtime_minutes(presence), overtime_minutes(previous_presence)
    return {
        "period": period,
        "previous_period": previous,
        "headcount": {**current_count, "variance": variance(current_count["total"], previous_count["total"])},
        "movements": {
            **current_moves,
            "variance": {
                "hires": variance(len(current_moves["hires"]), len(previous_moves["hires"])),
                "exits": variance(len(current_moves["exits"]), len(previous_moves["exits"])),
            },
        },
        "absence": {
            **current_absence,
            "previous": previous_absence,
            "variance": variance(current_absence["rate"], previous_absence["rate"]),
        },
        "overtime_minutes": {
            "current": current_ot,
            "previous": previous_ot,
            "variance": {band: variance(current_ot[band], previous_ot[band]) for band in OVERTIME_BANDS},
            "total": variance(sum(current_ot.values()), sum(previous_ot.values())),
        },
        "payroll": None if payroll_rows is None else payroll_by_department(payroll_rows, period),
    }


def attach_department_names(summary: dict, names: dict[str, str]) -> dict:
    """Adds `department_name` next to every `department_id`; None when the id is None or gone from hr."""

    def name(department_id: str | None) -> str | None:
        return None if department_id is None else names.get(department_id)

    for row in summary["headcount"]["by_department"]:
        row["department_name"] = name(row["department_id"])
    for row in (*summary["movements"]["hires"], *summary["movements"]["exits"]):
        row["department_name"] = name(row["department_id"])
    if summary["payroll"] is not None:
        for row in summary["payroll"]["departments"]:
            row["department_name"] = name(row["department_id"])
    return summary
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest modules/hr/domain/test_dashboard.py -q`
Expected: `13 passed`.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/hr/domain/dashboard.py backend/modules/hr/domain/test_dashboard.py
git commit -m "feat(hr): pure month arithmetic for the HR dashboard" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Expiry list (pure rules, horizon setting, service)

**Files:**
- Create: `backend/modules/hr/domain/expiry.py`
- Test: `backend/modules/hr/domain/test_expiry.py`
- Create: `backend/modules/hr/migrations/0020_hr_document_expiry_horizon.sql`
- Create: `backend/modules/hr/api/expiry_service.py`
- Test: `backend/modules/hr/api/test_expiry_service_integration.py`

**Interfaces:**
- Consumes: hr's own tables `hr.settings`, `hr.contracts`, `hr.employees`, `hr.employee_documents` (assumptions A5, A6).
- Produces (used by Task 4): `HrExpiryService(connection).expiring(*, tenant_id: str, today: date) -> {"horizons": {"contract_days", "trial_days", "document_days"} | None, "items": [{"kind": "contract"|"trial"|"document", "source_id", "employee_id", "employee_no", "employee_name", "label", "due_date": date, "days_left": int}]}`

- [ ] **Step 1: Write the failing domain tests**

`backend/modules/hr/domain/test_expiry.py`:

```python
"""What falls due inside the tenant's alert horizons."""
from __future__ import annotations

import datetime

from modules.hr.domain.expiry import Horizons, expiring_items, horizons_from_settings

TODAY = datetime.date(2026, 9, 25)
HORIZONS = Horizons(contract_days=30, trial_days=15, document_days=60)


def _days(n: int) -> datetime.date:
    return TODAY + datetime.timedelta(days=n)


def _contract(contract_id, *, end=None, trial=None, contract_type="cdd"):
    return {"id": contract_id, "employee_id": f"E-{contract_id}", "employee_no": f"N-{contract_id}",
            "employee_name": f"Name {contract_id}", "contract_type": contract_type,
            "end_date": end, "trial_end_date": trial}


def _document(document_id, expires_on, kind="medical_certificate"):
    return {"id": document_id, "employee_id": f"E-{document_id}", "employee_no": f"N-{document_id}",
            "employee_name": f"Name {document_id}", "kind": kind, "expires_on": expires_on}


def test_a_contract_ending_inside_the_horizon_is_listed_and_one_already_ended_is_listed_as_past_due():
    items = expiring_items(
        contracts=[_contract("in", end=_days(30)), _contract("out", end=_days(31)),
                   _contract("late", end=_days(-2)), _contract("open", contract_type="cdi")],
        documents=[], today=TODAY, horizons=HORIZONS,
    )
    assert [(item["source_id"], item["days_left"]) for item in items] == [("late", -2), ("in", 30)]
    assert {item["kind"] for item in items} == {"contract"}


def test_a_trial_is_listed_only_between_today_and_its_horizon():
    items = expiring_items(
        contracts=[_contract("soon", trial=_days(15)), _contract("far", trial=_days(16)), _contract("over", trial=_days(-1))],
        documents=[], today=TODAY, horizons=HORIZONS,
    )
    assert [(item["kind"], item["source_id"]) for item in items] == [("trial", "soon")]


def test_a_document_is_listed_inside_its_horizon_and_once_expired():
    items = expiring_items(
        contracts=[],
        documents=[_document("ok", _days(61)), _document("due", _days(60)), _document("gone", _days(-10))],
        today=TODAY, horizons=HORIZONS,
    )
    assert [(item["source_id"], item["days_left"], item["label"]) for item in items] == [
        ("gone", -10, "medical_certificate"), ("due", 60, "medical_certificate"),
    ]


def test_one_contract_can_raise_a_trial_and_an_end_alert_soonest_first():
    items = expiring_items(contracts=[_contract("both", end=_days(20), trial=_days(5))], documents=[], today=TODAY, horizons=HORIZONS)
    assert [item["kind"] for item in items] == ["trial", "contract"]


def test_horizons_come_from_the_settings_and_are_never_invented():
    assert horizons_from_settings(None, 15, 60) is None
    assert horizons_from_settings(30, None, None) is None
    assert horizons_from_settings(30, 15, None) == Horizons(30, 15, 30)  # documents follow contracts
    assert horizons_from_settings(30, 15, 90) == Horizons(30, 15, 90)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python -m pytest modules/hr/domain/test_expiry.py -q`
Expected: collection error `No module named 'modules.hr.domain.expiry'`.

- [ ] **Step 3: Write the domain rules**

`backend/modules/hr/domain/expiry.py`:

```python
"""Which contracts, trials and documents fall due inside the tenant's alert horizons.

The horizons are hr.settings values, never constants here. With no setting there is no list
(spec, phase 1: "horizons are settings in hr.settings, not constants").
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class Horizons:
    contract_days: int
    trial_days: int
    document_days: int


def horizons_from_settings(contract_days: int | None, trial_days: int | None,
                           document_days: int | None) -> Horizons | None:
    """None until both the contract and the trial horizons are set. A document horizon left empty
    follows the contract horizon (hr.settings.document_expiry_horizon_days is nullable on purpose)."""
    if contract_days is None or trial_days is None:
        return None
    return Horizons(contract_days, trial_days, contract_days if document_days is None else document_days)


def _item(kind: str, row: dict, label: str, due: datetime.date, today: datetime.date) -> dict:
    return {
        "kind": kind,
        "source_id": row["id"],
        "employee_id": row["employee_id"],
        "employee_no": row["employee_no"],
        "employee_name": row["employee_name"],
        "label": label,
        "due_date": due,
        "days_left": (due - today).days,
    }


def expiring_items(*, contracts: Iterable[dict], documents: Iterable[dict], today: datetime.date,
                   horizons: Horizons) -> list[dict]:
    """Contracts (in force) that end within the contract horizon or have already passed their end
    (days_left < 0); trials that end between today and the trial horizon (a past trial is over,
    not an alert); documents that expire within the document horizon or have already expired.
    Soonest first."""
    contract_limit = today + datetime.timedelta(days=horizons.contract_days)
    trial_limit = today + datetime.timedelta(days=horizons.trial_days)
    document_limit = today + datetime.timedelta(days=horizons.document_days)
    items: list[dict] = []
    for contract in contracts:
        end, trial = contract["end_date"], contract["trial_end_date"]
        if trial is not None and today <= trial <= trial_limit:
            items.append(_item("trial", contract, contract["contract_type"], trial, today))
        if end is not None and end <= contract_limit:
            items.append(_item("contract", contract, contract["contract_type"], end, today))
    for document in documents:
        if document["expires_on"] <= document_limit:
            items.append(_item("document", document, document["kind"], document["expires_on"], today))
    return sorted(items, key=lambda item: (item["due_date"], item["employee_name"], item["kind"]))
```

- [ ] **Step 4: Run the domain tests to verify they pass**

Run: `.venv/Scripts/python -m pytest modules/hr/domain/test_expiry.py -q`
Expected: `5 passed`.

- [ ] **Step 5: Write the migration**

The spec gives horizons for contracts (30 days) and trials (15 days) but none for documents. `backend/modules/hr/migrations/0020_hr_document_expiry_horizon.sql`:

```sql
-- Phase 5: documents get their own alert horizon on the HR dashboard.
-- NULL (the default) means "follow the contract expiry horizon": no document horizon is invented here.
-- IF NOT EXISTS keeps this harmless should phase 1 already have added the column.
ALTER TABLE hr.settings
    ADD COLUMN IF NOT EXISTS document_expiry_horizon_days INT
        CHECK (document_expiry_horizon_days IS NULL OR document_expiry_horizon_days >= 0);
```

Apply it by starting the API once, since its `lifespan` runs the migration runner. Stop the API once it has started:
Run (from `backend/`): `.venv/Scripts/python -m uvicorn app.main:app`
Expected: startup completes, and `SELECT version FROM core.module_migrations WHERE module_name = 'hr'` lists `0020_hr_document_expiry_horizon.sql`. If the tests use a separate `TEST_DATABASE_URL`, start the API once against that database as well (`DATABASE_URL=<test url>`). The `db` fixture needs the migrated schema.

- [ ] **Step 6: Write the failing service test**

`backend/modules/hr/api/test_expiry_service_integration.py`:

```python
"""HrExpiryService against the merged hr schema: which rows reach the dashboard's expiry list."""
from __future__ import annotations

import datetime

from ulid import ULID

from modules.hr.api.expiry_service import HrExpiryService

TENANT = "hr-expiry-test"
TODAY = datetime.date(2030, 5, 6)


def _days(n: int) -> datetime.date:
    return TODAY + datetime.timedelta(days=n)


def _employee(db, number: str, *, status: str = "active") -> str:
    employee_id = str(ULID())
    db.execute(
        "INSERT INTO hr.employees (id, tenant_id, employee_no, first_name, last_name, hire_date, status) "
        "VALUES (%s, %s, %s, 'Awa', %s, %s, %s)",
        (employee_id, TENANT, number, number, datetime.date(2029, 1, 7), status),
    )
    return employee_id


def _contract(db, employee_id: str, *, end=None, trial=None, status: str = "active") -> str:
    contract_id = str(ULID())
    db.execute(
        "INSERT INTO hr.contracts (id, tenant_id, employee_id, contract_type, start_date, end_date, trial_end_date, status) "
        "VALUES (%s, %s, %s, 'cdd', %s, %s, %s, %s)",
        (contract_id, TENANT, employee_id, datetime.date(2030, 1, 1), end, trial, status),
    )
    return contract_id


def _document(db, employee_id: str, expires_on: datetime.date) -> str:
    document_id = str(ULID())
    db.execute(
        "INSERT INTO hr.employee_documents (id, tenant_id, employee_id, kind, expires_on) "
        "VALUES (%s, %s, %s, 'medical_certificate', %s)",
        (document_id, TENANT, employee_id, expires_on),
    )
    return document_id


def _settings(db, *, contract: int = 30, trial: int = 15, document: int | None = None) -> None:
    db.execute(
        "INSERT INTO hr.settings (tenant_id, contract_expiry_horizon_days, trial_end_horizon_days, document_expiry_horizon_days) "
        "VALUES (%s, %s, %s, %s)",
        (TENANT, contract, trial, document),
    )


def test_nothing_is_listed_until_the_horizons_are_set(db):
    employee = _employee(db, "EXP-1")
    _contract(db, employee, end=_days(3))
    assert HrExpiryService(db).expiring(tenant_id=TENANT, today=TODAY) == {"horizons": None, "items": []}


def test_contracts_trials_and_documents_of_current_staff_fall_due(db):
    _settings(db)
    awa = _employee(db, "EXP-1")
    ending = _contract(db, awa, end=_days(10), trial=_days(4))
    expired_document = _document(db, awa, _days(-3))
    _document(db, awa, _days(31))  # beyond the contract horizon that documents follow
    leaver = _employee(db, "EXP-2", status="terminated")
    _document(db, leaver, _days(1))  # a leaver's paperwork is not an alert
    closed = _employee(db, "EXP-3")
    _contract(db, closed, end=_days(5), status="expired")  # only the contract in force counts
    result = HrExpiryService(db).expiring(tenant_id=TENANT, today=TODAY)
    assert result["horizons"] == {"contract_days": 30, "trial_days": 15, "document_days": 30}
    assert [(item["kind"], item["source_id"], item["days_left"]) for item in result["items"]] == [
        ("document", expired_document, -3), ("trial", ending, 4), ("contract", ending, 10),
    ]
```

Run: `.venv/Scripts/python -m pytest modules/hr/api/test_expiry_service_integration.py -q`
Expected: collection error `No module named 'modules.hr.api.expiry_service'` (or `2 skipped` if no DB is reachable, in which case start the DB first).

- [ ] **Step 7: Write the service**

`backend/modules/hr/api/expiry_service.py`:

```python
"""The expiry list of the HR dashboard: hr's own tables, filtered by the rules in hr/domain/expiry.py."""
from __future__ import annotations

import datetime

import psycopg

from modules.hr.domain.expiry import expiring_items, horizons_from_settings


class HrExpiryService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    def expiring(self, *, tenant_id: str, today: datetime.date) -> dict:
        settings = self.connection.execute(
            """
            SELECT contract_expiry_horizon_days, trial_end_horizon_days, document_expiry_horizon_days
            FROM hr.settings WHERE tenant_id = %s
            """,
            (tenant_id,),
        ).fetchone()
        horizons = None if settings is None else horizons_from_settings(*settings)
        if horizons is None:
            return {"horizons": None, "items": []}
        contracts = [
            {"id": r[0], "employee_id": r[1], "employee_no": r[2], "employee_name": r[3],
             "contract_type": r[4], "end_date": r[5], "trial_end_date": r[6]}
            for r in self.connection.execute(
                """
                SELECT c.id, c.employee_id, e.employee_no, e.first_name || ' ' || e.last_name,
                       c.contract_type, c.end_date, c.trial_end_date
                FROM hr.contracts c
                JOIN hr.employees e ON e.id = c.employee_id AND e.tenant_id = c.tenant_id
                WHERE c.tenant_id = %s AND c.status = 'active' AND e.status <> 'terminated'
                  AND (c.end_date IS NOT NULL OR c.trial_end_date IS NOT NULL)
                """,
                (tenant_id,),
            ).fetchall()
        ]
        documents = [
            {"id": r[0], "employee_id": r[1], "employee_no": r[2], "employee_name": r[3],
             "kind": r[4], "expires_on": r[5]}
            for r in self.connection.execute(
                """
                SELECT d.id, d.employee_id, e.employee_no, e.first_name || ' ' || e.last_name, d.kind, d.expires_on
                FROM hr.employee_documents d
                JOIN hr.employees e ON e.id = d.employee_id AND e.tenant_id = d.tenant_id
                WHERE d.tenant_id = %s AND d.expires_on IS NOT NULL AND e.status <> 'terminated'
                """,
                (tenant_id,),
            ).fetchall()
        ]
        return {
            "horizons": {
                "contract_days": horizons.contract_days,
                "trial_days": horizons.trial_days,
                "document_days": horizons.document_days,
            },
            "items": expiring_items(contracts=contracts, documents=documents, today=today, horizons=horizons),
        }
```

- [ ] **Step 8: Run all of the task's tests to verify they pass**

Run: `.venv/Scripts/python -m pytest modules/hr/domain/test_expiry.py modules/hr/api/test_expiry_service_integration.py -q`
Expected: `7 passed`, with none skipped.

- [ ] **Step 9: Commit**

```bash
git add backend/modules/hr/domain/expiry.py backend/modules/hr/domain/test_expiry.py backend/modules/hr/migrations/0020_hr_document_expiry_horizon.sql backend/modules/hr/api/expiry_service.py backend/modules/hr/api/test_expiry_service_integration.py
git commit -m "feat(hr): contracts, trials and documents falling due, from hr.settings horizons" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Analytics service (combine the contract sources)

**Files:**
- Create: `backend/modules/hr/api/payroll_bridge.py`
- Create: `backend/modules/hr/api/analytics_service.py`
- Modify: `backend/modules/hr/module.json`
- Test: `backend/modules/hr/api/test_analytics_service_integration.py`

**Interfaces:**
- Consumes: Task 1 (`validate_period`, `previous_period`, `build_summary`, `attach_department_names`); A1, A2, A4.
- Produces:
  - `payroll_bridge.payroll_report_service(connection) -> PayrollReportService | None` (Tasks 3 and 5; tests monkeypatch it)
  - `HrAnalyticsService(connection, *, snapshot=None, presence=None).summary(*, tenant_id: str, period: date, today: date, include_payroll: bool) -> Result[dict]`. The dict is Task 1's `build_summary` output with department names attached, plus `"payroll_status": "ok"|"hidden"|"unavailable"` and `"presence_closed": bool` (used by Task 4)

- [ ] **Step 1: Write the failing tests**

`backend/modules/hr/api/test_analytics_service_integration.py`:

```python
"""HrAnalyticsService: employees, presence and payroll cost combined into one dashboard month."""
from __future__ import annotations

import datetime
from decimal import Decimal

from ulid import ULID

from core.domain.result import Err, Ok
from modules.hr.api import payroll_bridge
from modules.hr.api.analytics_service import HrAnalyticsService

TENANT = "hr-analytics-test"
SEPT, AUG = datetime.date(2026, 9, 1), datetime.date(2026, 8, 1)
TODAY = datetime.date(2026, 9, 25)


def _employee(employee_id, department_id, *, hire=datetime.date(2025, 1, 6)):
    return {
        "employee_id": employee_id, "employee_no": employee_id, "full_name": f"Name {employee_id}",
        "department_id": department_id, "position_id": None, "grade_id": None, "hire_date": hire,
        "termination_date": None, "termination_reason": None, "tax_dependants": 0,
        "contract": {"id": f"C-{employee_id}", "contract_type": "cdi", "base_salary": Decimal("150000"),
                     "weekly_hours": Decimal("40"), "pay_frequency": "monthly", "start_date": hire,
                     "end_date": None, "components": []},
        "payment_methods": [],
    }


def _presence(employee_id, *, scheduled, unpaid, day=0):
    return {"employee_id": employee_id, "scheduled_days": scheduled, "worked_days": scheduled - unpaid,
            "unpaid_absence_days": unpaid, "paid_leave_days": 0, "sick_days": 0, "holiday_days": 0,
            "holidays_worked_days": 0, "ot_minutes_day": day, "ot_minutes_night": 0,
            "ot_minutes_rest_holiday": 0, "night_minutes": 0, "late_minutes": 0}


class _Snapshot:
    def __init__(self, by_period):
        self.by_period, self.calls = by_period, []

    def employees_for_period(self, *, tenant_id, period, employee_ids=None):
        self.calls.append((tenant_id, period))
        return self.by_period.get(period, [])


class _Presence:
    def __init__(self, by_period, closed=()):
        self.by_period, self.closed = by_period, set(closed)

    def month_summary(self, *, tenant_id, period, employee_ids=None):
        return self.by_period.get(period, [])

    def is_month_closed(self, *, tenant_id, period):
        return period in self.closed


class _Report:
    def __init__(self, rows):
        self.rows, self.calls = rows, []

    def cost_by_department(self, *, tenant_id, period_from, period_to):
        self.calls.append((tenant_id, period_from, period_to))
        return self.rows


class _ForbiddenReport:
    def cost_by_department(self, **kwargs):
        raise AssertionError("payroll cost must not be read for this user")


def _department(db, code: str, name: str) -> str:
    department_id = str(ULID())
    db.execute("INSERT INTO hr.departments (id, tenant_id, code, name) VALUES (%s, %s, %s, %s)",
               (department_id, TENANT, code, name))
    return department_id


def test_the_month_combines_employees_presence_and_payroll_cost(db, monkeypatch):
    production = _department(db, "PROD", "Production")
    report = _Report([
        {"period": SEPT, "department_id": production, "headcount": 2, "gross": Decimal("300000"), "employer_cost": Decimal("360000")},
        {"period": AUG, "department_id": production, "headcount": 1, "gross": Decimal("150000"), "employer_cost": Decimal("180000")},
    ])
    monkeypatch.setattr(payroll_bridge, "payroll_report_service", lambda connection: report)
    service = HrAnalyticsService(
        db,
        snapshot=_Snapshot({
            SEPT: [_employee("A", production), _employee("B", production, hire=datetime.date(2026, 9, 14))],
            AUG: [_employee("A", production)],
        }),
        presence=_Presence({SEPT: [_presence("A", scheduled=22, unpaid=1, day=90)],
                            AUG: [_presence("A", scheduled=21, unpaid=0)]}, closed=[AUG]),
    )
    result = service.summary(tenant_id=TENANT, period=SEPT, today=TODAY, include_payroll=True)
    assert isinstance(result, Ok)
    summary = result.value
    assert report.calls == [(TENANT, AUG, SEPT)]
    assert summary["payroll_status"] == "ok" and summary["presence_closed"] is False
    assert summary["headcount"]["total"] == 2 and summary["headcount"]["variance"]["delta"] == 1
    assert summary["headcount"]["by_department"] == [
        {"department_id": production, "count": 2, "department_name": "Production"},
    ]
    assert [row["employee_id"] for row in summary["movements"]["hires"]] == ["B"]
    assert summary["absence"]["rate"] == Decimal("0.0455")
    assert summary["overtime_minutes"]["current"]["day"] == 90
    assert summary["payroll"]["departments"][0]["department_name"] == "Production"
    assert summary["payroll"]["totals"]["variance"]["gross"]["delta"] == Decimal("150000")


def test_payroll_cost_is_not_read_for_a_user_who_may_not_see_pay(db, monkeypatch):
    monkeypatch.setattr(payroll_bridge, "payroll_report_service", lambda connection: _ForbiddenReport())
    service = HrAnalyticsService(db, snapshot=_Snapshot({}), presence=_Presence({}))
    result = service.summary(tenant_id=TENANT, period=AUG, today=TODAY, include_payroll=False)
    assert result.value["payroll"] is None and result.value["payroll_status"] == "hidden"


def test_payroll_cost_is_unavailable_without_the_payroll_module(db, monkeypatch):
    monkeypatch.setattr(payroll_bridge, "payroll_report_service", lambda connection: None)
    service = HrAnalyticsService(db, snapshot=_Snapshot({}), presence=_Presence({}))
    result = service.summary(tenant_id=TENANT, period=AUG, today=TODAY, include_payroll=True)
    assert result.value["payroll"] is None and result.value["payroll_status"] == "unavailable"


def test_a_mid_month_period_is_refused_before_anything_is_read(db):
    snapshot = _Snapshot({})
    result = HrAnalyticsService(db, snapshot=snapshot, presence=_Presence({})).summary(
        tenant_id=TENANT, period=datetime.date(2026, 9, 15), today=TODAY, include_payroll=True,
    )
    assert isinstance(result, Err) and result.code == "INVALID_PERIOD"
    assert snapshot.calls == []


def test_the_merged_services_answer_for_a_tenant_with_no_data(db):
    today = datetime.date.today()
    result = HrAnalyticsService(db).summary(
        tenant_id="hr-analytics-empty", period=today.replace(day=1), today=today, include_payroll=True,
    )
    assert isinstance(result, Ok)
    assert result.value["headcount"]["total"] == 0
    assert result.value["absence"]["rate"] is None  # nothing scheduled: unknown, not 0 %
    assert result.value["payroll_status"] in {"ok", "unavailable"}
    if result.value["payroll_status"] == "ok":
        assert result.value["payroll"]["departments"] == []
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python -m pytest modules/hr/api/test_analytics_service_integration.py -q`
Expected: collection error `No module named 'modules.hr.api.analytics_service'`.

- [ ] **Step 3: Write the bridge**

`backend/modules/hr/api/payroll_bridge.py`:

```python
"""hr's only way into payroll: an optional dependency, imported lazily.

payroll depends on hr (it reads employees and presence through hr's api), so hr must not import
payroll when a module loads, or the two would import each other. hr lists payroll under
`optional_depends` and reaches its public api only through this function. The function returns
None when the payroll module is not installed.
"""
from __future__ import annotations

import psycopg


def payroll_report_service(connection: psycopg.Connection):
    try:
        from modules.payroll.api.report_service import PayrollReportService
    except ImportError:  # pragma: no cover - payroll is an optional dependency of hr
        return None
    return PayrollReportService(connection)
```

- [ ] **Step 4: Write the service**

`backend/modules/hr/api/analytics_service.py`:

```python
"""The HR dashboard month: headcount, movements, absence, overtime and payroll cost.

Employees and presence come through hr's own api services (the phase 1/2 contract), and
payroll cost through payroll's public PayrollReportService (via payroll_bridge). The
arithmetic is the pure code in hr/domain/dashboard.py.
"""
from __future__ import annotations

import datetime

import psycopg

from core.domain.result import Err, Ok, Result
from modules.hr.api import payroll_bridge
from modules.hr.api.payroll_snapshot_service import PayrollSnapshotService
from modules.hr.api.presence_service import PresenceService
from modules.hr.domain.dashboard import attach_department_names, build_summary, previous_period, validate_period


class HrAnalyticsService:
    def __init__(self, connection: psycopg.Connection, *, snapshot=None, presence=None) -> None:
        self.connection = connection
        self.snapshot = snapshot if snapshot is not None else PayrollSnapshotService(connection)
        self.presence = presence if presence is not None else PresenceService(connection)

    def summary(self, *, tenant_id: str, period: datetime.date, today: datetime.date,
                include_payroll: bool) -> Result[dict]:
        """`include_payroll` is the caller's right to see pay. Without it payroll is never queried."""
        checked = validate_period(period, today=today)
        if isinstance(checked, Err):
            return checked
        previous = previous_period(period)
        payroll_rows, payroll_status = None, "hidden"
        if include_payroll:
            report = payroll_bridge.payroll_report_service(self.connection)
            if report is None:
                payroll_status = "unavailable"
            else:
                payroll_rows = report.cost_by_department(tenant_id=tenant_id, period_from=previous, period_to=period)
                payroll_status = "ok"
        summary = build_summary(
            period=period,
            today=today,
            snapshot=self.snapshot.employees_for_period(tenant_id=tenant_id, period=period),
            previous_snapshot=self.snapshot.employees_for_period(tenant_id=tenant_id, period=previous),
            presence=self.presence.month_summary(tenant_id=tenant_id, period=period),
            previous_presence=self.presence.month_summary(tenant_id=tenant_id, period=previous),
            payroll_rows=payroll_rows,
        )
        summary["payroll_status"] = payroll_status
        summary["presence_closed"] = self.presence.is_month_closed(tenant_id=tenant_id, period=period)
        return Ok(attach_department_names(summary, self._department_names(tenant_id)))

    def _department_names(self, tenant_id: str) -> dict[str, str]:
        rows = self.connection.execute(
            "SELECT id, name FROM hr.departments WHERE tenant_id = %s", (tenant_id,)
        ).fetchall()
        return {row[0]: row[1] for row in rows}
```

- [ ] **Step 5: Declare the optional dependency and the new services**

In `backend/modules/hr/module.json`, set `"optional_depends": ["payroll"]`. Then append these three names to the end of the existing `provides_api` array, keeping every entry phases 1–2 added (such as `PayrollSnapshotService` and `PresenceService`):

```json
  "optional_depends": ["payroll"],
```

```json
"HrAnalyticsService", "HrExpiryService", "SelfServiceService"
```

`permissions` does not change: `hr.self_service` and `hr.view_sensitive` were declared by phase 1.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest modules/hr/api/test_analytics_service_integration.py modules/hr/domain -q`
Expected: all pass, and the 5 analytics tests are not skipped.

- [ ] **Step 7: Commit**

```bash
git add backend/modules/hr/api/payroll_bridge.py backend/modules/hr/api/analytics_service.py backend/modules/hr/api/test_analytics_service_integration.py backend/modules/hr/module.json
git commit -m "feat(hr): HR analytics service over the snapshot, presence and payroll report contracts" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Dashboard endpoints

**Files:**
- Modify: `backend/modules/hr/api/router.py` (imports, and two routes after the existing `@router.get("/dashboard")`)
- Test: `backend/modules/hr/api/test_dashboard_router_integration.py`

**Interfaces:**
- Consumes: `HrAnalyticsService` (Task 3), `HrExpiryService` (Task 2), `core.tenancy.user_has_permission`.
- Produces (used by Task 8):
  - `GET /hr/dashboard/summary?period=YYYY-MM-01` (needs `hr.view_dashboard`) → the Task 3 summary. It includes payroll only for holders of `hr.view_sensitive`. Returns 422 `INVALID_PERIOD` / `PERIOD_IN_FUTURE`.
  - `GET /hr/dashboard/expiring` (needs `hr.view_dashboard`) → the Task 2 result.

- [ ] **Step 1: Write the failing tests**

`backend/modules/hr/api/test_dashboard_router_integration.py`:

```python
"""The HR dashboard endpoints over HTTP: who may read them, and what the payroll block needs."""
from __future__ import annotations

import datetime

import pytest
from fastapi import FastAPI

pytest.importorskip("httpx", reason="the FastAPI test client needs httpx (requirements-dev.txt)")
from fastapi.testclient import TestClient  # noqa: E402
from ulid import ULID  # noqa: E402

from core.domain.result import Ok  # noqa: E402
from core.tenancy import TenantContext, require_session  # noqa: E402
from modules.hr.api import router as router_module  # noqa: E402

TENANT = "hr-dashboard-router-test"


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
    user = str(ULID())
    db.execute("INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
               (user, TENANT, f"{user}@test.local"))
    wrapped = _Connection(db)
    monkeypatch.setattr(router_module, "get_connection", lambda: wrapped)
    monkeypatch.setattr("core.tenancy.get_connection", lambda: wrapped)
    app = FastAPI()
    app.include_router(router_module.router)
    app.dependency_overrides[require_session] = lambda: TenantContext(tenant_id=TENANT, user_id=user, session_token="t")

    def grant(*permissions: str) -> None:
        for permission in permissions:
            db.execute("INSERT INTO core.user_permissions (user_id, permission) VALUES (%s, %s)", (user, permission))

    return {"client": TestClient(app), "grant": grant}


class _FakeAnalytics:
    seen: list[dict] = []

    def __init__(self, connection) -> None:
        pass

    def summary(self, **kwargs):
        _FakeAnalytics.seen.append(kwargs)
        return Ok({"payroll_status": "ok" if kwargs["include_payroll"] else "hidden"})


def test_the_dashboard_needs_view_dashboard(world):
    assert world["client"].get("/hr/dashboard/summary", params={"period": "2026-08-01"}).status_code == 403
    assert world["client"].get("/hr/dashboard/expiring").status_code == 403


def test_payroll_cost_is_asked_for_only_when_the_user_may_see_pay(world, monkeypatch):
    _FakeAnalytics.seen = []
    monkeypatch.setattr(router_module, "HrAnalyticsService", _FakeAnalytics)
    world["grant"]("hr.view_dashboard")
    first = world["client"].get("/hr/dashboard/summary", params={"period": "2026-08-01"})
    assert first.json() == {"payroll_status": "hidden"}
    world["grant"]("hr.view_sensitive")
    second = world["client"].get("/hr/dashboard/summary", params={"period": "2026-08-01"})
    assert second.json() == {"payroll_status": "ok"}
    assert [call["include_payroll"] for call in _FakeAnalytics.seen] == [False, True]
    assert _FakeAnalytics.seen[0]["period"] == datetime.date(2026, 8, 1)


def test_a_mid_month_period_is_refused_in_both_languages(world):
    world["grant"]("hr.view_dashboard")
    response = world["client"].get("/hr/dashboard/summary", params={"period": "2026-08-15"})
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "INVALID_PERIOD" and detail["message_fr"]


def test_expiring_lists_nothing_until_the_horizons_are_set(world):
    world["grant"]("hr.view_dashboard")
    assert world["client"].get("/hr/dashboard/expiring").json() == {"horizons": None, "items": []}
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python -m pytest modules/hr/api/test_dashboard_router_integration.py -q`
Expected: the `/summary` and `/expiring` requests get 404 from FastAPI, so the tests fail; `test_payroll_cost_is_asked_for…` fails with `AttributeError: … has no attribute 'HrAnalyticsService'`.

- [ ] **Step 3: Add the routes**

In `backend/modules/hr/api/router.py`, extend the imports:

```python
from core.tenancy import TenantContext, require_permission, user_has_permission
from modules.hr.api.analytics_service import HrAnalyticsService
from modules.hr.api.expiry_service import HrExpiryService
```

Add these right after the existing `@router.get("/dashboard")` handler and keep that handler as it is:

```python
@router.get("/dashboard/summary")
def dashboard_summary(period: datetime.date, tenant: TenantContext = Depends(require_permission("hr.view_dashboard"))):
    """The dashboard month. Payroll cost is included only for a user who may see pay (hr.view_sensitive):
    grouped by a small department, it would reveal individual salaries."""
    with get_connection() as connection:
        include_payroll = user_has_permission(connection, user_id=tenant.user_id, permission="hr.view_sensitive")
        result = HrAnalyticsService(connection).summary(
            tenant_id=tenant.tenant_id, period=period, today=datetime.date.today(), include_payroll=include_payroll,
        )
    if isinstance(result, Err):
        fail(result)
    return result.value


@router.get("/dashboard/expiring")
def dashboard_expiring(tenant: TenantContext = Depends(require_permission("hr.view_dashboard"))):
    with get_connection() as connection:
        return HrExpiryService(connection).expiring(tenant_id=tenant.tenant_id, today=datetime.date.today())
```

The router's `fail()` maps any code other than `NOT_FOUND` / `DUPLICATE*` to 422, which is right for `INVALID_PERIOD` and `PERIOD_IN_FUTURE`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest modules/hr/api/test_dashboard_router_integration.py -q`
Expected: `4 passed`.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/hr/api/router.py backend/modules/hr/api/test_dashboard_router_integration.py
git commit -m "feat(hr): dashboard summary and expiry endpoints; payroll cost behind hr.view_sensitive" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Self-service: own-record selection and service

**Files:**
- Create: `backend/modules/hr/domain/self_service.py`
- Test: `backend/modules/hr/domain/test_self_service.py`
- Create: `backend/modules/hr/api/self_service.py`
- Test: `backend/modules/hr/api/test_self_service_integration.py`

**Interfaces:**
- Consumes: A1 (`employees_for_period` with `employee_ids`), A3 (`get_by_user`), A4 (`payslips_for_employee`), A6, A7, A8; `payroll_bridge` (Task 3).
- Produces (used by Task 6):
  - `SelfServiceService(connection, *, snapshot=None, leave=None)` with
    - `my_file(*, tenant_id, user_id, today) -> Result[dict]`: the whitelisted file, `department_name`, `position_title` and `contract` (`contract_type, start_date, end_date, weekly_hours, pay_frequency`) or None
    - `my_payslips(*, tenant_id, user_id) -> Result[list[dict]]`: `id, period, run_type, run_status, gross, net`, own payslips of approved/paid runs only, newest first
    - `my_leave(*, tenant_id, user_id, year) -> Result[dict]`: `{year, balances: [{leave_type_id, code, name, paid, accrued, taken, adjusted, available|None, pending}], requests: [{id, leave_type_id, leave_type_name, start_date, end_date, days, half_day, status, reason}]}`
    - `request_leave(*, tenant_id, user_id, leave_type_id, start_date, end_date, half_day, reason) -> Result[dict]`
  - Every method returns `Err("NO_EMPLOYEE_LINK", …)` when the user has no employee file.

- [ ] **Step 1: Write the failing domain tests**

`backend/modules/hr/domain/test_self_service.py`:

```python
"""What an employee sees of their own record."""
from __future__ import annotations

import datetime
from decimal import Decimal

from modules.hr.domain.self_service import leave_balances, my_file_view, my_payslips


def test_my_file_shows_the_whitelisted_fields_and_the_current_contract_terms():
    employee = {"id": "E1", "tenant_id": "t", "user_id": "U1", "employee_no": "M-001", "first_name": "Awa",
                "last_name": "Traoré", "hire_date": datetime.date(2024, 3, 4), "status": "active",
                "department_id": "D1", "position_id": "P1"}
    contract = {"id": "C1", "contract_type": "cdi", "start_date": datetime.date(2024, 3, 4), "end_date": None,
                "weekly_hours": Decimal("40"), "pay_frequency": "monthly", "base_salary": Decimal("200000"),
                "components": []}
    view = my_file_view(employee, department_name="Production", position_title="Opératrice", contract=contract)
    assert view["employee_no"] == "M-001" and view["department_name"] == "Production"
    assert view["position_title"] == "Opératrice"
    for hidden in ("id", "tenant_id", "user_id", "department_id", "position_id", "status"):
        assert hidden not in view
    assert view["contract"] == {"contract_type": "cdi", "start_date": datetime.date(2024, 3, 4), "end_date": None,
                                "weekly_hours": Decimal("40"), "pay_frequency": "monthly"}
    assert view["birth_date"] is None  # a field the record does not carry is shown empty, never invented
    assert my_file_view(employee, department_name=None, position_title=None, contract=None)["contract"] is None


def _payslip(payslip_id, employee_id, period, status):
    return {"id": payslip_id, "employee_id": employee_id, "period": period, "run_type": "regular",
            "run_status": status, "gross": Decimal("250000"), "net": Decimal("200000"), "snapshot": {"x": 1}}


def test_my_payslips_keep_only_mine_of_approved_or_paid_runs_newest_first():
    rows = [
        _payslip("P1", "E1", datetime.date(2026, 7, 1), "paid"),
        _payslip("P2", "E1", datetime.date(2026, 8, 1), "approved"),
        _payslip("P3", "E1", datetime.date(2026, 9, 1), "calculated"),
        _payslip("P4", "E2", datetime.date(2026, 8, 1), "paid"),
        _payslip("P5", "E1", datetime.date(2026, 6, 1), "reversed"),
    ]
    result = my_payslips(rows, employee_id="E1")
    assert [row["id"] for row in result] == ["P2", "P1"]
    assert set(result[0]) == {"id", "period", "run_type", "run_status", "gross", "net"}


def test_leave_balance_is_accrued_plus_adjusted_minus_taken_with_pending_apart():
    types = [
        {"id": "T1", "code": "CP", "name": "Congé payé", "paid": True, "accrual_days_per_month": Decimal("2.5")},
        {"id": "T2", "code": "SS", "name": "Sans solde", "paid": False, "accrual_days_per_month": Decimal("0")},
        {"id": "T3", "code": "EX", "name": "Exceptionnel", "paid": True, "accrual_days_per_month": None},
    ]
    balances = [
        {"leave_type_id": "T1", "accrued": Decimal("22.5"), "taken": Decimal("5"), "adjusted": Decimal("-1")},
        {"leave_type_id": "T3", "accrued": Decimal("0"), "taken": Decimal("0"), "adjusted": Decimal("3")},
    ]
    lines = {line["code"]: line for line in leave_balances(leave_types=types, balances=balances, pending_days={"T1": Decimal("2")})}
    assert lines["CP"]["available"] == Decimal("16.5") and lines["CP"]["pending"] == Decimal("2")
    assert lines["SS"]["available"] is None  # neither accrues nor has a balance: no figure to show
    assert lines["EX"]["available"] == Decimal("3")  # granted by adjustment
    assert lines["SS"]["pending"] == Decimal(0)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python -m pytest modules/hr/domain/test_self_service.py -q`
Expected: collection error `No module named 'modules.hr.domain.self_service'`.

- [ ] **Step 3: Write the domain selection**

`backend/modules/hr/domain/self_service.py`:

```python
"""What an employee sees of their own record. Pure selection, no database."""
from __future__ import annotations

from decimal import Decimal
from typing import Iterable

# The employee file as its owner sees it (read-only). Identifiers, the user link and the
# workflow status stay out; ids become names (department_name, position_title).
MY_FILE_FIELDS: tuple[str, ...] = (
    "employee_no", "first_name", "last_name", "birth_date", "birth_place", "nationality", "national_id",
    "inps_no", "amo_no", "marital_status", "email", "phone", "address", "emergency_contact", "badge_no",
    "site", "job_title", "hire_date",
)
MY_CONTRACT_FIELDS: tuple[str, ...] = ("contract_type", "start_date", "end_date", "weekly_hours", "pay_frequency")

# A payslip is the employee's to see once its run is approved or paid: a draft or calculated run
# can still change, and a reversed one no longer stands. The same rule guards the payslip print
# route in payroll/domain/payslip_access.py.
VISIBLE_RUN_STATUSES = frozenset({"approved", "paid"})
PAYSLIP_FIELDS: tuple[str, ...] = ("id", "period", "run_type", "run_status", "gross", "net")
_ZERO = Decimal(0)


def my_file_view(employee: dict, *, department_name: str | None, position_title: str | None,
                 contract: dict | None) -> dict:
    view = {field: employee.get(field) for field in MY_FILE_FIELDS}
    view["department_name"] = department_name
    view["position_title"] = position_title
    view["contract"] = None if contract is None else {field: contract.get(field) for field in MY_CONTRACT_FIELDS}
    return view


def my_payslips(rows: Iterable[dict], *, employee_id: str) -> list[dict]:
    """The employee's own payslips of approved/paid runs, newest first. Rows for anyone else are
    dropped even if the source returned them, so a generous source never leaks a payslip."""
    own = [row for row in rows if row.get("employee_id") == employee_id and row.get("run_status") in VISIBLE_RUN_STATUSES]
    picked = [{field: row.get(field) for field in PAYSLIP_FIELDS} for row in own]
    return sorted(picked, key=lambda row: (row["period"], row["id"]), reverse=True)


def leave_balances(*, leave_types: Iterable[dict], balances: Iterable[dict],
                   pending_days: dict[str, Decimal]) -> list[dict]:
    """One line per leave type. available = accrued + adjusted - taken. Pending requests are shown
    apart, because they are deducted only on approval. A type that neither accrues nor has a
    balance row has no available figure (None), rather than a misleading 0."""
    by_type = {row["leave_type_id"]: row for row in balances}
    lines = []
    for leave_type in leave_types:
        row = by_type.get(leave_type["id"])
        accrues = Decimal(leave_type["accrual_days_per_month"] or 0) > 0
        accrued = Decimal(row["accrued"]) if row else _ZERO
        taken = Decimal(row["taken"]) if row else _ZERO
        adjusted = Decimal(row["adjusted"]) if row else _ZERO
        lines.append({
            "leave_type_id": leave_type["id"],
            "code": leave_type["code"],
            "name": leave_type["name"],
            "paid": leave_type["paid"],
            "accrued": accrued,
            "taken": taken,
            "adjusted": adjusted,
            "available": accrued + adjusted - taken if (row is not None or accrues) else None,
            "pending": Decimal(pending_days.get(leave_type["id"], 0)),
        })
    return lines
```

- [ ] **Step 4: Run the domain tests to verify they pass**

Run: `.venv/Scripts/python -m pytest modules/hr/domain/test_self_service.py -q`
Expected: `3 passed`.

- [ ] **Step 5: Write the failing service tests**

`backend/modules/hr/api/test_self_service_integration.py`:

```python
"""SelfServiceService: everything is read for the employee linked to the calling user, and nobody else."""
from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from ulid import ULID

from core.domain.result import Err
from modules.hr.api import payroll_bridge
from modules.hr.api.self_service import SelfServiceService

TENANT = "hr-self-service-test"
TODAY = datetime.date(2026, 9, 25)
AUG = datetime.date(2026, 8, 1)


class _Snapshot:
    def employees_for_period(self, *, tenant_id, period, employee_ids=None):
        return []


class _Report:
    def __init__(self, by_employee: dict, *, leak: bool = False) -> None:
        self.by_employee, self.leak, self.asked = by_employee, leak, []

    def payslips_for_employee(self, *, tenant_id, employee_id):
        self.asked.append(employee_id)
        if self.leak:
            return [row for rows in self.by_employee.values() for row in rows]
        return self.by_employee.get(employee_id, [])


def _payslip(payslip_id, employee_id, status):
    return {"id": payslip_id, "employee_id": employee_id, "period": AUG, "run_type": "regular",
            "run_status": status, "gross": Decimal("250000"), "net": Decimal("200000")}


@pytest.fixture
def people(db):
    department = str(ULID())
    db.execute("INSERT INTO hr.departments (id, tenant_id, code, name) VALUES (%s, %s, 'ATL', 'Atelier')", (department, TENANT))
    ids = {}
    for name in ("awa", "moussa", "stranger"):
        user = str(ULID())
        db.execute("INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
                   (user, TENANT, f"{user}@test.local"))
        ids[f"{name}_user"] = user
    for name in ("awa", "moussa"):
        employee = str(ULID())
        db.execute(
            "INSERT INTO hr.employees (id, tenant_id, employee_no, first_name, last_name, department_id, hire_date, status, user_id) "
            "VALUES (%s, %s, %s, %s, 'Test', %s, %s, 'active', %s)",
            (employee, TENANT, f"SS-{name}", name.title(), department, datetime.date(2025, 1, 6), ids[f"{name}_user"]),
        )
        ids[f"{name}_employee"] = employee
    return ids


def _report(people, *, leak=False) -> _Report:
    return _Report({
        people["awa_employee"]: [_payslip("P-awa", people["awa_employee"], "approved")],
        people["moussa_employee"]: [_payslip("P-moussa", people["moussa_employee"], "paid")],
    }, leak=leak)


def test_a_user_without_an_employee_file_is_told_so(db, people):
    result = SelfServiceService(db, snapshot=_Snapshot()).my_file(tenant_id=TENANT, user_id=people["stranger_user"], today=TODAY)
    assert isinstance(result, Err) and result.code == "NO_EMPLOYEE_LINK" and result.message_fr


def test_my_file_is_the_employee_linked_to_my_user(db, people):
    result = SelfServiceService(db, snapshot=_Snapshot()).my_file(tenant_id=TENANT, user_id=people["awa_user"], today=TODAY)
    assert result.value["employee_no"] == "SS-awa" and result.value["department_name"] == "Atelier"
    assert "user_id" not in result.value and result.value["contract"] is None


def test_payslips_are_asked_for_my_employee_only(db, people, monkeypatch):
    report = _report(people)
    monkeypatch.setattr(payroll_bridge, "payroll_report_service", lambda connection: report)
    result = SelfServiceService(db).my_payslips(tenant_id=TENANT, user_id=people["awa_user"])
    assert [row["id"] for row in result.value] == ["P-awa"]
    assert report.asked == [people["awa_employee"]]


def test_a_source_returning_too_much_still_shows_only_mine(db, people, monkeypatch):
    monkeypatch.setattr(payroll_bridge, "payroll_report_service", lambda connection: _report(people, leak=True))
    result = SelfServiceService(db).my_payslips(tenant_id=TENANT, user_id=people["awa_user"])
    assert [row["id"] for row in result.value] == ["P-awa"]


def test_without_the_payroll_module_i_have_no_payslips(db, people, monkeypatch):
    monkeypatch.setattr(payroll_bridge, "payroll_report_service", lambda connection: None)
    assert SelfServiceService(db).my_payslips(tenant_id=TENANT, user_id=people["awa_user"]).value == []


def test_my_leave_shows_my_balance_not_a_colleagues(db, people):
    leave_type = str(ULID())
    db.execute(
        "INSERT INTO hr.leave_types (id, tenant_id, code, name, paid, accrual_days_per_month) "
        "VALUES (%s, %s, 'CP', 'Congé payé', TRUE, 2.5)",
        (leave_type, TENANT),
    )
    for employee, accrued in ((people["awa_employee"], 20), (people["moussa_employee"], 7)):
        db.execute(
            "INSERT INTO hr.leave_balances (id, tenant_id, employee_id, leave_type_id, year, accrued, taken, adjusted) "
            "VALUES (%s, %s, %s, %s, 2026, %s, 2, 0)",
            (str(ULID()), TENANT, employee, leave_type, accrued),
        )
    result = SelfServiceService(db, snapshot=_Snapshot()).my_leave(tenant_id=TENANT, user_id=people["awa_user"], year=2026)
    (line,) = result.value["balances"]
    assert line["code"] == "CP" and line["available"] == Decimal("18")
    assert result.value["requests"] == []
```

Run: `.venv/Scripts/python -m pytest modules/hr/api/test_self_service_integration.py -q`
Expected: collection error `No module named 'modules.hr.api.self_service'`.

- [ ] **Step 6: Write the service**

`backend/modules/hr/api/self_service.py`. If the contract check found `EmployeeService` or `LeaveRequestService` elsewhere, or the create method under another name or signature (A3, A8), change the import or the one `self.leave.create_request(...)` call:

```python
"""The signed-in user's own HR record, for /me.

The employee is always the one linked to the session's user (hr.employees.user_id, read through
EmployeeService.get_by_user). No method here takes an employee id from its caller, so no request
can reach another employee's file, payslips or leave.
"""
from __future__ import annotations

import datetime

import psycopg

from core.domain.result import Err, Ok, Result
from modules.hr.api import payroll_bridge
from modules.hr.api.leave_service import LeaveRequestService
from modules.hr.api.payroll_snapshot_service import PayrollSnapshotService
from modules.hr.api.service import EmployeeService
from modules.hr.domain.self_service import leave_balances, my_file_view, my_payslips

NO_EMPLOYEE_LINK = Err(
    "NO_EMPLOYEE_LINK",
    "your user account is not linked to an employee file",
    "votre compte utilisateur n'est lié à aucune fiche employé",
)


class SelfServiceService:
    def __init__(self, connection: psycopg.Connection, *, snapshot=None, leave=None) -> None:
        self.connection = connection
        self.employees = EmployeeService(connection)
        self.snapshot = snapshot if snapshot is not None else PayrollSnapshotService(connection)
        self.leave = leave if leave is not None else LeaveRequestService(connection)

    def _me(self, tenant_id: str, user_id: str) -> dict | None:
        return self.employees.get_by_user(tenant_id=tenant_id, user_id=user_id)

    def _name(self, sql: str, entity_id: str | None, tenant_id: str) -> str | None:
        if entity_id is None:
            return None
        row = self.connection.execute(sql, (entity_id, tenant_id)).fetchone()
        return None if row is None else row[0]

    def my_file(self, *, tenant_id: str, user_id: str, today: datetime.date) -> Result[dict]:
        me = self._me(tenant_id, user_id)
        if me is None:
            return NO_EMPLOYEE_LINK
        current = self.snapshot.employees_for_period(
            tenant_id=tenant_id, period=today.replace(day=1), employee_ids=[me["id"]],
        )
        return Ok(my_file_view(
            me,
            department_name=self._name(
                "SELECT name FROM hr.departments WHERE id = %s AND tenant_id = %s", me.get("department_id"), tenant_id),
            position_title=self._name(
                "SELECT title FROM hr.positions WHERE id = %s AND tenant_id = %s", me.get("position_id"), tenant_id),
            contract=current[0]["contract"] if current else None,
        ))

    def my_payslips(self, *, tenant_id: str, user_id: str) -> Result[list[dict]]:
        me = self._me(tenant_id, user_id)
        if me is None:
            return NO_EMPLOYEE_LINK
        report = payroll_bridge.payroll_report_service(self.connection)
        if report is None:
            return Ok([])
        rows = report.payslips_for_employee(tenant_id=tenant_id, employee_id=me["id"])
        return Ok(my_payslips(rows, employee_id=me["id"]))

    def my_leave(self, *, tenant_id: str, user_id: str, year: int) -> Result[dict]:
        me = self._me(tenant_id, user_id)
        if me is None:
            return NO_EMPLOYEE_LINK
        employee_id = me["id"]
        leave_types = [
            {"id": r[0], "code": r[1], "name": r[2], "paid": r[3], "accrual_days_per_month": r[4]}
            for r in self.connection.execute(
                "SELECT id, code, name, paid, accrual_days_per_month FROM hr.leave_types WHERE tenant_id = %s ORDER BY code",
                (tenant_id,),
            ).fetchall()
        ]
        balances = [
            {"leave_type_id": r[0], "accrued": r[1], "taken": r[2], "adjusted": r[3]}
            for r in self.connection.execute(
                "SELECT leave_type_id, accrued, taken, adjusted FROM hr.leave_balances "
                "WHERE tenant_id = %s AND employee_id = %s AND year = %s",
                (tenant_id, employee_id, year),
            ).fetchall()
        ]
        pending = dict(self.connection.execute(
            """
            SELECT leave_type_id, COALESCE(SUM(days), 0) FROM hr.leave_requests
            WHERE tenant_id = %s AND employee_id = %s AND status = 'pending' AND leave_type_id IS NOT NULL
              AND EXTRACT(YEAR FROM start_date) = %s
            GROUP BY leave_type_id
            """,
            (tenant_id, employee_id, year),
        ).fetchall())
        requests = [
            {"id": r[0], "leave_type_id": r[1], "leave_type_name": r[2], "start_date": r[3], "end_date": r[4],
             "days": r[5], "half_day": r[6], "status": r[7], "reason": r[8]}
            for r in self.connection.execute(
                """
                SELECT r.id, r.leave_type_id, t.name, r.start_date, r.end_date, r.days, r.half_day, r.status, r.reason
                FROM hr.leave_requests r
                LEFT JOIN hr.leave_types t ON t.id = r.leave_type_id AND t.tenant_id = r.tenant_id
                WHERE r.tenant_id = %s AND r.employee_id = %s
                ORDER BY r.start_date DESC
                """,
                (tenant_id, employee_id),
            ).fetchall()
        ]
        return Ok({
            "year": year,
            "balances": leave_balances(leave_types=leave_types, balances=balances, pending_days=pending),
            "requests": requests,
        })

    def request_leave(self, *, tenant_id: str, user_id: str, leave_type_id: str, start_date: datetime.date,
                      end_date: datetime.date, half_day: bool, reason: str | None) -> Result[dict]:
        """Files the request for the caller's own employee. Phase 2's LeaveRequestService validates it,
        counts the days and audits it."""
        me = self._me(tenant_id, user_id)
        if me is None:
            return NO_EMPLOYEE_LINK
        return self.leave.create_request(
            tenant_id=tenant_id, actor_id=user_id, employee_id=me["id"], leave_type_id=leave_type_id,
            start_date=start_date, end_date=end_date, half_day=half_day, reason=reason,
        )
```

- [ ] **Step 7: Run all of the task's tests to verify they pass**

Run: `.venv/Scripts/python -m pytest modules/hr/domain/test_self_service.py modules/hr/api/test_self_service_integration.py -q`
Expected: `9 passed`, with none skipped.

- [ ] **Step 8: Commit**

```bash
git add backend/modules/hr/domain/self_service.py backend/modules/hr/domain/test_self_service.py backend/modules/hr/api/self_service.py backend/modules/hr/api/test_self_service_integration.py
git commit -m "feat(hr): self-service service bound to the caller's own employee file" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

If the contract check required an additive fix to `payslips_for_employee` (A4), add those payroll files to this commit.

---

### Task 6: `/hr/me` endpoints

**Files:**
- Modify: `backend/modules/hr/api/router.py`
- Test: `backend/modules/hr/api/test_self_service_router_integration.py`

**Interfaces:**
- Consumes: `SelfServiceService` (Task 5).
- Produces (used by Task 9). Every route needs `hr.self_service`, and `NO_EMPLOYEE_LINK` → 404:
  - `GET /hr/me/file` → `my_file`
  - `GET /hr/me/payslips` → `my_payslips` (query parameters are ignored)
  - `GET /hr/me/leave?year=` → `my_leave` (default: the current year)
  - `POST /hr/me/leave-requests` body `{leave_type_id, start_date, end_date, half_day=false, reason=null}`, extra fields refused (422) → 201 with the created request

- [ ] **Step 1: Write the failing tests**

`backend/modules/hr/api/test_self_service_router_integration.py`:

```python
"""/hr/me over HTTP: gated by hr.self_service and bound to the caller's own employee file."""
from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from fastapi import FastAPI

pytest.importorskip("httpx", reason="the FastAPI test client needs httpx (requirements-dev.txt)")
from fastapi.testclient import TestClient  # noqa: E402
from ulid import ULID  # noqa: E402

from core.tenancy import TenantContext, require_session  # noqa: E402
from modules.hr.api import payroll_bridge  # noqa: E402
from modules.hr.api import router as router_module  # noqa: E402

TENANT = "hr-me-router-test"
ME_READS = ("/hr/me/file", "/hr/me/payslips", "/hr/me/leave")


class _Connection:
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


class _Report:
    def __init__(self, by_employee: dict) -> None:
        self.by_employee, self.asked = by_employee, []

    def payslips_for_employee(self, *, tenant_id, employee_id):
        self.asked.append(employee_id)
        return self.by_employee.get(employee_id, [])


def _payslip(payslip_id, employee_id, status):
    return {"id": payslip_id, "employee_id": employee_id, "period": datetime.date(2030, 4, 1), "run_type": "regular",
            "run_status": status, "gross": Decimal("250000"), "net": Decimal("200000")}


@pytest.fixture
def world(db, monkeypatch):
    users, employees = {}, {}
    for name in ("awa", "moussa", "stranger"):
        users[name] = str(ULID())
        db.execute("INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
                   (users[name], TENANT, f"{users[name]}@test.local"))
    for name in ("awa", "moussa"):
        employees[name] = str(ULID())
        db.execute(
            "INSERT INTO hr.employees (id, tenant_id, employee_no, first_name, last_name, hire_date, status, user_id) "
            "VALUES (%s, %s, %s, %s, 'Test', %s, 'active', %s)",
            (employees[name], TENANT, f"ME-{name}", name.title(), datetime.date(2029, 1, 7), users[name]),
        )
    leave_type = str(ULID())
    db.execute(
        "INSERT INTO hr.leave_types (id, tenant_id, code, name, paid, accrual_days_per_month) "
        "VALUES (%s, %s, 'CP', 'Congé payé', TRUE, 2.5)",
        (leave_type, TENANT),
    )
    db.execute(
        "INSERT INTO hr.leave_balances (id, tenant_id, employee_id, leave_type_id, year, accrued, taken, adjusted) "
        "VALUES (%s, %s, %s, %s, 2030, 20, 0, 0)",
        (str(ULID()), TENANT, employees["awa"], leave_type),
    )
    report = _Report({
        employees["awa"]: [_payslip("P-awa", employees["awa"], "approved")],
        employees["moussa"]: [_payslip("P-moussa", employees["moussa"], "paid")],
    })
    monkeypatch.setattr(payroll_bridge, "payroll_report_service", lambda connection: report)
    wrapped = _Connection(db)
    monkeypatch.setattr(router_module, "get_connection", lambda: wrapped)
    monkeypatch.setattr("core.tenancy.get_connection", lambda: wrapped)
    acting = {"user": users["awa"]}
    app = FastAPI()
    app.include_router(router_module.router)
    app.dependency_overrides[require_session] = lambda: TenantContext(tenant_id=TENANT, user_id=acting["user"], session_token="t")

    def act_as(name: str, *permissions: str) -> None:
        acting["user"] = users[name]
        for permission in permissions:
            db.execute("INSERT INTO core.user_permissions (user_id, permission) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                       (users[name], permission))

    return {"client": TestClient(app), "act_as": act_as, "employees": employees, "leave_type": leave_type,
            "report": report, "db": db}


def _request_body(world, **extra):
    return {"leave_type_id": world["leave_type"], "start_date": "2030-05-06", "end_date": "2030-05-07", **extra}


def test_every_me_route_needs_self_service(world):
    world["act_as"]("awa")
    for path in ME_READS:
        assert world["client"].get(path).status_code == 403, path
    assert world["client"].post("/hr/me/leave-requests", json=_request_body(world)).status_code == 403


def test_a_user_without_an_employee_file_gets_a_404_that_says_why(world):
    world["act_as"]("stranger", "hr.self_service")
    response = world["client"].get("/hr/me/file")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "NO_EMPLOYEE_LINK" and response.json()["detail"]["message_fr"]


def test_my_file_is_my_own(world):
    world["act_as"]("awa", "hr.self_service")
    body = world["client"].get("/hr/me/file").json()
    assert body["employee_no"] == "ME-awa" and "user_id" not in body


def test_asking_for_a_colleague_still_returns_only_my_payslips(world):
    world["act_as"]("awa", "hr.self_service")
    response = world["client"].get("/hr/me/payslips", params={"employee_id": world["employees"]["moussa"]})
    assert [row["id"] for row in response.json()] == ["P-awa"]
    assert world["report"].asked == [world["employees"]["awa"]]


def test_each_employee_sees_their_own_payslips(world):
    world["act_as"]("moussa", "hr.self_service")
    assert [row["id"] for row in world["client"].get("/hr/me/payslips").json()] == ["P-moussa"]


def test_my_leave_is_my_balance(world):
    world["act_as"]("awa", "hr.self_service")
    body = world["client"].get("/hr/me/leave", params={"year": 2030}).json()
    assert [(line["code"], line["available"]) for line in body["balances"]] == [("CP", 20)]


def test_a_leave_request_is_filed_for_my_own_employee(world):
    world["act_as"]("awa", "hr.self_service")
    response = world["client"].post("/hr/me/leave-requests", json=_request_body(world))
    assert response.status_code == 201, response.text
    owner = world["db"].execute("SELECT employee_id FROM hr.leave_requests WHERE id = %s", (response.json()["id"],)).fetchone()[0]
    assert owner == world["employees"]["awa"]


def test_an_employee_id_in_the_leave_body_is_refused(world):
    world["act_as"]("awa", "hr.self_service")
    response = world["client"].post("/hr/me/leave-requests",
                                    json=_request_body(world, employee_id=world["employees"]["moussa"]))
    assert response.status_code == 422
    written = world["db"].execute("SELECT count(*) FROM hr.leave_requests WHERE employee_id = %s",
                                  (world["employees"]["moussa"],)).fetchone()[0]
    assert written == 0
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python -m pytest modules/hr/api/test_self_service_router_integration.py -q`
Expected: failures, because FastAPI answers 404 for every `/hr/me/*` route.

- [ ] **Step 3: Add the routes and the 404 mapping**

In `backend/modules/hr/api/router.py`, add `ConfigDict` to the pydantic import and import the service:

```python
from pydantic import BaseModel, ConfigDict
from modules.hr.api.self_service import SelfServiceService
```

Make `fail()` answer 404 for `NO_EMPLOYEE_LINK` as well. If phase 1 changed `fail()`, add the code to whatever set it uses for 404:

```python
_NOT_FOUND_CODES = {"NOT_FOUND", "NO_EMPLOYEE_LINK"}


def fail(result: Err) -> None:
    code = status.HTTP_404_NOT_FOUND if result.code in _NOT_FOUND_CODES else status.HTTP_409_CONFLICT if result.code.startswith("DUPLICATE") else status.HTTP_422_UNPROCESSABLE_ENTITY
    raise HTTPException(code, err_detail(result))
```

Add the body model next to the other models, and the routes at the end of the file:

```python
class MyLeaveRequestBody(BaseModel):
    # extra="forbid": an employee id in the body is refused (422), never honoured. The employee
    # is always the one linked to the session's user.
    model_config = ConfigDict(extra="forbid")

    leave_type_id: str
    start_date: datetime.date
    end_date: datetime.date
    half_day: bool = False
    reason: str | None = None
```

```python
# ---- Self-service: the caller's own record only (hr.self_service) -----------------------

@router.get("/me/file")
def my_file(tenant: TenantContext = Depends(require_permission("hr.self_service"))):
    with get_connection() as connection:
        result = SelfServiceService(connection).my_file(tenant_id=tenant.tenant_id, user_id=tenant.user_id, today=datetime.date.today())
    if isinstance(result, Err):
        fail(result)
    return result.value


@router.get("/me/payslips")
def my_payslips(tenant: TenantContext = Depends(require_permission("hr.self_service"))):
    with get_connection() as connection:
        result = SelfServiceService(connection).my_payslips(tenant_id=tenant.tenant_id, user_id=tenant.user_id)
    if isinstance(result, Err):
        fail(result)
    return result.value


@router.get("/me/leave")
def my_leave(year: int | None = None, tenant: TenantContext = Depends(require_permission("hr.self_service"))):
    with get_connection() as connection:
        result = SelfServiceService(connection).my_leave(
            tenant_id=tenant.tenant_id, user_id=tenant.user_id, year=year or datetime.date.today().year,
        )
    if isinstance(result, Err):
        fail(result)
    return result.value


@router.post("/me/leave-requests", status_code=status.HTTP_201_CREATED)
def my_leave_request(body: MyLeaveRequestBody, tenant: TenantContext = Depends(require_permission("hr.self_service"))):
    with get_connection() as connection:
        result = SelfServiceService(connection).request_leave(tenant_id=tenant.tenant_id, user_id=tenant.user_id, **body.model_dump())
        if isinstance(result, Err):
            connection.rollback()
            fail(result)
        connection.commit()
        return result.value
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest modules/hr/api/test_self_service_router_integration.py modules/hr/api/test_dashboard_router_integration.py -q`
Expected: `12 passed`. If `test_a_leave_request_is_filed_for_my_own_employee` fails because phase 2's `create_request` needs more setup (A7/A8), add that setup to `world` and run again. Do not change phase 2's code.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/hr/api/router.py backend/modules/hr/api/test_self_service_router_integration.py
git commit -m "feat(hr): /hr/me self-service endpoints; the employee always comes from the session" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Payroll lets a payslip's owner read it through the print route

**Files:**
- Create: `backend/modules/payroll/domain/payslip_access.py`
- Test: `backend/modules/payroll/domain/test_payslip_access.py`
- Create: `backend/modules/payroll/api/payslip_access.py`
- Modify: `backend/modules/payroll/api/router.py` (single-payslip GET handlers)
- Test: `backend/modules/payroll/api/test_payslip_access_integration.py`

**Interfaces:**
- Consumes: `EmployeeService.get_by_user` (A3; payroll → hr is the allowed direction), payroll's own tables `payroll.payslips`/`payroll.runs` (A9), `core.tenancy.user_has_permission`.
- Produces:
  - `may_read_payslip(*, payslip_employee_id, run_status, own_employee_id, is_payroll_staff, has_self_service) -> bool`
  - `require_payslip_reader(payslip_id: str, tenant = Depends(require_session)) -> TenantContext`: 403 `FORBIDDEN` to a user with neither right, 404 `NOT_FOUND` to anyone else who may not read *this* payslip
  - `PAYSLIP_STAFF_PERMISSION` = the permission phase 3 put on the payslip detail route (A10)

- [ ] **Step 1: Write the failing domain tests**

`backend/modules/payroll/domain/test_payslip_access.py`:

```python
"""Who may open one payslip: payroll staff, or the employee it belongs to once its run stands."""
from __future__ import annotations

from modules.payroll.domain.payslip_access import may_read_payslip


def _may(**overrides) -> bool:
    arguments = {"payslip_employee_id": "E1", "run_status": "approved", "own_employee_id": "E1",
                 "is_payroll_staff": False, "has_self_service": True}
    arguments.update(overrides)
    return may_read_payslip(**arguments)


def test_payroll_staff_read_any_payslip_at_any_stage():
    assert _may(is_payroll_staff=True, own_employee_id=None, has_self_service=False, run_status="calculated")


def test_an_employee_reads_their_own_approved_or_paid_payslip():
    assert _may() and _may(run_status="paid")


def test_an_employee_never_reads_a_colleagues_payslip():
    assert not _may(payslip_employee_id="E2")


def test_an_employee_does_not_see_a_payslip_that_can_still_change_or_was_reversed():
    assert not _may(run_status="draft")
    assert not _may(run_status="calculated")
    assert not _may(run_status="reversed")


def test_self_service_is_needed_and_an_unlinked_user_owns_nothing():
    assert not _may(has_self_service=False)
    assert not _may(own_employee_id=None)
```

Run: `.venv/Scripts/python -m pytest modules/payroll/domain/test_payslip_access.py -q`
Expected: collection error `No module named 'modules.payroll.domain.payslip_access'`.

- [ ] **Step 2: Write the domain rule**

`backend/modules/payroll/domain/payslip_access.py`:

```python
"""Who may open one payslip: payroll staff, or the employee it belongs to.

An employee sees their payslip once its run is approved or paid. A draft or calculated run can
still change, and a reversed one no longer stands. This mirrors hr/domain/self_service.py, which
applies the same rule to the /me payslip list.
"""
from __future__ import annotations

OWNER_VISIBLE_RUN_STATUSES = frozenset({"approved", "paid"})


def may_read_payslip(*, payslip_employee_id: str, run_status: str, own_employee_id: str | None,
                     is_payroll_staff: bool, has_self_service: bool) -> bool:
    if is_payroll_staff:
        return True
    return (
        has_self_service
        and own_employee_id is not None
        and own_employee_id == payslip_employee_id
        and run_status in OWNER_VISIBLE_RUN_STATUSES
    )
```

Run: `.venv/Scripts/python -m pytest modules/payroll/domain/test_payslip_access.py -q`
Expected: `5 passed`.

- [ ] **Step 3: Write the failing HTTP tests**

`backend/modules/payroll/api/test_payslip_access_integration.py`:

```python
"""A payslip is read by payroll staff or by the employee it belongs to, never by a colleague."""
from __future__ import annotations

import datetime

import pytest
from fastapi import Depends, FastAPI

pytest.importorskip("httpx", reason="the FastAPI test client needs httpx (requirements-dev.txt)")
from fastapi.testclient import TestClient  # noqa: E402
from ulid import ULID  # noqa: E402

from core.tenancy import TenantContext, require_session  # noqa: E402
from modules.payroll.api import payslip_access as access_module  # noqa: E402
from modules.payroll.api import router as payroll_router_module  # noqa: E402

TENANT = "payslip-access-test"


class _Connection:
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
    users = {name: str(ULID()) for name in ("staff", "awa", "moussa", "nobody")}
    for user in users.values():
        db.execute("INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
                   (user, TENANT, f"{user}@test.local"))
    employees = {}
    for name in ("awa", "moussa"):
        employees[name] = str(ULID())
        db.execute(
            "INSERT INTO hr.employees (id, tenant_id, employee_no, first_name, last_name, hire_date, status, user_id) "
            "VALUES (%s, %s, %s, %s, 'Test', %s, 'active', %s)",
            (employees[name], TENANT, f"PA-{name}", name.title(), datetime.date(2025, 1, 6), users[name]),
        )
    payslips = {
        "awa-approved": (employees["awa"], "approved"),
        "awa-calculated": (employees["awa"], "calculated"),
        "moussa-paid": (employees["moussa"], "paid"),
    }
    monkeypatch.setattr(access_module, "payslip_owner",
                        lambda connection, *, tenant_id, payslip_id: payslips.get(payslip_id) if tenant_id == TENANT else None)
    wrapped = _Connection(db)
    monkeypatch.setattr(access_module, "get_connection", lambda: wrapped)
    monkeypatch.setattr(payroll_router_module, "get_connection", lambda: wrapped)
    monkeypatch.setattr("core.tenancy.get_connection", lambda: wrapped)
    acting = {"user": users["nobody"]}
    app = FastAPI()

    @app.get("/probe/payslips/{payslip_id}")
    def probe(payslip_id: str, tenant: TenantContext = Depends(access_module.require_payslip_reader)):
        return {"id": payslip_id}

    app.include_router(payroll_router_module.router)
    app.dependency_overrides[require_session] = lambda: TenantContext(tenant_id=TENANT, user_id=acting["user"], session_token="t")

    def act_as(name: str, *permissions: str) -> None:
        acting["user"] = users[name]
        for permission in permissions:
            db.execute("INSERT INTO core.user_permissions (user_id, permission) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                       (users[name], permission))

    return {"client": TestClient(app), "act_as": act_as}


def test_a_user_with_neither_right_is_forbidden(world):
    world["act_as"]("nobody")
    assert world["client"].get("/probe/payslips/moussa-paid").status_code == 403


def test_payroll_staff_read_any_payslip(world):
    world["act_as"]("staff", access_module.PAYSLIP_STAFF_PERMISSION)
    assert world["client"].get("/probe/payslips/moussa-paid").status_code == 200
    assert world["client"].get("/probe/payslips/awa-calculated").status_code == 200


def test_an_employee_reads_their_own_approved_payslip(world):
    world["act_as"]("awa", "hr.self_service")
    assert world["client"].get("/probe/payslips/awa-approved").json() == {"id": "awa-approved"}


def test_an_employee_never_reads_a_colleagues_payslip(world):
    world["act_as"]("awa", "hr.self_service")
    response = world["client"].get("/probe/payslips/moussa-paid")
    assert response.status_code == 404 and response.json()["detail"]["code"] == "NOT_FOUND"


def test_an_employee_does_not_see_their_payslip_before_approval(world):
    world["act_as"]("awa", "hr.self_service")
    assert world["client"].get("/probe/payslips/awa-calculated").status_code == 404


def test_an_unknown_payslip_is_not_found(world):
    world["act_as"]("staff", access_module.PAYSLIP_STAFF_PERMISSION)
    assert world["client"].get("/probe/payslips/nope").status_code == 404


def test_the_real_payslip_route_refuses_a_colleague(world):
    # Unguarded, awa (no payroll right) would get 403 from require_permission; the guard answers 404.
    world["act_as"]("awa", "hr.self_service")
    assert world["client"].get("/payroll/payslips/moussa-paid").status_code == 404
```

If the contract check found the detail route at a different path (A10), use that path in the last test.

Run: `.venv/Scripts/python -m pytest modules/payroll/api/test_payslip_access_integration.py -q`
Expected: collection error `cannot import name 'payslip_access' from 'modules.payroll.api'`.

- [ ] **Step 4: Write the guard**

`backend/modules/payroll/api/payslip_access.py`. Set `PAYSLIP_STAFF_PERMISSION` to the permission the contract check found on the payslip detail route (A10), and fix the `EmployeeService` import path if A3 found it elsewhere:

```python
"""FastAPI dependency that guards every read of one payslip (detail, lines, print data).

Payroll staff read any payslip. An employee with hr.self_service reads their own payslip once its
run is approved or paid, which is what lets /me link to the existing print route. To everyone
else a payslip does not exist (404), so a guessed id reveals nothing.
"""
from __future__ import annotations

from fastapi import Depends, HTTPException, status

from core.db import get_connection
from core.tenancy import TenantContext, require_session, user_has_permission
from modules.hr.api.service import EmployeeService
from modules.payroll.domain.payslip_access import may_read_payslip

PAYSLIP_STAFF_PERMISSION = "payroll.view_runs"
SELF_SERVICE_PERMISSION = "hr.self_service"
_NOT_FOUND = {"code": "NOT_FOUND", "message": "payslip not found", "message_fr": "bulletin de paie introuvable"}
_FORBIDDEN = {
    "code": "FORBIDDEN",
    "message": f"missing permission: {PAYSLIP_STAFF_PERMISSION}",
    "message_fr": f"permission manquante : {PAYSLIP_STAFF_PERMISSION}",
}


def payslip_owner(connection, *, tenant_id: str, payslip_id: str) -> tuple[str, str] | None:
    """(employee_id, run status) of the payslip, or None when the tenant has no such payslip."""
    return connection.execute(
        """
        SELECT s.employee_id, r.status
        FROM payroll.payslips s
        JOIN payroll.runs r ON r.id = s.run_id AND r.tenant_id = s.tenant_id
        WHERE s.id = %s AND s.tenant_id = %s
        """,
        (payslip_id, tenant_id),
    ).fetchone()


def require_payslip_reader(payslip_id: str, tenant: TenantContext = Depends(require_session)) -> TenantContext:
    with get_connection() as connection:
        staff = user_has_permission(connection, user_id=tenant.user_id, permission=PAYSLIP_STAFF_PERMISSION)
        self_service = not staff and user_has_permission(connection, user_id=tenant.user_id, permission=SELF_SERVICE_PERMISSION)
        if not staff and not self_service:
            raise HTTPException(status.HTTP_403_FORBIDDEN, _FORBIDDEN)
        found = payslip_owner(connection, tenant_id=tenant.tenant_id, payslip_id=payslip_id)
        own = EmployeeService(connection).get_by_user(tenant_id=tenant.tenant_id, user_id=tenant.user_id) if self_service else None
    if found is None or not may_read_payslip(
        payslip_employee_id=found[0],
        run_status=found[1],
        own_employee_id=None if own is None else own["id"],
        is_payroll_staff=staff,
        has_self_service=self_service,
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, _NOT_FOUND)
    return tenant
```

- [ ] **Step 5: Put the guard on payroll's single-payslip reads**

In `backend/modules/payroll/api/router.py`, import the guard:

```python
from modules.payroll.api.payslip_access import require_payslip_reader
```

For **every GET** handler whose path is `/payslips/{payslip_id}` or starts with `/payslips/{payslip_id}/` (detail, lines, print data), replace the permission dependency. For example:

```python
# before (phase 3)
@router.get("/payslips/{payslip_id}")
def payslip(payslip_id: str, tenant: TenantContext = Depends(require_permission("payroll.view_runs"))):
# after
@router.get("/payslips/{payslip_id}")
def payslip(payslip_id: str, tenant: TenantContext = Depends(require_payslip_reader)):
```

The path parameter must be named `payslip_id` so that FastAPI passes it to the guard. If phase 3 named it differently, rename it in that handler and its path. Do not touch routes that list payslips, act on runs, or write anything. Those keep their staff permissions.

- [ ] **Step 6: Check what the print page loads**

Find the print page component: `grep -n "payslips/:id/print" frontend/src/routes/router.tsx`, then open that component. List every API call it makes. Each one must be either a GET under `/payroll/payslips/{payslip_id}…` (guarded now) or an endpoint that needs only a session. If the page also loads the run for its header (for example `/payroll/runs/{runId}`, which lists everyone), do **not** open that endpoint to employees. Instead:
1. Add the header fields the page takes from the run (such as `period`, `run_type`, `run_status`) to the payslip detail response in phase 3's handler, as extra keys.
2. Make the print page read them from the payslip response.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest modules/payroll -q`
Expected: every payroll test passes, including `12` new ones (`5` domain + `7` HTTP), none of the new ones skipped.

- [ ] **Step 8: Commit**

```bash
git add backend/modules/payroll/domain/payslip_access.py backend/modules/payroll/domain/test_payslip_access.py backend/modules/payroll/api/payslip_access.py backend/modules/payroll/api/test_payslip_access_integration.py backend/modules/payroll/api/router.py
git commit -m "feat(payroll): a payslip's owner reads it through the print route; colleagues get 404" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

If Step 6 changed the print page or the detail response, add those files too.

---

### Task 8: HR dashboard screen

**Files:**
- Modify: `frontend/src/features/hr/api.ts` (append)
- Create: `frontend/src/features/hr/format.ts`
- Create: `frontend/src/features/hr/dashboard/KpiTile.tsx`
- Create: `frontend/src/features/hr/dashboard/PayrollCostTable.tsx`
- Create: `frontend/src/features/hr/dashboard/ExpiryTable.tsx`
- Create: `frontend/src/features/hr/dashboard/HrDashboardPage.tsx`
- Modify: `frontend/src/routes/router.tsx`, `frontend/src/routes/Sidebar.tsx`, `frontend/src/lib/i18n.tsx`

**Interfaces:**
- Consumes: `GET /hr/dashboard/summary`, `GET /hr/dashboard/expiring` (Task 4).
- Produces: route `/hr/dashboard`. `format.ts` exports used by Task 9: `formatCount`, `formatFcfa`, `formatDecimal`, `formatDate`, `formatMonth`, `contractTypeLabel`.

- [ ] **Step 1: Add the types and fetchers**

Append to `frontend/src/features/hr/api.ts`:

```ts
// ---- Phase 5: HR dashboard --------------------------------------------------------------

export interface Variance { current: number | null; previous: number | null; delta: number | null; delta_pct: number | null; }
export type OvertimeBand = "day" | "night" | "rest_holiday";
export interface HrMovement { employee_id: string; employee_no: string; full_name: string; department_id: string | null; department_name: string | null; date: string; reason?: string | null; }
export interface HrAbsence { unpaid_absence_days: number; scheduled_days: number; rate: number | null; }
export interface HrPayrollSide { headcount: number; gross: number; employer_cost: number; }
export interface HrPayrollDepartment { department_id: string | null; department_name: string | null; current: HrPayrollSide; previous: HrPayrollSide; variance: { gross: Variance; employer_cost: Variance }; }
export interface HrPayrollCost { departments: HrPayrollDepartment[]; totals: { current: HrPayrollSide; previous: HrPayrollSide; variance: { headcount: Variance; gross: Variance; employer_cost: Variance } }; }
export interface HrDashboardSummary {
  period: string;
  previous_period: string;
  presence_closed: boolean;
  payroll_status: "ok" | "hidden" | "unavailable";
  headcount: {
    as_of: string;
    total: number;
    variance: Variance;
    by_department: { department_id: string | null; department_name: string | null; count: number }[];
    by_contract_type: { contract_type: string; count: number }[];
  };
  movements: { hires: HrMovement[]; exits: HrMovement[]; variance: { hires: Variance; exits: Variance } };
  absence: HrAbsence & { previous: HrAbsence; variance: Variance };
  overtime_minutes: { current: Record<OvertimeBand, number>; previous: Record<OvertimeBand, number>; variance: Record<OvertimeBand, Variance>; total: Variance };
  payroll: HrPayrollCost | null;
}
export interface HrExpiryItem { kind: "contract" | "trial" | "document"; source_id: string; employee_id: string; employee_no: string; employee_name: string; label: string; due_date: string; days_left: number; }
export interface HrExpiring { horizons: { contract_days: number; trial_days: number; document_days: number } | null; items: HrExpiryItem[]; }

// Shares its prefix with HrPage's ["hr", "dashboard"] key, so HR edits there refresh this screen too.
export const HR_DASHBOARD_KEY = ["hr", "dashboard"] as const;
export function getHrDashboardSummary(token: string, period: string) { return apiFetch<HrDashboardSummary>(`/hr/dashboard/summary?period=${period}`, { token }); }
export function getHrExpiring(token: string) { return apiFetch<HrExpiring>("/hr/dashboard/expiring", { token }); }
```

- [ ] **Step 2: Write the formatting helpers**

`frontend/src/features/hr/format.ts`:

```ts
import { currentLocale, type TranslationKey } from "../../lib/i18n";
import type { Variance } from "./api";

function numberFormat(digits: number) {
  return new Intl.NumberFormat(currentLocale(), { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function formatCount(value: number): string {
  return numberFormat(0).format(value);
}

/** Whole francs: XOF has no sub-unit. */
export function formatFcfa(value: number): string {
  return `${numberFormat(0).format(value)} F CFA`;
}

/** Days or hours as recorded, up to one decimal (2.5 days of leave, 40 weekly hours). */
export function formatDecimal(value: number): string {
  return new Intl.NumberFormat(currentLocale(), { maximumFractionDigits: 1 }).format(value);
}

export function formatHours(minutes: number): string {
  return `${numberFormat(1).format(minutes / 60)} h`;
}

/** A 0–1 ratio as a percentage; an em dash when nothing was there to divide by. */
export function formatRate(rate: number | null): string {
  return rate === null ? "—" : `${numberFormat(1).format(rate * 100)} %`;
}

/** The change of a ratio, in percentage points. */
export function formatPoints(delta: number): string {
  return `${numberFormat(1).format(delta * 100)} pt`;
}

export function formatDate(iso: string): string {
  return new Intl.DateTimeFormat(currentLocale(), { dateStyle: "medium" }).format(new Date(`${iso}T00:00:00`));
}

export function formatMonth(iso: string): string {
  return new Intl.DateTimeFormat(currentLocale(), { month: "long", year: "numeric" }).format(new Date(`${iso}T00:00:00`));
}

export function currentPeriod(today: Date = new Date()): string {
  return `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-01`;
}

function withSign(text: string, value: number): string {
  return value > 0 ? `+${text}` : text;
}

/** "+3 (+12.5 %)": the change with its sign, worded the same way for a rise and a fall, since
 * no target makes either one good or bad. Null when one of the two months is missing. */
export function formatVariance(variance: Variance | null, format: (delta: number) => string, withPercent = true): string | null {
  if (!variance || variance.delta === null) return null;
  const main = withSign(format(variance.delta), variance.delta);
  if (!withPercent || variance.delta_pct === null) return main;
  return `${main} (${withSign(`${numberFormat(1).format(variance.delta_pct)} %`, variance.delta_pct)})`;
}

const CONTRACT_TYPES: Record<string, TranslationKey> = {
  cdi: "hr.dashboard.contractType.cdi",
  cdd: "hr.dashboard.contractType.cdd",
  apprentice: "hr.dashboard.contractType.apprentice",
  daily: "hr.dashboard.contractType.daily",
  intern: "hr.dashboard.contractType.intern",
};

/** The spec's contract types get a translated label; any other code is shown as recorded. */
export function contractTypeLabel(t: (key: TranslationKey) => string, code: string): string {
  const key = CONTRACT_TYPES[code];
  return key ? t(key) : code;
}
```

- [ ] **Step 3: Write the KPI tile**

`frontend/src/features/hr/dashboard/KpiTile.tsx`:

```tsx
import { Card } from "../../../components/ui/card";
import { Skeleton } from "../../../components/ui/skeleton";
import { useI18n } from "../../../lib/i18n";
import type { Variance } from "../api";
import { formatVariance } from "../format";

/** One recorded figure and its change against the previous month, in one neutral colour. */
export function KpiTile({
  label,
  value,
  hint,
  variance,
  formatDelta,
  withPercent = true,
  loading,
}: {
  label: string;
  value: string;
  hint?: string;
  variance: Variance | null;
  formatDelta: (delta: number) => string;
  withPercent?: boolean;
  loading: boolean;
}) {
  const { t } = useI18n();
  const change = formatVariance(variance, formatDelta, withPercent);
  return (
    <Card className="space-y-1 p-4">
      <p className="text-xs text-muted-foreground">{label}</p>
      {loading ? (
        <>
          <Skeleton className="h-7 w-24" />
          <Skeleton className="h-3 w-32" />
        </>
      ) : (
        <>
          <p className="text-2xl font-semibold tabular-nums tracking-tight">{value}</p>
          <p className="text-xs tabular-nums text-muted-foreground">
            {change === null ? t("hr.dashboard.noComparison") : `${change} ${t("hr.dashboard.vsPreviousMonth")}`}
          </p>
          {hint && <p className="text-[11px] text-muted-foreground/80">{hint}</p>}
        </>
      )}
    </Card>
  );
}
```

- [ ] **Step 4: Write the payroll cost table**

`frontend/src/features/hr/dashboard/PayrollCostTable.tsx`:

```tsx
import { ColumnFilterRow, type FilterCell } from "../../../components/patterns/ColumnFilterRow";
import { ColumnVisibilityMenu } from "../../../components/patterns/ColumnVisibilityMenu";
import { Button } from "../../../components/ui/button";
import { ResizableTableHead, Table, TableBody, TableCell, TableHeader, TableRow } from "../../../components/ui/table";
import { useI18n } from "../../../lib/i18n";
import { useColumnFilters } from "../../../lib/useColumnFilters";
import { useTableColumns, type ColumnDef } from "../../../lib/useTableColumns";
import type { HrPayrollDepartment } from "../api";
import { formatCount, formatFcfa, formatVariance } from "../format";

const NUMBER_CELL = "text-right tabular-nums";

export function PayrollCostTable({ rows }: { rows: HrPayrollDepartment[] }) {
  const { t } = useI18n();
  const name = (row: HrPayrollDepartment) => row.department_name ?? t("hr.dashboard.noDepartment");
  const filters = useColumnFilters<HrPayrollDepartment>([
    { key: "department", kind: "text", getValue: name },
    { key: "paid", kind: "range", getValue: (row) => row.current.headcount },
    { key: "gross", kind: "range", getValue: (row) => row.current.gross },
    { key: "grossPrevious", kind: "range", getValue: (row) => row.previous.gross },
    { key: "grossChange", kind: "range", getValue: (row) => row.variance.gross.delta },
    { key: "employerCost", kind: "range", getValue: (row) => row.current.employer_cost },
    { key: "employerCostPrevious", kind: "range", getValue: (row) => row.previous.employer_cost },
    { key: "employerCostChange", kind: "range", getValue: (row) => row.variance.employer_cost.delta },
  ]);
  const range = (key: string): FilterCell => ({
    type: "range",
    min: filters.range[key]?.min ?? "",
    max: filters.range[key]?.max ?? "",
    onMinChange: (value) => filters.setRangeValue(key, "min", value),
    onMaxChange: (value) => filters.setRangeValue(key, "max", value),
  });
  const change = (row: HrPayrollDepartment, measure: "gross" | "employer_cost") => formatVariance(row.variance[measure], formatFcfa) ?? "—";
  const columns: ColumnDef<HrPayrollDepartment>[] = [
    {
      key: "department", header: t("hr.dashboard.payroll.department"), cell: name, sortValue: name, defaultWidth: 200,
      filterCell: { type: "text", placeholder: t("common.filter"), value: filters.text.department ?? "", onChange: (value) => filters.setTextValue("department", value) },
    },
    { key: "paid", header: t("hr.dashboard.payroll.paid"), cell: (row) => formatCount(row.current.headcount), sortValue: (row) => row.current.headcount, defaultWidth: 130, cellClassName: NUMBER_CELL, filterCell: range("paid") },
    { key: "gross", header: t("hr.dashboard.payroll.gross"), cell: (row) => formatFcfa(row.current.gross), sortValue: (row) => row.current.gross, cellClassName: NUMBER_CELL, filterCell: range("gross") },
    { key: "grossPrevious", header: t("hr.dashboard.payroll.grossPrevious"), cell: (row) => formatFcfa(row.previous.gross), sortValue: (row) => row.previous.gross, cellClassName: NUMBER_CELL, filterCell: range("grossPrevious") },
    { key: "grossChange", header: t("hr.dashboard.payroll.grossChange"), cell: (row) => change(row, "gross"), sortValue: (row) => row.variance.gross.delta, defaultWidth: 200, cellClassName: NUMBER_CELL, filterCell: range("grossChange") },
    { key: "employerCost", header: t("hr.dashboard.payroll.employerCost"), cell: (row) => formatFcfa(row.current.employer_cost), sortValue: (row) => row.current.employer_cost, cellClassName: NUMBER_CELL, filterCell: range("employerCost") },
    { key: "employerCostPrevious", header: t("hr.dashboard.payroll.employerCostPrevious"), cell: (row) => formatFcfa(row.previous.employer_cost), sortValue: (row) => row.previous.employer_cost, cellClassName: NUMBER_CELL, filterCell: range("employerCostPrevious") },
    { key: "employerCostChange", header: t("hr.dashboard.payroll.employerCostChange"), cell: (row) => change(row, "employer_cost"), sortValue: (row) => row.variance.employer_cost.delta, defaultWidth: 200, cellClassName: NUMBER_CELL, filterCell: range("employerCostChange") },
  ];
  const { visibleColumns, colWidths, isVisible, toggleVisible, getWidth, setWidth, resetAll, sortDirectionFor, toggleSort, sortRows } =
    useTableColumns("hr.dashboard.payrollByDepartment", columns);
  const shown = sortRows(filters.apply(rows));
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-end gap-2">
        {filters.isActive && (
          <Button variant="ghost" size="sm" onClick={filters.reset}>
            {t("common.clearFilters")}
          </Button>
        )}
        <ColumnVisibilityMenu columns={columns} isVisible={isVisible} onToggle={toggleVisible} onReset={resetAll} />
      </div>
      <Table colWidths={colWidths}>
        <TableHeader>
          <TableRow>
            {visibleColumns.map((column) => (
              <ResizableTableHead
                key={column.key}
                width={getWidth(column.key)}
                onResize={(width) => setWidth(column.key, width)}
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
          {shown.map((row) => (
            <TableRow key={row.department_id ?? "none"}>
              {visibleColumns.map((column) => (
                <TableCell key={column.key} className={column.cellClassName}>
                  {column.cell(row)}
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
```

- [ ] **Step 5: Write the expiry table**

`frontend/src/features/hr/dashboard/ExpiryTable.tsx`:

```tsx
import { useState } from "react";
import { ColumnFilterRow } from "../../../components/patterns/ColumnFilterRow";
import { ColumnVisibilityMenu } from "../../../components/patterns/ColumnVisibilityMenu";
import { FilterTabs } from "../../../components/patterns/FilterTabs";
import { Badge } from "../../../components/ui/badge";
import { Button } from "../../../components/ui/button";
import { ResizableTableHead, Table, TableBody, TableCell, TableHeader, TableRow } from "../../../components/ui/table";
import { useI18n, type TranslationKey } from "../../../lib/i18n";
import { useColumnFilters } from "../../../lib/useColumnFilters";
import { useTableColumns, type ColumnDef } from "../../../lib/useTableColumns";
import type { HrExpiryItem } from "../api";
import { contractTypeLabel, formatCount, formatDate } from "../format";

type KindFilter = "all" | HrExpiryItem["kind"];
const KIND_LABEL: Record<HrExpiryItem["kind"], TranslationKey> = {
  contract: "hr.dashboard.expiry.kind.contract",
  trial: "hr.dashboard.expiry.kind.trial",
  document: "hr.dashboard.expiry.kind.document",
};

export function ExpiryTable({ items }: { items: HrExpiryItem[] }) {
  const { t } = useI18n();
  const [kind, setKind] = useState<KindFilter>("all");
  const itemLabel = (item: HrExpiryItem) => (item.kind === "document" ? item.label : contractTypeLabel(t, item.label));
  const filters = useColumnFilters<HrExpiryItem>([
    { key: "employee", kind: "text", getValue: (item) => `${item.employee_no} ${item.employee_name}` },
    { key: "item", kind: "text", getValue: itemLabel },
    { key: "daysLeft", kind: "range", getValue: (item) => item.days_left },
  ]);
  const columns: ColumnDef<HrExpiryItem>[] = [
    { key: "kind", header: t("hr.dashboard.expiry.kind"), cell: (item) => t(KIND_LABEL[item.kind]), sortValue: (item) => item.kind, defaultWidth: 160, filterCell: { type: "blank" } },
    {
      key: "employee", header: t("hr.dashboard.expiry.employee"), defaultWidth: 220, sortValue: (item) => item.employee_name,
      cell: (item) => (
        <span>
          {item.employee_name}
          <span className="ml-1 text-xs text-muted-foreground">{item.employee_no}</span>
        </span>
      ),
      filterCell: { type: "text", placeholder: t("common.filter"), value: filters.text.employee ?? "", onChange: (value) => filters.setTextValue("employee", value) },
    },
    {
      key: "item", header: t("hr.dashboard.expiry.item"), cell: itemLabel, sortValue: itemLabel, defaultWidth: 180,
      filterCell: { type: "text", placeholder: t("common.filter"), value: filters.text.item ?? "", onChange: (value) => filters.setTextValue("item", value) },
    },
    { key: "dueDate", header: t("hr.dashboard.expiry.dueDate"), cell: (item) => formatDate(item.due_date), sortValue: (item) => item.due_date, defaultWidth: 140, filterCell: { type: "blank" } },
    {
      key: "daysLeft", header: t("hr.dashboard.expiry.daysLeft"), defaultWidth: 170, cellClassName: "tabular-nums", sortValue: (item) => item.days_left,
      // "Past due" is a fact (the date has passed), not a threshold.
      cell: (item) =>
        item.days_left < 0 ? (
          <Badge variant="destructive">{`${t("hr.dashboard.expiry.overdue")} (${formatCount(-item.days_left)} ${t("hr.dashboard.days")})`}</Badge>
        ) : (
          formatCount(item.days_left)
        ),
      filterCell: {
        type: "range",
        min: filters.range.daysLeft?.min ?? "",
        max: filters.range.daysLeft?.max ?? "",
        onMinChange: (value) => filters.setRangeValue("daysLeft", "min", value),
        onMaxChange: (value) => filters.setRangeValue("daysLeft", "max", value),
      },
    },
  ];
  const { visibleColumns, colWidths, isVisible, toggleVisible, getWidth, setWidth, resetAll, sortDirectionFor, toggleSort, sortRows } =
    useTableColumns("hr.dashboard.expiry", columns);
  const shown = sortRows(filters.apply(items.filter((item) => kind === "all" || item.kind === kind)));
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <FilterTabs
          value={kind}
          onChange={setKind}
          options={[
            { value: "all", label: t("common.all") },
            { value: "contract", label: t(KIND_LABEL.contract) },
            { value: "trial", label: t(KIND_LABEL.trial) },
            { value: "document", label: t(KIND_LABEL.document) },
          ]}
        />
        <div className="flex items-center gap-2">
          {filters.isActive && (
            <Button variant="ghost" size="sm" onClick={filters.reset}>
              {t("common.clearFilters")}
            </Button>
          )}
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
          {shown.map((item) => (
            <TableRow key={`${item.kind}-${item.source_id}`}>
              {visibleColumns.map((column) => (
                <TableCell key={column.key} className={column.cellClassName}>
                  {column.cell(item)}
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
```

- [ ] **Step 6: Write the page**

`frontend/src/features/hr/dashboard/HrDashboardPage.tsx`:

```tsx
import { useState } from "react";
import { keepPreviousData, useQuery, type UseQueryResult } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";
import { Bar, BarChart, CartesianGrid, Tooltip, XAxis, YAxis } from "recharts";
import { InteractiveChart } from "../../../components/charts/InteractiveChart";
import { AppLoader } from "../../../components/patterns/AppLoader";
import { EmptyState } from "../../../components/patterns/EmptyState";
import { Button } from "../../../components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../../components/ui/card";
import { Input } from "../../../components/ui/input";
import { Skeleton } from "../../../components/ui/skeleton";
import { ApiError } from "../../../lib/api";
import { useAuth } from "../../../lib/auth";
import { useI18n, type TranslationKey } from "../../../lib/i18n";
import { getHrDashboardSummary, getHrExpiring, HR_DASHBOARD_KEY, type HrDashboardSummary, type HrExpiring, type OvertimeBand } from "../api";
import { contractTypeLabel, currentPeriod, formatCount, formatDate, formatFcfa, formatHours, formatMonth, formatPoints, formatRate } from "../format";
import { ExpiryTable } from "./ExpiryTable";
import { KpiTile } from "./KpiTile";
import { PayrollCostTable } from "./PayrollCostTable";

const BAR = "hsl(217 91% 45%)";
const BAR_PREVIOUS = "hsl(215 16% 70%)";
const GRID = "hsl(214 20% 92%)";
const TICK = { fontSize: 12, fill: "hsl(215 16% 47%)" };
const BANDS: OvertimeBand[] = ["day", "night", "rest_holiday"];
const BAND_LABEL: Record<OvertimeBand, TranslationKey> = {
  day: "hr.dashboard.band.day",
  night: "hr.dashboard.band.night",
  rest_holiday: "hr.dashboard.band.rest_holiday",
};
const MOVEMENT_TITLE: Record<"hires" | "exits", TranslationKey> = {
  hires: "hr.dashboard.movements.hires",
  exits: "hr.dashboard.movements.exits",
};

type BlockProps = { data: HrDashboardSummary; loading: boolean };

function Empty({ text }: { text: string }) {
  return <p className="py-8 text-center text-sm text-muted-foreground">{text}</p>;
}

export function HrDashboardPage() {
  const { t } = useI18n();
  const { session } = useAuth();
  const token = session!.token;
  const [period, setPeriod] = useState(currentPeriod());
  const summary = useQuery({
    queryKey: [...HR_DASHBOARD_KEY, "summary", period],
    queryFn: () => getHrDashboardSummary(token, period),
    placeholderData: keepPreviousData,
  });
  const expiring = useQuery({ queryKey: [...HR_DASHBOARD_KEY, "expiring"], queryFn: () => getHrExpiring(token) });

  // One branded loader for the screen, on the first load only. Changing month keeps every block
  // mounted and puts Skeletons in place of the figures until the new month arrives.
  if (summary.isPending) return <AppLoader label={t("hr.dashboard.loading")} fullScreen />;
  const data = summary.data;
  if (!data) {
    return (
      <EmptyState
        icon={<AlertTriangle className="h-6 w-6" />}
        title={t("hr.dashboard.error")}
        description={summary.error instanceof ApiError ? summary.error.message : ""}
        action={<Button variant="outline" onClick={() => summary.refetch()}>{t("hr.dashboard.retry")}</Button>}
      />
    );
  }
  const loading = summary.isPlaceholderData;

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">{t("hr.dashboard.title")}</h1>
          <p className="text-sm text-muted-foreground">{t("hr.dashboard.subtitle")}</p>
        </div>
        <label className="flex items-center gap-2 text-sm">
          <span className="text-muted-foreground">{t("hr.dashboard.month")}</span>
          <Input
            type="month"
            className="w-44"
            max={currentPeriod().slice(0, 7)}
            value={period.slice(0, 7)}
            onChange={(event) => event.target.value && setPeriod(`${event.target.value}-01`)}
          />
        </label>
      </header>

      {!data.presence_closed && (
        <p className="rounded-md border border-border bg-muted/40 px-3 py-2 text-xs text-muted-foreground">{t("hr.dashboard.presenceOpen")}</p>
      )}

      <KpiRow data={data} loading={loading} />
      <div className="grid gap-4 lg:grid-cols-2">
        <HeadcountByDepartment data={data} loading={loading} />
        <HeadcountByContractType data={data} loading={loading} />
        <OvertimeByBand data={data} loading={loading} />
        <Movements data={data} loading={loading} />
      </div>
      <PayrollBlock data={data} loading={loading} />
      <ExpiryBlock query={expiring} />
    </div>
  );
}

function KpiRow({ data, loading }: BlockProps) {
  const { t } = useI18n();
  const payroll = data.payroll_status === "ok" ? data.payroll : null;
  const overtimeTotal = BANDS.reduce((sum, band) => sum + data.overtime_minutes.current[band], 0);
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-7">
      <KpiTile
        label={t("hr.dashboard.kpi.headcount")}
        value={formatCount(data.headcount.total)}
        hint={`${t("hr.dashboard.kpi.headcountHint")} ${formatDate(data.headcount.as_of)}`}
        variance={data.headcount.variance}
        formatDelta={formatCount}
        loading={loading}
      />
      <KpiTile label={t("hr.dashboard.kpi.hires")} value={formatCount(data.movements.hires.length)} variance={data.movements.variance.hires} formatDelta={formatCount} loading={loading} />
      <KpiTile label={t("hr.dashboard.kpi.exits")} value={formatCount(data.movements.exits.length)} variance={data.movements.variance.exits} formatDelta={formatCount} loading={loading} />
      <KpiTile
        label={t("hr.dashboard.kpi.absenceRate")}
        value={formatRate(data.absence.rate)}
        hint={`${formatCount(data.absence.unpaid_absence_days)} / ${formatCount(data.absence.scheduled_days)} ${t("hr.dashboard.kpi.absenceHint")}`}
        variance={data.absence.variance}
        formatDelta={formatPoints}
        withPercent={false}
        loading={loading}
      />
      <KpiTile label={t("hr.dashboard.kpi.overtime")} value={formatHours(overtimeTotal)} variance={data.overtime_minutes.total} formatDelta={formatHours} loading={loading} />
      {payroll && (
        <KpiTile label={t("hr.dashboard.kpi.gross")} value={formatFcfa(payroll.totals.current.gross)} variance={payroll.totals.variance.gross} formatDelta={formatFcfa} loading={loading} />
      )}
      {payroll && (
        <KpiTile label={t("hr.dashboard.kpi.employerCost")} value={formatFcfa(payroll.totals.current.employer_cost)} variance={payroll.totals.variance.employer_cost} formatDelta={formatFcfa} loading={loading} />
      )}
    </div>
  );
}

function HeadcountByDepartment({ data, loading }: BlockProps) {
  const { t } = useI18n();
  const rows = data.headcount.by_department.map((row) => ({ department: row.department_name ?? t("hr.dashboard.noDepartment"), count: row.count }));
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("hr.dashboard.byDepartment.title")}</CardTitle>
        <CardDescription>{`${t("hr.dashboard.kpi.headcountHint")} ${formatDate(data.headcount.as_of)}`}</CardDescription>
      </CardHeader>
      <CardContent>
        {loading ? (
          <Skeleton className="h-64 w-full" />
        ) : rows.length === 0 ? (
          <Empty text={t("hr.dashboard.empty")} />
        ) : (
          <div className="w-full" style={{ height: Math.max(160, rows.length * 36) }}>
            <InteractiveChart height="100%" allowViewSwitch={false} legend={false}>
              <BarChart data={rows} layout="vertical" margin={{ top: 4, right: 16, left: 8, bottom: 4 }}>
                <CartesianGrid stroke={GRID} horizontal={false} />
                <XAxis type="number" allowDecimals={false} tick={TICK} tickLine={false} axisLine={false} />
                <YAxis type="category" dataKey="department" tick={TICK} tickLine={false} axisLine={false} width={140} />
                <Tooltip formatter={(value) => formatCount(Number(value))} />
                <Bar dataKey="count" name={t("hr.dashboard.kpi.headcount")} fill={BAR} radius={[0, 4, 4, 0]} />
              </BarChart>
            </InteractiveChart>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function HeadcountByContractType({ data, loading }: BlockProps) {
  const { t } = useI18n();
  const total = data.headcount.total;
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("hr.dashboard.byContractType.title")}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {loading ? (
          <Skeleton className="h-40 w-full" />
        ) : data.headcount.by_contract_type.length === 0 ? (
          <Empty text={t("hr.dashboard.empty")} />
        ) : (
          data.headcount.by_contract_type.map((row) => (
            <div key={row.contract_type} className="space-y-1">
              <div className="flex justify-between text-sm">
                <span>{contractTypeLabel(t, row.contract_type)}</span>
                <span className="tabular-nums">{formatCount(row.count)}</span>
              </div>
              <div className="h-2 rounded-full bg-muted">
                <div className="h-2 rounded-full" style={{ width: `${(row.count / total) * 100}%`, background: BAR }} />
              </div>
            </div>
          ))
        )}
      </CardContent>
    </Card>
  );
}

function OvertimeByBand({ data, loading }: BlockProps) {
  const { t } = useI18n();
  const rows = BANDS.map((band) => ({
    band: t(BAND_LABEL[band]),
    previous: data.overtime_minutes.previous[band] / 60,
    current: data.overtime_minutes.current[band] / 60,
  }));
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("hr.dashboard.overtime.title")}</CardTitle>
        <CardDescription>{formatMonth(data.period)}</CardDescription>
      </CardHeader>
      <CardContent>
        {loading ? (
          <Skeleton className="h-64 w-full" />
        ) : (
          <div className="h-64 w-full">
            <InteractiveChart height="100%" allowViewSwitch={false}>
              <BarChart data={rows} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                <CartesianGrid stroke={GRID} vertical={false} />
                <XAxis dataKey="band" tick={TICK} tickLine={false} axisLine={false} />
                <YAxis tick={TICK} tickLine={false} axisLine={false} width={48} unit=" h" />
                <Tooltip formatter={(value) => formatHours(Number(value) * 60)} />
                <Bar dataKey="previous" name={t("hr.dashboard.overtime.previous")} fill={BAR_PREVIOUS} radius={[4, 4, 0, 0]} />
                <Bar dataKey="current" name={t("hr.dashboard.overtime.current")} fill={BAR} radius={[4, 4, 0, 0]} />
              </BarChart>
            </InteractiveChart>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function Movements({ data, loading }: BlockProps) {
  const { t } = useI18n();
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("hr.dashboard.movements.title")}</CardTitle>
        <CardDescription>{formatMonth(data.period)}</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4 sm:grid-cols-2">
        {(["hires", "exits"] as const).map((kind) => (
          <div key={kind}>
            <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">{t(MOVEMENT_TITLE[kind])}</p>
            {loading ? (
              <Skeleton className="h-24 w-full" />
            ) : data.movements[kind].length === 0 ? (
              <p className="text-sm text-muted-foreground">{t("hr.dashboard.movements.none")}</p>
            ) : (
              <ul className="space-y-1.5 text-sm">
                {data.movements[kind].map((row) => (
                  <li key={row.employee_id} className="flex justify-between gap-2">
                    <span className="truncate">
                      {row.full_name}
                      <span className="ml-1 text-xs text-muted-foreground">
                        {row.department_name ?? t("hr.dashboard.noDepartment")}
                        {row.reason ? ` · ${row.reason}` : ""}
                      </span>
                    </span>
                    <span className="shrink-0 tabular-nums text-muted-foreground">{formatDate(row.date)}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

function PayrollBlock({ data, loading }: BlockProps) {
  const { t } = useI18n();
  let body;
  if (data.payroll_status === "hidden") body = <Empty text={t("hr.dashboard.payroll.hidden")} />;
  else if (data.payroll_status === "unavailable" || !data.payroll) body = <Empty text={t("hr.dashboard.payroll.unavailable")} />;
  else if (loading) body = <Skeleton className="h-48 w-full" />;
  else if (data.payroll.departments.length === 0) body = <Empty text={t("hr.dashboard.payroll.empty")} />;
  else body = <PayrollCostTable rows={data.payroll.departments} />;
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("hr.dashboard.payroll.title")}</CardTitle>
        <CardDescription>{`${formatMonth(data.period)} · ${t("hr.dashboard.vsPreviousMonth")} (${formatMonth(data.previous_period)})`}</CardDescription>
      </CardHeader>
      <CardContent>{body}</CardContent>
    </Card>
  );
}

function ExpiryBlock({ query }: { query: UseQueryResult<HrExpiring> }) {
  const { t } = useI18n();
  let body;
  if (query.isPending) {
    body = (
      <div className="space-y-2">
        {[0, 1, 2].map((row) => (
          <Skeleton key={row} className="h-8 w-full" />
        ))}
      </div>
    );
  } else if (query.isError) {
    body = <p className="text-sm text-destructive">{query.error instanceof ApiError ? query.error.message : t("hr.dashboard.error")}</p>;
  } else if (query.data.horizons === null) {
    body = <Empty text={t("hr.dashboard.expiry.noHorizons")} />;
  } else if (query.data.items.length === 0) {
    body = <Empty text={t("hr.dashboard.expiry.empty")} />;
  } else {
    body = <ExpiryTable items={query.data.items} />;
  }
  const horizons = query.data?.horizons;
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("hr.dashboard.expiry.title")}</CardTitle>
        {horizons && (
          <CardDescription>{`${t("hr.dashboard.expiry.horizons")} ${horizons.contract_days} / ${horizons.trial_days} / ${horizons.document_days}`}</CardDescription>
        )}
      </CardHeader>
      <CardContent>{body}</CardContent>
    </Card>
  );
}
```

- [ ] **Step 7: Add the strings (both languages)**

In `frontend/src/lib/i18n.tsx`, add to the `en` dictionary next to `"nav.hr"`:

```ts
  "nav.hrDashboard": "HR dashboard",
```

and next to the other `hr.*` keys:

```ts
  "hr.dashboard.title": "HR dashboard",
  "hr.dashboard.subtitle": "What was recorded for the month, against the month before.",
  "hr.dashboard.month": "Month",
  "hr.dashboard.loading": "Loading the HR dashboard",
  "hr.dashboard.error": "The HR dashboard could not be loaded",
  "hr.dashboard.retry": "Try again",
  "hr.dashboard.vsPreviousMonth": "vs previous month",
  "hr.dashboard.noComparison": "No previous month to compare",
  "hr.dashboard.empty": "Nothing recorded for this month.",
  "hr.dashboard.noDepartment": "No department",
  "hr.dashboard.days": "days",
  "hr.dashboard.presenceOpen": "Presence for this month is not closed yet: absence and overtime can still change.",
  "hr.dashboard.kpi.headcount": "Headcount",
  "hr.dashboard.kpi.headcountHint": "Employees under contract on",
  "hr.dashboard.kpi.hires": "Hires",
  "hr.dashboard.kpi.exits": "Exits",
  "hr.dashboard.kpi.absenceRate": "Unpaid absence rate",
  "hr.dashboard.kpi.absenceHint": "unpaid absence days / scheduled days",
  "hr.dashboard.kpi.overtime": "Overtime hours",
  "hr.dashboard.kpi.gross": "Gross payroll",
  "hr.dashboard.kpi.employerCost": "Employer cost",
  "hr.dashboard.byDepartment.title": "Headcount by department",
  "hr.dashboard.byContractType.title": "Headcount by contract type",
  "hr.dashboard.overtime.title": "Overtime hours by band",
  "hr.dashboard.overtime.current": "This month",
  "hr.dashboard.overtime.previous": "Previous month",
  "hr.dashboard.band.day": "Day",
  "hr.dashboard.band.night": "Night",
  "hr.dashboard.band.rest_holiday": "Rest day / holiday",
  "hr.dashboard.movements.title": "Hires and exits",
  "hr.dashboard.movements.hires": "Hires",
  "hr.dashboard.movements.exits": "Exits",
  "hr.dashboard.movements.none": "None this month",
  "hr.dashboard.payroll.title": "Payroll cost by department",
  "hr.dashboard.payroll.hidden": "Payroll amounts need the permission to see pay (hr.view_sensitive).",
  "hr.dashboard.payroll.unavailable": "The payroll module is not installed.",
  "hr.dashboard.payroll.empty": "No payslips for this month yet.",
  "hr.dashboard.payroll.department": "Department",
  "hr.dashboard.payroll.paid": "Paid employees",
  "hr.dashboard.payroll.gross": "Gross",
  "hr.dashboard.payroll.grossPrevious": "Gross, previous month",
  "hr.dashboard.payroll.grossChange": "Gross change",
  "hr.dashboard.payroll.employerCost": "Employer cost",
  "hr.dashboard.payroll.employerCostPrevious": "Employer cost, previous month",
  "hr.dashboard.payroll.employerCostChange": "Employer cost change",
  "hr.dashboard.expiry.title": "Contracts, trials and documents falling due",
  "hr.dashboard.expiry.noHorizons": "Set the alert horizons in the HR settings to list what falls due.",
  "hr.dashboard.expiry.horizons": "Horizons in days (contracts / trials / documents):",
  "hr.dashboard.expiry.empty": "Nothing falls due within the horizons.",
  "hr.dashboard.expiry.kind": "Kind",
  "hr.dashboard.expiry.kind.contract": "Contract end",
  "hr.dashboard.expiry.kind.trial": "Trial end",
  "hr.dashboard.expiry.kind.document": "Document expiry",
  "hr.dashboard.expiry.employee": "Employee",
  "hr.dashboard.expiry.item": "Item",
  "hr.dashboard.expiry.dueDate": "Due date",
  "hr.dashboard.expiry.daysLeft": "Days left",
  "hr.dashboard.expiry.overdue": "Past due",
  "hr.dashboard.contractType.cdi": "Permanent (CDI)",
  "hr.dashboard.contractType.cdd": "Fixed-term (CDD)",
  "hr.dashboard.contractType.apprentice": "Apprentice",
  "hr.dashboard.contractType.daily": "Daily worker",
  "hr.dashboard.contractType.intern": "Intern",
```

and the same keys to the `fr` dictionary:

```ts
  "nav.hrDashboard": "Tableau de bord RH",
```

```ts
  "hr.dashboard.title": "Tableau de bord RH",
  "hr.dashboard.subtitle": "Ce qui a été enregistré sur le mois, comparé au mois précédent.",
  "hr.dashboard.month": "Mois",
  "hr.dashboard.loading": "Chargement du tableau de bord RH",
  "hr.dashboard.error": "Le tableau de bord RH n'a pas pu être chargé",
  "hr.dashboard.retry": "Réessayer",
  "hr.dashboard.vsPreviousMonth": "vs mois précédent",
  "hr.dashboard.noComparison": "Pas de mois précédent à comparer",
  "hr.dashboard.empty": "Rien d'enregistré pour ce mois.",
  "hr.dashboard.noDepartment": "Sans département",
  "hr.dashboard.days": "jours",
  "hr.dashboard.presenceOpen": "La présence de ce mois n'est pas encore clôturée : absences et heures supplémentaires peuvent encore changer.",
  "hr.dashboard.kpi.headcount": "Effectif",
  "hr.dashboard.kpi.headcountHint": "Salariés sous contrat au",
  "hr.dashboard.kpi.hires": "Embauches",
  "hr.dashboard.kpi.exits": "Départs",
  "hr.dashboard.kpi.absenceRate": "Taux d'absence non payée",
  "hr.dashboard.kpi.absenceHint": "jours d'absence non payée / jours planifiés",
  "hr.dashboard.kpi.overtime": "Heures supplémentaires",
  "hr.dashboard.kpi.gross": "Masse salariale brute",
  "hr.dashboard.kpi.employerCost": "Coût employeur",
  "hr.dashboard.byDepartment.title": "Effectif par département",
  "hr.dashboard.byContractType.title": "Effectif par type de contrat",
  "hr.dashboard.overtime.title": "Heures supplémentaires par tranche",
  "hr.dashboard.overtime.current": "Ce mois",
  "hr.dashboard.overtime.previous": "Mois précédent",
  "hr.dashboard.band.day": "Jour",
  "hr.dashboard.band.night": "Nuit",
  "hr.dashboard.band.rest_holiday": "Repos / jour férié",
  "hr.dashboard.movements.title": "Embauches et départs",
  "hr.dashboard.movements.hires": "Embauches",
  "hr.dashboard.movements.exits": "Départs",
  "hr.dashboard.movements.none": "Aucun ce mois-ci",
  "hr.dashboard.payroll.title": "Coût de la paie par département",
  "hr.dashboard.payroll.hidden": "Les montants de paie demandent la permission de voir les salaires (hr.view_sensitive).",
  "hr.dashboard.payroll.unavailable": "Le module de paie n'est pas installé.",
  "hr.dashboard.payroll.empty": "Aucun bulletin pour ce mois pour l'instant.",
  "hr.dashboard.payroll.department": "Département",
  "hr.dashboard.payroll.paid": "Salariés payés",
  "hr.dashboard.payroll.gross": "Brut",
  "hr.dashboard.payroll.grossPrevious": "Brut, mois précédent",
  "hr.dashboard.payroll.grossChange": "Écart brut",
  "hr.dashboard.payroll.employerCost": "Coût employeur",
  "hr.dashboard.payroll.employerCostPrevious": "Coût employeur, mois précédent",
  "hr.dashboard.payroll.employerCostChange": "Écart coût employeur",
  "hr.dashboard.expiry.title": "Contrats, périodes d'essai et documents à échéance",
  "hr.dashboard.expiry.noHorizons": "Définissez les horizons d'alerte dans les paramètres RH pour lister les échéances.",
  "hr.dashboard.expiry.horizons": "Horizons en jours (contrats / essais / documents) :",
  "hr.dashboard.expiry.empty": "Aucune échéance dans les horizons.",
  "hr.dashboard.expiry.kind": "Nature",
  "hr.dashboard.expiry.kind.contract": "Fin de contrat",
  "hr.dashboard.expiry.kind.trial": "Fin d'essai",
  "hr.dashboard.expiry.kind.document": "Expiration de document",
  "hr.dashboard.expiry.employee": "Employé",
  "hr.dashboard.expiry.item": "Élément",
  "hr.dashboard.expiry.dueDate": "Échéance",
  "hr.dashboard.expiry.daysLeft": "Jours restants",
  "hr.dashboard.expiry.overdue": "Échue",
  "hr.dashboard.contractType.cdi": "CDI",
  "hr.dashboard.contractType.cdd": "CDD",
  "hr.dashboard.contractType.apprentice": "Apprenti",
  "hr.dashboard.contractType.daily": "Journalier",
  "hr.dashboard.contractType.intern": "Stagiaire",
```

- [ ] **Step 8: Route and nav entry**

In `frontend/src/routes/router.tsx`, add the import and the lazy page next to `CrmDashboardPage`, since Recharts stays out of the main chunk:

```tsx
import { AppLoader } from "../components/patterns/AppLoader";

const HrDashboardPage = lazy(() =>
  import("../features/hr/dashboard/HrDashboardPage").then((m) => ({ default: m.HrDashboardPage })),
);
```

and the route in `protectedChildren`, next to `{ path: "/hr", … }`:

```tsx
  {
    path: "/hr/dashboard",
    element: (
      // The same loader the page shows while its data loads, so chunk and data read as one wait.
      <Suspense fallback={<AppLoader fullScreen />}>
        <HrDashboardPage />
      </Suspense>
    ),
  },
```

In `frontend/src/routes/Sidebar.tsx`, add to the HR group's `items`. `LayoutDashboard` is already imported. If the `/hr` item lacks `exact: true`, add it so it does not light up on `/hr/dashboard`:

```ts
      { to: "/hr/dashboard", labelKey: "nav.hrDashboard", icon: LayoutDashboard, permission: "hr.view_dashboard" },
```

- [ ] **Step 9: Type-check**

Run (from `frontend/`): `npx tsc -b --force`
Expected: exits 0 with no output. A missing `fr` key or a wrong prop fails here.

- [ ] **Step 10: Browser check**

Start the API (from `backend/`: `.venv/Scripts/python -m uvicorn app.main:app`) and the SPA (from `frontend/`: `npm run dev`). Log in as `demo@sonalim-erp.local` / `demo1234` in a private headless browser (the working tree is shared) and open `/hr/dashboard`. Expected:
- one loader, then KPI tiles, charts, movements, the payroll block and the expiry block;
- changing the month shows Skeletons without a second loader;
- the payroll block says `hr.view_sensitive` is needed until Task 10 grants it;
- `fr` shows every string translated;
- a phone-width viewport has no horizontal scroll.

- [ ] **Step 11: Commit**

```bash
git add frontend/src/features/hr/api.ts frontend/src/features/hr/format.ts frontend/src/features/hr/dashboard frontend/src/routes/router.tsx frontend/src/routes/Sidebar.tsx frontend/src/lib/i18n.tsx
git commit -m "feat(hr): HR dashboard screen (headcount, movements, absence, overtime, payroll cost, expiries)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: `/me` self-service screen

**Files:**
- Modify: `frontend/src/features/hr/api.ts` (append)
- Create: `frontend/src/features/hr/me/MyPage.tsx`, `MyFileTab.tsx`, `MyPayslipsTab.tsx`, `MyLeaveTab.tsx`
- Modify: `frontend/src/routes/router.tsx`, `frontend/src/routes/Sidebar.tsx`, `frontend/src/lib/i18n.tsx`

**Interfaces:**
- Consumes: `/hr/me/*` (Task 6); `format.ts` (Task 8); the print route `/payroll/payslips/:id/print` (phase 3, opened to owners by Task 7).
- Produces: route `/me` (tabs `?tab=file|payslips|leave`).

- [ ] **Step 1: Add the types and fetchers**

Append to `frontend/src/features/hr/api.ts`:

```ts
// ---- Phase 5: self-service (/me) --------------------------------------------------------

export interface MyContract { contract_type: string; start_date: string; end_date: string | null; weekly_hours: number | null; pay_frequency: string | null; }
export interface MyFile {
  employee_no: string; first_name: string; last_name: string; birth_date: string | null; birth_place: string | null;
  nationality: string | null; national_id: string | null; inps_no: string | null; amo_no: string | null;
  marital_status: string | null; email: string | null; phone: string | null; address: string | null;
  emergency_contact: string | null; badge_no: string | null; site: string | null; job_title: string | null;
  hire_date: string | null; department_name: string | null; position_title: string | null; contract: MyContract | null;
}
export interface MyPayslip { id: string; period: string; run_type: string | null; run_status: "approved" | "paid"; gross: number; net: number; }
export interface MyLeaveBalance { leave_type_id: string; code: string; name: string; paid: boolean; accrued: number; taken: number; adjusted: number; available: number | null; pending: number; }
export interface MyLeaveRequest { id: string; leave_type_id: string | null; leave_type_name: string | null; start_date: string; end_date: string; days: number | null; half_day: boolean | null; status: "pending" | "approved" | "rejected" | "cancelled"; reason: string | null; }
export interface MyLeave { year: number; balances: MyLeaveBalance[]; requests: MyLeaveRequest[]; }
export interface MyLeaveRequestInput { leave_type_id: string; start_date: string; end_date: string; half_day: boolean; reason: string | null; }

export const ME_KEYS = { file: ["hr", "me", "file"], payslips: ["hr", "me", "payslips"], leave: ["hr", "me", "leave"] } as const;
export function getMyFile(token: string) { return apiFetch<MyFile>("/hr/me/file", { token }); }
export function getMyPayslips(token: string) { return apiFetch<MyPayslip[]>("/hr/me/payslips", { token }); }
export function getMyLeave(token: string) { return apiFetch<MyLeave>("/hr/me/leave", { token }); }
export function createMyLeaveRequest(token: string, input: MyLeaveRequestInput) { return apiFetch<{ id: string }>("/hr/me/leave-requests", { method: "POST", token, body: input }); }
```

- [ ] **Step 2: Write the page**

`frontend/src/features/hr/me/MyPage.tsx`:

```tsx
import { useQuery } from "@tanstack/react-query";
import { UserX } from "lucide-react";
import { useSearchParams } from "react-router-dom";
import { AppLoader } from "../../../components/patterns/AppLoader";
import { EmptyState } from "../../../components/patterns/EmptyState";
import { Button } from "../../../components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../../../components/ui/tabs";
import { ApiError } from "../../../lib/api";
import { useAuth } from "../../../lib/auth";
import { useI18n, type TranslationKey } from "../../../lib/i18n";
import { getMyFile, ME_KEYS } from "../api";
import { MyFileTab } from "./MyFileTab";
import { MyLeaveTab } from "./MyLeaveTab";
import { MyPayslipsTab } from "./MyPayslipsTab";

type MeTab = "file" | "payslips" | "leave";
const TABS: { value: MeTab; label: TranslationKey }[] = [
  { value: "file", label: "hr.me.tab.file" },
  { value: "payslips", label: "hr.me.tab.payslips" },
  { value: "leave", label: "hr.me.tab.leave" },
];

/** The signed-in employee's own space. The server decides whose file this is (the session's user);
 * nothing on this page names an employee. */
export function MyPage() {
  const { t } = useI18n();
  const { session } = useAuth();
  const token = session!.token;
  const [params, setParams] = useSearchParams();
  const requested = params.get("tab");
  const tab: MeTab = requested === "payslips" || requested === "leave" ? requested : "file";
  const file = useQuery({ queryKey: ME_KEYS.file, queryFn: () => getMyFile(token), retry: false });

  // The one branded loader of this screen; the tabs load behind Skeletons.
  if (file.isPending) return <AppLoader label={t("hr.me.loading")} fullScreen />;
  if (file.isError) {
    const unlinked = file.error instanceof ApiError && file.error.code === "NO_EMPLOYEE_LINK";
    return (
      <EmptyState
        icon={<UserX className="h-6 w-6" />}
        title={t(unlinked ? "hr.me.noLink.title" : "hr.me.error")}
        description={unlinked ? t("hr.me.noLink.description") : file.error.message}
        action={unlinked ? undefined : <Button variant="outline" onClick={() => file.refetch()}>{t("hr.dashboard.retry")}</Button>}
      />
    );
  }
  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-xl font-semibold tracking-tight">{t("hr.me.title")}</h1>
        <p className="text-sm text-muted-foreground">{`${file.data.first_name} ${file.data.last_name} · ${file.data.employee_no}`}</p>
      </header>
      <Tabs value={tab} onValueChange={(value) => setParams({ tab: value }, { replace: true })}>
        <TabsList>
          {TABS.map((item) => (
            <TabsTrigger key={item.value} value={item.value} active={tab === item.value} layoutId="hr-me-tab">
              {t(item.label)}
            </TabsTrigger>
          ))}
        </TabsList>
        <TabsContent value="file" className="mt-4">
          <MyFileTab file={file.data} />
        </TabsContent>
        <TabsContent value="payslips" className="mt-4">
          <MyPayslipsTab token={token} />
        </TabsContent>
        <TabsContent value="leave" className="mt-4">
          <MyLeaveTab token={token} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
```

- [ ] **Step 3: Write the file tab**

`frontend/src/features/hr/me/MyFileTab.tsx`:

```tsx
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../../components/ui/card";
import { useI18n, type TranslationKey } from "../../../lib/i18n";
import type { MyFile } from "../api";
import { contractTypeLabel, formatDate, formatDecimal } from "../format";

type FileField = { key: Exclude<keyof MyFile, "contract">; label: TranslationKey; date?: boolean };
const FIELDS: FileField[] = [
  { key: "employee_no", label: "hr.me.file.employeeNo" },
  { key: "department_name", label: "hr.me.file.department" },
  { key: "position_title", label: "hr.me.file.position" },
  { key: "job_title", label: "hr.me.file.jobTitle" },
  { key: "site", label: "hr.me.file.site" },
  { key: "hire_date", label: "hr.me.file.hireDate", date: true },
  { key: "badge_no", label: "hr.me.file.badgeNo" },
  { key: "birth_date", label: "hr.me.file.birthDate", date: true },
  { key: "birth_place", label: "hr.me.file.birthPlace" },
  { key: "nationality", label: "hr.me.file.nationality" },
  { key: "marital_status", label: "hr.me.file.maritalStatus" },
  { key: "national_id", label: "hr.me.file.nationalId" },
  { key: "inps_no", label: "hr.me.file.inpsNo" },
  { key: "amo_no", label: "hr.me.file.amoNo" },
  { key: "email", label: "hr.me.file.email" },
  { key: "phone", label: "hr.me.file.phone" },
  { key: "address", label: "hr.me.file.address" },
  { key: "emergency_contact", label: "hr.me.file.emergencyContact" },
];
const MARITAL: Record<string, TranslationKey> = {
  single: "hr.me.file.marital.single",
  married: "hr.me.file.marital.married",
  divorced: "hr.me.file.marital.divorced",
  widowed: "hr.me.file.marital.widowed",
};

export function MyFileTab({ file }: { file: MyFile }) {
  const { t } = useI18n();
  const show = (field: FileField): string => {
    const raw = file[field.key];
    if (raw === null || raw === undefined || raw === "") return "—";
    if (field.date) return formatDate(String(raw));
    if (field.key === "marital_status" && MARITAL[String(raw)]) return t(MARITAL[String(raw)]);
    return String(raw);
  };
  const contract = file.contract;
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Card className="lg:col-span-2">
        <CardHeader>
          <CardTitle>{t("hr.me.tab.file")}</CardTitle>
          <CardDescription>{t("hr.me.file.readOnly")}</CardDescription>
        </CardHeader>
        <CardContent>
          <dl className="grid gap-x-6 gap-y-3 sm:grid-cols-2">
            {FIELDS.map((field) => (
              <div key={field.key}>
                <dt className="text-xs text-muted-foreground">{t(field.label)}</dt>
                <dd className="text-sm">{show(field)}</dd>
              </div>
            ))}
          </dl>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>{t("hr.me.file.contract")}</CardTitle>
        </CardHeader>
        <CardContent>
          {contract === null ? (
            <p className="text-sm text-muted-foreground">{t("hr.me.file.noContract")}</p>
          ) : (
            <dl className="space-y-3">
              <div>
                <dt className="text-xs text-muted-foreground">{t("hr.me.file.contractType")}</dt>
                <dd className="text-sm">{contractTypeLabel(t, contract.contract_type)}</dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">{t("hr.me.file.start")}</dt>
                <dd className="text-sm">{formatDate(contract.start_date)}</dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">{t("hr.me.file.end")}</dt>
                <dd className="text-sm">{contract.end_date ? formatDate(contract.end_date) : t("hr.me.file.openEnded")}</dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">{t("hr.me.file.weeklyHours")}</dt>
                <dd className="text-sm">{contract.weekly_hours === null ? "—" : formatDecimal(contract.weekly_hours)}</dd>
              </div>
            </dl>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
```

- [ ] **Step 4: Write the payslips tab**

`frontend/src/features/hr/me/MyPayslipsTab.tsx`:

```tsx
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Printer } from "lucide-react";
import { Link } from "react-router-dom";
import { ColumnFilterRow, type FilterCell } from "../../../components/patterns/ColumnFilterRow";
import { ColumnVisibilityMenu } from "../../../components/patterns/ColumnVisibilityMenu";
import { FilterTabs } from "../../../components/patterns/FilterTabs";
import { Badge } from "../../../components/ui/badge";
import { Button } from "../../../components/ui/button";
import { Card, CardContent } from "../../../components/ui/card";
import { Skeleton } from "../../../components/ui/skeleton";
import { ResizableTableHead, Table, TableBody, TableCell, TableHeader, TableRow } from "../../../components/ui/table";
import { useI18n, type TranslationKey } from "../../../lib/i18n";
import { useColumnFilters } from "../../../lib/useColumnFilters";
import { useTableColumns, type ColumnDef } from "../../../lib/useTableColumns";
import { getMyPayslips, ME_KEYS, type MyPayslip } from "../api";
import { formatFcfa, formatMonth } from "../format";

type StatusFilter = "all" | MyPayslip["run_status"];
const STATUS_LABEL: Record<MyPayslip["run_status"], TranslationKey> = {
  approved: "hr.me.payslips.status.approved",
  paid: "hr.me.payslips.status.paid",
};
const RUN_TYPE_LABEL: Record<string, TranslationKey> = {
  regular: "hr.me.payslips.runType.regular",
  off_cycle: "hr.me.payslips.runType.off_cycle",
};

export function MyPayslipsTab({ token }: { token: string }) {
  const { t } = useI18n();
  const payslips = useQuery({ queryKey: ME_KEYS.payslips, queryFn: () => getMyPayslips(token) });
  const [status, setStatus] = useState<StatusFilter>("all");
  const filters = useColumnFilters<MyPayslip>([
    { key: "period", kind: "text", getValue: (row) => formatMonth(row.period) },
    { key: "gross", kind: "range", getValue: (row) => row.gross },
    { key: "net", kind: "range", getValue: (row) => row.net },
  ]);
  const range = (key: string): FilterCell => ({
    type: "range",
    min: filters.range[key]?.min ?? "",
    max: filters.range[key]?.max ?? "",
    onMinChange: (value) => filters.setRangeValue(key, "min", value),
    onMaxChange: (value) => filters.setRangeValue(key, "max", value),
  });
  const runType = (row: MyPayslip) => (row.run_type && RUN_TYPE_LABEL[row.run_type] ? t(RUN_TYPE_LABEL[row.run_type]) : row.run_type ?? "—");
  const columns: ColumnDef<MyPayslip>[] = [
    {
      key: "period", header: t("hr.me.payslips.period"), cell: (row) => formatMonth(row.period), sortValue: (row) => row.period, defaultWidth: 180,
      filterCell: { type: "text", placeholder: t("common.filter"), value: filters.text.period ?? "", onChange: (value) => filters.setTextValue("period", value) },
    },
    { key: "runType", header: t("hr.me.payslips.runType"), cell: runType, sortValue: runType, defaultWidth: 140, filterCell: { type: "blank" } },
    {
      key: "status", header: t("hr.me.payslips.status"), sortValue: (row) => row.run_status, defaultWidth: 130, filterCell: { type: "blank" },
      cell: (row) => <Badge variant={row.run_status === "paid" ? "success" : "primary"}>{t(STATUS_LABEL[row.run_status])}</Badge>,
    },
    { key: "gross", header: t("hr.me.payslips.gross"), cell: (row) => formatFcfa(row.gross), sortValue: (row) => row.gross, cellClassName: "text-right tabular-nums", filterCell: range("gross") },
    { key: "net", header: t("hr.me.payslips.net"), cell: (row) => formatFcfa(row.net), sortValue: (row) => row.net, cellClassName: "text-right tabular-nums", filterCell: range("net") },
    {
      key: "print", header: t("hr.me.payslips.print"), alwaysVisible: true, defaultWidth: 120, filterCell: { type: "blank" },
      // Same tab on purpose. The session lives in sessionStorage, and a new tab opened with
      // target="_blank" is noopener in current browsers and starts with an empty sessionStorage,
      // so it would land on /login. The browser's Back returns to /me?tab=payslips.
      cell: (row) => (
        <Link to={`/payroll/payslips/${row.id}/print`} className="inline-flex items-center gap-1 text-sm text-primary hover:underline">
          <Printer className="h-4 w-4" />
          {t("hr.me.payslips.print")}
        </Link>
      ),
    },
  ];
  const { visibleColumns, colWidths, isVisible, toggleVisible, getWidth, setWidth, resetAll, sortDirectionFor, toggleSort, sortRows } =
    useTableColumns("hr.me.payslips", columns);
  const rows = sortRows(filters.apply((payslips.data ?? []).filter((row) => status === "all" || row.run_status === status)));

  if (payslips.isPending) {
    return (
      <div className="space-y-2">
        {[0, 1, 2].map((row) => (
          <Skeleton key={row} className="h-9 w-full" />
        ))}
      </div>
    );
  }
  if (payslips.isError) return <p className="text-sm text-destructive">{payslips.error.message}</p>;
  if (payslips.data.length === 0) {
    return (
      <Card>
        <CardContent className="space-y-1 py-10 text-center">
          <p className="text-sm font-medium">{t("hr.me.payslips.empty")}</p>
          <p className="text-sm text-muted-foreground">{t("hr.me.payslips.emptyHint")}</p>
        </CardContent>
      </Card>
    );
  }
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <FilterTabs
          value={status}
          onChange={setStatus}
          options={[
            { value: "all", label: t("common.all") },
            { value: "approved", label: t(STATUS_LABEL.approved) },
            { value: "paid", label: t(STATUS_LABEL.paid) },
          ]}
        />
        <div className="flex items-center gap-2">
          {filters.isActive && (
            <Button variant="ghost" size="sm" onClick={filters.reset}>
              {t("common.clearFilters")}
            </Button>
          )}
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
          {rows.map((row) => (
            <TableRow key={row.id}>
              {visibleColumns.map((column) => (
                <TableCell key={column.key} className={column.cellClassName}>
                  {column.cell(row)}
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
```

The hooks (`useState`, `useColumnFilters`, `useTableColumns`) are all called before the early returns, so the Rules of Hooks hold.

- [ ] **Step 5: Write the leave tab**

`frontend/src/features/hr/me/MyLeaveTab.tsx`:

```tsx
import { useState } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { ColumnFilterRow } from "../../../components/patterns/ColumnFilterRow";
import { ColumnVisibilityMenu } from "../../../components/patterns/ColumnVisibilityMenu";
import { FilterTabs } from "../../../components/patterns/FilterTabs";
import { Button } from "../../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../../components/ui/card";
import { Input } from "../../../components/ui/input";
import { Select } from "../../../components/ui/select";
import { Skeleton } from "../../../components/ui/skeleton";
import { ResizableTableHead, Table, TableBody, TableCell, TableHeader, TableRow } from "../../../components/ui/table";
import { ApiError } from "../../../lib/api";
import { useI18n, type TranslationKey } from "../../../lib/i18n";
import { useColumnFilters } from "../../../lib/useColumnFilters";
import { useTableColumns, type ColumnDef } from "../../../lib/useTableColumns";
import { createMyLeaveRequest, getMyLeave, ME_KEYS, type MyLeaveRequest } from "../api";
import { formatDate, formatDecimal } from "../format";

// Zod messages are i18n keys, rendered through t(), so the form speaks the user's language.
const requestSchema = z
  .object({
    leave_type_id: z.string().min(1, "hr.me.leave.error.typeRequired"),
    start_date: z.string().min(1, "hr.me.leave.error.dateRequired"),
    end_date: z.string().min(1, "hr.me.leave.error.dateRequired"),
    half_day: z.boolean(),
    reason: z.string().max(500),
  })
  .refine((values) => !values.start_date || !values.end_date || values.end_date >= values.start_date, {
    path: ["end_date"],
    message: "hr.me.leave.error.endBeforeStart",
  });
type RequestForm = z.infer<typeof requestSchema>;
const EMPTY: RequestForm = { leave_type_id: "", start_date: "", end_date: "", half_day: false, reason: "" };

type StatusFilter = "all" | MyLeaveRequest["status"];
const STATUS_LABEL: Record<MyLeaveRequest["status"], TranslationKey> = {
  pending: "hr.me.leaveStatus.pending",
  approved: "hr.me.leaveStatus.approved",
  rejected: "hr.me.leaveStatus.rejected",
  cancelled: "hr.me.leaveStatus.cancelled",
};

function FieldError({ message }: { message?: string }) {
  const { t } = useI18n();
  return message ? <p className="text-xs text-destructive">{t(message as TranslationKey)}</p> : null;
}

export function MyLeaveTab({ token }: { token: string }) {
  const { t } = useI18n();
  const client = useQueryClient();
  const leave = useQuery({ queryKey: ME_KEYS.leave, queryFn: () => getMyLeave(token) });
  const form = useForm<RequestForm>({ resolver: zodResolver(requestSchema), defaultValues: EMPTY });
  const create = useMutation({
    mutationFn: (values: RequestForm) => createMyLeaveRequest(token, { ...values, reason: values.reason.trim() || null }),
    onSuccess: () => {
      toast.success(t("hr.me.leave.created"));
      form.reset(EMPTY);
      client.invalidateQueries({ queryKey: ME_KEYS.leave });
      client.invalidateQueries({ queryKey: ["hr", "leave"] });
    },
    onError: (error) => toast.error(error instanceof ApiError ? error.message : String(error)),
  });

  if (leave.isPending) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-48 w-full" />
      </div>
    );
  }
  if (leave.isError) return <p className="text-sm text-destructive">{leave.error.message}</p>;
  const { balances, requests, year } = leave.data;
  const errors = form.formState.errors;

  return (
    <div className="space-y-6">
      <section className="space-y-2">
        <h2 className="text-sm font-medium">{`${t("hr.me.leave.balanceTitle")} ${year}`}</h2>
        {balances.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t("hr.me.leave.noTypes")}</p>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {balances.map((line) => (
              <Card key={line.leave_type_id} className="space-y-2 p-4">
                <p className="text-sm font-medium">
                  {line.name}
                  <span className="ml-1 text-xs text-muted-foreground">{line.code}</span>
                </p>
                <p className="text-2xl font-semibold tabular-nums">
                  {line.available === null ? t("hr.me.leave.notAccrued") : formatDecimal(line.available)}
                </p>
                <p className="text-xs text-muted-foreground">{t("hr.me.leave.available")}</p>
                <dl className="grid grid-cols-2 gap-1 text-xs tabular-nums text-muted-foreground">
                  <dt>{t("hr.me.leave.accrued")}</dt>
                  <dd className="text-right">{formatDecimal(line.accrued)}</dd>
                  <dt>{t("hr.me.leave.adjusted")}</dt>
                  <dd className="text-right">{formatDecimal(line.adjusted)}</dd>
                  <dt>{t("hr.me.leave.taken")}</dt>
                  <dd className="text-right">{formatDecimal(line.taken)}</dd>
                  <dt>{t("hr.me.leave.pending")}</dt>
                  <dd className="text-right">{formatDecimal(line.pending)}</dd>
                </dl>
              </Card>
            ))}
          </div>
        )}
      </section>

      <Card>
        <CardHeader>
          <CardTitle>{t("hr.me.leave.requestTitle")}</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={form.handleSubmit((values) => create.mutate(values))} className="grid gap-3 sm:grid-cols-2">
            <label className="space-y-1 sm:col-span-2">
              <span className="text-xs text-muted-foreground">{t("hr.me.leave.type")}</span>
              <Select {...form.register("leave_type_id")}>
                <option value="">{t("hr.me.leave.chooseType")}</option>
                {balances.map((line) => (
                  <option key={line.leave_type_id} value={line.leave_type_id}>
                    {line.name}
                  </option>
                ))}
              </Select>
              <FieldError message={errors.leave_type_id?.message} />
            </label>
            <label className="space-y-1">
              <span className="text-xs text-muted-foreground">{t("hr.me.leave.start")}</span>
              <Input type="date" {...form.register("start_date")} />
              <FieldError message={errors.start_date?.message} />
            </label>
            <label className="space-y-1">
              <span className="text-xs text-muted-foreground">{t("hr.me.leave.end")}</span>
              <Input type="date" {...form.register("end_date")} />
              <FieldError message={errors.end_date?.message} />
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" className="h-4 w-4" {...form.register("half_day")} />
              {t("hr.me.leave.halfDay")}
            </label>
            <label className="space-y-1 sm:col-span-2">
              <span className="text-xs text-muted-foreground">{t("hr.me.leave.reason")}</span>
              <Input {...form.register("reason")} />
            </label>
            <div className="flex justify-end sm:col-span-2">
              <Button type="submit" disabled={create.isPending}>
                {t("hr.me.leave.submit")}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>

      <section className="space-y-2">
        <h2 className="text-sm font-medium">{t("hr.me.leave.requestsTitle")}</h2>
        {requests.length === 0 ? <p className="text-sm text-muted-foreground">{t("hr.me.leave.noRequests")}</p> : <MyRequestsTable requests={requests} />}
      </section>
    </div>
  );
}

function MyRequestsTable({ requests }: { requests: MyLeaveRequest[] }) {
  const { t } = useI18n();
  const [status, setStatus] = useState<StatusFilter>("all");
  const typeName = (row: MyLeaveRequest) => row.leave_type_name ?? "—";
  const filters = useColumnFilters<MyLeaveRequest>([
    { key: "type", kind: "text", getValue: typeName },
    { key: "days", kind: "range", getValue: (row) => row.days },
    { key: "reason", kind: "text", getValue: (row) => row.reason },
  ]);
  const columns: ColumnDef<MyLeaveRequest>[] = [
    {
      key: "type", header: t("hr.me.leave.type"), cell: typeName, sortValue: typeName, defaultWidth: 180,
      filterCell: { type: "text", placeholder: t("common.filter"), value: filters.text.type ?? "", onChange: (value) => filters.setTextValue("type", value) },
    },
    { key: "start", header: t("hr.me.leave.start"), cell: (row) => formatDate(row.start_date), sortValue: (row) => row.start_date, defaultWidth: 130, filterCell: { type: "blank" } },
    { key: "end", header: t("hr.me.leave.end"), cell: (row) => formatDate(row.end_date), sortValue: (row) => row.end_date, defaultWidth: 130, filterCell: { type: "blank" } },
    {
      key: "days", header: t("hr.me.leave.days"), cell: (row) => (row.days === null ? "—" : formatDecimal(row.days)), sortValue: (row) => row.days, defaultWidth: 110, cellClassName: "text-right tabular-nums",
      filterCell: { type: "range", min: filters.range.days?.min ?? "", max: filters.range.days?.max ?? "", onMinChange: (value) => filters.setRangeValue("days", "min", value), onMaxChange: (value) => filters.setRangeValue("days", "max", value) },
    },
    { key: "status", header: t("hr.me.leave.status"), cell: (row) => t(STATUS_LABEL[row.status]), sortValue: (row) => row.status, defaultWidth: 130, filterCell: { type: "blank" } },
    {
      key: "reason", header: t("hr.me.leave.reason"), cell: (row) => row.reason ?? "—", defaultWidth: 220,
      filterCell: { type: "text", placeholder: t("common.filter"), value: filters.text.reason ?? "", onChange: (value) => filters.setTextValue("reason", value) },
    },
  ];
  const { visibleColumns, colWidths, isVisible, toggleVisible, getWidth, setWidth, resetAll, sortDirectionFor, toggleSort, sortRows } =
    useTableColumns("hr.me.leaveRequests", columns);
  const rows = sortRows(filters.apply(requests.filter((row) => status === "all" || row.status === status)));
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <FilterTabs
          value={status}
          onChange={setStatus}
          options={[
            { value: "all", label: t("common.all") },
            { value: "pending", label: t(STATUS_LABEL.pending) },
            { value: "approved", label: t(STATUS_LABEL.approved) },
            { value: "rejected", label: t(STATUS_LABEL.rejected) },
            { value: "cancelled", label: t(STATUS_LABEL.cancelled) },
          ]}
        />
        <div className="flex items-center gap-2">
          {filters.isActive && (
            <Button variant="ghost" size="sm" onClick={filters.reset}>
              {t("common.clearFilters")}
            </Button>
          )}
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
          {rows.map((row) => (
            <TableRow key={row.id}>
              {visibleColumns.map((column) => (
                <TableCell key={column.key} className={column.cellClassName}>
                  {column.cell(row)}
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
```

`MyLeaveTab` calls all its hooks (`useQuery`, `useForm`, `useMutation`) before its early returns. The table has its own component, so the hooks it needs are not called conditionally.

- [ ] **Step 6: Add the strings (both languages)**

`en` dictionary, next to `"nav.hr"`:

```ts
  "nav.mySpace": "My space",
```

and with the `hr.*` keys:

```ts
  "hr.me.title": "My space",
  "hr.me.loading": "Loading your space",
  "hr.me.error": "Your space could not be loaded",
  "hr.me.noLink.title": "Your account is not linked to an employee file",
  "hr.me.noLink.description": "Ask HR to link your user account to your employee file.",
  "hr.me.tab.file": "My file",
  "hr.me.tab.payslips": "My payslips",
  "hr.me.tab.leave": "My leave",
  "hr.me.file.readOnly": "Read-only. Ask HR to correct anything wrong.",
  "hr.me.file.employeeNo": "Employee number",
  "hr.me.file.department": "Department",
  "hr.me.file.position": "Position",
  "hr.me.file.jobTitle": "Job title",
  "hr.me.file.site": "Site",
  "hr.me.file.hireDate": "Hire date",
  "hr.me.file.badgeNo": "Badge number",
  "hr.me.file.birthDate": "Birth date",
  "hr.me.file.birthPlace": "Birth place",
  "hr.me.file.nationality": "Nationality",
  "hr.me.file.maritalStatus": "Marital status",
  "hr.me.file.nationalId": "National ID (NINA)",
  "hr.me.file.inpsNo": "INPS number",
  "hr.me.file.amoNo": "AMO number",
  "hr.me.file.email": "Email",
  "hr.me.file.phone": "Phone",
  "hr.me.file.address": "Address",
  "hr.me.file.emergencyContact": "Emergency contact",
  "hr.me.file.marital.single": "Single",
  "hr.me.file.marital.married": "Married",
  "hr.me.file.marital.divorced": "Divorced",
  "hr.me.file.marital.widowed": "Widowed",
  "hr.me.file.contract": "Current contract",
  "hr.me.file.noContract": "No contract in force this month.",
  "hr.me.file.contractType": "Contract type",
  "hr.me.file.start": "Start",
  "hr.me.file.end": "End",
  "hr.me.file.openEnded": "Open-ended",
  "hr.me.file.weeklyHours": "Weekly hours",
  "hr.me.payslips.period": "Period",
  "hr.me.payslips.runType": "Payroll",
  "hr.me.payslips.runType.regular": "Regular",
  "hr.me.payslips.runType.off_cycle": "Off-cycle",
  "hr.me.payslips.status": "Status",
  "hr.me.payslips.status.approved": "Approved",
  "hr.me.payslips.status.paid": "Paid",
  "hr.me.payslips.gross": "Gross",
  "hr.me.payslips.net": "Net pay",
  "hr.me.payslips.print": "Print",
  "hr.me.payslips.empty": "No payslip yet.",
  "hr.me.payslips.emptyHint": "A payslip appears here once the month's payroll is approved.",
  "hr.me.leave.balanceTitle": "Leave balance",
  "hr.me.leave.noTypes": "No leave types are set up yet.",
  "hr.me.leave.available": "Available days",
  "hr.me.leave.notAccrued": "—",
  "hr.me.leave.accrued": "Accrued",
  "hr.me.leave.adjusted": "Adjusted",
  "hr.me.leave.taken": "Taken",
  "hr.me.leave.pending": "Pending requests",
  "hr.me.leave.requestTitle": "Request leave",
  "hr.me.leave.type": "Leave type",
  "hr.me.leave.chooseType": "Choose a leave type",
  "hr.me.leave.start": "From",
  "hr.me.leave.end": "To",
  "hr.me.leave.halfDay": "Half day",
  "hr.me.leave.reason": "Reason (optional)",
  "hr.me.leave.submit": "Send request",
  "hr.me.leave.created": "Leave request sent",
  "hr.me.leave.error.typeRequired": "Choose a leave type",
  "hr.me.leave.error.dateRequired": "Choose a date",
  "hr.me.leave.error.endBeforeStart": "The end date cannot be before the start date",
  "hr.me.leave.requestsTitle": "My requests",
  "hr.me.leave.noRequests": "No leave request yet.",
  "hr.me.leave.days": "Days",
  "hr.me.leave.status": "Status",
  "hr.me.leaveStatus.pending": "Pending",
  "hr.me.leaveStatus.approved": "Approved",
  "hr.me.leaveStatus.rejected": "Rejected",
  "hr.me.leaveStatus.cancelled": "Cancelled",
```

`fr` dictionary:

```ts
  "nav.mySpace": "Mon espace",
```

```ts
  "hr.me.title": "Mon espace",
  "hr.me.loading": "Chargement de votre espace",
  "hr.me.error": "Votre espace n'a pas pu être chargé",
  "hr.me.noLink.title": "Votre compte n'est lié à aucune fiche employé",
  "hr.me.noLink.description": "Demandez aux RH de lier votre compte utilisateur à votre fiche employé.",
  "hr.me.tab.file": "Ma fiche",
  "hr.me.tab.payslips": "Mes bulletins",
  "hr.me.tab.leave": "Mes congés",
  "hr.me.file.readOnly": "Lecture seule. Demandez aux RH de corriger toute erreur.",
  "hr.me.file.employeeNo": "Matricule",
  "hr.me.file.department": "Département",
  "hr.me.file.position": "Poste",
  "hr.me.file.jobTitle": "Fonction",
  "hr.me.file.site": "Site",
  "hr.me.file.hireDate": "Date d'embauche",
  "hr.me.file.badgeNo": "N° de badge",
  "hr.me.file.birthDate": "Date de naissance",
  "hr.me.file.birthPlace": "Lieu de naissance",
  "hr.me.file.nationality": "Nationalité",
  "hr.me.file.maritalStatus": "Situation familiale",
  "hr.me.file.nationalId": "NINA",
  "hr.me.file.inpsNo": "N° INPS",
  "hr.me.file.amoNo": "N° AMO",
  "hr.me.file.email": "E-mail",
  "hr.me.file.phone": "Téléphone",
  "hr.me.file.address": "Adresse",
  "hr.me.file.emergencyContact": "Contact d'urgence",
  "hr.me.file.marital.single": "Célibataire",
  "hr.me.file.marital.married": "Marié(e)",
  "hr.me.file.marital.divorced": "Divorcé(e)",
  "hr.me.file.marital.widowed": "Veuf / veuve",
  "hr.me.file.contract": "Contrat en cours",
  "hr.me.file.noContract": "Aucun contrat en vigueur ce mois-ci.",
  "hr.me.file.contractType": "Type de contrat",
  "hr.me.file.start": "Début",
  "hr.me.file.end": "Fin",
  "hr.me.file.openEnded": "Durée indéterminée",
  "hr.me.file.weeklyHours": "Heures hebdomadaires",
  "hr.me.payslips.period": "Période",
  "hr.me.payslips.runType": "Paie",
  "hr.me.payslips.runType.regular": "Normale",
  "hr.me.payslips.runType.off_cycle": "Hors cycle",
  "hr.me.payslips.status": "Statut",
  "hr.me.payslips.status.approved": "Approuvé",
  "hr.me.payslips.status.paid": "Payé",
  "hr.me.payslips.gross": "Brut",
  "hr.me.payslips.net": "Net à payer",
  "hr.me.payslips.print": "Imprimer",
  "hr.me.payslips.empty": "Aucun bulletin pour l'instant.",
  "hr.me.payslips.emptyHint": "Un bulletin apparaît ici une fois la paie du mois approuvée.",
  "hr.me.leave.balanceTitle": "Solde de congés",
  "hr.me.leave.noTypes": "Aucun type de congé n'est encore paramétré.",
  "hr.me.leave.available": "Jours disponibles",
  "hr.me.leave.notAccrued": "—",
  "hr.me.leave.accrued": "Acquis",
  "hr.me.leave.adjusted": "Ajusté",
  "hr.me.leave.taken": "Pris",
  "hr.me.leave.pending": "Demandes en attente",
  "hr.me.leave.requestTitle": "Demander un congé",
  "hr.me.leave.type": "Type de congé",
  "hr.me.leave.chooseType": "Choisissez un type de congé",
  "hr.me.leave.start": "Du",
  "hr.me.leave.end": "Au",
  "hr.me.leave.halfDay": "Demi-journée",
  "hr.me.leave.reason": "Motif (facultatif)",
  "hr.me.leave.submit": "Envoyer la demande",
  "hr.me.leave.created": "Demande de congé envoyée",
  "hr.me.leave.error.typeRequired": "Choisissez un type de congé",
  "hr.me.leave.error.dateRequired": "Choisissez une date",
  "hr.me.leave.error.endBeforeStart": "La date de fin ne peut pas précéder la date de début",
  "hr.me.leave.requestsTitle": "Mes demandes",
  "hr.me.leave.noRequests": "Aucune demande de congé pour l'instant.",
  "hr.me.leave.days": "Jours",
  "hr.me.leave.status": "Statut",
  "hr.me.leaveStatus.pending": "En attente",
  "hr.me.leaveStatus.approved": "Approuvée",
  "hr.me.leaveStatus.rejected": "Refusée",
  "hr.me.leaveStatus.cancelled": "Annulée",
```

- [ ] **Step 7: Route and nav entry**

`frontend/src/routes/router.tsx`: import and route. The page has no chart, so it is not lazy-loaded:

```tsx
import { MyPage } from "../features/hr/me/MyPage";
```

```tsx
  { path: "/me", element: <MyPage /> },
```

`frontend/src/routes/Sidebar.tsx`, HR group `items`. `UserCircle` is already imported:

```ts
      { to: "/me", labelKey: "nav.mySpace", icon: UserCircle, permission: "hr.self_service" },
```

- [ ] **Step 8: Type-check**

Run (from `frontend/`): `npx tsc -b --force`
Expected: exits 0 with no output.

- [ ] **Step 9: Browser check**

With the API and SPA running, log in as a user who has `hr.self_service` and is linked to an employee. Task 10 does this for the demo login; before then, grant and link one by hand in the dev DB. Open `/me`. Expected:
- one loader, then the file;
- the payslips and leave tabs load behind Skeletons;
- a payslip's Print opens `/payroll/payslips/<id>/print` in the same tab, still signed in, and renders; Back returns to the payslips tab;
- sending a leave request toasts success and the request appears as pending;
- a user with the permission but no link sees the "not linked" state;
- `fr` shows every string translated.

- [ ] **Step 10: Commit**

```bash
git add frontend/src/features/hr/api.ts frontend/src/features/hr/me frontend/src/routes/router.tsx frontend/src/routes/Sidebar.tsx frontend/src/lib/i18n.tsx
git commit -m "feat(hr): /me self-service screen (my file, my payslips, my leave)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Demo seed: link the demo login to an employee and grant self-service

**Files:**
- Modify: `backend/scripts/seed_hr_payroll.py`
- Test: `backend/scripts/test_seed_hr_self_service_integration.py`

**Interfaces:**
- Consumes: `hr.employees.user_id` (A6), `core.users`, `core.user_permissions (user_id, permission)` with primary key `(user_id, permission)`.
- Produces: `SELF_SERVICE_DEMO_EMAIL`, `link_demo_self_service(connection, tenant_id: str) -> str | None` (the linked employee id).

- [ ] **Step 1: Write the failing test**

`backend/scripts/test_seed_hr_self_service_integration.py`:

```python
"""The HR seed links the demo login to one employee, once, and grants it self-service."""
from __future__ import annotations

import datetime

from ulid import ULID

from scripts.seed_hr_payroll import SELF_SERVICE_DEMO_EMAIL, link_demo_self_service

TENANT = "seed-self-service-test"


def test_the_demo_login_is_linked_once_and_granted_self_service(db):
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, 'demo', %s, 'x') ON CONFLICT (email) DO NOTHING",
        (str(ULID()), SELF_SERVICE_DEMO_EMAIL),
    )
    user_id = db.execute("SELECT id FROM core.users WHERE email = %s", (SELF_SERVICE_DEMO_EMAIL,)).fetchone()[0]
    db.execute("UPDATE hr.employees SET user_id = NULL WHERE user_id = %s", (user_id,))  # rolled back after the test
    first, second = str(ULID()), str(ULID())
    for employee_id, number in ((first, "SS-001"), (second, "SS-002")):
        db.execute(
            "INSERT INTO hr.employees (id, tenant_id, employee_no, first_name, last_name, hire_date, status) "
            "VALUES (%s, %s, %s, 'Demo', 'Employé', %s, 'active')",
            (employee_id, TENANT, number, datetime.date(2025, 1, 6)),
        )
    assert link_demo_self_service(db, TENANT) == first
    assert link_demo_self_service(db, TENANT) == first  # run again: same link, no second employee
    assert db.execute("SELECT user_id FROM hr.employees WHERE id = %s", (first,)).fetchone()[0] == user_id
    assert db.execute("SELECT user_id FROM hr.employees WHERE id = %s", (second,)).fetchone()[0] is None
    granted = {row[0] for row in db.execute("SELECT permission FROM core.user_permissions WHERE user_id = %s", (user_id,)).fetchall()}
    assert {"hr.self_service", "hr.view_dashboard", "hr.view_sensitive"} <= granted
```

Run: `.venv/Scripts/python -m pytest scripts/test_seed_hr_self_service_integration.py -q`
Expected: `ImportError: cannot import name 'SELF_SERVICE_DEMO_EMAIL' from 'scripts.seed_hr_payroll'`. If instead the import runs the whole seed, the script lacks a `__main__` guard (A11): wrap its entry call in `if __name__ == "__main__":` first.

- [ ] **Step 2: Write the seed function and call it**

Add to `backend/scripts/seed_hr_payroll.py` (module level):

```python
SELF_SERVICE_DEMO_EMAIL = "demo@sonalim-erp.local"
# hr.self_service opens /me; hr.view_dashboard and hr.view_sensitive let the same demo login see the
# HR dashboard with its payroll block. New permissions are not auto-granted to the demo user.
SELF_SERVICE_DEMO_PERMISSIONS = ("hr.self_service", "hr.view_dashboard", "hr.view_sensitive")


def link_demo_self_service(connection, tenant_id: str) -> str | None:
    """Links the demo login to the first active employee (by number) that no user owns yet, and
    grants it self-service, so /me shows a real file and leave. Idempotent: an existing link is kept."""
    user = connection.execute("SELECT id FROM core.users WHERE email = %s", (SELF_SERVICE_DEMO_EMAIL,)).fetchone()
    if user is None:
        print(f"self-service: {SELF_SERVICE_DEMO_EMAIL} not found; run scripts.seed_dev first")
        return None
    user_id = user[0]
    linked = connection.execute(
        "SELECT id, employee_no FROM hr.employees WHERE tenant_id = %s AND user_id = %s", (tenant_id, user_id)
    ).fetchone()
    if linked is None:
        linked = connection.execute(
            """
            SELECT id, employee_no FROM hr.employees
            WHERE tenant_id = %s AND user_id IS NULL AND status = 'active'
            ORDER BY employee_no LIMIT 1
            """,
            (tenant_id,),
        ).fetchone()
        if linked is None:
            print("self-service: no active employee without a user to link")
            return None
        connection.execute("UPDATE hr.employees SET user_id = %s WHERE id = %s AND tenant_id = %s", (user_id, linked[0], tenant_id))
    for permission in SELF_SERVICE_DEMO_PERMISSIONS:
        connection.execute(
            "INSERT INTO core.user_permissions (user_id, permission) VALUES (%s, %s) ON CONFLICT (user_id, permission) DO NOTHING",
            (user_id, permission),
        )
    print(f"self-service: {SELF_SERVICE_DEMO_EMAIL} -> employee {linked[1]}; granted {', '.join(SELF_SERVICE_DEMO_PERMISSIONS)}")
    return linked[0]
```

Call it at the end of the seed's main transaction, after the employees are written and before the commit, with the tenant constant the script already uses (`"demo"`):

```python
        link_demo_self_service(connection, DEMO_TENANT_ID)
```

- [ ] **Step 3: Run the test to verify it passes**

Run: `.venv/Scripts/python -m pytest scripts/test_seed_hr_self_service_integration.py -q`
Expected: `1 passed` (not skipped).

- [ ] **Step 4: Run the seed on the dev DB and look**

Run: `.venv/Scripts/python -m scripts.seed_hr_payroll`
Expected: the output ends with a line `self-service: demo@sonalim-erp.local -> employee <number>; granted hr.self_service, hr.view_dashboard, hr.view_sensitive`. Log out and log in again, since permissions load with the session. Then:
- the sidebar shows "HR dashboard" and "My space";
- `/me` shows the linked employee's file and leave;
- `/hr/dashboard` shows the payroll block.

"My payslips" shows the empty state. This is expected: the seeded run is only *calculated* on a *draft* rule set, which the spec forbids approving, and an employee sees approved or paid payslips only.

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/seed_hr_payroll.py backend/scripts/test_seed_hr_self_service_integration.py
git commit -m "chore(seed): link the demo login to an employee and grant hr.self_service" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Final check (after Task 10)

- [ ] Run: `.venv/Scripts/python -m pytest modules/hr modules/payroll scripts/test_seed_hr_self_service_integration.py -q` from `backend/`. Expected: all pass. The new integration tests (Tasks 2–7, 10) show as passed, not skipped.
- [ ] Run: `npx tsc -b --force` from `frontend/`. Expected: exit 0.
- [ ] `git status` shows nothing left from this plan uncommitted, and nothing was pushed.

## Spec coverage (self-review)

| Spec / brief requirement | Task |
|---|---|
| Headcount by department and contract type | 1 (`headcount`), 3, 8 (chart + share bars) |
| Hires / exits of the month | 1 (`movements`), 8 |
| Absence rate = unpaid_absence_days / scheduled_days | 1 (`absence`), 8 (tile with both counts shown) |
| Overtime hours by band | 1 (`overtime_minutes`), 8 (current vs previous chart) |
| Payroll gross + employer cost by department | 1 (`payroll_by_department`), 3 (via `cost_by_department`), 8 (table + tiles) |
| Month-on-month variance | 1 (`variance` on every measure), 8 (neutral signed change) |
| Contract / trial / document expiry from hr.settings horizons | 2, 8 |
| Domain aggregation tested without DB | 1, 2, 5, 7 (domain tests) |
| `/me` gated by `hr.self_service`; own record only via user_id | 5, 6 |
| My payslips (list + print link, own only, isolation tested) | 5, 6, 7, 9 |
| My leave balance + create leave request | 5, 6, 9 |
| Only contract services across modules | 3 (`payroll_bridge`), 5, 7 (payroll → hr `get_by_user`) |
| hr migrations from 0020 only if needed | 2 (`0020`, conditional per contract check A5) |
| One loader per screen, Skeleton sub-blocks | 8, 9 |
| Demo user linked + `hr.self_service` granted | 10 |
