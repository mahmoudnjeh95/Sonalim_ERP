import datetime

from core.domain.result import Err, Ok
from modules.production.domain.dashboard import (
    ShiftWindow,
    current_shift,
    direction,
    line_state,
    previous_period,
    validate_shift_window,
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
