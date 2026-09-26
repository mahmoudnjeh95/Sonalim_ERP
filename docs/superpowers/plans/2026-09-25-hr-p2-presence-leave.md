# HR Phase 2 — Time & Presence + Leave Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Supervisors and the clock device record who worked when (one `hr.presence_days` row per employee and date), leave requests are approved against accrued balances, and a closed month gives payroll one exact summary per employee through `PresenceService.month_summary`.

**Architecture:** Everything lives in the existing `hr` module. Pure domain files (`domain/schedule.py`, `domain/presence.py`, `domain/pairing.py`, `domain/clock_csv.py`, `domain/leave.py`) hold every rule and are tested without a database. Services in `api/` (one per concern) load rows, call the domain, write rows, call `record_audit()` in the caller's transaction, and never commit; one new router file `api/presence_router.py` exposes them. Closing a month writes an outbox row `hr.presence_month.closed`; a new consumer reacts to phase 3's `payroll.run.approved/reversed` to block reopening a month whose payroll is approved. The old `hr.attendance_records` table and `/hr/attendance` endpoints stay untouched.

**Tech Stack:** FastAPI + raw SQL via psycopg 3 (Python 3, pytest), React 18 + TS (Vite, TanStack Query, React Router, Tailwind + hand-written Radix primitives). No new dependency (no `python-multipart`: the clock CSV travels as JSON text).

**Spec:** `docs/superpowers/specs/2026-09-25-hr-payroll-finance-design.md` (section "Phase 2 — Time & presence") and the cross-phase contract `docs/superpowers/plans/2026-09-25-hr-payroll-finance-interfaces.md`.

## Global Constraints

- Phase 1 (`2026-09-25-hr-p1-employee-core.md`) is merged before this plan starts: `hr.employees` has `badge_no` (unique per tenant, nullable), `termination_date`, `status` including `'terminated'`; `hr/module.json` already declares `hr.view_presence`, `hr.manage_presence`, `hr.import_clock`, `hr.close_presence`, `hr.admin_presence`; `backend/scripts/seed_hr_payroll.py` exists and seeds the demo tenant's employees. If any of these is missing, stop and report — do not re-create phase 1 work here.
- Contract names are fixed, copied verbatim from the interfaces file: `backend/modules/hr/api/presence_service.py` defines `class PresenceService` with
  `month_summary(self, *, tenant_id: str, period: datetime.date, employee_ids: list[str] | None = None) -> list[dict]` (keys exactly `employee_id, scheduled_days, worked_days, unpaid_absence_days, paid_leave_days, sick_days, holiday_days, holidays_worked_days, ot_minutes_day, ot_minutes_night, ot_minutes_rest_holiday, night_minutes, late_minutes`, all `int` except the id) and
  `is_month_closed(self, *, tenant_id: str, period: datetime.date) -> bool`. Overtime band codes are exactly `day`, `night`, `rest_holiday`. Event on close: `hr.presence_month.closed`, payload `{period}` (ISO date of the first day of the month).
- `hr` migrations of this phase use numbers `0010_*`..`0019_*` only (this plan uses 0010–0014). Never edit an applied migration.
- A "period" is a `datetime.date` equal to the first day of a month.
- Frontend routes exactly: `/hr/presence`, `/hr/presence/imports`, `/hr/leave`, `/hr/schedules`; feature folder `frontend/src/features/hr/`.
- `hr.attendance_records`, `hr.payroll_runs`, `hr.payroll_items` and their endpoints are not touched, not dropped, not written by new code.
- Every `Err(...)` carries its French as the third positional argument (`Err(code, message, message_fr)`); routers raise `HTTPException(status, err_detail(err))`.
- Every mutating service method takes `actor_id: str` and calls `record_audit()` in the same transaction; routers pass `actor_id=tenant.user_id`. Services never commit; the router commits or rolls back.
- Every entity with a create action has an edit action behind a separate admin permission: schedules, rotations, assignments, public holidays, clock profiles, presence settings and month reopen → `hr.admin_presence`; leave types, leave requests (edit) and balance adjustments → `hr.admin_leave`.
- Route permissions (enforced by the route tests of each task):

  | Routes | Permission |
  |---|---|
  | every `GET` of schedules, rotations, assignments, holidays, presence settings, grid, week, employee-month, months, gaps, summary, clock profiles, clock imports | `hr.view_presence` |
  | `POST /hr/schedules`, `/hr/rotation-patterns`, `/hr/schedule-assignments`, `/hr/public-holidays`; `PUT /hr/presence/days` | `hr.manage_presence` |
  | `PATCH` of those four + `PATCH /hr/clock-profiles/{id}` + `PUT /hr/presence/settings` + `POST /hr/presence/months/{period}/reopen` | `hr.admin_presence` |
  | `POST /hr/clock-profiles`, `POST /hr/clock-imports`, `POST /hr/clock-imports/{id}/commit`, `POST /hr/clock-imports/{id}/discard` | `hr.import_clock` |
  | `POST /hr/presence/months/{period}/close` | `hr.close_presence` |
  | `GET /hr/leave-types`, `GET /hr/leave/requests`, `GET /hr/leave/balances` | `hr.view_leave` |
  | `POST /hr/leave-types`, `POST /hr/leave/requests`, `POST /hr/leave/requests/{id}/approve|reject|cancel` | `hr.manage_leave` |
  | `PATCH /hr/leave-types/{id}`, `PATCH /hr/leave/requests/{id}`, `POST /hr/leave/balances/adjust` | `hr.admin_leave` |

- No statutory or plant value is written in code: the night-work window, punch attachment minutes, duplicate-punch seconds, lateness grace, public holidays, leave accrual per month, carry-over caps are database rows. Their tables start empty; a calculation that needs a missing value refuses with `PRESENCE_SETTINGS_MISSING` instead of assuming one. Only the dev seed (Task 14) writes draft values, flagged `confirmed = FALSE`, and prints them for HR to check.
- Times: clock punches are the device's wall-clock time (`TIMESTAMP` without time zone, Mali is UTC+0 with no DST). Weekday numbering everywhere is Python's `date.weekday()`: Monday = 0 … Sunday = 6. A shift whose end is not after its start crosses midnight and belongs to the day it starts on.
- Backend commands run from `backend/` with `.venv/Scripts/python` (Windows). Domain tests need nothing; integration tests (`*_integration.py`) use the `db` fixture and **skip** when no migrated DB is reachable — read the pytest summary: a run whose skips cover the integration tests tested nothing. After adding a migration, apply it before running integration tests:
  `DATABASE_URL=postgresql://erp:erp@localhost:5432/erp .venv/Scripts/python.exe -c "from core.migrations.runner import apply_all_migrations; apply_all_migrations()"`
- Frontend: from `frontend/`, `npx tsc -b --force` (never plain `tsc -b`). Every string through `useI18n()`, keys added to both `en` and `fr` in `frontend/src/lib/i18n.tsx` (append each task's keys at the end of the `en` object, just before `} as const;`, and at the end of the `fr` object, just before its closing `};`). Server state only through TanStack Query. Every list uses FilterTabs + ColumnFilterRow + `useTableColumns` (here through the shared `HrListTable`). One branded loader per screen (`AppLoader` until the page's first data), skeletons after.
- Shared working tree: never `git stash`, never `git add -A`; each commit step adds only the files it lists. Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Do not push.

## Review Focus

1. **An Excel-saved clock export (UTF-8 BOM + CRLF line endings).** Expected: read exactly like a plain file — header recognised, line numbers right. Pinned by `test_an_excel_export_with_bom_and_crlf_is_read` (Task 5).
2. **A clock file whose covered days straddle a closed month and an open one.** Expected: the whole commit is refused with `PRESENCE_MONTH_CLOSED`, no punch and no day written, the import stays staged. Pinned by `test_a_file_touching_a_closed_month_is_refused_whole` (Task 6).
3. **A device with no in/out column and a forgotten punch.** Expected: the missing punch spoils only its own day (MISSING_OUT); the next day still pairs correctly. Pinned by `test_unknown_directions_do_not_carry_a_forgotten_punch_into_the_next_day` (Task 4).
4. **Two partial exports for the same days (morning file, then evening file).** Expected: the second commit recomputes the day from all punches of both files — full worked time, no anomaly left, no duplicated punch. Pinned by `test_a_second_file_completes_the_days_of_the_first` (Task 6).
5. **An employee who leaves mid-month.** Expected: the close only asks for presence up to the termination date; days after it are neither gaps nor editable. Pinned by `test_gaps_stop_at_the_termination_date` (Task 9) and the accrual proration test (Task 7).

---

## File Structure

Backend (all under `backend/`):

| File | Responsibility |
|---|---|
| `modules/hr/migrations/0010_hr_work_schedules.sql` | schedules, schedule days, rotation patterns + steps, schedule assignments |
| `modules/hr/migrations/0011_hr_holidays_presence_settings.sql` | public holidays, per-tenant presence settings (start empty) |
| `modules/hr/migrations/0012_hr_presence_days.sql` | presence days, presence months, payroll locks |
| `modules/hr/migrations/0013_hr_clock_imports.sql` | clock profiles, imports, import rows, punches |
| `modules/hr/migrations/0014_hr_leave_types_balances.sql` | leave types, balances, accruals, new `leave_requests` columns |
| `modules/hr/domain/schedule.py` | schedule windows, rotation, assignment resolution, night overlap, settings/holiday validation |
| `modules/hr/domain/presence.py` | presence statuses, manual-entry rules, day figures, month summary aggregation |
| `modules/hr/domain/pairing.py` | punch pairing engine |
| `modules/hr/domain/clock_csv.py` | clock profile validation, CSV parsing |
| `modules/hr/domain/leave.py` | leave types, counted days, accrual, balances roll-over |
| `modules/hr/api/schedule_service.py` | `ScheduleService`, `HolidayService`, `PresenceSettingsService` |
| `modules/hr/api/presence_service.py` | `PresenceService` (grid, week, employee month, save, `month_summary`, `is_month_closed`) + shared helpers |
| `modules/hr/api/clock_import_service.py` | `ClockProfileService`, `ClockImportService` |
| `modules/hr/api/leave_service.py` | `LeaveTypeService`, `LeaveRequestService`, `LeaveBalanceService` |
| `modules/hr/api/presence_month_service.py` | `PresenceMonthService` (months, gaps, close, reopen) |
| `modules/hr/api/presence_router.py` | every phase-2 HTTP route |
| `modules/hr/events/__init__.py`, `modules/hr/events/consumers.py` | payroll-lock consumers |
| `modules/hr/api/presence_testkit.py` | shared integration fixture `presence_env` and helpers (not a test file) |
| `app/main.py`, `worker/main.py`, `modules/hr/module.json`, `events/CATALOG.md` | wiring |
| `scripts/seed_hr_payroll.py` | + one month of presence, clock sample, leave |

Frontend (all under `frontend/src/`):

| File | Responsibility |
|---|---|
| `features/hr/presenceApi.ts` | types, query keys and fetchers for every phase-2 endpoint |
| `features/hr/presenceFormat.ts` | minute/clock/date helpers |
| `features/hr/HrListTable.tsx` | the shared list table (columns as data, filter row, visibility, skeletons) |
| `features/hr/HrTabsPage.tsx` | page header + sticky tab bar driven by `?tab=`, one loader per screen |
| `features/hr/presence/PresenceStatusBadge.tsx` | status badge + label map |
| `features/hr/schedules/*.tsx` | `/hr/schedules` page and its five tabs |
| `features/hr/presence/*.tsx` | `/hr/presence` page (day, week, employee month, month close) and `/hr/presence/imports` |
| `features/hr/leave/*.tsx` | `/hr/leave` page (requests, balances, types) |
| `routes/router.tsx`, `routes/Sidebar.tsx`, `lib/i18n.tsx` | wiring and strings |

---

### Task 1: Schedule domain — windows, rotations, assignments, night overlap

**Files:**
- Create: `backend/modules/hr/domain/schedule.py`
- Test: `backend/modules/hr/domain/test_schedule.py`

**Interfaces:**
- Consumes: `core.domain.result.Err, Ok, Result`.
- Produces (used by every later task):
  - `MINUTES_PER_DAY = 1440`, `ONE_DAY: datetime.timedelta`
  - `minutes_between(start: datetime.datetime, end: datetime.datetime) -> int`
  - `date_range(first: datetime.date, last: datetime.date) -> list[datetime.date]`
  - `@dataclass(frozen=True) ScheduleDay(weekday: int, start_minute: int, end_minute: int, break_minutes: int = 0)` with property `span_minutes`
  - `@dataclass(frozen=True) Schedule(id: str, code: str, days: tuple[ScheduleDay, ...], is_night: bool = False)` with `day(weekday) -> ScheduleDay | None`
  - `@dataclass(frozen=True) ShiftWindow(work_date, start: datetime, end: datetime, break_minutes: int, schedule_id: str)` with property `scheduled_minutes`
  - `shift_window(schedule: Schedule, work_date: date) -> ShiftWindow | None`
  - `validate_schedule(*, code, name, days: list[ScheduleDay]) -> Result[None]` (code `INVALID_SCHEDULE`)
  - `@dataclass(frozen=True) RotationPattern(id: str, anchor_date: date, schedule_ids: tuple[str, ...])`
  - `validate_rotation(*, code, name, anchor_date, schedule_ids: list[str]) -> Result[None]` (code `INVALID_ROTATION`)
  - `rotation_schedule_id(pattern, work_date, offset_weeks: int = 0) -> str`
  - `@dataclass(frozen=True) Assignment(id, employee_id, valid_from, valid_to, schedule_id=None, rotation_pattern_id=None, rotation_offset_weeks=0)` with `covers(day) -> bool`
  - `validate_assignment(*, valid_from, valid_to, schedule_id, rotation_pattern_id, rotation_offset_weeks, others: list[Assignment]) -> Result[None]` (codes `INVALID_ASSIGNMENT`, `ASSIGNMENT_OVERLAP`)
  - `resolve_schedule_id(assignments, patterns: dict[str, RotationPattern], day) -> str | None`
  - `@dataclass(frozen=True) ResolvedDay(work_date, assigned: bool, schedule_id=None, schedule_code=None, window: ShiftWindow | None = None)` with property `is_working_day`
  - `resolve_days(*, assignments, patterns, schedules: dict[str, Schedule], dates) -> dict[date, ResolvedDay]`
  - `night_overlap_minutes(start: datetime, end: datetime, night_start_minute: int, night_end_minute: int) -> int`
  - `validate_holiday(*, country_code: str, name: str) -> Result[None]` (code `INVALID_HOLIDAY`)
  - `validate_presence_settings(*, night_start_minute, night_end_minute, punch_attach_minutes, punch_dedupe_seconds, late_grace_minutes) -> Result[None]` (code `INVALID_SETTINGS`)

- [ ] **Step 1: Write the failing tests**

`backend/modules/hr/domain/test_schedule.py`:

```python
"""Schedules and rotations, without a database.

The night window used here (21:00-05:00) is a test input, not the plant's setting:
the real one is a row of hr.presence_settings that HR confirms.
"""
from __future__ import annotations

import datetime as dt

import pytest

from core.domain.result import Err, Ok
from modules.hr.domain.schedule import (
    Assignment,
    RotationPattern,
    Schedule,
    ScheduleDay,
    date_range,
    night_overlap_minutes,
    resolve_days,
    resolve_schedule_id,
    rotation_schedule_id,
    shift_window,
    validate_assignment,
    validate_holiday,
    validate_presence_settings,
    validate_rotation,
    validate_schedule,
)

AUG_3 = dt.date(2026, 8, 3)  # a Monday
AUG_4 = dt.date(2026, 8, 4)
DAY = Schedule(id="s-day", code="JOUR", days=tuple(ScheduleDay(w, 420, 900) for w in range(6)))
NIGHT = Schedule(id="s-night", code="NUIT", days=tuple(ScheduleDay(w, 1380, 420, 30) for w in range(6)), is_night=True)
NIGHT_WINDOW = (1260, 300)


def at(day: dt.date, hour: int, minute: int = 0) -> dt.datetime:
    return dt.datetime(day.year, day.month, day.day, hour, minute)


def test_a_day_shift_starts_and_ends_on_its_own_date():
    window = shift_window(DAY, AUG_3)
    assert (window.start, window.end, window.scheduled_minutes) == (at(AUG_3, 7), at(AUG_3, 15), 480)


def test_a_night_shift_belongs_to_the_day_it_starts():
    window = shift_window(NIGHT, AUG_3)
    assert window.work_date == AUG_3
    assert (window.start, window.end) == (at(AUG_3, 23), at(AUG_4, 7))
    assert window.scheduled_minutes == 450  # 8 h less the 30 min break


def test_a_weekday_without_a_line_is_a_rest_day():
    assert shift_window(DAY, dt.date(2026, 8, 9)) is None  # Sunday


@pytest.mark.parametrize(
    "days",
    [
        [ScheduleDay(0, 420, 900), ScheduleDay(0, 900, 1380)],  # Monday twice
        [ScheduleDay(0, 420, 420)],  # starts and ends at the same time
        [ScheduleDay(0, 420, 900, 480)],  # break as long as the shift
        [ScheduleDay(7, 420, 900)],  # no such weekday
        [ScheduleDay(0, 420, 1440)],  # 24:00 is not a time of day
        [],  # no working day at all
    ],
)
def test_schedule_validation_refuses_impossible_days(days):
    result = validate_schedule(code="X", name="X", days=days)
    assert isinstance(result, Err) and result.code == "INVALID_SCHEDULE" and result.message_fr


def test_a_valid_schedule_passes_and_needs_code_and_name():
    assert isinstance(validate_schedule(code="JOUR", name="Jour", days=list(DAY.days)), Ok)
    assert isinstance(validate_schedule(code=" ", name="Jour", days=list(DAY.days)), Err)


ROTATION = RotationPattern(id="r", anchor_date=AUG_3, schedule_ids=("s-morning", "s-evening", "s-night"))


def test_a_rotation_moves_one_step_per_week():
    wednesdays = [AUG_3 + dt.timedelta(weeks=w, days=2) for w in range(4)]
    assert [rotation_schedule_id(ROTATION, day) for day in wednesdays] == ["s-morning", "s-evening", "s-night", "s-morning"]


def test_a_team_offset_shifts_the_cycle():
    assert rotation_schedule_id(ROTATION, AUG_3 + dt.timedelta(days=2), offset_weeks=1) == "s-evening"


def test_weeks_before_the_anchor_wrap_backwards():
    assert rotation_schedule_id(ROTATION, dt.date(2026, 7, 29)) == "s-night"


def test_a_rotation_needs_a_monday_anchor_and_at_least_one_week():
    tuesday = validate_rotation(code="ROT", name="Rotation", anchor_date=AUG_4, schedule_ids=["a"])
    empty = validate_rotation(code="ROT", name="Rotation", anchor_date=AUG_3, schedule_ids=[])
    assert isinstance(tuesday, Err) and tuesday.code == "INVALID_ROTATION" and tuesday.message_fr
    assert isinstance(empty, Err) and empty.code == "INVALID_ROTATION"
    assert isinstance(validate_rotation(code="ROT", name="Rotation", anchor_date=AUG_3, schedule_ids=["a"]), Ok)


def test_resolution_uses_the_assignment_that_covers_the_day():
    assignments = [
        Assignment(id="a1", employee_id="e1", valid_from=dt.date(2026, 8, 1), valid_to=dt.date(2026, 8, 9), schedule_id="s-day"),
        Assignment(id="a2", employee_id="e1", valid_from=dt.date(2026, 8, 10), valid_to=None, rotation_pattern_id="r"),
    ]
    patterns = {"r": RotationPattern(id="r", anchor_date=dt.date(2026, 8, 10), schedule_ids=("s-night", "s-day"))}
    assert resolve_schedule_id(assignments, patterns, dt.date(2026, 8, 5)) == "s-day"
    assert resolve_schedule_id(assignments, patterns, dt.date(2026, 8, 11)) == "s-night"
    assert resolve_schedule_id(assignments, patterns, dt.date(2026, 8, 18)) == "s-day"
    assert resolve_schedule_id(assignments, patterns, dt.date(2026, 7, 31)) is None


def test_resolve_days_tells_unassigned_rest_and_working_days_apart():
    assignments = [Assignment(id="a1", employee_id="e1", valid_from=AUG_3, valid_to=None, schedule_id="s-day")]
    days = resolve_days(assignments=assignments, patterns={}, schedules={"s-day": DAY}, dates=date_range(dt.date(2026, 8, 2), dt.date(2026, 8, 9)))
    assert days[dt.date(2026, 8, 2)].assigned is False
    assert days[AUG_3].is_working_day and days[AUG_3].schedule_code == "JOUR"
    assert days[dt.date(2026, 8, 9)].assigned and not days[dt.date(2026, 8, 9)].is_working_day


def test_an_assignment_names_exactly_one_schedule_or_rotation():
    neither = validate_assignment(valid_from=AUG_3, valid_to=None, schedule_id=None, rotation_pattern_id=None, rotation_offset_weeks=0, others=[])
    both = validate_assignment(valid_from=AUG_3, valid_to=None, schedule_id="s", rotation_pattern_id="r", rotation_offset_weeks=0, others=[])
    backwards = validate_assignment(valid_from=AUG_4, valid_to=AUG_3, schedule_id="s", rotation_pattern_id=None, rotation_offset_weeks=0, others=[])
    for result in (neither, both, backwards):
        assert isinstance(result, Err) and result.code == "INVALID_ASSIGNMENT" and result.message_fr


def test_overlapping_assignments_are_refused_and_adjacent_ones_accepted():
    existing = [Assignment(id="a1", employee_id="e1", valid_from=dt.date(2026, 8, 1), valid_to=dt.date(2026, 8, 31), schedule_id="s-day")]
    overlapping = validate_assignment(valid_from=dt.date(2026, 8, 31), valid_to=None, schedule_id="s-night", rotation_pattern_id=None, rotation_offset_weeks=0, others=existing)
    adjacent = validate_assignment(valid_from=dt.date(2026, 9, 1), valid_to=None, schedule_id="s-night", rotation_pattern_id=None, rotation_offset_weeks=0, others=existing)
    assert isinstance(overlapping, Err) and overlapping.code == "ASSIGNMENT_OVERLAP"
    assert isinstance(adjacent, Ok)


@pytest.mark.parametrize(
    "start,end,expected",
    [
        (at(AUG_3, 23), at(AUG_4, 7), 360),  # the whole 23-05 part of a night shift
        (at(AUG_3, 7), at(AUG_3, 15), 0),
        (at(AUG_3, 15), at(AUG_3, 23), 120),  # 21:00-23:00
        (at(AUG_3, 4), at(AUG_3, 6), 60),  # the tail of the previous evening's window
    ],
)
def test_night_overlap_counts_the_minutes_inside_the_night_window(start, end, expected):
    assert night_overlap_minutes(start, end, *NIGHT_WINDOW) == expected


def test_a_night_window_that_does_not_cross_midnight_also_works():
    assert night_overlap_minutes(at(AUG_3, 0), at(AUG_3, 6), 0, 300) == 300


def test_holiday_validation_wants_a_two_letter_country_and_a_name():
    assert isinstance(validate_holiday(country_code="ML", name="Fête du Travail"), Ok)
    for country, name in (("MLI", "x"), ("ml", "x"), ("ML", " ")):
        result = validate_holiday(country_code=country, name=name)
        assert isinstance(result, Err) and result.code == "INVALID_HOLIDAY" and result.message_fr


def test_presence_settings_validation():
    ok = validate_presence_settings(night_start_minute=1260, night_end_minute=300, punch_attach_minutes=240, punch_dedupe_seconds=60, late_grace_minutes=0)
    empty = validate_presence_settings(night_start_minute=None, night_end_minute=None, punch_attach_minutes=None, punch_dedupe_seconds=None, late_grace_minutes=None)
    half = validate_presence_settings(night_start_minute=1260, night_end_minute=None, punch_attach_minutes=None, punch_dedupe_seconds=None, late_grace_minutes=None)
    same = validate_presence_settings(night_start_minute=300, night_end_minute=300, punch_attach_minutes=None, punch_dedupe_seconds=None, late_grace_minutes=None)
    negative = validate_presence_settings(night_start_minute=None, night_end_minute=None, punch_attach_minutes=-1, punch_dedupe_seconds=None, late_grace_minutes=None)
    assert isinstance(ok, Ok) and isinstance(empty, Ok)
    for result in (half, same, negative):
        assert isinstance(result, Err) and result.code == "INVALID_SETTINGS" and result.message_fr
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest modules/hr/domain/test_schedule.py -q`
Expected: collection error `ModuleNotFoundError: No module named 'modules.hr.domain.schedule'`.

- [ ] **Step 3: Write the implementation**

`backend/modules/hr/domain/schedule.py`:

```python
"""Work schedules, weekly rotations and the minute arithmetic presence is built on.

Pure: no database, no clock. Times of day are minutes after local midnight (0..1439).
A shift whose end is not after its start crosses midnight and belongs to the day it
starts on: the 23-07 shift of 3 August is 3 August's shift, although most of it is
worked on the 4th. Weekdays follow datetime.date.weekday(): Monday = 0 ... Sunday = 6.
"""
from __future__ import annotations

import datetime
import re
from dataclasses import dataclass

from core.domain.result import Err, Ok, Result

MINUTES_PER_DAY = 1440
ONE_DAY = datetime.timedelta(days=1)
_COUNTRY = re.compile(r"^[A-Z]{2}$")


def minutes_between(start: datetime.datetime, end: datetime.datetime) -> int:
    """Whole minutes from `start` to `end`, truncated toward zero (negative when `end` is earlier)."""
    return int((end - start).total_seconds() / 60)


def date_range(first: datetime.date, last: datetime.date) -> list[datetime.date]:
    return [first + datetime.timedelta(days=offset) for offset in range((last - first).days + 1)]


@dataclass(frozen=True)
class ScheduleDay:
    weekday: int
    start_minute: int
    end_minute: int
    break_minutes: int = 0

    @property
    def span_minutes(self) -> int:
        return (self.end_minute - self.start_minute) % MINUTES_PER_DAY


@dataclass(frozen=True)
class Schedule:
    id: str
    code: str
    days: tuple[ScheduleDay, ...]
    is_night: bool = False

    def day(self, weekday: int) -> ScheduleDay | None:
        return next((day for day in self.days if day.weekday == weekday), None)


@dataclass(frozen=True)
class ShiftWindow:
    work_date: datetime.date
    start: datetime.datetime
    end: datetime.datetime
    break_minutes: int
    schedule_id: str

    @property
    def scheduled_minutes(self) -> int:
        return minutes_between(self.start, self.end) - self.break_minutes


def shift_window(schedule: Schedule, work_date: datetime.date) -> ShiftWindow | None:
    """The shift `schedule` plans on `work_date`, or None on a rest day."""
    day = schedule.day(work_date.weekday())
    if day is None:
        return None
    start = datetime.datetime.combine(work_date, datetime.time()) + datetime.timedelta(minutes=day.start_minute)
    return ShiftWindow(
        work_date=work_date,
        start=start,
        end=start + datetime.timedelta(minutes=day.span_minutes),
        break_minutes=day.break_minutes,
        schedule_id=schedule.id,
    )


def validate_schedule(*, code: str, name: str, days: list[ScheduleDay]) -> Result[None]:
    if not code.strip() or not name.strip():
        return Err("INVALID_SCHEDULE", "schedule code and name are required", "le code et le nom de l'horaire sont obligatoires")
    if not days:
        return Err("INVALID_SCHEDULE", "a schedule needs at least one working day", "un horaire doit avoir au moins un jour travaillé")
    weekdays = [day.weekday for day in days]
    if len(set(weekdays)) != len(weekdays):
        return Err("INVALID_SCHEDULE", "a weekday appears twice in the schedule", "un jour de la semaine apparaît deux fois dans l'horaire")
    for day in days:
        if not 0 <= day.weekday <= 6:
            return Err("INVALID_SCHEDULE", "weekday must be between 0 (Monday) and 6 (Sunday)", "le jour doit être compris entre 0 (lundi) et 6 (dimanche)")
        if not (0 <= day.start_minute < MINUTES_PER_DAY and 0 <= day.end_minute < MINUTES_PER_DAY):
            return Err("INVALID_SCHEDULE", "start and end must be times of day", "le début et la fin doivent être des heures de la journée")
        if day.span_minutes == 0:
            return Err("INVALID_SCHEDULE", "a working day cannot start and end at the same time", "une journée de travail ne peut pas commencer et finir à la même heure")
        if not 0 <= day.break_minutes < day.span_minutes:
            return Err("INVALID_SCHEDULE", "the break must be shorter than the shift", "la pause doit être plus courte que le poste")
    return Ok(None)


@dataclass(frozen=True)
class RotationPattern:
    id: str
    anchor_date: datetime.date
    schedule_ids: tuple[str, ...]


def validate_rotation(*, code: str, name: str, anchor_date: datetime.date, schedule_ids: list[str]) -> Result[None]:
    if not code.strip() or not name.strip():
        return Err("INVALID_ROTATION", "rotation code and name are required", "le code et le nom du roulement sont obligatoires")
    if anchor_date.weekday() != 0:
        return Err("INVALID_ROTATION", "week 1 of a rotation starts on a Monday", "la semaine 1 d'un roulement commence un lundi")
    if not schedule_ids:
        return Err("INVALID_ROTATION", "a rotation needs at least one weekly schedule", "un roulement doit avoir au moins un horaire hebdomadaire")
    return Ok(None)


def rotation_schedule_id(pattern: RotationPattern, work_date: datetime.date, offset_weeks: int = 0) -> str:
    """The schedule of the week `work_date` falls in; `offset_weeks` staggers teams on one pattern."""
    monday = work_date - datetime.timedelta(days=work_date.weekday())
    weeks = (monday - pattern.anchor_date).days // 7
    return pattern.schedule_ids[(weeks + offset_weeks) % len(pattern.schedule_ids)]


@dataclass(frozen=True)
class Assignment:
    id: str
    employee_id: str
    valid_from: datetime.date
    valid_to: datetime.date | None
    schedule_id: str | None = None
    rotation_pattern_id: str | None = None
    rotation_offset_weeks: int = 0

    def covers(self, day: datetime.date) -> bool:
        return self.valid_from <= day and (self.valid_to is None or day <= self.valid_to)


def validate_assignment(
    *,
    valid_from: datetime.date,
    valid_to: datetime.date | None,
    schedule_id: str | None,
    rotation_pattern_id: str | None,
    rotation_offset_weeks: int,
    others: list[Assignment],
) -> Result[None]:
    if (schedule_id is None) == (rotation_pattern_id is None):
        return Err("INVALID_ASSIGNMENT", "give either a schedule or a rotation", "indiquez soit un horaire, soit un roulement")
    if valid_to is not None and valid_to < valid_from:
        return Err("INVALID_ASSIGNMENT", "the end date cannot precede the start date", "la date de fin ne peut pas précéder la date de début")
    if rotation_offset_weeks < 0:
        return Err("INVALID_ASSIGNMENT", "the team offset cannot be negative", "le décalage d'équipe ne peut pas être négatif")
    far = datetime.date.max
    for other in others:
        if other.valid_from <= (valid_to or far) and valid_from <= (other.valid_to or far):
            return Err(
                "ASSIGNMENT_OVERLAP",
                "the employee already has a schedule on part of these dates",
                "l'employé a déjà un horaire sur une partie de ces dates",
            )
    return Ok(None)


def resolve_schedule_id(assignments: list[Assignment], patterns: dict[str, RotationPattern], day: datetime.date) -> str | None:
    for assignment in assignments:
        if not assignment.covers(day):
            continue
        if assignment.schedule_id is not None:
            return assignment.schedule_id
        pattern = patterns.get(assignment.rotation_pattern_id or "")
        return rotation_schedule_id(pattern, day, assignment.rotation_offset_weeks) if pattern else None
    return None


@dataclass(frozen=True)
class ResolvedDay:
    work_date: datetime.date
    assigned: bool
    schedule_id: str | None = None
    schedule_code: str | None = None
    window: ShiftWindow | None = None

    @property
    def is_working_day(self) -> bool:
        return self.window is not None


def resolve_days(
    *,
    assignments: list[Assignment],
    patterns: dict[str, RotationPattern],
    schedules: dict[str, Schedule],
    dates: list[datetime.date],
) -> dict[datetime.date, ResolvedDay]:
    resolved: dict[datetime.date, ResolvedDay] = {}
    for day in dates:
        schedule_id = resolve_schedule_id(assignments, patterns, day)
        schedule = schedules.get(schedule_id) if schedule_id else None
        if schedule is None:
            resolved[day] = ResolvedDay(work_date=day, assigned=False)
        else:
            resolved[day] = ResolvedDay(
                work_date=day,
                assigned=True,
                schedule_id=schedule.id,
                schedule_code=schedule.code,
                window=shift_window(schedule, day),
            )
    return resolved


def night_overlap_minutes(
    start: datetime.datetime, end: datetime.datetime, night_start_minute: int, night_end_minute: int
) -> int:
    """Minutes of [start, end) inside the nightly window, which may cross midnight."""
    span = (night_end_minute - night_start_minute) % MINUTES_PER_DAY
    if end <= start or span == 0:
        return 0
    total = 0
    day = start.date() - ONE_DAY
    while datetime.datetime.combine(day, datetime.time()) < end:
        night_from = datetime.datetime.combine(day, datetime.time()) + datetime.timedelta(minutes=night_start_minute)
        night_to = night_from + datetime.timedelta(minutes=span)
        total += max(0, minutes_between(max(start, night_from), min(end, night_to)))
        day += ONE_DAY
    return total


def validate_holiday(*, country_code: str, name: str) -> Result[None]:
    if not _COUNTRY.match(country_code):
        return Err("INVALID_HOLIDAY", "the country is a two-letter code such as ML", "le pays est un code à deux lettres comme ML")
    if not name.strip():
        return Err("INVALID_HOLIDAY", "the holiday name is required", "le nom du jour férié est obligatoire")
    return Ok(None)


def validate_presence_settings(
    *,
    night_start_minute: int | None,
    night_end_minute: int | None,
    punch_attach_minutes: int | None,
    punch_dedupe_seconds: int | None,
    late_grace_minutes: int | None,
) -> Result[None]:
    if (night_start_minute is None) != (night_end_minute is None):
        return Err("INVALID_SETTINGS", "give both ends of the night-work window, or neither", "indiquez les deux bornes de la plage de nuit, ou aucune")
    for value in (night_start_minute, night_end_minute):
        if value is not None and not 0 <= value < MINUTES_PER_DAY:
            return Err("INVALID_SETTINGS", "the night-work window uses times of day", "la plage de nuit se compose d'heures de la journée")
    if night_start_minute is not None and night_start_minute == night_end_minute:
        return Err("INVALID_SETTINGS", "the night-work window cannot start and end at the same time", "la plage de nuit ne peut pas commencer et finir à la même heure")
    for value in (punch_attach_minutes, punch_dedupe_seconds, late_grace_minutes):
        if value is not None and value < 0:
            return Err("INVALID_SETTINGS", "settings cannot be negative", "les paramètres ne peuvent pas être négatifs")
    return Ok(None)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest modules/hr/domain/test_schedule.py -q`
Expected: all pass (0 skipped).

- [ ] **Step 5: Commit**

```bash
git add backend/modules/hr/domain/schedule.py backend/modules/hr/domain/test_schedule.py
git commit -m "feat(hr): schedule domain - shift windows, weekly rotations, night overlap

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Schedules, rotations, assignments, holidays and presence settings — tables, services, routes

**Files:**
- Create: `backend/modules/hr/migrations/0010_hr_work_schedules.sql`
- Create: `backend/modules/hr/migrations/0011_hr_holidays_presence_settings.sql`
- Create: `backend/modules/hr/api/schedule_service.py`
- Create: `backend/modules/hr/api/presence_router.py`
- Create: `backend/modules/hr/api/presence_testkit.py`
- Modify: `backend/app/main.py` (import + `include_router` right after `app.include_router(hr_router)`)
- Test: `backend/modules/hr/api/test_schedule_service_integration.py`, `backend/modules/hr/api/test_presence_router_routes.py`

**Interfaces:**
- Consumes: everything from Task 1; `core.audit.record_audit`; `core.tenancy.require_permission`; `core.domain.result.err_detail`.
- Produces:
  - `ScheduleService(connection)`: `list_schedules(*, tenant_id) -> list[dict]` (dict: `id, code, name, is_night, active, days: [{weekday, start_minute, end_minute, break_minutes}]`); `create_schedule(*, tenant_id, actor_id, code, name, is_night, days: list[dict]) -> Result[dict]`; `update_schedule(*, tenant_id, actor_id, schedule_id, code=None, name=None, is_night=None, active=None, days=None) -> Result[dict]`; `list_rotations(*, tenant_id)` (dict: `id, code, name, anchor_date (iso), active, schedule_ids`); `create_rotation(*, tenant_id, actor_id, code, name, anchor_date, schedule_ids)`; `update_rotation(*, tenant_id, actor_id, rotation_id, code=None, name=None, anchor_date=None, schedule_ids=None, active=None)`; `list_assignments(*, tenant_id, employee_id=None)` (dict: `id, employee_id, employee_no, full_name, schedule_id, schedule_code, rotation_pattern_id, rotation_code, rotation_offset_weeks, valid_from, valid_to`); `create_assignment(*, tenant_id, actor_id, employee_id, valid_from, valid_to=None, schedule_id=None, rotation_pattern_id=None, rotation_offset_weeks=0)`; `update_assignment(*, tenant_id, actor_id, assignment_id, valid_from=None, valid_to=None, clear_valid_to=False, schedule_id=None, rotation_pattern_id=None, rotation_offset_weeks=None)`; `resolve(*, tenant_id, employee_ids: list[str], date_from, date_to) -> dict[str, dict[date, ResolvedDay]]`.
  - `HolidayService(connection)`: `list_holidays(*, tenant_id, year: int | None = None)` (dict: `id, country_code, holiday_date, name, paid, confirmed`); `create_holiday(*, tenant_id, actor_id, country_code, holiday_date, name, paid=True, confirmed=False)`; `update_holiday(*, tenant_id, actor_id, holiday_id, holiday_date=None, name=None, paid=None, confirmed=None)`; `holiday_map(*, tenant_id, date_from, date_to) -> dict[date, bool]` (date → paid).
  - `PresenceSettingsService(connection)`: `get(*, tenant_id) -> dict` (keys `night_start_minute, night_end_minute, punch_attach_minutes, punch_dedupe_seconds, late_grace_minutes, confirmed, confirmed_at`); `update(*, tenant_id, actor_id, night_start_minute, night_end_minute, punch_attach_minutes, punch_dedupe_seconds, late_grace_minutes, confirm=False) -> Result[dict]`; `night_window(*, tenant_id) -> Result[tuple[int, int]]` (`PRESENCE_SETTINGS_MISSING` when unset).
  - `presence_router.router` (`APIRouter(prefix="/hr")`) with helpers `_fail(err)`, `_write(action)`, `_read(action)`, `_read_result(action)`, `_period(value)` used by later tasks.
  - `presence_testkit`: `TENANT`, `AUG_1`, `AUG_3`, `DAY_SHIFT`, `NIGHT_SHIFT`, `PresenceEnv`, `add_employee(db, *, employee_no, department, hire_date=date(2026,1,1), termination_date=None, badge_no=None) -> str`, `presence_row(db, employee_id, work_date) -> dict | None`, `insert_presence_row(db, *, employee_id, work_date, status, source, worked_minutes=0, leave_request_id=None)`, `close_month_directly(db, period)`, fixture `presence_env`.

- [ ] **Step 1: Write the migrations**

`backend/modules/hr/migrations/0010_hr_work_schedules.sql`:

```sql
-- Phase 2 (presence & leave): work schedules, weekly rotations and who works which.
-- A schedule day whose end is not after its start crosses midnight and belongs to the
-- day it starts on. weekday follows Python's date.weekday(): Monday = 0 ... Sunday = 6.
CREATE TABLE IF NOT EXISTS hr.work_schedules (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    is_night BOOLEAN NOT NULL DEFAULT FALSE,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, code)
);

CREATE TABLE IF NOT EXISTS hr.work_schedule_days (
    schedule_id TEXT NOT NULL REFERENCES hr.work_schedules (id) ON DELETE CASCADE,
    tenant_id TEXT NOT NULL,
    weekday SMALLINT NOT NULL CHECK (weekday BETWEEN 0 AND 6),
    start_minute SMALLINT NOT NULL CHECK (start_minute BETWEEN 0 AND 1439),
    end_minute SMALLINT NOT NULL CHECK (end_minute BETWEEN 0 AND 1439),
    break_minutes SMALLINT NOT NULL DEFAULT 0 CHECK (break_minutes >= 0),
    PRIMARY KEY (schedule_id, weekday)
);

-- Week 1 of a rotation starts on anchor_date (a Monday); each step lasts one week.
CREATE TABLE IF NOT EXISTS hr.rotation_patterns (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    anchor_date DATE NOT NULL CHECK (EXTRACT(ISODOW FROM anchor_date) = 1),
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, code)
);

CREATE TABLE IF NOT EXISTS hr.rotation_pattern_steps (
    pattern_id TEXT NOT NULL REFERENCES hr.rotation_patterns (id) ON DELETE CASCADE,
    tenant_id TEXT NOT NULL,
    position SMALLINT NOT NULL CHECK (position >= 0),
    schedule_id TEXT NOT NULL REFERENCES hr.work_schedules (id),
    PRIMARY KEY (pattern_id, position)
);

CREATE TABLE IF NOT EXISTS hr.schedule_assignments (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    employee_id TEXT NOT NULL REFERENCES hr.employees (id),
    schedule_id TEXT REFERENCES hr.work_schedules (id),
    rotation_pattern_id TEXT REFERENCES hr.rotation_patterns (id),
    rotation_offset_weeks SMALLINT NOT NULL DEFAULT 0 CHECK (rotation_offset_weeks >= 0),
    valid_from DATE NOT NULL,
    valid_to DATE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK ((schedule_id IS NULL) <> (rotation_pattern_id IS NULL)),
    CHECK (valid_to IS NULL OR valid_to >= valid_from)
);

CREATE INDEX IF NOT EXISTS hr_schedule_assignments_employee_idx
    ON hr.schedule_assignments (tenant_id, employee_id, valid_from);
```

`backend/modules/hr/migrations/0011_hr_holidays_presence_settings.sql`:

```sql
-- Public holidays per tenant and country. scripts/seed_hr_payroll.py seeds Mali with
-- confirmed = FALSE: religious holidays follow the moon and HR confirms each year's date.
CREATE TABLE IF NOT EXISTS hr.public_holidays (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    country_code TEXT NOT NULL CHECK (country_code ~ '^[A-Z]{2}$'),
    holiday_date DATE NOT NULL,
    name TEXT NOT NULL,
    paid BOOLEAN NOT NULL DEFAULT TRUE,
    confirmed BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, country_code, holiday_date)
);

-- One row per tenant, every value empty until HR sets it: the night-work window is
-- statutory and the punch values describe how the plant uses its clock. Nothing that
-- needs a value runs on an assumed one (PRESENCE_SETTINGS_MISSING instead).
CREATE TABLE IF NOT EXISTS hr.presence_settings (
    tenant_id TEXT PRIMARY KEY,
    night_start_minute SMALLINT CHECK (night_start_minute BETWEEN 0 AND 1439),
    night_end_minute SMALLINT CHECK (night_end_minute BETWEEN 0 AND 1439),
    punch_attach_minutes SMALLINT CHECK (punch_attach_minutes >= 0),
    punch_dedupe_seconds INTEGER CHECK (punch_dedupe_seconds >= 0),
    late_grace_minutes SMALLINT CHECK (late_grace_minutes >= 0),
    confirmed_by TEXT,
    confirmed_at TIMESTAMPTZ,
    updated_by TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

- [ ] **Step 2: Apply the migrations**

Run (from `backend/`): `DATABASE_URL=postgresql://erp:erp@localhost:5432/erp .venv/Scripts/python.exe -c "from core.migrations.runner import apply_all_migrations; apply_all_migrations()"`
Expected: no output, exit 0; `SELECT version FROM core.module_migrations WHERE module_name='hr'` lists `0010_hr_work_schedules.sql` and `0011_hr_holidays_presence_settings.sql`.

- [ ] **Step 3: Write the test kit (shared fixture, not a test file)**

`backend/modules/hr/api/presence_testkit.py`:

```python
"""Shared set-up for the phase-2 integration tests (presence, clock, leave, month close).

A test module imports the fixture by name:
    from modules.hr.api.presence_testkit import presence_env  # noqa: F401
Every write goes through the `db` fixture's connection, which rolls back after each test.
The minute values below are test inputs, not the plant's settings (those are rows HR
confirms; the dev seed writes drafts).
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass

import pytest
from ulid import ULID

from core.domain.result import Ok
from modules.hr.api.schedule_service import PresenceSettingsService, ScheduleService

TENANT = "integration-test-presence"
AUG_1 = datetime.date(2026, 8, 1)
AUG_3 = datetime.date(2026, 8, 3)  # a Monday
DAY_SHIFT = [{"weekday": w, "start_minute": 420, "end_minute": 900, "break_minutes": 0} for w in range(6)]
NIGHT_SHIFT = [{"weekday": w, "start_minute": 1380, "end_minute": 420, "break_minutes": 0} for w in range(6)]

_ROW_KEYS = (
    "status", "source", "scheduled_minutes", "worked_minutes", "late_minutes", "ot_minutes_day",
    "ot_minutes_night", "ot_minutes_rest_holiday", "night_minutes", "justified", "locked", "leave_request_id",
)


@dataclass(frozen=True)
class PresenceEnv:
    actor: str
    department: str
    day_schedule: str
    night_schedule: str
    day_worker: str
    night_worker: str


def add_employee(
    db,
    *,
    employee_no: str,
    department: str,
    hire_date: datetime.date = datetime.date(2026, 1, 1),
    termination_date: datetime.date | None = None,
    badge_no: str | None = None,
) -> str:
    employee_id = str(ULID())
    db.execute(
        """
        INSERT INTO hr.employees (id, tenant_id, employee_no, first_name, last_name, department_id,
                                  hire_date, termination_date, badge_no)
        VALUES (%s, %s, %s, 'Test', %s, %s, %s, %s, %s)
        """,
        (employee_id, TENANT, employee_no, employee_no, department, hire_date, termination_date, badge_no),
    )
    return employee_id


def presence_row(db, employee_id: str, work_date: datetime.date) -> dict | None:
    row = db.execute(
        f"SELECT {', '.join(_ROW_KEYS)} FROM hr.presence_days WHERE tenant_id = %s AND employee_id = %s AND work_date = %s",
        (TENANT, employee_id, work_date),
    ).fetchone()
    return dict(zip(_ROW_KEYS, row)) if row else None


def insert_presence_row(
    db,
    *,
    employee_id: str,
    work_date: datetime.date,
    status: str,
    source: str,
    worked_minutes: int = 0,
    leave_request_id: str | None = None,
) -> None:
    db.execute(
        """
        INSERT INTO hr.presence_days (id, tenant_id, employee_id, work_date, status, source, worked_minutes, leave_request_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (str(ULID()), TENANT, employee_id, work_date, status, source, worked_minutes, leave_request_id),
    )


def close_month_directly(db, period: datetime.date) -> None:
    db.execute(
        """
        INSERT INTO hr.presence_months (tenant_id, period, status) VALUES (%s, %s, 'closed')
        ON CONFLICT (tenant_id, period) DO UPDATE SET status = 'closed'
        """,
        (TENANT, period),
    )


@pytest.fixture
def presence_env(db) -> PresenceEnv:
    actor = str(ULID())
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (actor, TENANT, f"{actor}@test.local"),
    )
    department = str(ULID())
    db.execute(
        "INSERT INTO hr.departments (id, tenant_id, code, name) VALUES (%s, %s, 'PROD', 'Production')",
        (department, TENANT),
    )
    settings = PresenceSettingsService(db).update(
        tenant_id=TENANT, actor_id=actor, night_start_minute=1260, night_end_minute=300,
        punch_attach_minutes=240, punch_dedupe_seconds=60, late_grace_minutes=0,
    )
    assert isinstance(settings, Ok), settings
    schedules = ScheduleService(db)
    day = schedules.create_schedule(tenant_id=TENANT, actor_id=actor, code="JOUR", name="Jour 07-15", is_night=False, days=DAY_SHIFT)
    night = schedules.create_schedule(tenant_id=TENANT, actor_id=actor, code="NUIT", name="Nuit 23-07", is_night=True, days=NIGHT_SHIFT)
    assert isinstance(day, Ok) and isinstance(night, Ok)
    day_worker = add_employee(db, employee_no="P-001", department=department, badge_no="B001")
    night_worker = add_employee(db, employee_no="P-002", department=department, badge_no="B002")
    for employee_id, schedule_id in ((day_worker, day.value["id"]), (night_worker, night.value["id"])):
        assigned = schedules.create_assignment(
            tenant_id=TENANT, actor_id=actor, employee_id=employee_id,
            valid_from=datetime.date(2026, 1, 1), schedule_id=schedule_id,
        )
        assert isinstance(assigned, Ok), assigned
    return PresenceEnv(
        actor=actor, department=department, day_schedule=day.value["id"], night_schedule=night.value["id"],
        day_worker=day_worker, night_worker=night_worker,
    )
```

- [ ] **Step 4: Write the failing integration tests**

`backend/modules/hr/api/test_schedule_service_integration.py`:

```python
"""Schedules, rotations, assignments, holidays and presence settings against a real database."""
from __future__ import annotations

import datetime

from ulid import ULID

from core.domain.result import Err, Ok
from modules.hr.api.presence_testkit import AUG_3, DAY_SHIFT, TENANT, add_employee, presence_env  # noqa: F401
from modules.hr.api.schedule_service import HolidayService, PresenceSettingsService, ScheduleService

EVENING_SHIFT = [{"weekday": w, "start_minute": 900, "end_minute": 1380, "break_minutes": 0} for w in range(6)]


def _audits(db, action: str) -> int:
    return db.execute("SELECT count(*) FROM core.audit_log WHERE tenant_id = %s AND action = %s", (TENANT, action)).fetchone()[0]


def test_a_schedule_is_listed_with_its_days_and_edited_with_an_audit_trail(db, presence_env):
    service = ScheduleService(db)
    listed = {s["code"]: s for s in service.list_schedules(tenant_id=TENANT)}
    assert [d["weekday"] for d in listed["JOUR"]["days"]] == [0, 1, 2, 3, 4, 5]
    updated = service.update_schedule(
        tenant_id=TENANT, actor_id=presence_env.actor, schedule_id=presence_env.day_schedule, name="Jour",
        days=[{"weekday": 0, "start_minute": 480, "end_minute": 960, "break_minutes": 30}],
    )
    assert isinstance(updated, Ok)
    assert updated.value["name"] == "Jour"
    assert updated.value["days"] == [{"weekday": 0, "start_minute": 480, "end_minute": 960, "break_minutes": 30}]
    assert _audits(db, "work_schedule.created") == 2 and _audits(db, "work_schedule.updated") == 1


def test_a_schedule_code_is_unique_per_tenant(db, presence_env):
    result = ScheduleService(db).create_schedule(tenant_id=TENANT, actor_id=presence_env.actor, code="JOUR", name="Autre", is_night=False, days=DAY_SHIFT)
    assert isinstance(result, Err) and result.code == "DUPLICATE_CODE" and result.message_fr


def test_a_rotation_resolves_week_by_week_and_a_night_stays_on_its_start_day(db, presence_env):
    service = ScheduleService(db)
    evening = service.create_schedule(tenant_id=TENANT, actor_id=presence_env.actor, code="SOIR", name="Soir 15-23", is_night=False, days=EVENING_SHIFT)
    rotation = service.create_rotation(
        tenant_id=TENANT, actor_id=presence_env.actor, code="ROT3", name="3x8", anchor_date=AUG_3,
        schedule_ids=[presence_env.day_schedule, evening.value["id"], presence_env.night_schedule],
    )
    assert isinstance(rotation, Ok) and rotation.value["schedule_ids"][1] == evening.value["id"]
    worker = add_employee(db, employee_no="P-010", department=presence_env.department)
    assigned = service.create_assignment(
        tenant_id=TENANT, actor_id=presence_env.actor, employee_id=worker, valid_from=AUG_3,
        rotation_pattern_id=rotation.value["id"], rotation_offset_weeks=1,
    )
    assert isinstance(assigned, Ok) and assigned.value["rotation_code"] == "ROT3"
    days = service.resolve(tenant_id=TENANT, employee_ids=[worker], date_from=AUG_3, date_to=AUG_3 + datetime.timedelta(days=20))[worker]
    mondays = [AUG_3 + datetime.timedelta(weeks=w) for w in range(3)]
    assert [days[monday].schedule_code for monday in mondays] == ["SOIR", "NUIT", "JOUR"]
    night = days[mondays[1]].window
    assert night.work_date == mondays[1] and night.end.date() == mondays[1] + datetime.timedelta(days=1)


def test_a_rotation_anchor_must_be_a_monday(db, presence_env):
    result = ScheduleService(db).create_rotation(
        tenant_id=TENANT, actor_id=presence_env.actor, code="ROT", name="Rotation",
        anchor_date=AUG_3 + datetime.timedelta(days=1), schedule_ids=[presence_env.day_schedule],
    )
    assert isinstance(result, Err) and result.code == "INVALID_ROTATION"


def test_overlaps_are_refused_and_an_assignment_can_switch_to_a_rotation_and_back_to_open_ended(db, presence_env):
    service = ScheduleService(db)
    overlap = service.create_assignment(tenant_id=TENANT, actor_id=presence_env.actor, employee_id=presence_env.day_worker, valid_from=AUG_3, schedule_id=presence_env.night_schedule)
    assert isinstance(overlap, Err) and overlap.code == "ASSIGNMENT_OVERLAP"
    current = service.list_assignments(tenant_id=TENANT, employee_id=presence_env.day_worker)[0]
    rotation = service.create_rotation(
        tenant_id=TENANT, actor_id=presence_env.actor, code="ROT2", name="2x8", anchor_date=AUG_3,
        schedule_ids=[presence_env.day_schedule, presence_env.night_schedule],
    ).value
    switched = service.update_assignment(tenant_id=TENANT, actor_id=presence_env.actor, assignment_id=current["id"], rotation_pattern_id=rotation["id"])
    assert isinstance(switched, Ok) and switched.value["schedule_id"] is None and switched.value["rotation_code"] == "ROT2"
    ended = service.update_assignment(tenant_id=TENANT, actor_id=presence_env.actor, assignment_id=current["id"], valid_to=datetime.date(2026, 8, 31))
    reopened = service.update_assignment(tenant_id=TENANT, actor_id=presence_env.actor, assignment_id=current["id"], clear_valid_to=True)
    assert ended.value["valid_to"] == "2026-08-31" and reopened.value["valid_to"] is None
    assert _audits(db, "schedule_assignment.updated") == 3


def test_public_holidays_are_listed_by_year_unique_per_date_and_confirmable(db, presence_env):
    holidays = HolidayService(db)
    created = holidays.create_holiday(tenant_id=TENANT, actor_id=presence_env.actor, country_code="ml", holiday_date=datetime.date(2026, 9, 22), name="Fête de l'Indépendance")
    assert isinstance(created, Ok) and created.value["country_code"] == "ML" and created.value["confirmed"] is False
    duplicate = holidays.create_holiday(tenant_id=TENANT, actor_id=presence_env.actor, country_code="ML", holiday_date=datetime.date(2026, 9, 22), name="Doublon")
    assert isinstance(duplicate, Err) and duplicate.code == "DUPLICATE_HOLIDAY" and duplicate.message_fr
    confirmed = holidays.update_holiday(tenant_id=TENANT, actor_id=presence_env.actor, holiday_id=created.value["id"], confirmed=True)
    assert isinstance(confirmed, Ok) and confirmed.value["confirmed"] is True
    assert [h["name"] for h in holidays.list_holidays(tenant_id=TENANT, year=2026)] == ["Fête de l'Indépendance"]
    assert holidays.list_holidays(tenant_id=TENANT, year=2025) == []
    september = holidays.holiday_map(tenant_id=TENANT, date_from=datetime.date(2026, 9, 1), date_to=datetime.date(2026, 9, 30))
    assert september == {datetime.date(2026, 9, 22): True}


def test_presence_settings_start_empty_and_a_change_clears_the_confirmation(db):
    tenant = "integration-test-settings"
    actor = str(ULID())
    db.execute("INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')", (actor, tenant, f"{actor}@test.local"))
    settings = PresenceSettingsService(db)
    assert settings.get(tenant_id=tenant)["night_start_minute"] is None
    missing = settings.night_window(tenant_id=tenant)
    assert isinstance(missing, Err) and missing.code == "PRESENCE_SETTINGS_MISSING" and missing.message_fr
    confirmed = settings.update(tenant_id=tenant, actor_id=actor, night_start_minute=1260, night_end_minute=300, punch_attach_minutes=240, punch_dedupe_seconds=None, late_grace_minutes=None, confirm=True)
    assert isinstance(confirmed, Ok) and confirmed.value["confirmed"] is True
    changed = settings.update(tenant_id=tenant, actor_id=actor, night_start_minute=1260, night_end_minute=300, punch_attach_minutes=240, punch_dedupe_seconds=None, late_grace_minutes=5)
    assert changed.value["confirmed"] is False and changed.value["late_grace_minutes"] == 5
    assert settings.night_window(tenant_id=tenant).value == (1260, 300)


def test_half_a_night_window_is_refused(db, presence_env):
    result = PresenceSettingsService(db).update(tenant_id=TENANT, actor_id=presence_env.actor, night_start_minute=1260, night_end_minute=None, punch_attach_minutes=None, punch_dedupe_seconds=None, late_grace_minutes=None)
    assert isinstance(result, Err) and result.code == "INVALID_SETTINGS"
```

`backend/modules/hr/api/test_presence_router_routes.py`:

```python
"""Every phase-2 route exists and is guarded by the permission the plan names. No database."""
from __future__ import annotations

from modules.hr.api.presence_router import router


def _permission_of(route) -> str | None:
    # require_permission(code) returns a closure over `code`; read it back from the dependency.
    for dependency in route.dependant.dependencies:
        for cell in getattr(dependency.call, "__closure__", None) or ():
            value = cell.cell_contents
            if isinstance(value, str) and value.startswith("hr."):
                return value
    return None


def _routes() -> dict[tuple[str, str], str | None]:
    return {(method, route.path): _permission_of(route) for route in router.routes for method in route.methods}


def test_schedule_routes_and_their_permissions():
    expected = {
        ("GET", "/hr/schedules"): "hr.view_presence",
        ("POST", "/hr/schedules"): "hr.manage_presence",
        ("PATCH", "/hr/schedules/{schedule_id}"): "hr.admin_presence",
        ("GET", "/hr/rotation-patterns"): "hr.view_presence",
        ("POST", "/hr/rotation-patterns"): "hr.manage_presence",
        ("PATCH", "/hr/rotation-patterns/{rotation_id}"): "hr.admin_presence",
        ("GET", "/hr/schedule-assignments"): "hr.view_presence",
        ("POST", "/hr/schedule-assignments"): "hr.manage_presence",
        ("PATCH", "/hr/schedule-assignments/{assignment_id}"): "hr.admin_presence",
        ("GET", "/hr/public-holidays"): "hr.view_presence",
        ("POST", "/hr/public-holidays"): "hr.manage_presence",
        ("PATCH", "/hr/public-holidays/{holiday_id}"): "hr.admin_presence",
        ("GET", "/hr/presence/settings"): "hr.view_presence",
        ("PUT", "/hr/presence/settings"): "hr.admin_presence",
    }
    routes = _routes()
    assert {key: routes.get(key) for key in expected} == expected
```

- [ ] **Step 5: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest modules/hr/api/test_schedule_service_integration.py modules/hr/api/test_presence_router_routes.py -q`
Expected: collection errors (`No module named 'modules.hr.api.schedule_service'` / `presence_router`).

- [ ] **Step 6: Write the services**

`backend/modules/hr/api/schedule_service.py`:

```python
"""Schedules, weekly rotations, schedule assignments, public holidays and presence settings.

Every mutation takes the acting user and writes its audit row in the caller's transaction;
the router commits. Nothing here holds a statutory or plant value: they are rows.
"""
from __future__ import annotations

import datetime

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.hr.domain.schedule import (
    Assignment,
    ResolvedDay,
    RotationPattern,
    Schedule,
    ScheduleDay,
    date_range,
    resolve_days,
    validate_assignment,
    validate_holiday,
    validate_presence_settings,
    validate_rotation,
    validate_schedule,
)

SCHEDULE_NOT_FOUND = Err("NOT_FOUND", "schedule not found", "horaire introuvable")
ROTATION_NOT_FOUND = Err("NOT_FOUND", "rotation not found", "roulement introuvable")
ASSIGNMENT_NOT_FOUND = Err("NOT_FOUND", "schedule assignment not found", "affectation d'horaire introuvable")
EMPLOYEE_NOT_FOUND = Err("NOT_FOUND", "employee not found", "employé introuvable")
HOLIDAY_NOT_FOUND = Err("NOT_FOUND", "public holiday not found", "jour férié introuvable")
SETTINGS_MISSING = Err(
    "PRESENCE_SETTINGS_MISSING",
    "the presence settings are not set (HR > Schedules & holidays > Settings)",
    "les paramètres de présence ne sont pas renseignés (RH > Horaires et jours fériés > Paramètres)",
)
_SETTING_FIELDS = ("night_start_minute", "night_end_minute", "punch_attach_minutes", "punch_dedupe_seconds", "late_grace_minutes")


def _schedule_days(items: list[dict]) -> list[ScheduleDay]:
    return [
        ScheduleDay(int(item["weekday"]), int(item["start_minute"]), int(item["end_minute"]), int(item.get("break_minutes") or 0))
        for item in items
    ]


class ScheduleService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    # ---- schedules ----------------------------------------------------------------
    def list_schedules(self, *, tenant_id: str) -> list[dict]:
        rows = self.connection.execute(
            """
            SELECT s.id, s.code, s.name, s.is_night, s.active,
                   COALESCE(
                       json_agg(
                           json_build_object('weekday', d.weekday, 'start_minute', d.start_minute,
                                             'end_minute', d.end_minute, 'break_minutes', d.break_minutes)
                           ORDER BY d.weekday
                       ) FILTER (WHERE d.weekday IS NOT NULL),
                       '[]'::json
                   )
            FROM hr.work_schedules s
            LEFT JOIN hr.work_schedule_days d ON d.schedule_id = s.id
            WHERE s.tenant_id = %s
            GROUP BY s.id
            ORDER BY s.code
            """,
            (tenant_id,),
        ).fetchall()
        return [{"id": r[0], "code": r[1], "name": r[2], "is_night": r[3], "active": r[4], "days": r[5]} for r in rows]

    def _schedule(self, tenant_id: str, schedule_id: str) -> dict | None:
        return next((s for s in self.list_schedules(tenant_id=tenant_id) if s["id"] == schedule_id), None)

    def create_schedule(self, *, tenant_id: str, actor_id: str, code: str, name: str, is_night: bool, days: list[dict]) -> Result[dict]:
        schedule_days = _schedule_days(days)
        validation = validate_schedule(code=code, name=name, days=schedule_days)
        if isinstance(validation, Err):
            return validation
        if self._code_taken("hr.work_schedules", tenant_id, code.strip()):
            return Err("DUPLICATE_CODE", f"schedule code {code.strip()} already exists", f"le code d'horaire {code.strip()} existe déjà")
        schedule_id = str(ULID())
        self.connection.execute(
            "INSERT INTO hr.work_schedules (id, tenant_id, code, name, is_night) VALUES (%s, %s, %s, %s, %s)",
            (schedule_id, tenant_id, code.strip(), name.strip(), is_night),
        )
        self._write_days(tenant_id, schedule_id, schedule_days)
        record_audit(
            self.connection, tenant_id=tenant_id, actor_id=actor_id, action="work_schedule.created",
            entity_type="work_schedule", entity_id=schedule_id, payload={"code": code.strip(), "days": days},
        )
        return Ok(self._schedule(tenant_id, schedule_id))

    def update_schedule(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        schedule_id: str,
        code: str | None = None,
        name: str | None = None,
        is_night: bool | None = None,
        active: bool | None = None,
        days: list[dict] | None = None,
    ) -> Result[dict]:
        current = self._schedule(tenant_id, schedule_id)
        if current is None:
            return SCHEDULE_NOT_FOUND
        new_code = code.strip() if code is not None else current["code"]
        new_name = name.strip() if name is not None else current["name"]
        schedule_days = _schedule_days(days if days is not None else current["days"])
        validation = validate_schedule(code=new_code, name=new_name, days=schedule_days)
        if isinstance(validation, Err):
            return validation
        if new_code != current["code"] and self._code_taken("hr.work_schedules", tenant_id, new_code):
            return Err("DUPLICATE_CODE", f"schedule code {new_code} already exists", f"le code d'horaire {new_code} existe déjà")
        self.connection.execute(
            "UPDATE hr.work_schedules SET code = %s, name = %s, is_night = %s, active = %s WHERE id = %s AND tenant_id = %s",
            (
                new_code, new_name,
                is_night if is_night is not None else current["is_night"],
                active if active is not None else current["active"],
                schedule_id, tenant_id,
            ),
        )
        if days is not None:
            self.connection.execute("DELETE FROM hr.work_schedule_days WHERE schedule_id = %s", (schedule_id,))
            self._write_days(tenant_id, schedule_id, schedule_days)
        changes = {k: v for k, v in {"code": code, "name": name, "is_night": is_night, "active": active, "days": days}.items() if v is not None}
        record_audit(
            self.connection, tenant_id=tenant_id, actor_id=actor_id, action="work_schedule.updated",
            entity_type="work_schedule", entity_id=schedule_id, payload=changes,
        )
        return Ok(self._schedule(tenant_id, schedule_id))

    def _write_days(self, tenant_id: str, schedule_id: str, days: list[ScheduleDay]) -> None:
        for day in days:
            self.connection.execute(
                """
                INSERT INTO hr.work_schedule_days (schedule_id, tenant_id, weekday, start_minute, end_minute, break_minutes)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (schedule_id, tenant_id, day.weekday, day.start_minute, day.end_minute, day.break_minutes),
            )

    def _code_taken(self, table: str, tenant_id: str, code: str) -> bool:
        # `table` is always one of this module's own table names, never user input.
        return self.connection.execute(f"SELECT 1 FROM {table} WHERE tenant_id = %s AND code = %s", (tenant_id, code)).fetchone() is not None

    def _missing_schedules(self, tenant_id: str, schedule_ids: list[str]) -> bool:
        wanted = set(schedule_ids)
        found = {
            row[0]
            for row in self.connection.execute(
                "SELECT id FROM hr.work_schedules WHERE tenant_id = %s AND id = ANY(%s)", (tenant_id, list(wanted))
            ).fetchall()
        }
        return found != wanted

    # ---- rotations ----------------------------------------------------------------
    def list_rotations(self, *, tenant_id: str) -> list[dict]:
        rows = self.connection.execute(
            """
            SELECT p.id, p.code, p.name, p.anchor_date, p.active,
                   COALESCE(array_agg(st.schedule_id ORDER BY st.position) FILTER (WHERE st.schedule_id IS NOT NULL), '{}')
            FROM hr.rotation_patterns p
            LEFT JOIN hr.rotation_pattern_steps st ON st.pattern_id = p.id
            WHERE p.tenant_id = %s
            GROUP BY p.id
            ORDER BY p.code
            """,
            (tenant_id,),
        ).fetchall()
        return [
            {"id": r[0], "code": r[1], "name": r[2], "anchor_date": r[3].isoformat(), "active": r[4], "schedule_ids": list(r[5])}
            for r in rows
        ]

    def _rotation(self, tenant_id: str, rotation_id: str) -> dict | None:
        return next((r for r in self.list_rotations(tenant_id=tenant_id) if r["id"] == rotation_id), None)

    def create_rotation(
        self, *, tenant_id: str, actor_id: str, code: str, name: str, anchor_date: datetime.date, schedule_ids: list[str]
    ) -> Result[dict]:
        validation = validate_rotation(code=code, name=name, anchor_date=anchor_date, schedule_ids=schedule_ids)
        if isinstance(validation, Err):
            return validation
        if self._missing_schedules(tenant_id, schedule_ids):
            return SCHEDULE_NOT_FOUND
        if self._code_taken("hr.rotation_patterns", tenant_id, code.strip()):
            return Err("DUPLICATE_CODE", f"rotation code {code.strip()} already exists", f"le code de roulement {code.strip()} existe déjà")
        rotation_id = str(ULID())
        self.connection.execute(
            "INSERT INTO hr.rotation_patterns (id, tenant_id, code, name, anchor_date) VALUES (%s, %s, %s, %s, %s)",
            (rotation_id, tenant_id, code.strip(), name.strip(), anchor_date),
        )
        self._write_steps(tenant_id, rotation_id, schedule_ids)
        record_audit(
            self.connection, tenant_id=tenant_id, actor_id=actor_id, action="rotation_pattern.created",
            entity_type="rotation_pattern", entity_id=rotation_id,
            payload={"code": code.strip(), "anchor_date": anchor_date.isoformat(), "schedule_ids": schedule_ids},
        )
        return Ok(self._rotation(tenant_id, rotation_id))

    def update_rotation(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        rotation_id: str,
        code: str | None = None,
        name: str | None = None,
        anchor_date: datetime.date | None = None,
        schedule_ids: list[str] | None = None,
        active: bool | None = None,
    ) -> Result[dict]:
        current = self._rotation(tenant_id, rotation_id)
        if current is None:
            return ROTATION_NOT_FOUND
        new_code = code.strip() if code is not None else current["code"]
        new_name = name.strip() if name is not None else current["name"]
        new_anchor = anchor_date or datetime.date.fromisoformat(current["anchor_date"])
        new_steps = schedule_ids if schedule_ids is not None else current["schedule_ids"]
        validation = validate_rotation(code=new_code, name=new_name, anchor_date=new_anchor, schedule_ids=new_steps)
        if isinstance(validation, Err):
            return validation
        if self._missing_schedules(tenant_id, new_steps):
            return SCHEDULE_NOT_FOUND
        if new_code != current["code"] and self._code_taken("hr.rotation_patterns", tenant_id, new_code):
            return Err("DUPLICATE_CODE", f"rotation code {new_code} already exists", f"le code de roulement {new_code} existe déjà")
        self.connection.execute(
            "UPDATE hr.rotation_patterns SET code = %s, name = %s, anchor_date = %s, active = %s WHERE id = %s AND tenant_id = %s",
            (new_code, new_name, new_anchor, active if active is not None else current["active"], rotation_id, tenant_id),
        )
        if schedule_ids is not None:
            self.connection.execute("DELETE FROM hr.rotation_pattern_steps WHERE pattern_id = %s", (rotation_id,))
            self._write_steps(tenant_id, rotation_id, schedule_ids)
        changes = {
            k: v
            for k, v in {
                "code": code, "name": name, "anchor_date": anchor_date.isoformat() if anchor_date else None,
                "schedule_ids": schedule_ids, "active": active,
            }.items()
            if v is not None
        }
        record_audit(
            self.connection, tenant_id=tenant_id, actor_id=actor_id, action="rotation_pattern.updated",
            entity_type="rotation_pattern", entity_id=rotation_id, payload=changes,
        )
        return Ok(self._rotation(tenant_id, rotation_id))

    def _write_steps(self, tenant_id: str, rotation_id: str, schedule_ids: list[str]) -> None:
        for position, schedule_id in enumerate(schedule_ids):
            self.connection.execute(
                "INSERT INTO hr.rotation_pattern_steps (pattern_id, tenant_id, position, schedule_id) VALUES (%s, %s, %s, %s)",
                (rotation_id, tenant_id, position, schedule_id),
            )

    # ---- assignments --------------------------------------------------------------
    def list_assignments(self, *, tenant_id: str, employee_id: str | None = None) -> list[dict]:
        params: list[object] = [tenant_id]
        clause = ""
        if employee_id:
            clause = " AND a.employee_id = %s"
            params.append(employee_id)
        rows = self.connection.execute(
            f"""
            SELECT a.id, a.employee_id, e.employee_no, e.first_name || ' ' || e.last_name,
                   a.schedule_id, s.code, a.rotation_pattern_id, p.code, a.rotation_offset_weeks, a.valid_from, a.valid_to
            FROM hr.schedule_assignments a
            JOIN hr.employees e ON e.id = a.employee_id
            LEFT JOIN hr.work_schedules s ON s.id = a.schedule_id
            LEFT JOIN hr.rotation_patterns p ON p.id = a.rotation_pattern_id
            WHERE a.tenant_id = %s{clause}
            ORDER BY e.employee_no, a.valid_from
            """,
            params,
        ).fetchall()
        return [
            {
                "id": r[0], "employee_id": r[1], "employee_no": r[2], "full_name": r[3],
                "schedule_id": r[4], "schedule_code": r[5], "rotation_pattern_id": r[6], "rotation_code": r[7],
                "rotation_offset_weeks": r[8], "valid_from": r[9].isoformat(), "valid_to": r[10].isoformat() if r[10] else None,
            }
            for r in rows
        ]

    def _one_assignment(self, tenant_id: str, assignment_id: str) -> dict | None:
        return next((a for a in self.list_assignments(tenant_id=tenant_id) if a["id"] == assignment_id), None)

    def _check_target(self, tenant_id: str, schedule_id: str | None, rotation_pattern_id: str | None) -> Result[None]:
        if schedule_id and self._missing_schedules(tenant_id, [schedule_id]):
            return SCHEDULE_NOT_FOUND
        if rotation_pattern_id and self._rotation(tenant_id, rotation_pattern_id) is None:
            return ROTATION_NOT_FOUND
        return Ok(None)

    def create_assignment(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        employee_id: str,
        valid_from: datetime.date,
        valid_to: datetime.date | None = None,
        schedule_id: str | None = None,
        rotation_pattern_id: str | None = None,
        rotation_offset_weeks: int = 0,
    ) -> Result[dict]:
        if self.connection.execute("SELECT 1 FROM hr.employees WHERE id = %s AND tenant_id = %s", (employee_id, tenant_id)).fetchone() is None:
            return EMPLOYEE_NOT_FOUND
        target = self._check_target(tenant_id, schedule_id, rotation_pattern_id)
        if isinstance(target, Err):
            return target
        validation = validate_assignment(
            valid_from=valid_from, valid_to=valid_to, schedule_id=schedule_id, rotation_pattern_id=rotation_pattern_id,
            rotation_offset_weeks=rotation_offset_weeks, others=self._assignments(tenant_id, [employee_id]).get(employee_id, []),
        )
        if isinstance(validation, Err):
            return validation
        assignment_id = str(ULID())
        self.connection.execute(
            """
            INSERT INTO hr.schedule_assignments (id, tenant_id, employee_id, schedule_id, rotation_pattern_id,
                                                 rotation_offset_weeks, valid_from, valid_to)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (assignment_id, tenant_id, employee_id, schedule_id, rotation_pattern_id, rotation_offset_weeks, valid_from, valid_to),
        )
        record_audit(
            self.connection, tenant_id=tenant_id, actor_id=actor_id, action="schedule_assignment.created",
            entity_type="schedule_assignment", entity_id=assignment_id,
            payload={
                "employee_id": employee_id, "schedule_id": schedule_id, "rotation_pattern_id": rotation_pattern_id,
                "rotation_offset_weeks": rotation_offset_weeks, "valid_from": valid_from.isoformat(),
                "valid_to": valid_to.isoformat() if valid_to else None,
            },
        )
        return Ok(self._one_assignment(tenant_id, assignment_id))

    def update_assignment(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        assignment_id: str,
        valid_from: datetime.date | None = None,
        valid_to: datetime.date | None = None,
        clear_valid_to: bool = False,
        schedule_id: str | None = None,
        rotation_pattern_id: str | None = None,
        rotation_offset_weeks: int | None = None,
    ) -> Result[dict]:
        current = self._one_assignment(tenant_id, assignment_id)
        if current is None:
            return ASSIGNMENT_NOT_FOUND
        new_schedule, new_rotation = current["schedule_id"], current["rotation_pattern_id"]
        if schedule_id is not None and rotation_pattern_id is not None:
            new_schedule, new_rotation = schedule_id, rotation_pattern_id  # refused below by the domain
        elif schedule_id is not None:
            new_schedule, new_rotation = schedule_id, None
        elif rotation_pattern_id is not None:
            new_schedule, new_rotation = None, rotation_pattern_id
        new_from = valid_from or datetime.date.fromisoformat(current["valid_from"])
        stored_to = datetime.date.fromisoformat(current["valid_to"]) if current["valid_to"] else None
        new_to = None if clear_valid_to else (valid_to if valid_to is not None else stored_to)
        new_offset = rotation_offset_weeks if rotation_offset_weeks is not None else current["rotation_offset_weeks"]
        target = self._check_target(tenant_id, new_schedule, new_rotation)
        if isinstance(target, Err):
            return target
        others = [a for a in self._assignments(tenant_id, [current["employee_id"]]).get(current["employee_id"], []) if a.id != assignment_id]
        validation = validate_assignment(
            valid_from=new_from, valid_to=new_to, schedule_id=new_schedule, rotation_pattern_id=new_rotation,
            rotation_offset_weeks=new_offset, others=others,
        )
        if isinstance(validation, Err):
            return validation
        self.connection.execute(
            """
            UPDATE hr.schedule_assignments
            SET schedule_id = %s, rotation_pattern_id = %s, rotation_offset_weeks = %s, valid_from = %s, valid_to = %s
            WHERE id = %s AND tenant_id = %s
            """,
            (new_schedule, new_rotation, new_offset, new_from, new_to, assignment_id, tenant_id),
        )
        record_audit(
            self.connection, tenant_id=tenant_id, actor_id=actor_id, action="schedule_assignment.updated",
            entity_type="schedule_assignment", entity_id=assignment_id,
            payload={
                "schedule_id": new_schedule, "rotation_pattern_id": new_rotation, "rotation_offset_weeks": new_offset,
                "valid_from": new_from.isoformat(), "valid_to": new_to.isoformat() if new_to else None,
            },
        )
        return Ok(self._one_assignment(tenant_id, assignment_id))

    def _assignments(
        self, tenant_id: str, employee_ids: list[str], date_from: datetime.date | None = None, date_to: datetime.date | None = None
    ) -> dict[str, list[Assignment]]:
        params: list[object] = [tenant_id, list(employee_ids)]
        clause = ""
        if date_from is not None and date_to is not None:
            clause = " AND valid_from <= %s AND (valid_to IS NULL OR valid_to >= %s)"
            params += [date_to, date_from]
        rows = self.connection.execute(
            f"""
            SELECT id, employee_id, valid_from, valid_to, schedule_id, rotation_pattern_id, rotation_offset_weeks
            FROM hr.schedule_assignments
            WHERE tenant_id = %s AND employee_id = ANY(%s){clause}
            ORDER BY valid_from
            """,
            params,
        ).fetchall()
        grouped: dict[str, list[Assignment]] = {}
        for r in rows:
            grouped.setdefault(r[1], []).append(
                Assignment(id=r[0], employee_id=r[1], valid_from=r[2], valid_to=r[3], schedule_id=r[4], rotation_pattern_id=r[5], rotation_offset_weeks=r[6])
            )
        return grouped

    # ---- resolution ---------------------------------------------------------------
    def resolve(
        self, *, tenant_id: str, employee_ids: list[str], date_from: datetime.date, date_to: datetime.date
    ) -> dict[str, dict[datetime.date, ResolvedDay]]:
        schedules = {
            item["id"]: Schedule(id=item["id"], code=item["code"], is_night=item["is_night"], days=tuple(_schedule_days(item["days"])))
            for item in self.list_schedules(tenant_id=tenant_id)
        }
        patterns = {
            item["id"]: RotationPattern(id=item["id"], anchor_date=datetime.date.fromisoformat(item["anchor_date"]), schedule_ids=tuple(item["schedule_ids"]))
            for item in self.list_rotations(tenant_id=tenant_id)
            if item["schedule_ids"]
        }
        assignments = self._assignments(tenant_id, employee_ids, date_from, date_to)
        dates = date_range(date_from, date_to)
        return {
            employee_id: resolve_days(assignments=assignments.get(employee_id, []), patterns=patterns, schedules=schedules, dates=dates)
            for employee_id in employee_ids
        }


class HolidayService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    def list_holidays(self, *, tenant_id: str, year: int | None = None) -> list[dict]:
        params: list[object] = [tenant_id]
        clause = ""
        if year is not None:
            clause = " AND EXTRACT(YEAR FROM holiday_date) = %s"
            params.append(year)
        rows = self.connection.execute(
            f"SELECT id, country_code, holiday_date, name, paid, confirmed FROM hr.public_holidays WHERE tenant_id = %s{clause} ORDER BY holiday_date",
            params,
        ).fetchall()
        return [
            {"id": r[0], "country_code": r[1], "holiday_date": r[2].isoformat(), "name": r[3], "paid": r[4], "confirmed": r[5]}
            for r in rows
        ]

    def _holiday(self, tenant_id: str, holiday_id: str) -> dict | None:
        return next((h for h in self.list_holidays(tenant_id=tenant_id) if h["id"] == holiday_id), None)

    def _taken(self, tenant_id: str, country_code: str, holiday_date: datetime.date) -> bool:
        return self.connection.execute(
            "SELECT 1 FROM hr.public_holidays WHERE tenant_id = %s AND country_code = %s AND holiday_date = %s",
            (tenant_id, country_code, holiday_date),
        ).fetchone() is not None

    def create_holiday(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        country_code: str,
        holiday_date: datetime.date,
        name: str,
        paid: bool = True,
        confirmed: bool = False,
    ) -> Result[dict]:
        country = country_code.strip().upper()
        validation = validate_holiday(country_code=country, name=name)
        if isinstance(validation, Err):
            return validation
        if self._taken(tenant_id, country, holiday_date):
            return Err(
                "DUPLICATE_HOLIDAY",
                f"a public holiday already exists on {holiday_date.isoformat()} for {country}",
                f"un jour férié existe déjà le {holiday_date.isoformat()} pour {country}",
            )
        holiday_id = str(ULID())
        self.connection.execute(
            "INSERT INTO hr.public_holidays (id, tenant_id, country_code, holiday_date, name, paid, confirmed) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (holiday_id, tenant_id, country, holiday_date, name.strip(), paid, confirmed),
        )
        record_audit(
            self.connection, tenant_id=tenant_id, actor_id=actor_id, action="public_holiday.created",
            entity_type="public_holiday", entity_id=holiday_id,
            payload={"country_code": country, "holiday_date": holiday_date.isoformat(), "name": name.strip(), "paid": paid, "confirmed": confirmed},
        )
        return Ok(self._holiday(tenant_id, holiday_id))

    def update_holiday(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        holiday_id: str,
        holiday_date: datetime.date | None = None,
        name: str | None = None,
        paid: bool | None = None,
        confirmed: bool | None = None,
    ) -> Result[dict]:
        current = self._holiday(tenant_id, holiday_id)
        if current is None:
            return HOLIDAY_NOT_FOUND
        new_date = holiday_date or datetime.date.fromisoformat(current["holiday_date"])
        new_name = name.strip() if name is not None else current["name"]
        validation = validate_holiday(country_code=current["country_code"], name=new_name)
        if isinstance(validation, Err):
            return validation
        if new_date.isoformat() != current["holiday_date"] and self._taken(tenant_id, current["country_code"], new_date):
            return Err(
                "DUPLICATE_HOLIDAY",
                f"a public holiday already exists on {new_date.isoformat()} for {current['country_code']}",
                f"un jour férié existe déjà le {new_date.isoformat()} pour {current['country_code']}",
            )
        self.connection.execute(
            "UPDATE hr.public_holidays SET holiday_date = %s, name = %s, paid = %s, confirmed = %s WHERE id = %s AND tenant_id = %s",
            (
                new_date, new_name,
                paid if paid is not None else current["paid"],
                confirmed if confirmed is not None else current["confirmed"],
                holiday_id, tenant_id,
            ),
        )
        changes = {
            k: v
            for k, v in {"holiday_date": holiday_date.isoformat() if holiday_date else None, "name": name, "paid": paid, "confirmed": confirmed}.items()
            if v is not None
        }
        record_audit(
            self.connection, tenant_id=tenant_id, actor_id=actor_id, action="public_holiday.updated",
            entity_type="public_holiday", entity_id=holiday_id, payload=changes,
        )
        return Ok(self._holiday(tenant_id, holiday_id))

    def holiday_map(self, *, tenant_id: str, date_from: datetime.date, date_to: datetime.date) -> dict[datetime.date, bool]:
        """Every public holiday date in the range, mapped to whether it is paid."""
        rows = self.connection.execute(
            """
            SELECT holiday_date, bool_or(paid) FROM hr.public_holidays
            WHERE tenant_id = %s AND holiday_date BETWEEN %s AND %s
            GROUP BY holiday_date
            """,
            (tenant_id, date_from, date_to),
        ).fetchall()
        return {row[0]: row[1] for row in rows}


class PresenceSettingsService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    def get(self, *, tenant_id: str) -> dict:
        row = self.connection.execute(
            f"SELECT {', '.join(_SETTING_FIELDS)}, confirmed_at FROM hr.presence_settings WHERE tenant_id = %s",
            (tenant_id,),
        ).fetchone()
        if row is None:
            return {**{field: None for field in _SETTING_FIELDS}, "confirmed": False, "confirmed_at": None}
        values = dict(zip(_SETTING_FIELDS, row[:5]))
        return {**values, "confirmed": row[5] is not None, "confirmed_at": row[5].isoformat() if row[5] else None}

    def update(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        night_start_minute: int | None,
        night_end_minute: int | None,
        punch_attach_minutes: int | None,
        punch_dedupe_seconds: int | None,
        late_grace_minutes: int | None,
        confirm: bool = False,
    ) -> Result[dict]:
        values = {
            "night_start_minute": night_start_minute, "night_end_minute": night_end_minute,
            "punch_attach_minutes": punch_attach_minutes, "punch_dedupe_seconds": punch_dedupe_seconds,
            "late_grace_minutes": late_grace_minutes,
        }
        validation = validate_presence_settings(**values)
        if isinstance(validation, Err):
            return validation
        # Any save that is not an explicit confirmation clears the confirmation: a changed
        # value has not been checked yet.
        self.connection.execute(
            """
            INSERT INTO hr.presence_settings (tenant_id, night_start_minute, night_end_minute, punch_attach_minutes,
                                              punch_dedupe_seconds, late_grace_minutes, confirmed_by, confirmed_at,
                                              updated_by, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, CASE WHEN %s THEN NOW() END, %s, NOW())
            ON CONFLICT (tenant_id) DO UPDATE SET
                night_start_minute = EXCLUDED.night_start_minute, night_end_minute = EXCLUDED.night_end_minute,
                punch_attach_minutes = EXCLUDED.punch_attach_minutes, punch_dedupe_seconds = EXCLUDED.punch_dedupe_seconds,
                late_grace_minutes = EXCLUDED.late_grace_minutes, confirmed_by = EXCLUDED.confirmed_by,
                confirmed_at = EXCLUDED.confirmed_at, updated_by = EXCLUDED.updated_by, updated_at = NOW()
            """,
            (
                tenant_id, night_start_minute, night_end_minute, punch_attach_minutes, punch_dedupe_seconds,
                late_grace_minutes, actor_id if confirm else None, confirm, actor_id,
            ),
        )
        record_audit(
            self.connection, tenant_id=tenant_id, actor_id=actor_id, action="presence_settings.updated",
            entity_type="presence_settings", entity_id=tenant_id, payload={**values, "confirmed": confirm},
        )
        return Ok(self.get(tenant_id=tenant_id))

    def night_window(self, *, tenant_id: str) -> Result[tuple[int, int]]:
        settings = self.get(tenant_id=tenant_id)
        if settings["night_start_minute"] is None or settings["night_end_minute"] is None:
            return SETTINGS_MISSING
        return Ok((settings["night_start_minute"], settings["night_end_minute"]))
```

- [ ] **Step 7: Write the router (first section) and wire it**

`backend/modules/hr/api/presence_router.py`:

```python
"""HTTP routes of HR phase 2: schedules, holidays, presence, clock imports, leave, month close."""
from __future__ import annotations

import datetime
from typing import Callable, NoReturn

import psycopg
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from core.db import get_connection
from core.domain.result import Err, Result, err_detail
from core.tenancy import TenantContext, require_permission
from modules.hr.api.schedule_service import HolidayService, PresenceSettingsService, ScheduleService

router = APIRouter(prefix="/hr", tags=["hr.presence"])

# Refusals caused by the current state of the data rather than by a malformed request.
_CONFLICT_CODES = frozenset({
    "ASSIGNMENT_OVERLAP", "PRESENCE_MONTH_CLOSED", "PRESENCE_DAY_FROM_LEAVE", "PRESENCE_INCOMPLETE",
    "PRESENCE_PAYROLL_APPROVED", "LEAVE_PENDING", "LEAVE_OVERLAP", "LEAVE_OVERLAPS_WORK",
    "LEAVE_BALANCE_INSUFFICIENT", "INVALID_TRANSITION", "IMPORT_NOT_STAGED",
})


def _fail(err: Err) -> NoReturn:
    if err.code == "NOT_FOUND":
        code = status.HTTP_404_NOT_FOUND
    elif err.code in _CONFLICT_CODES or err.code.startswith("DUPLICATE"):
        code = status.HTTP_409_CONFLICT
    else:
        code = status.HTTP_422_UNPROCESSABLE_ENTITY
    raise HTTPException(code, err_detail(err))


def _write(action: Callable[[psycopg.Connection], Result]):
    with get_connection() as connection:
        result = action(connection)
        if isinstance(result, Err):
            connection.rollback()
            _fail(result)
        connection.commit()
        return result.value


def _read(action: Callable[[psycopg.Connection], object]):
    with get_connection() as connection:
        return action(connection)


def _read_result(action: Callable[[psycopg.Connection], Result]):
    with get_connection() as connection:
        result = action(connection)
    if isinstance(result, Err):
        _fail(result)
    return result.value


def _period(value: datetime.date) -> datetime.date:
    if value.day != 1:
        _fail(Err("INVALID_PERIOD", "a period is the first day of a month", "une période est le premier jour d'un mois"))
    return value


# ---- schedules, rotations, assignments, holidays, settings --------------------------

class ScheduleDayBody(BaseModel):
    weekday: int
    start_minute: int
    end_minute: int
    break_minutes: int = 0


class ScheduleBody(BaseModel):
    code: str
    name: str
    is_night: bool = False
    days: list[ScheduleDayBody]


class ScheduleUpdateBody(BaseModel):
    code: str | None = None
    name: str | None = None
    is_night: bool | None = None
    active: bool | None = None
    days: list[ScheduleDayBody] | None = None


class RotationBody(BaseModel):
    code: str
    name: str
    anchor_date: datetime.date
    schedule_ids: list[str]


class RotationUpdateBody(BaseModel):
    code: str | None = None
    name: str | None = None
    anchor_date: datetime.date | None = None
    schedule_ids: list[str] | None = None
    active: bool | None = None


class AssignmentBody(BaseModel):
    employee_id: str
    valid_from: datetime.date
    valid_to: datetime.date | None = None
    schedule_id: str | None = None
    rotation_pattern_id: str | None = None
    rotation_offset_weeks: int = 0


class AssignmentUpdateBody(BaseModel):
    valid_from: datetime.date | None = None
    valid_to: datetime.date | None = None
    clear_valid_to: bool = False
    schedule_id: str | None = None
    rotation_pattern_id: str | None = None
    rotation_offset_weeks: int | None = None


class HolidayBody(BaseModel):
    country_code: str
    holiday_date: datetime.date
    name: str
    paid: bool = True
    confirmed: bool = False


class HolidayUpdateBody(BaseModel):
    holiday_date: datetime.date | None = None
    name: str | None = None
    paid: bool | None = None
    confirmed: bool | None = None


class PresenceSettingsBody(BaseModel):
    night_start_minute: int | None = None
    night_end_minute: int | None = None
    punch_attach_minutes: int | None = None
    punch_dedupe_seconds: int | None = None
    late_grace_minutes: int | None = None
    confirm: bool = False


@router.get("/schedules")
def list_schedules(tenant: TenantContext = Depends(require_permission("hr.view_presence"))):
    return _read(lambda c: ScheduleService(c).list_schedules(tenant_id=tenant.tenant_id))


@router.post("/schedules", status_code=status.HTTP_201_CREATED)
def create_schedule(body: ScheduleBody, tenant: TenantContext = Depends(require_permission("hr.manage_presence"))):
    return _write(lambda c: ScheduleService(c).create_schedule(
        tenant_id=tenant.tenant_id, actor_id=tenant.user_id, code=body.code, name=body.name,
        is_night=body.is_night, days=[day.model_dump() for day in body.days],
    ))


@router.patch("/schedules/{schedule_id}")
def update_schedule(schedule_id: str, body: ScheduleUpdateBody, tenant: TenantContext = Depends(require_permission("hr.admin_presence"))):
    return _write(lambda c: ScheduleService(c).update_schedule(
        tenant_id=tenant.tenant_id, actor_id=tenant.user_id, schedule_id=schedule_id, code=body.code, name=body.name,
        is_night=body.is_night, active=body.active,
        days=[day.model_dump() for day in body.days] if body.days is not None else None,
    ))


@router.get("/rotation-patterns")
def list_rotations(tenant: TenantContext = Depends(require_permission("hr.view_presence"))):
    return _read(lambda c: ScheduleService(c).list_rotations(tenant_id=tenant.tenant_id))


@router.post("/rotation-patterns", status_code=status.HTTP_201_CREATED)
def create_rotation(body: RotationBody, tenant: TenantContext = Depends(require_permission("hr.manage_presence"))):
    return _write(lambda c: ScheduleService(c).create_rotation(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, **body.model_dump()))


@router.patch("/rotation-patterns/{rotation_id}")
def update_rotation(rotation_id: str, body: RotationUpdateBody, tenant: TenantContext = Depends(require_permission("hr.admin_presence"))):
    return _write(lambda c: ScheduleService(c).update_rotation(
        tenant_id=tenant.tenant_id, actor_id=tenant.user_id, rotation_id=rotation_id, **body.model_dump()
    ))


@router.get("/schedule-assignments")
def list_assignments(employee_id: str | None = None, tenant: TenantContext = Depends(require_permission("hr.view_presence"))):
    return _read(lambda c: ScheduleService(c).list_assignments(tenant_id=tenant.tenant_id, employee_id=employee_id))


@router.post("/schedule-assignments", status_code=status.HTTP_201_CREATED)
def create_assignment(body: AssignmentBody, tenant: TenantContext = Depends(require_permission("hr.manage_presence"))):
    return _write(lambda c: ScheduleService(c).create_assignment(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, **body.model_dump()))


@router.patch("/schedule-assignments/{assignment_id}")
def update_assignment(assignment_id: str, body: AssignmentUpdateBody, tenant: TenantContext = Depends(require_permission("hr.admin_presence"))):
    return _write(lambda c: ScheduleService(c).update_assignment(
        tenant_id=tenant.tenant_id, actor_id=tenant.user_id, assignment_id=assignment_id, **body.model_dump()
    ))


@router.get("/public-holidays")
def list_holidays(year: int | None = None, tenant: TenantContext = Depends(require_permission("hr.view_presence"))):
    return _read(lambda c: HolidayService(c).list_holidays(tenant_id=tenant.tenant_id, year=year))


@router.post("/public-holidays", status_code=status.HTTP_201_CREATED)
def create_holiday(body: HolidayBody, tenant: TenantContext = Depends(require_permission("hr.manage_presence"))):
    return _write(lambda c: HolidayService(c).create_holiday(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, **body.model_dump()))


@router.patch("/public-holidays/{holiday_id}")
def update_holiday(holiday_id: str, body: HolidayUpdateBody, tenant: TenantContext = Depends(require_permission("hr.admin_presence"))):
    return _write(lambda c: HolidayService(c).update_holiday(
        tenant_id=tenant.tenant_id, actor_id=tenant.user_id, holiday_id=holiday_id, **body.model_dump()
    ))


@router.get("/presence/settings")
def get_presence_settings(tenant: TenantContext = Depends(require_permission("hr.view_presence"))):
    return _read(lambda c: PresenceSettingsService(c).get(tenant_id=tenant.tenant_id))


@router.put("/presence/settings")
def save_presence_settings(body: PresenceSettingsBody, tenant: TenantContext = Depends(require_permission("hr.admin_presence"))):
    return _write(lambda c: PresenceSettingsService(c).update(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, **body.model_dump()))
```

In `backend/app/main.py`, next to the existing `from modules.hr.api.router import router as hr_router` add:

```python
from modules.hr.api.presence_router import router as hr_presence_router
```

and right after `app.include_router(hr_router)` add:

```python
app.include_router(hr_presence_router)
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest modules/hr/api/test_schedule_service_integration.py modules/hr/api/test_presence_router_routes.py modules/hr/domain -q`
Expected: all pass, **0 skipped** (if the integration tests skip, the DB is unreachable or unmigrated — fix that first).

- [ ] **Step 9: Commit**

```bash
git add backend/modules/hr/migrations/0010_hr_work_schedules.sql backend/modules/hr/migrations/0011_hr_holidays_presence_settings.sql backend/modules/hr/api/schedule_service.py backend/modules/hr/api/presence_router.py backend/modules/hr/api/presence_testkit.py backend/modules/hr/api/test_schedule_service_integration.py backend/modules/hr/api/test_presence_router_routes.py backend/app/main.py
git commit -m "feat(hr): schedules, rotations, assignments, public holidays and presence settings

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Presence days — domain rules, table, supervisor grid (day and week), employee month

**Files:**
- Create: `backend/modules/hr/migrations/0012_hr_presence_days.sql`
- Create: `backend/modules/hr/domain/presence.py`
- Create: `backend/modules/hr/api/presence_service.py`
- Modify: `backend/modules/hr/api/presence_router.py` (append the presence section)
- Test: `backend/modules/hr/domain/test_presence.py`, `backend/modules/hr/api/test_presence_grid_integration.py`, `backend/modules/hr/api/test_presence_router_routes.py` (append one test)

**Interfaces:**
- Consumes: `ScheduleService.resolve`, `HolidayService.holiday_map`, `PresenceSettingsService.night_window` (Task 2); `ResolvedDay`, `ShiftWindow`, `night_overlap_minutes`, `date_range` (Task 1); testkit (Task 2).
- Produces:
  - `domain/presence.py`: `PRESENCE_STATUSES`, `WORKED_STATUSES`, `PROTECTED_SOURCES = {"manual", "leave"}`, `SUMMARY_FIELDS` (the 12 contract keys, in contract order); `ManualEntry(employee_id, work_date, status, worked_minutes=None, late_minutes=0, ot_minutes_day=0, ot_minutes_night=0, justified=False, note=None)`; `DayFigures(status, schedule_id, scheduled_minutes, worked_minutes, late_minutes=0, ot_minutes_day=0, ot_minutes_night=0, ot_minutes_rest_holiday=0, night_minutes=0)`; `validate_entry(entry) -> Result[None]` (code `INVALID_PRESENCE`); `default_status(day: ResolvedDay, *, is_holiday: bool) -> str | None`; `figures_for_entry(entry, window, night: tuple[int, int], *, is_holiday: bool) -> DayFigures`; `SummaryRow(employee_id, work_date, status, scheduled_minutes, worked_minutes, late_minutes, ot_minutes_day, ot_minutes_night, ot_minutes_rest_holiday, night_minutes, justified, leave_paid: bool | None)`; `summarize_month(employee_ids: list[str], rows: list[SummaryRow], paid_holidays: set[date]) -> list[dict]`.
  - `api/presence_service.py` module functions: `month_bounds(period) -> tuple[date, date]` (raises `ValueError` unless `period.day == 1`), `closed_periods(connection, tenant_id, dates) -> list[date]`, `month_closed_error(periods) -> Err` (code `PRESENCE_MONTH_CLOSED`), `employed_between(connection, *, tenant_id, date_from, date_to, department_id=None, employee_ids=None) -> list[dict]` (dict: `id, employee_no, full_name, department_id, hire_date, termination_date, badge_no`), `is_employed(employee: dict, day) -> bool`.
  - `PresenceService(connection)`: `grid(*, tenant_id, work_date, department_id=None, schedule_id=None) -> list[dict]`; `week(*, tenant_id, date_from, department_id=None, schedule_id=None) -> list[dict]`; `employee_month(*, tenant_id, employee_id, period) -> Result[dict]`; `is_month_closed(*, tenant_id, period) -> bool` (**contract**); `existing_days(*, tenant_id, employee_ids, date_from, date_to) -> dict[tuple[str, date], dict]`; `save_days(*, tenant_id, actor_id, entries: list[ManualEntry]) -> Result[dict]` (`{"saved": n}`); `upsert_day(*, tenant_id, actor_id, employee_id, work_date, figures: DayFigures, source, justified=False, note=None, leave_request_id=None, clock_import_id=None) -> str`.
  - Grid row dict: `employee_id, employee_no, full_name, department_id, days: [{work_date, employed, assigned, schedule_id, schedule_code, is_working_day, is_holiday, planned_minutes, default_status, record}]`; `record` is `None` or `{id, status, source, scheduled_minutes, worked_minutes, late_minutes, ot_minutes_day, ot_minutes_night, ot_minutes_rest_holiday, night_minutes, justified, note, locked, leave_request_id}`.
  - Routes: `GET /hr/presence/grid?work_date=&department_id=&schedule_id=`, `GET /hr/presence/week?date_from=&department_id=&schedule_id=`, `PUT /hr/presence/days` body `{entries: [...]}`, `GET /hr/presence/employee-month?employee_id=&period=`.

- [ ] **Step 1: Write the failing domain tests**

`backend/modules/hr/domain/test_presence.py`:

```python
"""Presence rules without a database. The night window 21:00-05:00 is a test input."""
from __future__ import annotations

import datetime as dt

import pytest

from core.domain.result import Err, Ok
from modules.hr.domain.presence import (
    SUMMARY_FIELDS,
    ManualEntry,
    SummaryRow,
    default_status,
    figures_for_entry,
    summarize_month,
    validate_entry,
)
from modules.hr.domain.schedule import ResolvedDay, Schedule, ScheduleDay, shift_window

AUG_3 = dt.date(2026, 8, 3)
DAY = Schedule(id="s-day", code="JOUR", days=tuple(ScheduleDay(w, 420, 900) for w in range(6)))
NIGHT = Schedule(id="s-night", code="NUIT", days=tuple(ScheduleDay(w, 1380, 420) for w in range(6)))
NIGHT_WINDOW = (1260, 300)


def entry(status: str, **values) -> ManualEntry:
    return ManualEntry(employee_id="e1", work_date=AUG_3, status=status, **values)


@pytest.mark.parametrize(
    "bad",
    [
        entry("leave"),  # leave days come from an approved request
        entry("late"),  # late without minutes
        entry("present", late_minutes=10),  # lateness on a day that is not late
        entry("absent", worked_minutes=60),  # worked minutes on an absence
        entry("sick", ot_minutes_day=30),  # overtime on a sick day
        entry("present", ot_minutes_night=-5),
        entry("away"),  # unknown status
    ],
)
def test_impossible_entries_are_refused(bad):
    result = validate_entry(bad)
    assert isinstance(result, Err) and result.code == "INVALID_PRESENCE" and result.message_fr


def test_ordinary_entries_pass():
    for good in (entry("present"), entry("late", late_minutes=15), entry("absent", justified=True), entry("mission"), entry("holiday")):
        assert isinstance(validate_entry(good), Ok)


def test_a_late_day_works_the_planned_minutes_less_the_lateness():
    figures = figures_for_entry(entry("late", late_minutes=30), shift_window(DAY, AUG_3), NIGHT_WINDOW, is_holiday=False)
    assert (figures.scheduled_minutes, figures.worked_minutes, figures.late_minutes, figures.night_minutes) == (480, 450, 30, 0)


def test_a_night_shift_carries_its_night_minutes():
    figures = figures_for_entry(entry("present"), shift_window(NIGHT, AUG_3), NIGHT_WINDOW, is_holiday=False)
    assert (figures.worked_minutes, figures.night_minutes, figures.schedule_id) == (480, 360, "s-night")


def test_typed_overtime_is_kept_on_a_working_day():
    figures = figures_for_entry(entry("present", ot_minutes_day=45, ot_minutes_night=15), shift_window(DAY, AUG_3), NIGHT_WINDOW, is_holiday=False)
    assert (figures.ot_minutes_day, figures.ot_minutes_night, figures.ot_minutes_rest_holiday) == (45, 15, 0)


def test_work_on_a_rest_day_is_all_rest_holiday_overtime():
    sunday = dt.date(2026, 8, 9)
    typed = ManualEntry(employee_id="e1", work_date=sunday, status="present", worked_minutes=240, ot_minutes_day=30)
    figures = figures_for_entry(typed, shift_window(DAY, sunday), NIGHT_WINDOW, is_holiday=False)
    assert (figures.scheduled_minutes, figures.worked_minutes, figures.ot_minutes_rest_holiday, figures.ot_minutes_day) == (0, 240, 240, 0)


def test_work_on_a_public_holiday_defaults_to_the_planned_shift_as_overtime():
    figures = figures_for_entry(entry("present"), shift_window(DAY, AUG_3), NIGHT_WINDOW, is_holiday=True)
    assert (figures.scheduled_minutes, figures.worked_minutes, figures.ot_minutes_rest_holiday) == (0, 480, 480)


def test_an_absence_has_no_worked_minutes():
    figures = figures_for_entry(entry("absent"), shift_window(DAY, AUG_3), NIGHT_WINDOW, is_holiday=False)
    assert (figures.scheduled_minutes, figures.worked_minutes, figures.night_minutes) == (480, 0, 0)


def test_the_grid_default_follows_the_schedule_and_the_holiday_calendar():
    window = shift_window(DAY, AUG_3)
    working = ResolvedDay(work_date=AUG_3, assigned=True, schedule_id="s-day", schedule_code="JOUR", window=window)
    rest = ResolvedDay(work_date=AUG_3, assigned=True, schedule_id="s-day", schedule_code="JOUR", window=None)
    assert default_status(working, is_holiday=False) == "present"
    assert default_status(working, is_holiday=True) == "holiday"
    assert default_status(rest, is_holiday=True) == "rest"  # a holiday on a rest day stays a rest day
    assert default_status(ResolvedDay(work_date=AUG_3, assigned=False), is_holiday=False) is None


def _row(day: int, status: str, **values) -> SummaryRow:
    base = dict(
        employee_id="e1", work_date=dt.date(2026, 8, day), status=status, scheduled_minutes=480, worked_minutes=0,
        late_minutes=0, ot_minutes_day=0, ot_minutes_night=0, ot_minutes_rest_holiday=0, night_minutes=0,
        justified=False, leave_paid=None,
    )
    base.update(values)
    return SummaryRow(**base)


def test_the_month_summary_counts_each_kind_of_day():
    rows = [
        _row(3, "present", worked_minutes=480, ot_minutes_day=30),
        _row(4, "late", worked_minutes=450, late_minutes=30),
        _row(5, "absent"),
        _row(6, "absent", justified=True),
        _row(7, "leave", leave_paid=True),
        _row(8, "leave", leave_paid=False),
        _row(9, "rest", scheduled_minutes=0),
        _row(10, "sick"),
        _row(11, "holiday", scheduled_minutes=0),
        _row(12, "present", scheduled_minutes=0, worked_minutes=420, ot_minutes_rest_holiday=420, night_minutes=60),
        _row(13, "suspended"),
    ]
    summary = summarize_month(["e1", "e2"], rows, paid_holidays={dt.date(2026, 8, 11), dt.date(2026, 8, 12)})
    assert summary[0] == {
        "employee_id": "e1",
        "scheduled_days": 8,  # 3, 4, 5, 6, 7, 8, 10, 13
        "worked_days": 3,  # 3, 4, 12
        "unpaid_absence_days": 3,  # 5 (unjustified), 8 (unpaid leave), 13 (suspended)
        "paid_leave_days": 1,
        "sick_days": 1,
        "holiday_days": 2,  # 11 not worked, 12 worked
        "holidays_worked_days": 1,
        "ot_minutes_day": 30,
        "ot_minutes_night": 0,
        "ot_minutes_rest_holiday": 420,
        "night_minutes": 60,
        "late_minutes": 30,
    }
    assert summary[1] == {"employee_id": "e2", **{field: 0 for field in SUMMARY_FIELDS}}


def test_a_leave_day_without_a_type_is_paid_and_an_unpaid_holiday_is_no_holiday_day():
    summary = summarize_month(["e1"], [_row(7, "leave"), _row(11, "holiday", scheduled_minutes=0)], paid_holidays=set())
    assert (summary[0]["paid_leave_days"], summary[0]["holiday_days"], summary[0]["unpaid_absence_days"]) == (1, 0, 0)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python -m pytest modules/hr/domain/test_presence.py -q`
Expected: collection error `No module named 'modules.hr.domain.presence'`.

- [ ] **Step 3: Write the domain module**

`backend/modules/hr/domain/presence.py`:

```python
"""Presence days: what a supervisor may record, the figures of a day, and the month summary.

Pure: no database. The month summary is the only presence input payroll reads
(PresenceService.month_summary). Its rules, each pinned by test_presence.py:

* scheduled_days: rows with scheduled minutes whose status is not rest or holiday.
* worked_days: rows with worked minutes (a worked rest day or holiday included).
* unpaid_absence_days: unjustified absences, suspensions, leave of an unpaid type.
  A justified absence is not unpaid.
* paid_leave_days: leave days of a paid type; a leave day without a type (an old
  request) counts as paid.
* sick_days: rows marked sick.
* holiday_days: paid public holidays the person was off for (status holiday) or worked;
  holidays_worked_days: the worked ones among them. An unpaid holiday counts in neither.
* minute fields: straight sums of the stored columns.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass

from core.domain.result import Err, Ok, Result
from modules.hr.domain.schedule import ResolvedDay, ShiftWindow, night_overlap_minutes

PRESENCE_STATUSES = ("present", "absent", "late", "leave", "holiday", "rest", "sick", "mission", "suspended")
WORKED_STATUSES = frozenset({"present", "late", "mission"})
# Statuses a supervisor may not type: leave days come from an approved leave request.
REQUEST_ONLY_STATUSES = frozenset({"leave"})
# A clock import never overwrites a day a person decided by hand or an approved leave.
PROTECTED_SOURCES = frozenset({"manual", "leave"})
SUMMARY_FIELDS = (
    "scheduled_days", "worked_days", "unpaid_absence_days", "paid_leave_days", "sick_days", "holiday_days",
    "holidays_worked_days", "ot_minutes_day", "ot_minutes_night", "ot_minutes_rest_holiday", "night_minutes", "late_minutes",
)
_SUMMED_MINUTES = ("ot_minutes_day", "ot_minutes_night", "ot_minutes_rest_holiday", "night_minutes", "late_minutes")


@dataclass(frozen=True)
class ManualEntry:
    employee_id: str
    work_date: datetime.date
    status: str
    worked_minutes: int | None = None  # None: planned minutes less the lateness
    late_minutes: int = 0
    ot_minutes_day: int = 0
    ot_minutes_night: int = 0
    justified: bool = False
    note: str | None = None


@dataclass(frozen=True)
class DayFigures:
    status: str
    schedule_id: str | None
    scheduled_minutes: int
    worked_minutes: int
    late_minutes: int = 0
    ot_minutes_day: int = 0
    ot_minutes_night: int = 0
    ot_minutes_rest_holiday: int = 0
    night_minutes: int = 0


def validate_entry(entry: ManualEntry) -> Result[None]:
    if entry.status not in PRESENCE_STATUSES:
        return Err("INVALID_PRESENCE", f"unknown presence status {entry.status!r}", f"statut de présence inconnu {entry.status!r}")
    if entry.status in REQUEST_ONLY_STATUSES:
        return Err("INVALID_PRESENCE", "leave days come from an approved leave request", "les jours de congé viennent d'une demande de congé approuvée")
    minutes = (entry.worked_minutes or 0, entry.late_minutes, entry.ot_minutes_day, entry.ot_minutes_night)
    if any(value < 0 for value in minutes):
        return Err("INVALID_PRESENCE", "minutes cannot be negative", "les minutes ne peuvent pas être négatives")
    if entry.status == "late" and entry.late_minutes <= 0:
        return Err("INVALID_PRESENCE", "a late day needs its minutes of lateness", "un retard doit indiquer ses minutes de retard")
    if entry.status != "late" and entry.late_minutes:
        return Err("INVALID_PRESENCE", "only a late day carries minutes of lateness", "seul un retard porte des minutes de retard")
    if entry.status not in WORKED_STATUSES and (entry.worked_minutes or entry.ot_minutes_day or entry.ot_minutes_night):
        return Err(
            "INVALID_PRESENCE",
            f"a day marked {entry.status} has no worked minutes or overtime",
            f"un jour marqué {entry.status} n'a ni minutes travaillées ni heures supplémentaires",
        )
    return Ok(None)


def default_status(day: ResolvedDay, *, is_holiday: bool) -> str | None:
    """What the grid proposes before anyone saved the day; None when no schedule is assigned."""
    if not day.assigned:
        return None
    if not day.is_working_day:
        return "rest"
    return "holiday" if is_holiday else "present"


def figures_for_entry(entry: ManualEntry, window: ShiftWindow | None, night: tuple[int, int], *, is_holiday: bool) -> DayFigures:
    """The stored figures of a day typed in the grid.

    On a working day the typed day/night overtime is kept. On a rest day or a public holiday
    every worked minute is rest/holiday overtime, as for the clock, and typed day/night
    overtime is not used (the grid disables those inputs there).
    """
    expected = window is not None and not is_holiday
    schedule_id = window.schedule_id if window is not None else None
    scheduled = window.scheduled_minutes if expected else 0
    if entry.status not in WORKED_STATUSES:
        return DayFigures(status=entry.status, schedule_id=schedule_id, scheduled_minutes=scheduled, worked_minutes=0)
    planned = window.scheduled_minutes if window is not None else 0
    worked = entry.worked_minutes if entry.worked_minutes is not None else max(0, planned - entry.late_minutes)
    night_minutes = 0
    if window is not None:
        start = window.start + datetime.timedelta(minutes=entry.late_minutes)
        night_minutes = night_overlap_minutes(start, window.end, *night) if start < window.end else 0
    if expected:
        return DayFigures(
            status=entry.status, schedule_id=schedule_id, scheduled_minutes=scheduled, worked_minutes=worked,
            late_minutes=entry.late_minutes, ot_minutes_day=entry.ot_minutes_day, ot_minutes_night=entry.ot_minutes_night,
            night_minutes=night_minutes,
        )
    return DayFigures(
        status=entry.status, schedule_id=schedule_id, scheduled_minutes=0, worked_minutes=worked,
        late_minutes=entry.late_minutes, ot_minutes_rest_holiday=worked, night_minutes=night_minutes,
    )


@dataclass(frozen=True)
class SummaryRow:
    employee_id: str
    work_date: datetime.date
    status: str
    scheduled_minutes: int
    worked_minutes: int
    late_minutes: int
    ot_minutes_day: int
    ot_minutes_night: int
    ot_minutes_rest_holiday: int
    night_minutes: int
    justified: bool
    leave_paid: bool | None  # the leave type's paid flag on a leave day, else None


def _empty(employee_id: str) -> dict:
    return {"employee_id": employee_id, **{field: 0 for field in SUMMARY_FIELDS}}


def summarize_month(employee_ids: list[str], rows: list[SummaryRow], paid_holidays: set[datetime.date]) -> list[dict]:
    """One dict per employee (the requested ones first, in order, then any other found in rows)."""
    requested = list(employee_ids)
    totals: dict[str, dict] = {employee_id: _empty(employee_id) for employee_id in requested}
    for row in rows:
        total = totals.setdefault(row.employee_id, _empty(row.employee_id))
        if row.scheduled_minutes > 0 and row.status not in ("rest", "holiday"):
            total["scheduled_days"] += 1
        if row.worked_minutes > 0:
            total["worked_days"] += 1
        unpaid_leave = row.status == "leave" and row.leave_paid is False
        if (row.status == "absent" and not row.justified) or row.status == "suspended" or unpaid_leave:
            total["unpaid_absence_days"] += 1
        if row.status == "leave" and not unpaid_leave:
            total["paid_leave_days"] += 1
        if row.status == "sick":
            total["sick_days"] += 1
        if row.work_date in paid_holidays:
            if row.worked_minutes > 0:
                total["holiday_days"] += 1
                total["holidays_worked_days"] += 1
            elif row.status == "holiday":
                total["holiday_days"] += 1
        for field in _SUMMED_MINUTES:
            total[field] += getattr(row, field)
    known = set(requested)
    ordered = requested + sorted(employee_id for employee_id in totals if employee_id not in known)
    return [totals[employee_id] for employee_id in ordered]
```

- [ ] **Step 4: Run the domain tests to verify they pass**

Run: `.venv/Scripts/python -m pytest modules/hr/domain/test_presence.py -q`
Expected: all pass.

- [ ] **Step 5: Write and apply the migration**

`backend/modules/hr/migrations/0012_hr_presence_days.sql`:

```sql
-- One row per employee and date. New code writes here; hr.attendance_records stays as it is.
-- clock_import_id gets its foreign key in 0013, once hr.clock_imports exists.
CREATE TABLE IF NOT EXISTS hr.presence_days (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    employee_id TEXT NOT NULL REFERENCES hr.employees (id),
    work_date DATE NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('present', 'absent', 'late', 'leave', 'holiday', 'rest', 'sick', 'mission', 'suspended')),
    schedule_id TEXT REFERENCES hr.work_schedules (id),
    scheduled_minutes INTEGER NOT NULL DEFAULT 0 CHECK (scheduled_minutes >= 0),
    worked_minutes INTEGER NOT NULL DEFAULT 0 CHECK (worked_minutes >= 0),
    late_minutes INTEGER NOT NULL DEFAULT 0 CHECK (late_minutes >= 0),
    ot_minutes_day INTEGER NOT NULL DEFAULT 0 CHECK (ot_minutes_day >= 0),
    ot_minutes_night INTEGER NOT NULL DEFAULT 0 CHECK (ot_minutes_night >= 0),
    ot_minutes_rest_holiday INTEGER NOT NULL DEFAULT 0 CHECK (ot_minutes_rest_holiday >= 0),
    night_minutes INTEGER NOT NULL DEFAULT 0 CHECK (night_minutes >= 0),
    source TEXT NOT NULL CHECK (source IN ('manual', 'clock', 'leave', 'holiday')),
    justified BOOLEAN NOT NULL DEFAULT FALSE,
    note TEXT,
    leave_request_id TEXT REFERENCES hr.leave_requests (id),
    clock_import_id TEXT,
    locked BOOLEAN NOT NULL DEFAULT FALSE,
    updated_by TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, employee_id, work_date)
);

CREATE INDEX IF NOT EXISTS hr_presence_days_date_idx ON hr.presence_days (tenant_id, work_date);
CREATE INDEX IF NOT EXISTS hr_presence_days_leave_idx ON hr.presence_days (leave_request_id) WHERE leave_request_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS hr.presence_months (
    tenant_id TEXT NOT NULL,
    period DATE NOT NULL CHECK (EXTRACT(DAY FROM period) = 1),
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed')),
    closed_by TEXT,
    closed_at TIMESTAMPTZ,
    reopened_by TEXT,
    reopened_at TIMESTAMPTZ,
    PRIMARY KEY (tenant_id, period)
);

-- Written by the consumers of payroll.run.approved / payroll.run.reversed (Task 9): while a
-- row exists for a period, that month's presence cannot be reopened.
CREATE TABLE IF NOT EXISTS hr.presence_month_payroll_locks (
    tenant_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    period DATE NOT NULL,
    locked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (tenant_id, run_id)
);
```

Run: `DATABASE_URL=postgresql://erp:erp@localhost:5432/erp .venv/Scripts/python.exe -c "from core.migrations.runner import apply_all_migrations; apply_all_migrations()"`
Expected: exit 0.

- [ ] **Step 6: Write the failing integration tests and route test**

`backend/modules/hr/api/test_presence_grid_integration.py`:

```python
"""The supervisor grid against a real database."""
from __future__ import annotations

import datetime

from core.domain.result import Err, Ok
from modules.hr.api.presence_service import PresenceService
from modules.hr.api.presence_testkit import (  # noqa: F401
    AUG_1, AUG_3, TENANT, add_employee, close_month_directly, insert_presence_row, presence_env, presence_row,
)
from modules.hr.api.schedule_service import HolidayService
from modules.hr.domain.presence import ManualEntry

SUNDAY = datetime.date(2026, 8, 9)


def _day(rows: list[dict], employee_no: str) -> dict:
    return next(row["days"][0] for row in rows if row["employee_no"] == employee_no)


def _save(db, env, *entries: ManualEntry):
    return PresenceService(db).save_days(tenant_id=TENANT, actor_id=env.actor, entries=list(entries))


def test_the_day_grid_defaults_each_person_to_their_schedule(db, presence_env):
    rows = PresenceService(db).grid(tenant_id=TENANT, work_date=AUG_3)
    day = _day(rows, "P-001")
    assert (day["default_status"], day["planned_minutes"], day["record"], day["employed"]) == ("present", 480, None, True)
    assert _day(rows, "P-002")["schedule_code"] == "NUIT"


def test_sunday_is_rest_and_a_public_holiday_defaults_to_holiday(db, presence_env):
    HolidayService(db).create_holiday(tenant_id=TENANT, actor_id=presence_env.actor, country_code="ML", holiday_date=AUG_3, name="Jour de test")
    presence = PresenceService(db)
    assert _day(presence.grid(tenant_id=TENANT, work_date=AUG_3), "P-001")["default_status"] == "holiday"
    assert _day(presence.grid(tenant_id=TENANT, work_date=SUNDAY), "P-001")["default_status"] == "rest"


def test_the_schedule_filter_keeps_that_team_only_and_a_week_has_seven_days(db, presence_env):
    presence = PresenceService(db)
    night_team = presence.grid(tenant_id=TENANT, work_date=AUG_3, schedule_id=presence_env.night_schedule)
    assert [row["employee_no"] for row in night_team] == ["P-002"]
    assert {len(row["days"]) for row in presence.week(tenant_id=TENANT, date_from=AUG_3)} == {7}


def test_saving_writes_manual_days_with_derived_minutes_and_one_audit_row_each(db, presence_env):
    saved = _save(
        db, presence_env,
        ManualEntry(employee_id=presence_env.day_worker, work_date=AUG_3, status="late", late_minutes=30),
        ManualEntry(employee_id=presence_env.night_worker, work_date=AUG_3, status="present"),
    )
    assert isinstance(saved, Ok) and saved.value == {"saved": 2}
    day = presence_row(db, presence_env.day_worker, AUG_3)
    night = presence_row(db, presence_env.night_worker, AUG_3)
    assert (day["status"], day["worked_minutes"], day["late_minutes"], day["source"]) == ("late", 450, 30, "manual")
    assert (night["worked_minutes"], night["night_minutes"]) == (480, 360)
    audits = db.execute("SELECT count(*) FROM core.audit_log WHERE tenant_id = %s AND action = 'presence_day.saved'", (TENANT,)).fetchone()[0]
    assert audits == 2


def test_a_rest_day_worked_by_hand_is_rest_holiday_overtime(db, presence_env):
    saved = _save(db, presence_env, ManualEntry(employee_id=presence_env.day_worker, work_date=SUNDAY, status="present", worked_minutes=240))
    assert isinstance(saved, Ok)
    row = presence_row(db, presence_env.day_worker, SUNDAY)
    assert (row["scheduled_minutes"], row["worked_minutes"], row["ot_minutes_rest_holiday"]) == (0, 240, 240)


def test_a_manual_entry_replaces_a_clock_day(db, presence_env):
    insert_presence_row(db, employee_id=presence_env.day_worker, work_date=AUG_3, status="absent", source="clock")
    assert isinstance(_save(db, presence_env, ManualEntry(employee_id=presence_env.day_worker, work_date=AUG_3, status="present")), Ok)
    assert presence_row(db, presence_env.day_worker, AUG_3)["source"] == "manual"


def test_a_leave_day_cannot_be_overwritten_from_the_grid_nor_typed_there(db, presence_env):
    insert_presence_row(db, employee_id=presence_env.day_worker, work_date=AUG_3, status="leave", source="leave")
    over_leave = _save(db, presence_env, ManualEntry(employee_id=presence_env.day_worker, work_date=AUG_3, status="present"))
    typed_leave = _save(db, presence_env, ManualEntry(employee_id=presence_env.night_worker, work_date=AUG_3, status="leave"))
    assert isinstance(over_leave, Err) and over_leave.code == "PRESENCE_DAY_FROM_LEAVE" and over_leave.message_fr
    assert isinstance(typed_leave, Err) and typed_leave.code == "INVALID_PRESENCE"


def test_a_closed_month_refuses_changes_and_reports_itself_closed(db, presence_env):
    close_month_directly(db, AUG_1)
    result = _save(db, presence_env, ManualEntry(employee_id=presence_env.day_worker, work_date=AUG_3, status="present"))
    assert isinstance(result, Err) and result.code == "PRESENCE_MONTH_CLOSED" and "2026-08" in result.message_fr
    presence = PresenceService(db)
    assert presence.is_month_closed(tenant_id=TENANT, period=AUG_1) is True
    assert presence.is_month_closed(tenant_id=TENANT, period=datetime.date(2026, 9, 1)) is False


def test_saving_needs_the_night_window(db, presence_env):
    db.execute("UPDATE hr.presence_settings SET night_start_minute = NULL, night_end_minute = NULL WHERE tenant_id = %s", (TENANT,))
    result = _save(db, presence_env, ManualEntry(employee_id=presence_env.day_worker, work_date=AUG_3, status="present"))
    assert isinstance(result, Err) and result.code == "PRESENCE_SETTINGS_MISSING"


def test_a_day_outside_employment_is_refused(db, presence_env):
    newcomer = add_employee(db, employee_no="P-003", department=presence_env.department, hire_date=datetime.date(2026, 8, 10))
    result = _save(db, presence_env, ManualEntry(employee_id=newcomer, work_date=AUG_3, status="present"))
    assert isinstance(result, Err) and result.code == "NOT_EMPLOYED" and result.message_fr


def test_the_employee_month_lists_every_day_and_says_whether_it_is_closed(db, presence_env):
    result = PresenceService(db).employee_month(tenant_id=TENANT, employee_id=presence_env.day_worker, period=AUG_1)
    assert isinstance(result, Ok)
    assert (len(result.value["days"]), result.value["closed"], result.value["period"]) == (31, False, "2026-08-01")
```

Append to `backend/modules/hr/api/test_presence_router_routes.py`:

```python
def test_presence_grid_routes_and_their_permissions():
    expected = {
        ("GET", "/hr/presence/grid"): "hr.view_presence",
        ("GET", "/hr/presence/week"): "hr.view_presence",
        ("PUT", "/hr/presence/days"): "hr.manage_presence",
        ("GET", "/hr/presence/employee-month"): "hr.view_presence",
    }
    routes = _routes()
    assert {key: routes.get(key) for key in expected} == expected
```

Run: `.venv/Scripts/python -m pytest modules/hr/api/test_presence_grid_integration.py modules/hr/api/test_presence_router_routes.py -q`
Expected: FAIL (`No module named 'modules.hr.api.presence_service'`).

- [ ] **Step 7: Write the service**

`backend/modules/hr/api/presence_service.py`:

```python
"""Daily presence: the supervisor grid (a team on a day or a week), one person's month,
saving what the supervisor typed, and the answers payroll asks for.

Helpers at module level (month bounds, closed months, who is employed) are shared by the
clock, leave and month-close services of this module.
"""
from __future__ import annotations

import calendar
import datetime
from typing import Iterable

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.hr.api.schedule_service import HolidayService, PresenceSettingsService, ScheduleService
from modules.hr.domain.presence import DayFigures, ManualEntry, default_status, figures_for_entry, validate_entry
from modules.hr.domain.schedule import date_range

_RECORD_KEYS = (
    "id", "status", "source", "scheduled_minutes", "worked_minutes", "late_minutes", "ot_minutes_day",
    "ot_minutes_night", "ot_minutes_rest_holiday", "night_minutes", "justified", "note", "locked", "leave_request_id",
)


def month_bounds(period: datetime.date) -> tuple[datetime.date, datetime.date]:
    """First and last day of the month `period` opens. A period is always a first of month."""
    if period.day != 1:
        raise ValueError("a period is the first day of a month")
    return period, period.replace(day=calendar.monthrange(period.year, period.month)[1])


def closed_periods(connection: psycopg.Connection, tenant_id: str, dates: Iterable[datetime.date]) -> list[datetime.date]:
    periods = sorted({day.replace(day=1) for day in dates})
    if not periods:
        return []
    rows = connection.execute(
        "SELECT period FROM hr.presence_months WHERE tenant_id = %s AND period = ANY(%s) AND status = 'closed' ORDER BY period",
        (tenant_id, periods),
    ).fetchall()
    return [row[0] for row in rows]


def month_closed_error(periods: list[datetime.date]) -> Err:
    months = ", ".join(period.strftime("%Y-%m") for period in periods)
    return Err("PRESENCE_MONTH_CLOSED", f"presence is closed for {months}", f"la présence est clôturée pour {months}")


def employed_between(
    connection: psycopg.Connection,
    *,
    tenant_id: str,
    date_from: datetime.date,
    date_to: datetime.date,
    department_id: str | None = None,
    employee_ids: list[str] | None = None,
) -> list[dict]:
    """Employees employed on at least one day of [date_from, date_to], by hire and termination dates."""
    clauses = [
        "e.tenant_id = %s", "e.status <> 'inactive'", "e.hire_date <= %s",
        "(e.termination_date IS NULL OR e.termination_date >= %s)",
    ]
    params: list[object] = [tenant_id, date_to, date_from]
    if department_id:
        clauses.append("e.department_id = %s")
        params.append(department_id)
    if employee_ids is not None:
        clauses.append("e.id = ANY(%s)")
        params.append(list(employee_ids))
    rows = connection.execute(
        f"""
        SELECT e.id, e.employee_no, e.first_name || ' ' || e.last_name, e.department_id, e.hire_date, e.termination_date, e.badge_no
        FROM hr.employees e
        WHERE {' AND '.join(clauses)}
        ORDER BY e.employee_no
        """,
        params,
    ).fetchall()
    return [
        {"id": r[0], "employee_no": r[1], "full_name": r[2], "department_id": r[3], "hire_date": r[4], "termination_date": r[5], "badge_no": r[6]}
        for r in rows
    ]


def is_employed(employee: dict, day: datetime.date) -> bool:
    return employee["hire_date"] <= day and (employee["termination_date"] is None or day <= employee["termination_date"])


class PresenceService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    # ---- reads ------------------------------------------------------------------
    def grid(self, *, tenant_id: str, work_date: datetime.date, department_id: str | None = None, schedule_id: str | None = None) -> list[dict]:
        return self._rows(tenant_id=tenant_id, date_from=work_date, date_to=work_date, department_id=department_id, schedule_id=schedule_id)

    def week(self, *, tenant_id: str, date_from: datetime.date, department_id: str | None = None, schedule_id: str | None = None) -> list[dict]:
        return self._rows(
            tenant_id=tenant_id, date_from=date_from, date_to=date_from + datetime.timedelta(days=6),
            department_id=department_id, schedule_id=schedule_id,
        )

    def employee_month(self, *, tenant_id: str, employee_id: str, period: datetime.date) -> Result[dict]:
        first, last = month_bounds(period)
        rows = self._rows(tenant_id=tenant_id, date_from=first, date_to=last, employee_ids=[employee_id])
        if not rows:
            return Err("NOT_FOUND", "employee not found or not employed this month", "employé introuvable ou non employé ce mois-ci")
        return Ok({**rows[0], "period": first.isoformat(), "closed": self.is_month_closed(tenant_id=tenant_id, period=first)})

    def is_month_closed(self, *, tenant_id: str, period: datetime.date) -> bool:
        row = self.connection.execute(
            "SELECT status FROM hr.presence_months WHERE tenant_id = %s AND period = %s", (tenant_id, period)
        ).fetchone()
        return row is not None and row[0] == "closed"

    def existing_days(
        self, *, tenant_id: str, employee_ids: list[str], date_from: datetime.date, date_to: datetime.date
    ) -> dict[tuple[str, datetime.date], dict]:
        if not employee_ids:
            return {}
        rows = self.connection.execute(
            f"""
            SELECT employee_id, work_date, {', '.join(_RECORD_KEYS)}
            FROM hr.presence_days
            WHERE tenant_id = %s AND employee_id = ANY(%s) AND work_date BETWEEN %s AND %s
            """,
            (tenant_id, list(employee_ids), date_from, date_to),
        ).fetchall()
        return {(row[0], row[1]): dict(zip(_RECORD_KEYS, row[2:])) for row in rows}

    def _rows(
        self,
        *,
        tenant_id: str,
        date_from: datetime.date,
        date_to: datetime.date,
        department_id: str | None = None,
        schedule_id: str | None = None,
        employee_ids: list[str] | None = None,
    ) -> list[dict]:
        employees = employed_between(
            self.connection, tenant_id=tenant_id, date_from=date_from, date_to=date_to,
            department_id=department_id, employee_ids=employee_ids,
        )
        if not employees:
            return []
        ids = [employee["id"] for employee in employees]
        resolved = ScheduleService(self.connection).resolve(tenant_id=tenant_id, employee_ids=ids, date_from=date_from, date_to=date_to)
        holidays = HolidayService(self.connection).holiday_map(tenant_id=tenant_id, date_from=date_from, date_to=date_to)
        existing = self.existing_days(tenant_id=tenant_id, employee_ids=ids, date_from=date_from, date_to=date_to)
        rows = []
        for employee in employees:
            days = []
            for day in date_range(date_from, date_to):
                resolved_day = resolved[employee["id"]][day]
                days.append({
                    "work_date": day.isoformat(),
                    "employed": is_employed(employee, day),
                    "assigned": resolved_day.assigned,
                    "schedule_id": resolved_day.schedule_id,
                    "schedule_code": resolved_day.schedule_code,
                    "is_working_day": resolved_day.is_working_day,
                    "is_holiday": day in holidays,
                    "planned_minutes": resolved_day.window.scheduled_minutes if resolved_day.window else 0,
                    "default_status": default_status(resolved_day, is_holiday=day in holidays),
                    "record": existing.get((employee["id"], day)),
                })
            if schedule_id and not any(day["schedule_id"] == schedule_id for day in days):
                continue
            rows.append({
                "employee_id": employee["id"], "employee_no": employee["employee_no"], "full_name": employee["full_name"],
                "department_id": employee["department_id"], "days": days,
            })
        return rows

    # ---- writes -----------------------------------------------------------------
    def save_days(self, *, tenant_id: str, actor_id: str, entries: list[ManualEntry]) -> Result[dict]:
        """Saves what a supervisor typed. Overwrites clock and holiday days (a person's decision
        wins over the device), never an approved leave day, never a closed month."""
        if not entries:
            return Err("INVALID_PRESENCE", "nothing to save", "rien à enregistrer")
        keys = [(entry.employee_id, entry.work_date) for entry in entries]
        if len(set(keys)) != len(keys):
            return Err("INVALID_PRESENCE", "the same employee and day appear twice", "le même employé et le même jour apparaissent deux fois")
        for entry in entries:
            validation = validate_entry(entry)
            if isinstance(validation, Err):
                day = entry.work_date.isoformat()
                return Err(validation.code, f"{day}: {validation.message}", f"{day} : {validation.message_fr}")
        night = PresenceSettingsService(self.connection).night_window(tenant_id=tenant_id)
        if isinstance(night, Err):
            return night
        closed = closed_periods(self.connection, tenant_id, (entry.work_date for entry in entries))
        if closed:
            return month_closed_error(closed)
        date_from = min(entry.work_date for entry in entries)
        date_to = max(entry.work_date for entry in entries)
        ids = sorted({entry.employee_id for entry in entries})
        employees = {
            employee["id"]: employee
            for employee in employed_between(self.connection, tenant_id=tenant_id, date_from=date_from, date_to=date_to, employee_ids=ids)
        }
        for entry in entries:
            employee = employees.get(entry.employee_id)
            if employee is None or not is_employed(employee, entry.work_date):
                day = entry.work_date.isoformat()
                return Err("NOT_EMPLOYED", f"employee {entry.employee_id} is not employed on {day}", f"l'employé {entry.employee_id} n'est pas en poste le {day}")
        existing = self.existing_days(tenant_id=tenant_id, employee_ids=ids, date_from=date_from, date_to=date_to)
        for entry in entries:
            before = existing.get((entry.employee_id, entry.work_date))
            if before is not None and before["source"] == "leave":
                number = employees[entry.employee_id]["employee_no"]
                day = entry.work_date.isoformat()
                return Err(
                    "PRESENCE_DAY_FROM_LEAVE",
                    f"{day} is an approved leave day of {number}; change the leave request instead",
                    f"le {day} est un jour de congé approuvé de {number} ; modifiez plutôt la demande de congé",
                )
        resolved = ScheduleService(self.connection).resolve(tenant_id=tenant_id, employee_ids=ids, date_from=date_from, date_to=date_to)
        holidays = HolidayService(self.connection).holiday_map(tenant_id=tenant_id, date_from=date_from, date_to=date_to)
        for entry in entries:
            window = resolved[entry.employee_id][entry.work_date].window
            figures = figures_for_entry(entry, window, night.value, is_holiday=entry.work_date in holidays)
            day_id = self.upsert_day(
                tenant_id=tenant_id, actor_id=actor_id, employee_id=entry.employee_id, work_date=entry.work_date,
                figures=figures, source="manual", justified=entry.justified, note=entry.note,
            )
            before = existing.get((entry.employee_id, entry.work_date))
            record_audit(
                self.connection, tenant_id=tenant_id, actor_id=actor_id, action="presence_day.saved",
                entity_type="presence_day", entity_id=day_id,
                payload={
                    "employee_id": entry.employee_id, "work_date": entry.work_date.isoformat(),
                    "from_status": before["status"] if before else None, "from_source": before["source"] if before else None,
                    "to_status": figures.status, "worked_minutes": figures.worked_minutes,
                },
            )
        return Ok({"saved": len(entries)})

    def upsert_day(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        employee_id: str,
        work_date: datetime.date,
        figures: DayFigures,
        source: str,
        justified: bool = False,
        note: str | None = None,
        leave_request_id: str | None = None,
        clock_import_id: str | None = None,
    ) -> str:
        """Writes one day, inserting or overwriting. Callers decide who may overwrite whom and check the month is open."""
        row = self.connection.execute(
            """
            INSERT INTO hr.presence_days (id, tenant_id, employee_id, work_date, status, schedule_id, scheduled_minutes,
                                          worked_minutes, late_minutes, ot_minutes_day, ot_minutes_night,
                                          ot_minutes_rest_holiday, night_minutes, source, justified, note,
                                          leave_request_id, clock_import_id, updated_by, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (tenant_id, employee_id, work_date) DO UPDATE SET
                status = EXCLUDED.status, schedule_id = EXCLUDED.schedule_id,
                scheduled_minutes = EXCLUDED.scheduled_minutes, worked_minutes = EXCLUDED.worked_minutes,
                late_minutes = EXCLUDED.late_minutes, ot_minutes_day = EXCLUDED.ot_minutes_day,
                ot_minutes_night = EXCLUDED.ot_minutes_night, ot_minutes_rest_holiday = EXCLUDED.ot_minutes_rest_holiday,
                night_minutes = EXCLUDED.night_minutes, source = EXCLUDED.source, justified = EXCLUDED.justified,
                note = EXCLUDED.note, leave_request_id = EXCLUDED.leave_request_id,
                clock_import_id = EXCLUDED.clock_import_id, updated_by = EXCLUDED.updated_by, updated_at = NOW()
            RETURNING id
            """,
            (
                str(ULID()), tenant_id, employee_id, work_date, figures.status, figures.schedule_id, figures.scheduled_minutes,
                figures.worked_minutes, figures.late_minutes, figures.ot_minutes_day, figures.ot_minutes_night,
                figures.ot_minutes_rest_holiday, figures.night_minutes, source, justified, note, leave_request_id,
                clock_import_id, actor_id,
            ),
        ).fetchone()
        return row[0]
```

- [ ] **Step 8: Append the presence routes**

At the top of `backend/modules/hr/api/presence_router.py` add the imports:

```python
from modules.hr.api.presence_service import PresenceService
from modules.hr.domain.presence import ManualEntry
```

Append at the end of the file:

```python
# ---- presence grid ------------------------------------------------------------------

class PresenceEntryBody(BaseModel):
    employee_id: str
    work_date: datetime.date
    status: str
    worked_minutes: int | None = None
    late_minutes: int = 0
    ot_minutes_day: int = 0
    ot_minutes_night: int = 0
    justified: bool = False
    note: str | None = None


class PresenceDaysBody(BaseModel):
    entries: list[PresenceEntryBody]


@router.get("/presence/grid")
def presence_grid(
    work_date: datetime.date,
    department_id: str | None = None,
    schedule_id: str | None = None,
    tenant: TenantContext = Depends(require_permission("hr.view_presence")),
):
    return _read(lambda c: PresenceService(c).grid(tenant_id=tenant.tenant_id, work_date=work_date, department_id=department_id, schedule_id=schedule_id))


@router.get("/presence/week")
def presence_week(
    date_from: datetime.date,
    department_id: str | None = None,
    schedule_id: str | None = None,
    tenant: TenantContext = Depends(require_permission("hr.view_presence")),
):
    return _read(lambda c: PresenceService(c).week(tenant_id=tenant.tenant_id, date_from=date_from, department_id=department_id, schedule_id=schedule_id))


@router.put("/presence/days")
def save_presence_days(body: PresenceDaysBody, tenant: TenantContext = Depends(require_permission("hr.manage_presence"))):
    entries = [ManualEntry(**entry.model_dump()) for entry in body.entries]
    return _write(lambda c: PresenceService(c).save_days(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, entries=entries))


@router.get("/presence/employee-month")
def presence_employee_month(employee_id: str, period: datetime.date, tenant: TenantContext = Depends(require_permission("hr.view_presence"))):
    return _read_result(lambda c: PresenceService(c).employee_month(tenant_id=tenant.tenant_id, employee_id=employee_id, period=_period(period)))
```

- [ ] **Step 9: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest modules/hr -q`
Expected: all pass, 0 skipped.

- [ ] **Step 10: Commit**

```bash
git add backend/modules/hr/migrations/0012_hr_presence_days.sql backend/modules/hr/domain/presence.py backend/modules/hr/domain/test_presence.py backend/modules/hr/api/presence_service.py backend/modules/hr/api/presence_router.py backend/modules/hr/api/test_presence_grid_integration.py backend/modules/hr/api/test_presence_router_routes.py
git commit -m "feat(hr): presence days and the supervisor grid (day and week)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Punch pairing engine (pure domain)

**Files:**
- Create: `backend/modules/hr/domain/pairing.py`
- Test: `backend/modules/hr/domain/test_pairing.py`

**Interfaces:**
- Consumes: `ShiftWindow`, `shift_window`, `night_overlap_minutes`, `minutes_between`, `ONE_DAY`, `date_range` (Task 1).
- Produces (used by Task 6):
  - `Punch(punched_at: datetime, direction: str = "unknown")` — direction in `in | out | unknown`
  - `PairingConfig(night_start_minute: int, night_end_minute: int, attach_minutes: int, dedupe_seconds: int = 0, late_grace_minutes: int = 0)`
  - `WorkDay(work_date, window: ShiftWindow | None, is_holiday: bool = False, in_range: bool = True)`
  - `DayResult(work_date, status, scheduled_minutes=0, worked_minutes=0, late_minutes=0, ot_minutes_day=0, ot_minutes_night=0, ot_minutes_rest_holiday=0, night_minutes=0, first_punch=None, last_punch=None, anomalies: tuple[str, ...] = ())`
  - `PairingResult(days: list[DayResult], duplicate_punches: int, outside_range_punches: int)`
  - `dedupe(punches, dedupe_seconds) -> tuple[list[Punch], int]`, `attribute(punch, work_days: dict[date, WorkDay], attach_minutes) -> date`, `pair_group(punches) -> tuple[list[tuple[datetime, datetime]], list[str]]`, `compute_day(work_day, punches, config) -> DayResult`, `pair_punches(punches, work_days: list[WorkDay], config) -> PairingResult`
  - Anomaly codes: `MISSING_OUT`, `MISSING_IN`.

- [ ] **Step 1: Write the failing tests**

`backend/modules/hr/domain/test_pairing.py`:

```python
"""The pairing engine, without a database.

The config values (night 21:00-05:00, 240 attach minutes, 60 s duplicates, no grace)
are test inputs; the plant's values are rows of hr.presence_settings.
"""
from __future__ import annotations

import datetime as dt

from modules.hr.domain.pairing import PairingConfig, Punch, WorkDay, pair_punches
from modules.hr.domain.schedule import Schedule, ScheduleDay, date_range, shift_window

CONFIG = PairingConfig(night_start_minute=1260, night_end_minute=300, attach_minutes=240, dedupe_seconds=60)
DAY = Schedule(id="s-day", code="JOUR", days=tuple(ScheduleDay(w, 420, 900) for w in range(6)))
DAY_WITH_BREAK = Schedule(id="s-day-b", code="JOURP", days=tuple(ScheduleDay(w, 420, 900, 30) for w in range(6)))
EVENING = Schedule(id="s-evening", code="SOIR", days=tuple(ScheduleDay(w, 900, 1380) for w in range(6)))
NIGHT = Schedule(id="s-night", code="NUIT", days=tuple(ScheduleDay(w, 1380, 420) for w in range(6)))
AUG_3 = dt.date(2026, 8, 3)  # Monday
AUG_4 = dt.date(2026, 8, 4)
AUG_9 = dt.date(2026, 8, 9)  # Sunday


def at(day: dt.date, hour: int, minute: int = 0, second: int = 0) -> dt.datetime:
    return dt.datetime(day.year, day.month, day.day, hour, minute, second)


def punch(day: dt.date, hour: int, minute: int = 0, direction: str = "unknown", second: int = 0) -> Punch:
    return Punch(at(day, hour, minute, second), direction)


def days_of(schedule: Schedule, first: dt.date, last: dt.date, *, holidays=(), context=()) -> list[WorkDay]:
    return [
        WorkDay(work_date=d, window=shift_window(schedule, d), is_holiday=d in holidays, in_range=d not in context)
        for d in date_range(first, last)
    ]


def result_for(result, day: dt.date):
    return next(item for item in result.days if item.work_date == day)


def test_an_on_time_day_shift_with_ten_minutes_extra_is_day_overtime():
    result = pair_punches([punch(AUG_3, 6, 55, "in"), punch(AUG_3, 15, 5, "out")], days_of(DAY, AUG_3, AUG_3), CONFIG)
    day = result_for(result, AUG_3)
    assert (day.status, day.scheduled_minutes, day.worked_minutes, day.late_minutes) == ("present", 480, 490, 0)
    assert (day.ot_minutes_day, day.ot_minutes_night, day.night_minutes, day.anomalies) == (10, 0, 0, ())


def test_a_late_arrival_counts_its_minutes():
    day = result_for(pair_punches([punch(AUG_3, 7, 20, "in"), punch(AUG_3, 15, 0, "out")], days_of(DAY, AUG_3, AUG_3), CONFIG), AUG_3)
    assert (day.status, day.late_minutes, day.worked_minutes, day.ot_minutes_day) == ("late", 20, 460, 0)


def test_the_grace_setting_forgives_a_few_minutes():
    config = PairingConfig(night_start_minute=1260, night_end_minute=300, attach_minutes=240, late_grace_minutes=5)
    day = result_for(pair_punches([punch(AUG_3, 7, 4, "in"), punch(AUG_3, 15, 0, "out")], days_of(DAY, AUG_3, AUG_3), config), AUG_3)
    assert (day.status, day.late_minutes, day.worked_minutes) == ("present", 0, 476)


def test_a_night_shift_belongs_to_the_day_it_starts_and_keeps_its_morning_out_punch():
    result = pair_punches([punch(AUG_3, 22, 55, "in"), punch(AUG_4, 7, 0, "out")], days_of(NIGHT, AUG_3, AUG_4), CONFIG)
    started = result_for(result, AUG_3)
    assert (started.status, started.worked_minutes, started.night_minutes) == ("present", 485, 365)
    assert (started.ot_minutes_night, started.ot_minutes_day) == (5, 0)  # 22:55-23:00 is inside the night window
    assert result_for(result, AUG_4).status == "absent"


def test_a_missing_out_punch_is_flagged_and_adds_no_time():
    day = result_for(pair_punches([punch(AUG_3, 7, 0, "in")], days_of(DAY, AUG_3, AUG_3), CONFIG), AUG_3)
    assert (day.status, day.worked_minutes, day.anomalies) == ("present", 0, ("MISSING_OUT",))


def test_an_out_punch_with_nothing_open_is_a_missing_in():
    day = result_for(pair_punches([punch(AUG_3, 15, 0, "out")], days_of(DAY, AUG_3, AUG_3), CONFIG), AUG_3)
    assert (day.status, day.worked_minutes, day.late_minutes, day.anomalies) == ("present", 0, 0, ("MISSING_IN",))


def test_repeated_punches_count_once():
    punches = [
        punch(AUG_3, 7, 0, "in"),
        punch(AUG_3, 7, 0, "in"),  # same second
        punch(AUG_3, 7, 0, "in", second=30),  # same direction within 60 s
        punch(AUG_3, 15, 0, "out"),
    ]
    result = pair_punches(punches, days_of(DAY, AUG_3, AUG_3), CONFIG)
    assert result.duplicate_punches == 2
    assert (result_for(result, AUG_3).worked_minutes, result_for(result, AUG_3).anomalies) == (480, ())


def test_an_in_while_one_is_open_closes_nothing_and_is_flagged():
    punches = [punch(AUG_3, 7, 0, "in"), punch(AUG_3, 11, 0, "in"), punch(AUG_3, 15, 0, "out")]
    day = result_for(pair_punches(punches, days_of(DAY, AUG_3, AUG_3), CONFIG), AUG_3)
    assert (day.worked_minutes, day.late_minutes, day.anomalies) == (240, 0, ("MISSING_OUT",))


def test_unknown_directions_alternate_in_and_out():
    day = result_for(pair_punches([punch(AUG_3, 7, 0), punch(AUG_3, 15, 0)], days_of(DAY, AUG_3, AUG_3), CONFIG), AUG_3)
    assert (day.worked_minutes, day.anomalies) == (480, ())


def test_unknown_directions_do_not_carry_a_forgotten_punch_into_the_next_day():
    punches = [punch(AUG_3, 7, 0), punch(AUG_4, 6, 58), punch(AUG_4, 15, 1)]
    result = pair_punches(punches, days_of(DAY, AUG_3, AUG_4), CONFIG)
    assert (result_for(result, AUG_3).worked_minutes, result_for(result, AUG_3).anomalies) == (0, ("MISSING_OUT",))
    assert (result_for(result, AUG_4).worked_minutes, result_for(result, AUG_4).anomalies) == (483, ())


def test_work_on_a_rest_day_is_rest_holiday_overtime():
    result = pair_punches([punch(AUG_9, 8, 0, "in"), punch(AUG_9, 12, 0, "out")], days_of(DAY, dt.date(2026, 8, 8), AUG_9), CONFIG)
    sunday = result_for(result, AUG_9)
    assert (sunday.status, sunday.scheduled_minutes, sunday.worked_minutes, sunday.ot_minutes_rest_holiday) == ("present", 0, 240, 240)
    assert result_for(result, dt.date(2026, 8, 8)).status == "absent"


def test_a_public_holiday_is_holiday_when_not_worked_and_overtime_when_worked():
    off = result_for(pair_punches([], days_of(DAY, AUG_3, AUG_3, holidays={AUG_3}), CONFIG), AUG_3)
    worked = result_for(
        pair_punches([punch(AUG_3, 7, 0, "in"), punch(AUG_3, 15, 0, "out")], days_of(DAY, AUG_3, AUG_3, holidays={AUG_3}), CONFIG), AUG_3
    )
    assert (off.status, off.scheduled_minutes) == ("holiday", 0)
    assert (worked.status, worked.scheduled_minutes, worked.worked_minutes, worked.ot_minutes_rest_holiday, worked.late_minutes) == ("present", 0, 480, 480, 0)


def test_no_punch_is_absent_on_a_working_day_and_rest_on_a_rest_day():
    result = pair_punches([], days_of(DAY, AUG_3, AUG_9), CONFIG)
    assert result_for(result, AUG_3).status == "absent"
    assert result_for(result, AUG_9).status == "rest"


def test_evening_overtime_after_21h_is_night_overtime():
    day = result_for(pair_punches([punch(AUG_3, 15, 0, "in"), punch(AUG_3, 23, 30, "out")], days_of(EVENING, AUG_3, AUG_3), CONFIG), AUG_3)
    assert (day.worked_minutes, day.ot_minutes_night, day.ot_minutes_day, day.night_minutes) == (510, 30, 0, 150)


def test_a_punch_that_belongs_to_the_day_before_the_range_is_not_misplaced():
    july_31 = dt.date(2026, 7, 31)
    days = days_of(NIGHT, july_31, dt.date(2026, 8, 1), context={july_31})
    result = pair_punches([punch(dt.date(2026, 8, 1), 6, 58, "out")], days, CONFIG)
    assert result.outside_range_punches == 1
    assert [item.work_date for item in result.days] == [dt.date(2026, 8, 1)]
    assert (result.days[0].status, result.days[0].anomalies) == ("absent", ())


def test_a_switch_from_night_to_day_shift_splits_the_punches_by_direction():
    switch = Schedule(id="s-switch", code="SWITCH", days=(ScheduleDay(6, 1380, 420), ScheduleDay(0, 420, 900)))
    sunday = dt.date(2026, 8, 2)
    punches = [punch(sunday, 22, 58, "in"), punch(AUG_3, 7, 0, "out"), punch(AUG_3, 7, 5, "in"), punch(AUG_3, 15, 0, "out")]
    result = pair_punches(punches, days_of(switch, sunday, AUG_3), CONFIG)
    assert result_for(result, sunday).worked_minutes == 482
    assert (result_for(result, AUG_3).worked_minutes, result_for(result, AUG_3).late_minutes) == (475, 5)


def test_the_schedule_break_is_not_worked_time():
    day = result_for(pair_punches([punch(AUG_3, 7, 0, "in"), punch(AUG_3, 15, 0, "out")], days_of(DAY_WITH_BREAK, AUG_3, AUG_3), CONFIG), AUG_3)
    assert (day.scheduled_minutes, day.worked_minutes, day.ot_minutes_day) == (450, 450, 0)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python -m pytest modules/hr/domain/test_pairing.py -q`
Expected: collection error `No module named 'modules.hr.domain.pairing'`.

- [ ] **Step 3: Write the engine**

`backend/modules/hr/domain/pairing.py`:

```python
"""Turning clock punches into worked days: the pairing engine.

Pure: no database. Rules, each pinned by test_pairing.py:

* Punches of the same second, or of the same direction within `dedupe_seconds`, are one punch.
* A punch belongs to the shift of its own date or of the date before whose window, widened
  by `attach_minutes` on both sides, contains it; when both do, the nearer one (an `in`
  measured to the shift start, an `out` to its end, an `unknown` to either). A punch no
  shift claims belongs to its calendar date (work on a rest day). A night shift therefore
  keeps its morning out-punch: the 23-07 shift of the 3rd owns the 07:00 punch of the 4th.
* Within one day, punches pair in time order: `in` opens, `out` closes, `unknown` does
  whichever is due. An `in` while one is open, or one left open at the end, is MISSING_OUT;
  an `out` with nothing open is MISSING_IN. Unpaired punches add no time, and a forgotten
  punch never shifts the pairing of another day.
* Worked minutes are the paired time less the schedule break (on a working day). Lateness
  is the first arrival (an `in` or `unknown` punch) after the shift start, beyond the grace
  minutes; a day with only an out-punch has no measurable lateness.
* On a working day, worked minutes beyond the scheduled ones are overtime; the part of it
  outside the shift window and inside the night window is night overtime, the rest day
  overtime. On a rest day or a public holiday every worked minute is rest/holiday overtime.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass

from modules.hr.domain.schedule import ONE_DAY, ShiftWindow, minutes_between, night_overlap_minutes

Interval = tuple[datetime.datetime, datetime.datetime]


@dataclass(frozen=True)
class Punch:
    punched_at: datetime.datetime
    direction: str = "unknown"  # 'in' | 'out' | 'unknown'


@dataclass(frozen=True)
class PairingConfig:
    night_start_minute: int
    night_end_minute: int
    attach_minutes: int
    dedupe_seconds: int = 0
    late_grace_minutes: int = 0


@dataclass(frozen=True)
class WorkDay:
    work_date: datetime.date
    window: ShiftWindow | None  # None: a rest day (or no schedule)
    is_holiday: bool = False
    in_range: bool = True  # False: a neighbouring day loaded only so its punches are not misplaced


@dataclass(frozen=True)
class DayResult:
    work_date: datetime.date
    status: str
    scheduled_minutes: int = 0
    worked_minutes: int = 0
    late_minutes: int = 0
    ot_minutes_day: int = 0
    ot_minutes_night: int = 0
    ot_minutes_rest_holiday: int = 0
    night_minutes: int = 0
    first_punch: datetime.datetime | None = None
    last_punch: datetime.datetime | None = None
    anomalies: tuple[str, ...] = ()


@dataclass(frozen=True)
class PairingResult:
    days: list[DayResult]
    duplicate_punches: int
    outside_range_punches: int


def dedupe(punches: list[Punch], dedupe_seconds: int) -> tuple[list[Punch], int]:
    kept: list[Punch] = []
    dropped = 0
    for punch in sorted(punches, key=lambda p: p.punched_at):
        if kept:
            previous = kept[-1]
            gap = (punch.punched_at - previous.punched_at).total_seconds()
            if gap == 0 or (gap <= dedupe_seconds and punch.direction == previous.direction):
                dropped += 1
                continue
        kept.append(punch)
    return kept, dropped


def _distance(punch: Punch, window: ShiftWindow) -> int:
    to_start = abs(minutes_between(window.start, punch.punched_at))
    to_end = abs(minutes_between(window.end, punch.punched_at))
    if punch.direction == "in":
        return to_start
    if punch.direction == "out":
        return to_end
    return min(to_start, to_end)


def attribute(punch: Punch, work_days: dict[datetime.date, WorkDay], attach_minutes: int) -> datetime.date:
    attach = datetime.timedelta(minutes=attach_minutes)
    moment = punch.punched_at
    best: tuple[int, int, datetime.date] | None = None
    for day in (moment.date() - ONE_DAY, moment.date()):
        work_day = work_days.get(day)
        if work_day is None or work_day.window is None:
            continue
        window = work_day.window
        if not window.start - attach <= moment <= window.end + attach:
            continue
        candidate = (_distance(punch, window), -day.toordinal(), day)  # nearer first, then the later day
        if best is None or candidate[:2] < best[:2]:
            best = candidate
    return best[2] if best is not None else moment.date()


def pair_group(punches: list[Punch]) -> tuple[list[Interval], list[str]]:
    intervals: list[Interval] = []
    anomalies: list[str] = []
    opened: datetime.datetime | None = None
    for punch in sorted(punches, key=lambda p: p.punched_at):
        direction = punch.direction
        if direction == "unknown":
            direction = "out" if opened is not None else "in"
        if direction == "in":
            if opened is not None:
                anomalies.append("MISSING_OUT")
            opened = punch.punched_at
        elif opened is None:
            anomalies.append("MISSING_IN")
        else:
            intervals.append((opened, punch.punched_at))
            opened = None
    if opened is not None:
        anomalies.append("MISSING_OUT")
    return intervals, anomalies


def _outside(start: datetime.datetime, end: datetime.datetime, window: ShiftWindow) -> list[Interval]:
    segments = []
    if start < window.start:
        segments.append((start, min(end, window.start)))
    if end > window.end:
        segments.append((max(start, window.end), end))
    return [(a, b) for a, b in segments if b > a]


def compute_day(work_day: WorkDay, punches: list[Punch], config: PairingConfig) -> DayResult:
    window = work_day.window
    expected = window is not None and not work_day.is_holiday
    scheduled = window.scheduled_minutes if expected else 0
    if not punches:
        if window is not None and work_day.is_holiday:
            status = "holiday"
        else:
            status = "absent" if expected else "rest"
        return DayResult(work_date=work_day.work_date, status=status, scheduled_minutes=scheduled)
    ordered = sorted(punches, key=lambda p: p.punched_at)
    intervals, anomalies = pair_group(ordered)
    night = (config.night_start_minute, config.night_end_minute)
    raw = sum(minutes_between(start, end) for start, end in intervals)
    worked = raw - (min(window.break_minutes, raw) if expected else 0)
    night_minutes = sum(night_overlap_minutes(start, end, *night) for start, end in intervals)
    arrivals = [punch.punched_at for punch in ordered if punch.direction != "out"]
    late = ot_day = ot_night = ot_rest_holiday = 0
    if expected:
        if arrivals:
            delay = minutes_between(window.start, arrivals[0])
            late = delay if delay > config.late_grace_minutes else 0
        extra = max(0, worked - scheduled)
        outside = [segment for start, end in intervals for segment in _outside(start, end, window)]
        night_outside = sum(night_overlap_minutes(start, end, *night) for start, end in outside)
        ot_night = min(night_outside, extra)
        ot_day = extra - ot_night
    else:
        ot_rest_holiday = worked
    return DayResult(
        work_date=work_day.work_date,
        status="late" if late > 0 else "present",
        scheduled_minutes=scheduled,
        worked_minutes=worked,
        late_minutes=late,
        ot_minutes_day=ot_day,
        ot_minutes_night=ot_night,
        ot_minutes_rest_holiday=ot_rest_holiday,
        night_minutes=night_minutes,
        first_punch=ordered[0].punched_at,
        last_punch=ordered[-1].punched_at,
        anomalies=tuple(anomalies),
    )


def pair_punches(punches: list[Punch], work_days: list[WorkDay], config: PairingConfig) -> PairingResult:
    """One DayResult per in-range work day; punches owned by a context day are counted, not used."""
    kept, duplicates = dedupe(punches, config.dedupe_seconds)
    by_date = {work_day.work_date: work_day for work_day in work_days}
    groups: dict[datetime.date, list[Punch]] = {day: [] for day in by_date}
    outside = 0
    for punch in kept:
        day = attribute(punch, by_date, config.attach_minutes)
        if day in by_date and by_date[day].in_range:
            groups[day].append(punch)
        else:
            outside += 1
    days = [compute_day(by_date[day], groups[day], config) for day in sorted(by_date) if by_date[day].in_range]
    return PairingResult(days=days, duplicate_punches=duplicates, outside_range_punches=outside)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest modules/hr/domain/test_pairing.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/hr/domain/pairing.py backend/modules/hr/domain/test_pairing.py
git commit -m "feat(hr): punch pairing engine - night shifts, missing punches, duplicates, overtime bands

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Clock CSV parsing with device profiles (pure domain)

**Files:**
- Create: `backend/modules/hr/domain/clock_csv.py`
- Test: `backend/modules/hr/domain/test_clock_csv.py`

**Interfaces:**
- Consumes: `core.domain.result`.
- Produces (used by Task 6 and the seed):
  - `ClockProfile(delimiter, has_header, badge_column, timestamp_column, timestamp_format, time_column=None, direction_column=None, in_values: tuple[str, ...] = (), out_values: tuple[str, ...] = ())` — with a header row, columns are header names (case-insensitive); without, 1-based positions written as digits. With `time_column`, the parsed text is `"<timestamp cell> <time cell>"`.
  - `ParsedRow(line_no, raw, badge_no, punched_at, direction, error_code)`; row error codes `MISSING_COLUMN`, `MISSING_BADGE`, `BAD_TIMESTAMP`, `DUPLICATE_PUNCH`.
  - `validate_profile(*, code, name, delimiter, has_header, badge_column, timestamp_column, timestamp_format, time_column, direction_column) -> Result[None]` (code `INVALID_CLOCK_PROFILE`)
  - `parse_clock_csv(content: str, profile: ClockProfile) -> Result[list[ParsedRow]]` (file-level codes `CLOCK_COLUMN_MISSING`, `CLOCK_FILE_EMPTY`)

- [ ] **Step 1: Write the failing tests**

`backend/modules/hr/domain/test_clock_csv.py`:

```python
"""Reading clock-device exports with a saved profile, without a database."""
from __future__ import annotations

import datetime as dt

import pytest

from core.domain.result import Err, Ok
from modules.hr.domain.clock_csv import ClockProfile, parse_clock_csv, validate_profile

PROFILE = ClockProfile(
    delimiter=";", has_header=True, badge_column="Badge", timestamp_column="DateHeure",
    timestamp_format="%d/%m/%Y %H:%M", direction_column="Etat", in_values=("Entrée", "IN"), out_values=("Sortie", "OUT"),
)


def _rows(result):
    assert isinstance(result, Ok), result
    return [(row.line_no, row.badge_no, row.punched_at, row.direction, row.error_code) for row in result.value]


def test_a_header_file_is_read_by_column_name_whatever_the_case_of_the_values():
    content = "Badge;DateHeure;Etat\nB001;03/08/2026 06:55;Entrée\nB001;03/08/2026 15:05;sortie\n"
    assert _rows(parse_clock_csv(content, PROFILE)) == [
        (2, "B001", dt.datetime(2026, 8, 3, 6, 55), "in", None),
        (3, "B001", dt.datetime(2026, 8, 3, 15, 5), "out", None),
    ]


def test_an_excel_export_with_bom_and_crlf_is_read():
    content = "﻿Badge;DateHeure;Etat\r\nB001;03/08/2026 06:55;IN\r\n\r\nB002;03/08/2026 07:02;OUT\r\n"
    assert _rows(parse_clock_csv(content, PROFILE)) == [
        (2, "B001", dt.datetime(2026, 8, 3, 6, 55), "in", None),
        (4, "B002", dt.datetime(2026, 8, 3, 7, 2), "out", None),
    ]


def test_a_headerless_file_uses_positions_from_one_and_a_separate_time_column():
    profile = ClockProfile(
        delimiter=",", has_header=False, badge_column="2", timestamp_column="3", time_column="4",
        timestamp_format="%Y-%m-%d %H:%M:%S",
    )
    content = "1,0042,2026-08-03,23:01:10\n2,0042,2026-08-04,07:02:00\n"
    assert _rows(parse_clock_csv(content, profile)) == [
        (1, "0042", dt.datetime(2026, 8, 3, 23, 1, 10), "unknown", None),  # leading zeros kept
        (2, "0042", dt.datetime(2026, 8, 4, 7, 2), "unknown", None),
    ]


def test_bad_rows_are_flagged_not_dropped():
    content = (
        "Badge;DateHeure;Etat\n"
        ";03/08/2026 07:00;IN\n"  # no badge
        "B002;32/08/2026 07:00;IN\n"  # no 32 August
        "B003;03/08/2026 07:00;Pause\n"  # unknown in/out value: not an error
        "B004\n"  # line too short
        "B005;03/08/2026 07:00:15;IN\n"  # seconds the profile does not expect
    )
    result = parse_clock_csv(content, PROFILE)
    assert [(line, error) for line, _, _, _, error in _rows(result)] == [
        (2, "MISSING_BADGE"), (3, "BAD_TIMESTAMP"), (4, None), (5, "MISSING_COLUMN"), (6, "BAD_TIMESTAMP"),
    ]
    assert result.value[2].direction == "unknown"


def test_a_punch_repeated_in_the_file_is_flagged_on_its_second_line():
    content = "Badge;DateHeure;Etat\nB001;03/08/2026 07:00;IN\nB001;03/08/2026 07:00;IN\n"
    assert [error for *_, error in _rows(parse_clock_csv(content, PROFILE))] == [None, "DUPLICATE_PUNCH"]


def test_a_missing_header_column_refuses_the_whole_file():
    result = parse_clock_csv("Badge;Date\nB001;03/08/2026 07:00\n", PROFILE)
    assert isinstance(result, Err) and result.code == "CLOCK_COLUMN_MISSING" and "DateHeure" in result.message_fr


@pytest.mark.parametrize("content", ["", "Badge;DateHeure;Etat\n", "Badge;DateHeure;Etat\n\n\n"])
def test_a_file_without_punches_is_refused(content):
    result = parse_clock_csv(content, PROFILE)
    assert isinstance(result, Err) and result.code == "CLOCK_FILE_EMPTY" and result.message_fr


def test_profile_validation():
    good = dict(
        code="ZK", name="Entrée", delimiter=";", has_header=True, badge_column="Badge", timestamp_column="DateHeure",
        timestamp_format="%d/%m/%Y %H:%M", time_column=None, direction_column=None,
    )
    assert isinstance(validate_profile(**good), Ok)
    for change in ({"delimiter": ";;"}, {"code": " "}, {"has_header": False}, {"timestamp_format": "dd/mm/yyyy"}, {"badge_column": ""}):
        result = validate_profile(**{**good, **change})
        assert isinstance(result, Err) and result.code == "INVALID_CLOCK_PROFILE" and result.message_fr
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python -m pytest modules/hr/domain/test_clock_csv.py -q`
Expected: collection error `No module named 'modules.hr.domain.clock_csv'`.

- [ ] **Step 3: Write the parser**

`backend/modules/hr/domain/clock_csv.py`:

```python
"""Reading a clock-device CSV export with a saved device profile. Pure: no database.

A row that cannot be read is kept with an error code (the reviewer sees it); only a file
whose header lacks a profile column, or that holds no punch at all, is refused whole.
"""
from __future__ import annotations

import csv
import datetime
import io
from dataclasses import dataclass

from core.domain.result import Err, Ok, Result

_EMPTY = Err("CLOCK_FILE_EMPTY", "the file has no punch rows", "le fichier ne contient aucun pointage")


@dataclass(frozen=True)
class ClockProfile:
    delimiter: str
    has_header: bool
    badge_column: str
    timestamp_column: str
    timestamp_format: str
    time_column: str | None = None
    direction_column: str | None = None
    in_values: tuple[str, ...] = ()
    out_values: tuple[str, ...] = ()


@dataclass(frozen=True)
class ParsedRow:
    line_no: int
    raw: str
    badge_no: str | None
    punched_at: datetime.datetime | None
    direction: str
    error_code: str | None


def validate_profile(
    *,
    code: str,
    name: str,
    delimiter: str,
    has_header: bool,
    badge_column: str,
    timestamp_column: str,
    timestamp_format: str,
    time_column: str | None,
    direction_column: str | None,
) -> Result[None]:
    if not code.strip() or not name.strip():
        return Err("INVALID_CLOCK_PROFILE", "profile code and name are required", "le code et le nom du profil sont obligatoires")
    if len(delimiter) != 1:
        return Err("INVALID_CLOCK_PROFILE", "the separator is a single character", "le séparateur est un seul caractère")
    if not badge_column.strip() or not timestamp_column.strip():
        return Err("INVALID_CLOCK_PROFILE", "the badge and date/time columns are required", "les colonnes badge et date/heure sont obligatoires")
    columns = [column for column in (badge_column, timestamp_column, time_column, direction_column) if column]
    if not has_header and not all(column.strip().isdigit() and int(column) >= 1 for column in columns):
        return Err(
            "INVALID_CLOCK_PROFILE",
            "without a header line, columns are positions starting at 1",
            "sans ligne d'en-tête, les colonnes sont des positions à partir de 1",
        )
    if "%" not in timestamp_format:
        return Err(
            "INVALID_CLOCK_PROFILE",
            "the date/time format uses codes such as %d/%m/%Y %H:%M",
            "le format date/heure utilise des codes comme %d/%m/%Y %H:%M",
        )
    return Ok(None)


def _position(column: str, header: list[str] | None) -> int | None:
    if header is None:
        return int(column) - 1
    wanted = column.strip().casefold()
    return next((index for index, name in enumerate(header) if name.strip().casefold() == wanted), None)


def parse_clock_csv(content: str, profile: ClockProfile) -> Result[list[ParsedRow]]:
    reader = csv.reader(io.StringIO(content.lstrip("﻿"), newline=""), delimiter=profile.delimiter)
    header: list[str] | None = None
    if profile.has_header:
        header = next(reader, None)
        if header is None:
            return _EMPTY
    wanted = {"badge": profile.badge_column, "timestamp": profile.timestamp_column}
    if profile.time_column:
        wanted["time"] = profile.time_column
    if profile.direction_column:
        wanted["direction"] = profile.direction_column
    positions: dict[str, int] = {}
    for role, column in wanted.items():
        index = _position(column, header)
        if index is None:
            return Err("CLOCK_COLUMN_MISSING", f"column {column!r} is not in the file header", f"la colonne {column!r} est absente de l'en-tête du fichier")
        positions[role] = index
    needed = max(positions.values())
    ins = {value.strip().casefold() for value in profile.in_values}
    outs = {value.strip().casefold() for value in profile.out_values}
    rows: list[ParsedRow] = []
    seen: set[tuple[str, datetime.datetime]] = set()
    for record in reader:
        line_no = reader.line_num
        if not any(cell.strip() for cell in record):
            continue
        raw = profile.delimiter.join(record)
        if len(record) <= needed:
            rows.append(ParsedRow(line_no, raw, None, None, "unknown", "MISSING_COLUMN"))
            continue
        badge = record[positions["badge"]].strip() or None
        text = record[positions["timestamp"]].strip()
        if "time" in positions:
            text = f"{text} {record[positions['time']].strip()}"
        try:
            punched_at: datetime.datetime | None = datetime.datetime.strptime(text, profile.timestamp_format)
        except ValueError:
            punched_at = None
        direction = "unknown"
        if "direction" in positions:
            value = record[positions["direction"]].strip().casefold()
            direction = "in" if value in ins else "out" if value in outs else "unknown"
        error = None
        if badge is None:
            error = "MISSING_BADGE"
        elif punched_at is None:
            error = "BAD_TIMESTAMP"
        elif (badge, punched_at) in seen:
            error = "DUPLICATE_PUNCH"
        else:
            seen.add((badge, punched_at))
        rows.append(ParsedRow(line_no, raw, badge, punched_at, direction, error))
    if not rows:
        return _EMPTY
    return Ok(rows)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest modules/hr/domain/test_clock_csv.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/hr/domain/clock_csv.py backend/modules/hr/domain/test_clock_csv.py
git commit -m "feat(hr): clock CSV parsing with device profiles

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Clock imports — profiles, staging, review, commit into presence days

**Files:**
- Create: `backend/modules/hr/migrations/0013_hr_clock_imports.sql`
- Create: `backend/modules/hr/api/clock_import_service.py`
- Modify: `backend/modules/hr/api/presence_router.py` (append the clock section; `from pydantic import BaseModel` becomes `from pydantic import BaseModel, Field`)
- Test: `backend/modules/hr/api/test_clock_import_integration.py`, `backend/modules/hr/api/test_presence_router_routes.py` (append one test)

**Interfaces:**
- Consumes: `parse_clock_csv`, `validate_profile`, `ClockProfile` (Task 5); `pair_punches`, `PairingConfig`, `Punch`, `WorkDay` (Task 4); `PresenceService.existing_days/upsert_day`, `closed_periods`, `month_closed_error`, `employed_between`, `is_employed` (Task 3); `PROTECTED_SOURCES`, `DayFigures` (Task 3); `ScheduleService.resolve`, `HolidayService.holiday_map`, `PresenceSettingsService.get` (Task 2).
- Produces:
  - `ClockProfileService(connection)`: `list_profiles(*, tenant_id) -> list[dict]` (dict: `id, code, name, delimiter, has_header, badge_column, timestamp_column, time_column, timestamp_format, direction_column, in_values, out_values, active`); `get_profile(*, tenant_id, profile_id) -> dict | None`; `create_profile(*, tenant_id, actor_id, code, name, delimiter, has_header, badge_column, timestamp_column, timestamp_format, time_column=None, direction_column=None, in_values=None, out_values=None) -> Result[dict]`; `update_profile(*, tenant_id, actor_id, profile_id, name=None, delimiter=None, has_header=None, badge_column=None, timestamp_column=None, timestamp_format=None, time_column=None, direction_column=None, in_values=None, out_values=None, active=None) -> Result[dict]` (an empty string clears `time_column` / `direction_column`; `code` is not editable).
  - `ClockImportService(connection)`: `list_imports(*, tenant_id) -> list[dict]` (dict: `id, profile_id, profile_code, file_name, date_from, date_to, status, total_rows, valid_rows, error_rows, uploaded_by, uploaded_by_email, uploaded_at, decided_at, result`); `get_import(*, tenant_id, import_id) -> Result[dict]` (+ `rows: [{line_no, raw, badge_no, employee_id, employee_no, full_name, punched_at, direction, error_code}]`); `stage(*, tenant_id, actor_id, profile_id, file_name, content, date_from, date_to) -> Result[dict]` (same shape as `get_import`); `commit(*, tenant_id, actor_id, import_id) -> Result[dict]` (`{id, days_written, conflicts, anomalies, unscheduled, duplicate_punches, outside_range_punches}`); `discard(*, tenant_id, actor_id, import_id) -> Result[dict]`.
  - Staging row codes added to the parser's: `UNKNOWN_BADGE`, `OUTSIDE_RANGE` (punch more than one day outside the covered days), `DUPLICATE_PUNCH` (already imported). Refusals: `IMPORT_NOT_STAGED`, `PRESENCE_SETTINGS_MISSING`, `PRESENCE_MONTH_CLOSED`, `INVALID_IMPORT`.
  - Conflict dict: `employee_id, employee_no, full_name, work_date, kept_status, kept_source, clock_status, clock_worked_minutes`; anomaly dict: `employee_id, employee_no, full_name, work_date, codes`.
  - Routes: `GET/POST /hr/clock-profiles`, `PATCH /hr/clock-profiles/{profile_id}`, `GET/POST /hr/clock-imports`, `GET /hr/clock-imports/{import_id}`, `POST /hr/clock-imports/{import_id}/commit`, `POST /hr/clock-imports/{import_id}/discard`. The upload body is JSON `{profile_id, file_name, content, date_from, date_to}` — the browser reads the file as text (no multipart dependency).

- [ ] **Step 1: Write and apply the migration**

`backend/modules/hr/migrations/0013_hr_clock_imports.sql`:

```sql
-- How to read each clock model's CSV export.
CREATE TABLE IF NOT EXISTS hr.clock_profiles (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    delimiter TEXT NOT NULL CHECK (char_length(delimiter) = 1),
    has_header BOOLEAN NOT NULL,
    badge_column TEXT NOT NULL,
    timestamp_column TEXT NOT NULL,
    time_column TEXT,
    timestamp_format TEXT NOT NULL,
    direction_column TEXT,
    in_values TEXT[] NOT NULL DEFAULT '{}',
    out_values TEXT[] NOT NULL DEFAULT '{}',
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, code)
);

-- An uploaded file: staged for review, then committed or discarded. Rows stay for history.
CREATE TABLE IF NOT EXISTS hr.clock_imports (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    profile_id TEXT NOT NULL REFERENCES hr.clock_profiles (id),
    file_name TEXT NOT NULL,
    date_from DATE NOT NULL,
    date_to DATE NOT NULL,
    status TEXT NOT NULL DEFAULT 'staged' CHECK (status IN ('staged', 'committed', 'discarded')),
    total_rows INTEGER NOT NULL DEFAULT 0,
    valid_rows INTEGER NOT NULL DEFAULT 0,
    error_rows INTEGER NOT NULL DEFAULT 0,
    uploaded_by TEXT NOT NULL,
    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    decided_by TEXT,
    decided_at TIMESTAMPTZ,
    result JSONB,
    CHECK (date_to >= date_from)
);

CREATE TABLE IF NOT EXISTS hr.clock_import_rows (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    import_id TEXT NOT NULL REFERENCES hr.clock_imports (id) ON DELETE CASCADE,
    line_no INTEGER NOT NULL,
    raw TEXT NOT NULL,
    badge_no TEXT,
    employee_id TEXT REFERENCES hr.employees (id),
    punched_at TIMESTAMP,
    direction TEXT NOT NULL DEFAULT 'unknown' CHECK (direction IN ('in', 'out', 'unknown')),
    error_code TEXT,
    UNIQUE (import_id, line_no)
);

-- The device's wall-clock time (no time zone): what the clock printed is what counts.
CREATE TABLE IF NOT EXISTS hr.clock_punches (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    employee_id TEXT NOT NULL REFERENCES hr.employees (id),
    badge_no TEXT NOT NULL,
    punched_at TIMESTAMP NOT NULL,
    direction TEXT NOT NULL CHECK (direction IN ('in', 'out', 'unknown')),
    import_id TEXT NOT NULL REFERENCES hr.clock_imports (id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, badge_no, punched_at)
);

CREATE INDEX IF NOT EXISTS hr_clock_punches_employee_idx ON hr.clock_punches (tenant_id, employee_id, punched_at);

ALTER TABLE hr.presence_days DROP CONSTRAINT IF EXISTS presence_days_clock_import_id_fkey;
ALTER TABLE hr.presence_days ADD CONSTRAINT presence_days_clock_import_id_fkey
    FOREIGN KEY (clock_import_id) REFERENCES hr.clock_imports (id);
```

Run: `DATABASE_URL=postgresql://erp:erp@localhost:5432/erp .venv/Scripts/python.exe -c "from core.migrations.runner import apply_all_migrations; apply_all_migrations()"`
Expected: exit 0.

- [ ] **Step 2: Write the failing integration tests and route test**

`backend/modules/hr/api/test_clock_import_integration.py`:

```python
"""Clock imports against a real database: staging, commit into presence days, manual wins."""
from __future__ import annotations

import datetime

import pytest

from core.domain.result import Err, Ok
from modules.hr.api.clock_import_service import ClockImportService, ClockProfileService
from modules.hr.api.presence_service import PresenceService
from modules.hr.api.presence_testkit import AUG_3, TENANT, close_month_directly, insert_presence_row, presence_env, presence_row  # noqa: F401
from modules.hr.domain.presence import ManualEntry

AUG_4 = datetime.date(2026, 8, 4)
HEADER = "Badge;DateHeure;Etat\n"


@pytest.fixture
def profile_id(db, presence_env) -> str:
    created = ClockProfileService(db).create_profile(
        tenant_id=TENANT, actor_id=presence_env.actor, code="ZK", name="Pointeuse entrée", delimiter=";", has_header=True,
        badge_column="Badge", timestamp_column="DateHeure", timestamp_format="%d/%m/%Y %H:%M",
        direction_column="Etat", in_values=["IN"], out_values=["OUT"],
    )
    assert isinstance(created, Ok), created
    return created.value["id"]


def _stage(db, env, profile_id, lines, *, date_from=AUG_3, date_to=AUG_4, file_name="aout.csv"):
    return ClockImportService(db).stage(
        tenant_id=TENANT, actor_id=env.actor, profile_id=profile_id, file_name=file_name,
        content=HEADER + "\n".join(lines) + "\n", date_from=date_from, date_to=date_to,
    )


def _commit(db, env, import_id):
    return ClockImportService(db).commit(tenant_id=TENANT, actor_id=env.actor, import_id=import_id)


def _punches(db) -> int:
    return db.execute("SELECT count(*) FROM hr.clock_punches WHERE tenant_id = %s", (TENANT,)).fetchone()[0]


def test_staging_flags_unknown_badges_and_bad_times_and_writes_nothing_yet(db, presence_env, profile_id):
    staged = _stage(db, presence_env, profile_id, ["B001;03/08/2026 06:58;IN", "B001;03/08/2026 15:02;OUT", "B999;03/08/2026 07:00;IN", "B002;xx;IN"])
    assert isinstance(staged, Ok)
    detail = staged.value
    assert (detail["status"], detail["total_rows"], detail["valid_rows"], detail["error_rows"]) == ("staged", 4, 2, 2)
    assert [row["error_code"] for row in detail["rows"]] == [None, None, "UNKNOWN_BADGE", "BAD_TIMESTAMP"]
    assert detail["rows"][0]["employee_no"] == "P-001"
    assert _punches(db) == 0 and presence_row(db, presence_env.day_worker, AUG_3) is None


def test_commit_turns_punches_into_days_and_a_night_stays_on_its_start_day(db, presence_env, profile_id):
    staged = _stage(db, presence_env, profile_id, [
        "B001;03/08/2026 06:58;IN", "B001;03/08/2026 15:02;OUT", "B002;03/08/2026 22:57;IN", "B002;04/08/2026 07:03;OUT",
    ])
    committed = _commit(db, presence_env, staged.value["id"])
    assert isinstance(committed, Ok) and committed.value["days_written"] == 4
    day = presence_row(db, presence_env.day_worker, AUG_3)
    assert (day["status"], day["worked_minutes"], day["source"]) == ("present", 484, "clock")
    assert presence_row(db, presence_env.day_worker, AUG_4)["status"] == "absent"
    night = presence_row(db, presence_env.night_worker, AUG_3)
    assert (night["worked_minutes"], night["night_minutes"]) == (486, 363)
    assert presence_row(db, presence_env.night_worker, AUG_4)["status"] == "absent"
    assert ClockImportService(db).get_import(tenant_id=TENANT, import_id=staged.value["id"]).value["status"] == "committed"


def test_a_manual_day_and_a_leave_day_win_over_the_clock_and_are_listed(db, presence_env, profile_id):
    saved = PresenceService(db).save_days(tenant_id=TENANT, actor_id=presence_env.actor, entries=[
        ManualEntry(employee_id=presence_env.day_worker, work_date=AUG_3, status="mission"),
    ])
    assert isinstance(saved, Ok)
    insert_presence_row(db, employee_id=presence_env.day_worker, work_date=AUG_4, status="leave", source="leave")
    staged = _stage(db, presence_env, profile_id, ["B001;03/08/2026 07:30;IN", "B001;03/08/2026 15:00;OUT"])
    committed = _commit(db, presence_env, staged.value["id"])
    assert isinstance(committed, Ok)
    conflicts = {(c["work_date"], c["kept_status"], c["clock_status"]) for c in committed.value["conflicts"]}
    assert conflicts == {("2026-08-03", "mission", "late"), ("2026-08-04", "leave", "absent")}
    assert presence_row(db, presence_env.day_worker, AUG_3)["status"] == "mission"
    assert presence_row(db, presence_env.day_worker, AUG_4)["status"] == "leave"


def test_a_missing_out_punch_is_reported_for_review(db, presence_env, profile_id):
    staged = _stage(db, presence_env, profile_id, ["B001;03/08/2026 07:00;IN"], date_to=AUG_3)
    committed = _commit(db, presence_env, staged.value["id"])
    assert committed.value["anomalies"] == [{
        "employee_id": presence_env.day_worker, "employee_no": "P-001", "full_name": "Test P-001",
        "work_date": "2026-08-03", "codes": ["MISSING_OUT"],
    }]
    row = presence_row(db, presence_env.day_worker, AUG_3)
    assert (row["status"], row["worked_minutes"]) == ("present", 0)


def test_a_second_file_completes_the_days_of_the_first(db, presence_env, profile_id):
    morning = _stage(db, presence_env, profile_id, ["B001;03/08/2026 06:58;IN"], date_to=AUG_3, file_name="matin.csv")
    assert isinstance(_commit(db, presence_env, morning.value["id"]), Ok)
    evening = _stage(db, presence_env, profile_id, ["B001;03/08/2026 06:58;IN", "B001;03/08/2026 15:02;OUT"], date_to=AUG_3, file_name="soir.csv")
    assert [row["error_code"] for row in evening.value["rows"]] == ["DUPLICATE_PUNCH", None]
    committed = _commit(db, presence_env, evening.value["id"])
    assert committed.value["anomalies"] == []
    assert presence_row(db, presence_env.day_worker, AUG_3)["worked_minutes"] == 484
    assert _punches(db) == 2


def test_a_file_touching_a_closed_month_is_refused_whole(db, presence_env, profile_id):
    close_month_directly(db, datetime.date(2026, 7, 1))
    staged = _stage(db, presence_env, profile_id, ["B001;31/07/2026 07:00;IN", "B001;03/08/2026 07:00;IN"], date_from=datetime.date(2026, 7, 31), date_to=AUG_3)
    committed = _commit(db, presence_env, staged.value["id"])
    assert isinstance(committed, Err) and committed.code == "PRESENCE_MONTH_CLOSED" and "2026-07" in committed.message
    assert _punches(db) == 0 and presence_row(db, presence_env.day_worker, AUG_3) is None
    assert ClockImportService(db).get_import(tenant_id=TENANT, import_id=staged.value["id"]).value["status"] == "staged"


def test_committing_needs_the_pairing_settings(db, presence_env, profile_id):
    db.execute("UPDATE hr.presence_settings SET punch_attach_minutes = NULL WHERE tenant_id = %s", (TENANT,))
    staged = _stage(db, presence_env, profile_id, ["B001;03/08/2026 07:00;IN"])
    result = _commit(db, presence_env, staged.value["id"])
    assert isinstance(result, Err) and result.code == "PRESENCE_SETTINGS_MISSING" and result.message_fr


def test_a_decided_import_cannot_be_committed_or_discarded_again(db, presence_env, profile_id):
    service = ClockImportService(db)
    committed_one = _stage(db, presence_env, profile_id, ["B001;03/08/2026 07:00;IN"])
    assert isinstance(_commit(db, presence_env, committed_one.value["id"]), Ok)
    discarded_one = _stage(db, presence_env, profile_id, ["B001;04/08/2026 07:00;IN"])
    discarded = service.discard(tenant_id=TENANT, actor_id=presence_env.actor, import_id=discarded_one.value["id"])
    assert isinstance(discarded, Ok) and discarded.value["status"] == "discarded"
    for import_id in (committed_one.value["id"], discarded_one.value["id"]):
        assert _commit(db, presence_env, import_id).code == "IMPORT_NOT_STAGED"
        assert service.discard(tenant_id=TENANT, actor_id=presence_env.actor, import_id=import_id).code == "IMPORT_NOT_STAGED"


def test_a_profile_code_is_unique_and_a_profile_can_be_edited(db, presence_env, profile_id):
    profiles = ClockProfileService(db)
    duplicate = profiles.create_profile(
        tenant_id=TENANT, actor_id=presence_env.actor, code="ZK", name="Autre", delimiter=",", has_header=True,
        badge_column="Badge", timestamp_column="Heure", timestamp_format="%H:%M",
    )
    assert isinstance(duplicate, Err) and duplicate.code == "DUPLICATE_CODE"
    edited = profiles.update_profile(tenant_id=TENANT, actor_id=presence_env.actor, profile_id=profile_id, delimiter=",", direction_column="")
    assert isinstance(edited, Ok) and (edited.value["delimiter"], edited.value["direction_column"]) == (",", None)
```

Append to `backend/modules/hr/api/test_presence_router_routes.py`:

```python
def test_clock_routes_and_their_permissions():
    expected = {
        ("GET", "/hr/clock-profiles"): "hr.view_presence",
        ("POST", "/hr/clock-profiles"): "hr.import_clock",
        ("PATCH", "/hr/clock-profiles/{profile_id}"): "hr.admin_presence",
        ("GET", "/hr/clock-imports"): "hr.view_presence",
        ("POST", "/hr/clock-imports"): "hr.import_clock",
        ("GET", "/hr/clock-imports/{import_id}"): "hr.view_presence",
        ("POST", "/hr/clock-imports/{import_id}/commit"): "hr.import_clock",
        ("POST", "/hr/clock-imports/{import_id}/discard"): "hr.import_clock",
    }
    routes = _routes()
    assert {key: routes.get(key) for key in expected} == expected
```

Run: `.venv/Scripts/python -m pytest modules/hr/api/test_clock_import_integration.py modules/hr/api/test_presence_router_routes.py -q`
Expected: FAIL (`No module named 'modules.hr.api.clock_import_service'`).

- [ ] **Step 3: Write the service**

`backend/modules/hr/api/clock_import_service.py`:

```python
"""Clock-device profiles and CSV imports: stage a file, review its rows, then commit it into
punches and presence days, or discard it.

Committing re-pairs every stored punch of the people in the file over the covered days (from
every import, so a second partial file completes the first) and writes the days. A day a
person entered by hand, or an approved leave day, is kept and listed as a conflict when the
clock disagrees; everything else is written with source 'clock' ('holiday' for an unworked
public holiday). Scheduled days without any punch become absences for the people in the file.
An unset duplicate window or grace means none (0): only identical punches merge, any delay is
lateness. The night window and the attachment minutes have no such reading and are required.
"""
from __future__ import annotations

import datetime

import psycopg
from psycopg.types.json import Jsonb
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.hr.api.presence_service import PresenceService, closed_periods, employed_between, is_employed, month_closed_error
from modules.hr.api.schedule_service import HolidayService, PresenceSettingsService, ScheduleService
from modules.hr.domain.clock_csv import ClockProfile, parse_clock_csv, validate_profile
from modules.hr.domain.pairing import PairingConfig, Punch, WorkDay, pair_punches
from modules.hr.domain.presence import PROTECTED_SOURCES, DayFigures
from modules.hr.domain.schedule import ONE_DAY, date_range

PROFILE_NOT_FOUND = Err("NOT_FOUND", "clock profile not found", "profil de pointeuse introuvable")
IMPORT_NOT_FOUND = Err("NOT_FOUND", "clock import not found", "import de pointage introuvable")
NOT_STAGED = Err(
    "IMPORT_NOT_STAGED",
    "only an import waiting for review can be committed or discarded",
    "seul un import en attente de vérification peut être importé ou écarté",
)
PAIRING_SETTINGS_MISSING = Err(
    "PRESENCE_SETTINGS_MISSING",
    "set the night-work window and the punch attachment minutes before importing (HR > Schedules & holidays > Settings)",
    "renseignez la plage de nuit et les minutes de rattachement des pointages avant d'importer (RH > Horaires et jours fériés > Paramètres)",
)
_PROFILE_KEYS = (
    "id", "code", "name", "delimiter", "has_header", "badge_column", "timestamp_column", "time_column",
    "timestamp_format", "direction_column", "in_values", "out_values", "active",
)
_IMPORT_COLUMNS = (
    "i.id, i.profile_id, p.code, i.file_name, i.date_from, i.date_to, i.status, i.total_rows, i.valid_rows, "
    "i.error_rows, i.uploaded_by, u.email, i.uploaded_at, i.decided_at, i.result"
)


def _optional(value: str | None) -> str | None:
    """None leaves an optional column alone at the call site; an empty string means 'no column'."""
    if value is None:
        return None
    return value.strip() or None


def _values(values: list[str] | None) -> list[str]:
    return [value.strip() for value in values or [] if value.strip()]


def _to_profile(profile: dict) -> ClockProfile:
    return ClockProfile(
        delimiter=profile["delimiter"], has_header=profile["has_header"], badge_column=profile["badge_column"],
        timestamp_column=profile["timestamp_column"], timestamp_format=profile["timestamp_format"],
        time_column=profile["time_column"], direction_column=profile["direction_column"],
        in_values=tuple(profile["in_values"]), out_values=tuple(profile["out_values"]),
    )


class ClockProfileService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    def list_profiles(self, *, tenant_id: str) -> list[dict]:
        rows = self.connection.execute(
            f"SELECT {', '.join(_PROFILE_KEYS)} FROM hr.clock_profiles WHERE tenant_id = %s ORDER BY code", (tenant_id,)
        ).fetchall()
        return [dict(zip(_PROFILE_KEYS, row)) for row in rows]

    def get_profile(self, *, tenant_id: str, profile_id: str) -> dict | None:
        row = self.connection.execute(
            f"SELECT {', '.join(_PROFILE_KEYS)} FROM hr.clock_profiles WHERE tenant_id = %s AND id = %s", (tenant_id, profile_id)
        ).fetchone()
        return dict(zip(_PROFILE_KEYS, row)) if row else None

    def create_profile(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        code: str,
        name: str,
        delimiter: str,
        has_header: bool,
        badge_column: str,
        timestamp_column: str,
        timestamp_format: str,
        time_column: str | None = None,
        direction_column: str | None = None,
        in_values: list[str] | None = None,
        out_values: list[str] | None = None,
    ) -> Result[dict]:
        time_column, direction_column = _optional(time_column), _optional(direction_column)
        validation = validate_profile(
            code=code, name=name, delimiter=delimiter, has_header=has_header, badge_column=badge_column,
            timestamp_column=timestamp_column, timestamp_format=timestamp_format, time_column=time_column,
            direction_column=direction_column,
        )
        if isinstance(validation, Err):
            return validation
        if self.connection.execute("SELECT 1 FROM hr.clock_profiles WHERE tenant_id = %s AND code = %s", (tenant_id, code.strip())).fetchone():
            return Err("DUPLICATE_CODE", f"clock profile code {code.strip()} already exists", f"le code de profil {code.strip()} existe déjà")
        profile_id = str(ULID())
        self.connection.execute(
            """
            INSERT INTO hr.clock_profiles (id, tenant_id, code, name, delimiter, has_header, badge_column, timestamp_column,
                                           time_column, timestamp_format, direction_column, in_values, out_values)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                profile_id, tenant_id, code.strip(), name.strip(), delimiter, has_header, badge_column.strip(),
                timestamp_column.strip(), time_column, timestamp_format, direction_column, _values(in_values), _values(out_values),
            ),
        )
        record_audit(
            self.connection, tenant_id=tenant_id, actor_id=actor_id, action="clock_profile.created",
            entity_type="clock_profile", entity_id=profile_id, payload={"code": code.strip(), "name": name.strip()},
        )
        return Ok(self.get_profile(tenant_id=tenant_id, profile_id=profile_id))

    def update_profile(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        profile_id: str,
        name: str | None = None,
        delimiter: str | None = None,
        has_header: bool | None = None,
        badge_column: str | None = None,
        timestamp_column: str | None = None,
        timestamp_format: str | None = None,
        time_column: str | None = None,
        direction_column: str | None = None,
        in_values: list[str] | None = None,
        out_values: list[str] | None = None,
        active: bool | None = None,
    ) -> Result[dict]:
        current = self.get_profile(tenant_id=tenant_id, profile_id=profile_id)
        if current is None:
            return PROFILE_NOT_FOUND
        changes = {
            key: value
            for key, value in {
                "name": name, "delimiter": delimiter, "has_header": has_header, "badge_column": badge_column,
                "timestamp_column": timestamp_column, "timestamp_format": timestamp_format, "active": active,
                "in_values": _values(in_values) if in_values is not None else None,
                "out_values": _values(out_values) if out_values is not None else None,
            }.items()
            if value is not None
        }
        if time_column is not None:
            changes["time_column"] = _optional(time_column)
        if direction_column is not None:
            changes["direction_column"] = _optional(direction_column)
        merged = {**current, **changes}
        validation = validate_profile(
            code=merged["code"], name=merged["name"], delimiter=merged["delimiter"], has_header=merged["has_header"],
            badge_column=merged["badge_column"], timestamp_column=merged["timestamp_column"],
            timestamp_format=merged["timestamp_format"], time_column=merged["time_column"], direction_column=merged["direction_column"],
        )
        if isinstance(validation, Err):
            return validation
        self.connection.execute(
            """
            UPDATE hr.clock_profiles
            SET name = %s, delimiter = %s, has_header = %s, badge_column = %s, timestamp_column = %s, time_column = %s,
                timestamp_format = %s, direction_column = %s, in_values = %s, out_values = %s, active = %s
            WHERE id = %s AND tenant_id = %s
            """,
            (
                merged["name"], merged["delimiter"], merged["has_header"], merged["badge_column"], merged["timestamp_column"],
                merged["time_column"], merged["timestamp_format"], merged["direction_column"], merged["in_values"],
                merged["out_values"], merged["active"], profile_id, tenant_id,
            ),
        )
        record_audit(
            self.connection, tenant_id=tenant_id, actor_id=actor_id, action="clock_profile.updated",
            entity_type="clock_profile", entity_id=profile_id, payload=changes,
        )
        return Ok(self.get_profile(tenant_id=tenant_id, profile_id=profile_id))


class ClockImportService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    @staticmethod
    def _header(row) -> dict:
        return {
            "id": row[0], "profile_id": row[1], "profile_code": row[2], "file_name": row[3],
            "date_from": row[4].isoformat(), "date_to": row[5].isoformat(), "status": row[6],
            "total_rows": row[7], "valid_rows": row[8], "error_rows": row[9], "uploaded_by": row[10],
            "uploaded_by_email": row[11], "uploaded_at": row[12].isoformat(),
            "decided_at": row[13].isoformat() if row[13] else None, "result": row[14],
        }

    def list_imports(self, *, tenant_id: str) -> list[dict]:
        rows = self.connection.execute(
            f"""
            SELECT {_IMPORT_COLUMNS}
            FROM hr.clock_imports i
            JOIN hr.clock_profiles p ON p.id = i.profile_id
            LEFT JOIN core.users u ON u.id = i.uploaded_by
            WHERE i.tenant_id = %s
            ORDER BY i.uploaded_at DESC
            """,
            (tenant_id,),
        ).fetchall()
        return [self._header(row) for row in rows]

    def get_import(self, *, tenant_id: str, import_id: str) -> Result[dict]:
        row = self.connection.execute(
            f"""
            SELECT {_IMPORT_COLUMNS}
            FROM hr.clock_imports i
            JOIN hr.clock_profiles p ON p.id = i.profile_id
            LEFT JOIN core.users u ON u.id = i.uploaded_by
            WHERE i.tenant_id = %s AND i.id = %s
            """,
            (tenant_id, import_id),
        ).fetchone()
        if row is None:
            return IMPORT_NOT_FOUND
        lines = self.connection.execute(
            """
            SELECT r.line_no, r.raw, r.badge_no, r.employee_id, e.employee_no, e.first_name || ' ' || e.last_name,
                   r.punched_at, r.direction, r.error_code
            FROM hr.clock_import_rows r
            LEFT JOIN hr.employees e ON e.id = r.employee_id
            WHERE r.import_id = %s
            ORDER BY r.line_no
            """,
            (import_id,),
        ).fetchall()
        rows = [
            {
                "line_no": r[0], "raw": r[1], "badge_no": r[2], "employee_id": r[3], "employee_no": r[4], "full_name": r[5],
                "punched_at": r[6].isoformat() if r[6] else None, "direction": r[7], "error_code": r[8],
            }
            for r in lines
        ]
        return Ok({**self._header(row), "rows": rows})

    def stage(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        profile_id: str,
        file_name: str,
        content: str,
        date_from: datetime.date,
        date_to: datetime.date,
    ) -> Result[dict]:
        if not file_name.strip():
            return Err("INVALID_IMPORT", "the file name is required", "le nom du fichier est obligatoire")
        if date_to < date_from:
            return Err("INVALID_IMPORT", "the covered days end before they start", "la période couverte se termine avant de commencer")
        profile = ClockProfileService(self.connection).get_profile(tenant_id=tenant_id, profile_id=profile_id)
        if profile is None or not profile["active"]:
            return PROFILE_NOT_FOUND
        parsed = parse_clock_csv(content, _to_profile(profile))
        if isinstance(parsed, Err):
            return parsed
        rows = parsed.value
        badges = sorted({row.badge_no for row in rows if row.badge_no})
        employee_by_badge = dict(
            self.connection.execute(
                "SELECT badge_no, id FROM hr.employees WHERE tenant_id = %s AND badge_no = ANY(%s)", (tenant_id, badges)
            ).fetchall()
        )
        stamps = [row.punched_at for row in rows if row.punched_at is not None]
        known: set[tuple[str, datetime.datetime]] = set()
        if stamps:
            known = {
                (r[0], r[1])
                for r in self.connection.execute(
                    """
                    SELECT badge_no, punched_at FROM hr.clock_punches
                    WHERE tenant_id = %s AND badge_no = ANY(%s) AND punched_at BETWEEN %s AND %s
                    """,
                    (tenant_id, badges, min(stamps), max(stamps)),
                ).fetchall()
            }
        lowest, highest = date_from - ONE_DAY, date_to + ONE_DAY
        import_id = str(ULID())
        staged = []
        for row in rows:
            error = row.error_code
            employee_id = employee_by_badge.get(row.badge_no) if row.badge_no else None
            if error is None and employee_id is None:
                error = "UNKNOWN_BADGE"
            if error is None and not lowest <= row.punched_at.date() <= highest:
                error = "OUTSIDE_RANGE"
            if error is None and (row.badge_no, row.punched_at) in known:
                error = "DUPLICATE_PUNCH"
            staged.append((str(ULID()), tenant_id, import_id, row.line_no, row.raw, row.badge_no, employee_id, row.punched_at, row.direction, error))
        errors = sum(1 for item in staged if item[-1] is not None)
        self.connection.execute(
            """
            INSERT INTO hr.clock_imports (id, tenant_id, profile_id, file_name, date_from, date_to, total_rows,
                                          valid_rows, error_rows, uploaded_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (import_id, tenant_id, profile_id, file_name.strip(), date_from, date_to, len(staged), len(staged) - errors, errors, actor_id),
        )
        with self.connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO hr.clock_import_rows (id, tenant_id, import_id, line_no, raw, badge_no, employee_id,
                                                  punched_at, direction, error_code)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                staged,
            )
        record_audit(
            self.connection, tenant_id=tenant_id, actor_id=actor_id, action="clock_import.staged",
            entity_type="clock_import", entity_id=import_id,
            payload={
                "file_name": file_name.strip(), "profile_id": profile_id, "date_from": date_from.isoformat(),
                "date_to": date_to.isoformat(), "total_rows": len(staged), "error_rows": errors,
            },
        )
        return self.get_import(tenant_id=tenant_id, import_id=import_id)

    def commit(self, *, tenant_id: str, actor_id: str, import_id: str) -> Result[dict]:
        header = self.connection.execute(
            "SELECT status, date_from, date_to FROM hr.clock_imports WHERE id = %s AND tenant_id = %s FOR UPDATE",
            (import_id, tenant_id),
        ).fetchone()
        if header is None:
            return IMPORT_NOT_FOUND
        status, date_from, date_to = header
        if status != "staged":
            return NOT_STAGED
        settings = PresenceSettingsService(self.connection).get(tenant_id=tenant_id)
        if settings["night_start_minute"] is None or settings["night_end_minute"] is None or settings["punch_attach_minutes"] is None:
            return PAIRING_SETTINGS_MISSING
        config = PairingConfig(
            night_start_minute=settings["night_start_minute"], night_end_minute=settings["night_end_minute"],
            attach_minutes=settings["punch_attach_minutes"], dedupe_seconds=settings["punch_dedupe_seconds"] or 0,
            late_grace_minutes=settings["late_grace_minutes"] or 0,
        )
        closed = closed_periods(self.connection, tenant_id, date_range(date_from, date_to))
        if closed:
            return month_closed_error(closed)
        valid = self.connection.execute(
            "SELECT employee_id, badge_no, punched_at, direction FROM hr.clock_import_rows WHERE import_id = %s AND error_code IS NULL ORDER BY line_no",
            (import_id,),
        ).fetchall()
        with self.connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO hr.clock_punches (id, tenant_id, employee_id, badge_no, punched_at, direction, import_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (tenant_id, badge_no, punched_at) DO NOTHING
                """,
                [(str(ULID()), tenant_id, r[0], r[1], r[2], r[3], import_id) for r in valid],
            )
        outcome = self._apply(
            tenant_id=tenant_id, actor_id=actor_id, import_id=import_id, employee_ids=sorted({r[0] for r in valid}),
            date_from=date_from, date_to=date_to, config=config,
        )
        self.connection.execute(
            "UPDATE hr.clock_imports SET status = 'committed', decided_by = %s, decided_at = NOW(), result = %s WHERE id = %s",
            (actor_id, Jsonb(outcome), import_id),
        )
        record_audit(
            self.connection, tenant_id=tenant_id, actor_id=actor_id, action="clock_import.committed",
            entity_type="clock_import", entity_id=import_id,
            payload={"days_written": outcome["days_written"], "conflicts": len(outcome["conflicts"]), "anomalies": len(outcome["anomalies"])},
        )
        return Ok({"id": import_id, **outcome})

    def discard(self, *, tenant_id: str, actor_id: str, import_id: str) -> Result[dict]:
        header = self.connection.execute(
            "SELECT status FROM hr.clock_imports WHERE id = %s AND tenant_id = %s FOR UPDATE", (import_id, tenant_id)
        ).fetchone()
        if header is None:
            return IMPORT_NOT_FOUND
        if header[0] != "staged":
            return NOT_STAGED
        self.connection.execute(
            "UPDATE hr.clock_imports SET status = 'discarded', decided_by = %s, decided_at = NOW() WHERE id = %s", (actor_id, import_id)
        )
        record_audit(
            self.connection, tenant_id=tenant_id, actor_id=actor_id, action="clock_import.discarded",
            entity_type="clock_import", entity_id=import_id, payload={},
        )
        return self.get_import(tenant_id=tenant_id, import_id=import_id)

    def _punches(self, tenant_id: str, employee_ids: list[str], first: datetime.date, until: datetime.date) -> dict[str, list[Punch]]:
        rows = self.connection.execute(
            """
            SELECT employee_id, punched_at, direction FROM hr.clock_punches
            WHERE tenant_id = %s AND employee_id = ANY(%s) AND punched_at >= %s AND punched_at < %s
            ORDER BY punched_at
            """,
            (tenant_id, employee_ids, datetime.datetime.combine(first, datetime.time()), datetime.datetime.combine(until, datetime.time())),
        ).fetchall()
        grouped: dict[str, list[Punch]] = {}
        for employee_id, punched_at, direction in rows:
            grouped.setdefault(employee_id, []).append(Punch(punched_at, direction))
        return grouped

    def _apply(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        import_id: str,
        employee_ids: list[str],
        date_from: datetime.date,
        date_to: datetime.date,
        config: PairingConfig,
    ) -> dict:
        outcome: dict = {
            "days_written": 0, "conflicts": [], "anomalies": [], "unscheduled": [],
            "duplicate_punches": 0, "outside_range_punches": 0,
        }
        employees = employed_between(self.connection, tenant_id=tenant_id, date_from=date_from, date_to=date_to, employee_ids=employee_ids)
        if not employees:
            return outcome
        ids = [employee["id"] for employee in employees]
        # One neighbouring day on each side: a night shift of the day before owns the first
        # morning's out-punch, and the last day's night shift ends the morning after.
        context_from, context_to = date_from - ONE_DAY, date_to + ONE_DAY
        resolved = ScheduleService(self.connection).resolve(tenant_id=tenant_id, employee_ids=ids, date_from=context_from, date_to=context_to)
        holidays = HolidayService(self.connection).holiday_map(tenant_id=tenant_id, date_from=context_from, date_to=context_to)
        punches = self._punches(tenant_id, ids, context_from, context_to + ONE_DAY)
        presence = PresenceService(self.connection)
        existing = presence.existing_days(tenant_id=tenant_id, employee_ids=ids, date_from=date_from, date_to=date_to)
        for employee in employees:
            days = resolved[employee["id"]]
            work_days = [
                WorkDay(work_date=day, window=days[day].window, is_holiday=day in holidays, in_range=date_from <= day <= date_to)
                for day in date_range(context_from, context_to)
            ]
            result = pair_punches(punches.get(employee["id"], []), work_days, config)
            outcome["duplicate_punches"] += result.duplicate_punches
            outcome["outside_range_punches"] += result.outside_range_punches
            who = {"employee_id": employee["id"], "employee_no": employee["employee_no"], "full_name": employee["full_name"]}
            for day in result.days:
                if not is_employed(employee, day.work_date):
                    continue
                label = {**who, "work_date": day.work_date.isoformat()}
                if not days[day.work_date].assigned:
                    if day.first_punch is not None:
                        outcome["unscheduled"].append(label)
                    continue
                if day.anomalies:
                    outcome["anomalies"].append({**label, "codes": list(day.anomalies)})
                before = existing.get((employee["id"], day.work_date))
                if before is not None and before["source"] in PROTECTED_SOURCES:
                    if (before["status"], before["worked_minutes"]) != (day.status, day.worked_minutes):
                        outcome["conflicts"].append({
                            **label, "kept_status": before["status"], "kept_source": before["source"],
                            "clock_status": day.status, "clock_worked_minutes": day.worked_minutes,
                        })
                    continue
                figures = DayFigures(
                    status=day.status, schedule_id=days[day.work_date].schedule_id, scheduled_minutes=day.scheduled_minutes,
                    worked_minutes=day.worked_minutes, late_minutes=day.late_minutes, ot_minutes_day=day.ot_minutes_day,
                    ot_minutes_night=day.ot_minutes_night, ot_minutes_rest_holiday=day.ot_minutes_rest_holiday,
                    night_minutes=day.night_minutes,
                )
                presence.upsert_day(
                    tenant_id=tenant_id, actor_id=actor_id, employee_id=employee["id"], work_date=day.work_date,
                    figures=figures, source="holiday" if day.status == "holiday" else "clock",
                    justified=day.status == "holiday", note=", ".join(day.anomalies) or None, clock_import_id=import_id,
                )
                outcome["days_written"] += 1
        return outcome
```

Clock-written days are audited once per import (`clock_import.committed`, with counts); every written row carries `clock_import_id`, which links it to that audit entry. Per-row audit stays for hand-made changes.

- [ ] **Step 4: Append the clock routes**

In `backend/modules/hr/api/presence_router.py` change `from pydantic import BaseModel` to `from pydantic import BaseModel, Field`, add the import

```python
from modules.hr.api.clock_import_service import ClockImportService, ClockProfileService
```

and append:

```python
# ---- clock profiles and imports -----------------------------------------------------

class ClockProfileBody(BaseModel):
    code: str
    name: str
    delimiter: str
    has_header: bool
    badge_column: str
    timestamp_column: str
    timestamp_format: str
    time_column: str | None = None
    direction_column: str | None = None
    in_values: list[str] = Field(default_factory=list)
    out_values: list[str] = Field(default_factory=list)


class ClockProfileUpdateBody(BaseModel):
    name: str | None = None
    delimiter: str | None = None
    has_header: bool | None = None
    badge_column: str | None = None
    timestamp_column: str | None = None
    timestamp_format: str | None = None
    time_column: str | None = None
    direction_column: str | None = None
    in_values: list[str] | None = None
    out_values: list[str] | None = None
    active: bool | None = None


class ClockImportBody(BaseModel):
    profile_id: str
    file_name: str
    content: str
    date_from: datetime.date
    date_to: datetime.date


@router.get("/clock-profiles")
def list_clock_profiles(tenant: TenantContext = Depends(require_permission("hr.view_presence"))):
    return _read(lambda c: ClockProfileService(c).list_profiles(tenant_id=tenant.tenant_id))


@router.post("/clock-profiles", status_code=status.HTTP_201_CREATED)
def create_clock_profile(body: ClockProfileBody, tenant: TenantContext = Depends(require_permission("hr.import_clock"))):
    return _write(lambda c: ClockProfileService(c).create_profile(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, **body.model_dump()))


@router.patch("/clock-profiles/{profile_id}")
def update_clock_profile(profile_id: str, body: ClockProfileUpdateBody, tenant: TenantContext = Depends(require_permission("hr.admin_presence"))):
    return _write(lambda c: ClockProfileService(c).update_profile(
        tenant_id=tenant.tenant_id, actor_id=tenant.user_id, profile_id=profile_id, **body.model_dump()
    ))


@router.get("/clock-imports")
def list_clock_imports(tenant: TenantContext = Depends(require_permission("hr.view_presence"))):
    return _read(lambda c: ClockImportService(c).list_imports(tenant_id=tenant.tenant_id))


@router.post("/clock-imports", status_code=status.HTTP_201_CREATED)
def stage_clock_import(body: ClockImportBody, tenant: TenantContext = Depends(require_permission("hr.import_clock"))):
    return _write(lambda c: ClockImportService(c).stage(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, **body.model_dump()))


@router.get("/clock-imports/{import_id}")
def get_clock_import(import_id: str, tenant: TenantContext = Depends(require_permission("hr.view_presence"))):
    return _read_result(lambda c: ClockImportService(c).get_import(tenant_id=tenant.tenant_id, import_id=import_id))


@router.post("/clock-imports/{import_id}/commit")
def commit_clock_import(import_id: str, tenant: TenantContext = Depends(require_permission("hr.import_clock"))):
    return _write(lambda c: ClockImportService(c).commit(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, import_id=import_id))


@router.post("/clock-imports/{import_id}/discard")
def discard_clock_import(import_id: str, tenant: TenantContext = Depends(require_permission("hr.import_clock"))):
    return _write(lambda c: ClockImportService(c).discard(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, import_id=import_id))
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest modules/hr -q`
Expected: all pass, 0 skipped.

- [ ] **Step 6: Commit**

```bash
git add backend/modules/hr/migrations/0013_hr_clock_imports.sql backend/modules/hr/api/clock_import_service.py backend/modules/hr/api/presence_router.py backend/modules/hr/api/test_clock_import_integration.py backend/modules/hr/api/test_presence_router_routes.py
git commit -m "feat(hr): clock CSV imports - device profiles, staging review, commit into presence days

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Leave domain — counted days, monthly accrual, balances with carry-over

**Files:**
- Create: `backend/modules/hr/domain/leave.py`
- Test: `backend/modules/hr/domain/test_leave.py`

**Interfaces:**
- Consumes: `core.domain.result`.
- Produces (used by Task 8):
  - `COUNTS_DAYS = ("calendar", "working")`, `LEAVE_PRESENCE_STATUSES = ("leave", "sick")`
  - `LeaveType(id, code, paid: bool, accrual_days_per_month: Decimal, max_carry_over: Decimal | None, counts_days: str, requires_document: bool, presence_status: str, active: bool = True)` with property `tracks_balance` (accrual > 0)
  - `validate_leave_type(*, code, name_en, name_fr, accrual_days_per_month, max_carry_over, counts_days, presence_status) -> Result[None]` (code `INVALID_LEAVE_TYPE`)
  - `leave_dates(*, start, end, counts_days, working_days: set[date]) -> list[date]`
  - `requested_days(*, start, end, half_day, counted: list[date]) -> Result[Decimal]` (codes `INVALID_DATES`, `INVALID_LEAVE`)
  - `month_accrual(*, rate: Decimal, period: date, employed_from: date, employed_to: date | None) -> Decimal` (2 decimals, half-up, prorated by employed calendar days)
  - `YearFigures(year, accrued, taken, adjusted)`, `BalanceView(year, carried_over, accrued, taken, adjusted)` with property `available`
  - `roll_balances(figures: list[YearFigures], max_carry_over: Decimal | None, *, until: int) -> dict[int, BalanceView]`
  - `check_balance(view: BalanceView, days: Decimal) -> Result[None]` (code `LEAVE_BALANCE_INSUFFICIENT`)

- [ ] **Step 1: Write the failing tests**

`backend/modules/hr/domain/test_leave.py`:

```python
"""Leave rules without a database. The 2.5 days a month used here is a test input:
the plant's accrual is a row of hr.leave_types that HR confirms."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from core.domain.result import Err, Ok
from modules.hr.domain.leave import (
    BalanceView,
    YearFigures,
    check_balance,
    leave_dates,
    month_accrual,
    requested_days,
    roll_balances,
    validate_leave_type,
)

AUG_3 = dt.date(2026, 8, 3)
AUG_9 = dt.date(2026, 8, 9)
RATE = Decimal("2.5")


def test_calendar_leave_counts_every_day_and_working_leave_only_working_days():
    working = {dt.date(2026, 8, 3), dt.date(2026, 8, 4), dt.date(2026, 8, 6)}
    assert len(leave_dates(start=AUG_3, end=AUG_9, counts_days="calendar", working_days=working)) == 7
    assert leave_dates(start=AUG_3, end=AUG_9, counts_days="working", working_days=working) == sorted(working)


def test_requested_days():
    assert requested_days(start=AUG_3, end=AUG_3, half_day=True, counted=[AUG_3]).value == Decimal("0.5")
    assert requested_days(start=AUG_3, end=dt.date(2026, 8, 5), half_day=False, counted=[AUG_3, dt.date(2026, 8, 4)]).value == Decimal(2)
    half_over_two_days = requested_days(start=AUG_3, end=dt.date(2026, 8, 4), half_day=True, counted=[AUG_3])
    backwards = requested_days(start=dt.date(2026, 8, 4), end=AUG_3, half_day=False, counted=[])
    nothing = requested_days(start=AUG_9, end=AUG_9, half_day=False, counted=[])
    assert (half_over_two_days.code, backwards.code, nothing.code) == ("INVALID_LEAVE", "INVALID_DATES", "INVALID_LEAVE")
    assert all(result.message_fr for result in (half_over_two_days, backwards, nothing))


@pytest.mark.parametrize(
    "hired,left,expected",
    [
        (dt.date(2025, 1, 1), None, Decimal("2.50")),  # the whole month
        (dt.date(2026, 8, 16), None, Decimal("1.29")),  # 16 of 31 days
        (dt.date(2025, 1, 1), dt.date(2026, 8, 10), Decimal("0.81")),  # left on the 10th: 10 of 31 days
        (dt.date(2026, 9, 1), None, Decimal("0.00")),  # not hired yet
    ],
)
def test_monthly_accrual_is_prorated_by_employed_days(hired, left, expected):
    assert month_accrual(rate=RATE, period=dt.date(2026, 8, 1), employed_from=hired, employed_to=left) == expected


def _year(year: int, accrued: str = "0", taken: str = "0", adjusted: str = "0") -> YearFigures:
    return YearFigures(year, Decimal(accrued), Decimal(taken), Decimal(adjusted))


def test_balances_roll_the_remainder_into_next_year_up_to_the_cap():
    figures = [_year(2025, accrued="30", taken="20"), _year(2026, accrued="15", taken="5", adjusted="2")]
    uncapped = roll_balances(figures, None, until=2026)[2026]
    capped = roll_balances(figures, Decimal("6"), until=2026)[2026]
    assert (uncapped.carried_over, uncapped.available) == (Decimal("10"), Decimal("22"))
    assert (capped.carried_over, capped.available) == (Decimal("6"), Decimal("18"))


def test_a_year_without_rows_still_carries_over_and_no_history_is_zero():
    views = roll_balances([_year(2024, accrued="5")], None, until=2026)
    assert (views[2025].carried_over, views[2026].carried_over) == (Decimal("5"), Decimal("5"))
    assert roll_balances([], None, until=2026)[2026].available == Decimal("0")


def test_an_overdrawn_year_carries_nothing():
    assert roll_balances([_year(2025, taken="3")], None, until=2026)[2026].carried_over == Decimal("0")


def test_the_balance_check():
    view = BalanceView(year=2026, carried_over=Decimal("1"), accrued=Decimal("2"), taken=Decimal("0"), adjusted=Decimal("0"))
    refused = check_balance(view, Decimal("3.5"))
    assert isinstance(refused, Err) and refused.code == "LEAVE_BALANCE_INSUFFICIENT" and "3.5" in refused.message_fr
    assert isinstance(check_balance(view, Decimal("3")), Ok)


def test_leave_type_validation():
    good = dict(
        code="ANNUEL", name_en="Annual leave", name_fr="Congé annuel", accrual_days_per_month=RATE,
        max_carry_over=None, counts_days="calendar", presence_status="leave",
    )
    assert isinstance(validate_leave_type(**good), Ok)
    for change in ({"counts_days": "weeks"}, {"presence_status": "absent"}, {"accrual_days_per_month": Decimal("-1")}, {"name_fr": " "}):
        result = validate_leave_type(**{**good, **change})
        assert isinstance(result, Err) and result.code == "INVALID_LEAVE_TYPE" and result.message_fr
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python -m pytest modules/hr/domain/test_leave.py -q`
Expected: collection error `No module named 'modules.hr.domain.leave'`.

- [ ] **Step 3: Write the domain module**

`backend/modules/hr/domain/leave.py`:

```python
"""Leave: types, the days a request counts, monthly accrual and yearly balances. Pure.

Accrual per month and the carry-over cap are properties of a leave type (rows HR confirms),
never constants here. A month's accrual is prorated by the calendar days the person was
employed in it. A year's unused balance (never less than zero) is carried into the next
year, up to the type's cap (no cap when empty).
"""
from __future__ import annotations

import calendar
import datetime
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from core.domain.result import Err, Ok, Result

COUNTS_DAYS = ("calendar", "working")
LEAVE_PRESENCE_STATUSES = ("leave", "sick")
HALF_DAY = Decimal("0.5")
_ZERO = Decimal("0")
_CENT = Decimal("0.01")


@dataclass(frozen=True)
class LeaveType:
    id: str
    code: str
    paid: bool
    accrual_days_per_month: Decimal
    max_carry_over: Decimal | None
    counts_days: str
    requires_document: bool
    presence_status: str
    active: bool = True

    @property
    def tracks_balance(self) -> bool:
        return self.accrual_days_per_month > 0


def validate_leave_type(
    *,
    code: str,
    name_en: str,
    name_fr: str,
    accrual_days_per_month: Decimal,
    max_carry_over: Decimal | None,
    counts_days: str,
    presence_status: str,
) -> Result[None]:
    if not code.strip() or not name_en.strip() or not name_fr.strip():
        return Err("INVALID_LEAVE_TYPE", "code and both names are required", "le code et les deux libellés sont obligatoires")
    if accrual_days_per_month < 0 or (max_carry_over is not None and max_carry_over < 0):
        return Err("INVALID_LEAVE_TYPE", "day counts cannot be negative", "les nombres de jours ne peuvent pas être négatifs")
    if counts_days not in COUNTS_DAYS:
        return Err("INVALID_LEAVE_TYPE", f"counts_days must be one of {COUNTS_DAYS}", f"counts_days doit être l'un de {COUNTS_DAYS}")
    if presence_status not in LEAVE_PRESENCE_STATUSES:
        return Err(
            "INVALID_LEAVE_TYPE",
            f"presence_status must be one of {LEAVE_PRESENCE_STATUSES}",
            f"presence_status doit être l'un de {LEAVE_PRESENCE_STATUSES}",
        )
    return Ok(None)


def leave_dates(*, start: datetime.date, end: datetime.date, counts_days: str, working_days: set[datetime.date]) -> list[datetime.date]:
    """The dates a request counts: every date, or only the person's working days (no rest day, no public holiday)."""
    every = [start + datetime.timedelta(days=offset) for offset in range((end - start).days + 1)]
    return every if counts_days == "calendar" else [day for day in every if day in working_days]


def requested_days(*, start: datetime.date, end: datetime.date, half_day: bool, counted: list[datetime.date]) -> Result[Decimal]:
    if end < start:
        return Err("INVALID_DATES", "leave end date cannot be before its start date", "la date de fin du congé ne peut pas précéder sa date de début")
    if half_day and start != end:
        return Err("INVALID_LEAVE", "a half day starts and ends on the same date", "une demi-journée commence et finit le même jour")
    if not counted:
        return Err("INVALID_LEAVE", "no leave day falls between these dates", "aucun jour de congé ne tombe entre ces dates")
    return Ok(HALF_DAY if half_day else Decimal(len(counted)))


def month_accrual(*, rate: Decimal, period: datetime.date, employed_from: datetime.date, employed_to: datetime.date | None) -> Decimal:
    last = period.replace(day=calendar.monthrange(period.year, period.month)[1])
    start = max(period, employed_from)
    end = min(last, employed_to) if employed_to is not None else last
    if end < start:
        return Decimal("0.00")
    employed_days = Decimal((end - start).days + 1)
    return (rate * employed_days / Decimal(last.day)).quantize(_CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class YearFigures:
    year: int
    accrued: Decimal
    taken: Decimal
    adjusted: Decimal


@dataclass(frozen=True)
class BalanceView:
    year: int
    carried_over: Decimal
    accrued: Decimal
    taken: Decimal
    adjusted: Decimal

    @property
    def available(self) -> Decimal:
        return self.carried_over + self.accrued + self.adjusted - self.taken


def roll_balances(figures: list[YearFigures], max_carry_over: Decimal | None, *, until: int) -> dict[int, BalanceView]:
    by_year = {item.year: item for item in figures}
    first = min([item.year for item in figures] + [until])
    views: dict[int, BalanceView] = {}
    carried = _ZERO
    for year in range(first, until + 1):
        item = by_year.get(year, YearFigures(year, _ZERO, _ZERO, _ZERO))
        view = BalanceView(year=year, carried_over=carried, accrued=item.accrued, taken=item.taken, adjusted=item.adjusted)
        views[year] = view
        remaining = max(_ZERO, view.available)
        carried = remaining if max_carry_over is None else min(remaining, max_carry_over)
    return views


def check_balance(view: BalanceView, days: Decimal) -> Result[None]:
    if view.available < days:
        return Err(
            "LEAVE_BALANCE_INSUFFICIENT",
            f"only {view.available} day(s) available for {view.year}, {days} requested",
            f"seulement {view.available} jour(s) disponible(s) pour {view.year}, {days} demandé(s)",
        )
    return Ok(None)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest modules/hr/domain/test_leave.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/hr/domain/leave.py backend/modules/hr/domain/test_leave.py
git commit -m "feat(hr): leave domain - counted days, prorated accrual, carry-over

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Leave types, requests with approval, balances — tables, services, routes

**Files:**
- Create: `backend/modules/hr/migrations/0014_hr_leave_types_balances.sql`
- Create: `backend/modules/hr/api/leave_service.py`
- Modify: `backend/modules/hr/api/presence_router.py` (append the leave section)
- Test: `backend/modules/hr/api/test_leave_integration.py`, `backend/modules/hr/api/test_presence_router_routes.py` (append one test)

**Interfaces:**
- Consumes: Task 7 domain; `validate_leave` from `modules/hr/domain/entities.py` (existing, `INVALID_DATES`); `PresenceService.existing_days/upsert_day`, `closed_periods`, `month_closed_error`, `employed_between`, `is_employed`, `month_bounds` (Task 3); `ScheduleService.resolve`, `HolidayService.holiday_map` (Task 2); `DayFigures` (Task 3).
- Produces:
  - `LeaveTypeService(connection)`: `list_types(*, tenant_id) -> list[dict]` (dict: `id, code, name_en, name_fr, paid, accrual_days_per_month, max_carry_over, counts_days, requires_document, presence_status, confirmed, active`); `get_type(*, tenant_id, leave_type_id) -> dict | None`; `create_type(*, tenant_id, actor_id, code, name_en, name_fr, paid, accrual_days_per_month, max_carry_over, counts_days, requires_document, presence_status, confirmed=False) -> Result[dict]`; `update_type(*, tenant_id, actor_id, leave_type_id, name_en=None, name_fr=None, paid=None, accrual_days_per_month=None, max_carry_over=None, clear_max_carry_over=False, counts_days=None, requires_document=None, presence_status=None, confirmed=None, active=None) -> Result[dict]` (`code` is not editable).
  - `LeaveRequestService(connection)`: `list_requests(*, tenant_id, status=None, employee_id=None) -> list[dict]` (dict: `id, employee_id, employee_no, full_name, leave_type_id, leave_type_code, leave_type_name_en, leave_type_name_fr, legacy_leave_type, start_date, end_date, days, half_day, reason, document_ref, status, reviewed_by, reviewed_at, review_note`); `create_request(*, tenant_id, actor_id, employee_id, leave_type_id, start_date, end_date, half_day=False, reason=None, document_ref=None)`; `approve / reject / cancel(*, tenant_id, actor_id, request_id, note=None)`; `update_request(*, tenant_id, actor_id, request_id, leave_type_id=None, start_date=None, end_date=None, half_day=None, reason=None, document_ref=None)` — all `-> Result[dict]`.
  - `LeaveBalanceService(connection)`: `balances(*, tenant_id, year, employee_id=None) -> list[dict]` (dict: `employee_id, employee_no, full_name, leave_type_id, leave_type_code, tracks_balance, year, carried_over, accrued, taken, adjusted, available`); `balance_view(*, tenant_id, employee_id, leave_type: LeaveType, year) -> BalanceView`; `add_taken(*, tenant_id, employee_id, leave_type_id, year, days: Decimal) -> None`; `adjust(*, tenant_id, actor_id, employee_id, leave_type_id, year, delta: Decimal, reason: str) -> Result[dict]`; `post_month_accruals(*, tenant_id, period) -> int` (called by the month close, Task 9).
  - Refusal codes: `LEAVE_OVERLAP`, `LEAVE_BALANCE_INSUFFICIENT`, `LEAVE_OVERLAPS_WORK`, `LEAVE_DOCUMENT_REQUIRED`, `NO_SCHEDULE`, `NOT_EMPLOYED`, `INVALID_LEAVE`, `INVALID_ADJUSTMENT`, `PRESENCE_MONTH_CLOSED`, `INVALID_TRANSITION`.
  - Routes: `GET/POST /hr/leave-types`, `PATCH /hr/leave-types/{leave_type_id}`, `GET/POST /hr/leave/requests`, `PATCH /hr/leave/requests/{request_id}`, `POST /hr/leave/requests/{request_id}/approve|reject|cancel` (body `{note}` optional), `GET /hr/leave/balances?year=&employee_id=`, `POST /hr/leave/balances/adjust`. The old `/hr/leave-requests` routes stay as they are.

- [ ] **Step 1: Write and apply the migration**

`backend/modules/hr/migrations/0014_hr_leave_types_balances.sql`:

```sql
-- Leave types carry statutory values (accrual per month, carry-over cap): seed data flagged
-- confirmed = FALSE until HR checks them, never constants in code.
CREATE TABLE IF NOT EXISTS hr.leave_types (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    code TEXT NOT NULL,
    name_en TEXT NOT NULL,
    name_fr TEXT NOT NULL,
    paid BOOLEAN NOT NULL,
    accrual_days_per_month NUMERIC(5, 2) NOT NULL CHECK (accrual_days_per_month >= 0),
    max_carry_over NUMERIC(6, 2) CHECK (max_carry_over IS NULL OR max_carry_over >= 0),
    counts_days TEXT NOT NULL CHECK (counts_days IN ('calendar', 'working')),
    requires_document BOOLEAN NOT NULL DEFAULT FALSE,
    presence_status TEXT NOT NULL CHECK (presence_status IN ('leave', 'sick')),
    confirmed BOOLEAN NOT NULL DEFAULT FALSE,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, code)
);

CREATE TABLE IF NOT EXISTS hr.leave_balances (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    employee_id TEXT NOT NULL REFERENCES hr.employees (id),
    leave_type_id TEXT NOT NULL REFERENCES hr.leave_types (id),
    year SMALLINT NOT NULL,
    accrued NUMERIC(6, 2) NOT NULL DEFAULT 0,
    taken NUMERIC(6, 2) NOT NULL DEFAULT 0,
    adjusted NUMERIC(6, 2) NOT NULL DEFAULT 0,
    UNIQUE (tenant_id, employee_id, leave_type_id, year)
);

-- One posting per employee, type and closed month; leave_balances.accrued is their yearly sum,
-- so closing a month twice (after a reopen) posts the same value again, not twice.
CREATE TABLE IF NOT EXISTS hr.leave_accruals (
    tenant_id TEXT NOT NULL,
    employee_id TEXT NOT NULL REFERENCES hr.employees (id),
    leave_type_id TEXT NOT NULL REFERENCES hr.leave_types (id),
    period DATE NOT NULL CHECK (EXTRACT(DAY FROM period) = 1),
    days NUMERIC(6, 2) NOT NULL,
    posted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (tenant_id, employee_id, leave_type_id, period)
);

-- Old rows keep their free-text leave_type and get no leave_type_id: they are listed as
-- "old request" and must be given a type before being decided through the new flow.
ALTER TABLE hr.leave_requests ADD COLUMN IF NOT EXISTS leave_type_id TEXT REFERENCES hr.leave_types (id);
ALTER TABLE hr.leave_requests ADD COLUMN IF NOT EXISTS days NUMERIC(5, 1);
ALTER TABLE hr.leave_requests ADD COLUMN IF NOT EXISTS half_day BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE hr.leave_requests ADD COLUMN IF NOT EXISTS document_ref TEXT;
ALTER TABLE hr.leave_requests ADD COLUMN IF NOT EXISTS balance_year SMALLINT;
ALTER TABLE hr.leave_requests ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMPTZ;
ALTER TABLE hr.leave_requests ADD COLUMN IF NOT EXISTS review_note TEXT;
```

Run: `DATABASE_URL=postgresql://erp:erp@localhost:5432/erp .venv/Scripts/python.exe -c "from core.migrations.runner import apply_all_migrations; apply_all_migrations()"`
Expected: exit 0.

- [ ] **Step 2: Write the failing integration tests and route test**

`backend/modules/hr/api/test_leave_integration.py`:

```python
"""Leave types, requests, approval and balances against a real database.
The 2.5 days a month below is a test input, not the plant's (unconfirmed) seed value."""
from __future__ import annotations

import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from modules.hr.api.leave_service import LeaveBalanceService, LeaveRequestService, LeaveTypeService
from modules.hr.api.presence_testkit import (  # noqa: F401
    AUG_1, AUG_3, TENANT, add_employee, close_month_directly, insert_presence_row, presence_env, presence_row,
)
from modules.hr.api.schedule_service import HolidayService

AUG_4 = datetime.date(2026, 8, 4)
AUG_5 = datetime.date(2026, 8, 5)
AUG_6 = datetime.date(2026, 8, 6)
AUG_9 = datetime.date(2026, 8, 9)


@pytest.fixture
def leave(db, presence_env):
    types = LeaveTypeService(db)

    def create(code: str, **values) -> str:
        created = types.create_type(tenant_id=TENANT, actor_id=presence_env.actor, code=code, **values)
        assert isinstance(created, Ok), created
        return created.value["id"]

    return SimpleNamespace(
        annual=create("ANNUEL", name_en="Annual leave", name_fr="Congé annuel", paid=True, accrual_days_per_month=Decimal("2.5"),
                      max_carry_over=None, counts_days="working", requires_document=False, presence_status="leave"),
        sick=create("MALADIE", name_en="Sick leave", name_fr="Congé maladie", paid=True, accrual_days_per_month=Decimal("0"),
                    max_carry_over=None, counts_days="calendar", requires_document=True, presence_status="sick"),
        unpaid=create("SANS_SOLDE", name_en="Unpaid leave", name_fr="Congé sans solde", paid=False, accrual_days_per_month=Decimal("0"),
                      max_carry_over=None, counts_days="calendar", requires_document=False, presence_status="leave"),
    )


def _request(db, env, leave_type_id, start, end, *, half_day=False, document_ref=None):
    return LeaveRequestService(db).create_request(
        tenant_id=TENANT, actor_id=env.actor, employee_id=env.day_worker, leave_type_id=leave_type_id,
        start_date=start, end_date=end, half_day=half_day, document_ref=document_ref,
    )


def _approve(db, env, request_id):
    return LeaveRequestService(db).approve(tenant_id=TENANT, actor_id=env.actor, request_id=request_id)


def _give(db, env, leave_type_id, days: str, year: int = 2026):
    result = LeaveBalanceService(db).adjust(
        tenant_id=TENANT, actor_id=env.actor, employee_id=env.day_worker, leave_type_id=leave_type_id,
        year=year, delta=Decimal(days), reason="solde d'ouverture",
    )
    assert isinstance(result, Ok), result


def _balance(db, env, leave_type_id, year: int = 2026) -> dict:
    return next(b for b in LeaveBalanceService(db).balances(tenant_id=TENANT, year=year, employee_id=env.day_worker) if b["leave_type_id"] == leave_type_id)


def test_working_day_leave_skips_the_rest_day_and_the_public_holiday(db, presence_env, leave):
    HolidayService(db).create_holiday(tenant_id=TENANT, actor_id=presence_env.actor, country_code="ML", holiday_date=AUG_5, name="Jour de test")
    created = _request(db, presence_env, leave.annual, AUG_3, AUG_9)
    assert isinstance(created, Ok)
    assert (created.value["days"], created.value["status"], created.value["leave_type_code"]) == (Decimal("5"), "pending", "ANNUEL")


def test_approval_needs_enough_balance_then_writes_leave_days(db, presence_env, leave):
    request = _request(db, presence_env, leave.annual, AUG_3, AUG_4).value
    refused = _approve(db, presence_env, request["id"])
    assert isinstance(refused, Err) and refused.code == "LEAVE_BALANCE_INSUFFICIENT" and refused.message_fr
    _give(db, presence_env, leave.annual, "5")
    approved = _approve(db, presence_env, request["id"])
    assert isinstance(approved, Ok) and approved.value["status"] == "approved"
    for day in (AUG_3, AUG_4):
        row = presence_row(db, presence_env.day_worker, day)
        assert (row["status"], row["source"], row["justified"], row["leave_request_id"]) == ("leave", "leave", True, request["id"])
    balance = _balance(db, presence_env, leave.annual)
    assert (balance["taken"], balance["available"]) == (Decimal("2"), Decimal("3"))


def test_a_half_day_takes_half_a_day_and_writes_no_presence(db, presence_env, leave):
    _give(db, presence_env, leave.annual, "1")
    request = _request(db, presence_env, leave.annual, AUG_3, AUG_3, half_day=True).value
    assert request["days"] == Decimal("0.5")
    assert isinstance(_approve(db, presence_env, request["id"]), Ok)
    assert presence_row(db, presence_env.day_worker, AUG_3) is None
    assert _balance(db, presence_env, leave.annual)["available"] == Decimal("0.5")


def test_leave_over_a_worked_day_is_refused(db, presence_env, leave):
    _give(db, presence_env, leave.annual, "5")
    insert_presence_row(db, employee_id=presence_env.day_worker, work_date=AUG_4, status="present", source="clock", worked_minutes=480)
    request = _request(db, presence_env, leave.annual, AUG_3, AUG_4).value
    refused = _approve(db, presence_env, request["id"])
    assert isinstance(refused, Err) and refused.code == "LEAVE_OVERLAPS_WORK" and "2026-08-04" in refused.message_fr


def test_overlapping_requests_are_refused(db, presence_env, leave):
    assert isinstance(_request(db, presence_env, leave.annual, AUG_3, AUG_4), Ok)
    overlap = _request(db, presence_env, leave.unpaid, AUG_4, AUG_5)
    assert isinstance(overlap, Err) and overlap.code == "LEAVE_OVERLAP" and overlap.message_fr


def test_cancelling_approved_leave_gives_the_days_back_and_clears_the_leave_days(db, presence_env, leave):
    _give(db, presence_env, leave.annual, "5")
    request = _request(db, presence_env, leave.annual, AUG_3, AUG_4).value
    assert isinstance(_approve(db, presence_env, request["id"]), Ok)
    cancelled = LeaveRequestService(db).cancel(tenant_id=TENANT, actor_id=presence_env.actor, request_id=request["id"])
    assert isinstance(cancelled, Ok) and cancelled.value["status"] == "cancelled"
    assert presence_row(db, presence_env.day_worker, AUG_3) is None
    assert _balance(db, presence_env, leave.annual)["taken"] == Decimal("0")


def test_a_closed_month_refuses_approval_and_cancellation(db, presence_env, leave):
    _give(db, presence_env, leave.annual, "5")
    approved = _request(db, presence_env, leave.annual, AUG_3, AUG_4).value
    assert isinstance(_approve(db, presence_env, approved["id"]), Ok)
    pending = _request(db, presence_env, leave.annual, datetime.date(2026, 8, 10), datetime.date(2026, 8, 11)).value
    close_month_directly(db, AUG_1)
    refused_approval = _approve(db, presence_env, pending["id"])
    refused_cancel = LeaveRequestService(db).cancel(tenant_id=TENANT, actor_id=presence_env.actor, request_id=approved["id"])
    assert (refused_approval.code, refused_cancel.code) == ("PRESENCE_MONTH_CLOSED", "PRESENCE_MONTH_CLOSED")


def test_sick_leave_needs_its_document_and_marks_sick_days_without_a_balance(db, presence_env, leave):
    request = _request(db, presence_env, leave.sick, AUG_3, AUG_4).value
    refused = _approve(db, presence_env, request["id"])
    assert isinstance(refused, Err) and refused.code == "LEAVE_DOCUMENT_REQUIRED" and refused.message_fr
    edited = LeaveRequestService(db).update_request(tenant_id=TENANT, actor_id=presence_env.actor, request_id=request["id"], document_ref="certificat-2026-081.pdf")
    assert isinstance(edited, Ok)
    assert isinstance(_approve(db, presence_env, request["id"]), Ok)
    assert presence_row(db, presence_env.day_worker, AUG_3)["status"] == "sick"


def test_editing_approved_leave_moves_its_days_and_its_balance(db, presence_env, leave):
    _give(db, presence_env, leave.annual, "5")
    request = _request(db, presence_env, leave.annual, AUG_3, AUG_4).value
    assert isinstance(_approve(db, presence_env, request["id"]), Ok)
    edited = LeaveRequestService(db).update_request(tenant_id=TENANT, actor_id=presence_env.actor, request_id=request["id"], start_date=AUG_4, end_date=AUG_6)
    assert isinstance(edited, Ok) and edited.value["days"] == Decimal("3")
    assert presence_row(db, presence_env.day_worker, AUG_3) is None
    assert presence_row(db, presence_env.day_worker, AUG_6)["status"] == "leave"
    assert _balance(db, presence_env, leave.annual)["taken"] == Decimal("3")


def test_month_accrual_is_prorated_and_posting_it_twice_changes_nothing(db, presence_env, leave):
    add_employee(db, employee_no="P-003", department=presence_env.department, hire_date=datetime.date(2026, 8, 16))
    balances = LeaveBalanceService(db)
    assert balances.post_month_accruals(tenant_id=TENANT, period=AUG_1) == 3  # three people, one accruing type
    assert balances.post_month_accruals(tenant_id=TENANT, period=AUG_1) == 3
    accrued = {b["employee_no"]: b["accrued"] for b in balances.balances(tenant_id=TENANT, year=2026) if b["leave_type_id"] == leave.annual}
    assert accrued == {"P-001": Decimal("2.50"), "P-002": Decimal("2.50"), "P-003": Decimal("1.29")}


def test_the_carry_over_cap_of_the_leave_type_applies_and_can_be_cleared(db, presence_env, leave):
    _give(db, presence_env, leave.annual, "10", year=2025)
    types = LeaveTypeService(db)
    capped = types.update_type(tenant_id=TENANT, actor_id=presence_env.actor, leave_type_id=leave.annual, max_carry_over=Decimal("2"))
    assert isinstance(capped, Ok)
    assert _balance(db, presence_env, leave.annual)["carried_over"] == Decimal("2")
    uncapped = types.update_type(tenant_id=TENANT, actor_id=presence_env.actor, leave_type_id=leave.annual, clear_max_carry_over=True)
    assert uncapped.value["max_carry_over"] is None
    assert _balance(db, presence_env, leave.annual)["carried_over"] == Decimal("10")


def test_an_old_request_without_a_type_is_listed_and_must_get_one_before_approval(db, presence_env, leave):
    old_id = str(ULID())
    db.execute(
        "INSERT INTO hr.leave_requests (id, tenant_id, employee_id, leave_type, start_date, end_date) VALUES (%s, %s, %s, 'annual', %s, %s)",
        (old_id, TENANT, presence_env.day_worker, AUG_3, AUG_3),
    )
    listed = next(r for r in LeaveRequestService(db).list_requests(tenant_id=TENANT) if r["id"] == old_id)
    assert (listed["leave_type_id"], listed["legacy_leave_type"], listed["days"]) == (None, "annual", None)
    refused = _approve(db, presence_env, old_id)
    assert isinstance(refused, Err) and refused.code == "INVALID_LEAVE"
```

Append to `backend/modules/hr/api/test_presence_router_routes.py`:

```python
def test_leave_routes_and_their_permissions():
    expected = {
        ("GET", "/hr/leave-types"): "hr.view_leave",
        ("POST", "/hr/leave-types"): "hr.manage_leave",
        ("PATCH", "/hr/leave-types/{leave_type_id}"): "hr.admin_leave",
        ("GET", "/hr/leave/requests"): "hr.view_leave",
        ("POST", "/hr/leave/requests"): "hr.manage_leave",
        ("PATCH", "/hr/leave/requests/{request_id}"): "hr.admin_leave",
        ("POST", "/hr/leave/requests/{request_id}/approve"): "hr.manage_leave",
        ("POST", "/hr/leave/requests/{request_id}/reject"): "hr.manage_leave",
        ("POST", "/hr/leave/requests/{request_id}/cancel"): "hr.manage_leave",
        ("GET", "/hr/leave/balances"): "hr.view_leave",
        ("POST", "/hr/leave/balances/adjust"): "hr.admin_leave",
    }
    routes = _routes()
    assert {key: routes.get(key) for key in expected} == expected
```

Run: `.venv/Scripts/python -m pytest modules/hr/api/test_leave_integration.py modules/hr/api/test_presence_router_routes.py -q`
Expected: FAIL (`No module named 'modules.hr.api.leave_service'`).

- [ ] **Step 3: Write the service**

`backend/modules/hr/api/leave_service.py`:

```python
"""Leave types, leave requests with approval, and balances (monthly accrual, carry-over, adjustments).

Approving a request takes its days from the balance of the start date's year and writes one
presence day per counted day with source 'leave' (none for a half day: the person also works
that day). Cancelling an approved request, or editing it, first undoes that. Every one of
these refuses a closed month. Audit payloads hold Decimals as strings (JSON has no Decimal).
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass
from decimal import Decimal

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.hr.api.presence_service import (
    PresenceService,
    closed_periods,
    employed_between,
    is_employed,
    month_bounds,
    month_closed_error,
)
from modules.hr.api.schedule_service import HolidayService, ScheduleService
from modules.hr.domain.entities import validate_leave
from modules.hr.domain.leave import (
    BalanceView,
    LeaveType,
    YearFigures,
    check_balance,
    leave_dates,
    month_accrual,
    requested_days,
    roll_balances,
    validate_leave_type,
)
from modules.hr.domain.presence import DayFigures
from modules.hr.domain.schedule import ResolvedDay, date_range

TYPE_NOT_FOUND = Err("NOT_FOUND", "leave type not found", "type de congé introuvable")
REQUEST_NOT_FOUND = Err("NOT_FOUND", "leave request not found", "demande de congé introuvable")
EMPLOYEE_NOT_FOUND = Err("NOT_FOUND", "employee not found", "employé introuvable")
LEAVE_OVERLAP = Err(
    "LEAVE_OVERLAP",
    "the employee already has a pending or approved leave on these dates",
    "l'employé a déjà un congé en attente ou approuvé sur ces dates",
)
_TYPE_KEYS = (
    "id", "code", "name_en", "name_fr", "paid", "accrual_days_per_month", "max_carry_over", "counts_days",
    "requires_document", "presence_status", "confirmed", "active",
)
_REQUEST_KEYS = (
    "id", "employee_id", "leave_type_id", "leave_type", "start_date", "end_date", "days", "half_day", "status",
    "document_ref", "reason", "balance_year",
)
_LIST_COLUMNS = """
    r.id, r.employee_id, e.employee_no, e.first_name || ' ' || e.last_name, r.leave_type_id, t.code, t.name_en,
    t.name_fr, r.leave_type, r.start_date, r.end_date, r.days, r.half_day, r.reason, r.document_ref, r.status,
    r.reviewed_by, r.reviewed_at, r.review_note
"""


def _domain_type(row: dict) -> LeaveType:
    return LeaveType(
        id=row["id"], code=row["code"], paid=row["paid"], accrual_days_per_month=row["accrual_days_per_month"],
        max_carry_over=row["max_carry_over"], counts_days=row["counts_days"], requires_document=row["requires_document"],
        presence_status=row["presence_status"], active=row["active"],
    )


def _text(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


@dataclass(frozen=True)
class _Plan:
    dates: list[datetime.date]
    days: Decimal
    resolved: dict[datetime.date, ResolvedDay]
    holidays: set[datetime.date]


class LeaveTypeService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    def list_types(self, *, tenant_id: str) -> list[dict]:
        rows = self.connection.execute(
            f"SELECT {', '.join(_TYPE_KEYS)} FROM hr.leave_types WHERE tenant_id = %s ORDER BY code", (tenant_id,)
        ).fetchall()
        return [dict(zip(_TYPE_KEYS, row)) for row in rows]

    def get_type(self, *, tenant_id: str, leave_type_id: str) -> dict | None:
        row = self.connection.execute(
            f"SELECT {', '.join(_TYPE_KEYS)} FROM hr.leave_types WHERE tenant_id = %s AND id = %s", (tenant_id, leave_type_id)
        ).fetchone()
        return dict(zip(_TYPE_KEYS, row)) if row else None

    def create_type(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        code: str,
        name_en: str,
        name_fr: str,
        paid: bool,
        accrual_days_per_month: Decimal,
        max_carry_over: Decimal | None,
        counts_days: str,
        requires_document: bool,
        presence_status: str,
        confirmed: bool = False,
    ) -> Result[dict]:
        validation = validate_leave_type(
            code=code, name_en=name_en, name_fr=name_fr, accrual_days_per_month=accrual_days_per_month,
            max_carry_over=max_carry_over, counts_days=counts_days, presence_status=presence_status,
        )
        if isinstance(validation, Err):
            return validation
        if self.connection.execute("SELECT 1 FROM hr.leave_types WHERE tenant_id = %s AND code = %s", (tenant_id, code.strip())).fetchone():
            return Err("DUPLICATE_CODE", f"leave type code {code.strip()} already exists", f"le code de type de congé {code.strip()} existe déjà")
        leave_type_id = str(ULID())
        self.connection.execute(
            """
            INSERT INTO hr.leave_types (id, tenant_id, code, name_en, name_fr, paid, accrual_days_per_month, max_carry_over,
                                        counts_days, requires_document, presence_status, confirmed)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                leave_type_id, tenant_id, code.strip(), name_en.strip(), name_fr.strip(), paid, accrual_days_per_month,
                max_carry_over, counts_days, requires_document, presence_status, confirmed,
            ),
        )
        record_audit(
            self.connection, tenant_id=tenant_id, actor_id=actor_id, action="leave_type.created",
            entity_type="leave_type", entity_id=leave_type_id,
            payload={
                "code": code.strip(), "paid": paid, "accrual_days_per_month": _text(accrual_days_per_month),
                "max_carry_over": _text(max_carry_over), "counts_days": counts_days, "confirmed": confirmed,
            },
        )
        return Ok(self.get_type(tenant_id=tenant_id, leave_type_id=leave_type_id))

    def update_type(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        leave_type_id: str,
        name_en: str | None = None,
        name_fr: str | None = None,
        paid: bool | None = None,
        accrual_days_per_month: Decimal | None = None,
        max_carry_over: Decimal | None = None,
        clear_max_carry_over: bool = False,
        counts_days: str | None = None,
        requires_document: bool | None = None,
        presence_status: str | None = None,
        confirmed: bool | None = None,
        active: bool | None = None,
    ) -> Result[dict]:
        current = self.get_type(tenant_id=tenant_id, leave_type_id=leave_type_id)
        if current is None:
            return TYPE_NOT_FOUND
        changes = {
            key: value
            for key, value in {
                "name_en": name_en, "name_fr": name_fr, "paid": paid, "accrual_days_per_month": accrual_days_per_month,
                "max_carry_over": max_carry_over, "counts_days": counts_days, "requires_document": requires_document,
                "presence_status": presence_status, "confirmed": confirmed, "active": active,
            }.items()
            if value is not None
        }
        if clear_max_carry_over:
            changes["max_carry_over"] = None
        merged = {**current, **changes}
        validation = validate_leave_type(
            code=merged["code"], name_en=merged["name_en"], name_fr=merged["name_fr"],
            accrual_days_per_month=merged["accrual_days_per_month"], max_carry_over=merged["max_carry_over"],
            counts_days=merged["counts_days"], presence_status=merged["presence_status"],
        )
        if isinstance(validation, Err):
            return validation
        self.connection.execute(
            """
            UPDATE hr.leave_types
            SET name_en = %s, name_fr = %s, paid = %s, accrual_days_per_month = %s, max_carry_over = %s, counts_days = %s,
                requires_document = %s, presence_status = %s, confirmed = %s, active = %s
            WHERE id = %s AND tenant_id = %s
            """,
            (
                merged["name_en"], merged["name_fr"], merged["paid"], merged["accrual_days_per_month"], merged["max_carry_over"],
                merged["counts_days"], merged["requires_document"], merged["presence_status"], merged["confirmed"],
                merged["active"], leave_type_id, tenant_id,
            ),
        )
        record_audit(
            self.connection, tenant_id=tenant_id, actor_id=actor_id, action="leave_type.updated",
            entity_type="leave_type", entity_id=leave_type_id,
            payload={key: _text(value) if isinstance(value, Decimal) else value for key, value in changes.items()},
        )
        return Ok(self.get_type(tenant_id=tenant_id, leave_type_id=leave_type_id))


class LeaveBalanceService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    def _ensure(self, tenant_id: str, employee_id: str, leave_type_id: str, year: int) -> str:
        self.connection.execute(
            """
            INSERT INTO hr.leave_balances (id, tenant_id, employee_id, leave_type_id, year) VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id, employee_id, leave_type_id, year) DO NOTHING
            """,
            (str(ULID()), tenant_id, employee_id, leave_type_id, year),
        )
        return self.connection.execute(
            "SELECT id FROM hr.leave_balances WHERE tenant_id = %s AND employee_id = %s AND leave_type_id = %s AND year = %s",
            (tenant_id, employee_id, leave_type_id, year),
        ).fetchone()[0]

    def add_taken(self, *, tenant_id: str, employee_id: str, leave_type_id: str, year: int, days: Decimal) -> None:
        balance_id = self._ensure(tenant_id, employee_id, leave_type_id, year)
        self.connection.execute("UPDATE hr.leave_balances SET taken = taken + %s WHERE id = %s", (days, balance_id))

    def balance_view(self, *, tenant_id: str, employee_id: str, leave_type: LeaveType, year: int) -> BalanceView:
        rows = self.connection.execute(
            """
            SELECT year, accrued, taken, adjusted FROM hr.leave_balances
            WHERE tenant_id = %s AND employee_id = %s AND leave_type_id = %s AND year <= %s
            ORDER BY year
            """,
            (tenant_id, employee_id, leave_type.id, year),
        ).fetchall()
        return roll_balances([YearFigures(*row) for row in rows], leave_type.max_carry_over, until=year)[year]

    def balances(self, *, tenant_id: str, year: int, employee_id: str | None = None) -> list[dict]:
        types = {row["id"]: row for row in LeaveTypeService(self.connection).list_types(tenant_id=tenant_id)}
        params: list[object] = [tenant_id, year]
        clause = ""
        if employee_id:
            clause = " AND b.employee_id = %s"
            params.append(employee_id)
        rows = self.connection.execute(
            f"""
            SELECT b.employee_id, e.employee_no, e.first_name || ' ' || e.last_name, b.leave_type_id, b.year,
                   b.accrued, b.taken, b.adjusted
            FROM hr.leave_balances b
            JOIN hr.employees e ON e.id = b.employee_id
            WHERE b.tenant_id = %s AND b.year <= %s{clause}
            ORDER BY e.employee_no, b.leave_type_id, b.year
            """,
            params,
        ).fetchall()
        grouped: dict[tuple[str, str], dict] = {}
        for r in rows:
            item = grouped.setdefault((r[0], r[3]), {"employee_no": r[1], "full_name": r[2], "figures": []})
            item["figures"].append(YearFigures(r[4], r[5], r[6], r[7]))
        result = []
        for (row_employee_id, leave_type_id), item in grouped.items():
            leave_type = types[leave_type_id]
            view = roll_balances(item["figures"], leave_type["max_carry_over"], until=year)[year]
            result.append({
                "employee_id": row_employee_id, "employee_no": item["employee_no"], "full_name": item["full_name"],
                "leave_type_id": leave_type_id, "leave_type_code": leave_type["code"],
                "tracks_balance": leave_type["accrual_days_per_month"] > 0, "year": year,
                "carried_over": view.carried_over, "accrued": view.accrued, "taken": view.taken,
                "adjusted": view.adjusted, "available": view.available,
            })
        return result

    def adjust(
        self, *, tenant_id: str, actor_id: str, employee_id: str, leave_type_id: str, year: int, delta: Decimal, reason: str
    ) -> Result[dict]:
        if not reason.strip():
            return Err("INVALID_ADJUSTMENT", "a reason is required", "un motif est obligatoire")
        if delta == 0:
            return Err("INVALID_ADJUSTMENT", "the adjustment cannot be zero", "l'ajustement ne peut pas être nul")
        if self.connection.execute("SELECT 1 FROM hr.employees WHERE id = %s AND tenant_id = %s", (employee_id, tenant_id)).fetchone() is None:
            return EMPLOYEE_NOT_FOUND
        if LeaveTypeService(self.connection).get_type(tenant_id=tenant_id, leave_type_id=leave_type_id) is None:
            return TYPE_NOT_FOUND
        balance_id = self._ensure(tenant_id, employee_id, leave_type_id, year)
        self.connection.execute("UPDATE hr.leave_balances SET adjusted = adjusted + %s WHERE id = %s", (delta, balance_id))
        record_audit(
            self.connection, tenant_id=tenant_id, actor_id=actor_id, action="leave_balance.adjusted",
            entity_type="leave_balance", entity_id=balance_id,
            payload={"employee_id": employee_id, "leave_type_id": leave_type_id, "year": year, "delta": str(delta), "reason": reason.strip()},
        )
        return Ok(next(b for b in self.balances(tenant_id=tenant_id, year=year, employee_id=employee_id) if b["leave_type_id"] == leave_type_id))

    def post_month_accruals(self, *, tenant_id: str, period: datetime.date) -> int:
        """Posts the month's accrual of every accruing type for everyone employed in it. Re-posting replaces."""
        first, last = month_bounds(period)
        accruing = [
            _domain_type(row)
            for row in LeaveTypeService(self.connection).list_types(tenant_id=tenant_id)
            if row["active"] and row["accrual_days_per_month"] > 0
        ]
        if not accruing:
            return 0
        posted = 0
        for employee in employed_between(self.connection, tenant_id=tenant_id, date_from=first, date_to=last):
            for leave_type in accruing:
                days = month_accrual(
                    rate=leave_type.accrual_days_per_month, period=first,
                    employed_from=employee["hire_date"], employed_to=employee["termination_date"],
                )
                self.connection.execute(
                    """
                    INSERT INTO hr.leave_accruals (tenant_id, employee_id, leave_type_id, period, days) VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (tenant_id, employee_id, leave_type_id, period) DO UPDATE SET days = EXCLUDED.days, posted_at = NOW()
                    """,
                    (tenant_id, employee["id"], leave_type.id, first, days),
                )
                balance_id = self._ensure(tenant_id, employee["id"], leave_type.id, first.year)
                self.connection.execute(
                    """
                    UPDATE hr.leave_balances SET accrued = (
                        SELECT COALESCE(SUM(days), 0) FROM hr.leave_accruals
                        WHERE tenant_id = %s AND employee_id = %s AND leave_type_id = %s AND period BETWEEN %s AND %s
                    ) WHERE id = %s
                    """,
                    (tenant_id, employee["id"], leave_type.id, datetime.date(first.year, 1, 1), datetime.date(first.year, 12, 31), balance_id),
                )
                posted += 1
        return posted


class LeaveRequestService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    # ---- reads ------------------------------------------------------------------
    def list_requests(self, *, tenant_id: str, status: str | None = None, employee_id: str | None = None) -> list[dict]:
        clauses = ["r.tenant_id = %s"]
        params: list[object] = [tenant_id]
        if status:
            clauses.append("r.status = %s")
            params.append(status)
        if employee_id:
            clauses.append("r.employee_id = %s")
            params.append(employee_id)
        return self._query(clauses, params)

    def _request(self, tenant_id: str, request_id: str) -> dict:
        return self._query(["r.tenant_id = %s", "r.id = %s"], [tenant_id, request_id])[0]

    def _query(self, clauses: list[str], params: list[object]) -> list[dict]:
        rows = self.connection.execute(
            f"""
            SELECT {_LIST_COLUMNS}
            FROM hr.leave_requests r
            JOIN hr.employees e ON e.id = r.employee_id
            LEFT JOIN hr.leave_types t ON t.id = r.leave_type_id
            WHERE {' AND '.join(clauses)}
            ORDER BY r.start_date DESC, e.employee_no
            """,
            params,
        ).fetchall()
        return [
            {
                "id": r[0], "employee_id": r[1], "employee_no": r[2], "full_name": r[3], "leave_type_id": r[4],
                "leave_type_code": r[5], "leave_type_name_en": r[6], "leave_type_name_fr": r[7], "legacy_leave_type": r[8],
                "start_date": r[9].isoformat(), "end_date": r[10].isoformat(), "days": r[11], "half_day": r[12],
                "reason": r[13], "document_ref": r[14], "status": r[15], "reviewed_by": r[16],
                "reviewed_at": r[17].isoformat() if r[17] else None, "review_note": r[18],
            }
            for r in rows
        ]

    def _locked(self, tenant_id: str, request_id: str) -> dict | None:
        row = self.connection.execute(
            f"SELECT {', '.join(_REQUEST_KEYS)} FROM hr.leave_requests WHERE id = %s AND tenant_id = %s FOR UPDATE",
            (request_id, tenant_id),
        ).fetchone()
        return dict(zip(_REQUEST_KEYS, row)) if row else None

    def _overlapping(self, tenant_id: str, employee_id: str, start: datetime.date, end: datetime.date, exclude_id: str | None) -> bool:
        return self.connection.execute(
            """
            SELECT 1 FROM hr.leave_requests
            WHERE tenant_id = %s AND employee_id = %s AND status IN ('pending', 'approved')
              AND start_date <= %s AND end_date >= %s AND id <> %s
            """,
            (tenant_id, employee_id, end, start, exclude_id or ""),
        ).fetchone() is not None

    def _plan(
        self, *, tenant_id: str, employee_id: str, leave_type: LeaveType, start_date: datetime.date, end_date: datetime.date, half_day: bool
    ) -> Result[_Plan]:
        dates_ok = validate_leave(start_date=start_date, end_date=end_date)
        if isinstance(dates_ok, Err):
            return dates_ok
        if self.connection.execute("SELECT 1 FROM hr.employees WHERE id = %s AND tenant_id = %s", (employee_id, tenant_id)).fetchone() is None:
            return EMPLOYEE_NOT_FOUND
        employees = employed_between(self.connection, tenant_id=tenant_id, date_from=start_date, date_to=end_date, employee_ids=[employee_id])
        if not employees or not all(is_employed(employees[0], day) for day in date_range(start_date, end_date)):
            return Err("NOT_EMPLOYED", "the employee is not employed on every day of this leave", "l'employé n'est pas en poste sur tous les jours de ce congé")
        resolved = ScheduleService(self.connection).resolve(tenant_id=tenant_id, employee_ids=[employee_id], date_from=start_date, date_to=end_date)[employee_id]
        holidays = set(HolidayService(self.connection).holiday_map(tenant_id=tenant_id, date_from=start_date, date_to=end_date))
        if leave_type.counts_days == "working" and not all(day.assigned for day in resolved.values()):
            return Err(
                "NO_SCHEDULE",
                "the employee has no schedule on some of these dates, so working days cannot be counted",
                "l'employé n'a pas d'horaire sur certaines de ces dates : les jours ouvrés ne peuvent pas être comptés",
            )
        working = {day for day, resolved_day in resolved.items() if resolved_day.is_working_day and day not in holidays}
        dates = leave_dates(start=start_date, end=end_date, counts_days=leave_type.counts_days, working_days=working)
        days = requested_days(start=start_date, end=end_date, half_day=half_day, counted=dates)
        if isinstance(days, Err):
            return days
        return Ok(_Plan(dates=dates, days=days.value, resolved=resolved, holidays=holidays))

    def _type_of(self, tenant_id: str, request: dict) -> Result[LeaveType]:
        if request["leave_type_id"] is None:
            return Err(
                "INVALID_LEAVE",
                "this old request has no leave type: set one before deciding it",
                "cette ancienne demande n'a pas de type de congé : indiquez-en un avant de la traiter",
            )
        row = LeaveTypeService(self.connection).get_type(tenant_id=tenant_id, leave_type_id=request["leave_type_id"])
        return TYPE_NOT_FOUND if row is None else Ok(_domain_type(row))

    # ---- effects of an approved request -------------------------------------------
    def _apply(self, *, tenant_id: str, actor_id: str, request: dict, leave_type: LeaveType) -> Result[None]:
        planned = self._plan(
            tenant_id=tenant_id, employee_id=request["employee_id"], leave_type=leave_type,
            start_date=request["start_date"], end_date=request["end_date"], half_day=request["half_day"],
        )
        if isinstance(planned, Err):
            return planned
        plan = planned.value
        closed = closed_periods(self.connection, tenant_id, plan.dates)
        if closed:
            return month_closed_error(closed)
        year = request["start_date"].year
        balances = LeaveBalanceService(self.connection)
        if leave_type.tracks_balance:
            enough = check_balance(balances.balance_view(tenant_id=tenant_id, employee_id=request["employee_id"], leave_type=leave_type, year=year), plan.days)
            if isinstance(enough, Err):
                return enough
        presence = PresenceService(self.connection)
        if not request["half_day"]:
            existing = presence.existing_days(tenant_id=tenant_id, employee_ids=[request["employee_id"]], date_from=min(plan.dates), date_to=max(plan.dates))
            worked = [day.isoformat() for day in plan.dates if (existing.get((request["employee_id"], day)) or {}).get("worked_minutes", 0) > 0]
            if worked:
                listed = ", ".join(worked)
                return Err("LEAVE_OVERLAPS_WORK", f"the employee worked on {listed}", f"l'employé a travaillé le {listed}")
        balances.add_taken(tenant_id=tenant_id, employee_id=request["employee_id"], leave_type_id=leave_type.id, year=year, days=plan.days)
        if not request["half_day"]:
            for day in plan.dates:
                resolved_day = plan.resolved[day]
                expected = resolved_day.window is not None and day not in plan.holidays
                figures = DayFigures(
                    status=leave_type.presence_status, schedule_id=resolved_day.schedule_id,
                    scheduled_minutes=resolved_day.window.scheduled_minutes if expected else 0, worked_minutes=0,
                )
                presence.upsert_day(
                    tenant_id=tenant_id, actor_id=actor_id, employee_id=request["employee_id"], work_date=day,
                    figures=figures, source="leave", justified=True, leave_request_id=request["id"],
                )
        self.connection.execute("UPDATE hr.leave_requests SET days = %s, balance_year = %s WHERE id = %s", (plan.days, year, request["id"]))
        return Ok(None)

    def _unapply(self, *, tenant_id: str, request: dict) -> Result[None]:
        closed = closed_periods(self.connection, tenant_id, date_range(request["start_date"], request["end_date"]))
        if closed:
            return month_closed_error(closed)
        if request["leave_type_id"] is not None and request["days"] is not None:
            LeaveBalanceService(self.connection).add_taken(
                tenant_id=tenant_id, employee_id=request["employee_id"], leave_type_id=request["leave_type_id"],
                year=request["balance_year"] or request["start_date"].year, days=-request["days"],
            )
        self.connection.execute("DELETE FROM hr.presence_days WHERE tenant_id = %s AND leave_request_id = %s", (tenant_id, request["id"]))
        return Ok(None)

    def _decide(self, tenant_id: str, actor_id: str, request: dict, status: str, note: str | None) -> None:
        self.connection.execute(
            "UPDATE hr.leave_requests SET status = %s, reviewed_by = %s, reviewed_at = NOW(), review_note = %s WHERE id = %s AND tenant_id = %s",
            (status, actor_id, note, request["id"], tenant_id),
        )
        record_audit(
            self.connection, tenant_id=tenant_id, actor_id=actor_id, action="leave_request.status_changed",
            entity_type="leave_request", entity_id=request["id"],
            payload={"from_status": request["status"], "to_status": status, "days": _text(request["days"]), "note": note},
        )

    # ---- writes -----------------------------------------------------------------
    def create_request(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        employee_id: str,
        leave_type_id: str,
        start_date: datetime.date,
        end_date: datetime.date,
        half_day: bool = False,
        reason: str | None = None,
        document_ref: str | None = None,
    ) -> Result[dict]:
        row = LeaveTypeService(self.connection).get_type(tenant_id=tenant_id, leave_type_id=leave_type_id)
        if row is None or not row["active"]:
            return TYPE_NOT_FOUND
        leave_type = _domain_type(row)
        plan = self._plan(tenant_id=tenant_id, employee_id=employee_id, leave_type=leave_type, start_date=start_date, end_date=end_date, half_day=half_day)
        if isinstance(plan, Err):
            return plan
        if self._overlapping(tenant_id, employee_id, start_date, end_date, exclude_id=None):
            return LEAVE_OVERLAP
        request_id = str(ULID())
        self.connection.execute(
            """
            INSERT INTO hr.leave_requests (id, tenant_id, employee_id, leave_type, leave_type_id, start_date, end_date, days,
                                           half_day, reason, document_ref, balance_year)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                request_id, tenant_id, employee_id, leave_type.code, leave_type.id, start_date, end_date, plan.value.days,
                half_day, reason, document_ref, start_date.year,
            ),
        )
        record_audit(
            self.connection, tenant_id=tenant_id, actor_id=actor_id, action="leave_request.created",
            entity_type="leave_request", entity_id=request_id,
            payload={
                "employee_id": employee_id, "leave_type": leave_type.code, "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(), "days": str(plan.value.days), "half_day": half_day,
            },
        )
        return Ok(self._request(tenant_id, request_id))

    def approve(self, *, tenant_id: str, actor_id: str, request_id: str, note: str | None = None) -> Result[dict]:
        request = self._locked(tenant_id, request_id)
        if request is None:
            return REQUEST_NOT_FOUND
        if request["status"] != "pending":
            return Err("INVALID_TRANSITION", "only a pending leave request can be approved", "seule une demande de congé en attente peut être approuvée")
        leave_type = self._type_of(tenant_id, request)
        if isinstance(leave_type, Err):
            return leave_type
        if leave_type.value.requires_document and not (request["document_ref"] or "").strip():
            return Err(
                "LEAVE_DOCUMENT_REQUIRED",
                "this leave type needs a supporting document before approval",
                "ce type de congé exige un justificatif avant approbation",
            )
        applied = self._apply(tenant_id=tenant_id, actor_id=actor_id, request=request, leave_type=leave_type.value)
        if isinstance(applied, Err):
            return applied
        self._decide(tenant_id, actor_id, request, "approved", note)
        return Ok(self._request(tenant_id, request_id))

    def reject(self, *, tenant_id: str, actor_id: str, request_id: str, note: str | None = None) -> Result[dict]:
        request = self._locked(tenant_id, request_id)
        if request is None:
            return REQUEST_NOT_FOUND
        if request["status"] != "pending":
            return Err("INVALID_TRANSITION", "only a pending leave request can be rejected", "seule une demande de congé en attente peut être refusée")
        self._decide(tenant_id, actor_id, request, "rejected", note)
        return Ok(self._request(tenant_id, request_id))

    def cancel(self, *, tenant_id: str, actor_id: str, request_id: str, note: str | None = None) -> Result[dict]:
        request = self._locked(tenant_id, request_id)
        if request is None:
            return REQUEST_NOT_FOUND
        if request["status"] not in ("pending", "approved"):
            return Err(
                "INVALID_TRANSITION",
                "only a pending or approved leave request can be cancelled",
                "seule une demande de congé en attente ou approuvée peut être annulée",
            )
        if request["status"] == "approved":
            undone = self._unapply(tenant_id=tenant_id, request=request)
            if isinstance(undone, Err):
                return undone
        self._decide(tenant_id, actor_id, request, "cancelled", note)
        return Ok(self._request(tenant_id, request_id))

    def update_request(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        request_id: str,
        leave_type_id: str | None = None,
        start_date: datetime.date | None = None,
        end_date: datetime.date | None = None,
        half_day: bool | None = None,
        reason: str | None = None,
        document_ref: str | None = None,
    ) -> Result[dict]:
        request = self._locked(tenant_id, request_id)
        if request is None:
            return REQUEST_NOT_FOUND
        new_type_id = leave_type_id or request["leave_type_id"]
        if new_type_id is None:
            return Err("INVALID_LEAVE", "choose a leave type", "choisissez un type de congé")
        row = LeaveTypeService(self.connection).get_type(tenant_id=tenant_id, leave_type_id=new_type_id)
        if row is None:
            return TYPE_NOT_FOUND
        leave_type = _domain_type(row)
        updated = {
            **request,
            "leave_type_id": new_type_id,
            "leave_type": leave_type.code,
            "start_date": start_date or request["start_date"],
            "end_date": end_date or request["end_date"],
            "half_day": half_day if half_day is not None else request["half_day"],
            "reason": reason if reason is not None else request["reason"],
            "document_ref": document_ref if document_ref is not None else request["document_ref"],
        }
        if request["status"] == "approved":
            undone = self._unapply(tenant_id=tenant_id, request=request)
            if isinstance(undone, Err):
                return undone
        plan = self._plan(
            tenant_id=tenant_id, employee_id=request["employee_id"], leave_type=leave_type,
            start_date=updated["start_date"], end_date=updated["end_date"], half_day=updated["half_day"],
        )
        if isinstance(plan, Err):
            return plan
        if self._overlapping(tenant_id, request["employee_id"], updated["start_date"], updated["end_date"], exclude_id=request_id):
            return LEAVE_OVERLAP
        self.connection.execute(
            """
            UPDATE hr.leave_requests
            SET leave_type_id = %s, leave_type = %s, start_date = %s, end_date = %s, half_day = %s, days = %s,
                reason = %s, document_ref = %s, balance_year = %s
            WHERE id = %s AND tenant_id = %s
            """,
            (
                new_type_id, leave_type.code, updated["start_date"], updated["end_date"], updated["half_day"], plan.value.days,
                updated["reason"], updated["document_ref"], updated["start_date"].year, request_id, tenant_id,
            ),
        )
        if request["status"] == "approved":
            applied = self._apply(tenant_id=tenant_id, actor_id=actor_id, request={**updated, "days": plan.value.days}, leave_type=leave_type)
            if isinstance(applied, Err):
                return applied
        record_audit(
            self.connection, tenant_id=tenant_id, actor_id=actor_id, action="leave_request.updated",
            entity_type="leave_request", entity_id=request_id,
            payload={
                "leave_type": leave_type.code, "start_date": updated["start_date"].isoformat(),
                "end_date": updated["end_date"].isoformat(), "half_day": updated["half_day"],
                "days": str(plan.value.days), "document_ref": updated["document_ref"],
            },
        )
        return Ok(self._request(tenant_id, request_id))
```

- [ ] **Step 4: Append the leave routes**

In `backend/modules/hr/api/presence_router.py` add the imports

```python
from decimal import Decimal

from modules.hr.api.leave_service import LeaveBalanceService, LeaveRequestService, LeaveTypeService
```

and append:

```python
# ---- leave ---------------------------------------------------------------------------

class LeaveTypeBody(BaseModel):
    code: str
    name_en: str
    name_fr: str
    paid: bool
    accrual_days_per_month: Decimal
    max_carry_over: Decimal | None = None
    counts_days: str
    requires_document: bool = False
    presence_status: str
    confirmed: bool = False


class LeaveTypeUpdateBody(BaseModel):
    name_en: str | None = None
    name_fr: str | None = None
    paid: bool | None = None
    accrual_days_per_month: Decimal | None = None
    max_carry_over: Decimal | None = None
    clear_max_carry_over: bool = False
    counts_days: str | None = None
    requires_document: bool | None = None
    presence_status: str | None = None
    confirmed: bool | None = None
    active: bool | None = None


class LeaveRequestBody(BaseModel):
    employee_id: str
    leave_type_id: str
    start_date: datetime.date
    end_date: datetime.date
    half_day: bool = False
    reason: str | None = None
    document_ref: str | None = None


class LeaveRequestUpdateBody(BaseModel):
    leave_type_id: str | None = None
    start_date: datetime.date | None = None
    end_date: datetime.date | None = None
    half_day: bool | None = None
    reason: str | None = None
    document_ref: str | None = None


class LeaveDecisionBody(BaseModel):
    note: str | None = None


class LeaveAdjustBody(BaseModel):
    employee_id: str
    leave_type_id: str
    year: int
    delta: Decimal
    reason: str


@router.get("/leave-types")
def list_leave_types(tenant: TenantContext = Depends(require_permission("hr.view_leave"))):
    return _read(lambda c: LeaveTypeService(c).list_types(tenant_id=tenant.tenant_id))


@router.post("/leave-types", status_code=status.HTTP_201_CREATED)
def create_leave_type(body: LeaveTypeBody, tenant: TenantContext = Depends(require_permission("hr.manage_leave"))):
    return _write(lambda c: LeaveTypeService(c).create_type(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, **body.model_dump()))


@router.patch("/leave-types/{leave_type_id}")
def update_leave_type(leave_type_id: str, body: LeaveTypeUpdateBody, tenant: TenantContext = Depends(require_permission("hr.admin_leave"))):
    return _write(lambda c: LeaveTypeService(c).update_type(
        tenant_id=tenant.tenant_id, actor_id=tenant.user_id, leave_type_id=leave_type_id, **body.model_dump()
    ))


@router.get("/leave/requests")
def list_leave_requests(status_filter: str | None = None, employee_id: str | None = None, tenant: TenantContext = Depends(require_permission("hr.view_leave"))):
    return _read(lambda c: LeaveRequestService(c).list_requests(tenant_id=tenant.tenant_id, status=status_filter, employee_id=employee_id))


@router.post("/leave/requests", status_code=status.HTTP_201_CREATED)
def create_leave_request(body: LeaveRequestBody, tenant: TenantContext = Depends(require_permission("hr.manage_leave"))):
    return _write(lambda c: LeaveRequestService(c).create_request(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, **body.model_dump()))


@router.patch("/leave/requests/{request_id}")
def update_leave_request(request_id: str, body: LeaveRequestUpdateBody, tenant: TenantContext = Depends(require_permission("hr.admin_leave"))):
    return _write(lambda c: LeaveRequestService(c).update_request(
        tenant_id=tenant.tenant_id, actor_id=tenant.user_id, request_id=request_id, **body.model_dump()
    ))


@router.post("/leave/requests/{request_id}/approve")
def approve_leave_request(request_id: str, body: LeaveDecisionBody | None = None, tenant: TenantContext = Depends(require_permission("hr.manage_leave"))):
    return _write(lambda c: LeaveRequestService(c).approve(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, request_id=request_id, note=body.note if body else None))


@router.post("/leave/requests/{request_id}/reject")
def reject_leave_request(request_id: str, body: LeaveDecisionBody | None = None, tenant: TenantContext = Depends(require_permission("hr.manage_leave"))):
    return _write(lambda c: LeaveRequestService(c).reject(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, request_id=request_id, note=body.note if body else None))


@router.post("/leave/requests/{request_id}/cancel")
def cancel_leave_request(request_id: str, body: LeaveDecisionBody | None = None, tenant: TenantContext = Depends(require_permission("hr.manage_leave"))):
    return _write(lambda c: LeaveRequestService(c).cancel(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, request_id=request_id, note=body.note if body else None))


@router.get("/leave/balances")
def list_leave_balances(year: int, employee_id: str | None = None, tenant: TenantContext = Depends(require_permission("hr.view_leave"))):
    return _read(lambda c: LeaveBalanceService(c).balances(tenant_id=tenant.tenant_id, year=year, employee_id=employee_id))


@router.post("/leave/balances/adjust")
def adjust_leave_balance(body: LeaveAdjustBody, tenant: TenantContext = Depends(require_permission("hr.admin_leave"))):
    return _write(lambda c: LeaveBalanceService(c).adjust(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, **body.model_dump()))
```

The status query parameter is named `status_filter` (as the existing `/hr/employees` route does) so it does not shadow `fastapi.status`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest modules/hr -q`
Expected: all pass, 0 skipped.

- [ ] **Step 6: Commit**

```bash
git add backend/modules/hr/migrations/0014_hr_leave_types_balances.sql backend/modules/hr/api/leave_service.py backend/modules/hr/api/presence_router.py backend/modules/hr/api/test_leave_integration.py backend/modules/hr/api/test_presence_router_routes.py
git commit -m "feat(hr): leave types, approval against balances, leave presence days

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Month close and reopen, the payroll summary, the closed event and the payroll-lock consumers

**Files:**
- Create: `backend/modules/hr/api/presence_month_service.py`
- Create: `backend/modules/hr/events/__init__.py` (empty), `backend/modules/hr/events/consumers.py`
- Modify: `backend/modules/hr/api/presence_service.py` (add `month_summary`)
- Modify: `backend/modules/hr/api/presence_router.py` (append the month section)
- Modify: `backend/modules/hr/api/presence_testkit.py` (add `fill_month`)
- Modify: `backend/worker/main.py` (import the hr consumers)
- Modify: `backend/modules/hr/module.json`, `backend/events/CATALOG.md`
- Test: `backend/modules/hr/api/test_presence_month_integration.py`, `backend/modules/hr/api/test_presence_router_routes.py` (append one test)

**Interfaces:**
- Consumes: everything above; `core.events.outbox.publish_event`; `core.events.consumers.register`.
- Produces:
  - `PresenceService.month_summary(self, *, tenant_id: str, period: datetime.date, employee_ids: list[str] | None = None) -> list[dict]` (**contract**; keys exactly `SUMMARY_FIELDS` + `employee_id`, ints; with `employee_ids` every requested id is returned, zeros when no row; without, the employees having rows).
  - `PresenceMonthService(connection)`: `list_months(*, tenant_id, year) -> list[dict]` (12 dicts: `period, status, closed_by, closed_at, payroll_locked`); `gaps(*, tenant_id, period) -> list[dict]` (dict: `employee_id, employee_no, full_name, work_date, reason` in `missing | no_schedule`); `close(*, tenant_id, actor_id, period, correlation_id=None) -> Result[dict]` (`{period, status, locked_rows, holiday_rows, accruals_posted}`); `reopen(*, tenant_id, actor_id, period, reason) -> Result[dict]`.
  - Event `hr.presence_month.closed` v1.0, producer `hr`, payload `{"period": "YYYY-MM-01"}`.
  - Consumers `hr.payroll_run_approved` (on `payroll.run.approved`, payload `{run_id, period, run_type}`) and `hr.payroll_run_reversed` (on `payroll.run.reversed`, payload `{run_id, period}`) maintaining `hr.presence_month_payroll_locks`.
  - Refusal codes: `PRESENCE_INCOMPLETE`, `LEAVE_PENDING`, `PRESENCE_PAYROLL_APPROVED`, `INVALID_REOPEN`, `INVALID_PERIOD`, `INVALID_TRANSITION`.
  - Routes: `GET /hr/presence/months?year=`, `GET /hr/presence/months/{period}/gaps`, `GET /hr/presence/months/{period}/summary?employee_id=`, `POST /hr/presence/months/{period}/close`, `POST /hr/presence/months/{period}/reopen` body `{reason}`.
  - Testkit: `fill_month(db, env: PresenceEnv, period) -> None`.

- [ ] **Step 1: Add `fill_month` to the test kit**

In `backend/modules/hr/api/presence_testkit.py` add the imports

```python
from modules.hr.api.presence_service import PresenceService
from modules.hr.domain.presence import ManualEntry
```

and the helper:

```python
def fill_month(db, env: PresenceEnv, period: datetime.date) -> None:
    """Saves 'present' on every working day of both test workers that has no row yet (public holidays left alone)."""
    presence = PresenceService(db)
    entries: list[ManualEntry] = []
    for employee_id in (env.day_worker, env.night_worker):
        month = presence.employee_month(tenant_id=TENANT, employee_id=employee_id, period=period).value
        entries += [
            ManualEntry(employee_id=employee_id, work_date=datetime.date.fromisoformat(day["work_date"]), status="present")
            for day in month["days"]
            if day["default_status"] == "present" and day["record"] is None
        ]
    saved = presence.save_days(tenant_id=TENANT, actor_id=env.actor, entries=entries)
    assert isinstance(saved, Ok), saved
```

- [ ] **Step 2: Write the failing integration tests and route test**

`backend/modules/hr/api/test_presence_month_integration.py`:

```python
"""Closing and reopening a month, the summary payroll reads, and the payroll-lock consumers."""
from __future__ import annotations

import datetime
from decimal import Decimal

from ulid import ULID

from core.domain.result import Err, Ok
from modules.hr.api.leave_service import LeaveRequestService, LeaveTypeService
from modules.hr.api.presence_month_service import PresenceMonthService
from modules.hr.api.presence_service import PresenceService
from modules.hr.api.presence_testkit import AUG_1, AUG_3, TENANT, add_employee, fill_month, presence_env, presence_row  # noqa: F401
from modules.hr.api.schedule_service import HolidayService, ScheduleService
from modules.hr.domain.presence import ManualEntry
from modules.hr.events.consumers import _handle_run_approved, _handle_run_reversed

AUG_5 = datetime.date(2026, 8, 5)
AUG_31 = datetime.date(2026, 8, 31)
CONTRACT_KEYS = {
    "employee_id", "scheduled_days", "worked_days", "unpaid_absence_days", "paid_leave_days", "sick_days", "holiday_days",
    "holidays_worked_days", "ot_minutes_day", "ot_minutes_night", "ot_minutes_rest_holiday", "night_minutes", "late_minutes",
}


def _close(db, env):
    return PresenceMonthService(db).close(tenant_id=TENANT, actor_id=env.actor, period=AUG_1)


def _envelope(event_type: str, run_id: str) -> dict:
    return {
        "event_id": str(ULID()), "event_type": event_type, "tenant_id": TENANT,
        "payload": {"run_id": run_id, "period": "2026-08-01", "run_type": "regular"},
    }


def test_gaps_list_every_working_day_without_presence_and_block_the_close(db, presence_env):
    gaps = PresenceMonthService(db).gaps(tenant_id=TENANT, period=AUG_1)
    assert len([gap for gap in gaps if gap["reason"] == "missing"]) == 52  # 26 working days (Mon-Sat) x 2 people
    refused = _close(db, presence_env)
    assert isinstance(refused, Err) and refused.code == "PRESENCE_INCOMPLETE" and "52" in refused.message_fr


def test_gaps_stop_at_the_termination_date_and_a_person_without_schedule_is_a_gap(db, presence_env):
    leaver = add_employee(db, employee_no="P-004", department=presence_env.department, termination_date=datetime.date(2026, 8, 14))
    ScheduleService(db).create_assignment(
        tenant_id=TENANT, actor_id=presence_env.actor, employee_id=leaver, valid_from=datetime.date(2026, 1, 1),
        schedule_id=presence_env.day_schedule,
    )
    unscheduled = add_employee(db, employee_no="P-005", department=presence_env.department)
    gaps = PresenceMonthService(db).gaps(tenant_id=TENANT, period=AUG_1)
    leaver_days = [gap["work_date"] for gap in gaps if gap["employee_id"] == leaver]
    assert len(leaver_days) == 12 and leaver_days[-1] == "2026-08-14"
    assert {gap["reason"] for gap in gaps if gap["employee_id"] == unscheduled} == {"no_schedule"}


def test_closing_a_complete_month_writes_holidays_locks_rows_and_announces_it(db, presence_env):
    HolidayService(db).create_holiday(tenant_id=TENANT, actor_id=presence_env.actor, country_code="ML", holiday_date=AUG_5, name="Jour de test")
    fill_month(db, presence_env, AUG_1)
    closed = _close(db, presence_env)
    assert isinstance(closed, Ok)
    assert (closed.value["status"], closed.value["holiday_rows"]) == ("closed", 2)
    assert presence_row(db, presence_env.day_worker, AUG_5)["status"] == "holiday"
    unlocked = db.execute(
        "SELECT count(*) FROM hr.presence_days WHERE tenant_id = %s AND work_date BETWEEN %s AND %s AND NOT locked", (TENANT, AUG_1, AUG_31)
    ).fetchone()[0]
    assert unlocked == 0
    envelope = db.execute("SELECT payload FROM events.outbox WHERE tenant_id = %s AND event_type = 'hr.presence_month.closed'", (TENANT,)).fetchone()[0]
    assert envelope["payload"] == {"period": "2026-08-01"} and envelope["producer"] == "hr"
    assert PresenceService(db).is_month_closed(tenant_id=TENANT, period=AUG_1) is True
    august = next(m for m in PresenceMonthService(db).list_months(tenant_id=TENANT, year=2026) if m["period"] == "2026-08-01")
    assert (august["status"], august["payroll_locked"]) == ("closed", False)
    again = _close(db, presence_env)
    assert isinstance(again, Err) and again.code == "INVALID_TRANSITION"
    refused = PresenceService(db).save_days(tenant_id=TENANT, actor_id=presence_env.actor, entries=[
        ManualEntry(employee_id=presence_env.day_worker, work_date=AUG_3, status="absent"),
    ])
    assert refused.code == "PRESENCE_MONTH_CLOSED"


def test_a_pending_leave_request_touching_the_month_blocks_the_close(db, presence_env):
    fill_month(db, presence_env, AUG_1)
    unpaid = LeaveTypeService(db).create_type(
        tenant_id=TENANT, actor_id=presence_env.actor, code="SANS_SOLDE", name_en="Unpaid leave", name_fr="Congé sans solde",
        paid=False, accrual_days_per_month=Decimal("0"), max_carry_over=None, counts_days="calendar",
        requires_document=False, presence_status="leave",
    ).value
    LeaveRequestService(db).create_request(
        tenant_id=TENANT, actor_id=presence_env.actor, employee_id=presence_env.day_worker, leave_type_id=unpaid["id"],
        start_date=AUG_31, end_date=datetime.date(2026, 9, 2),
    )
    refused = _close(db, presence_env)
    assert isinstance(refused, Err) and refused.code == "LEAVE_PENDING" and refused.message_fr


def test_reopening_needs_a_reason_and_no_approved_payroll(db, presence_env):
    fill_month(db, presence_env, AUG_1)
    assert isinstance(_close(db, presence_env), Ok)
    months = PresenceMonthService(db)
    no_reason = months.reopen(tenant_id=TENANT, actor_id=presence_env.actor, period=AUG_1, reason=" ")
    assert isinstance(no_reason, Err) and no_reason.code == "INVALID_REOPEN"
    _handle_run_approved(db, _envelope("payroll.run.approved", "run-1"))
    _handle_run_approved(db, _envelope("payroll.run.approved", "run-1"))  # a redelivery changes nothing
    assert db.execute("SELECT count(*) FROM hr.presence_month_payroll_locks WHERE tenant_id = %s", (TENANT,)).fetchone()[0] == 1
    blocked = months.reopen(tenant_id=TENANT, actor_id=presence_env.actor, period=AUG_1, reason="correction d'un pointage")
    assert isinstance(blocked, Err) and blocked.code == "PRESENCE_PAYROLL_APPROVED" and blocked.message_fr
    _handle_run_reversed(db, _envelope("payroll.run.reversed", "run-1"))
    reopened = months.reopen(tenant_id=TENANT, actor_id=presence_env.actor, period=AUG_1, reason="correction d'un pointage")
    assert isinstance(reopened, Ok) and reopened.value["status"] == "open"
    assert presence_row(db, presence_env.day_worker, AUG_3)["locked"] is False
    assert PresenceService(db).is_month_closed(tenant_id=TENANT, period=AUG_1) is False
    audit = db.execute("SELECT payload FROM core.audit_log WHERE tenant_id = %s AND action = 'presence_month.reopened'", (TENANT,)).fetchone()[0]
    assert audit["reason"] == "correction d'un pointage"


def test_the_month_summary_is_exactly_what_payroll_is_promised(db, presence_env):
    HolidayService(db).create_holiday(tenant_id=TENANT, actor_id=presence_env.actor, country_code="ML", holiday_date=AUG_5, name="Jour de test")
    fill_month(db, presence_env, AUG_1)
    PresenceService(db).save_days(tenant_id=TENANT, actor_id=presence_env.actor, entries=[
        ManualEntry(employee_id=presence_env.day_worker, work_date=datetime.date(2026, 8, 4), status="late", late_minutes=30),
        ManualEntry(employee_id=presence_env.day_worker, work_date=datetime.date(2026, 8, 6), status="absent"),
    ])
    assert isinstance(_close(db, presence_env), Ok)
    nobody = add_employee(db, employee_no="P-009", department=presence_env.department)
    summary = PresenceService(db).month_summary(
        tenant_id=TENANT, period=AUG_1, employee_ids=[presence_env.day_worker, presence_env.night_worker, nobody]
    )
    assert all(set(item) == CONTRACT_KEYS for item in summary)
    assert all(type(value) is int for item in summary for key, value in item.items() if key != "employee_id")
    day, night, empty = summary
    assert (day["scheduled_days"], day["worked_days"], day["unpaid_absence_days"], day["holiday_days"], day["late_minutes"]) == (25, 24, 1, 1, 30)
    assert (night["worked_days"], night["night_minutes"], night["holiday_days"]) == (25, 25 * 360, 1)
    assert empty == {"employee_id": nobody, **{key: 0 for key in CONTRACT_KEYS - {"employee_id"}}}


def test_the_payroll_consumers_are_registered():
    from core.events.consumers import _registry

    assert ("hr.payroll_run_approved", _handle_run_approved) in _registry["payroll.run.approved"]
    assert ("hr.payroll_run_reversed", _handle_run_reversed) in _registry["payroll.run.reversed"]
```

Append to `backend/modules/hr/api/test_presence_router_routes.py`:

```python
def test_month_routes_and_their_permissions():
    expected = {
        ("GET", "/hr/presence/months"): "hr.view_presence",
        ("GET", "/hr/presence/months/{period}/gaps"): "hr.view_presence",
        ("GET", "/hr/presence/months/{period}/summary"): "hr.view_presence",
        ("POST", "/hr/presence/months/{period}/close"): "hr.close_presence",
        ("POST", "/hr/presence/months/{period}/reopen"): "hr.admin_presence",
    }
    routes = _routes()
    assert {key: routes.get(key) for key in expected} == expected
```

Run: `.venv/Scripts/python -m pytest modules/hr/api/test_presence_month_integration.py modules/hr/api/test_presence_router_routes.py -q`
Expected: FAIL (`No module named 'modules.hr.api.presence_month_service'`).

- [ ] **Step 3: Add `month_summary` to `PresenceService`**

In `backend/modules/hr/api/presence_service.py` extend the presence-domain import to

```python
from modules.hr.domain.presence import DayFigures, ManualEntry, SummaryRow, default_status, figures_for_entry, summarize_month, validate_entry
```

and add this method to `PresenceService` (after `is_month_closed`):

```python
    def month_summary(self, *, tenant_id: str, period: datetime.date, employee_ids: list[str] | None = None) -> list[dict]:
        """Payroll's only presence input (cross-phase contract). One dict per employee, every count an int.

        With `employee_ids`, every requested id is returned (zeros when nothing is recorded);
        without, the employees that have presence rows in the month. Read it once the month is
        closed (`is_month_closed`): before that the figures can still change.
        """
        first, last = month_bounds(period)
        params: list[object] = [tenant_id, first, last]
        clause = ""
        if employee_ids is not None:
            clause = " AND p.employee_id = ANY(%s)"
            params.append(list(employee_ids))
        rows = self.connection.execute(
            f"""
            SELECT p.employee_id, p.work_date, p.status, p.scheduled_minutes, p.worked_minutes, p.late_minutes,
                   p.ot_minutes_day, p.ot_minutes_night, p.ot_minutes_rest_holiday, p.night_minutes, p.justified, t.paid
            FROM hr.presence_days p
            LEFT JOIN hr.leave_requests r ON r.id = p.leave_request_id
            LEFT JOIN hr.leave_types t ON t.id = r.leave_type_id
            WHERE p.tenant_id = %s AND p.work_date BETWEEN %s AND %s{clause}
            """,
            params,
        ).fetchall()
        summary_rows = [
            SummaryRow(
                employee_id=r[0], work_date=r[1], status=r[2], scheduled_minutes=r[3], worked_minutes=r[4], late_minutes=r[5],
                ot_minutes_day=r[6], ot_minutes_night=r[7], ot_minutes_rest_holiday=r[8], night_minutes=r[9], justified=r[10],
                leave_paid=r[11] if r[2] == "leave" else None,
            )
            for r in rows
        ]
        holidays = HolidayService(self.connection).holiday_map(tenant_id=tenant_id, date_from=first, date_to=last)
        paid_holidays = {day for day, paid in holidays.items() if paid}
        ids = list(employee_ids) if employee_ids is not None else sorted({row.employee_id for row in summary_rows})
        return summarize_month(ids, summary_rows, paid_holidays)
```

- [ ] **Step 4: Write the month service and the consumers**

`backend/modules/hr/api/presence_month_service.py`:

```python
"""Closing and reopening a month of presence.

Close refuses while any working day of an employed person has no presence row (or no schedule
says which days they work), or while a leave request touching the month is pending. It then
writes the public-holiday days nobody recorded, locks every row of the month, posts the month's
leave accrual, and publishes hr.presence_month.closed (payload {period}).
Reopen (hr.admin_presence) needs a reason and is refused while an approved payroll run exists
for the month (hr.presence_month_payroll_locks, fed by the payroll events); it unlocks the rows.
"""
from __future__ import annotations

import datetime

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from core.events.outbox import publish_event
from modules.hr.api.leave_service import LeaveBalanceService
from modules.hr.api.presence_service import PresenceService, employed_between, is_employed, month_bounds
from modules.hr.api.schedule_service import HolidayService, ScheduleService
from modules.hr.domain.presence import DayFigures
from modules.hr.domain.schedule import ResolvedDay, date_range

CLOSED_EVENT = "hr.presence_month.closed"
INVALID_PERIOD = Err("INVALID_PERIOD", "a period is the first day of a month", "une période est le premier jour d'un mois")


class PresenceMonthService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    def list_months(self, *, tenant_id: str, year: int) -> list[dict]:
        stored = {
            row[0]: row
            for row in self.connection.execute(
                "SELECT period, status, closed_by, closed_at FROM hr.presence_months WHERE tenant_id = %s AND EXTRACT(YEAR FROM period) = %s",
                (tenant_id, year),
            ).fetchall()
        }
        locked = {
            row[0]
            for row in self.connection.execute(
                "SELECT DISTINCT period FROM hr.presence_month_payroll_locks WHERE tenant_id = %s AND EXTRACT(YEAR FROM period) = %s",
                (tenant_id, year),
            ).fetchall()
        }
        months = []
        for month in range(1, 13):
            period = datetime.date(year, month, 1)
            row = stored.get(period)
            months.append({
                "period": period.isoformat(),
                "status": row[1] if row else "open",
                "closed_by": row[2] if row else None,
                "closed_at": row[3].isoformat() if row and row[3] else None,
                "payroll_locked": period in locked,
            })
        return months

    def gaps(self, *, tenant_id: str, period: datetime.date) -> list[dict]:
        first, last = month_bounds(period)
        return self._scan(tenant_id, first, last)[0]

    def _scan(self, tenant_id: str, first: datetime.date, last: datetime.date) -> tuple[list[dict], list[tuple[dict, datetime.date, ResolvedDay]]]:
        """The gaps, and the public-holiday working days nobody recorded (written on close)."""
        employees = employed_between(self.connection, tenant_id=tenant_id, date_from=first, date_to=last)
        if not employees:
            return [], []
        ids = [employee["id"] for employee in employees]
        resolved = ScheduleService(self.connection).resolve(tenant_id=tenant_id, employee_ids=ids, date_from=first, date_to=last)
        holidays = HolidayService(self.connection).holiday_map(tenant_id=tenant_id, date_from=first, date_to=last)
        existing = PresenceService(self.connection).existing_days(tenant_id=tenant_id, employee_ids=ids, date_from=first, date_to=last)
        gaps: list[dict] = []
        holiday_days: list[tuple[dict, datetime.date, ResolvedDay]] = []
        for employee in employees:
            for day in date_range(first, last):
                if not is_employed(employee, day) or (employee["id"], day) in existing:
                    continue
                resolved_day = resolved[employee["id"]][day]
                label = {
                    "employee_id": employee["id"], "employee_no": employee["employee_no"],
                    "full_name": employee["full_name"], "work_date": day.isoformat(),
                }
                if not resolved_day.assigned:
                    gaps.append({**label, "reason": "no_schedule"})
                elif resolved_day.is_working_day and day in holidays:
                    holiday_days.append((employee, day, resolved_day))
                elif resolved_day.is_working_day:
                    gaps.append({**label, "reason": "missing"})
        return gaps, holiday_days

    def close(self, *, tenant_id: str, actor_id: str, period: datetime.date, correlation_id: str | None = None) -> Result[dict]:
        if period.day != 1:
            return INVALID_PERIOD
        first, last = month_bounds(period)
        current = self.connection.execute(
            "SELECT status FROM hr.presence_months WHERE tenant_id = %s AND period = %s FOR UPDATE", (tenant_id, first)
        ).fetchone()
        if current is not None and current[0] == "closed":
            return Err("INVALID_TRANSITION", "presence for this month is already closed", "la présence de ce mois est déjà clôturée")
        pending = self.connection.execute(
            "SELECT count(*) FROM hr.leave_requests WHERE tenant_id = %s AND status = 'pending' AND start_date <= %s AND end_date >= %s",
            (tenant_id, last, first),
        ).fetchone()[0]
        if pending:
            return Err(
                "LEAVE_PENDING",
                f"{pending} leave request(s) touching this month are still pending",
                f"{pending} demande(s) de congé touchant ce mois sont encore en attente",
            )
        gaps, holiday_days = self._scan(tenant_id, first, last)
        if gaps:
            sample = ", ".join(f"{gap['employee_no']} {gap['work_date']}" for gap in gaps[:5])
            return Err(
                "PRESENCE_INCOMPLETE",
                f"{len(gaps)} working day(s) have no presence (for example {sample})",
                f"{len(gaps)} jour(s) de travail sans présence (par exemple {sample})",
            )
        presence = PresenceService(self.connection)
        for employee, day, resolved_day in holiday_days:
            presence.upsert_day(
                tenant_id=tenant_id, actor_id=actor_id, employee_id=employee["id"], work_date=day,
                figures=DayFigures(status="holiday", schedule_id=resolved_day.schedule_id, scheduled_minutes=0, worked_minutes=0),
                source="holiday", justified=True,
            )
        locked = self.connection.execute(
            "UPDATE hr.presence_days SET locked = TRUE WHERE tenant_id = %s AND work_date BETWEEN %s AND %s", (tenant_id, first, last)
        ).rowcount
        accruals = LeaveBalanceService(self.connection).post_month_accruals(tenant_id=tenant_id, period=first)
        self.connection.execute(
            """
            INSERT INTO hr.presence_months (tenant_id, period, status, closed_by, closed_at) VALUES (%s, %s, 'closed', %s, NOW())
            ON CONFLICT (tenant_id, period) DO UPDATE SET status = 'closed', closed_by = EXCLUDED.closed_by, closed_at = NOW()
            """,
            (tenant_id, first, actor_id),
        )
        publish_event(
            self.connection, event_type=CLOSED_EVENT, producer="hr", tenant_id=tenant_id,
            correlation_id=correlation_id or str(ULID()), payload={"period": first.isoformat()},
        )
        outcome = {"period": first.isoformat(), "status": "closed", "locked_rows": locked, "holiday_rows": len(holiday_days), "accruals_posted": accruals}
        record_audit(
            self.connection, tenant_id=tenant_id, actor_id=actor_id, action="presence_month.closed",
            entity_type="presence_month", entity_id=first.isoformat(), payload=outcome,
        )
        return Ok(outcome)

    def reopen(self, *, tenant_id: str, actor_id: str, period: datetime.date, reason: str) -> Result[dict]:
        if period.day != 1:
            return INVALID_PERIOD
        if not (reason or "").strip():
            return Err("INVALID_REOPEN", "a reason is required to reopen a month", "un motif est obligatoire pour rouvrir un mois")
        current = self.connection.execute(
            "SELECT status FROM hr.presence_months WHERE tenant_id = %s AND period = %s FOR UPDATE", (tenant_id, period)
        ).fetchone()
        if current is None or current[0] != "closed":
            return Err("INVALID_TRANSITION", "only a closed month can be reopened", "seul un mois clôturé peut être rouvert")
        runs = self.connection.execute(
            "SELECT count(*) FROM hr.presence_month_payroll_locks WHERE tenant_id = %s AND period = %s", (tenant_id, period)
        ).fetchone()[0]
        if runs:
            return Err(
                "PRESENCE_PAYROLL_APPROVED",
                "an approved payroll run exists for this month; reverse it before reopening presence",
                "une paie approuvée existe pour ce mois ; annulez-la avant de rouvrir la présence",
            )
        first, last = month_bounds(period)
        unlocked = self.connection.execute(
            "UPDATE hr.presence_days SET locked = FALSE WHERE tenant_id = %s AND work_date BETWEEN %s AND %s", (tenant_id, first, last)
        ).rowcount
        self.connection.execute(
            "UPDATE hr.presence_months SET status = 'open', reopened_by = %s, reopened_at = NOW() WHERE tenant_id = %s AND period = %s",
            (actor_id, tenant_id, period),
        )
        record_audit(
            self.connection, tenant_id=tenant_id, actor_id=actor_id, action="presence_month.reopened",
            entity_type="presence_month", entity_id=period.isoformat(),
            payload={"period": period.isoformat(), "reason": reason.strip(), "unlocked_rows": unlocked},
        )
        return Ok({"period": period.isoformat(), "status": "open", "unlocked_rows": unlocked})
```

`backend/modules/hr/events/__init__.py`: empty file.

`backend/modules/hr/events/consumers.py`:

```python
"""hr reacts to payroll: while a payroll run of a month is approved, that month's presence
cannot be reopened. Phase 3 publishes these events; until it ships the handlers never fire.

Idempotent twice over: the registry skips an event_id a consumer already processed, and the
handlers are no-ops on a repeat (insert on conflict do nothing / delete).
"""
from __future__ import annotations

import datetime

import psycopg

from core.events.consumers import register

APPROVED_CONSUMER = "hr.payroll_run_approved"
REVERSED_CONSUMER = "hr.payroll_run_reversed"


def _period(payload: dict) -> datetime.date:
    return datetime.date.fromisoformat(str(payload["period"])[:10])


def _handle_run_approved(connection: psycopg.Connection, envelope: dict) -> None:
    payload = envelope["payload"]
    connection.execute(
        """
        INSERT INTO hr.presence_month_payroll_locks (tenant_id, run_id, period) VALUES (%s, %s, %s)
        ON CONFLICT (tenant_id, run_id) DO NOTHING
        """,
        (envelope["tenant_id"], payload["run_id"], _period(payload)),
    )


def _handle_run_reversed(connection: psycopg.Connection, envelope: dict) -> None:
    connection.execute(
        "DELETE FROM hr.presence_month_payroll_locks WHERE tenant_id = %s AND run_id = %s",
        (envelope["tenant_id"], envelope["payload"]["run_id"]),
    )


register(APPROVED_CONSUMER, "payroll.run.approved", _handle_run_approved)
register(REVERSED_CONSUMER, "payroll.run.reversed", _handle_run_reversed)
```

- [ ] **Step 5: Append the month routes and wire the worker, manifest and catalog**

In `backend/modules/hr/api/presence_router.py` add the import

```python
from modules.hr.api.presence_month_service import PresenceMonthService
```

and append:

```python
# ---- month close ---------------------------------------------------------------------

class ReopenBody(BaseModel):
    reason: str


@router.get("/presence/months")
def list_presence_months(year: int, tenant: TenantContext = Depends(require_permission("hr.view_presence"))):
    return _read(lambda c: PresenceMonthService(c).list_months(tenant_id=tenant.tenant_id, year=year))


@router.get("/presence/months/{period}/gaps")
def presence_month_gaps(period: datetime.date, tenant: TenantContext = Depends(require_permission("hr.view_presence"))):
    return _read(lambda c: PresenceMonthService(c).gaps(tenant_id=tenant.tenant_id, period=_period(period)))


@router.get("/presence/months/{period}/summary")
def presence_month_summary(period: datetime.date, employee_id: str | None = None, tenant: TenantContext = Depends(require_permission("hr.view_presence"))):
    return _read(lambda c: PresenceService(c).month_summary(
        tenant_id=tenant.tenant_id, period=_period(period), employee_ids=[employee_id] if employee_id else None
    ))


@router.post("/presence/months/{period}/close")
def close_presence_month(period: datetime.date, tenant: TenantContext = Depends(require_permission("hr.close_presence"))):
    return _write(lambda c: PresenceMonthService(c).close(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, period=_period(period)))


@router.post("/presence/months/{period}/reopen")
def reopen_presence_month(period: datetime.date, body: ReopenBody, tenant: TenantContext = Depends(require_permission("hr.admin_presence"))):
    return _write(lambda c: PresenceMonthService(c).reopen(
        tenant_id=tenant.tenant_id, actor_id=tenant.user_id, period=_period(period), reason=body.reason
    ))
```

In `backend/worker/main.py`, next to the other consumer imports, add:

```python
from modules.hr.events import consumers as _hr_consumers  # noqa: F401
```

In `backend/modules/hr/module.json` add to the existing arrays (keep every entry phase 1 put there; the five presence permission codes must already be listed — add any that is missing):

```json
"provides_api": ["PresenceService", "ScheduleService", "LeaveRequestService", "LeaveBalanceService"],
"publishes_events": ["hr.presence_month.closed"],
"subscribes_events": ["payroll.run.approved", "payroll.run.reversed"],
```

(i.e. append these values to `provides_api`, and set/extend `publishes_events` and `subscribes_events`).

In `backend/events/CATALOG.md` add a row after the `qc.*` rows:

```markdown
| `hr.presence_month.closed` | 1.0 | hr | payroll (phase 3) | `period` (ISO date, first day of the month) — every presence day of the month is locked and complete; `PresenceService.month_summary` for it is final until the month is reopened. |
```

(Phase 3 adds the `payroll.run.*` rows; it must list `hr` among the consumers of `payroll.run.approved` and `payroll.run.reversed`.)

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest modules/hr -q`
Expected: all pass, 0 skipped.
Run: `.venv/Scripts/python -c "import worker.main"` (from `backend/`)
Expected: no import error.

- [ ] **Step 7: Commit**

```bash
git add backend/modules/hr/api/presence_month_service.py backend/modules/hr/api/presence_service.py backend/modules/hr/api/presence_router.py backend/modules/hr/api/presence_testkit.py backend/modules/hr/events/__init__.py backend/modules/hr/events/consumers.py backend/modules/hr/api/test_presence_month_integration.py backend/modules/hr/api/test_presence_router_routes.py backend/worker/main.py backend/modules/hr/module.json backend/events/CATALOG.md
git commit -m "feat(hr): presence month close/reopen, payroll month summary, hr.presence_month.closed

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Frontend foundation + `/hr/schedules` (schedules, rotations, assignments, holidays, settings)

**Files:**
- Create: `frontend/src/features/hr/presenceApi.ts`
- Create: `frontend/src/features/hr/presenceFormat.ts`
- Create: `frontend/src/features/hr/HrListTable.tsx`
- Create: `frontend/src/features/hr/HrTabsPage.tsx`
- Create: `frontend/src/features/hr/presence/PresenceStatusBadge.tsx`
- Create: `frontend/src/features/hr/schedules/SchedulesPage.tsx`, `WorkSchedulesTab.tsx`, `RotationsTab.tsx`, `AssignmentsTab.tsx`, `HolidaysTab.tsx`, `PresenceSettingsCard.tsx`
- Modify: `frontend/src/routes/router.tsx`, `frontend/src/routes/Sidebar.tsx`, `frontend/src/lib/i18n.tsx`

**Interfaces:**
- Consumes: every backend route of Tasks 2–9 (exact paths and dict shapes listed in those tasks); `listEmployees(token)` / `listDepartments(token)` and type `Employee` from `frontend/src/features/hr/api.ts` (phase 1 may have extended them; only `id, employee_no, first_name, last_name, department_id` are used); `useTableColumns`, `useColumnFilters`, `ColumnFilterRow`, `ColumnVisibilityMenu`, `FilterTabs`, `StickyTabBar`, `AppLoader`, `EmptyState`, `Skeleton`, Radix `Tabs`.
- Produces (used by Tasks 11–13):
  - `presenceApi.ts`: every type and fetcher below, and `HR_KEYS` (query keys; every presence write invalidates `HR_KEYS.presence`, a prefix of all grid/week/month/summary keys).
  - `presenceFormat.ts`: `minutesToClock`, `clockToMinutes`, `formatDuration`, `spanMinutes`, `todayIso`, `addDaysIso`, `weekdayOf`, `mondayOf`, `monthStartOf`, `formatDay`, `formatMonth`, `errorText`, `employeeLabel`.
  - `HrListTable<Row>` props: `tableKey, columns, rows, rowKey, loading, emptyIcon, emptyTitle, emptyDescription, toolbar?, filtersActive?, onClearFilters?, rowClassName?`.
  - `HrTabsPage<T>` props: `title, subtitle, tabs: HrTab<T>[], active, onChange, layoutId, booted, loaderLabel, actions?`; hooks `useTabParam(values, fallback)`, `useBooted(ready)`.
  - `PresenceStatusBadge({ status })`, `PRESENCE_STATUS_LABEL`, `WEEKDAY_KEYS`, `WEEKDAY_SHORT_KEYS` (exported from `PresenceStatusBadge.tsx`).

- [ ] **Step 1: Write the API module**

`frontend/src/features/hr/presenceApi.ts`:

```ts
import { apiFetch } from "../../lib/api";

export type PresenceStatus = "present" | "absent" | "late" | "leave" | "holiday" | "rest" | "sick" | "mission" | "suspended";
export type PresenceSource = "manual" | "clock" | "leave" | "holiday";
/** What a supervisor may pick in a grid: leave days come only from an approved leave request. */
export const ENTERABLE_STATUSES: PresenceStatus[] = ["present", "late", "absent", "sick", "mission", "suspended", "holiday", "rest"];
export const WORKED_STATUSES: PresenceStatus[] = ["present", "late", "mission"];

export interface ScheduleDay { weekday: number; start_minute: number; end_minute: number; break_minutes: number }
export interface WorkSchedule { id: string; code: string; name: string; is_night: boolean; active: boolean; days: ScheduleDay[] }
export interface ScheduleInput { code: string; name: string; is_night: boolean; days: ScheduleDay[] }
export interface RotationPattern { id: string; code: string; name: string; anchor_date: string; active: boolean; schedule_ids: string[] }
export interface RotationInput { code: string; name: string; anchor_date: string; schedule_ids: string[] }
export interface ScheduleAssignment {
  id: string; employee_id: string; employee_no: string; full_name: string; schedule_id: string | null; schedule_code: string | null;
  rotation_pattern_id: string | null; rotation_code: string | null; rotation_offset_weeks: number; valid_from: string; valid_to: string | null;
}
export interface AssignmentInput {
  employee_id: string; schedule_id: string | null; rotation_pattern_id: string | null; rotation_offset_weeks: number; valid_from: string; valid_to: string | null;
}
export interface PublicHoliday { id: string; country_code: string; holiday_date: string; name: string; paid: boolean; confirmed: boolean }
export interface HolidayInput { country_code: string; holiday_date: string; name: string; paid: boolean; confirmed: boolean }
export interface PresenceSettingsValues {
  night_start_minute: number | null; night_end_minute: number | null; punch_attach_minutes: number | null;
  punch_dedupe_seconds: number | null; late_grace_minutes: number | null;
}
export interface PresenceSettings extends PresenceSettingsValues { confirmed: boolean; confirmed_at: string | null }

export interface PresenceRecord {
  id: string; status: PresenceStatus; source: PresenceSource; scheduled_minutes: number; worked_minutes: number; late_minutes: number;
  ot_minutes_day: number; ot_minutes_night: number; ot_minutes_rest_holiday: number; night_minutes: number; justified: boolean;
  note: string | null; locked: boolean; leave_request_id: string | null;
}
export interface GridDay {
  work_date: string; employed: boolean; assigned: boolean; schedule_id: string | null; schedule_code: string | null;
  is_working_day: boolean; is_holiday: boolean; planned_minutes: number; default_status: PresenceStatus | null; record: PresenceRecord | null;
}
export interface GridRow { employee_id: string; employee_no: string; full_name: string; department_id: string | null; days: GridDay[] }
export interface EmployeeMonth extends GridRow { period: string; closed: boolean }
export interface PresenceEntry {
  employee_id: string; work_date: string; status: PresenceStatus; worked_minutes: number | null; late_minutes: number;
  ot_minutes_day: number; ot_minutes_night: number; justified: boolean; note: string | null;
}
export interface PresenceMonth { period: string; status: "open" | "closed"; closed_by: string | null; closed_at: string | null; payroll_locked: boolean }
export interface PresenceGap { employee_id: string; employee_no: string; full_name: string; work_date: string; reason: "missing" | "no_schedule" }
export interface MonthSummary {
  employee_id: string; scheduled_days: number; worked_days: number; unpaid_absence_days: number; paid_leave_days: number; sick_days: number;
  holiday_days: number; holidays_worked_days: number; ot_minutes_day: number; ot_minutes_night: number; ot_minutes_rest_holiday: number;
  night_minutes: number; late_minutes: number;
}
export interface MonthCloseResult { period: string; status: string; locked_rows: number; holiday_rows: number; accruals_posted: number }

export interface ClockProfile {
  id: string; code: string; name: string; delimiter: string; has_header: boolean; badge_column: string; timestamp_column: string;
  time_column: string | null; timestamp_format: string; direction_column: string | null; in_values: string[]; out_values: string[]; active: boolean;
}
export type ClockProfileInput = Omit<ClockProfile, "id" | "active">;
export type ClockImportStatus = "staged" | "committed" | "discarded";
export interface ClockDayLabel { employee_id: string; employee_no: string; full_name: string; work_date: string }
export interface ClockConflict extends ClockDayLabel { kept_status: PresenceStatus; kept_source: PresenceSource; clock_status: PresenceStatus; clock_worked_minutes: number }
export interface ClockAnomaly extends ClockDayLabel { codes: string[] }
export interface ClockCommitResult {
  days_written: number; conflicts: ClockConflict[]; anomalies: ClockAnomaly[]; unscheduled: ClockDayLabel[];
  duplicate_punches: number; outside_range_punches: number;
}
export interface ClockImport {
  id: string; profile_id: string; profile_code: string; file_name: string; date_from: string; date_to: string; status: ClockImportStatus;
  total_rows: number; valid_rows: number; error_rows: number; uploaded_by: string; uploaded_by_email: string | null; uploaded_at: string;
  decided_at: string | null; result: ClockCommitResult | null;
}
export interface ClockImportRow {
  line_no: number; raw: string; badge_no: string | null; employee_id: string | null; employee_no: string | null; full_name: string | null;
  punched_at: string | null; direction: "in" | "out" | "unknown"; error_code: string | null;
}
export interface ClockImportDetail extends ClockImport { rows: ClockImportRow[] }
export interface ClockImportInput { profile_id: string; file_name: string; content: string; date_from: string; date_to: string }

export type LeaveRequestStatus = "pending" | "approved" | "rejected" | "cancelled";
export interface LeaveType {
  id: string; code: string; name_en: string; name_fr: string; paid: boolean; accrual_days_per_month: number; max_carry_over: number | null;
  counts_days: "calendar" | "working"; requires_document: boolean; presence_status: "leave" | "sick"; confirmed: boolean; active: boolean;
}
export type LeaveTypeInput = Omit<LeaveType, "id" | "active">;
export interface LeaveRecord {
  id: string; employee_id: string; employee_no: string; full_name: string; leave_type_id: string | null; leave_type_code: string | null;
  leave_type_name_en: string | null; leave_type_name_fr: string | null; legacy_leave_type: string; start_date: string; end_date: string;
  days: number | null; half_day: boolean; reason: string | null; document_ref: string | null; status: LeaveRequestStatus;
  reviewed_by: string | null; reviewed_at: string | null; review_note: string | null;
}
export interface LeaveRecordInput {
  employee_id: string; leave_type_id: string; start_date: string; end_date: string; half_day: boolean; reason: string | null; document_ref: string | null;
}
export interface LeaveBalance {
  employee_id: string; employee_no: string; full_name: string; leave_type_id: string; leave_type_code: string; tracks_balance: boolean;
  year: number; carried_over: number; accrued: number; taken: number; adjusted: number; available: number;
}
export interface LeaveAdjustInput { employee_id: string; leave_type_id: string; year: number; delta: number; reason: string }
export type LeaveDecision = "approve" | "reject" | "cancel";

export const HR_KEYS = {
  employees: ["hr", "employees"] as const,
  departments: ["hr", "departments"] as const,
  schedules: ["hr", "schedules"] as const,
  rotations: ["hr", "rotations"] as const,
  assignments: ["hr", "schedule-assignments"] as const,
  holidays: ["hr", "public-holidays"] as const,
  settings: ["hr", "presence-settings"] as const,
  presence: ["hr", "presence"] as const,
  clockProfiles: ["hr", "clock-profiles"] as const,
  clockImports: ["hr", "clock-imports"] as const,
  leaveTypes: ["hr", "leave-types"] as const,
  leaveRequests: ["hr", "leave-records"] as const,
  leaveBalances: ["hr", "leave-balances"] as const,
};

function query(params: Record<string, string | number | null | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== "") search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

export interface TeamFilter { departmentId?: string; scheduleId?: string }

export const listSchedules = (token: string) => apiFetch<WorkSchedule[]>("/hr/schedules", { token });
export const createSchedule = (token: string, input: ScheduleInput) => apiFetch<WorkSchedule>("/hr/schedules", { method: "POST", token, body: input });
export const updateSchedule = (token: string, id: string, input: Partial<ScheduleInput> & { active?: boolean }) =>
  apiFetch<WorkSchedule>(`/hr/schedules/${id}`, { method: "PATCH", token, body: input });
export const listRotations = (token: string) => apiFetch<RotationPattern[]>("/hr/rotation-patterns", { token });
export const createRotation = (token: string, input: RotationInput) => apiFetch<RotationPattern>("/hr/rotation-patterns", { method: "POST", token, body: input });
export const updateRotation = (token: string, id: string, input: Partial<RotationInput> & { active?: boolean }) =>
  apiFetch<RotationPattern>(`/hr/rotation-patterns/${id}`, { method: "PATCH", token, body: input });
export const listAssignments = (token: string) => apiFetch<ScheduleAssignment[]>("/hr/schedule-assignments", { token });
export const createAssignment = (token: string, input: AssignmentInput) =>
  apiFetch<ScheduleAssignment>("/hr/schedule-assignments", { method: "POST", token, body: input });
export const updateAssignment = (token: string, id: string, input: Omit<AssignmentInput, "employee_id"> & { clear_valid_to: boolean }) =>
  apiFetch<ScheduleAssignment>(`/hr/schedule-assignments/${id}`, { method: "PATCH", token, body: input });
export const listHolidays = (token: string, year: number) => apiFetch<PublicHoliday[]>(`/hr/public-holidays${query({ year })}`, { token });
export const createHoliday = (token: string, input: HolidayInput) => apiFetch<PublicHoliday>("/hr/public-holidays", { method: "POST", token, body: input });
export const updateHoliday = (token: string, id: string, input: Omit<HolidayInput, "country_code">) =>
  apiFetch<PublicHoliday>(`/hr/public-holidays/${id}`, { method: "PATCH", token, body: input });
export const getPresenceSettings = (token: string) => apiFetch<PresenceSettings>("/hr/presence/settings", { token });
export const savePresenceSettings = (token: string, input: PresenceSettingsValues & { confirm: boolean }) =>
  apiFetch<PresenceSettings>("/hr/presence/settings", { method: "PUT", token, body: input });

export const getPresenceGrid = (token: string, workDate: string, team: TeamFilter) =>
  apiFetch<GridRow[]>(`/hr/presence/grid${query({ work_date: workDate, department_id: team.departmentId, schedule_id: team.scheduleId })}`, { token });
export const getPresenceWeek = (token: string, dateFrom: string, team: TeamFilter) =>
  apiFetch<GridRow[]>(`/hr/presence/week${query({ date_from: dateFrom, department_id: team.departmentId, schedule_id: team.scheduleId })}`, { token });
export const savePresenceDays = (token: string, entries: PresenceEntry[]) =>
  apiFetch<{ saved: number }>("/hr/presence/days", { method: "PUT", token, body: { entries } });
export const getEmployeeMonth = (token: string, employeeId: string, period: string) =>
  apiFetch<EmployeeMonth>(`/hr/presence/employee-month${query({ employee_id: employeeId, period })}`, { token });
export const listPresenceMonths = (token: string, year: number) => apiFetch<PresenceMonth[]>(`/hr/presence/months${query({ year })}`, { token });
export const getMonthGaps = (token: string, period: string) => apiFetch<PresenceGap[]>(`/hr/presence/months/${period}/gaps`, { token });
export const getMonthSummary = (token: string, period: string, employeeId?: string) =>
  apiFetch<MonthSummary[]>(`/hr/presence/months/${period}/summary${query({ employee_id: employeeId })}`, { token });
export const closePresenceMonth = (token: string, period: string) =>
  apiFetch<MonthCloseResult>(`/hr/presence/months/${period}/close`, { method: "POST", token });
export const reopenPresenceMonth = (token: string, period: string, reason: string) =>
  apiFetch<{ period: string; status: string }>(`/hr/presence/months/${period}/reopen`, { method: "POST", token, body: { reason } });

export const listClockProfiles = (token: string) => apiFetch<ClockProfile[]>("/hr/clock-profiles", { token });
export const createClockProfile = (token: string, input: ClockProfileInput) =>
  apiFetch<ClockProfile>("/hr/clock-profiles", { method: "POST", token, body: input });
export const updateClockProfile = (token: string, id: string, input: Partial<Omit<ClockProfileInput, "code">> & { active?: boolean }) =>
  apiFetch<ClockProfile>(`/hr/clock-profiles/${id}`, { method: "PATCH", token, body: input });
export const listClockImports = (token: string) => apiFetch<ClockImport[]>("/hr/clock-imports", { token });
export const getClockImport = (token: string, id: string) => apiFetch<ClockImportDetail>(`/hr/clock-imports/${id}`, { token });
export const stageClockImport = (token: string, input: ClockImportInput) =>
  apiFetch<ClockImportDetail>("/hr/clock-imports", { method: "POST", token, body: input });
export const commitClockImport = (token: string, id: string) =>
  apiFetch<ClockCommitResult & { id: string }>(`/hr/clock-imports/${id}/commit`, { method: "POST", token });
export const discardClockImport = (token: string, id: string) =>
  apiFetch<ClockImportDetail>(`/hr/clock-imports/${id}/discard`, { method: "POST", token });

export const listLeaveTypes = (token: string) => apiFetch<LeaveType[]>("/hr/leave-types", { token });
export const createLeaveType = (token: string, input: LeaveTypeInput) => apiFetch<LeaveType>("/hr/leave-types", { method: "POST", token, body: input });
export const updateLeaveType = (token: string, id: string, input: Partial<Omit<LeaveTypeInput, "code">> & { active?: boolean; clear_max_carry_over?: boolean }) =>
  apiFetch<LeaveType>(`/hr/leave-types/${id}`, { method: "PATCH", token, body: input });
export const fetchLeaveRequests = (token: string) => apiFetch<LeaveRecord[]>("/hr/leave/requests", { token });
export const submitLeaveRequest = (token: string, input: LeaveRecordInput) =>
  apiFetch<LeaveRecord>("/hr/leave/requests", { method: "POST", token, body: input });
export const editLeaveRequest = (token: string, id: string, input: Omit<LeaveRecordInput, "employee_id">) =>
  apiFetch<LeaveRecord>(`/hr/leave/requests/${id}`, { method: "PATCH", token, body: input });
export const decideLeaveRequest = (token: string, id: string, decision: LeaveDecision, note: string | null = null) =>
  apiFetch<LeaveRecord>(`/hr/leave/requests/${id}/${decision}`, { method: "POST", token, body: { note } });
export const listLeaveBalances = (token: string, year: number) => apiFetch<LeaveBalance[]>(`/hr/leave/balances${query({ year })}`, { token });
export const adjustLeaveBalance = (token: string, input: LeaveAdjustInput) =>
  apiFetch<LeaveBalance>("/hr/leave/balances/adjust", { method: "POST", token, body: input });
```

- [ ] **Step 2: Write the shared helpers and components**

`frontend/src/features/hr/presenceFormat.ts`:

```ts
import { ApiError } from "../../lib/api";
import { currentLocale } from "../../lib/i18n";
import type { ScheduleDay } from "./presenceApi";

const pad = (value: number) => String(value).padStart(2, "0");

/** 420 -> "07:00". */
export function minutesToClock(minutes: number | null | undefined): string {
  if (minutes === null || minutes === undefined) return "";
  return `${pad(Math.floor(minutes / 60) % 24)}:${pad(minutes % 60)}`;
}

/** "07:00" -> 420; anything else -> null. */
export function clockToMinutes(value: string): number | null {
  const match = /^(\d{1,2}):(\d{2})$/.exec(value.trim());
  if (!match) return null;
  const hours = Number(match[1]);
  const minutes = Number(match[2]);
  return hours < 24 && minutes < 60 ? hours * 60 + minutes : null;
}

/** 485 -> "8 h 05", 480 -> "8 h", 0 -> "0". */
export function formatDuration(minutes: number): string {
  if (!minutes) return "0";
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest ? `${hours} h ${pad(rest)}` : `${hours} h`;
}

export function spanMinutes(day: ScheduleDay): number {
  return (day.end_minute - day.start_minute + 1440) % 1440;
}

function fromIso(iso: string): Date {
  const [year, month, day] = iso.split("-").map(Number);
  return new Date(Date.UTC(year, month - 1, day));
}

export function todayIso(): string {
  const now = new Date();
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

export function addDaysIso(iso: string, days: number): string {
  const date = fromIso(iso);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

/** Monday = 0 ... Sunday = 6, the backend's convention. */
export function weekdayOf(iso: string): number {
  return (fromIso(iso).getUTCDay() + 6) % 7;
}

export function mondayOf(iso: string): string {
  return addDaysIso(iso, -weekdayOf(iso));
}

/** "2026-08-17" -> "2026-08-01". */
export function monthStartOf(iso: string): string {
  return `${iso.slice(0, 7)}-01`;
}

/** "2026-08-03" -> "lun. 03 août" / "Mon, Aug 03", in the app's language. */
export function formatDay(iso: string): string {
  return new Intl.DateTimeFormat(currentLocale(), { weekday: "short", day: "2-digit", month: "short", timeZone: "UTC" }).format(fromIso(iso));
}

/** "2026-08-01" -> "août 2026" / "August 2026". */
export function formatMonth(iso: string): string {
  return new Intl.DateTimeFormat(currentLocale(), { month: "long", year: "numeric", timeZone: "UTC" }).format(fromIso(iso));
}

export function errorText(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback;
}

export function employeeLabel(employee: { employee_no: string; first_name: string; last_name: string }): string {
  return `${employee.employee_no} · ${employee.first_name} ${employee.last_name}`;
}
```

`frontend/src/features/hr/HrListTable.tsx`:

```tsx
import type { ReactNode } from "react";
import { Table, TableBody, TableCell, TableHeader, TableRow, ResizableTableHead } from "../../components/ui/table";
import { Button } from "../../components/ui/button";
import { Skeleton } from "../../components/ui/skeleton";
import { ColumnFilterRow } from "../../components/patterns/ColumnFilterRow";
import { ColumnVisibilityMenu } from "../../components/patterns/ColumnVisibilityMenu";
import { EmptyState } from "../../components/patterns/EmptyState";
import { useI18n } from "../../lib/i18n";
import { useTableColumns, type ColumnDef } from "../../lib/useTableColumns";

interface HrListTableProps<Row> {
  tableKey: string;
  columns: ColumnDef<Row>[];
  rows: Row[];
  rowKey: (row: Row) => string;
  loading: boolean;
  emptyIcon: ReactNode;
  emptyTitle: string;
  emptyDescription: string;
  /** Rendered left of the column menu: FilterTabs, create buttons, pickers. */
  toolbar?: ReactNode;
  filtersActive?: boolean;
  onClearFilters?: () => void;
  rowClassName?: (row: Row) => string | undefined;
}

/**
 * The phase-2 HR list table: columns as data (resize, hide and sort, saved per user through
 * useTableColumns), the per-column filter row under the headers, skeleton rows while loading
 * (the page shows the branded loader once), an empty state.
 */
export function HrListTable<Row>({
  tableKey, columns, rows, rowKey, loading, emptyIcon, emptyTitle, emptyDescription, toolbar, filtersActive, onClearFilters, rowClassName,
}: HrListTableProps<Row>) {
  const { t } = useI18n();
  const table = useTableColumns(tableKey, columns);
  const sorted = table.sortRows(rows);
  const span = table.visibleColumns.length;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        {toolbar}
        {filtersActive && onClearFilters && (
          <Button variant="ghost" size="sm" onClick={onClearFilters}>
            {t("common.clearFilters")}
          </Button>
        )}
        <div className="ml-auto">
          <ColumnVisibilityMenu columns={columns} isVisible={table.isVisible} onToggle={table.toggleVisible} onReset={table.resetAll} />
        </div>
      </div>
      <div className="rounded-lg border border-border">
        <Table colWidths={table.colWidths}>
          <TableHeader>
            <TableRow>
              {table.visibleColumns.map((column) => (
                <ResizableTableHead
                  key={column.key}
                  width={table.getWidth(column.key)}
                  onResize={(width) => table.setWidth(column.key, width)}
                  className={column.headerClassName}
                  sortDirection={table.sortDirectionFor(column.key)}
                  onSort={column.sortValue ? () => table.toggleSort(column.key) : undefined}
                >
                  {column.header}
                </ResizableTableHead>
              ))}
            </TableRow>
            <ColumnFilterRow cells={table.visibleColumns.map((column) => column.filterCell ?? { type: "blank" })} />
          </TableHeader>
          <TableBody>
            {loading &&
              [0, 1, 2].map((index) => (
                <TableRow key={`skeleton-${index}`}>
                  <TableCell colSpan={span}>
                    <Skeleton className="h-5 w-full" />
                  </TableCell>
                </TableRow>
              ))}
            {!loading && sorted.length === 0 && (
              <TableRow>
                <TableCell colSpan={span} className="p-0">
                  <EmptyState icon={emptyIcon} title={emptyTitle} description={emptyDescription} />
                </TableCell>
              </TableRow>
            )}
            {!loading &&
              sorted.map((row) => (
                <TableRow key={rowKey(row)} className={rowClassName?.(row)}>
                  {table.visibleColumns.map((column) => (
                    <TableCell key={column.key} className={column.cellClassName}>
                      {column.cell(row)}
                    </TableCell>
                  ))}
                </TableRow>
              ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
```

`frontend/src/features/hr/HrTabsPage.tsx`:

```tsx
import { useEffect, useState, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { Tabs, TabsList, TabsTrigger } from "../../components/ui/tabs";
import { StickyTabBar } from "../../components/patterns/StickyTabBar";
import { AppLoader } from "../../components/patterns/AppLoader";

export interface HrTab<T extends string> {
  value: T;
  label: string;
  content: ReactNode;
  hidden?: boolean;
}

/** The active tab lives in `?tab=` so each tab can be linked to and reloaded. */
export function useTabParam<T extends string>(values: readonly T[], fallback: T): [T, (value: T) => void] {
  const [params, setParams] = useSearchParams();
  const raw = params.get("tab");
  const current = values.find((value) => value === raw) ?? fallback;
  const select = (value: T) => {
    const next = new URLSearchParams(params);
    next.set("tab", value);
    setParams(next, { replace: true });
  };
  return [current, select];
}

/** True from the first time `ready` is true: the branded loader shows for the first load only. */
export function useBooted(ready: boolean): boolean {
  const [booted, setBooted] = useState(ready);
  useEffect(() => {
    if (ready) setBooted(true);
  }, [ready]);
  return booted;
}

export function HrTabsPage<T extends string>({
  title, subtitle, tabs, active, onChange, layoutId, booted, loaderLabel, actions,
}: {
  title: string;
  subtitle: string;
  tabs: HrTab<T>[];
  active: T;
  onChange: (value: T) => void;
  layoutId: string;
  booted: boolean;
  loaderLabel: string;
  actions?: ReactNode;
}) {
  const visible = tabs.filter((tab) => !tab.hidden);
  const current = visible.find((tab) => tab.value === active) ?? visible[0];
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
          <p className="text-sm text-muted-foreground">{subtitle}</p>
        </div>
        {actions}
      </div>
      <Tabs value={current?.value} onValueChange={(value) => onChange(value as T)}>
        <StickyTabBar>
          <TabsList>
            {visible.map((tab) => (
              <TabsTrigger key={tab.value} value={tab.value} active={current?.value === tab.value} layoutId={layoutId}>
                {tab.label}
              </TabsTrigger>
            ))}
          </TabsList>
        </StickyTabBar>
      </Tabs>
      {!booted && <AppLoader label={loaderLabel} />}
      {/* Kept mounted behind the loader so its reads start at once. */}
      <div hidden={!booted}>{current?.content}</div>
    </div>
  );
}
```

`frontend/src/features/hr/presence/PresenceStatusBadge.tsx`:

```tsx
import { Badge, type BadgeProps } from "../../../components/ui/badge";
import { useI18n, type TranslationKey } from "../../../lib/i18n";
import type { PresenceStatus } from "../presenceApi";

const VARIANT: Record<PresenceStatus, BadgeProps["variant"]> = {
  present: "success", late: "warning", absent: "destructive", leave: "primary", holiday: "accent",
  rest: "default", sick: "warning", mission: "primary", suspended: "destructive",
};

export const PRESENCE_STATUS_LABEL: Record<PresenceStatus, TranslationKey> = {
  present: "hr.presenceStatus.present", absent: "hr.presenceStatus.absent", late: "hr.presenceStatus.late",
  leave: "hr.presenceStatus.leave", holiday: "hr.presenceStatus.holiday", rest: "hr.presenceStatus.rest",
  sick: "hr.presenceStatus.sick", mission: "hr.presenceStatus.mission", suspended: "hr.presenceStatus.suspended",
};

export const WEEKDAY_KEYS: TranslationKey[] = [
  "hr.weekday.0", "hr.weekday.1", "hr.weekday.2", "hr.weekday.3", "hr.weekday.4", "hr.weekday.5", "hr.weekday.6",
];
export const WEEKDAY_SHORT_KEYS: TranslationKey[] = [
  "hr.weekdayShort.0", "hr.weekdayShort.1", "hr.weekdayShort.2", "hr.weekdayShort.3", "hr.weekdayShort.4", "hr.weekdayShort.5", "hr.weekdayShort.6",
];

export function PresenceStatusBadge({ status }: { status: PresenceStatus }) {
  const { t } = useI18n();
  return (
    <Badge variant={VARIANT[status]} dot>
      {t(PRESENCE_STATUS_LABEL[status])}
    </Badge>
  );
}
```

- [ ] **Step 3: Write the schedules tabs**

`frontend/src/features/hr/schedules/WorkSchedulesTab.tsx`:

```tsx
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarClock, Pencil, Plus } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../../lib/auth";
import { useI18n, type TranslationKey } from "../../../lib/i18n";
import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { Checkbox } from "../../../components/ui/checkbox";
import { Badge } from "../../../components/ui/badge";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../../components/ui/dialog";
import { FilterTabs } from "../../../components/patterns/FilterTabs";
import { useColumnFilters, type FilterField } from "../../../lib/useColumnFilters";
import type { ColumnDef } from "../../../lib/useTableColumns";
import { HrListTable } from "../HrListTable";
import { HR_KEYS, createSchedule, listSchedules, updateSchedule, type ScheduleDay, type WorkSchedule } from "../presenceApi";
import { clockToMinutes, errorText, formatDuration, minutesToClock, spanMinutes } from "../presenceFormat";
import { WEEKDAY_KEYS, WEEKDAY_SHORT_KEYS } from "../presence/PresenceStatusBadge";

interface DayDraft { works: boolean; start: string; end: string; breakMinutes: string }
interface ScheduleDraft { code: string; name: string; isNight: boolean; days: DayDraft[] }
type ActiveFilter = "active" | "inactive" | "all";

const blankDay = (): DayDraft => ({ works: false, start: "", end: "", breakMinutes: "" });
const emptyDraft = (): ScheduleDraft => ({ code: "", name: "", isNight: false, days: Array.from({ length: 7 }, blankDay) });

function toDraft(schedule: WorkSchedule): ScheduleDraft {
  return {
    code: schedule.code,
    name: schedule.name,
    isNight: schedule.is_night,
    days: Array.from({ length: 7 }, (_, weekday) => {
      const day = schedule.days.find((item) => item.weekday === weekday);
      return day
        ? { works: true, start: minutesToClock(day.start_minute), end: minutesToClock(day.end_minute), breakMinutes: String(day.break_minutes) }
        : blankDay();
    }),
  };
}

/** The ticked days as backend lines, or null when a ticked day lacks a valid time. */
function toDays(draft: ScheduleDraft): ScheduleDay[] | null {
  const days: ScheduleDay[] = [];
  for (const [weekday, day] of draft.days.entries()) {
    if (!day.works) continue;
    const start = clockToMinutes(day.start);
    const end = clockToMinutes(day.end);
    const breakMinutes = Number(day.breakMinutes || 0);
    if (start === null || end === null || !Number.isInteger(breakMinutes) || breakMinutes < 0) return null;
    days.push({ weekday, start_minute: start, end_minute: end, break_minutes: breakMinutes });
  }
  return days;
}

export function weeklyMinutes(schedule: WorkSchedule): number {
  return schedule.days.reduce((sum, day) => sum + spanMinutes(day) - day.break_minutes, 0);
}

export function weekSummary(schedule: WorkSchedule, t: (key: TranslationKey) => string): string {
  if (schedule.days.length === 0) return "—";
  const first = schedule.days[0];
  const names = schedule.days.map((day) => t(WEEKDAY_SHORT_KEYS[day.weekday])).join(", ");
  const same = schedule.days.every((day) => day.start_minute === first.start_minute && day.end_minute === first.end_minute);
  return same ? `${names} · ${minutesToClock(first.start_minute)}–${minutesToClock(first.end_minute)}` : names;
}

export function WorkSchedulesTab() {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const schedules = useQuery({ queryKey: HR_KEYS.schedules, queryFn: () => listSchedules(token) });
  const [activeFilter, setActiveFilter] = useState<ActiveFilter>("active");
  const [editing, setEditing] = useState<WorkSchedule | null>(null);
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<ScheduleDraft>(emptyDraft);
  const [formError, setFormError] = useState<string | null>(null);
  const canEdit = hasPermission("hr.admin_presence");

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: HR_KEYS.schedules });
    queryClient.invalidateQueries({ queryKey: HR_KEYS.presence });
  };
  const save = useMutation({
    mutationFn: (days: ScheduleDay[]) => {
      const body = { code: draft.code.trim(), name: draft.name.trim(), is_night: draft.isNight, days };
      return editing ? updateSchedule(token, editing.id, body) : createSchedule(token, body);
    },
    onSuccess: () => {
      refresh();
      setOpen(false);
      toast.success(t(editing ? "hr.schedules.updated" : "hr.schedules.created"));
    },
    onError: (error) => setFormError(errorText(error, t("hr.common.saveError"))),
  });
  const toggleActive = useMutation({
    mutationFn: (schedule: WorkSchedule) => updateSchedule(token, schedule.id, { active: !schedule.active }),
    onSuccess: refresh,
    onError: (error) => toast.error(errorText(error, t("hr.common.saveError"))),
  });

  function openDialog(schedule: WorkSchedule | null) {
    setEditing(schedule);
    setDraft(schedule ? toDraft(schedule) : emptyDraft());
    setFormError(null);
    setOpen(true);
  }
  function submit() {
    const days = toDays(draft);
    if (!draft.code.trim() || !draft.name.trim()) {
      setFormError(t("hr.schedules.error.codeName"));
      return;
    }
    if (days === null || days.length === 0) {
      setFormError(t("hr.schedules.error.times"));
      return;
    }
    save.mutate(days);
  }
  const setDay = (weekday: number, patch: Partial<DayDraft>) =>
    setDraft((current) => ({ ...current, days: current.days.map((day, index) => (index === weekday ? { ...day, ...patch } : day)) }));

  const fields: FilterField<WorkSchedule>[] = [
    { key: "code", kind: "text", getValue: (s) => s.code },
    { key: "name", kind: "text", getValue: (s) => s.name },
    { key: "weekly", kind: "range", getValue: (s) => weeklyMinutes(s) / 60 },
  ];
  const filters = useColumnFilters(fields);
  const rows = filters.apply((schedules.data ?? []).filter((s) => activeFilter === "all" || (activeFilter === "active") === s.active));

  const columns: ColumnDef<WorkSchedule>[] = [
    {
      key: "code", header: t("hr.schedules.code"), defaultWidth: 110, sortValue: (s) => s.code,
      cell: (s) => <span className="font-medium">{s.code}</span>,
      filterCell: { type: "text", placeholder: t("hr.schedules.code"), value: filters.text.code ?? "", onChange: (v) => filters.setTextValue("code", v) },
    },
    {
      key: "name", header: t("hr.schedules.name"), defaultWidth: 200, sortValue: (s) => s.name, cell: (s) => s.name,
      filterCell: { type: "text", placeholder: t("hr.schedules.name"), value: filters.text.name ?? "", onChange: (v) => filters.setTextValue("name", v) },
    },
    { key: "days", header: t("hr.schedules.days"), defaultWidth: 280, cell: (s) => weekSummary(s, t) },
    {
      key: "weekly", header: t("hr.schedules.weeklyHours"), defaultWidth: 130, cellClassName: "tabular-nums",
      sortValue: (s) => weeklyMinutes(s), cell: (s) => formatDuration(weeklyMinutes(s)),
      filterCell: {
        type: "range", min: filters.range.weekly?.min ?? "", max: filters.range.weekly?.max ?? "",
        onMinChange: (v) => filters.setRangeValue("weekly", "min", v), onMaxChange: (v) => filters.setRangeValue("weekly", "max", v),
      },
    },
    { key: "night", header: t("hr.schedules.night"), defaultWidth: 90, cell: (s) => (s.is_night ? <Badge variant="accent">{t("hr.schedules.night")}</Badge> : null) },
    { key: "active", header: t("hr.common.active"), defaultWidth: 90, cell: (s) => (s.active ? t("common.yes") : t("common.no")) },
    {
      key: "actions", header: "", defaultWidth: 200, alwaysVisible: true,
      cell: (s) =>
        canEdit ? (
          <div className="flex justify-end gap-2">
            <Button size="sm" variant="outline" onClick={() => openDialog(s)}>
              <Pencil className="h-3.5 w-3.5" />
              {t("common.edit")}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => toggleActive.mutate(s)}>
              {s.active ? t("hr.common.deactivate") : t("hr.common.activate")}
            </Button>
          </div>
        ) : null,
    },
  ];

  return (
    <>
      <HrListTable
        tableKey="hr.schedules"
        columns={columns}
        rows={rows}
        rowKey={(s) => s.id}
        loading={schedules.isLoading}
        emptyIcon={<CalendarClock className="h-5 w-5" />}
        emptyTitle={t("hr.schedules.empty.title")}
        emptyDescription={t("hr.schedules.empty.description")}
        filtersActive={filters.isActive}
        onClearFilters={filters.reset}
        toolbar={
          <>
            <FilterTabs
              value={activeFilter}
              onChange={setActiveFilter}
              options={[
                { value: "active", label: t("hr.common.activeOnly") },
                { value: "inactive", label: t("hr.common.inactiveOnly") },
                { value: "all", label: t("common.all") },
              ]}
            />
            {hasPermission("hr.manage_presence") && (
              <Button size="sm" onClick={() => openDialog(null)}>
                <Plus className="h-4 w-4" />
                {t("hr.schedules.new")}
              </Button>
            )}
          </>
        }
      />
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>{t(editing ? "hr.schedules.editTitle" : "hr.schedules.new")}</DialogTitle>
            <DialogDescription>{t("hr.schedules.dialogHelp")}</DialogDescription>
          </DialogHeader>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="schedule-code">{t("hr.schedules.code")}</Label>
              <Input id="schedule-code" value={draft.code} onChange={(e) => setDraft({ ...draft, code: e.target.value })} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="schedule-name">{t("hr.schedules.name")}</Label>
              <Input id="schedule-name" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
            </div>
          </div>
          <label className="flex items-center gap-2 text-sm">
            <Checkbox checked={draft.isNight} onCheckedChange={(value) => setDraft({ ...draft, isNight: value === true })} />
            {t("hr.schedules.isNight")}
          </label>
          <div className="space-y-2">
            <div className="grid grid-cols-[130px_1fr_1fr_1fr] gap-2 text-xs text-muted-foreground">
              <span />
              <span>{t("hr.schedules.start")}</span>
              <span>{t("hr.schedules.end")}</span>
              <span>{t("hr.schedules.breakMinutes")}</span>
            </div>
            {draft.days.map((day, weekday) => (
              <div key={weekday} className="grid grid-cols-[130px_1fr_1fr_1fr] items-center gap-2">
                <label className="flex items-center gap-2 text-sm">
                  <Checkbox checked={day.works} onCheckedChange={(value) => setDay(weekday, { works: value === true })} />
                  {t(WEEKDAY_KEYS[weekday])}
                </label>
                <Input type="time" aria-label={t("hr.schedules.start")} disabled={!day.works} value={day.start} onChange={(e) => setDay(weekday, { start: e.target.value })} />
                <Input type="time" aria-label={t("hr.schedules.end")} disabled={!day.works} value={day.end} onChange={(e) => setDay(weekday, { end: e.target.value })} />
                <Input type="number" min={0} aria-label={t("hr.schedules.breakMinutes")} disabled={!day.works} value={day.breakMinutes} onChange={(e) => setDay(weekday, { breakMinutes: e.target.value })} />
              </div>
            ))}
          </div>
          {formError && <p className="text-sm text-destructive">{formError}</p>}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setOpen(false)}>{t("common.cancel")}</Button>
            <Button onClick={submit} disabled={save.isPending}>{save.isPending ? t("common.saving") : t("common.save")}</Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
```

`frontend/src/features/hr/schedules/RotationsTab.tsx`:

```tsx
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil, Plus, Repeat, X } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { Select } from "../../../components/ui/select";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../../components/ui/dialog";
import { FilterTabs } from "../../../components/patterns/FilterTabs";
import { useColumnFilters, type FilterField } from "../../../lib/useColumnFilters";
import type { ColumnDef } from "../../../lib/useTableColumns";
import { HrListTable } from "../HrListTable";
import { HR_KEYS, createRotation, listRotations, listSchedules, updateRotation, type RotationPattern } from "../presenceApi";
import { errorText, formatDay, mondayOf, todayIso, weekdayOf } from "../presenceFormat";

interface RotationDraft { code: string; name: string; anchorDate: string; scheduleIds: string[] }
const emptyDraft = (): RotationDraft => ({ code: "", name: "", anchorDate: mondayOf(todayIso()), scheduleIds: [""] });

export function RotationsTab() {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const rotations = useQuery({ queryKey: HR_KEYS.rotations, queryFn: () => listRotations(token) });
  const schedules = useQuery({ queryKey: HR_KEYS.schedules, queryFn: () => listSchedules(token) });
  const [activeFilter, setActiveFilter] = useState<"active" | "inactive" | "all">("active");
  const [editing, setEditing] = useState<RotationPattern | null>(null);
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<RotationDraft>(emptyDraft);
  const [formError, setFormError] = useState<string | null>(null);
  const canEdit = hasPermission("hr.admin_presence");
  const scheduleCode = (id: string) => schedules.data?.find((s) => s.id === id)?.code ?? "?";

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: HR_KEYS.rotations });
    queryClient.invalidateQueries({ queryKey: HR_KEYS.presence });
  };
  const save = useMutation({
    mutationFn: () => {
      const body = { code: draft.code.trim(), name: draft.name.trim(), anchor_date: draft.anchorDate, schedule_ids: draft.scheduleIds };
      return editing ? updateRotation(token, editing.id, body) : createRotation(token, body);
    },
    onSuccess: () => {
      refresh();
      setOpen(false);
      toast.success(t(editing ? "hr.rotations.updated" : "hr.rotations.created"));
    },
    onError: (error) => setFormError(errorText(error, t("hr.common.saveError"))),
  });
  const toggleActive = useMutation({
    mutationFn: (rotation: RotationPattern) => updateRotation(token, rotation.id, { active: !rotation.active }),
    onSuccess: refresh,
    onError: (error) => toast.error(errorText(error, t("hr.common.saveError"))),
  });

  function openDialog(rotation: RotationPattern | null) {
    setEditing(rotation);
    setDraft(rotation ? { code: rotation.code, name: rotation.name, anchorDate: rotation.anchor_date, scheduleIds: [...rotation.schedule_ids] } : emptyDraft());
    setFormError(null);
    setOpen(true);
  }
  function submit() {
    if (!draft.code.trim() || !draft.name.trim()) {
      setFormError(t("hr.schedules.error.codeName"));
      return;
    }
    if (!draft.anchorDate || weekdayOf(draft.anchorDate) !== 0) {
      setFormError(t("hr.rotations.error.monday"));
      return;
    }
    if (draft.scheduleIds.length === 0 || draft.scheduleIds.some((id) => !id)) {
      setFormError(t("hr.rotations.error.steps"));
      return;
    }
    save.mutate();
  }
  const setStep = (index: number, scheduleId: string) =>
    setDraft((current) => ({ ...current, scheduleIds: current.scheduleIds.map((id, i) => (i === index ? scheduleId : id)) }));

  const fields: FilterField<RotationPattern>[] = [
    { key: "code", kind: "text", getValue: (r) => r.code },
    { key: "name", kind: "text", getValue: (r) => r.name },
    { key: "steps", kind: "text", getValue: (r) => r.schedule_ids.map(scheduleCode).join(" ") },
  ];
  const filters = useColumnFilters(fields);
  const rows = filters.apply((rotations.data ?? []).filter((r) => activeFilter === "all" || (activeFilter === "active") === r.active));

  const columns: ColumnDef<RotationPattern>[] = [
    {
      key: "code", header: t("hr.schedules.code"), defaultWidth: 110, sortValue: (r) => r.code,
      cell: (r) => <span className="font-medium">{r.code}</span>,
      filterCell: { type: "text", placeholder: t("hr.schedules.code"), value: filters.text.code ?? "", onChange: (v) => filters.setTextValue("code", v) },
    },
    {
      key: "name", header: t("hr.schedules.name"), defaultWidth: 220, sortValue: (r) => r.name, cell: (r) => r.name,
      filterCell: { type: "text", placeholder: t("hr.schedules.name"), value: filters.text.name ?? "", onChange: (v) => filters.setTextValue("name", v) },
    },
    { key: "anchor", header: t("hr.rotations.anchor"), defaultWidth: 150, sortValue: (r) => r.anchor_date, cell: (r) => formatDay(r.anchor_date) },
    {
      key: "steps", header: t("hr.rotations.steps"), defaultWidth: 240, cell: (r) => r.schedule_ids.map(scheduleCode).join(" → "),
      filterCell: { type: "text", placeholder: t("hr.rotations.steps"), value: filters.text.steps ?? "", onChange: (v) => filters.setTextValue("steps", v) },
    },
    { key: "active", header: t("hr.common.active"), defaultWidth: 90, cell: (r) => (r.active ? t("common.yes") : t("common.no")) },
    {
      key: "actions", header: "", defaultWidth: 200, alwaysVisible: true,
      cell: (r) =>
        canEdit ? (
          <div className="flex justify-end gap-2">
            <Button size="sm" variant="outline" onClick={() => openDialog(r)}>
              <Pencil className="h-3.5 w-3.5" />
              {t("common.edit")}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => toggleActive.mutate(r)}>
              {r.active ? t("hr.common.deactivate") : t("hr.common.activate")}
            </Button>
          </div>
        ) : null,
    },
  ];

  const activeSchedules = (schedules.data ?? []).filter((s) => s.active || draft.scheduleIds.includes(s.id));
  return (
    <>
      <HrListTable
        tableKey="hr.rotations"
        columns={columns}
        rows={rows}
        rowKey={(r) => r.id}
        loading={rotations.isLoading}
        emptyIcon={<Repeat className="h-5 w-5" />}
        emptyTitle={t("hr.rotations.empty.title")}
        emptyDescription={t("hr.rotations.empty.description")}
        filtersActive={filters.isActive}
        onClearFilters={filters.reset}
        toolbar={
          <>
            <FilterTabs
              value={activeFilter}
              onChange={setActiveFilter}
              options={[
                { value: "active", label: t("hr.common.activeOnly") },
                { value: "inactive", label: t("hr.common.inactiveOnly") },
                { value: "all", label: t("common.all") },
              ]}
            />
            {hasPermission("hr.manage_presence") && (
              <Button size="sm" onClick={() => openDialog(null)}>
                <Plus className="h-4 w-4" />
                {t("hr.rotations.new")}
              </Button>
            )}
          </>
        }
      />
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t(editing ? "hr.rotations.editTitle" : "hr.rotations.new")}</DialogTitle>
            <DialogDescription>{t("hr.rotations.dialogHelp")}</DialogDescription>
          </DialogHeader>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="rotation-code">{t("hr.schedules.code")}</Label>
              <Input id="rotation-code" value={draft.code} onChange={(e) => setDraft({ ...draft, code: e.target.value })} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="rotation-name">{t("hr.schedules.name")}</Label>
              <Input id="rotation-name" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
            </div>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="rotation-anchor">{t("hr.rotations.anchor")}</Label>
            <Input id="rotation-anchor" type="date" value={draft.anchorDate} onChange={(e) => setDraft({ ...draft, anchorDate: e.target.value })} />
          </div>
          <div className="space-y-2">
            {draft.scheduleIds.map((scheduleId, index) => (
              <div key={index} className="flex items-center gap-2">
                <span className="w-24 text-sm text-muted-foreground">{t("hr.rotations.week")} {index + 1}</span>
                <Select value={scheduleId} onChange={(e) => setStep(index, e.target.value)} aria-label={`${t("hr.rotations.week")} ${index + 1}`}>
                  <option value="">{t("hr.rotations.pickSchedule")}</option>
                  {activeSchedules.map((s) => (
                    <option key={s.id} value={s.id}>{s.code} · {s.name}</option>
                  ))}
                </Select>
                <Button
                  size="sm"
                  variant="ghost"
                  aria-label={t("hr.rotations.remove")}
                  disabled={draft.scheduleIds.length === 1}
                  onClick={() => setDraft({ ...draft, scheduleIds: draft.scheduleIds.filter((_, i) => i !== index) })}
                >
                  <X className="h-4 w-4" />
                </Button>
              </div>
            ))}
            <Button size="sm" variant="outline" onClick={() => setDraft({ ...draft, scheduleIds: [...draft.scheduleIds, ""] })}>
              <Plus className="h-4 w-4" />
              {t("hr.rotations.addWeek")}
            </Button>
          </div>
          {formError && <p className="text-sm text-destructive">{formError}</p>}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setOpen(false)}>{t("common.cancel")}</Button>
            <Button onClick={submit} disabled={save.isPending}>{save.isPending ? t("common.saving") : t("common.save")}</Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
```

`frontend/src/features/hr/schedules/AssignmentsTab.tsx`:

```tsx
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil, Plus, UserCog } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { Select } from "../../../components/ui/select";
import { Badge } from "../../../components/ui/badge";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../../components/ui/dialog";
import { FilterTabs } from "../../../components/patterns/FilterTabs";
import { useColumnFilters, type FilterField } from "../../../lib/useColumnFilters";
import type { ColumnDef } from "../../../lib/useTableColumns";
import { listEmployees } from "../api";
import { HrListTable } from "../HrListTable";
import {
  HR_KEYS, createAssignment, listAssignments, listRotations, listSchedules, updateAssignment, type ScheduleAssignment,
} from "../presenceApi";
import { employeeLabel, errorText, formatDay, todayIso } from "../presenceFormat";

type Kind = "schedule" | "rotation";
interface AssignmentDraft { employeeId: string; kind: Kind; scheduleId: string; rotationId: string; offset: string; validFrom: string; validTo: string }
const emptyDraft = (): AssignmentDraft => ({ employeeId: "", kind: "schedule", scheduleId: "", rotationId: "", offset: "0", validFrom: todayIso(), validTo: "" });

export function AssignmentsTab() {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const assignments = useQuery({ queryKey: HR_KEYS.assignments, queryFn: () => listAssignments(token) });
  const employees = useQuery({ queryKey: HR_KEYS.employees, queryFn: () => listEmployees(token) });
  const schedules = useQuery({ queryKey: HR_KEYS.schedules, queryFn: () => listSchedules(token) });
  const rotations = useQuery({ queryKey: HR_KEYS.rotations, queryFn: () => listRotations(token) });
  const [kindFilter, setKindFilter] = useState<"all" | Kind>("all");
  const [editing, setEditing] = useState<ScheduleAssignment | null>(null);
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<AssignmentDraft>(emptyDraft);
  const [formError, setFormError] = useState<string | null>(null);
  const canEdit = hasPermission("hr.admin_presence");

  const save = useMutation({
    mutationFn: () => {
      const plan = {
        schedule_id: draft.kind === "schedule" ? draft.scheduleId : null,
        rotation_pattern_id: draft.kind === "rotation" ? draft.rotationId : null,
        rotation_offset_weeks: draft.kind === "rotation" ? Number(draft.offset || 0) : 0,
        valid_from: draft.validFrom,
        valid_to: draft.validTo || null,
      };
      return editing
        ? updateAssignment(token, editing.id, { ...plan, clear_valid_to: !draft.validTo })
        : createAssignment(token, { ...plan, employee_id: draft.employeeId });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: HR_KEYS.assignments });
      queryClient.invalidateQueries({ queryKey: HR_KEYS.presence });
      setOpen(false);
      toast.success(t(editing ? "hr.assignments.updated" : "hr.assignments.created"));
    },
    onError: (error) => setFormError(errorText(error, t("hr.common.saveError"))),
  });

  function openDialog(assignment: ScheduleAssignment | null) {
    setEditing(assignment);
    setDraft(
      assignment
        ? {
            employeeId: assignment.employee_id,
            kind: assignment.rotation_pattern_id ? "rotation" : "schedule",
            scheduleId: assignment.schedule_id ?? "",
            rotationId: assignment.rotation_pattern_id ?? "",
            offset: String(assignment.rotation_offset_weeks),
            validFrom: assignment.valid_from,
            validTo: assignment.valid_to ?? "",
          }
        : emptyDraft(),
    );
    setFormError(null);
    setOpen(true);
  }
  function submit() {
    const target = draft.kind === "schedule" ? draft.scheduleId : draft.rotationId;
    const offset = Number(draft.offset || 0);
    if (!draft.employeeId || !target || !draft.validFrom || !Number.isInteger(offset) || offset < 0) {
      setFormError(t("hr.assignments.error.required"));
      return;
    }
    save.mutate();
  }

  const planOf = (a: ScheduleAssignment) => a.schedule_code ?? a.rotation_code ?? "?";
  const fields: FilterField<ScheduleAssignment>[] = [
    { key: "employee", kind: "text", getValue: (a) => `${a.employee_no} ${a.full_name}` },
    { key: "plan", kind: "text", getValue: planOf },
    { key: "offset", kind: "range", getValue: (a) => a.rotation_offset_weeks },
  ];
  const filters = useColumnFilters(fields);
  const rows = filters.apply(
    (assignments.data ?? []).filter((a) => kindFilter === "all" || (kindFilter === "rotation") === (a.rotation_pattern_id !== null)),
  );

  const columns: ColumnDef<ScheduleAssignment>[] = [
    {
      key: "employee", header: t("hr.common.employee"), defaultWidth: 240, sortValue: (a) => a.employee_no,
      cell: (a) => <span className="font-medium">{a.employee_no} · {a.full_name}</span>,
      filterCell: { type: "text", placeholder: t("hr.common.employee"), value: filters.text.employee ?? "", onChange: (v) => filters.setTextValue("employee", v) },
    },
    {
      key: "plan", header: t("hr.assignments.plan"), defaultWidth: 200, sortValue: planOf,
      cell: (a) => (
        <span className="inline-flex items-center gap-2">
          {planOf(a)}
          <Badge variant={a.rotation_pattern_id ? "accent" : "default"}>
            {t(a.rotation_pattern_id ? "hr.assignments.kind.rotation" : "hr.assignments.kind.schedule")}
          </Badge>
        </span>
      ),
      filterCell: { type: "text", placeholder: t("hr.assignments.plan"), value: filters.text.plan ?? "", onChange: (v) => filters.setTextValue("plan", v) },
    },
    {
      key: "offset", header: t("hr.assignments.offset"), defaultWidth: 150, cellClassName: "tabular-nums", sortValue: (a) => a.rotation_offset_weeks,
      cell: (a) => (a.rotation_pattern_id ? a.rotation_offset_weeks : "—"),
      filterCell: {
        type: "range", min: filters.range.offset?.min ?? "", max: filters.range.offset?.max ?? "",
        onMinChange: (v) => filters.setRangeValue("offset", "min", v), onMaxChange: (v) => filters.setRangeValue("offset", "max", v),
      },
    },
    { key: "from", header: t("hr.common.from"), defaultWidth: 140, sortValue: (a) => a.valid_from, cell: (a) => formatDay(a.valid_from) },
    { key: "to", header: t("hr.common.to"), defaultWidth: 140, sortValue: (a) => a.valid_to ?? "9999", cell: (a) => (a.valid_to ? formatDay(a.valid_to) : t("hr.assignments.openEnded")) },
    {
      key: "actions", header: "", defaultWidth: 120, alwaysVisible: true,
      cell: (a) =>
        canEdit ? (
          <Button size="sm" variant="outline" onClick={() => openDialog(a)}>
            <Pencil className="h-3.5 w-3.5" />
            {t("common.edit")}
          </Button>
        ) : null,
    },
  ];

  return (
    <>
      <HrListTable
        tableKey="hr.scheduleAssignments"
        columns={columns}
        rows={rows}
        rowKey={(a) => a.id}
        loading={assignments.isLoading}
        emptyIcon={<UserCog className="h-5 w-5" />}
        emptyTitle={t("hr.assignments.empty.title")}
        emptyDescription={t("hr.assignments.empty.description")}
        filtersActive={filters.isActive}
        onClearFilters={filters.reset}
        toolbar={
          <>
            <FilterTabs
              value={kindFilter}
              onChange={setKindFilter}
              options={[
                { value: "all", label: t("common.all") },
                { value: "schedule", label: t("hr.assignments.kind.schedule") },
                { value: "rotation", label: t("hr.assignments.kind.rotation") },
              ]}
            />
            {hasPermission("hr.manage_presence") && (
              <Button size="sm" onClick={() => openDialog(null)}>
                <Plus className="h-4 w-4" />
                {t("hr.assignments.new")}
              </Button>
            )}
          </>
        }
      />
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t(editing ? "hr.assignments.editTitle" : "hr.assignments.new")}</DialogTitle>
            <DialogDescription>{t("hr.assignments.dialogHelp")}</DialogDescription>
          </DialogHeader>
          <div className="space-y-1.5">
            <Label htmlFor="assignment-employee">{t("hr.common.employee")}</Label>
            <Select id="assignment-employee" value={draft.employeeId} disabled={editing !== null} onChange={(e) => setDraft({ ...draft, employeeId: e.target.value })}>
              <option value="">—</option>
              {(employees.data ?? []).map((employee) => (
                <option key={employee.id} value={employee.id}>{employeeLabel(employee)}</option>
              ))}
            </Select>
          </div>
          <FilterTabs
            value={draft.kind}
            onChange={(kind) => setDraft({ ...draft, kind })}
            options={[
              { value: "schedule", label: t("hr.assignments.kind.schedule") },
              { value: "rotation", label: t("hr.assignments.kind.rotation") },
            ]}
          />
          {draft.kind === "schedule" ? (
            <Select value={draft.scheduleId} aria-label={t("hr.assignments.kind.schedule")} onChange={(e) => setDraft({ ...draft, scheduleId: e.target.value })}>
              <option value="">{t("hr.rotations.pickSchedule")}</option>
              {(schedules.data ?? []).filter((s) => s.active || s.id === draft.scheduleId).map((s) => (
                <option key={s.id} value={s.id}>{s.code} · {s.name}</option>
              ))}
            </Select>
          ) : (
            <div className="grid grid-cols-2 gap-3">
              <Select value={draft.rotationId} aria-label={t("hr.assignments.kind.rotation")} onChange={(e) => setDraft({ ...draft, rotationId: e.target.value })}>
                <option value="">—</option>
                {(rotations.data ?? []).filter((r) => r.active || r.id === draft.rotationId).map((r) => (
                  <option key={r.id} value={r.id}>{r.code} · {r.name}</option>
                ))}
              </Select>
              <div className="space-y-1.5">
                <Label htmlFor="assignment-offset">{t("hr.assignments.offset")}</Label>
                <Input id="assignment-offset" type="number" min={0} value={draft.offset} onChange={(e) => setDraft({ ...draft, offset: e.target.value })} />
              </div>
            </div>
          )}
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="assignment-from">{t("hr.common.from")}</Label>
              <Input id="assignment-from" type="date" value={draft.validFrom} onChange={(e) => setDraft({ ...draft, validFrom: e.target.value })} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="assignment-to">{t("hr.common.to")}</Label>
              <Input id="assignment-to" type="date" value={draft.validTo} onChange={(e) => setDraft({ ...draft, validTo: e.target.value })} />
            </div>
          </div>
          {formError && <p className="text-sm text-destructive">{formError}</p>}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setOpen(false)}>{t("common.cancel")}</Button>
            <Button onClick={submit} disabled={save.isPending}>{save.isPending ? t("common.saving") : t("common.save")}</Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
```

`frontend/src/features/hr/schedules/HolidaysTab.tsx`:

```tsx
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarHeart, Pencil, Plus } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { Checkbox } from "../../../components/ui/checkbox";
import { Badge } from "../../../components/ui/badge";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../../components/ui/dialog";
import { FilterTabs } from "../../../components/patterns/FilterTabs";
import { useColumnFilters, type FilterField } from "../../../lib/useColumnFilters";
import type { ColumnDef } from "../../../lib/useTableColumns";
import { HrListTable } from "../HrListTable";
import { HR_KEYS, createHoliday, listHolidays, updateHoliday, type PublicHoliday } from "../presenceApi";
import { errorText, formatDay, todayIso } from "../presenceFormat";

interface HolidayDraft { countryCode: string; date: string; name: string; paid: boolean; confirmed: boolean }
type CheckFilter = "all" | "toConfirm" | "confirmed";

export function HolidaysTab() {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [year, setYear] = useState(Number(todayIso().slice(0, 4)));
  const holidays = useQuery({ queryKey: [...HR_KEYS.holidays, year], queryFn: () => listHolidays(token, year) });
  const [checkFilter, setCheckFilter] = useState<CheckFilter>("all");
  const [editing, setEditing] = useState<PublicHoliday | null>(null);
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<HolidayDraft>({ countryCode: "", date: "", name: "", paid: true, confirmed: false });
  const [formError, setFormError] = useState<string | null>(null);
  const canEdit = hasPermission("hr.admin_presence");

  const save = useMutation({
    mutationFn: () => {
      const body = { holiday_date: draft.date, name: draft.name.trim(), paid: draft.paid, confirmed: draft.confirmed };
      return editing ? updateHoliday(token, editing.id, body) : createHoliday(token, { ...body, country_code: draft.countryCode.trim().toUpperCase() });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: HR_KEYS.holidays });
      queryClient.invalidateQueries({ queryKey: HR_KEYS.presence });
      setOpen(false);
      toast.success(t(editing ? "hr.holidays.updated" : "hr.holidays.created"));
    },
    onError: (error) => setFormError(errorText(error, t("hr.common.saveError"))),
  });

  function openDialog(holiday: PublicHoliday | null) {
    setEditing(holiday);
    // A new holiday takes the country of the ones already listed; nothing is assumed when there are none.
    const knownCountry = holidays.data?.[0]?.country_code ?? "";
    setDraft(
      holiday
        ? { countryCode: holiday.country_code, date: holiday.holiday_date, name: holiday.name, paid: holiday.paid, confirmed: holiday.confirmed }
        : { countryCode: knownCountry, date: "", name: "", paid: true, confirmed: false },
    );
    setFormError(null);
    setOpen(true);
  }
  function submit() {
    if (!/^[A-Za-z]{2}$/.test(draft.countryCode.trim()) || !draft.date || !draft.name.trim()) {
      setFormError(t("hr.holidays.error.required"));
      return;
    }
    save.mutate();
  }

  const fields: FilterField<PublicHoliday>[] = [
    { key: "name", kind: "text", getValue: (h) => h.name },
    { key: "country", kind: "text", getValue: (h) => h.country_code },
  ];
  const filters = useColumnFilters(fields);
  const rows = filters.apply(
    (holidays.data ?? []).filter((h) => checkFilter === "all" || (checkFilter === "confirmed") === h.confirmed),
  );
  const columns: ColumnDef<PublicHoliday>[] = [
    { key: "date", header: t("hr.holidays.date"), defaultWidth: 150, sortValue: (h) => h.holiday_date, cell: (h) => formatDay(h.holiday_date) },
    {
      key: "name", header: t("hr.holidays.name"), defaultWidth: 300, sortValue: (h) => h.name, cell: (h) => h.name,
      filterCell: { type: "text", placeholder: t("hr.holidays.name"), value: filters.text.name ?? "", onChange: (v) => filters.setTextValue("name", v) },
    },
    {
      key: "country", header: t("hr.holidays.country"), defaultWidth: 90, cell: (h) => h.country_code,
      filterCell: { type: "text", placeholder: t("hr.holidays.country"), value: filters.text.country ?? "", onChange: (v) => filters.setTextValue("country", v) },
    },
    { key: "paid", header: t("hr.holidays.paid"), defaultWidth: 90, cell: (h) => (h.paid ? t("common.yes") : t("common.no")) },
    {
      key: "check", header: t("hr.holidays.status"), defaultWidth: 130,
      cell: (h) => <Badge variant={h.confirmed ? "success" : "warning"}>{t(h.confirmed ? "hr.common.confirmed" : "hr.common.toConfirm")}</Badge>,
    },
    {
      key: "actions", header: "", defaultWidth: 120, alwaysVisible: true,
      cell: (h) =>
        canEdit ? (
          <Button size="sm" variant="outline" onClick={() => openDialog(h)}>
            <Pencil className="h-3.5 w-3.5" />
            {t("common.edit")}
          </Button>
        ) : null,
    },
  ];

  return (
    <>
      <HrListTable
        tableKey="hr.publicHolidays"
        columns={columns}
        rows={rows}
        rowKey={(h) => h.id}
        loading={holidays.isLoading}
        emptyIcon={<CalendarHeart className="h-5 w-5" />}
        emptyTitle={t("hr.holidays.empty.title")}
        emptyDescription={t("hr.holidays.empty.description")}
        filtersActive={filters.isActive}
        onClearFilters={filters.reset}
        toolbar={
          <>
            <Input type="number" className="w-24" aria-label={t("hr.common.year")} value={year} onChange={(e) => setYear(Number(e.target.value) || year)} />
            <FilterTabs
              value={checkFilter}
              onChange={setCheckFilter}
              options={[
                { value: "all", label: t("common.all") },
                { value: "toConfirm", label: t("hr.common.toConfirm") },
                { value: "confirmed", label: t("hr.common.confirmed") },
              ]}
            />
            {hasPermission("hr.manage_presence") && (
              <Button size="sm" onClick={() => openDialog(null)}>
                <Plus className="h-4 w-4" />
                {t("hr.holidays.new")}
              </Button>
            )}
          </>
        }
      />
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t(editing ? "hr.holidays.editTitle" : "hr.holidays.new")}</DialogTitle>
            <DialogDescription>{t("hr.holidays.dialogHelp")}</DialogDescription>
          </DialogHeader>
          <div className="grid grid-cols-[100px_1fr] gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="holiday-country">{t("hr.holidays.country")}</Label>
              <Input id="holiday-country" maxLength={2} disabled={editing !== null} value={draft.countryCode} onChange={(e) => setDraft({ ...draft, countryCode: e.target.value })} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="holiday-date">{t("hr.holidays.date")}</Label>
              <Input id="holiday-date" type="date" value={draft.date} onChange={(e) => setDraft({ ...draft, date: e.target.value })} />
            </div>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="holiday-name">{t("hr.holidays.name")}</Label>
            <Input id="holiday-name" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
          </div>
          <label className="flex items-center gap-2 text-sm">
            <Checkbox checked={draft.paid} onCheckedChange={(value) => setDraft({ ...draft, paid: value === true })} />
            {t("hr.holidays.paid")}
          </label>
          <label className="flex items-center gap-2 text-sm">
            <Checkbox checked={draft.confirmed} onCheckedChange={(value) => setDraft({ ...draft, confirmed: value === true })} />
            {t("hr.common.confirmed")}
          </label>
          {formError && <p className="text-sm text-destructive">{formError}</p>}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setOpen(false)}>{t("common.cancel")}</Button>
            <Button onClick={submit} disabled={save.isPending}>{save.isPending ? t("common.saving") : t("common.save")}</Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
```

`frontend/src/features/hr/schedules/PresenceSettingsCard.tsx`:

```tsx
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { Checkbox } from "../../../components/ui/checkbox";
import { Badge } from "../../../components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "../../../components/ui/card";
import { Skeleton } from "../../../components/ui/skeleton";
import { HR_KEYS, getPresenceSettings, savePresenceSettings, type PresenceSettings, type PresenceSettingsValues } from "../presenceApi";
import { clockToMinutes, errorText, formatDay, minutesToClock } from "../presenceFormat";

interface SettingsDraft { nightStart: string; nightEnd: string; attach: string; dedupe: string; grace: string; confirm: boolean }

function toDraft(settings: PresenceSettings): SettingsDraft {
  const text = (value: number | null) => (value === null ? "" : String(value));
  return {
    nightStart: minutesToClock(settings.night_start_minute), nightEnd: minutesToClock(settings.night_end_minute),
    attach: text(settings.punch_attach_minutes), dedupe: text(settings.punch_dedupe_seconds), grace: text(settings.late_grace_minutes),
    confirm: false,
  };
}

/** "" -> null; a whole number >= 0 -> that number; anything else -> undefined (invalid). */
function wholeOrEmpty(value: string): number | null | undefined {
  if (value.trim() === "") return null;
  const number = Number(value);
  return Number.isInteger(number) && number >= 0 ? number : undefined;
}

export function PresenceSettingsCard() {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const settings = useQuery({ queryKey: HR_KEYS.settings, queryFn: () => getPresenceSettings(token) });
  const [draft, setDraft] = useState<SettingsDraft | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const canEdit = hasPermission("hr.admin_presence");

  useEffect(() => {
    if (settings.data) setDraft(toDraft(settings.data));
  }, [settings.data]);

  const save = useMutation({
    mutationFn: (values: PresenceSettingsValues & { confirm: boolean }) => savePresenceSettings(token, values),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: HR_KEYS.settings });
      toast.success(t("hr.settings.saved"));
    },
    onError: (error) => setFormError(errorText(error, t("hr.common.saveError"))),
  });

  function submit() {
    if (!draft) return;
    const nightStart = draft.nightStart ? clockToMinutes(draft.nightStart) : null;
    const nightEnd = draft.nightEnd ? clockToMinutes(draft.nightEnd) : null;
    const attach = wholeOrEmpty(draft.attach);
    const dedupe = wholeOrEmpty(draft.dedupe);
    const grace = wholeOrEmpty(draft.grace);
    if (attach === undefined || dedupe === undefined || grace === undefined || (draft.nightStart && nightStart === null) || (draft.nightEnd && nightEnd === null)) {
      setFormError(t("hr.settings.error.number"));
      return;
    }
    setFormError(null);
    save.mutate({
      night_start_minute: nightStart, night_end_minute: nightEnd, punch_attach_minutes: attach,
      punch_dedupe_seconds: dedupe, late_grace_minutes: grace, confirm: draft.confirm,
    });
  }

  if (!draft || !settings.data) return <Skeleton className="h-64 w-full" />;
  const field = (id: string, label: string, input: JSX.Element) => (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      {input}
    </div>
  );
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("hr.settings.title")}</CardTitle>
        <p className="text-sm text-muted-foreground">{t("hr.settings.help")}</p>
        {settings.data.confirmed && settings.data.confirmed_at ? (
          <Badge variant="success">{t("hr.settings.confirmedOn")} {formatDay(settings.data.confirmed_at.slice(0, 10))}</Badge>
        ) : (
          <Badge variant="warning">{t("hr.settings.notConfirmed")}</Badge>
        )}
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-2">
          {field("night-start", t("hr.settings.nightStart"), <Input id="night-start" type="time" disabled={!canEdit} value={draft.nightStart} onChange={(e) => setDraft({ ...draft, nightStart: e.target.value })} />)}
          {field("night-end", t("hr.settings.nightEnd"), <Input id="night-end" type="time" disabled={!canEdit} value={draft.nightEnd} onChange={(e) => setDraft({ ...draft, nightEnd: e.target.value })} />)}
          {field("punch-attach", t("hr.settings.attach"), <Input id="punch-attach" type="number" min={0} disabled={!canEdit} value={draft.attach} onChange={(e) => setDraft({ ...draft, attach: e.target.value })} />)}
          {field("punch-dedupe", t("hr.settings.dedupe"), <Input id="punch-dedupe" type="number" min={0} disabled={!canEdit} value={draft.dedupe} onChange={(e) => setDraft({ ...draft, dedupe: e.target.value })} />)}
          {field("late-grace", t("hr.settings.grace"), <Input id="late-grace" type="number" min={0} disabled={!canEdit} value={draft.grace} onChange={(e) => setDraft({ ...draft, grace: e.target.value })} />)}
        </div>
        {canEdit && (
          <>
            <label className="flex items-center gap-2 text-sm">
              <Checkbox checked={draft.confirm} onCheckedChange={(value) => setDraft({ ...draft, confirm: value === true })} />
              {t("hr.settings.confirm")}
            </label>
            {formError && <p className="text-sm text-destructive">{formError}</p>}
            <Button onClick={submit} disabled={save.isPending}>{save.isPending ? t("common.saving") : t("common.save")}</Button>
          </>
        )}
      </CardContent>
    </Card>
  );
}
```

(`JSX.Element` is available globally with `jsx: react-jsx` and `@types/react`; if tsc reports it missing, import `type ReactElement` from `react` and use that.)

`frontend/src/features/hr/schedules/SchedulesPage.tsx`:

```tsx
import { useQuery } from "@tanstack/react-query";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { HrTabsPage, useBooted, useTabParam } from "../HrTabsPage";
import { HR_KEYS, listSchedules } from "../presenceApi";
import { AssignmentsTab } from "./AssignmentsTab";
import { HolidaysTab } from "./HolidaysTab";
import { PresenceSettingsCard } from "./PresenceSettingsCard";
import { RotationsTab } from "./RotationsTab";
import { WorkSchedulesTab } from "./WorkSchedulesTab";

const TABS = ["schedules", "rotations", "assignments", "holidays", "settings"] as const;

export function SchedulesPage() {
  const { session } = useAuth();
  const { t } = useI18n();
  const [tab, setTab] = useTabParam(TABS, "schedules");
  const schedules = useQuery({ queryKey: HR_KEYS.schedules, queryFn: () => listSchedules(session!.token) });
  const booted = useBooted(!schedules.isLoading);
  return (
    <HrTabsPage
      title={t("hr.schedules.title")}
      subtitle={t("hr.schedules.subtitle")}
      layoutId="hr-schedules-tab"
      active={tab}
      onChange={setTab}
      booted={booted}
      loaderLabel={t("hr.schedules.loading")}
      tabs={[
        { value: "schedules", label: t("hr.schedules.tab.schedules"), content: <WorkSchedulesTab /> },
        { value: "rotations", label: t("hr.schedules.tab.rotations"), content: <RotationsTab /> },
        { value: "assignments", label: t("hr.schedules.tab.assignments"), content: <AssignmentsTab /> },
        { value: "holidays", label: t("hr.schedules.tab.holidays"), content: <HolidaysTab /> },
        { value: "settings", label: t("hr.schedules.tab.settings"), content: <PresenceSettingsCard /> },
      ]}
    />
  );
}
```

- [ ] **Step 4: Route, sidebar entry and strings**

`frontend/src/routes/router.tsx`: add `import { SchedulesPage } from "../features/hr/schedules/SchedulesPage";` and, in `protectedChildren` after the `/hr` entries, `{ path: "/hr/schedules", element: <SchedulesPage /> },`.

`frontend/src/routes/Sidebar.tsx`: in the `NAV_GROUPS` entry whose `labelKey` is `"nav.hr"`, append to its `items` array (after whatever phase 1 put there):

```ts
      { to: "/hr/schedules", labelKey: "nav.hrSchedules", icon: CalendarClock, permission: "hr.view_presence" },
```

(`CalendarClock` is already imported.)

`frontend/src/lib/i18n.tsx` — append to `en` (before `} as const;`):

```ts
  "nav.hrSchedules": "Schedules & holidays",
  "hr.common.active": "Active",
  "hr.common.activeOnly": "Active",
  "hr.common.inactiveOnly": "Inactive",
  "hr.common.activate": "Activate",
  "hr.common.deactivate": "Deactivate",
  "hr.common.saveError": "Could not save",
  "hr.common.employee": "Employee",
  "hr.common.toConfirm": "To confirm",
  "hr.common.confirmed": "Confirmed",
  "hr.common.from": "From",
  "hr.common.to": "To",
  "hr.common.year": "Year",
  "hr.weekday.0": "Monday",
  "hr.weekday.1": "Tuesday",
  "hr.weekday.2": "Wednesday",
  "hr.weekday.3": "Thursday",
  "hr.weekday.4": "Friday",
  "hr.weekday.5": "Saturday",
  "hr.weekday.6": "Sunday",
  "hr.weekdayShort.0": "Mon",
  "hr.weekdayShort.1": "Tue",
  "hr.weekdayShort.2": "Wed",
  "hr.weekdayShort.3": "Thu",
  "hr.weekdayShort.4": "Fri",
  "hr.weekdayShort.5": "Sat",
  "hr.weekdayShort.6": "Sun",
  "hr.presenceStatus.present": "Present",
  "hr.presenceStatus.absent": "Absent",
  "hr.presenceStatus.late": "Late",
  "hr.presenceStatus.leave": "Leave",
  "hr.presenceStatus.holiday": "Public holiday",
  "hr.presenceStatus.rest": "Rest day",
  "hr.presenceStatus.sick": "Sick",
  "hr.presenceStatus.mission": "On mission",
  "hr.presenceStatus.suspended": "Suspended",
  "hr.schedules.title": "Schedules & holidays",
  "hr.schedules.subtitle": "Working hours, weekly rotations, who works which schedule, public holidays and the presence settings.",
  "hr.schedules.loading": "Loading schedules…",
  "hr.schedules.tab.schedules": "Schedules",
  "hr.schedules.tab.rotations": "Rotations",
  "hr.schedules.tab.assignments": "Assignments",
  "hr.schedules.tab.holidays": "Public holidays",
  "hr.schedules.tab.settings": "Settings",
  "hr.schedules.code": "Code",
  "hr.schedules.name": "Name",
  "hr.schedules.days": "Working days",
  "hr.schedules.weeklyHours": "Hours / week",
  "hr.schedules.night": "Night",
  "hr.schedules.new": "New schedule",
  "hr.schedules.editTitle": "Edit schedule",
  "hr.schedules.dialogHelp": "Tick the days worked. An end earlier than the start means the shift ends the next morning; it still belongs to the day it starts.",
  "hr.schedules.isNight": "Night schedule",
  "hr.schedules.start": "Start",
  "hr.schedules.end": "End",
  "hr.schedules.breakMinutes": "Break (min)",
  "hr.schedules.error.codeName": "Code and name are required.",
  "hr.schedules.error.times": "Tick at least one day; each ticked day needs a start, an end and a whole number of break minutes.",
  "hr.schedules.created": "Schedule created",
  "hr.schedules.updated": "Schedule updated",
  "hr.schedules.empty.title": "No schedule yet",
  "hr.schedules.empty.description": "Create the plant's shifts (for example 07-15, 15-23, 23-07) before recording presence.",
  "hr.rotations.anchor": "Week 1 starts on",
  "hr.rotations.steps": "Weekly sequence",
  "hr.rotations.new": "New rotation",
  "hr.rotations.editTitle": "Edit rotation",
  "hr.rotations.dialogHelp": "Each line is one week. Week 1 starts on the Monday chosen; the sequence then repeats.",
  "hr.rotations.week": "Week",
  "hr.rotations.addWeek": "Add a week",
  "hr.rotations.remove": "Remove",
  "hr.rotations.pickSchedule": "Choose a schedule",
  "hr.rotations.error.monday": "Week 1 must start on a Monday.",
  "hr.rotations.error.steps": "Every week needs a schedule.",
  "hr.rotations.created": "Rotation created",
  "hr.rotations.updated": "Rotation updated",
  "hr.rotations.empty.title": "No rotation yet",
  "hr.rotations.empty.description": "A rotation moves a team through the shifts week after week (morning → evening → night).",
  "hr.assignments.plan": "Schedule or rotation",
  "hr.assignments.offset": "Team offset (weeks)",
  "hr.assignments.kind.schedule": "Fixed schedule",
  "hr.assignments.kind.rotation": "Rotation",
  "hr.assignments.new": "Assign a schedule",
  "hr.assignments.editTitle": "Edit assignment",
  "hr.assignments.dialogHelp": "From this date the employee works this schedule. Leave the end empty while it lasts.",
  "hr.assignments.openEnded": "ongoing",
  "hr.assignments.error.required": "Choose an employee, a schedule or rotation, a start date and a whole, non-negative offset.",
  "hr.assignments.created": "Schedule assigned",
  "hr.assignments.updated": "Assignment updated",
  "hr.assignments.empty.title": "Nobody is assigned",
  "hr.assignments.empty.description": "Presence needs to know who works which schedule.",
  "hr.holidays.date": "Date",
  "hr.holidays.name": "Holiday",
  "hr.holidays.country": "Country",
  "hr.holidays.paid": "Paid",
  "hr.holidays.status": "Check",
  "hr.holidays.new": "New holiday",
  "hr.holidays.editTitle": "Edit holiday",
  "hr.holidays.dialogHelp": "Religious holidays follow the moon: confirm each year's date once it is announced.",
  "hr.holidays.error.required": "A two-letter country, a date and a name are required.",
  "hr.holidays.created": "Holiday created",
  "hr.holidays.updated": "Holiday updated",
  "hr.holidays.empty.title": "No public holiday this year",
  "hr.holidays.empty.description": "On a public holiday, people scheduled that day are not expected at work.",
  "hr.settings.title": "Presence settings",
  "hr.settings.help": "These values come from the labour code and from how the plant uses its clock. They start empty; the clock import and the grid refuse to compute until the night window is set.",
  "hr.settings.nightStart": "Night work starts",
  "hr.settings.nightEnd": "Night work ends",
  "hr.settings.attach": "A punch belongs to a shift up to (min) before its start or after its end",
  "hr.settings.dedupe": "Same-direction punches closer than (s) count once",
  "hr.settings.grace": "Lateness counted beyond (min)",
  "hr.settings.confirm": "I have checked these values",
  "hr.settings.confirmedOn": "Confirmed on",
  "hr.settings.notConfirmed": "Draft: not confirmed yet",
  "hr.settings.saved": "Settings saved",
  "hr.settings.error.number": "Enter times as HH:MM and whole numbers, or leave empty.",
```

and to `fr` (before its closing `};`):

```ts
  "nav.hrSchedules": "Horaires et jours fériés",
  "hr.common.active": "Actif",
  "hr.common.activeOnly": "Actifs",
  "hr.common.inactiveOnly": "Inactifs",
  "hr.common.activate": "Activer",
  "hr.common.deactivate": "Désactiver",
  "hr.common.saveError": "Enregistrement impossible",
  "hr.common.employee": "Employé",
  "hr.common.toConfirm": "À confirmer",
  "hr.common.confirmed": "Confirmé",
  "hr.common.from": "Du",
  "hr.common.to": "Au",
  "hr.common.year": "Année",
  "hr.weekday.0": "Lundi",
  "hr.weekday.1": "Mardi",
  "hr.weekday.2": "Mercredi",
  "hr.weekday.3": "Jeudi",
  "hr.weekday.4": "Vendredi",
  "hr.weekday.5": "Samedi",
  "hr.weekday.6": "Dimanche",
  "hr.weekdayShort.0": "Lun",
  "hr.weekdayShort.1": "Mar",
  "hr.weekdayShort.2": "Mer",
  "hr.weekdayShort.3": "Jeu",
  "hr.weekdayShort.4": "Ven",
  "hr.weekdayShort.5": "Sam",
  "hr.weekdayShort.6": "Dim",
  "hr.presenceStatus.present": "Présent",
  "hr.presenceStatus.absent": "Absent",
  "hr.presenceStatus.late": "Retard",
  "hr.presenceStatus.leave": "Congé",
  "hr.presenceStatus.holiday": "Férié",
  "hr.presenceStatus.rest": "Repos",
  "hr.presenceStatus.sick": "Maladie",
  "hr.presenceStatus.mission": "Mission",
  "hr.presenceStatus.suspended": "Mise à pied",
  "hr.schedules.title": "Horaires et jours fériés",
  "hr.schedules.subtitle": "Horaires de travail, roulements hebdomadaires, affectations, jours fériés et paramètres de présence.",
  "hr.schedules.loading": "Chargement des horaires…",
  "hr.schedules.tab.schedules": "Horaires",
  "hr.schedules.tab.rotations": "Roulements",
  "hr.schedules.tab.assignments": "Affectations",
  "hr.schedules.tab.holidays": "Jours fériés",
  "hr.schedules.tab.settings": "Paramètres",
  "hr.schedules.code": "Code",
  "hr.schedules.name": "Nom",
  "hr.schedules.days": "Jours travaillés",
  "hr.schedules.weeklyHours": "Heures / semaine",
  "hr.schedules.night": "Nuit",
  "hr.schedules.new": "Nouvel horaire",
  "hr.schedules.editTitle": "Modifier l'horaire",
  "hr.schedules.dialogHelp": "Cochez les jours travaillés. Une fin plus tôt que le début signifie que le poste finit le lendemain matin ; il appartient au jour où il commence.",
  "hr.schedules.isNight": "Horaire de nuit",
  "hr.schedules.start": "Début",
  "hr.schedules.end": "Fin",
  "hr.schedules.breakMinutes": "Pause (min)",
  "hr.schedules.error.codeName": "Le code et le nom sont obligatoires.",
  "hr.schedules.error.times": "Cochez au moins un jour ; chaque jour coché demande un début, une fin et un nombre entier de minutes de pause.",
  "hr.schedules.created": "Horaire créé",
  "hr.schedules.updated": "Horaire modifié",
  "hr.schedules.empty.title": "Aucun horaire",
  "hr.schedules.empty.description": "Créez les postes de l'usine (par exemple 07-15, 15-23, 23-07) avant de saisir la présence.",
  "hr.rotations.anchor": "La semaine 1 commence le",
  "hr.rotations.steps": "Séquence hebdomadaire",
  "hr.rotations.new": "Nouveau roulement",
  "hr.rotations.editTitle": "Modifier le roulement",
  "hr.rotations.dialogHelp": "Chaque ligne est une semaine. La semaine 1 commence le lundi choisi ; la séquence se répète ensuite.",
  "hr.rotations.week": "Semaine",
  "hr.rotations.addWeek": "Ajouter une semaine",
  "hr.rotations.remove": "Retirer",
  "hr.rotations.pickSchedule": "Choisir un horaire",
  "hr.rotations.error.monday": "La semaine 1 doit commencer un lundi.",
  "hr.rotations.error.steps": "Chaque semaine doit avoir un horaire.",
  "hr.rotations.created": "Roulement créé",
  "hr.rotations.updated": "Roulement modifié",
  "hr.rotations.empty.title": "Aucun roulement",
  "hr.rotations.empty.description": "Un roulement fait passer une équipe d'un poste à l'autre chaque semaine (matin → soir → nuit).",
  "hr.assignments.plan": "Horaire ou roulement",
  "hr.assignments.offset": "Décalage d'équipe (semaines)",
  "hr.assignments.kind.schedule": "Horaire fixe",
  "hr.assignments.kind.rotation": "Roulement",
  "hr.assignments.new": "Affecter un horaire",
  "hr.assignments.editTitle": "Modifier l'affectation",
  "hr.assignments.dialogHelp": "À partir de cette date l'employé suit cet horaire. Laissez la fin vide tant qu'il dure.",
  "hr.assignments.openEnded": "en cours",
  "hr.assignments.error.required": "Choisissez un employé, un horaire ou un roulement, une date de début et un décalage entier positif ou nul.",
  "hr.assignments.created": "Horaire affecté",
  "hr.assignments.updated": "Affectation modifiée",
  "hr.assignments.empty.title": "Aucune affectation",
  "hr.assignments.empty.description": "La présence doit savoir qui suit quel horaire.",
  "hr.holidays.date": "Date",
  "hr.holidays.name": "Jour férié",
  "hr.holidays.country": "Pays",
  "hr.holidays.paid": "Payé",
  "hr.holidays.status": "Vérification",
  "hr.holidays.new": "Nouveau jour férié",
  "hr.holidays.editTitle": "Modifier le jour férié",
  "hr.holidays.dialogHelp": "Les fêtes religieuses suivent la lune : confirmez la date de chaque année dès qu'elle est annoncée.",
  "hr.holidays.error.required": "Un pays à deux lettres, une date et un nom sont obligatoires.",
  "hr.holidays.created": "Jour férié créé",
  "hr.holidays.updated": "Jour férié modifié",
  "hr.holidays.empty.title": "Aucun jour férié cette année",
  "hr.holidays.empty.description": "Un jour férié, les personnes prévues ce jour-là ne sont pas attendues au travail.",
  "hr.settings.title": "Paramètres de présence",
  "hr.settings.help": "Ces valeurs viennent du code du travail et de l'usage de la pointeuse à l'usine. Elles sont vides au départ ; l'import de pointage et la grille refusent de calculer tant que la plage de nuit n'est pas renseignée.",
  "hr.settings.nightStart": "Début du travail de nuit",
  "hr.settings.nightEnd": "Fin du travail de nuit",
  "hr.settings.attach": "Un pointage appartient au poste jusqu'à (min) avant son début ou après sa fin",
  "hr.settings.dedupe": "Deux pointages de même sens à moins de (s) comptent pour un",
  "hr.settings.grace": "Retard compté au-delà de (min)",
  "hr.settings.confirm": "J'ai vérifié ces valeurs",
  "hr.settings.confirmedOn": "Confirmé le",
  "hr.settings.notConfirmed": "Brouillon : pas encore confirmé",
  "hr.settings.saved": "Paramètres enregistrés",
  "hr.settings.error.number": "Saisissez les heures au format HH:MM et des nombres entiers, ou laissez vide.",
```

- [ ] **Step 5: Type-check**

Run (from `frontend/`): `npx tsc -b --force`
Expected: exit 0, no error. (A missing `fr` key fails here by design.)

- [ ] **Step 6: Browser check**

Start backend and Vite if they are down (memory `feedback_verify_frontend_in_repo.md`), log in as `demo@sonalim-erp.local` over the API, grant the demo user `hr.view_presence`, `hr.manage_presence`, `hr.admin_presence` if the administrator role does not already carry them (`POST /core/users/{id}/permissions`), then in a private headless Chrome open `/hr/schedules`. Check: one branded loader, then the five tabs; create a schedule "JOUR" Mon–Sat 07:00–15:00; edit it; create a rotation anchored on a Monday; a Tuesday anchor shows the Monday error; assign an employee; add a holiday; settings show "Draft: not confirmed yet" and save; switch the language to French and back.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/features/hr/presenceApi.ts frontend/src/features/hr/presenceFormat.ts frontend/src/features/hr/HrListTable.tsx frontend/src/features/hr/HrTabsPage.tsx frontend/src/features/hr/presence/PresenceStatusBadge.tsx frontend/src/features/hr/schedules frontend/src/routes/router.tsx frontend/src/routes/Sidebar.tsx frontend/src/lib/i18n.tsx
git commit -m "feat(hr): schedules & holidays screen with rotations, assignments and presence settings

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: `/hr/presence` — day grid, week grid, employee month, month close

**Files:**
- Create: `frontend/src/features/hr/presence/PresencePage.tsx`, `TeamPicker.tsx`, `useClosedMonths.ts`, `DayGridTab.tsx`, `WeekGridTab.tsx`, `EmployeeMonthTab.tsx`, `MonthCloseTab.tsx`
- Modify: `frontend/src/routes/router.tsx`, `frontend/src/routes/Sidebar.tsx`, `frontend/src/lib/i18n.tsx`

**Interfaces:**
- Consumes (Task 10): `HR_KEYS`, `getPresenceGrid`, `getPresenceWeek`, `savePresenceDays`, `getEmployeeMonth`, `listPresenceMonths`, `getMonthGaps`, `getMonthSummary`, `closePresenceMonth`, `reopenPresenceMonth`, `listSchedules`, types `GridRow`, `GridDay`, `PresenceEntry`, `PresenceStatus`, `ENTERABLE_STATUSES`, `WORKED_STATUSES`, `TeamFilter`, `MonthSummary`, `PresenceGap`, `PresenceMonth`; `HrListTable`, `HrTabsPage`, `useTabParam`, `useBooted`; `PresenceStatusBadge`, `PRESENCE_STATUS_LABEL`, `WEEKDAY_SHORT_KEYS`; `presenceFormat` helpers; `listEmployees`, `listDepartments` from `../api`.
- Produces: `PresencePage` (route `/hr/presence`, tabs `day | week | calendar | month`); `TeamPicker`, `teamFilterOf(team)`, `type Team`; `useClosedMonths(years: number[]) -> Set<string>` (closed periods, ISO).

Saving rules the grids follow (they mirror Task 3's service): a row or cell is sent only when it has no record yet (the default is being confirmed) or the user changed it; a day from an approved leave, a day outside employment, a day without schedule and any day of a closed month are read-only; lateness only for `late`; worked minutes and overtime only for worked statuses; day/night overtime is disabled on rest days and public holidays (the server counts every worked minute there as rest/holiday overtime).

- [ ] **Step 1: Shared pieces**

`frontend/src/features/hr/presence/TeamPicker.tsx`:

```tsx
import { useI18n } from "../../../lib/i18n";
import { Select } from "../../../components/ui/select";
import type { Department } from "../api";
import type { TeamFilter, WorkSchedule } from "../presenceApi";

export interface Team {
  kind: "department" | "schedule";
  id: string; // "" = everyone
}

export function teamFilterOf(team: Team): TeamFilter {
  if (!team.id) return {};
  return team.kind === "department" ? { departmentId: team.id } : { scheduleId: team.id };
}

/** A supervisor's team: one department, or everyone on one schedule that day. */
export function TeamPicker({ team, onChange, departments, schedules }: {
  team: Team;
  onChange: (team: Team) => void;
  departments: Department[];
  schedules: WorkSchedule[];
}) {
  const { t } = useI18n();
  const options = team.kind === "department"
    ? departments.map((d) => ({ id: d.id, label: `${d.code} · ${d.name}` }))
    : schedules.filter((s) => s.active).map((s) => ({ id: s.id, label: `${s.code} · ${s.name}` }));
  return (
    <div className="flex items-center gap-2">
      <Select aria-label={t("hr.presence.team")} value={team.kind} onChange={(e) => onChange({ kind: e.target.value as Team["kind"], id: "" })}>
        <option value="department">{t("hr.presence.teamKind.department")}</option>
        <option value="schedule">{t("hr.presence.teamKind.schedule")}</option>
      </Select>
      <Select aria-label={t("hr.presence.team")} value={team.id} onChange={(e) => onChange({ ...team, id: e.target.value })}>
        <option value="">{t("hr.presence.allTeams")}</option>
        {options.map((option) => (
          <option key={option.id} value={option.id}>{option.label}</option>
        ))}
      </Select>
    </div>
  );
}
```

`frontend/src/features/hr/presence/useClosedMonths.ts`:

```ts
import { useQueries } from "@tanstack/react-query";
import { useAuth } from "../../../lib/auth";
import { HR_KEYS, listPresenceMonths } from "../presenceApi";

/** The closed periods ("YYYY-MM-01") of the given years. */
export function useClosedMonths(years: number[]): Set<string> {
  const { session } = useAuth();
  const token = session!.token;
  const unique = [...new Set(years)];
  const results = useQueries({
    queries: unique.map((year) => ({
      queryKey: [...HR_KEYS.presence, "months", year],
      queryFn: () => listPresenceMonths(token, year),
    })),
  });
  return new Set(results.flatMap((result) => (result.data ?? []).filter((m) => m.status === "closed").map((m) => m.period)));
}
```

- [ ] **Step 2: The day grid**

`frontend/src/features/hr/presence/DayGridTab.tsx`:

```tsx
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Save, Users } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../../lib/auth";
import { useI18n, type TranslationKey } from "../../../lib/i18n";
import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import { Select } from "../../../components/ui/select";
import { Checkbox } from "../../../components/ui/checkbox";
import { Badge } from "../../../components/ui/badge";
import { FilterTabs } from "../../../components/patterns/FilterTabs";
import { useColumnFilters, type FilterField } from "../../../lib/useColumnFilters";
import type { ColumnDef } from "../../../lib/useTableColumns";
import type { Department } from "../api";
import { HrListTable } from "../HrListTable";
import {
  ENTERABLE_STATUSES, HR_KEYS, WORKED_STATUSES, getPresenceGrid, savePresenceDays,
  type GridDay, type GridRow, type PresenceEntry, type PresenceSource, type PresenceStatus, type WorkSchedule,
} from "../presenceApi";
import { errorText, formatDuration, monthStartOf, todayIso } from "../presenceFormat";
import { PRESENCE_STATUS_LABEL, PresenceStatusBadge } from "./PresenceStatusBadge";
import { TeamPicker, teamFilterOf, type Team } from "./TeamPicker";
import { useClosedMonths } from "./useClosedMonths";

interface RowDraft { status: PresenceStatus | ""; late: string; worked: string; otDay: string; otNight: string; justified: boolean; note: string; dirty: boolean }
type View = "all" | "unsaved" | "exceptions";

export const SOURCE_LABEL: Record<PresenceSource, TranslationKey> = {
  manual: "hr.presence.source.manual", clock: "hr.presence.source.clock", leave: "hr.presence.source.leave", holiday: "hr.presence.source.holiday",
};

const count = (value: number) => (value ? String(value) : "");

function draftFrom(day: GridDay): RowDraft {
  const record = day.record;
  if (!record) return { status: day.default_status ?? "", late: "", worked: "", otDay: "", otNight: "", justified: false, note: "", dirty: false };
  const derived = Math.max(0, day.planned_minutes - record.late_minutes);
  return {
    status: record.status, late: count(record.late_minutes),
    worked: record.worked_minutes === derived ? "" : String(record.worked_minutes), // "" = derived from the schedule
    otDay: count(record.ot_minutes_day), otNight: count(record.ot_minutes_night),
    justified: record.justified, note: record.note ?? "", dirty: false,
  };
}

export function isEditable(day: GridDay, closed: boolean): boolean {
  return !closed && day.employed && day.assigned && day.record?.source !== "leave";
}

function toEntry(employeeId: string, day: GridDay, draft: RowDraft): PresenceEntry {
  const status = draft.status as PresenceStatus;
  const worked = WORKED_STATUSES.includes(status);
  const offDay = !day.is_working_day || day.is_holiday;
  return {
    employee_id: employeeId,
    work_date: day.work_date,
    status,
    worked_minutes: worked && draft.worked !== "" ? Number(draft.worked) : null,
    late_minutes: status === "late" ? Number(draft.late || 0) : 0,
    ot_minutes_day: worked && !offDay ? Number(draft.otDay || 0) : 0,
    ot_minutes_night: worked && !offDay ? Number(draft.otNight || 0) : 0,
    justified: status === "absent" && draft.justified,
    note: draft.note.trim() || null,
  };
}

export function DayGridTab({ departments, schedules }: { departments: Department[]; schedules: WorkSchedule[] }) {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [workDate, setWorkDate] = useState(todayIso());
  const [team, setTeam] = useState<Team>({ kind: "department", id: "" });
  const [view, setView] = useState<View>("all");
  const [drafts, setDrafts] = useState<Record<string, RowDraft>>({});
  const grid = useQuery({
    queryKey: [...HR_KEYS.presence, "grid", workDate, team.kind, team.id],
    queryFn: () => getPresenceGrid(token, workDate, teamFilterOf(team)),
  });
  const closed = useClosedMonths([Number(workDate.slice(0, 4))]).has(monthStartOf(workDate));
  const canSave = hasPermission("hr.manage_presence");

  useEffect(() => {
    if (grid.data) setDrafts(Object.fromEntries(grid.data.map((row) => [row.employee_id, draftFrom(row.days[0])])));
  }, [grid.data]);

  const update = (employeeId: string, patch: Partial<RowDraft>) =>
    setDrafts((current) => ({ ...current, [employeeId]: { ...current[employeeId], ...patch, dirty: true } }));

  const entries = (grid.data ?? []).flatMap((row) => {
    const day = row.days[0];
    const draft = drafts[row.employee_id];
    if (!draft || !draft.status || !isEditable(day, closed) || (day.record && !draft.dirty)) return [];
    return [toEntry(row.employee_id, day, draft)];
  });
  const save = useMutation({
    mutationFn: () => savePresenceDays(token, entries),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: HR_KEYS.presence });
      toast.success(`${t("hr.presence.saved")} (${result.saved})`);
    },
    onError: (error) => toast.error(errorText(error, t("hr.common.saveError"))),
  });

  const fields: FilterField<GridRow>[] = [
    { key: "employee", kind: "text", getValue: (row) => `${row.employee_no} ${row.full_name}` },
    { key: "schedule", kind: "text", getValue: (row) => row.days[0].schedule_code },
  ];
  const filters = useColumnFilters(fields);
  const rows = filters.apply(
    (grid.data ?? []).filter((row) => {
      const draft = drafts[row.employee_id];
      if (view === "unsaved") return row.days[0].record === null;
      if (view === "exceptions") return draft !== undefined && draft.status !== "" && draft.status !== "present" && draft.status !== "rest";
      return true;
    }),
  );

  const numberInput = (row: GridRow, key: "late" | "worked" | "otDay" | "otNight", enabled: boolean, placeholder = "") => (
    <Input
      type="number"
      min={0}
      className="h-8"
      placeholder={placeholder}
      disabled={!enabled}
      value={drafts[row.employee_id]?.[key] ?? ""}
      onChange={(e) => update(row.employee_id, { [key]: e.target.value } as Partial<RowDraft>)}
    />
  );
  const stateOf = (row: GridRow) => {
    const day = row.days[0];
    const draft = drafts[row.employee_id];
    const editable = isEditable(day, closed) && canSave;
    const worked = draft !== undefined && WORKED_STATUSES.includes(draft.status as PresenceStatus);
    const offDay = !day.is_working_day || day.is_holiday;
    return { day, draft, editable, worked, offDay };
  };

  const columns: ColumnDef<GridRow>[] = [
    {
      key: "employee", header: t("hr.common.employee"), defaultWidth: 220, sortValue: (row) => row.employee_no,
      cell: (row) => <span className="font-medium">{row.employee_no} · {row.full_name}</span>,
      filterCell: { type: "text", placeholder: t("hr.common.employee"), value: filters.text.employee ?? "", onChange: (v) => filters.setTextValue("employee", v) },
    },
    {
      key: "schedule", header: t("hr.presence.schedule"), defaultWidth: 160, sortValue: (row) => row.days[0].schedule_code ?? "",
      cell: (row) => {
        const day = row.days[0];
        if (!day.employed) return <span className="text-muted-foreground">{t("hr.presence.notEmployed")}</span>;
        if (!day.assigned) return <Badge variant="warning">{t("hr.presence.noSchedule")}</Badge>;
        return (
          <span className="inline-flex items-center gap-2">
            {day.schedule_code}
            <span className="text-xs text-muted-foreground">{day.is_working_day ? formatDuration(day.planned_minutes) : t("hr.presenceStatus.rest")}</span>
            {day.is_holiday && <Badge variant="accent">{t("hr.presenceStatus.holiday")}</Badge>}
          </span>
        );
      },
      filterCell: { type: "text", placeholder: t("hr.presence.schedule"), value: filters.text.schedule ?? "", onChange: (v) => filters.setTextValue("schedule", v) },
    },
    {
      key: "status", header: t("hr.presence.status"), defaultWidth: 150, alwaysVisible: true,
      cell: (row) => {
        const { day, draft, editable } = stateOf(row);
        if (!editable) return day.record ? <PresenceStatusBadge status={day.record.status} /> : "—";
        return (
          <Select className="h-8" aria-label={t("hr.presence.status")} value={draft?.status ?? ""} onChange={(e) => update(row.employee_id, { status: e.target.value as PresenceStatus })}>
            <option value="">—</option>
            {ENTERABLE_STATUSES.map((status) => (
              <option key={status} value={status}>{t(PRESENCE_STATUS_LABEL[status])}</option>
            ))}
          </Select>
        );
      },
    },
    { key: "late", header: t("hr.presence.lateMinutes"), defaultWidth: 110, cell: (row) => numberInput(row, "late", stateOf(row).editable && stateOf(row).draft?.status === "late") },
    {
      key: "worked", header: t("hr.presence.workedMinutes"), defaultWidth: 130,
      cell: (row) => numberInput(row, "worked", stateOf(row).editable && stateOf(row).worked, stateOf(row).day.planned_minutes ? String(stateOf(row).day.planned_minutes) : t("hr.presence.workedAuto")),
    },
    { key: "otDay", header: t("hr.presence.otDay"), defaultWidth: 120, cell: (row) => numberInput(row, "otDay", stateOf(row).editable && stateOf(row).worked && !stateOf(row).offDay) },
    { key: "otNight", header: t("hr.presence.otNight"), defaultWidth: 120, cell: (row) => numberInput(row, "otNight", stateOf(row).editable && stateOf(row).worked && !stateOf(row).offDay) },
    {
      key: "justified", header: t("hr.presence.justified"), defaultWidth: 100,
      cell: (row) => {
        const { draft, editable } = stateOf(row);
        return (
          <Checkbox
            aria-label={t("hr.presence.justified")}
            disabled={!editable || draft?.status !== "absent"}
            checked={draft?.justified ?? false}
            onCheckedChange={(value) => update(row.employee_id, { justified: value === true })}
          />
        );
      },
    },
    {
      key: "note", header: t("hr.presence.note"), defaultWidth: 200,
      cell: (row) => (
        <Input className="h-8" disabled={!stateOf(row).editable} value={drafts[row.employee_id]?.note ?? ""} onChange={(e) => update(row.employee_id, { note: e.target.value })} />
      ),
    },
    {
      key: "source", header: t("hr.presence.source"), defaultWidth: 130,
      cell: (row) => {
        const record = row.days[0].record;
        return record ? <Badge variant="outline">{t(SOURCE_LABEL[record.source])}</Badge> : <span className="text-xs text-muted-foreground">{t("hr.presence.notSaved")}</span>;
      },
    },
  ];

  return (
    <div className="space-y-3">
      {closed && <p className="rounded-md border border-warning/30 bg-warning-soft px-3 py-2 text-sm text-warning">{t("hr.presence.monthClosed")}</p>}
      <p className="text-xs text-muted-foreground">{t("hr.presence.restHolidayHint")}</p>
      <HrListTable
        tableKey="hr.presence.dayGrid"
        columns={columns}
        rows={rows}
        rowKey={(row) => row.employee_id}
        loading={grid.isLoading}
        emptyIcon={<Users className="h-5 w-5" />}
        emptyTitle={t("hr.presence.empty.title")}
        emptyDescription={t("hr.presence.empty.description")}
        filtersActive={filters.isActive}
        onClearFilters={filters.reset}
        toolbar={
          <>
            <input type="date" aria-label={t("hr.presence.date")} className="h-9 rounded-md border border-border bg-background px-2 text-sm" value={workDate} onChange={(e) => e.target.value && setWorkDate(e.target.value)} />
            <TeamPicker team={team} onChange={setTeam} departments={departments} schedules={schedules} />
            <FilterTabs
              value={view}
              onChange={setView}
              options={[
                { value: "all", label: t("hr.presence.view.all") },
                { value: "unsaved", label: t("hr.presence.view.unsaved") },
                { value: "exceptions", label: t("hr.presence.view.exceptions") },
              ]}
            />
            {canSave && (
              <Button size="sm" disabled={entries.length === 0 || save.isPending} onClick={() => save.mutate()}>
                <Save className="h-4 w-4" />
                {save.isPending ? t("common.saving") : `${t("hr.presence.save")} (${entries.length})`}
              </Button>
            )}
          </>
        }
      />
    </div>
  );
}
```

- [ ] **Step 3: The week grid**

`frontend/src/features/hr/presence/WeekGridTab.tsx`:

```tsx
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Save, Users } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import { Select } from "../../../components/ui/select";
import { useColumnFilters, type FilterField } from "../../../lib/useColumnFilters";
import type { ColumnDef } from "../../../lib/useTableColumns";
import type { Department } from "../api";
import { HrListTable } from "../HrListTable";
import {
  ENTERABLE_STATUSES, HR_KEYS, getPresenceWeek, savePresenceDays,
  type GridDay, type GridRow, type PresenceEntry, type PresenceStatus, type WorkSchedule,
} from "../presenceApi";
import { addDaysIso, errorText, monthStartOf, mondayOf, todayIso } from "../presenceFormat";
import { isEditable } from "./DayGridTab";
import { PRESENCE_STATUS_LABEL, PresenceStatusBadge, WEEKDAY_SHORT_KEYS } from "./PresenceStatusBadge";
import { TeamPicker, teamFilterOf, type Team } from "./TeamPicker";
import { useClosedMonths } from "./useClosedMonths";

interface CellDraft { status: PresenceStatus | ""; late: string; dirty: boolean }
const cellKey = (employeeId: string, workDate: string) => `${employeeId}|${workDate}`;

/** Catch-up entry for a whole week: status (and lateness) per cell. Details stay in the day grid. */
export function WeekGridTab({ departments, schedules }: { departments: Department[]; schedules: WorkSchedule[] }) {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [dateFrom, setDateFrom] = useState(mondayOf(todayIso()));
  const [team, setTeam] = useState<Team>({ kind: "department", id: "" });
  const [drafts, setDrafts] = useState<Record<string, CellDraft>>({});
  const dates = Array.from({ length: 7 }, (_, i) => addDaysIso(dateFrom, i));
  const week = useQuery({
    queryKey: [...HR_KEYS.presence, "week", dateFrom, team.kind, team.id],
    queryFn: () => getPresenceWeek(token, dateFrom, teamFilterOf(team)),
  });
  const closedMonths = useClosedMonths([Number(dates[0].slice(0, 4)), Number(dates[6].slice(0, 4))]);
  const canSave = hasPermission("hr.manage_presence");

  useEffect(() => {
    if (!week.data) return;
    const next: Record<string, CellDraft> = {};
    for (const row of week.data) {
      for (const day of row.days) {
        const status = day.record?.status ?? day.default_status ?? "";
        next[cellKey(row.employee_id, day.work_date)] = { status, late: day.record?.late_minutes ? String(day.record.late_minutes) : "", dirty: false };
      }
    }
    setDrafts(next);
  }, [week.data]);

  const editable = (day: GridDay) => canSave && isEditable(day, closedMonths.has(monthStartOf(day.work_date)));
  const update = (key: string, patch: Partial<CellDraft>) => setDrafts((current) => ({ ...current, [key]: { ...current[key], ...patch, dirty: true } }));

  const entries: PresenceEntry[] = (week.data ?? []).flatMap((row) =>
    row.days.flatMap((day) => {
      const draft = drafts[cellKey(row.employee_id, day.work_date)];
      if (!draft || !draft.status || draft.status === "leave" || !editable(day) || (day.record && !draft.dirty)) return [];
      const status = draft.status;
      return [{
        employee_id: row.employee_id, work_date: day.work_date, status, worked_minutes: null,
        late_minutes: status === "late" ? Number(draft.late || 0) : 0, ot_minutes_day: 0, ot_minutes_night: 0,
        justified: false, note: day.record?.note ?? null,
      }];
    }),
  );
  const save = useMutation({
    mutationFn: () => savePresenceDays(token, entries),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: HR_KEYS.presence });
      toast.success(`${t("hr.presence.saved")} (${result.saved})`);
    },
    onError: (error) => toast.error(errorText(error, t("hr.common.saveError"))),
  });

  const fields: FilterField<GridRow>[] = [{ key: "employee", kind: "text", getValue: (row) => `${row.employee_no} ${row.full_name}` }];
  const filters = useColumnFilters(fields);
  const rows = filters.apply(week.data ?? []);

  const dayColumn = (workDate: string, index: number): ColumnDef<GridRow> => ({
    key: `d${index}`,
    header: `${t(WEEKDAY_SHORT_KEYS[index])} ${workDate.slice(8, 10)}/${workDate.slice(5, 7)}`,
    defaultWidth: 130,
    cell: (row) => {
      const day = row.days[index];
      const key = cellKey(row.employee_id, workDate);
      const draft = drafts[key];
      if (!editable(day)) return day.record ? <PresenceStatusBadge status={day.record.status} /> : <span className="text-muted-foreground">—</span>;
      return (
        <div className="space-y-1">
          <Select className="h-8 text-xs" aria-label={workDate} value={draft?.status ?? ""} onChange={(e) => update(key, { status: e.target.value as PresenceStatus })}>
            <option value="">—</option>
            {ENTERABLE_STATUSES.map((status) => (
              <option key={status} value={status}>{t(PRESENCE_STATUS_LABEL[status])}</option>
            ))}
          </Select>
          {draft?.status === "late" && (
            <Input type="number" min={1} className="h-7 text-xs" placeholder={t("hr.presence.lateMinutes")} value={draft.late} onChange={(e) => update(key, { late: e.target.value })} />
          )}
        </div>
      );
    },
  });
  const columns: ColumnDef<GridRow>[] = [
    {
      key: "employee", header: t("hr.common.employee"), defaultWidth: 220, alwaysVisible: true, sortValue: (row) => row.employee_no,
      cell: (row) => <span className="font-medium">{row.employee_no} · {row.full_name}</span>,
      filterCell: { type: "text", placeholder: t("hr.common.employee"), value: filters.text.employee ?? "", onChange: (v) => filters.setTextValue("employee", v) },
    },
    ...dates.map(dayColumn),
  ];

  return (
    <HrListTable
      tableKey="hr.presence.weekGrid"
      columns={columns}
      rows={rows}
      rowKey={(row) => row.employee_id}
      loading={week.isLoading}
      emptyIcon={<Users className="h-5 w-5" />}
      emptyTitle={t("hr.presence.empty.title")}
      emptyDescription={t("hr.presence.empty.description")}
      filtersActive={filters.isActive}
      onClearFilters={filters.reset}
      toolbar={
        <>
          <label className="flex items-center gap-2 text-sm">
            {t("hr.presence.weekOf")}
            <input type="date" className="h-9 rounded-md border border-border bg-background px-2 text-sm" value={dateFrom} onChange={(e) => e.target.value && setDateFrom(mondayOf(e.target.value))} />
          </label>
          <TeamPicker team={team} onChange={setTeam} departments={departments} schedules={schedules} />
          {canSave && (
            <Button size="sm" disabled={entries.length === 0 || save.isPending} onClick={() => save.mutate()}>
              <Save className="h-4 w-4" />
              {save.isPending ? t("common.saving") : `${t("hr.presence.save")} (${entries.length})`}
            </Button>
          )}
        </>
      }
    />
  );
}
```

- [ ] **Step 4: One person's month**

`frontend/src/features/hr/presence/EmployeeMonthTab.tsx`:

```tsx
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Lock } from "lucide-react";
import { useAuth } from "../../../lib/auth";
import { useI18n, type TranslationKey } from "../../../lib/i18n";
import { Select } from "../../../components/ui/select";
import { Skeleton } from "../../../components/ui/skeleton";
import { Badge } from "../../../components/ui/badge";
import { cn } from "../../../lib/utils";
import type { Employee } from "../api";
import { HR_KEYS, getEmployeeMonth, getMonthSummary, type MonthSummary } from "../presenceApi";
import { employeeLabel, formatDuration, todayIso, weekdayOf } from "../presenceFormat";
import { PresenceStatusBadge, WEEKDAY_SHORT_KEYS } from "./PresenceStatusBadge";

export const SUMMARY_TILES: { key: keyof MonthSummary; label: TranslationKey; minutes?: boolean }[] = [
  { key: "scheduled_days", label: "hr.presence.summary.scheduledDays" },
  { key: "worked_days", label: "hr.presence.summary.workedDays" },
  { key: "unpaid_absence_days", label: "hr.presence.summary.unpaidAbsenceDays" },
  { key: "paid_leave_days", label: "hr.presence.summary.paidLeaveDays" },
  { key: "sick_days", label: "hr.presence.summary.sickDays" },
  { key: "holiday_days", label: "hr.presence.summary.holidayDays" },
  { key: "holidays_worked_days", label: "hr.presence.summary.holidaysWorkedDays" },
  { key: "ot_minutes_day", label: "hr.presence.summary.otDay", minutes: true },
  { key: "ot_minutes_night", label: "hr.presence.summary.otNight", minutes: true },
  { key: "ot_minutes_rest_holiday", label: "hr.presence.summary.otRestHoliday", minutes: true },
  { key: "night_minutes", label: "hr.presence.summary.nightHours", minutes: true },
  { key: "late_minutes", label: "hr.presence.summary.lateMinutes", minutes: true },
];


export function EmployeeMonthTab({ employees }: { employees: Employee[] }) {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const [employeeId, setEmployeeId] = useState("");
  const [month, setMonth] = useState(todayIso().slice(0, 7));
  const period = `${month}-01`;
  const detail = useQuery({
    queryKey: [...HR_KEYS.presence, "employee-month", employeeId, period],
    queryFn: () => getEmployeeMonth(token, employeeId, period),
    enabled: employeeId !== "",
  });
  const summary = useQuery({
    queryKey: [...HR_KEYS.presence, "summary", period, employeeId],
    queryFn: () => getMonthSummary(token, period, employeeId),
    enabled: employeeId !== "",
  });
  const figures = summary.data?.[0];
  const days = detail.data?.days ?? [];
  const leading = days.length ? weekdayOf(days[0].work_date) : 0;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Select aria-label={t("hr.common.employee")} value={employeeId} onChange={(e) => setEmployeeId(e.target.value)}>
          <option value="">{t("hr.presence.pickEmployee")}</option>
          {employees.map((employee) => (
            <option key={employee.id} value={employee.id}>{employeeLabel(employee)}</option>
          ))}
        </Select>
        <input type="month" aria-label={t("hr.presence.month")} className="h-9 rounded-md border border-border bg-background px-2 text-sm" value={month} onChange={(e) => e.target.value && setMonth(e.target.value)} />
        {detail.data?.closed && (
          <Badge variant="default"><Lock className="mr-1 h-3 w-3" />{t("hr.presence.months.status.closed")}</Badge>
        )}
      </div>
      {employeeId && detail.isLoading && <Skeleton className="h-96 w-full" />}
      {detail.data && (
        <>
          <div className="grid grid-cols-7 gap-1 text-xs">
            {WEEKDAY_SHORT_KEYS.map((key) => (
              <div key={key} className="px-1 font-medium text-muted-foreground">{t(key)}</div>
            ))}
            {Array.from({ length: leading }, (_, i) => <div key={`pad-${i}`} />)}
            {days.map((day) => {
              const record = day.record;
              const overtime = record ? record.ot_minutes_day + record.ot_minutes_night + record.ot_minutes_rest_holiday : 0;
              return (
                <div
                  key={day.work_date}
                  className={cn("min-h-20 space-y-1 rounded-md border border-border p-1.5", !day.employed && "opacity-40", day.is_holiday && "bg-accent/5")}
                >
                  <div className="flex items-center justify-between">
                    <span className="font-medium">{Number(day.work_date.slice(8, 10))}</span>
                    {record?.locked && <Lock className="h-3 w-3 text-muted-foreground" />}
                  </div>
                  {record ? (
                    <PresenceStatusBadge status={record.status} />
                  ) : day.default_status ? (
                    <span className="text-muted-foreground">{t("hr.presence.planned")}</span>
                  ) : null}
                  {record && record.worked_minutes > 0 && <div className="tabular-nums">{formatDuration(record.worked_minutes)}</div>}
                  {overtime > 0 && <div className="tabular-nums text-warning">+{formatDuration(overtime)}</div>}
                </div>
              );
            })}
          </div>
          {figures && (
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-6">
              {SUMMARY_TILES.map((tile) => (
                <div key={tile.key} className="rounded-md border border-border p-2">
                  <p className="text-lg font-semibold tabular-nums">
                    {tile.minutes ? formatDuration(Number(figures[tile.key])) : figures[tile.key]}
                  </p>
                  <p className="text-xs text-muted-foreground">{t(tile.label)}</p>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
```


- [ ] **Step 5: Month close**

`frontend/src/features/hr/presence/MonthCloseTab.tsx`:

```tsx
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarCheck, CheckCircle2, Lock, ListChecks, Unlock } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { Badge } from "../../../components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "../../../components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../../components/ui/dialog";
import { FilterTabs } from "../../../components/patterns/FilterTabs";
import { useColumnFilters, type FilterField } from "../../../lib/useColumnFilters";
import type { ColumnDef } from "../../../lib/useTableColumns";
import type { Employee } from "../api";
import { HrListTable } from "../HrListTable";
import {
  HR_KEYS, closePresenceMonth, getMonthGaps, getMonthSummary, listPresenceMonths, reopenPresenceMonth,
  type MonthSummary, type PresenceGap, type PresenceMonth,
} from "../presenceApi";
import { errorText, formatDay, formatDuration, formatMonth, monthStartOf, todayIso } from "../presenceFormat";
import { SUMMARY_TILES } from "./EmployeeMonthTab";

type StatusFilter = "all" | "open" | "closed";
type GapFilter = "all" | "missing" | "no_schedule";
type SummaryRowView = MonthSummary & { employee_no: string; full_name: string };

export function MonthCloseTab({ employees }: { employees: Employee[] }) {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [year, setYear] = useState(Number(todayIso().slice(0, 4)));
  const [selected, setSelected] = useState(monthStartOf(todayIso()));
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [gapFilter, setGapFilter] = useState<GapFilter>("all");
  const [closing, setClosing] = useState(false);
  const [reopening, setReopening] = useState(false);
  const [reason, setReason] = useState("");
  const months = useQuery({ queryKey: [...HR_KEYS.presence, "months", year], queryFn: () => listPresenceMonths(token, year) });
  const current = months.data?.find((m) => m.period === selected);
  const gaps = useQuery({
    queryKey: [...HR_KEYS.presence, "gaps", selected],
    queryFn: () => getMonthGaps(token, selected),
    enabled: current?.status === "open",
  });
  const summary = useQuery({ queryKey: [...HR_KEYS.presence, "summary", selected, ""], queryFn: () => getMonthSummary(token, selected) });
  const refresh = () => queryClient.invalidateQueries({ queryKey: HR_KEYS.presence });

  const close = useMutation({
    mutationFn: () => closePresenceMonth(token, selected),
    onSuccess: () => {
      refresh();
      setClosing(false);
      toast.success(t("hr.presence.months.closedToast"));
    },
    onError: (error) => toast.error(errorText(error, t("hr.common.saveError"))),
  });
  const reopen = useMutation({
    mutationFn: () => reopenPresenceMonth(token, selected, reason.trim()),
    onSuccess: () => {
      refresh();
      setReopening(false);
      setReason("");
      toast.success(t("hr.presence.months.reopened"));
    },
    onError: (error) => toast.error(errorText(error, t("hr.common.saveError"))),
  });

  const monthColumns: ColumnDef<PresenceMonth>[] = [
    { key: "period", header: t("hr.presence.months.period"), defaultWidth: 180, sortValue: (m) => m.period, cell: (m) => <span className="font-medium capitalize">{formatMonth(m.period)}</span> },
    {
      key: "status", header: t("hr.presence.status"), defaultWidth: 130,
      cell: (m) => <Badge variant={m.status === "closed" ? "success" : "warning"}>{t(m.status === "closed" ? "hr.presence.months.status.closed" : "hr.presence.months.status.open")}</Badge>,
    },
    { key: "closedAt", header: t("hr.presence.months.closedAt"), defaultWidth: 150, cell: (m) => (m.closed_at ? formatDay(m.closed_at.slice(0, 10)) : "—") },
    { key: "payroll", header: t("hr.presence.months.payroll"), defaultWidth: 140, cell: (m) => (m.payroll_locked ? <Lock className="h-4 w-4" /> : "—") },
    {
      key: "actions", header: "", defaultWidth: 320, alwaysVisible: true,
      cell: (m) => (
        <div className="flex justify-end gap-2">
          <Button size="sm" variant={m.period === selected ? "default" : "outline"} onClick={() => setSelected(m.period)}>
            <ListChecks className="h-3.5 w-3.5" />
            {t("hr.presence.months.view")}
          </Button>
          {m.status === "open" && hasPermission("hr.close_presence") && (
            <Button size="sm" variant="outline" onClick={() => { setSelected(m.period); setClosing(true); }}>
              <CheckCircle2 className="h-3.5 w-3.5" />
              {t("hr.presence.months.close")}
            </Button>
          )}
          {m.status === "closed" && hasPermission("hr.admin_presence") && (
            <Button size="sm" variant="ghost" disabled={m.payroll_locked} onClick={() => { setSelected(m.period); setReopening(true); }}>
              <Unlock className="h-3.5 w-3.5" />
              {t("hr.presence.months.reopen")}
            </Button>
          )}
        </div>
      ),
    },
  ];
  const monthRows = (months.data ?? []).filter((m) => statusFilter === "all" || m.status === statusFilter);

  const gapFields: FilterField<PresenceGap>[] = [
    { key: "employee", kind: "text", getValue: (g) => `${g.employee_no} ${g.full_name}` },
    { key: "date", kind: "text", getValue: (g) => g.work_date },
  ];
  const gapFilters = useColumnFilters(gapFields);
  const gapRows = gapFilters.apply((gaps.data ?? []).filter((g) => gapFilter === "all" || g.reason === gapFilter));
  const gapColumns: ColumnDef<PresenceGap>[] = [
    {
      key: "employee", header: t("hr.common.employee"), defaultWidth: 240, sortValue: (g) => g.employee_no, cell: (g) => `${g.employee_no} · ${g.full_name}`,
      filterCell: { type: "text", placeholder: t("hr.common.employee"), value: gapFilters.text.employee ?? "", onChange: (v) => gapFilters.setTextValue("employee", v) },
    },
    {
      key: "date", header: t("hr.presence.date"), defaultWidth: 160, sortValue: (g) => g.work_date, cell: (g) => formatDay(g.work_date),
      filterCell: { type: "text", placeholder: "2026-08-…", value: gapFilters.text.date ?? "", onChange: (v) => gapFilters.setTextValue("date", v) },
    },
    { key: "reason", header: t("hr.presence.months.gapColumn"), defaultWidth: 160, cell: (g) => t(g.reason === "missing" ? "hr.presence.months.gapReason.missing" : "hr.presence.months.gapReason.no_schedule") },
  ];

  const byId = new Map(employees.map((e) => [e.id, e]));
  const summaryRows: SummaryRowView[] = (summary.data ?? []).map((row) => ({
    ...row,
    employee_no: byId.get(row.employee_id)?.employee_no ?? "?",
    full_name: byId.get(row.employee_id) ? `${byId.get(row.employee_id)!.first_name} ${byId.get(row.employee_id)!.last_name}` : row.employee_id,
  }));
  const summaryFields: FilterField<SummaryRowView>[] = [
    { key: "employee", kind: "text", getValue: (r) => `${r.employee_no} ${r.full_name}` },
    { key: "worked_days", kind: "range", getValue: (r) => r.worked_days },
    { key: "unpaid_absence_days", kind: "range", getValue: (r) => r.unpaid_absence_days },
  ];
  const summaryFilters = useColumnFilters(summaryFields);
  const summaryColumns: ColumnDef<SummaryRowView>[] = [
    {
      key: "employee", header: t("hr.common.employee"), defaultWidth: 220, alwaysVisible: true, sortValue: (r) => r.employee_no, cell: (r) => `${r.employee_no} · ${r.full_name}`,
      filterCell: { type: "text", placeholder: t("hr.common.employee"), value: summaryFilters.text.employee ?? "", onChange: (v) => summaryFilters.setTextValue("employee", v) },
    },
    ...SUMMARY_TILES.map((tile): ColumnDef<SummaryRowView> => ({
      key: tile.key,
      header: t(tile.label),
      defaultWidth: 120,
      cellClassName: "tabular-nums",
      sortValue: (r) => Number(r[tile.key]),
      cell: (r) => (tile.minutes ? formatDuration(Number(r[tile.key])) : r[tile.key]),
      filterCell:
        tile.key === "worked_days" || tile.key === "unpaid_absence_days"
          ? {
              type: "range",
              min: summaryFilters.range[tile.key]?.min ?? "",
              max: summaryFilters.range[tile.key]?.max ?? "",
              onMinChange: (v) => summaryFilters.setRangeValue(tile.key, "min", v),
              onMaxChange: (v) => summaryFilters.setRangeValue(tile.key, "max", v),
            }
          : undefined,
    })),
  ];

  return (
    <div className="space-y-4">
      <HrListTable
        tableKey="hr.presence.months"
        columns={monthColumns}
        rows={monthRows}
        rowKey={(m) => m.period}
        loading={months.isLoading}
        emptyIcon={<CalendarCheck className="h-5 w-5" />}
        emptyTitle={t("hr.presence.months.period")}
        emptyDescription=""
        rowClassName={(m) => (m.period === selected ? "bg-muted/50" : undefined)}
        toolbar={
          <>
            <Input type="number" className="w-24" aria-label={t("hr.common.year")} value={year} onChange={(e) => setYear(Number(e.target.value) || year)} />
            <FilterTabs
              value={statusFilter}
              onChange={setStatusFilter}
              options={[
                { value: "all", label: t("common.all") },
                { value: "open", label: t("hr.presence.months.status.open") },
                { value: "closed", label: t("hr.presence.months.status.closed") },
              ]}
            />
          </>
        }
      />
      {current?.status === "open" && (
        <Card>
          <CardHeader>
            <CardTitle className="capitalize">{t("hr.presence.months.gaps")} — {formatMonth(selected)}</CardTitle>
          </CardHeader>
          <CardContent>
            <HrListTable
              tableKey="hr.presence.gaps"
              columns={gapColumns}
              rows={gapRows}
              rowKey={(g) => `${g.employee_id}|${g.work_date}`}
              loading={gaps.isLoading}
              emptyIcon={<CheckCircle2 className="h-5 w-5" />}
              emptyTitle={t("hr.presence.months.gapsNone")}
              emptyDescription={t("hr.presence.months.gapsNoneHelp")}
              filtersActive={gapFilters.isActive}
              onClearFilters={gapFilters.reset}
              toolbar={
                <FilterTabs
                  value={gapFilter}
                  onChange={setGapFilter}
                  options={[
                    { value: "all", label: t("common.all") },
                    { value: "missing", label: t("hr.presence.months.gapReason.missing") },
                    { value: "no_schedule", label: t("hr.presence.months.gapReason.no_schedule") },
                  ]}
                />
              }
            />
          </CardContent>
        </Card>
      )}
      <Card>
        <CardHeader>
          <CardTitle className="capitalize">{t("hr.presence.months.summary")} — {formatMonth(selected)}</CardTitle>
        </CardHeader>
        <CardContent>
          <HrListTable
            tableKey="hr.presence.summary"
            columns={summaryColumns}
            rows={summaryFilters.apply(summaryRows)}
            rowKey={(r) => r.employee_id}
            loading={summary.isLoading}
            emptyIcon={<ListChecks className="h-5 w-5" />}
            emptyTitle={t("hr.presence.months.summaryEmpty.title")}
            emptyDescription={t("hr.presence.months.summaryEmpty.description")}
            filtersActive={summaryFilters.isActive}
            onClearFilters={summaryFilters.reset}
          />
        </CardContent>
      </Card>
      <Dialog open={closing} onOpenChange={setClosing}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="capitalize">{t("hr.presence.months.closeTitle")} — {formatMonth(selected)}</DialogTitle>
            <DialogDescription>{t("hr.presence.months.closeHelp")}</DialogDescription>
          </DialogHeader>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setClosing(false)}>{t("common.cancel")}</Button>
            <Button onClick={() => close.mutate()} disabled={close.isPending}>{t("hr.presence.months.close")}</Button>
          </div>
        </DialogContent>
      </Dialog>
      <Dialog open={reopening} onOpenChange={setReopening}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="capitalize">{t("hr.presence.months.reopenTitle")} — {formatMonth(selected)}</DialogTitle>
            <DialogDescription>{t("hr.presence.months.reopenHelp")}</DialogDescription>
          </DialogHeader>
          <div className="space-y-1.5">
            <Label htmlFor="reopen-reason">{t("hr.presence.months.reason")}</Label>
            <Input id="reopen-reason" value={reason} onChange={(e) => setReason(e.target.value)} />
          </div>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setReopening(false)}>{t("common.cancel")}</Button>
            <Button onClick={() => reopen.mutate()} disabled={!reason.trim() || reopen.isPending}>{t("hr.presence.months.reopen")}</Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
```

- [ ] **Step 6: The page, route, sidebar and strings**

`frontend/src/features/hr/presence/PresencePage.tsx`:

```tsx
import { useQuery } from "@tanstack/react-query";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { listDepartments, listEmployees } from "../api";
import { HrTabsPage, useBooted, useTabParam } from "../HrTabsPage";
import { HR_KEYS, listSchedules } from "../presenceApi";
import { DayGridTab } from "./DayGridTab";
import { EmployeeMonthTab } from "./EmployeeMonthTab";
import { MonthCloseTab } from "./MonthCloseTab";
import { WeekGridTab } from "./WeekGridTab";

const TABS = ["day", "week", "calendar", "month"] as const;

export function PresencePage() {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const [tab, setTab] = useTabParam(TABS, "day");
  const departments = useQuery({ queryKey: HR_KEYS.departments, queryFn: () => listDepartments(token) });
  const schedules = useQuery({ queryKey: HR_KEYS.schedules, queryFn: () => listSchedules(token) });
  const employees = useQuery({ queryKey: HR_KEYS.employees, queryFn: () => listEmployees(token) });
  const booted = useBooted(!departments.isLoading && !schedules.isLoading && !employees.isLoading);
  const teams = { departments: departments.data ?? [], schedules: schedules.data ?? [] };
  return (
    <HrTabsPage
      title={t("hr.presence.title")}
      subtitle={t("hr.presence.subtitle")}
      layoutId="hr-presence-tab"
      active={tab}
      onChange={setTab}
      booted={booted}
      loaderLabel={t("hr.presence.loading")}
      tabs={[
        { value: "day", label: t("hr.presence.tab.day"), content: <DayGridTab {...teams} /> },
        { value: "week", label: t("hr.presence.tab.week"), content: <WeekGridTab {...teams} /> },
        { value: "calendar", label: t("hr.presence.tab.calendar"), content: <EmployeeMonthTab employees={employees.data ?? []} /> },
        { value: "month", label: t("hr.presence.tab.month"), content: <MonthCloseTab employees={employees.data ?? []} /> },
      ]}
    />
  );
}
```

`router.tsx`: import `PresencePage` from `"../features/hr/presence/PresencePage"`; add `{ path: "/hr/presence", element: <PresencePage /> },`.

`Sidebar.tsx`: add `CalendarCheck` to the `lucide-react` import list and append to the HR group's `items` (before the schedules entry from Task 10):

```ts
      { to: "/hr/presence", labelKey: "nav.hrPresence", icon: CalendarCheck, exact: true, permission: "hr.view_presence" },
```

(`exact` keeps it from lighting up on `/hr/presence/imports`.)

`i18n.tsx` — `en`:

```ts
  "nav.hrPresence": "Presence",
  "hr.presence.title": "Presence",
  "hr.presence.subtitle": "Daily presence by team, each person's month, and the month close payroll waits for.",
  "hr.presence.loading": "Loading presence…",
  "hr.presence.tab.day": "Day",
  "hr.presence.tab.week": "Week",
  "hr.presence.tab.calendar": "Employee month",
  "hr.presence.tab.month": "Month close",
  "hr.presence.team": "Team",
  "hr.presence.teamKind.department": "By department",
  "hr.presence.teamKind.schedule": "By schedule",
  "hr.presence.allTeams": "Everyone",
  "hr.presence.date": "Date",
  "hr.presence.weekOf": "Week of",
  "hr.presence.schedule": "Schedule",
  "hr.presence.status": "Status",
  "hr.presence.lateMinutes": "Late (min)",
  "hr.presence.workedMinutes": "Worked (min)",
  "hr.presence.workedAuto": "auto",
  "hr.presence.otDay": "OT day (min)",
  "hr.presence.otNight": "OT night (min)",
  "hr.presence.justified": "Justified",
  "hr.presence.note": "Note",
  "hr.presence.source": "Source",
  "hr.presence.source.manual": "Entered",
  "hr.presence.source.clock": "Clock",
  "hr.presence.source.leave": "Leave request",
  "hr.presence.source.holiday": "Holiday",
  "hr.presence.notSaved": "Not saved",
  "hr.presence.noSchedule": "No schedule",
  "hr.presence.notEmployed": "Not employed",
  "hr.presence.view.all": "Everyone",
  "hr.presence.view.unsaved": "Not saved",
  "hr.presence.view.exceptions": "Exceptions",
  "hr.presence.save": "Save presence",
  "hr.presence.saved": "Presence saved",
  "hr.presence.monthClosed": "This month is closed: its presence can no longer change.",
  "hr.presence.restHolidayHint": "On a rest day or a public holiday every worked minute is rest/holiday overtime; day and night overtime apply to working days only.",
  "hr.presence.empty.title": "Nobody to show",
  "hr.presence.empty.description": "No employee of this team is employed on these dates.",
  "hr.presence.pickEmployee": "Choose an employee",
  "hr.presence.month": "Month",
  "hr.presence.planned": "planned",
  "hr.presence.summary.scheduledDays": "Scheduled days",
  "hr.presence.summary.workedDays": "Days worked",
  "hr.presence.summary.unpaidAbsenceDays": "Unpaid absence days",
  "hr.presence.summary.paidLeaveDays": "Paid leave days",
  "hr.presence.summary.sickDays": "Sick days",
  "hr.presence.summary.holidayDays": "Public holidays",
  "hr.presence.summary.holidaysWorkedDays": "Holidays worked",
  "hr.presence.summary.otDay": "Day overtime",
  "hr.presence.summary.otNight": "Night overtime",
  "hr.presence.summary.otRestHoliday": "Rest/holiday overtime",
  "hr.presence.summary.nightHours": "Night hours",
  "hr.presence.summary.lateMinutes": "Lateness",
  "hr.presence.months.period": "Month",
  "hr.presence.months.status.open": "Open",
  "hr.presence.months.status.closed": "Closed",
  "hr.presence.months.closedAt": "Closed on",
  "hr.presence.months.payroll": "Payroll approved",
  "hr.presence.months.view": "View",
  "hr.presence.months.close": "Close the month",
  "hr.presence.months.closeTitle": "Close this month?",
  "hr.presence.months.closeHelp": "Closing locks every presence day of the month, adds the public-holiday days, posts the month's leave accrual and tells payroll the month is ready.",
  "hr.presence.months.closedToast": "Month closed",
  "hr.presence.months.reopen": "Reopen",
  "hr.presence.months.reopenTitle": "Reopen this month?",
  "hr.presence.months.reopenHelp": "Reopening unlocks the month so presence can be corrected. It is refused while an approved payroll exists for it.",
  "hr.presence.months.reason": "Reason",
  "hr.presence.months.reopened": "Month reopened",
  "hr.presence.months.gaps": "Working days without presence",
  "hr.presence.months.gapsNone": "Every working day has its presence.",
  "hr.presence.months.gapsNoneHelp": "The month can be closed.",
  "hr.presence.months.gapColumn": "Why",
  "hr.presence.months.gapReason.missing": "Not recorded",
  "hr.presence.months.gapReason.no_schedule": "No schedule",
  "hr.presence.months.summary": "Month summary (what payroll reads)",
  "hr.presence.months.summaryEmpty.title": "Nothing recorded this month",
  "hr.presence.months.summaryEmpty.description": "Presence days appear here once saved or imported.",
```

`fr`:

```ts
  "nav.hrPresence": "Présence",
  "hr.presence.title": "Présence",
  "hr.presence.subtitle": "La présence du jour par équipe, le mois de chaque personne et la clôture mensuelle attendue par la paie.",
  "hr.presence.loading": "Chargement de la présence…",
  "hr.presence.tab.day": "Jour",
  "hr.presence.tab.week": "Semaine",
  "hr.presence.tab.calendar": "Mois d'un employé",
  "hr.presence.tab.month": "Clôture du mois",
  "hr.presence.team": "Équipe",
  "hr.presence.teamKind.department": "Par département",
  "hr.presence.teamKind.schedule": "Par horaire",
  "hr.presence.allTeams": "Tout le monde",
  "hr.presence.date": "Date",
  "hr.presence.weekOf": "Semaine du",
  "hr.presence.schedule": "Horaire",
  "hr.presence.status": "Statut",
  "hr.presence.lateMinutes": "Retard (min)",
  "hr.presence.workedMinutes": "Travaillé (min)",
  "hr.presence.workedAuto": "auto",
  "hr.presence.otDay": "HS jour (min)",
  "hr.presence.otNight": "HS nuit (min)",
  "hr.presence.justified": "Justifiée",
  "hr.presence.note": "Note",
  "hr.presence.source": "Source",
  "hr.presence.source.manual": "Saisi",
  "hr.presence.source.clock": "Pointeuse",
  "hr.presence.source.leave": "Demande de congé",
  "hr.presence.source.holiday": "Férié",
  "hr.presence.notSaved": "Non enregistré",
  "hr.presence.noSchedule": "Sans horaire",
  "hr.presence.notEmployed": "Hors contrat",
  "hr.presence.view.all": "Tous",
  "hr.presence.view.unsaved": "Non enregistrés",
  "hr.presence.view.exceptions": "Exceptions",
  "hr.presence.save": "Enregistrer la présence",
  "hr.presence.saved": "Présence enregistrée",
  "hr.presence.monthClosed": "Ce mois est clôturé : sa présence ne peut plus changer.",
  "hr.presence.restHolidayHint": "Un jour de repos ou férié, chaque minute travaillée est une heure supplémentaire repos/férié ; les HS jour et nuit ne concernent que les jours travaillés.",
  "hr.presence.empty.title": "Personne à afficher",
  "hr.presence.empty.description": "Aucun employé de cette équipe n'est en poste à ces dates.",
  "hr.presence.pickEmployee": "Choisissez un employé",
  "hr.presence.month": "Mois",
  "hr.presence.planned": "prévu",
  "hr.presence.summary.scheduledDays": "Jours prévus",
  "hr.presence.summary.workedDays": "Jours travaillés",
  "hr.presence.summary.unpaidAbsenceDays": "Absences non payées",
  "hr.presence.summary.paidLeaveDays": "Jours de congé payé",
  "hr.presence.summary.sickDays": "Jours de maladie",
  "hr.presence.summary.holidayDays": "Jours fériés",
  "hr.presence.summary.holidaysWorkedDays": "Fériés travaillés",
  "hr.presence.summary.otDay": "HS de jour",
  "hr.presence.summary.otNight": "HS de nuit",
  "hr.presence.summary.otRestHoliday": "HS repos/férié",
  "hr.presence.summary.nightHours": "Heures de nuit",
  "hr.presence.summary.lateMinutes": "Retards",
  "hr.presence.months.period": "Mois",
  "hr.presence.months.status.open": "Ouvert",
  "hr.presence.months.status.closed": "Clôturé",
  "hr.presence.months.closedAt": "Clôturé le",
  "hr.presence.months.payroll": "Paie approuvée",
  "hr.presence.months.view": "Voir",
  "hr.presence.months.close": "Clôturer le mois",
  "hr.presence.months.closeTitle": "Clôturer ce mois ?",
  "hr.presence.months.closeHelp": "La clôture verrouille chaque jour de présence du mois, ajoute les jours fériés, comptabilise l'acquisition des congés du mois et signale à la paie que le mois est prêt.",
  "hr.presence.months.closedToast": "Mois clôturé",
  "hr.presence.months.reopen": "Rouvrir",
  "hr.presence.months.reopenTitle": "Rouvrir ce mois ?",
  "hr.presence.months.reopenHelp": "La réouverture déverrouille le mois pour corriger la présence. Elle est refusée tant qu'une paie approuvée existe pour ce mois.",
  "hr.presence.months.reason": "Motif",
  "hr.presence.months.reopened": "Mois rouvert",
  "hr.presence.months.gaps": "Jours de travail sans présence",
  "hr.presence.months.gapsNone": "Chaque jour de travail a sa présence.",
  "hr.presence.months.gapsNoneHelp": "Le mois peut être clôturé.",
  "hr.presence.months.gapColumn": "Raison",
  "hr.presence.months.gapReason.missing": "Non saisi",
  "hr.presence.months.gapReason.no_schedule": "Sans horaire",
  "hr.presence.months.summary": "Récapitulatif du mois (ce que lit la paie)",
  "hr.presence.months.summaryEmpty.title": "Rien d'enregistré ce mois",
  "hr.presence.months.summaryEmpty.description": "Les jours de présence apparaissent ici une fois saisis ou importés.",
```

- [ ] **Step 7: Type-check**

Run (from `frontend/`): `npx tsc -b --force`
Expected: exit 0. (If `Department` is not exported from `features/hr/api.ts` under that name after phase 1, import the type phase 1 exports for `listDepartments`.)

- [ ] **Step 8: Browser check**

With the Task 10 schedules in place (one schedule, two assigned employees), open `/hr/presence` in a private headless Chrome: one branded loader; Day tab shows each employee with the planned status; change one to Late 30 and save → toast, "Source: Entered", the other rows still "Not saved" until saved; Week tab shows seven day columns with the saved day; Employee month shows the calendar and the summary tiles; Month close lists 12 months, the current month's gaps, and the close dialog refuses with the gap count (`PRESENCE_INCOMPLETE`) in the chosen language.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/features/hr/presence/PresencePage.tsx frontend/src/features/hr/presence/TeamPicker.tsx frontend/src/features/hr/presence/useClosedMonths.ts frontend/src/features/hr/presence/DayGridTab.tsx frontend/src/features/hr/presence/WeekGridTab.tsx frontend/src/features/hr/presence/EmployeeMonthTab.tsx frontend/src/features/hr/presence/MonthCloseTab.tsx frontend/src/routes/router.tsx frontend/src/routes/Sidebar.tsx frontend/src/lib/i18n.tsx
git commit -m "feat(hr): presence screen - day and week grids, employee month, month close

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12: `/hr/presence/imports` — device profiles, upload, staging review, commit

**Files:**
- Create: `frontend/src/features/hr/presence/ClockImportsPage.tsx`, `ClockProfilesCard.tsx`, `ClockImportReview.tsx`
- Modify: `frontend/src/routes/router.tsx`, `frontend/src/routes/Sidebar.tsx`, `frontend/src/lib/i18n.tsx`

**Interfaces:**
- Consumes (Task 10): `HR_KEYS`, `listClockProfiles`, `createClockProfile`, `updateClockProfile`, `listClockImports`, `getClockImport`, `stageClockImport`, `commitClockImport`, `discardClockImport`, types `ClockProfile`, `ClockProfileInput`, `ClockImport`, `ClockImportRow`, `ClockCommitResult`, `ClockConflict`, `ClockAnomaly`; `HrListTable`, `useBooted`; `PresenceStatusBadge`; `presenceFormat` helpers.
- Produces: `ClockImportsPage` (route `/hr/presence/imports`). The file is read in the browser with `File.text()` and sent as JSON (`content`), matching Task 6's route.

- [ ] **Step 1: Device profiles card**

`frontend/src/features/hr/presence/ClockProfilesCard.tsx`:

```tsx
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Fingerprint, Pencil, Plus } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { Select } from "../../../components/ui/select";
import { Checkbox } from "../../../components/ui/checkbox";
import { Card, CardContent, CardHeader, CardTitle } from "../../../components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../../components/ui/dialog";
import { FilterTabs } from "../../../components/patterns/FilterTabs";
import { useColumnFilters, type FilterField } from "../../../lib/useColumnFilters";
import type { ColumnDef } from "../../../lib/useTableColumns";
import { HrListTable } from "../HrListTable";
import { HR_KEYS, createClockProfile, listClockProfiles, updateClockProfile, type ClockProfile, type ClockProfileInput } from "../presenceApi";
import { errorText } from "../presenceFormat";

interface ProfileDraft {
  code: string; name: string; delimiter: string; hasHeader: boolean; badgeColumn: string; timestampColumn: string;
  timeColumn: string; timestampFormat: string; directionColumn: string; inValues: string; outValues: string;
}
const DELIMITERS = [";", ",", "\t", "|"];
const emptyDraft = (): ProfileDraft => ({
  code: "", name: "", delimiter: ";", hasHeader: true, badgeColumn: "", timestampColumn: "", timeColumn: "",
  timestampFormat: "", directionColumn: "", inValues: "", outValues: "",
});
const splitValues = (text: string) => text.split(",").map((value) => value.trim()).filter(Boolean);

function toInput(draft: ProfileDraft): ClockProfileInput {
  return {
    code: draft.code.trim(), name: draft.name.trim(), delimiter: draft.delimiter, has_header: draft.hasHeader,
    badge_column: draft.badgeColumn.trim(), timestamp_column: draft.timestampColumn.trim(), time_column: draft.timeColumn.trim() || null,
    timestamp_format: draft.timestampFormat.trim(), direction_column: draft.directionColumn.trim() || null,
    in_values: splitValues(draft.inValues), out_values: splitValues(draft.outValues),
  };
}

export function ClockProfilesCard() {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const profiles = useQuery({ queryKey: HR_KEYS.clockProfiles, queryFn: () => listClockProfiles(token) });
  const [activeFilter, setActiveFilter] = useState<"active" | "inactive" | "all">("active");
  const [editing, setEditing] = useState<ClockProfile | null>(null);
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<ProfileDraft>(emptyDraft);
  const [formError, setFormError] = useState<string | null>(null);
  const canEdit = hasPermission("hr.admin_presence");

  const save = useMutation({
    mutationFn: () => {
      const input = toInput(draft);
      if (!editing) return createClockProfile(token, input);
      const { code: _code, ...changes } = input;
      // An empty optional column is sent as "" so the server clears it.
      return updateClockProfile(token, editing.id, { ...changes, time_column: changes.time_column ?? "", direction_column: changes.direction_column ?? "" });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: HR_KEYS.clockProfiles });
      setOpen(false);
      toast.success(t(editing ? "hr.clock.profiles.updated" : "hr.clock.profiles.created"));
    },
    onError: (error) => setFormError(errorText(error, t("hr.common.saveError"))),
  });
  const toggleActive = useMutation({
    mutationFn: (profile: ClockProfile) => updateClockProfile(token, profile.id, { active: !profile.active }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: HR_KEYS.clockProfiles }),
    onError: (error) => toast.error(errorText(error, t("hr.common.saveError"))),
  });

  function openDialog(profile: ClockProfile | null) {
    setEditing(profile);
    setDraft(
      profile
        ? {
            code: profile.code, name: profile.name, delimiter: profile.delimiter, hasHeader: profile.has_header,
            badgeColumn: profile.badge_column, timestampColumn: profile.timestamp_column, timeColumn: profile.time_column ?? "",
            timestampFormat: profile.timestamp_format, directionColumn: profile.direction_column ?? "",
            inValues: profile.in_values.join(", "), outValues: profile.out_values.join(", "),
          }
        : emptyDraft(),
    );
    setFormError(null);
    setOpen(true);
  }
  function submit() {
    if (!draft.code.trim() || !draft.name.trim() || !draft.badgeColumn.trim() || !draft.timestampColumn.trim() || !draft.timestampFormat.includes("%")) {
      setFormError(t("hr.clock.profiles.error.required"));
      return;
    }
    save.mutate();
  }

  const fields: FilterField<ClockProfile>[] = [
    { key: "code", kind: "text", getValue: (p) => p.code },
    { key: "name", kind: "text", getValue: (p) => p.name },
  ];
  const filters = useColumnFilters(fields);
  const rows = filters.apply((profiles.data ?? []).filter((p) => activeFilter === "all" || (activeFilter === "active") === p.active));
  const delimiterLabel = (value: string) => (value === "\t" ? t("hr.clock.profiles.tab") : value);
  const columns: ColumnDef<ClockProfile>[] = [
    {
      key: "code", header: t("hr.schedules.code"), defaultWidth: 110, sortValue: (p) => p.code, cell: (p) => <span className="font-medium">{p.code}</span>,
      filterCell: { type: "text", placeholder: t("hr.schedules.code"), value: filters.text.code ?? "", onChange: (v) => filters.setTextValue("code", v) },
    },
    {
      key: "name", header: t("hr.schedules.name"), defaultWidth: 200, sortValue: (p) => p.name, cell: (p) => p.name,
      filterCell: { type: "text", placeholder: t("hr.schedules.name"), value: filters.text.name ?? "", onChange: (v) => filters.setTextValue("name", v) },
    },
    { key: "delimiter", header: t("hr.clock.profiles.delimiter"), defaultWidth: 100, cell: (p) => <code>{delimiterLabel(p.delimiter)}</code> },
    {
      key: "columns", header: t("hr.clock.profiles.columns"), defaultWidth: 280,
      cell: (p) => <code className="text-xs">{[p.badge_column, p.timestamp_column, p.time_column, p.direction_column].filter(Boolean).join(" · ")}</code>,
    },
    { key: "format", header: t("hr.clock.profiles.format"), defaultWidth: 160, cell: (p) => <code className="text-xs">{p.timestamp_format}</code> },
    {
      key: "actions", header: "", defaultWidth: 200, alwaysVisible: true,
      cell: (p) =>
        canEdit ? (
          <div className="flex justify-end gap-2">
            <Button size="sm" variant="outline" onClick={() => openDialog(p)}>
              <Pencil className="h-3.5 w-3.5" />
              {t("common.edit")}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => toggleActive.mutate(p)}>
              {p.active ? t("hr.common.deactivate") : t("hr.common.activate")}
            </Button>
          </div>
        ) : null,
    },
  ];

  const text = (id: string, label: string, key: keyof ProfileDraft, placeholder = "") => (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input id={id} placeholder={placeholder} value={String(draft[key])} onChange={(e) => setDraft({ ...draft, [key]: e.target.value } as ProfileDraft)} />
    </div>
  );
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("hr.clock.profiles.title")}</CardTitle>
        <p className="text-sm text-muted-foreground">{t("hr.clock.profiles.help")}</p>
      </CardHeader>
      <CardContent>
        <HrListTable
          tableKey="hr.clock.profiles"
          columns={columns}
          rows={rows}
          rowKey={(p) => p.id}
          loading={profiles.isLoading}
          emptyIcon={<Fingerprint className="h-5 w-5" />}
          emptyTitle={t("hr.clock.profiles.empty.title")}
          emptyDescription={t("hr.clock.profiles.empty.description")}
          filtersActive={filters.isActive}
          onClearFilters={filters.reset}
          toolbar={
            <>
              <FilterTabs
                value={activeFilter}
                onChange={setActiveFilter}
                options={[
                  { value: "active", label: t("hr.common.activeOnly") },
                  { value: "inactive", label: t("hr.common.inactiveOnly") },
                  { value: "all", label: t("common.all") },
                ]}
              />
              {hasPermission("hr.import_clock") && (
                <Button size="sm" onClick={() => openDialog(null)}>
                  <Plus className="h-4 w-4" />
                  {t("hr.clock.profiles.new")}
                </Button>
              )}
            </>
          }
        />
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogContent className="max-w-2xl">
            <DialogHeader>
              <DialogTitle>{t(editing ? "hr.clock.profiles.editTitle" : "hr.clock.profiles.new")}</DialogTitle>
              <DialogDescription>{t("hr.clock.profiles.columnsHelp")}</DialogDescription>
            </DialogHeader>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="profile-code">{t("hr.schedules.code")}</Label>
                <Input id="profile-code" disabled={editing !== null} value={draft.code} onChange={(e) => setDraft({ ...draft, code: e.target.value })} />
              </div>
              {text("profile-name", t("hr.schedules.name"), "name")}
              <div className="space-y-1.5">
                <Label htmlFor="profile-delimiter">{t("hr.clock.profiles.delimiter")}</Label>
                <Select id="profile-delimiter" value={draft.delimiter} onChange={(e) => setDraft({ ...draft, delimiter: e.target.value })}>
                  {DELIMITERS.map((value) => (
                    <option key={value} value={value}>{delimiterLabel(value)}</option>
                  ))}
                </Select>
              </div>
              <label className="flex items-center gap-2 self-end pb-2 text-sm">
                <Checkbox checked={draft.hasHeader} onCheckedChange={(value) => setDraft({ ...draft, hasHeader: value === true })} />
                {t("hr.clock.profiles.hasHeader")}
              </label>
              {text("profile-badge", t("hr.clock.profiles.badgeColumn"), "badgeColumn")}
              {text("profile-timestamp", t("hr.clock.profiles.timestampColumn"), "timestampColumn")}
              {text("profile-time", t("hr.clock.profiles.timeColumn"), "timeColumn")}
              {text("profile-format", t("hr.clock.profiles.format"), "timestampFormat", "%d/%m/%Y %H:%M")}
              {text("profile-direction", t("hr.clock.profiles.directionColumn"), "directionColumn")}
              <span />
              {text("profile-in", t("hr.clock.profiles.inValues"), "inValues")}
              {text("profile-out", t("hr.clock.profiles.outValues"), "outValues")}
            </div>
            <p className="text-xs text-muted-foreground">{t("hr.clock.profiles.formatHelp")}</p>
            {formError && <p className="text-sm text-destructive">{formError}</p>}
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={() => setOpen(false)}>{t("common.cancel")}</Button>
              <Button onClick={submit} disabled={save.isPending}>{save.isPending ? t("common.saving") : t("common.save")}</Button>
            </div>
          </DialogContent>
        </Dialog>
      </CardContent>
    </Card>
  );
}
```

(`const { code: _code, ...changes }` — `noUnusedLocals` ignores destructured siblings of a rest element; if tsc still complains, build `changes` by listing the fields instead.)

- [ ] **Step 2: Staging review**

`frontend/src/features/hr/presence/ClockImportReview.tsx`:

```tsx
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileSearch, X } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../../lib/auth";
import { useI18n, type TranslationKey } from "../../../lib/i18n";
import { Button } from "../../../components/ui/button";
import { Badge } from "../../../components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "../../../components/ui/card";
import { Skeleton } from "../../../components/ui/skeleton";
import { FilterTabs } from "../../../components/patterns/FilterTabs";
import { useColumnFilters, type FilterField } from "../../../lib/useColumnFilters";
import type { ColumnDef } from "../../../lib/useTableColumns";
import { HrListTable } from "../HrListTable";
import {
  HR_KEYS, commitClockImport, discardClockImport, getClockImport,
  type ClockAnomaly, type ClockCommitResult, type ClockConflict, type ClockImportRow,
} from "../presenceApi";
import { errorText, formatDay, formatDuration } from "../presenceFormat";
import { PresenceStatusBadge } from "./PresenceStatusBadge";

export const ROW_ERROR_LABEL: Record<string, TranslationKey> = {
  MISSING_BADGE: "hr.clock.error.MISSING_BADGE",
  BAD_TIMESTAMP: "hr.clock.error.BAD_TIMESTAMP",
  MISSING_COLUMN: "hr.clock.error.MISSING_COLUMN",
  DUPLICATE_PUNCH: "hr.clock.error.DUPLICATE_PUNCH",
  UNKNOWN_BADGE: "hr.clock.error.UNKNOWN_BADGE",
  OUTSIDE_RANGE: "hr.clock.error.OUTSIDE_RANGE",
};
const ANOMALY_LABEL: Record<string, TranslationKey> = { MISSING_OUT: "hr.clock.anomaly.MISSING_OUT", MISSING_IN: "hr.clock.anomaly.MISSING_IN" };
const DIRECTION_LABEL: Record<ClockImportRow["direction"], TranslationKey> = { in: "hr.clock.direction.in", out: "hr.clock.direction.out", unknown: "hr.clock.direction.unknown" };
const label = (map: Record<string, TranslationKey>, code: string, t: (key: TranslationKey) => string) => (map[code] ? t(map[code]) : code);

function ImportResult({ result }: { result: ClockCommitResult }) {
  const { t } = useI18n();
  const conflictColumns: ColumnDef<ClockConflict>[] = [
    { key: "employee", header: t("hr.common.employee"), defaultWidth: 220, sortValue: (c) => c.employee_no, cell: (c) => `${c.employee_no} · ${c.full_name}` },
    { key: "date", header: t("hr.presence.date"), defaultWidth: 140, sortValue: (c) => c.work_date, cell: (c) => formatDay(c.work_date) },
    { key: "kept", header: t("hr.clock.result.kept"), defaultWidth: 140, cell: (c) => <PresenceStatusBadge status={c.kept_status} /> },
    {
      key: "clock", header: t("hr.clock.result.clock"), defaultWidth: 180,
      cell: (c) => <span className="inline-flex items-center gap-2"><PresenceStatusBadge status={c.clock_status} />{formatDuration(c.clock_worked_minutes)}</span>,
    },
  ];
  const anomalyColumns: ColumnDef<ClockAnomaly>[] = [
    { key: "employee", header: t("hr.common.employee"), defaultWidth: 220, sortValue: (a) => a.employee_no, cell: (a) => `${a.employee_no} · ${a.full_name}` },
    { key: "date", header: t("hr.presence.date"), defaultWidth: 140, sortValue: (a) => a.work_date, cell: (a) => formatDay(a.work_date) },
    { key: "codes", header: t("hr.clock.result.codes"), defaultWidth: 240, cell: (a) => a.codes.map((code) => label(ANOMALY_LABEL, code, t)).join(", ") },
  ];
  const stat = (value: number, key: TranslationKey) => (
    <div className="rounded-md border border-border p-2">
      <p className="text-lg font-semibold tabular-nums">{value}</p>
      <p className="text-xs text-muted-foreground">{t(key)}</p>
    </div>
  );
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {stat(result.days_written, "hr.clock.result.daysWritten")}
        {stat(result.duplicate_punches, "hr.clock.result.duplicates")}
        {stat(result.outside_range_punches, "hr.clock.result.outside")}
        {stat(result.unscheduled.length, "hr.clock.result.unscheduled")}
      </div>
      <div className="space-y-2">
        <h3 className="text-sm font-semibold">{t("hr.clock.result.conflicts")}</h3>
        <p className="text-xs text-muted-foreground">{t("hr.clock.result.conflictsHelp")}</p>
        <HrListTable tableKey="hr.clock.conflicts" columns={conflictColumns} rows={result.conflicts} rowKey={(c) => `${c.employee_id}|${c.work_date}`} loading={false}
          emptyIcon={<FileSearch className="h-5 w-5" />} emptyTitle={t("hr.clock.result.none")} emptyDescription="" />
      </div>
      <div className="space-y-2">
        <h3 className="text-sm font-semibold">{t("hr.clock.result.anomalies")}</h3>
        <HrListTable tableKey="hr.clock.anomalies" columns={anomalyColumns} rows={result.anomalies} rowKey={(a) => `${a.employee_id}|${a.work_date}`} loading={false}
          emptyIcon={<FileSearch className="h-5 w-5" />} emptyTitle={t("hr.clock.result.none")} emptyDescription="" />
      </div>
    </div>
  );
}

type RowFilter = "all" | "errors" | "valid";

export function ClockImportReview({ importId, onClose }: { importId: string; onClose: () => void }) {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const detail = useQuery({ queryKey: [...HR_KEYS.clockImports, importId], queryFn: () => getClockImport(token, importId) });
  const [rowFilter, setRowFilter] = useState<RowFilter>("all");
  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: HR_KEYS.clockImports });
    queryClient.invalidateQueries({ queryKey: HR_KEYS.presence });
  };
  const commit = useMutation({
    mutationFn: () => commitClockImport(token, importId),
    onSuccess: () => {
      refresh();
      toast.success(t("hr.clock.review.committed"));
    },
    onError: (error) => toast.error(errorText(error, t("hr.common.saveError"))),
  });
  const discard = useMutation({
    mutationFn: () => discardClockImport(token, importId),
    onSuccess: () => {
      refresh();
      toast.success(t("hr.clock.review.discarded"));
    },
    onError: (error) => toast.error(errorText(error, t("hr.common.saveError"))),
  });

  const fields: FilterField<ClockImportRow>[] = [
    { key: "line", kind: "range", getValue: (r) => r.line_no },
    { key: "badge", kind: "text", getValue: (r) => r.badge_no },
    { key: "employee", kind: "text", getValue: (r) => (r.employee_no ? `${r.employee_no} ${r.full_name}` : "") },
    { key: "error", kind: "text", getValue: (r) => (r.error_code ? label(ROW_ERROR_LABEL, r.error_code, t) : "") },
  ];
  const filters = useColumnFilters(fields);
  const rows = filters.apply((detail.data?.rows ?? []).filter((r) => rowFilter === "all" || (rowFilter === "errors") === (r.error_code !== null)));
  const columns: ColumnDef<ClockImportRow>[] = [
    {
      key: "line", header: t("hr.clock.review.line"), defaultWidth: 90, cellClassName: "tabular-nums", sortValue: (r) => r.line_no, cell: (r) => r.line_no,
      filterCell: { type: "range", min: filters.range.line?.min ?? "", max: filters.range.line?.max ?? "", onMinChange: (v) => filters.setRangeValue("line", "min", v), onMaxChange: (v) => filters.setRangeValue("line", "max", v) },
    },
    {
      key: "badge", header: t("hr.clock.review.badge"), defaultWidth: 110, sortValue: (r) => r.badge_no, cell: (r) => r.badge_no ?? "—",
      filterCell: { type: "text", placeholder: t("hr.clock.review.badge"), value: filters.text.badge ?? "", onChange: (v) => filters.setTextValue("badge", v) },
    },
    {
      key: "employee", header: t("hr.common.employee"), defaultWidth: 220, cell: (r) => (r.employee_no ? `${r.employee_no} · ${r.full_name}` : "—"),
      filterCell: { type: "text", placeholder: t("hr.common.employee"), value: filters.text.employee ?? "", onChange: (v) => filters.setTextValue("employee", v) },
    },
    { key: "punchedAt", header: t("hr.clock.review.punchedAt"), defaultWidth: 170, sortValue: (r) => r.punched_at, cell: (r) => (r.punched_at ? r.punched_at.replace("T", " ").slice(0, 16) : "—") },
    { key: "direction", header: t("hr.clock.review.direction"), defaultWidth: 100, cell: (r) => t(DIRECTION_LABEL[r.direction]) },
    {
      key: "error", header: t("hr.clock.review.error"), defaultWidth: 240,
      cell: (r) => (r.error_code ? <Badge variant="destructive">{label(ROW_ERROR_LABEL, r.error_code, t)}</Badge> : null),
      filterCell: { type: "text", placeholder: t("hr.clock.review.error"), value: filters.text.error ?? "", onChange: (v) => filters.setTextValue("error", v) },
    },
    { key: "raw", header: t("hr.clock.review.raw"), defaultWidth: 260, cell: (r) => <code className="text-xs">{r.raw}</code> },
  ];

  if (detail.isLoading || !detail.data) return <Skeleton className="h-64 w-full" />;
  const current = detail.data;
  const result = commit.data ?? current.result;
  const canAct = current.status === "staged" && hasPermission("hr.import_clock");
  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-3">
        <div className="space-y-1">
          <CardTitle>{t("hr.clock.review.title")} — {current.file_name}</CardTitle>
          <p className="text-sm text-muted-foreground">
            {current.profile_code} · {formatDay(current.date_from)} → {formatDay(current.date_to)} · {current.total_rows} {t("hr.clock.imports.rows")} · {current.error_rows} {t("hr.clock.imports.errors")}
          </p>
          <p className="text-xs text-muted-foreground">{t("hr.clock.review.help")}</p>
        </div>
        <div className="flex gap-2">
          {canAct && (
            <>
              <Button size="sm" onClick={() => commit.mutate()} disabled={commit.isPending || current.valid_rows === 0}>
                {commit.isPending ? t("hr.clock.review.committing") : t("hr.clock.review.commit")}
              </Button>
              <Button size="sm" variant="outline" onClick={() => discard.mutate()} disabled={discard.isPending}>{t("hr.clock.review.discard")}</Button>
            </>
          )}
          <Button size="sm" variant="ghost" aria-label={t("hr.clock.review.close")} onClick={onClose}><X className="h-4 w-4" /></Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-6">
        {result && (
          <div className="space-y-2">
            <h3 className="text-sm font-semibold">{t("hr.clock.result.title")}</h3>
            <ImportResult result={result} />
          </div>
        )}
        <HrListTable
          tableKey="hr.clock.importRows"
          columns={columns}
          rows={rows}
          rowKey={(r) => String(r.line_no)}
          loading={false}
          emptyIcon={<FileSearch className="h-5 w-5" />}
          emptyTitle={t("hr.clock.review.empty.title")}
          emptyDescription={t("hr.clock.review.empty.description")}
          filtersActive={filters.isActive}
          onClearFilters={filters.reset}
          toolbar={
            <FilterTabs
              value={rowFilter}
              onChange={setRowFilter}
              options={[
                { value: "all", label: t("hr.clock.review.filter.all") },
                { value: "errors", label: t("hr.clock.review.filter.errors") },
                { value: "valid", label: t("hr.clock.review.filter.valid") },
              ]}
            />
          }
        />
      </CardContent>
    </Card>
  );
}
```

- [ ] **Step 3: The page**

`frontend/src/features/hr/presence/ClockImportsPage.tsx`:

```tsx
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileUp, Upload } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../../lib/auth";
import { useI18n, type TranslationKey } from "../../../lib/i18n";
import { AppLoader } from "../../../components/patterns/AppLoader";
import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { Select } from "../../../components/ui/select";
import { Badge } from "../../../components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "../../../components/ui/card";
import { FilterTabs } from "../../../components/patterns/FilterTabs";
import { useColumnFilters, type FilterField } from "../../../lib/useColumnFilters";
import type { ColumnDef } from "../../../lib/useTableColumns";
import { HrListTable } from "../HrListTable";
import { useBooted } from "../HrTabsPage";
import { HR_KEYS, listClockImports, listClockProfiles, stageClockImport, type ClockImport, type ClockImportStatus } from "../presenceApi";
import { addDaysIso, errorText, formatDay, monthStartOf, todayIso } from "../presenceFormat";
import { ClockImportReview } from "./ClockImportReview";
import { ClockProfilesCard } from "./ClockProfilesCard";

const STATUS_LABEL: Record<ClockImportStatus, TranslationKey> = {
  staged: "hr.clock.status.staged", committed: "hr.clock.status.committed", discarded: "hr.clock.status.discarded",
};
const STATUS_VARIANT = { staged: "warning", committed: "success", discarded: "default" } as const;

export function ClockImportsPage() {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const profiles = useQuery({ queryKey: HR_KEYS.clockProfiles, queryFn: () => listClockProfiles(token) });
  const imports = useQuery({ queryKey: HR_KEYS.clockImports, queryFn: () => listClockImports(token) });
  const booted = useBooted(!profiles.isLoading && !imports.isLoading);
  const [profileId, setProfileId] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [dateFrom, setDateFrom] = useState(monthStartOf(todayIso()));
  const [dateTo, setDateTo] = useState(addDaysIso(todayIso(), -1));
  const [formError, setFormError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<"all" | ClockImportStatus>("all");

  const stage = useMutation({
    mutationFn: async () => stageClockImport(token, { profile_id: profileId, file_name: file!.name, content: await file!.text(), date_from: dateFrom, date_to: dateTo }),
    onSuccess: (staged) => {
      queryClient.invalidateQueries({ queryKey: HR_KEYS.clockImports });
      setSelected(staged.id);
      setFile(null);
      toast.success(t("hr.clock.upload.staged"));
    },
    onError: (error) => setFormError(errorText(error, t("hr.common.saveError"))),
  });
  function submit() {
    if (!profileId || !file || !dateFrom || !dateTo || dateTo < dateFrom) {
      setFormError(t("hr.clock.upload.error.required"));
      return;
    }
    setFormError(null);
    stage.mutate();
  }

  const fields: FilterField<ClockImport>[] = [
    { key: "file", kind: "text", getValue: (i) => i.file_name },
    { key: "profile", kind: "text", getValue: (i) => i.profile_code },
    { key: "errors", kind: "range", getValue: (i) => i.error_rows },
  ];
  const filters = useColumnFilters(fields);
  const rows = filters.apply((imports.data ?? []).filter((i) => statusFilter === "all" || i.status === statusFilter));
  const columns: ColumnDef<ClockImport>[] = [
    {
      key: "file", header: t("hr.clock.imports.file"), defaultWidth: 220, sortValue: (i) => i.file_name, cell: (i) => <span className="font-medium">{i.file_name}</span>,
      filterCell: { type: "text", placeholder: t("hr.clock.imports.file"), value: filters.text.file ?? "", onChange: (v) => filters.setTextValue("file", v) },
    },
    {
      key: "profile", header: t("hr.clock.imports.profile"), defaultWidth: 120, cell: (i) => i.profile_code,
      filterCell: { type: "text", placeholder: t("hr.clock.imports.profile"), value: filters.text.profile ?? "", onChange: (v) => filters.setTextValue("profile", v) },
    },
    { key: "period", header: t("hr.clock.imports.period"), defaultWidth: 220, sortValue: (i) => i.date_from, cell: (i) => `${formatDay(i.date_from)} → ${formatDay(i.date_to)}` },
    { key: "status", header: t("hr.presence.status"), defaultWidth: 120, cell: (i) => <Badge variant={STATUS_VARIANT[i.status]}>{t(STATUS_LABEL[i.status])}</Badge> },
    { key: "rows", header: t("hr.clock.imports.rows"), defaultWidth: 90, cellClassName: "tabular-nums", sortValue: (i) => i.total_rows, cell: (i) => i.total_rows },
    {
      key: "errors", header: t("hr.clock.imports.errors"), defaultWidth: 110, cellClassName: "tabular-nums", sortValue: (i) => i.error_rows, cell: (i) => i.error_rows,
      filterCell: { type: "range", min: filters.range.errors?.min ?? "", max: filters.range.errors?.max ?? "", onMinChange: (v) => filters.setRangeValue("errors", "min", v), onMaxChange: (v) => filters.setRangeValue("errors", "max", v) },
    },
    { key: "uploaded", header: t("hr.clock.imports.uploaded"), defaultWidth: 200, sortValue: (i) => i.uploaded_at, cell: (i) => `${formatDay(i.uploaded_at.slice(0, 10))} · ${i.uploaded_by_email ?? ""}` },
    {
      key: "actions", header: "", defaultWidth: 120, alwaysVisible: true,
      cell: (i) => <Button size="sm" variant={i.id === selected ? "default" : "outline"} onClick={() => setSelected(i.id)}>{t("hr.clock.imports.review")}</Button>,
    },
  ];

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">{t("hr.clock.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("hr.clock.subtitle")}</p>
      </div>
      {!booted && <AppLoader label={t("hr.clock.loading")} />}
      <div hidden={!booted} className="space-y-4">
        {hasPermission("hr.import_clock") && (
          <Card>
            <CardHeader>
              <CardTitle>{t("hr.clock.upload.title")}</CardTitle>
              <p className="text-sm text-muted-foreground">{t("hr.clock.upload.periodHelp")}</p>
            </CardHeader>
            <CardContent className="flex flex-wrap items-end gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="upload-profile">{t("hr.clock.upload.profile")}</Label>
                <Select id="upload-profile" value={profileId} onChange={(e) => setProfileId(e.target.value)}>
                  <option value="">—</option>
                  {(profiles.data ?? []).filter((p) => p.active).map((p) => (
                    <option key={p.id} value={p.id}>{p.code} · {p.name}</option>
                  ))}
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="upload-file">{t("hr.clock.upload.file")}</Label>
                <Input id="upload-file" type="file" accept=".csv,.txt,text/csv" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="upload-from">{t("hr.common.from")}</Label>
                <Input id="upload-from" type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="upload-to">{t("hr.common.to")}</Label>
                <Input id="upload-to" type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
              </div>
              <Button onClick={submit} disabled={stage.isPending}>
                <Upload className="h-4 w-4" />
                {stage.isPending ? t("hr.clock.upload.uploading") : t("hr.clock.upload.submit")}
              </Button>
              {formError && <p className="w-full text-sm text-destructive">{formError}</p>}
            </CardContent>
          </Card>
        )}
        {selected && <ClockImportReview key={selected} importId={selected} onClose={() => setSelected(null)} />}
        <Card>
          <CardHeader>
            <CardTitle>{t("hr.clock.imports.title")}</CardTitle>
          </CardHeader>
          <CardContent>
            <HrListTable
              tableKey="hr.clock.imports"
              columns={columns}
              rows={rows}
              rowKey={(i) => i.id}
              loading={imports.isLoading}
              emptyIcon={<FileUp className="h-5 w-5" />}
              emptyTitle={t("hr.clock.imports.empty.title")}
              emptyDescription={t("hr.clock.imports.empty.description")}
              filtersActive={filters.isActive}
              onClearFilters={filters.reset}
              toolbar={
                <FilterTabs
                  value={statusFilter}
                  onChange={setStatusFilter}
                  options={[
                    { value: "all", label: t("common.all") },
                    { value: "staged", label: t("hr.clock.status.staged") },
                    { value: "committed", label: t("hr.clock.status.committed") },
                    { value: "discarded", label: t("hr.clock.status.discarded") },
                  ]}
                />
              }
            />
          </CardContent>
        </Card>
        <ClockProfilesCard />
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Route, sidebar, strings**

`router.tsx`: import `ClockImportsPage` from `"../features/hr/presence/ClockImportsPage"`; add `{ path: "/hr/presence/imports", element: <ClockImportsPage /> },`.

`Sidebar.tsx`: add `Fingerprint` to the `lucide-react` import and, right after the `/hr/presence` item, `{ to: "/hr/presence/imports", labelKey: "nav.hrClockImports", icon: Fingerprint, permission: "hr.view_presence" },`.

`i18n.tsx` — `en`:

```ts
  "nav.hrClockImports": "Clock imports",
  "hr.clock.title": "Clock imports",
  "hr.clock.subtitle": "Upload the clock export, review it, then turn the punches into presence days.",
  "hr.clock.loading": "Loading imports…",
  "hr.clock.profiles.title": "Device profiles",
  "hr.clock.profiles.help": "How to read each clock's file: separator, columns and date/time format.",
  "hr.clock.profiles.new": "New profile",
  "hr.clock.profiles.editTitle": "Edit profile",
  "hr.clock.profiles.delimiter": "Separator",
  "hr.clock.profiles.tab": "Tab",
  "hr.clock.profiles.hasHeader": "First line holds the column names",
  "hr.clock.profiles.columns": "Columns",
  "hr.clock.profiles.badgeColumn": "Badge column",
  "hr.clock.profiles.timestampColumn": "Date/time column",
  "hr.clock.profiles.timeColumn": "Separate time column (optional)",
  "hr.clock.profiles.format": "Date/time format",
  "hr.clock.profiles.formatHelp": "Codes: %d day, %m month, %Y year, %H hour, %M minute, %S second. With a separate time column, write the format of \"date time\".",
  "hr.clock.profiles.directionColumn": "In/out column (optional)",
  "hr.clock.profiles.inValues": "Values meaning in (comma-separated)",
  "hr.clock.profiles.outValues": "Values meaning out (comma-separated)",
  "hr.clock.profiles.columnsHelp": "With a header line give the column names; without, their positions (1, 2, 3…).",
  "hr.clock.profiles.error.required": "Code, name, badge column, date/time column and a format with % codes are required.",
  "hr.clock.profiles.created": "Profile created",
  "hr.clock.profiles.updated": "Profile updated",
  "hr.clock.profiles.empty.title": "No device profile",
  "hr.clock.profiles.empty.description": "Create one per clock model before uploading its file.",
  "hr.clock.upload.title": "Upload a file",
  "hr.clock.upload.profile": "Device profile",
  "hr.clock.upload.file": "CSV file",
  "hr.clock.upload.periodHelp": "Give the days the file covers: a scheduled day in this period without any punch becomes an absence for the people in the file.",
  "hr.clock.upload.submit": "Upload for review",
  "hr.clock.upload.uploading": "Uploading…",
  "hr.clock.upload.staged": "File staged for review",
  "hr.clock.upload.error.required": "Choose a profile, a file and the days it covers (the end not before the start).",
  "hr.clock.imports.title": "Imports",
  "hr.clock.imports.file": "File",
  "hr.clock.imports.profile": "Profile",
  "hr.clock.imports.period": "Days covered",
  "hr.clock.imports.rows": "rows",
  "hr.clock.imports.errors": "errors",
  "hr.clock.imports.uploaded": "Uploaded",
  "hr.clock.imports.review": "Review",
  "hr.clock.imports.empty.title": "No import yet",
  "hr.clock.imports.empty.description": "Upload the first clock export above.",
  "hr.clock.status.staged": "To review",
  "hr.clock.status.committed": "Imported",
  "hr.clock.status.discarded": "Discarded",
  "hr.clock.review.title": "Review",
  "hr.clock.review.help": "Rows in error are not imported. Fix the file and upload it again if they matter.",
  "hr.clock.review.commit": "Import the punches",
  "hr.clock.review.committing": "Importing…",
  "hr.clock.review.discard": "Discard",
  "hr.clock.review.close": "Close",
  "hr.clock.review.committed": "Punches imported",
  "hr.clock.review.discarded": "Import discarded",
  "hr.clock.review.line": "Line",
  "hr.clock.review.badge": "Badge",
  "hr.clock.review.punchedAt": "Punch",
  "hr.clock.review.direction": "Direction",
  "hr.clock.review.error": "Problem",
  "hr.clock.review.raw": "Line as read",
  "hr.clock.review.filter.all": "All rows",
  "hr.clock.review.filter.errors": "Errors",
  "hr.clock.review.filter.valid": "Valid",
  "hr.clock.review.empty.title": "No row",
  "hr.clock.review.empty.description": "Nothing matches these filters.",
  "hr.clock.direction.in": "In",
  "hr.clock.direction.out": "Out",
  "hr.clock.direction.unknown": "Unknown",
  "hr.clock.error.MISSING_BADGE": "No badge",
  "hr.clock.error.BAD_TIMESTAMP": "Date/time not readable with this profile",
  "hr.clock.error.MISSING_COLUMN": "Line too short",
  "hr.clock.error.DUPLICATE_PUNCH": "Already imported or repeated",
  "hr.clock.error.UNKNOWN_BADGE": "Badge given to no employee",
  "hr.clock.error.OUTSIDE_RANGE": "Outside the days covered",
  "hr.clock.anomaly.MISSING_OUT": "No out-punch",
  "hr.clock.anomaly.MISSING_IN": "No in-punch",
  "hr.clock.result.title": "Import result",
  "hr.clock.result.daysWritten": "Days written",
  "hr.clock.result.duplicates": "Repeated punches ignored",
  "hr.clock.result.outside": "Punches outside the days covered",
  "hr.clock.result.unscheduled": "Punched days without schedule (not written)",
  "hr.clock.result.conflicts": "Kept as entered (the clock disagrees)",
  "hr.clock.result.conflictsHelp": "A day entered by a supervisor or taken as approved leave wins over the clock.",
  "hr.clock.result.kept": "Kept",
  "hr.clock.result.clock": "Clock says",
  "hr.clock.result.anomalies": "Days to check",
  "hr.clock.result.codes": "What is wrong",
  "hr.clock.result.none": "None",
```

`fr`:

```ts
  "nav.hrClockImports": "Imports pointeuse",
  "hr.clock.title": "Imports de la pointeuse",
  "hr.clock.subtitle": "Chargez l'export de la pointeuse, vérifiez-le, puis transformez les pointages en jours de présence.",
  "hr.clock.loading": "Chargement des imports…",
  "hr.clock.profiles.title": "Profils de pointeuse",
  "hr.clock.profiles.help": "Comment lire le fichier de chaque pointeuse : séparateur, colonnes et format date/heure.",
  "hr.clock.profiles.new": "Nouveau profil",
  "hr.clock.profiles.editTitle": "Modifier le profil",
  "hr.clock.profiles.delimiter": "Séparateur",
  "hr.clock.profiles.tab": "Tabulation",
  "hr.clock.profiles.hasHeader": "La première ligne contient les noms de colonnes",
  "hr.clock.profiles.columns": "Colonnes",
  "hr.clock.profiles.badgeColumn": "Colonne badge",
  "hr.clock.profiles.timestampColumn": "Colonne date/heure",
  "hr.clock.profiles.timeColumn": "Colonne heure séparée (facultatif)",
  "hr.clock.profiles.format": "Format date/heure",
  "hr.clock.profiles.formatHelp": "Codes : %d jour, %m mois, %Y année, %H heure, %M minute, %S seconde. Avec une colonne heure séparée, indiquez le format de « date heure ».",
  "hr.clock.profiles.directionColumn": "Colonne entrée/sortie (facultatif)",
  "hr.clock.profiles.inValues": "Valeurs signifiant entrée (séparées par des virgules)",
  "hr.clock.profiles.outValues": "Valeurs signifiant sortie (séparées par des virgules)",
  "hr.clock.profiles.columnsHelp": "Avec une ligne d'en-tête indiquez les noms des colonnes ; sans, leurs positions (1, 2, 3…).",
  "hr.clock.profiles.error.required": "Le code, le nom, la colonne badge, la colonne date/heure et un format avec des codes % sont obligatoires.",
  "hr.clock.profiles.created": "Profil créé",
  "hr.clock.profiles.updated": "Profil modifié",
  "hr.clock.profiles.empty.title": "Aucun profil",
  "hr.clock.profiles.empty.description": "Créez-en un par modèle de pointeuse avant de charger son fichier.",
  "hr.clock.upload.title": "Charger un fichier",
  "hr.clock.upload.profile": "Profil de pointeuse",
  "hr.clock.upload.file": "Fichier CSV",
  "hr.clock.upload.periodHelp": "Indiquez les jours couverts par le fichier : un jour prévu de cette période sans aucun pointage devient une absence pour les personnes du fichier.",
  "hr.clock.upload.submit": "Charger pour vérification",
  "hr.clock.upload.uploading": "Chargement…",
  "hr.clock.upload.staged": "Fichier en attente de vérification",
  "hr.clock.upload.error.required": "Choisissez un profil, un fichier et les jours couverts (la fin pas avant le début).",
  "hr.clock.imports.title": "Imports",
  "hr.clock.imports.file": "Fichier",
  "hr.clock.imports.profile": "Profil",
  "hr.clock.imports.period": "Jours couverts",
  "hr.clock.imports.rows": "lignes",
  "hr.clock.imports.errors": "erreurs",
  "hr.clock.imports.uploaded": "Chargé le",
  "hr.clock.imports.review": "Vérifier",
  "hr.clock.imports.empty.title": "Aucun import",
  "hr.clock.imports.empty.description": "Chargez le premier export de pointeuse ci-dessus.",
  "hr.clock.status.staged": "À vérifier",
  "hr.clock.status.committed": "Importé",
  "hr.clock.status.discarded": "Écarté",
  "hr.clock.review.title": "Vérification",
  "hr.clock.review.help": "Les lignes en erreur ne sont pas importées. Corrigez le fichier et rechargez-le si elles comptent.",
  "hr.clock.review.commit": "Importer les pointages",
  "hr.clock.review.committing": "Import…",
  "hr.clock.review.discard": "Écarter",
  "hr.clock.review.close": "Fermer",
  "hr.clock.review.committed": "Pointages importés",
  "hr.clock.review.discarded": "Import écarté",
  "hr.clock.review.line": "Ligne",
  "hr.clock.review.badge": "Badge",
  "hr.clock.review.punchedAt": "Pointage",
  "hr.clock.review.direction": "Sens",
  "hr.clock.review.error": "Problème",
  "hr.clock.review.raw": "Ligne lue",
  "hr.clock.review.filter.all": "Toutes les lignes",
  "hr.clock.review.filter.errors": "Erreurs",
  "hr.clock.review.filter.valid": "Valides",
  "hr.clock.review.empty.title": "Aucune ligne",
  "hr.clock.review.empty.description": "Rien ne correspond à ces filtres.",
  "hr.clock.direction.in": "Entrée",
  "hr.clock.direction.out": "Sortie",
  "hr.clock.direction.unknown": "Inconnu",
  "hr.clock.error.MISSING_BADGE": "Badge manquant",
  "hr.clock.error.BAD_TIMESTAMP": "Date/heure illisible avec ce profil",
  "hr.clock.error.MISSING_COLUMN": "Ligne incomplète",
  "hr.clock.error.DUPLICATE_PUNCH": "Déjà importé ou en double",
  "hr.clock.error.UNKNOWN_BADGE": "Badge attribué à aucun employé",
  "hr.clock.error.OUTSIDE_RANGE": "Hors des jours couverts",
  "hr.clock.anomaly.MISSING_OUT": "Sortie non pointée",
  "hr.clock.anomaly.MISSING_IN": "Entrée non pointée",
  "hr.clock.result.title": "Résultat de l'import",
  "hr.clock.result.daysWritten": "Jours enregistrés",
  "hr.clock.result.duplicates": "Pointages répétés ignorés",
  "hr.clock.result.outside": "Pointages hors des jours couverts",
  "hr.clock.result.unscheduled": "Jours pointés sans horaire (non enregistrés)",
  "hr.clock.result.conflicts": "Conservés tels que saisis (la pointeuse diffère)",
  "hr.clock.result.conflictsHelp": "Un jour saisi par un chef d'équipe ou pris en congé approuvé l'emporte sur la pointeuse.",
  "hr.clock.result.kept": "Conservé",
  "hr.clock.result.clock": "Selon la pointeuse",
  "hr.clock.result.anomalies": "Jours à vérifier",
  "hr.clock.result.codes": "Anomalie",
  "hr.clock.result.none": "Aucun",
```

- [ ] **Step 5: Type-check**

Run (from `frontend/`): `npx tsc -b --force`
Expected: exit 0.

- [ ] **Step 6: Browser check**

Grant the demo user `hr.import_clock` if missing. On `/hr/presence/imports`: create a profile (`;`, header, `Badge`, `DateHeure`, `%d/%m/%Y %H:%M`, `Etat`, in `Entrée`, out `Sortie`); upload a 4-line CSV with one unknown badge (the seed's `backend/scripts/data/hr_clock_sample_2026-08.csv` once Task 14 has run); the review opens with 1 error row; "Errors" filter shows it; Import → result block with days written; the import row turns "Imported"; the day grid of `/hr/presence` shows "Source: Clock" for those days.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/features/hr/presence/ClockImportsPage.tsx frontend/src/features/hr/presence/ClockProfilesCard.tsx frontend/src/features/hr/presence/ClockImportReview.tsx frontend/src/routes/router.tsx frontend/src/routes/Sidebar.tsx frontend/src/lib/i18n.tsx
git commit -m "feat(hr): clock imports screen - device profiles, staging review, commit result

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 13: `/hr/leave` — leave types, requests with approval, balances

**Files:**
- Create: `frontend/src/features/hr/leave/LeavePage.tsx`, `LeaveTypesTab.tsx`, `LeaveRequestsTab.tsx`, `LeaveBalancesTab.tsx`
- Modify: `frontend/src/routes/router.tsx`, `frontend/src/routes/Sidebar.tsx`, `frontend/src/lib/i18n.tsx`

**Interfaces:**
- Consumes (Task 10): `HR_KEYS`, `listLeaveTypes`, `createLeaveType`, `updateLeaveType`, `fetchLeaveRequests`, `submitLeaveRequest`, `editLeaveRequest`, `decideLeaveRequest`, `listLeaveBalances`, `adjustLeaveBalance`, types `LeaveType`, `LeaveTypeInput`, `LeaveRecord`, `LeaveRecordInput`, `LeaveBalance`, `LeaveRequestStatus`; `listEmployees` (`../api`); `HrListTable`, `HrTabsPage`, `useTabParam`, `useBooted`; `presenceFormat` helpers.
- Produces: `LeavePage` (route `/hr/leave`, tabs `requests | balances | types`). This is the only place old (no-`leave_type_id`) `hr.leave_requests` rows are surfaced (`legacy_leave_type`); they show a "give it a type" affordance that calls `editLeaveRequest`.

- [ ] **Step 1: Leave types tab**

`frontend/src/features/hr/leave/LeaveTypesTab.tsx`:

```tsx
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarClock, Pencil, Plus } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { Select } from "../../../components/ui/select";
import { Checkbox } from "../../../components/ui/checkbox";
import { Badge } from "../../../components/ui/badge";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../../components/ui/dialog";
import { FilterTabs } from "../../../components/patterns/FilterTabs";
import { useColumnFilters, type FilterField } from "../../../lib/useColumnFilters";
import type { ColumnDef } from "../../../lib/useTableColumns";
import { HrListTable } from "../HrListTable";
import { HR_KEYS, createLeaveType, listLeaveTypes, updateLeaveType, type LeaveType } from "../presenceApi";
import { errorText } from "../presenceFormat";

interface TypeDraft {
  code: string; nameEn: string; nameFr: string; paid: boolean; accrual: string; maxCarryOver: string;
  countsDays: "calendar" | "working"; requiresDocument: boolean; presenceStatus: "leave" | "sick"; confirmed: boolean;
}
const emptyDraft = (): TypeDraft => ({
  code: "", nameEn: "", nameFr: "", paid: true, accrual: "0", maxCarryOver: "", countsDays: "calendar",
  requiresDocument: false, presenceStatus: "leave", confirmed: false,
});

export function LeaveTypesTab() {
  const { session, hasPermission } = useAuth();
  const { language, t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const types = useQuery({ queryKey: HR_KEYS.leaveTypes, queryFn: () => listLeaveTypes(token) });
  const [activeFilter, setActiveFilter] = useState<"active" | "inactive" | "all">("active");
  const [editing, setEditing] = useState<LeaveType | null>(null);
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<TypeDraft>(emptyDraft);
  const [formError, setFormError] = useState<string | null>(null);
  const canEdit = hasPermission("hr.admin_leave");
  const nameOf = (t2: LeaveType) => (language === "fr" ? t2.name_fr : t2.name_en);

  const save = useMutation({
    mutationFn: () => {
      const accrual = Number(draft.accrual || 0);
      const cap = draft.maxCarryOver.trim() === "" ? null : Number(draft.maxCarryOver);
      const body = {
        name_en: draft.nameEn.trim(), name_fr: draft.nameFr.trim(), paid: draft.paid, accrual_days_per_month: accrual,
        max_carry_over: cap, counts_days: draft.countsDays, requires_document: draft.requiresDocument,
        presence_status: draft.presenceStatus, confirmed: draft.confirmed,
      };
      return editing
        ? updateLeaveType(token, editing.id, { ...body, clear_max_carry_over: cap === null })
        : createLeaveType(token, { code: draft.code.trim(), ...body });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: HR_KEYS.leaveTypes });
      setOpen(false);
      toast.success(t(editing ? "hr.leaveTypes.updated" : "hr.leaveTypes.created"));
    },
    onError: (error) => setFormError(errorText(error, t("hr.common.saveError"))),
  });
  const toggleActive = useMutation({
    mutationFn: (type: LeaveType) => updateLeaveType(token, type.id, { active: !type.active }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: HR_KEYS.leaveTypes }),
    onError: (error) => toast.error(errorText(error, t("hr.common.saveError"))),
  });

  function openDialog(type: LeaveType | null) {
    setEditing(type);
    setDraft(
      type
        ? {
            code: type.code, nameEn: type.name_en, nameFr: type.name_fr, paid: type.paid, accrual: String(type.accrual_days_per_month),
            maxCarryOver: type.max_carry_over === null ? "" : String(type.max_carry_over), countsDays: type.counts_days,
            requiresDocument: type.requires_document, presenceStatus: type.presence_status, confirmed: type.confirmed,
          }
        : emptyDraft(),
    );
    setFormError(null);
    setOpen(true);
  }
  function submit() {
    const accrual = Number(draft.accrual || 0);
    const cap = draft.maxCarryOver.trim() === "" ? 0 : Number(draft.maxCarryOver);
    if (!draft.nameEn.trim() || !draft.nameFr.trim() || (!editing && !draft.code.trim()) || Number.isNaN(accrual) || accrual < 0 || Number.isNaN(cap) || cap < 0) {
      setFormError(t("hr.leaveTypes.error.required"));
      return;
    }
    save.mutate();
  }

  const fields: FilterField<LeaveType>[] = [
    { key: "code", kind: "text", getValue: (r) => r.code },
    { key: "name", kind: "text", getValue: nameOf },
  ];
  const filters = useColumnFilters(fields);
  const rows = filters.apply((types.data ?? []).filter((r) => activeFilter === "all" || (activeFilter === "active") === r.active));

  const columns: ColumnDef<LeaveType>[] = [
    {
      key: "code", header: t("hr.schedules.code"), defaultWidth: 130, sortValue: (r) => r.code, cell: (r) => <span className="font-medium">{r.code}</span>,
      filterCell: { type: "text", placeholder: t("hr.schedules.code"), value: filters.text.code ?? "", onChange: (v) => filters.setTextValue("code", v) },
    },
    {
      key: "name", header: t("hr.schedules.name"), defaultWidth: 220, sortValue: nameOf, cell: nameOf,
      filterCell: { type: "text", placeholder: t("hr.schedules.name"), value: filters.text.name ?? "", onChange: (v) => filters.setTextValue("name", v) },
    },
    { key: "paid", header: t("hr.holidays.paid"), defaultWidth: 90, cell: (r) => (r.paid ? t("common.yes") : t("common.no")) },
    { key: "accrual", header: t("hr.leaveTypes.accrual"), defaultWidth: 150, cellClassName: "tabular-nums", sortValue: (r) => r.accrual_days_per_month, cell: (r) => r.accrual_days_per_month },
    { key: "cap", header: t("hr.leaveTypes.cap"), defaultWidth: 130, cellClassName: "tabular-nums", cell: (r) => r.max_carry_over ?? t("hr.leaveTypes.noCap") },
    { key: "counts", header: t("hr.leaveTypes.counts"), defaultWidth: 130, cell: (r) => t(r.counts_days === "working" ? "hr.leaveTypes.counts.working" : "hr.leaveTypes.counts.calendar") },
    { key: "document", header: t("hr.leaveTypes.document"), defaultWidth: 100, cell: (r) => (r.requires_document ? t("common.yes") : t("common.no")) },
    { key: "check", header: t("hr.holidays.status"), defaultWidth: 130, cell: (r) => <Badge variant={r.confirmed ? "success" : "warning"}>{t(r.confirmed ? "hr.common.confirmed" : "hr.common.toConfirm")}</Badge> },
    {
      key: "actions", header: "", defaultWidth: 200, alwaysVisible: true,
      cell: (r) =>
        canEdit ? (
          <div className="flex justify-end gap-2">
            <Button size="sm" variant="outline" onClick={() => openDialog(r)}>
              <Pencil className="h-3.5 w-3.5" />
              {t("common.edit")}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => toggleActive.mutate(r)}>{r.active ? t("hr.common.deactivate") : t("hr.common.activate")}</Button>
          </div>
        ) : null,
    },
  ];

  return (
    <>
      <HrListTable
        tableKey="hr.leaveTypes"
        columns={columns}
        rows={rows}
        rowKey={(r) => r.id}
        loading={types.isLoading}
        emptyIcon={<CalendarClock className="h-5 w-5" />}
        emptyTitle={t("hr.leaveTypes.empty.title")}
        emptyDescription={t("hr.leaveTypes.empty.description")}
        filtersActive={filters.isActive}
        onClearFilters={filters.reset}
        toolbar={
          <>
            <FilterTabs
              value={activeFilter}
              onChange={setActiveFilter}
              options={[
                { value: "active", label: t("hr.common.activeOnly") },
                { value: "inactive", label: t("hr.common.inactiveOnly") },
                { value: "all", label: t("common.all") },
              ]}
            />
            {hasPermission("hr.manage_leave") && (
              <Button size="sm" onClick={() => openDialog(null)}>
                <Plus className="h-4 w-4" />
                {t("hr.leaveTypes.new")}
              </Button>
            )}
          </>
        }
      />
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-xl">
          <DialogHeader>
            <DialogTitle>{t(editing ? "hr.leaveTypes.editTitle" : "hr.leaveTypes.new")}</DialogTitle>
            <DialogDescription>{t("hr.leaveTypes.dialogHelp")}</DialogDescription>
          </DialogHeader>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="type-code">{t("hr.schedules.code")}</Label>
              <Input id="type-code" disabled={editing !== null} value={draft.code} onChange={(e) => setDraft({ ...draft, code: e.target.value })} />
            </div>
            <div />
            <div className="space-y-1.5">
              <Label htmlFor="type-name-en">{t("hr.leaveTypes.nameEn")}</Label>
              <Input id="type-name-en" value={draft.nameEn} onChange={(e) => setDraft({ ...draft, nameEn: e.target.value })} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="type-name-fr">{t("hr.leaveTypes.nameFr")}</Label>
              <Input id="type-name-fr" value={draft.nameFr} onChange={(e) => setDraft({ ...draft, nameFr: e.target.value })} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="type-accrual">{t("hr.leaveTypes.accrual")}</Label>
              <Input id="type-accrual" type="number" min={0} step="0.01" value={draft.accrual} onChange={(e) => setDraft({ ...draft, accrual: e.target.value })} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="type-cap">{t("hr.leaveTypes.cap")}</Label>
              <Input id="type-cap" type="number" min={0} step="0.01" placeholder={t("hr.leaveTypes.noCap")} value={draft.maxCarryOver} onChange={(e) => setDraft({ ...draft, maxCarryOver: e.target.value })} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="type-counts">{t("hr.leaveTypes.counts")}</Label>
              <Select id="type-counts" value={draft.countsDays} onChange={(e) => setDraft({ ...draft, countsDays: e.target.value as TypeDraft["countsDays"] })}>
                <option value="calendar">{t("hr.leaveTypes.counts.calendar")}</option>
                <option value="working">{t("hr.leaveTypes.counts.working")}</option>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="type-presence">{t("hr.leaveTypes.presenceStatus")}</Label>
              <Select id="type-presence" value={draft.presenceStatus} onChange={(e) => setDraft({ ...draft, presenceStatus: e.target.value as TypeDraft["presenceStatus"] })}>
                <option value="leave">{t("hr.presenceStatus.leave")}</option>
                <option value="sick">{t("hr.presenceStatus.sick")}</option>
              </Select>
            </div>
          </div>
          <label className="flex items-center gap-2 text-sm">
            <Checkbox checked={draft.paid} onCheckedChange={(value) => setDraft({ ...draft, paid: value === true })} />
            {t("hr.leaveTypes.paidLabel")}
          </label>
          <label className="flex items-center gap-2 text-sm">
            <Checkbox checked={draft.requiresDocument} onCheckedChange={(value) => setDraft({ ...draft, requiresDocument: value === true })} />
            {t("hr.leaveTypes.requiresDocumentLabel")}
          </label>
          <label className="flex items-center gap-2 text-sm">
            <Checkbox checked={draft.confirmed} onCheckedChange={(value) => setDraft({ ...draft, confirmed: value === true })} />
            {t("hr.common.confirmed")}
          </label>
          {formError && <p className="text-sm text-destructive">{formError}</p>}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setOpen(false)}>{t("common.cancel")}</Button>
            <Button onClick={submit} disabled={save.isPending}>{save.isPending ? t("common.saving") : t("common.save")}</Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
```

- [ ] **Step 2: Leave requests tab**

`frontend/src/features/hr/leave/LeaveRequestsTab.tsx`:

```tsx
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarDays, Check, FileWarning, Pencil, Plus, X } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { Select } from "../../../components/ui/select";
import { Checkbox } from "../../../components/ui/checkbox";
import { Badge } from "../../../components/ui/badge";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../../components/ui/dialog";
import { FilterTabs } from "../../../components/patterns/FilterTabs";
import { useColumnFilters, type FilterField } from "../../../lib/useColumnFilters";
import type { ColumnDef } from "../../../lib/useTableColumns";
import type { Employee } from "../api";
import { HrListTable } from "../HrListTable";
import {
  HR_KEYS, decideLeaveRequest, editLeaveRequest, listLeaveTypes, submitLeaveRequest, fetchLeaveRequests,
  type LeaveRecord, type LeaveRequestStatus, type LeaveType,
} from "../presenceApi";
import { employeeLabel, errorText, formatDay, todayIso } from "../presenceFormat";

interface RequestDraft { employeeId: string; leaveTypeId: string; startDate: string; endDate: string; halfDay: boolean; reason: string; documentRef: string }
const emptyDraft = (): RequestDraft => ({ employeeId: "", leaveTypeId: "", startDate: todayIso(), endDate: todayIso(), halfDay: false, reason: "", documentRef: "" });

const STATUS_VARIANT = { pending: "warning", approved: "success", rejected: "destructive", cancelled: "default" } as const;

export function LeaveRequestsTab({ employees }: { employees: Employee[] }) {
  const { session, hasPermission } = useAuth();
  const { language: uiLanguage, t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const requests = useQuery({ queryKey: HR_KEYS.leaveRequests, queryFn: () => fetchLeaveRequests(token) });
  const types = useQuery({ queryKey: HR_KEYS.leaveTypes, queryFn: () => listLeaveTypes(token) });
  const [statusFilter, setStatusFilter] = useState<"all" | LeaveRequestStatus>("pending");
  const [editing, setEditing] = useState<LeaveRecord | null>(null);
  const [assigningType, setAssigningType] = useState<LeaveRecord | null>(null);
  const [pickedType, setPickedType] = useState("");
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<RequestDraft>(emptyDraft);
  const [formError, setFormError] = useState<string | null>(null);
  const canManage = hasPermission("hr.manage_leave");
  const canAdmin = hasPermission("hr.admin_leave");
  const typeName = (r: LeaveRecord) => (r.leave_type_id ? (uiLanguage === "fr" ? r.leave_type_name_fr : r.leave_type_name_en) ?? r.leave_type_code : `${r.legacy_leave_type} (${t("hr.leaveRequests.legacy")})`);

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: HR_KEYS.leaveRequests });
    queryClient.invalidateQueries({ queryKey: HR_KEYS.leaveBalances });
    queryClient.invalidateQueries({ queryKey: HR_KEYS.presence });
  };
  const save = useMutation({
    mutationFn: () => {
      const body = {
        leave_type_id: draft.leaveTypeId, start_date: draft.startDate, end_date: draft.halfDay ? draft.startDate : draft.endDate,
        half_day: draft.halfDay, reason: draft.reason.trim() || null, document_ref: draft.documentRef.trim() || null,
      };
      return editing ? editLeaveRequest(token, editing.id, body) : submitLeaveRequest(token, { ...body, employee_id: draft.employeeId });
    },
    onSuccess: () => {
      refresh();
      setOpen(false);
      toast.success(t(editing ? "hr.leaveRequests.updated" : "hr.leaveRequests.created"));
    },
    onError: (error) => setFormError(errorText(error, t("hr.common.saveError"))),
  });
  const decide = useMutation({
    mutationFn: (input: { id: string; decision: "approve" | "reject" | "cancel" }) => decideLeaveRequest(token, input.id, input.decision),
    onSuccess: (_, input) => {
      refresh();
      toast.success(t(`hr.leaveRequests.decision.${input.decision}` as const));
    },
    onError: (error) => toast.error(errorText(error, t("hr.common.saveError"))),
  });
  const assignType = useMutation({
    mutationFn: () => editLeaveRequest(token, assigningType!.id, { leave_type_id: pickedType, start_date: assigningType!.start_date, end_date: assigningType!.end_date, half_day: false, reason: assigningType!.reason, document_ref: assigningType!.document_ref }),
    onSuccess: () => {
      refresh();
      setAssigningType(null);
      toast.success(t("hr.leaveRequests.typeAssigned"));
    },
    onError: (error) => toast.error(errorText(error, t("hr.common.saveError"))),
  });

  function openDialog(request: LeaveRecord | null) {
    setEditing(request);
    setDraft(
      request
        ? {
            employeeId: request.employee_id, leaveTypeId: request.leave_type_id ?? "", startDate: request.start_date, endDate: request.end_date,
            halfDay: request.half_day, reason: request.reason ?? "", documentRef: request.document_ref ?? "",
          }
        : emptyDraft(),
    );
    setFormError(null);
    setOpen(true);
  }
  function submit() {
    if (!draft.employeeId || !draft.leaveTypeId || !draft.startDate || (!draft.halfDay && draft.endDate < draft.startDate)) {
      setFormError(t("hr.leaveRequests.error.required"));
      return;
    }
    save.mutate();
  }

  const fields: FilterField<LeaveRecord>[] = [
    { key: "employee", kind: "text", getValue: (r) => `${r.employee_no} ${r.full_name}` },
    { key: "type", kind: "text", getValue: typeName },
  ];
  const filters = useColumnFilters(fields);
  const rows = filters.apply((requests.data ?? []).filter((r) => statusFilter === "all" || r.status === statusFilter));
  const activeTypes = (types.data ?? []).filter((r: LeaveType) => r.active || r.id === draft.leaveTypeId);

  const columns: ColumnDef<LeaveRecord>[] = [
    {
      key: "employee", header: t("hr.common.employee"), defaultWidth: 220, sortValue: (r) => r.employee_no, cell: (r) => <span className="font-medium">{r.employee_no} · {r.full_name}</span>,
      filterCell: { type: "text", placeholder: t("hr.common.employee"), value: filters.text.employee ?? "", onChange: (v) => filters.setTextValue("employee", v) },
    },
    {
      key: "type", header: t("hr.leaveRequests.type"), defaultWidth: 180,
      cell: (r) =>
        r.leave_type_id ? typeName(r) : (
          <span className="inline-flex items-center gap-2">
            <Badge variant="warning">{typeName(r)}</Badge>
            {canAdmin && (
              <Button size="sm" variant="outline" onClick={() => { setAssigningType(r); setPickedType(""); }}>
                {t("hr.leaveRequests.assignType")}
              </Button>
            )}
          </span>
        ),
      filterCell: { type: "text", placeholder: t("hr.leaveRequests.type"), value: filters.text.type ?? "", onChange: (v) => filters.setTextValue("type", v) },
    },
    { key: "dates", header: t("hr.leaveRequests.dates"), defaultWidth: 220, sortValue: (r) => r.start_date, cell: (r) => (r.half_day ? `${formatDay(r.start_date)} (${t("hr.leaveRequests.halfDayShort")})` : `${formatDay(r.start_date)} → ${formatDay(r.end_date)}`) },
    { key: "days", header: t("hr.leaveRequests.days"), defaultWidth: 90, cellClassName: "tabular-nums", cell: (r) => r.days ?? "—" },
    { key: "status", header: t("hr.presence.status"), defaultWidth: 130, cell: (r) => <Badge variant={STATUS_VARIANT[r.status]}>{t(`status.${r.status}` as const)}</Badge> },
    {
      key: "document", header: t("hr.leaveTypes.document"), defaultWidth: 100,
      cell: (r) => (r.document_ref ? <Check className="h-4 w-4 text-success" /> : <FileWarning className="h-4 w-4 text-muted-foreground" />),
    },
    {
      key: "actions", header: "", defaultWidth: 260, alwaysVisible: true,
      cell: (r) => (
        <div className="flex justify-end gap-2">
          {canAdmin && (r.status === "pending" || r.status === "approved") && (
            <Button size="sm" variant="outline" onClick={() => openDialog(r)}>
              <Pencil className="h-3.5 w-3.5" />
              {t("common.edit")}
            </Button>
          )}
          {canManage && r.status === "pending" && (
            <>
              <Button size="sm" onClick={() => decide.mutate({ id: r.id, decision: "approve" })}>
                <Check className="h-3.5 w-3.5" />
                {t("hr.leaveRequests.approve")}
              </Button>
              <Button size="sm" variant="outline" onClick={() => decide.mutate({ id: r.id, decision: "reject" })}>
                <X className="h-3.5 w-3.5" />
                {t("hr.leaveRequests.reject")}
              </Button>
            </>
          )}
          {canManage && r.status === "approved" && (
            <Button size="sm" variant="ghost" onClick={() => decide.mutate({ id: r.id, decision: "cancel" })}>{t("hr.leaveRequests.cancel")}</Button>
          )}
        </div>
      ),
    },
  ];

  return (
    <>
      <HrListTable
        tableKey="hr.leaveRequests"
        columns={columns}
        rows={rows}
        rowKey={(r) => r.id}
        loading={requests.isLoading}
        emptyIcon={<CalendarDays className="h-5 w-5" />}
        emptyTitle={t("hr.leaveRequests.empty.title")}
        emptyDescription={t("hr.leaveRequests.empty.description")}
        filtersActive={filters.isActive}
        onClearFilters={filters.reset}
        toolbar={
          <>
            <FilterTabs
              value={statusFilter}
              onChange={setStatusFilter}
              options={[
                { value: "pending", label: t("status.pending") },
                { value: "approved", label: t("status.approved") },
                { value: "rejected", label: t("status.rejected") },
                { value: "cancelled", label: t("status.cancelled") },
                { value: "all", label: t("common.all") },
              ]}
            />
            {canManage && (
              <Button size="sm" onClick={() => openDialog(null)}>
                <Plus className="h-4 w-4" />
                {t("hr.leaveRequests.new")}
              </Button>
            )}
          </>
        }
      />
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t(editing ? "hr.leaveRequests.editTitle" : "hr.leaveRequests.new")}</DialogTitle>
            <DialogDescription>{t("hr.leaveRequests.dialogHelp")}</DialogDescription>
          </DialogHeader>
          {!editing && (
            <div className="space-y-1.5">
              <Label htmlFor="request-employee">{t("hr.common.employee")}</Label>
              <Select id="request-employee" value={draft.employeeId} onChange={(e) => setDraft({ ...draft, employeeId: e.target.value })}>
                <option value="">—</option>
                {employees.map((employee) => (
                  <option key={employee.id} value={employee.id}>{employeeLabel(employee)}</option>
                ))}
              </Select>
            </div>
          )}
          <div className="space-y-1.5">
            <Label htmlFor="request-type">{t("hr.leaveRequests.type")}</Label>
            <Select id="request-type" value={draft.leaveTypeId} onChange={(e) => setDraft({ ...draft, leaveTypeId: e.target.value })}>
              <option value="">—</option>
              {activeTypes.map((leaveType) => (
                <option key={leaveType.id} value={leaveType.id}>{uiLanguage === "fr" ? leaveType.name_fr : leaveType.name_en}</option>
              ))}
            </Select>
          </div>
          <label className="flex items-center gap-2 text-sm">
            <Checkbox checked={draft.halfDay} onCheckedChange={(value) => setDraft({ ...draft, halfDay: value === true })} />
            {t("hr.leaveRequests.halfDay")}
          </label>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="request-start">{t("hr.common.from")}</Label>
              <Input id="request-start" type="date" value={draft.startDate} onChange={(e) => setDraft({ ...draft, startDate: e.target.value })} />
            </div>
            {!draft.halfDay && (
              <div className="space-y-1.5">
                <Label htmlFor="request-end">{t("hr.common.to")}</Label>
                <Input id="request-end" type="date" value={draft.endDate} onChange={(e) => setDraft({ ...draft, endDate: e.target.value })} />
              </div>
            )}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="request-reason">{t("hr.leaveRequests.reason")}</Label>
            <Input id="request-reason" value={draft.reason} onChange={(e) => setDraft({ ...draft, reason: e.target.value })} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="request-document">{t("hr.leaveRequests.document")}</Label>
            <Input id="request-document" placeholder={t("hr.leaveRequests.documentPlaceholder")} value={draft.documentRef} onChange={(e) => setDraft({ ...draft, documentRef: e.target.value })} />
          </div>
          {formError && <p className="text-sm text-destructive">{formError}</p>}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setOpen(false)}>{t("common.cancel")}</Button>
            <Button onClick={submit} disabled={save.isPending}>{save.isPending ? t("common.saving") : t("common.save")}</Button>
          </div>
        </DialogContent>
      </Dialog>
      <Dialog open={assigningType !== null} onOpenChange={(value) => !value && setAssigningType(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("hr.leaveRequests.assignTypeTitle")}</DialogTitle>
            <DialogDescription>{t("hr.leaveRequests.assignTypeHelp")}</DialogDescription>
          </DialogHeader>
          <Select aria-label={t("hr.leaveRequests.type")} value={pickedType} onChange={(e) => setPickedType(e.target.value)}>
            <option value="">—</option>
            {(types.data ?? []).filter((r) => r.active).map((leaveType) => (
              <option key={leaveType.id} value={leaveType.id}>{uiLanguage === "fr" ? leaveType.name_fr : leaveType.name_en}</option>
            ))}
          </Select>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setAssigningType(null)}>{t("common.cancel")}</Button>
            <Button onClick={() => assignType.mutate()} disabled={!pickedType || assignType.isPending}>{t("common.save")}</Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
```

- [ ] **Step 3: Leave balances tab**

`frontend/src/features/hr/leave/LeaveBalancesTab.tsx`:

```tsx
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { PiggyBank, Plus } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { Select } from "../../../components/ui/select";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../../components/ui/dialog";
import { useColumnFilters, type FilterField } from "../../../lib/useColumnFilters";
import type { ColumnDef } from "../../../lib/useTableColumns";
import type { Employee } from "../api";
import { HrListTable } from "../HrListTable";
import { HR_KEYS, adjustLeaveBalance, listLeaveBalances, listLeaveTypes, type LeaveBalance } from "../presenceApi";
import { employeeLabel, errorText, todayIso } from "../presenceFormat";

interface AdjustDraft { employeeId: string; leaveTypeId: string; delta: string; reason: string }
const emptyDraft = (): AdjustDraft => ({ employeeId: "", leaveTypeId: "", delta: "", reason: "" });

export function LeaveBalancesTab({ employees }: { employees: Employee[] }) {
  const { session, hasPermission } = useAuth();
  const { language, t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [year, setYear] = useState(Number(todayIso().slice(0, 4)));
  const balances = useQuery({ queryKey: [...HR_KEYS.leaveBalances, year], queryFn: () => listLeaveBalances(token, year) });
  const types = useQuery({ queryKey: HR_KEYS.leaveTypes, queryFn: () => listLeaveTypes(token) });
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<AdjustDraft>(emptyDraft);
  const [formError, setFormError] = useState<string | null>(null);
  const canAdjust = hasPermission("hr.admin_leave");

  const adjust = useMutation({
    mutationFn: () => adjustLeaveBalance(token, { employee_id: draft.employeeId, leave_type_id: draft.leaveTypeId, year, delta: Number(draft.delta), reason: draft.reason.trim() }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: HR_KEYS.leaveBalances });
      setOpen(false);
      setDraft(emptyDraft());
      toast.success(t("hr.leaveBalances.adjusted"));
    },
    onError: (error) => setFormError(errorText(error, t("hr.common.saveError"))),
  });
  function submit() {
    const delta = Number(draft.delta);
    if (!draft.employeeId || !draft.leaveTypeId || draft.delta.trim() === "" || Number.isNaN(delta) || delta === 0 || !draft.reason.trim()) {
      setFormError(t("hr.leaveBalances.error.required"));
      return;
    }
    adjust.mutate();
  }

  const trackedTypes = (types.data ?? []).filter((leaveType) => leaveType.accrual_days_per_month > 0 || leaveType.id === draft.leaveTypeId);
  const fields: FilterField<LeaveBalance>[] = [
    { key: "employee", kind: "text", getValue: (b) => `${b.employee_no} ${b.full_name}` },
    { key: "type", kind: "text", getValue: (b) => b.leave_type_code },
    { key: "available", kind: "range", getValue: (b) => b.available },
  ];
  const filters = useColumnFilters(fields);
  const rows = filters.apply((balances.data ?? []).filter((b) => b.tracks_balance));

  const columns: ColumnDef<LeaveBalance>[] = [
    {
      key: "employee", header: t("hr.common.employee"), defaultWidth: 220, sortValue: (b) => b.employee_no, cell: (b) => <span className="font-medium">{b.employee_no} · {b.full_name}</span>,
      filterCell: { type: "text", placeholder: t("hr.common.employee"), value: filters.text.employee ?? "", onChange: (v) => filters.setTextValue("employee", v) },
    },
    {
      key: "type", header: t("hr.leaveRequests.type"), defaultWidth: 140, sortValue: (b) => b.leave_type_code, cell: (b) => b.leave_type_code,
      filterCell: { type: "text", placeholder: t("hr.leaveRequests.type"), value: filters.text.type ?? "", onChange: (v) => filters.setTextValue("type", v) },
    },
    { key: "carried", header: t("hr.leaveBalances.carried"), defaultWidth: 120, cellClassName: "tabular-nums", cell: (b) => b.carried_over },
    { key: "accrued", header: t("hr.leaveBalances.accrued"), defaultWidth: 120, cellClassName: "tabular-nums", cell: (b) => b.accrued },
    { key: "taken", header: t("hr.leaveBalances.taken"), defaultWidth: 120, cellClassName: "tabular-nums", cell: (b) => b.taken },
    { key: "adjusted", header: t("hr.leaveBalances.adjustedColumn"), defaultWidth: 120, cellClassName: "tabular-nums", cell: (b) => b.adjusted },
    {
      key: "available", header: t("hr.leaveBalances.available"), defaultWidth: 130, cellClassName: "tabular-nums font-medium", sortValue: (b) => b.available, cell: (b) => b.available,
      filterCell: { type: "range", min: filters.range.available?.min ?? "", max: filters.range.available?.max ?? "", onMinChange: (v) => filters.setRangeValue("available", "min", v), onMaxChange: (v) => filters.setRangeValue("available", "max", v) },
    },
  ];

  return (
    <>
      <HrListTable
        tableKey="hr.leaveBalances"
        columns={columns}
        rows={rows}
        rowKey={(b) => `${b.employee_id}|${b.leave_type_id}`}
        loading={balances.isLoading}
        emptyIcon={<PiggyBank className="h-5 w-5" />}
        emptyTitle={t("hr.leaveBalances.empty.title")}
        emptyDescription={t("hr.leaveBalances.empty.description")}
        filtersActive={filters.isActive}
        onClearFilters={filters.reset}
        toolbar={
          <>
            <Input type="number" className="w-24" aria-label={t("hr.common.year")} value={year} onChange={(e) => setYear(Number(e.target.value) || year)} />
            {canAdjust && (
              <Button size="sm" onClick={() => { setDraft(emptyDraft()); setFormError(null); setOpen(true); }}>
                <Plus className="h-4 w-4" />
                {t("hr.leaveBalances.adjust")}
              </Button>
            )}
          </>
        }
      />
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("hr.leaveBalances.adjustTitle")}</DialogTitle>
            <DialogDescription>{t("hr.leaveBalances.adjustHelp")}</DialogDescription>
          </DialogHeader>
          <div className="space-y-1.5">
            <Label htmlFor="adjust-employee">{t("hr.common.employee")}</Label>
            <Select id="adjust-employee" value={draft.employeeId} onChange={(e) => setDraft({ ...draft, employeeId: e.target.value })}>
              <option value="">—</option>
              {employees.map((employee) => (
                <option key={employee.id} value={employee.id}>{employeeLabel(employee)}</option>
              ))}
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="adjust-type">{t("hr.leaveRequests.type")}</Label>
            <Select id="adjust-type" value={draft.leaveTypeId} onChange={(e) => setDraft({ ...draft, leaveTypeId: e.target.value })}>
              <option value="">—</option>
              {trackedTypes.map((leaveType) => (
                <option key={leaveType.id} value={leaveType.id}>{leaveType.code} · {language === "fr" ? leaveType.name_fr : leaveType.name_en}</option>
              ))}
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="adjust-delta">{t("hr.leaveBalances.delta")}</Label>
            <Input id="adjust-delta" type="number" step="0.5" value={draft.delta} onChange={(e) => setDraft({ ...draft, delta: e.target.value })} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="adjust-reason">{t("hr.leaveBalances.reason")}</Label>
            <Input id="adjust-reason" value={draft.reason} onChange={(e) => setDraft({ ...draft, reason: e.target.value })} />
          </div>
          {formError && <p className="text-sm text-destructive">{formError}</p>}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setOpen(false)}>{t("common.cancel")}</Button>
            <Button onClick={submit} disabled={adjust.isPending}>{adjust.isPending ? t("common.saving") : t("common.save")}</Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
```

- [ ] **Step 4: The page, route, sidebar, strings**

`frontend/src/features/hr/leave/LeavePage.tsx`:

```tsx
import { useQuery } from "@tanstack/react-query";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { listEmployees } from "../api";
import { HrTabsPage, useBooted, useTabParam } from "../HrTabsPage";
import { HR_KEYS } from "../presenceApi";
import { LeaveBalancesTab } from "./LeaveBalancesTab";
import { LeaveRequestsTab } from "./LeaveRequestsTab";
import { LeaveTypesTab } from "./LeaveTypesTab";

const TABS = ["requests", "balances", "types"] as const;

export function LeavePage() {
  const { session } = useAuth();
  const { t } = useI18n();
  const [tab, setTab] = useTabParam(TABS, "requests");
  const employees = useQuery({ queryKey: HR_KEYS.employees, queryFn: () => listEmployees(session!.token) });
  const booted = useBooted(!employees.isLoading);
  return (
    <HrTabsPage
      title={t("hr.leave.title")}
      subtitle={t("hr.leave.subtitle")}
      layoutId="hr-leave-tab"
      active={tab}
      onChange={setTab}
      booted={booted}
      loaderLabel={t("hr.leave.loading")}
      tabs={[
        { value: "requests", label: t("hr.leave.tab.requests"), content: <LeaveRequestsTab employees={employees.data ?? []} /> },
        { value: "balances", label: t("hr.leave.tab.balances"), content: <LeaveBalancesTab employees={employees.data ?? []} /> },
        { value: "types", label: t("hr.leave.tab.types"), content: <LeaveTypesTab /> },
      ]}
    />
  );
}
```

`router.tsx`: import `LeavePage` from `"../features/hr/leave/LeavePage"`; add `{ path: "/hr/leave", element: <LeavePage /> },`.

`Sidebar.tsx`: append to the HR group's `items` (after `/hr/presence/imports`):

```ts
      { to: "/hr/leave", labelKey: "nav.hrLeave", icon: CalendarDays, permission: "hr.view_leave" },
```

(`CalendarDays` is already imported.)

`i18n.tsx` — `en`:

```ts
  "nav.hrLeave": "Leave",
  "hr.leave.title": "Leave",
  "hr.leave.subtitle": "Requests, balances and leave types.",
  "hr.leave.loading": "Loading leave…",
  "hr.leave.tab.requests": "Requests",
  "hr.leave.tab.balances": "Balances",
  "hr.leave.tab.types": "Leave types",
  "hr.leaveTypes.nameEn": "Name (English)",
  "hr.leaveTypes.nameFr": "Name (French)",
  "hr.leaveTypes.accrual": "Days / month",
  "hr.leaveTypes.cap": "Carry-over cap",
  "hr.leaveTypes.noCap": "No cap",
  "hr.leaveTypes.counts": "Counts",
  "hr.leaveTypes.counts.calendar": "Calendar days",
  "hr.leaveTypes.counts.working": "Working days only",
  "hr.leaveTypes.document": "Needs document",
  "hr.leaveTypes.presenceStatus": "Presence status",
  "hr.leaveTypes.paidLabel": "Paid",
  "hr.leaveTypes.requiresDocumentLabel": "Requires a supporting document before approval",
  "hr.leaveTypes.new": "New leave type",
  "hr.leaveTypes.editTitle": "Edit leave type",
  "hr.leaveTypes.dialogHelp": "The accrual rate and carry-over cap are statutory values: leave them as drafts until confirmed.",
  "hr.leaveTypes.error.required": "Code (for a new type) and both names are required; days per month and the cap must be numbers of 0 or more.",
  "hr.leaveTypes.created": "Leave type created",
  "hr.leaveTypes.updated": "Leave type updated",
  "hr.leaveTypes.empty.title": "No leave type",
  "hr.leaveTypes.empty.description": "Create at least a paid annual leave type before requesting leave.",
  "hr.leaveRequests.type": "Type",
  "hr.leaveRequests.dates": "Dates",
  "hr.leaveRequests.days": "Days",
  "hr.leaveRequests.halfDay": "Half day",
  "hr.leaveRequests.halfDayShort": "half day",
  "hr.leaveRequests.reason": "Reason",
  "hr.leaveRequests.document": "Document",
  "hr.leaveRequests.documentPlaceholder": "Reference or file name",
  "hr.leaveRequests.new": "New request",
  "hr.leaveRequests.editTitle": "Edit request",
  "hr.leaveRequests.dialogHelp": "Working-day leave types skip rest days and public holidays automatically.",
  "hr.leaveRequests.error.required": "Choose an employee and a type, and give a valid date range (or tick half day).",
  "hr.leaveRequests.created": "Leave request created",
  "hr.leaveRequests.updated": "Leave request updated",
  "hr.leaveRequests.approve": "Approve",
  "hr.leaveRequests.reject": "Reject",
  "hr.leaveRequests.cancel": "Cancel",
  "hr.leaveRequests.decision.approve": "Leave approved",
  "hr.leaveRequests.decision.reject": "Leave rejected",
  "hr.leaveRequests.decision.cancel": "Leave cancelled",
  "hr.leaveRequests.legacy": "old request",
  "hr.leaveRequests.assignType": "Give it a type",
  "hr.leaveRequests.assignTypeTitle": "Choose a leave type",
  "hr.leaveRequests.assignTypeHelp": "This request predates leave types. Pick one before it can be approved or rejected.",
  "hr.leaveRequests.typeAssigned": "Leave type set",
  "hr.leaveRequests.empty.title": "No leave request",
  "hr.leaveRequests.empty.description": "Requests appear here once submitted.",
  "hr.leaveBalances.carried": "Carried over",
  "hr.leaveBalances.accrued": "Accrued",
  "hr.leaveBalances.taken": "Taken",
  "hr.leaveBalances.adjustedColumn": "Adjusted",
  "hr.leaveBalances.available": "Available",
  "hr.leaveBalances.adjust": "Adjust a balance",
  "hr.leaveBalances.adjustTitle": "Adjust a leave balance",
  "hr.leaveBalances.adjustHelp": "For an opening balance or a correction. A negative amount removes days.",
  "hr.leaveBalances.delta": "Amount (days)",
  "hr.leaveBalances.reason": "Reason",
  "hr.leaveBalances.adjusted": "Balance adjusted",
  "hr.leaveBalances.error.required": "Choose an employee and a type, a non-zero amount and a reason.",
  "hr.leaveBalances.empty.title": "No tracked balance",
  "hr.leaveBalances.empty.description": "Balances appear for leave types that accrue days per month.",
```

`fr`:

```ts
  "nav.hrLeave": "Congés",
  "hr.leave.title": "Congés",
  "hr.leave.subtitle": "Demandes, soldes et types de congé.",
  "hr.leave.loading": "Chargement des congés…",
  "hr.leave.tab.requests": "Demandes",
  "hr.leave.tab.balances": "Soldes",
  "hr.leave.tab.types": "Types de congé",
  "hr.leaveTypes.nameEn": "Nom (anglais)",
  "hr.leaveTypes.nameFr": "Nom (français)",
  "hr.leaveTypes.accrual": "Jours / mois",
  "hr.leaveTypes.cap": "Plafond de report",
  "hr.leaveTypes.noCap": "Sans plafond",
  "hr.leaveTypes.counts": "Décompte",
  "hr.leaveTypes.counts.calendar": "Jours calendaires",
  "hr.leaveTypes.counts.working": "Jours ouvrés seulement",
  "hr.leaveTypes.document": "Justificatif requis",
  "hr.leaveTypes.presenceStatus": "Statut de présence",
  "hr.leaveTypes.paidLabel": "Payé",
  "hr.leaveTypes.requiresDocumentLabel": "Exige un justificatif avant approbation",
  "hr.leaveTypes.new": "Nouveau type de congé",
  "hr.leaveTypes.editTitle": "Modifier le type de congé",
  "hr.leaveTypes.dialogHelp": "Le taux d'acquisition et le plafond de report sont des valeurs légales : laissez-les en brouillon tant qu'ils ne sont pas confirmés.",
  "hr.leaveTypes.error.required": "Le code (pour un nouveau type) et les deux noms sont obligatoires ; les jours par mois et le plafond doivent être des nombres supérieurs ou égaux à 0.",
  "hr.leaveTypes.created": "Type de congé créé",
  "hr.leaveTypes.updated": "Type de congé modifié",
  "hr.leaveTypes.empty.title": "Aucun type de congé",
  "hr.leaveTypes.empty.description": "Créez au moins un congé annuel payé avant de demander un congé.",
  "hr.leaveRequests.type": "Type",
  "hr.leaveRequests.dates": "Dates",
  "hr.leaveRequests.days": "Jours",
  "hr.leaveRequests.halfDay": "Demi-journée",
  "hr.leaveRequests.halfDayShort": "demi-journée",
  "hr.leaveRequests.reason": "Motif",
  "hr.leaveRequests.document": "Document",
  "hr.leaveRequests.documentPlaceholder": "Référence ou nom du fichier",
  "hr.leaveRequests.new": "Nouvelle demande",
  "hr.leaveRequests.editTitle": "Modifier la demande",
  "hr.leaveRequests.dialogHelp": "Les types de congé en jours ouvrés sautent automatiquement les jours de repos et les jours fériés.",
  "hr.leaveRequests.error.required": "Choisissez un employé et un type, et donnez une période valide (ou cochez demi-journée).",
  "hr.leaveRequests.created": "Demande de congé créée",
  "hr.leaveRequests.updated": "Demande de congé modifiée",
  "hr.leaveRequests.approve": "Approuver",
  "hr.leaveRequests.reject": "Refuser",
  "hr.leaveRequests.cancel": "Annuler",
  "hr.leaveRequests.decision.approve": "Congé approuvé",
  "hr.leaveRequests.decision.reject": "Congé refusé",
  "hr.leaveRequests.decision.cancel": "Congé annulé",
  "hr.leaveRequests.legacy": "ancienne demande",
  "hr.leaveRequests.assignType": "Donner un type",
  "hr.leaveRequests.assignTypeTitle": "Choisir un type de congé",
  "hr.leaveRequests.assignTypeHelp": "Cette demande date d'avant les types de congé. Choisissez-en un avant de pouvoir l'approuver ou la refuser.",
  "hr.leaveRequests.typeAssigned": "Type de congé défini",
  "hr.leaveRequests.empty.title": "Aucune demande de congé",
  "hr.leaveRequests.empty.description": "Les demandes apparaissent ici une fois soumises.",
  "hr.leaveBalances.carried": "Reporté",
  "hr.leaveBalances.accrued": "Acquis",
  "hr.leaveBalances.taken": "Pris",
  "hr.leaveBalances.adjustedColumn": "Ajusté",
  "hr.leaveBalances.available": "Disponible",
  "hr.leaveBalances.adjust": "Ajuster un solde",
  "hr.leaveBalances.adjustTitle": "Ajuster un solde de congé",
  "hr.leaveBalances.adjustHelp": "Pour un solde d'ouverture ou une correction. Un montant négatif retire des jours.",
  "hr.leaveBalances.delta": "Montant (jours)",
  "hr.leaveBalances.reason": "Motif",
  "hr.leaveBalances.adjusted": "Solde ajusté",
  "hr.leaveBalances.error.required": "Choisissez un employé et un type, un montant non nul et un motif.",
  "hr.leaveBalances.empty.title": "Aucun solde suivi",
  "hr.leaveBalances.empty.description": "Les soldes apparaissent pour les types de congé qui acquièrent des jours par mois.",
```

- [ ] **Step 5: Type-check**

Run (from `frontend/`): `npx tsc -b --force`
Expected: exit 0.

- [ ] **Step 6: Browser check**

Grant the demo user `hr.view_leave`, `hr.manage_leave`, `hr.admin_leave` if missing. On `/hr/leave`: create a leave type "Congé annuel" / "Annual leave", paid, 2.5 days/month, calendar days; create a request for an employee spanning a few days; approve it (refused first with `LEAVE_BALANCE_INSUFFICIENT` until a balance adjustment is made, then succeeds); check `/hr/presence` shows those days as "Leave" with source "Leave request" and they are not editable there; check Balances tab shows the taken days; switch language and re-check labels.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/features/hr/leave frontend/src/routes/router.tsx frontend/src/routes/Sidebar.tsx frontend/src/lib/i18n.tsx
git commit -m "feat(hr): leave screen - types, requests with approval, balances

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 14: Extend the dev seed with a month of presence, a clock sample and leave

**Files:**
- Modify: `backend/scripts/seed_hr_payroll.py`
- Create: `backend/scripts/data/hr_clock_sample_2026-08.csv`

**Interfaces:**
- Consumes: every service of Tasks 2, 3, 6, 8, 9 (`ScheduleService`, `HolidayService`, `PresenceSettingsService`, `PresenceService`, `ClockProfileService`, `ClockImportService`, `LeaveTypeService`, `LeaveRequestService`, `LeaveBalanceService`, `PresenceMonthService`); phase 1's `EmployeeService`/employee list (however phase 1 exposes "all employees of the demo tenant" — read `backend/scripts/seed_hr_payroll.py` as it stands after phase 1 before writing this task, and call whatever function/attribute it already uses to list the seeded employees; do not re-seed employees here).
- Produces: nothing new for other phases — this is the leaf of the plan. Running it twice must not fail or duplicate (every write here already goes through `ON CONFLICT`-safe services, or is itself idempotent by construction: the same schedule/rotation/holiday codes, the same clock file staged twice is two harmless import rows, but committing an already-committed import is refused and this script only commits once per run guarded by a "does July's or August's month already exist" check described below).

- [ ] **Step 1: Read the current seed script**

Open `backend/scripts/seed_hr_payroll.py` as phase 1 left it. Find: the tenant id constant it uses (reuse it, do not invent a second one), how it lists the employees it created (a query or a returned list of dicts/ids with `employee_no`), and whether it already prints a summary at the end (append to that pattern rather than starting a second one).

- [ ] **Step 2: Write the clock sample file**

`backend/scripts/data/hr_clock_sample_2026-08.csv` — one Excel-style export (CRLF, semicolon, French header) covering 2026-08-03 (a Monday) for a handful of badges, with one deliberate unknown badge and one deliberate bad time so the seed's own commit result documents what staging review looks like:

```
Badge;DateHeure;Etat
B-0001;03/08/2026 06:58;Entrée
B-0001;03/08/2026 15:04;Sortie
B-0002;03/08/2026 06:55;Entrée
B-0002;03/08/2026 15:01;Sortie
B-0003;03/08/2026 22:57;Entrée
B-0003;04/08/2026 07:03;Sortie
B-9999;03/08/2026 07:00;Entrée
B-0002;32/08/2026 07:00;Entrée
```

(Badges `B-0001`/`B-0002`/`B-0003` must match the `badge_no` the seed gives its first three employees in Step 3 below; `B-9999` is deliberately unknown; the `32/08/2026` row is a deliberate bad timestamp.)

- [ ] **Step 3: Extend the seed script**

Append to `backend/scripts/seed_hr_payroll.py` (inside its existing `seed()` function or a new function it calls — match its existing structure; the sketch below assumes a `seed()` function opening one connection and committing once at the end, as `seed_dev.py` does):

```python
    # --- Phase 2: schedules, a month of presence, a clock import, leave -----------------
    from datetime import date
    from decimal import Decimal

    from core.domain.result import Ok
    from modules.hr.api.clock_import_service import ClockImportService, ClockProfileService
    from modules.hr.api.leave_service import LeaveBalanceService, LeaveRequestService, LeaveTypeService
    from modules.hr.api.presence_month_service import PresenceMonthService
    from modules.hr.api.presence_service import PresenceService
    from modules.hr.api.schedule_service import HolidayService, PresenceSettingsService, ScheduleService
    from modules.hr.domain.presence import ManualEntry

    PERIOD = date(2026, 8, 1)
    already_seeded = connection.execute(
        "SELECT 1 FROM hr.presence_months WHERE tenant_id = %s AND period = %s", (DEMO_TENANT_ID, PERIOD)
    ).fetchone()
    if already_seeded:
        print("Phase 2 presence/leave already seeded for 2026-08; skipping (rerun-safe).")
    else:
        schedules = ScheduleService(connection)
        holidays = HolidayService(connection)
        settings = PresenceSettingsService(connection)
        presence = PresenceService(connection)
        months = PresenceMonthService(connection)
        leave_types = LeaveTypeService(connection)
        leave_requests = LeaveRequestService(connection)
        leave_balances = LeaveBalanceService(connection)

        # Draft settings: HR confirms the real night-work window and clock tolerances.
        settings.update(
            tenant_id=DEMO_TENANT_ID, actor_id=user_id, night_start_minute=21 * 60, night_end_minute=5 * 60,
            punch_attach_minutes=240, punch_dedupe_seconds=60, late_grace_minutes=5,
        )
        day_shift = [{"weekday": w, "start_minute": 7 * 60, "end_minute": 15 * 60, "break_minutes": 0} for w in range(6)]
        evening_shift = [{"weekday": w, "start_minute": 15 * 60, "end_minute": 23 * 60, "break_minutes": 0} for w in range(6)]
        night_shift = [{"weekday": w, "start_minute": 23 * 60, "end_minute": 7 * 60, "break_minutes": 0} for w in range(6)]
        day_result = schedules.create_schedule(tenant_id=DEMO_TENANT_ID, actor_id=user_id, code="JOUR", name="Jour 07-15", is_night=False, days=day_shift)
        evening_result = schedules.create_schedule(tenant_id=DEMO_TENANT_ID, actor_id=user_id, code="SOIR", name="Soir 15-23", is_night=False, days=evening_shift)
        night_result = schedules.create_schedule(tenant_id=DEMO_TENANT_ID, actor_id=user_id, code="NUIT", name="Nuit 23-07", is_night=True, days=night_shift)

        def schedule_id(result, code: str) -> str:
            if isinstance(result, Ok):
                return result.value["id"]
            existing = next(s for s in schedules.list_schedules(tenant_id=DEMO_TENANT_ID) if s["code"] == code)
            return existing["id"]

        day_id = schedule_id(day_result, "JOUR")
        evening_id = schedule_id(evening_result, "SOIR")
        night_id = schedule_id(night_result, "NUIT")

        # Mali public holidays, draft: the accountant confirms the exact dates each year.
        for holiday_date, name in [(date(2026, 8, 22), "Fête de l'Indépendance")]:
            holidays.create_holiday(tenant_id=DEMO_TENANT_ID, actor_id=user_id, country_code="ML", holiday_date=holiday_date, name=name, paid=True, confirmed=False)

        # Assign the first three demo employees to the three shifts; everyone else stays on JOUR.
        seeded_employees = list_seeded_employees(connection)  # whatever phase 1's helper is named
        for index, employee in enumerate(seeded_employees):
            target = [day_id, evening_id, night_id][index % 3] if index < 3 else day_id
            schedules.create_assignment(tenant_id=DEMO_TENANT_ID, actor_id=user_id, employee_id=employee["id"], valid_from=date(2026, 1, 1), schedule_id=target)
            if index < 3:
                connection.execute("UPDATE hr.employees SET badge_no = %s WHERE id = %s", (f"B-{index + 1:04d}", employee["id"]))

        # A full month of "present" on every working day for everyone but the first three
        # (whose days come from the clock import below).
        entries = []
        for employee in seeded_employees[3:]:
            month = presence.employee_month(tenant_id=DEMO_TENANT_ID, employee_id=employee["id"], period=PERIOD)
            if isinstance(month, Ok):
                entries += [
                    ManualEntry(employee_id=employee["id"], work_date=date.fromisoformat(day["work_date"]), status="present")
                    for day in month.value["days"]
                    if day["default_status"] == "present"
                ]
        if entries:
            presence.save_days(tenant_id=DEMO_TENANT_ID, actor_id=user_id, entries=entries)

        # The clock sample: stage and commit it for the three badge-carrying employees.
        profile = ClockProfileService(connection).create_profile(
            tenant_id=DEMO_TENANT_ID, actor_id=user_id, code="ZK-DEMO", name="Pointeuse démo", delimiter=";", has_header=True,
            badge_column="Badge", timestamp_column="DateHeure", timestamp_format="%d/%m/%Y %H:%M",
            direction_column="Etat", in_values=["Entrée"], out_values=["Sortie"],
        )
        clock_csv_path = REPO_ROOT / "scripts" / "data" / "hr_clock_sample_2026-08.csv"  # adjust to the script's own path constant
        clock_content = clock_csv_path.read_text(encoding="utf-8")
        imports = ClockImportService(connection)
        staged = imports.stage(
            tenant_id=DEMO_TENANT_ID, actor_id=user_id, profile_id=profile.value["id"], file_name="hr_clock_sample_2026-08.csv",
            content=clock_content, date_from=date(2026, 8, 3), date_to=date(2026, 8, 4),
        )
        if isinstance(staged, Ok):
            committed = imports.commit(tenant_id=DEMO_TENANT_ID, actor_id=user_id, import_id=staged.value["id"])
            print(f"Clock sample committed: {committed.value if isinstance(committed, Ok) else committed}")
        for employee in seeded_employees[3:]:
            pass  # already filled above; the three clock employees' remaining August days are filled next

        remaining_entries = []
        for employee in seeded_employees[:3]:
            month = presence.employee_month(tenant_id=DEMO_TENANT_ID, employee_id=employee["id"], period=PERIOD)
            if isinstance(month, Ok):
                remaining_entries += [
                    ManualEntry(employee_id=employee["id"], work_date=date.fromisoformat(day["work_date"]), status="present")
                    for day in month.value["days"]
                    if day["default_status"] == "present" and day["record"] is None
                ]
        if remaining_entries:
            presence.save_days(tenant_id=DEMO_TENANT_ID, actor_id=user_id, entries=remaining_entries)

        # Leave: one draft paid annual-leave type (Mali statutory rate to be confirmed), an
        # opening balance, and one approved + one pending request so both screens show data.
        annual = leave_types.create_type(
            tenant_id=DEMO_TENANT_ID, actor_id=user_id, code="ANNUEL", name_en="Annual leave", name_fr="Congé annuel",
            paid=True, accrual_days_per_month=Decimal("2.5"), max_carry_over=None, counts_days="working",
            requires_document=False, presence_status="leave", confirmed=False,
        )
        annual_id = annual.value["id"] if isinstance(annual, Ok) else next(t["id"] for t in leave_types.list_types(tenant_id=DEMO_TENANT_ID) if t["code"] == "ANNUEL")
        if len(seeded_employees) > 3:
            leave_balances.adjust(
                tenant_id=DEMO_TENANT_ID, actor_id=user_id, employee_id=seeded_employees[3]["id"], leave_type_id=annual_id,
                year=2026, delta=Decimal("5"), reason="solde d'ouverture (démo)",
            )
            approved = leave_requests.create_request(
                tenant_id=DEMO_TENANT_ID, actor_id=user_id, employee_id=seeded_employees[3]["id"], leave_type_id=annual_id,
                start_date=date(2026, 8, 17), end_date=date(2026, 8, 18), half_day=False, reason="Congé démo",
            )
            if isinstance(approved, Ok):
                leave_requests.approve(tenant_id=DEMO_TENANT_ID, actor_id=user_id, request_id=approved.value["id"])
        if len(seeded_employees) > 4:
            leave_requests.create_request(
                tenant_id=DEMO_TENANT_ID, actor_id=user_id, employee_id=seeded_employees[4]["id"], leave_type_id=annual_id,
                start_date=date(2026, 9, 7), end_date=date(2026, 9, 8), half_day=False, reason="Demande démo en attente",
            )

        closed = months.close(tenant_id=DEMO_TENANT_ID, actor_id=user_id, period=PERIOD)
        print(f"August 2026 presence close: {closed.value if isinstance(closed, Ok) else closed}")
        print("Presence settings, holidays and leave accrual rate are DRAFT seed values - confirm with HR/payroll before go-live.")
```

Adjust the placeholder names (`list_seeded_employees`, `REPO_ROOT`, `user_id`, `DEMO_TENANT_ID`) to whatever phase 1's actual script already defines — read the file first (Step 1) and match its names exactly; do not introduce a second tenant id or a second employee-listing helper. If phase 1's script does not commit once at the end but instead opens/commits its own connection per section, wrap this block the same way (its own connection, its own `connection.commit()`), consistent with the rest of the file.

- [ ] **Step 4: Run it**

Run (from `backend/`): `.venv/Scripts/python -m scripts.seed_hr_payroll`
Expected: exit 0; the printed close summary shows `locked_rows` > 0 and `holiday_rows` for the seeded month; running it a second time prints "already seeded" and still exits 0.

- [ ] **Step 5: Verify by API**

With the backend running and logged in as `demo@sonalim-erp.local` (granted the phase-2 permissions), `GET /hr/presence/months?year=2026` shows August `closed`; `GET /hr/presence/months/2026-08-01/summary` returns non-zero `worked_days` for every seeded employee; `GET /hr/clock-imports` shows one `committed` import with `error_rows: 2`; `GET /hr/leave/requests` shows one `approved` and one `pending` row.

- [ ] **Step 6: Commit**

```bash
git add backend/scripts/seed_hr_payroll.py backend/scripts/data/hr_clock_sample_2026-08.csv
git commit -m "chore(hr): seed a month of presence, a clock import sample and leave data

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Self-Review

**1. Spec coverage.** Every phase-2 bullet of the design doc maps to a task: schedules/rotation patterns → Tasks 1–2; public holidays (Mali seeded, flagged to confirm) → Task 2 (table + service) and Task 14 (seed); supervisor bulk grid (team × day, team × week) → Task 11; clock CSV import with device profiles → Tasks 5–6, 12; staging review → Task 6 (service) and Task 12 (UI); pure-domain punch pairing engine (night belongs to its start day, missing out-punch, duplicates, manual wins over clock) → Task 4 (engine) and Task 6 (`PROTECTED_SOURCES` wins the conflict); overtime minutes by band day/night/rest_holiday → Tasks 1, 3, 4 (`ot_minutes_day/night/rest_holiday`, `night_overlap_minutes`); leave types/accrual/balances/approval writing leave presence days → Tasks 7–8; month close/reopen publishing `hr.presence_month.closed` → Task 9; `PresenceService.month_summary` + `is_month_closed` exactly per contract → Task 3 (`is_month_closed`) and Task 9 (`month_summary`, tested against the exact contract keys in `test_the_month_summary_is_exactly_what_payroll_is_promised`); old `hr.attendance_records` untouched → stated in Global Constraints and never referenced by any new migration or service; frontend pages `/hr/presence`, `/hr/presence/imports`, `/hr/leave`, `/hr/schedules` → Tasks 10–13. Statutory/plant values as seed data, never hard-coded → Global Constraints line + `hr.presence_settings`/`hr.public_holidays`/`hr.leave_types` all starting empty or `confirmed=false`, asserted by `test_presence_settings_start_empty_and_a_change_clears_the_confirmation` and the holiday/leave-type "to confirm" badges in the UI.

**2. Placeholder scan.** No task uses "TBD"/"handle edge cases"/"similar to Task N" language for code; every step has real code or an exact shell command. The one intentional exception is Task 14's Step 3, which is deliberately written as a template because it must adapt to phase 1's actual seed-script structure (not yet written when this plan was authored) — it is flagged explicitly as a "read first, then match names" step rather than left silently vague, and it still gives complete, copy-pasteable code for every new piece of behaviour (schedules, clock import, leave), with only the wiring names left to confirm against the real file.

**3. Type consistency.** `PresenceService.month_summary` return keys (`SUMMARY_FIELDS` in `domain/presence.py`) are used identically in the domain test (Task 3), the integration test (Task 9), and the frontend `MonthSummary` interface (Task 10) — cross-checked field-by-field. `DayFigures` is constructed the same way in `presence_service.py` (Task 3), `clock_import_service.py` (Task 6) and `leave_service.py` (Task 8). `ManualEntry`/`PresenceEntry` field names match between the domain (Task 3), the router body (Task 3), and the frontend type + both grids (Tasks 10–11). `ScheduleAssignment`/`AssignmentInput`, `ClockProfile`/`ClockProfileInput`, `LeaveType`/`LeaveTypeInput`, `LeaveRecord`/`LeaveRecordInput` all match their backend dict shapes field-for-field between Tasks 2/6/8 and Task 10. Permission codes used in `presence_router.py` handlers match exactly the table in Global Constraints and the route-permission tests appended in each backend task.

**4. Review Focus.** All five items each have an owning task and test: (1) BOM/CRLF Excel export → Task 5, `test_an_excel_export_with_bom_and_crlf_is_read`. (2) A clock file straddling a closed and an open month → Task 6, `test_a_file_touching_a_closed_month_is_refused_whole`. (3) No in/out column + a forgotten punch → Task 4, `test_unknown_directions_do_not_carry_a_forgotten_punch_into_the_next_day`. (4) Two partial exports for the same days → Task 6, `test_a_second_file_completes_the_days_of_the_first`. (5) An employee leaving mid-month → Task 9, `test_gaps_stop_at_the_termination_date_and_a_person_without_schedule_is_a_gap`, and Task 7's `test_monthly_accrual_is_prorated_by_employed_days`.

Two additional risks noticed during the review and already covered rather than left open: a redelivered `payroll.run.approved`/`reversed` event must not double- or wrongly-unlock a month (Task 9, `_handle_run_approved`'s `ON CONFLICT DO NOTHING`, asserted by the "a redelivery changes nothing" line in `test_reopening_needs_a_reason_and_no_approved_payroll`); and editing an *approved* leave request must move both its presence days and its balance rather than leaving stale rows behind (Task 8, `_unapply` + `_apply` inside `update_request`, asserted by `test_editing_approved_leave_moves_its_days_and_its_balance`).

**Spec ambiguities resolved:**
- The spec's `hr.presence_days.status` list and `WORKED_STATUSES` don't say what "worked minutes on a rest/holiday day" count as when nobody typed an overtime band. Resolved by treating every worked minute on a rest day or unworked-by-schedule holiday as `ot_minutes_rest_holiday`, both from manual entry (Task 3's `figures_for_entry`) and from the clock (Task 4's `compute_day`) — consistent with the spec's "Overtime bands: split by the rule set of phase 3 (day overtime tiers, night, rest day/holiday)" and with `hr.presence_days` having exactly those three overtime columns.
- The spec doesn't say whether a public holiday that falls on a person's rest day is a "holiday day" for the month summary. Resolved as: a public holiday only produces a `holiday`-status presence day (and counts as `holiday_days`) when the person was scheduled to work that day; on an already-rest day it stays `rest` and is not double-counted — pinned by `test_the_grid_default_follows_the_schedule_and_the_holiday_calendar`'s "a holiday on a rest day stays a rest day" case.
- The spec's "manual wins over clock" rule doesn't say what happens when the clock and an existing manual/leave day actually agree. Resolved as: only a genuine disagreement (different status or worked minutes) is reported as a conflict; an agreeing day is silently left alone, so the reviewer isn't shown noise — implemented in `ClockImportService._apply` and pinned by `test_a_manual_day_and_a_leave_day_win_over_the_clock_and_are_listed` only asserting the two rows that actually differ.
- The contract fixes `PresenceService.month_summary`'s signature but not what happens with `employee_ids=None`. Resolved as "every employee that has at least one presence row in the month," matching how the interfaces doc's phase-3 usage (`employees_for_period`) always passes explicit ids in practice, while leaving the parameterless form usable for the month-close summary screen (Task 9/11).
- "Supervisor bulk grid ... team × day and team × week" doesn't specify what a "team" is. Resolved as either a department or a single work schedule (a rotation's current step), since both are named in the spec's own data model and either is a defensible reading of "team" on this plant — implemented as the `TeamPicker`'s two modes rather than picking one and dropping the other.

Plan complete and saved to `docs/superpowers/plans/2026-09-25-hr-p2-presence-leave.md`. Please review the plan. Which execution approach would you prefer?

- **Subagent-driven** — a fresh subagent implements each task and a fresh reviewer checks it before the next one starts, then a whole-branch review at the end. Most thorough; costs a fresh context per task and per review.
- **Native** — implement every task in this session, then one fresh reviewer on the most capable model checks the whole branch. Cheapest and fastest; no independent review until the end.

For this plan I recommend **Subagent-driven**, because the 14 tasks form a long dependency chain across a pure-domain engine (pairing), three cross-cutting services (schedules, clock imports, leave) and four frontend screens that all share one API surface (`presenceApi.ts`) — a mistake in an early task's exact field names (e.g. `SUMMARY_FIELDS`, `DayFigures`) would silently propagate through six or more later tasks before surfacing, and a fresh reviewer after each task catches that immediately rather than at the end of a 14-task run. Does the plan capture what you want, and which approach should we use?
