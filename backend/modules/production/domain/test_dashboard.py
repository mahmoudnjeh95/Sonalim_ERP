import datetime

from core.domain.result import Err, Ok
from modules.production.domain.dashboard import (
    ShiftWindow,
    current_shift,
    direction,
    line_state,
    previous_period,
    shift_length_minutes,
    team_rotation_schedule,
    validate_shift_window,
    validate_team_rotation,
)

T = datetime.time


def _windows():
    return [
        ShiftWindow(shift="Shift 1", start=T(7, 0), end=T(15, 0)),
        ShiftWindow(shift="Shift 2", start=T(15, 0), end=T(23, 0)),
        ShiftWindow(shift="Shift 3", start=T(23, 0), end=T(7, 0)),
    ]


def test_current_shift_inside_a_daytime_window():
    assert current_shift(_windows(), T(8, 4)).shift == "Shift 1"
    assert current_shift(_windows(), T(22, 59)).shift == "Shift 2"


def test_a_window_starts_inclusive_and_ends_exclusive():
    assert current_shift(_windows(), T(15, 0)).shift == "Shift 2"
    assert current_shift(_windows(), T(7, 0)).shift == "Shift 1"


def test_current_shift_across_midnight():
    assert current_shift(_windows(), T(23, 30)).shift == "Shift 3"
    assert current_shift(_windows(), T(0, 0)).shift == "Shift 3"
    assert current_shift(_windows(), T(6, 59)).shift == "Shift 3"


def test_no_shift_when_nothing_is_configured_or_the_time_is_uncovered():
    assert current_shift([], T(8, 0)) is None
    assert current_shift([ShiftWindow(shift="Day", start=T(9, 0), end=T(17, 0))], T(20, 0)) is None


def test_shift_window_needs_a_name_and_a_real_span():
    assert isinstance(validate_shift_window(shift="Shift 1", start=T(7, 0), end=T(15, 0)), Ok)
    assert isinstance(validate_shift_window(shift="Shift 3", start=T(23, 0), end=T(7, 0)), Ok)
    assert isinstance(validate_shift_window(shift="  ", start=T(7, 0), end=T(15, 0)), Err)
    # Same start and end is either zero or 24 hours; neither is a shift.
    assert isinstance(validate_shift_window(shift="Shift 1", start=T(7, 0), end=T(7, 0)), Err)


def test_line_state_green_when_ongoing_and_every_machine_operational():
    assert line_state(of_status="ongoing", machine_statuses=["operational", "operational"]) == "running"
    # A line with no machines on file is not a stoppage.
    assert line_state(of_status="ongoing", machine_statuses=[]) == "running"


def test_line_state_yellow_for_maintenance_red_for_down_and_red_wins():
    assert line_state(of_status="ongoing", machine_statuses=["operational", "maintenance"]) == "maintenance"
    assert line_state(of_status="ongoing", machine_statuses=["operational", "down"]) == "down"
    assert line_state(of_status="ongoing", machine_statuses=["maintenance", "down"]) == "down"


def test_a_suspended_of_is_shown_as_suspended_whatever_the_machines_say():
    assert line_state(of_status="suspended", machine_statuses=["down"]) == "suspended"


def test_previous_period_is_the_equal_length_window_just_before():
    assert previous_period(datetime.date(2026, 9, 19), datetime.date(2026, 9, 19)) == (
        datetime.date(2026, 9, 18),
        datetime.date(2026, 9, 18),
    )
    assert previous_period(datetime.date(2026, 9, 13), datetime.date(2026, 9, 19)) == (
        datetime.date(2026, 9, 6),
        datetime.date(2026, 9, 12),
    )


def test_direction_compares_at_display_precision_and_never_judges():
    assert direction(96.14, 96.1, decimals=1) == "flat"
    assert direction(96.2, 96.1, decimals=1) == "up"
    assert direction(95.9, 96.1, decimals=1) == "down"
    assert direction(10, None, decimals=1) is None


def test_a_shift_is_as_long_as_its_window():
    assert [shift_length_minutes(w) for w in _windows()] == [8 * 60, 8 * 60, 8 * 60]
    assert shift_length_minutes(ShiftWindow(shift="Matin", start=T(7, 0), end=T(14, 30))) == 7 * 60 + 30


def test_a_window_through_midnight_is_measured_across_it():
    assert shift_length_minutes(ShiftWindow(shift="Nuit", start=T(22, 0), end=T(7, 0))) == 9 * 60
    assert shift_length_minutes(ShiftWindow(shift="Nuit", start=T(23, 45), end=T(0, 15))) == 30


def _rotation():
    # The owner's own anchor: on 2026-09-19, B was on the first shift, C on the
    # second, D on the third, A resting.
    return [
        ("B", datetime.date(2026, 9, 19), 0),
        ("C", datetime.date(2026, 9, 19), 1),
        ("D", datetime.date(2026, 9, 19), 2),
        ("A", datetime.date(2026, 9, 19), 3),
    ]


def test_team_rotation_schedule_on_the_anchor_date():
    shifts = ["Shift 1", "Shift 2", "Shift 3"]
    schedule = team_rotation_schedule(shifts=shifts, rotation=_rotation(), date=datetime.date(2026, 9, 19))
    assert {(e["team"], e["shift"]) for e in schedule} == {
        ("B", "Shift 1"), ("C", "Shift 2"), ("D", "Shift 3"), ("A", None),
    }


def test_team_rotation_schedule_advances_one_stop_per_day():
    shifts = ["Shift 1", "Shift 2", "Shift 3"]
    schedule = team_rotation_schedule(shifts=shifts, rotation=_rotation(), date=datetime.date(2026, 9, 22))
    assert {(e["team"], e["shift"]) for e in schedule} == {
        ("C", "Shift 1"), ("D", "Shift 2"), ("A", "Shift 3"), ("B", None),
    }


def test_team_rotation_schedule_wraps_after_a_full_cycle_and_works_before_the_anchor():
    shifts = ["Shift 1", "Shift 2", "Shift 3"]
    # The cycle is 4 days long (3 shifts + rest), so 4 days later matches the anchor exactly.
    after = team_rotation_schedule(shifts=shifts, rotation=_rotation(), date=datetime.date(2026, 9, 23))
    assert {(e["team"], e["shift"]) for e in after} == {
        ("B", "Shift 1"), ("C", "Shift 2"), ("D", "Shift 3"), ("A", None),
    }
    before = team_rotation_schedule(shifts=shifts, rotation=_rotation(), date=datetime.date(2026, 9, 18))
    assert {(e["team"], e["shift"]) for e in before} == {
        ("C", "Shift 1"), ("D", "Shift 2"), ("A", "Shift 3"), ("B", None),
    }


def test_team_rotation_needs_exactly_shifts_plus_one_teams():
    entries = [
        {"team": "A", "anchor_date": datetime.date(2026, 9, 19), "anchor_stop": 0},
        {"team": "B", "anchor_date": datetime.date(2026, 9, 19), "anchor_stop": 1},
    ]
    result = validate_team_rotation(entries, num_shifts=3)
    assert isinstance(result, Err) and result.code == "WRONG_TEAM_COUNT"


def test_team_rotation_rejects_two_teams_on_the_same_stop():
    entries = [
        {"team": "A", "anchor_date": datetime.date(2026, 9, 19), "anchor_stop": 0},
        {"team": "B", "anchor_date": datetime.date(2026, 9, 19), "anchor_stop": 0},
        {"team": "C", "anchor_date": datetime.date(2026, 9, 19), "anchor_stop": 2},
        {"team": "D", "anchor_date": datetime.date(2026, 9, 19), "anchor_stop": 3},
    ]
    result = validate_team_rotation(entries, num_shifts=3)
    assert isinstance(result, Err) and result.code == "DUPLICATE_ENTRY"


def test_team_rotation_rejects_two_teams_with_the_same_name():
    entries = [
        {"team": "A", "anchor_date": datetime.date(2026, 9, 19), "anchor_stop": 0},
        {"team": "a", "anchor_date": datetime.date(2026, 9, 19), "anchor_stop": 1},
        {"team": "C", "anchor_date": datetime.date(2026, 9, 19), "anchor_stop": 2},
        {"team": "D", "anchor_date": datetime.date(2026, 9, 19), "anchor_stop": 3},
    ]
    result = validate_team_rotation(entries, num_shifts=3)
    assert isinstance(result, Err) and result.code == "DUPLICATE_ENTRY"


def test_team_rotation_rejects_mismatched_anchor_dates():
    entries = [
        {"team": "A", "anchor_date": datetime.date(2026, 9, 19), "anchor_stop": 0},
        {"team": "B", "anchor_date": datetime.date(2026, 9, 20), "anchor_stop": 1},
        {"team": "C", "anchor_date": datetime.date(2026, 9, 19), "anchor_stop": 2},
        {"team": "D", "anchor_date": datetime.date(2026, 9, 19), "anchor_stop": 3},
    ]
    result = validate_team_rotation(entries, num_shifts=3)
    assert isinstance(result, Err) and result.code == "INVALID_ENTRY"


def test_team_rotation_accepts_a_complete_valid_set():
    result = validate_team_rotation(
        [{"team": t, "anchor_date": d, "anchor_stop": s} for t, d, s in _rotation()], num_shifts=3
    )
    assert isinstance(result, Ok)
