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
