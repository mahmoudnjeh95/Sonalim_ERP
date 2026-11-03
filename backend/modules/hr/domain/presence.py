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
* rest_days_worked: worked days whose minutes are rest/holiday overtime and that are not
  paid holidays (a rest day, or an unpaid holiday); also counted in worked_days.
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
    "holidays_worked_days", "rest_days_worked", "ot_minutes_day", "ot_minutes_night", "ot_minutes_rest_holiday",
    "night_minutes", "late_minutes",
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
        elif row.worked_minutes > 0 and row.ot_minutes_rest_holiday > 0:
            total["rest_days_worked"] += 1
        for field in _SUMMED_MINUTES:
            total[field] += getattr(row, field)
    known = set(requested)
    ordered = requested + sorted(employee_id for employee_id in totals if employee_id not in known)
    return [totals[employee_id] for employee_id in ordered]
