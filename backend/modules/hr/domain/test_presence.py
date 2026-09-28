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
