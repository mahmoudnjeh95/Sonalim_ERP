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
