from datetime import date

from core.domain.result import Err, Ok
from modules.maintenance.domain.programs import (
    due_occurrences,
    next_occurrence,
    nth_occurrence,
    occurrences,
    validate_program,
)


# -- nth_occurrence / month clamp ----------------------------------------------


def test_monthly_clamp_jan_31_to_feb_28():
    assert nth_occurrence(date(2026, 1, 31), 1, "month", 1) == date(2026, 2, 28)


def test_monthly_clamp_does_not_carry_over_to_the_next_occurrence():
    assert nth_occurrence(date(2026, 1, 31), 1, "month", 2) == date(2026, 3, 31)


def test_nth_occurrence_zero_is_the_start_date():
    assert nth_occurrence(date(2026, 1, 31), 1, "month", 0) == date(2026, 1, 31)


def test_daily_occurrence():
    assert nth_occurrence(date(2026, 1, 1), 3, "day", 2) == date(2026, 1, 7)


def test_weekly_occurrence():
    assert nth_occurrence(date(2026, 1, 1), 2, "week", 3) == date(2026, 2, 12)


def test_multi_month_interval_clamp():
    assert nth_occurrence(date(2026, 1, 31), 2, "month", 1) == date(2026, 3, 31)
    assert nth_occurrence(date(2026, 12, 31), 1, "month", 2) == date(2027, 2, 28)


# -- occurrences ----------------------------------------------------------------


def test_occurrences_weekly_window():
    result = occurrences(date(2026, 1, 1), 1, "week", date(2026, 1, 1), date(2026, 1, 22))
    assert result == [date(2026, 1, 1), date(2026, 1, 8), date(2026, 1, 15), date(2026, 1, 22)]


def test_occurrences_window_excludes_outside_dates():
    result = occurrences(date(2026, 1, 1), 1, "week", date(2026, 1, 9), date(2026, 1, 14))
    assert result == []


def test_occurrences_are_ascending_and_inclusive():
    result = occurrences(date(2026, 1, 1), 1, "month", date(2026, 1, 1), date(2026, 3, 1))
    assert result == [date(2026, 1, 1), date(2026, 2, 1), date(2026, 3, 1)]


# -- due_occurrences --------------------------------------------------------------


def test_due_occurrences_lead_3_includes_occurrence_3_days_out():
    # today = occurrence - 3 -> included
    result = due_occurrences(
        start=date(2026, 1, 1),
        value=1,
        unit="month",
        lead_days=3,
        today=date(2026, 1, 29),
        not_before=date(2026, 1, 1),
    )
    assert date(2026, 2, 1) in result


def test_due_occurrences_lead_3_excludes_occurrence_4_days_out():
    # today = occurrence - 4 -> excluded
    result = due_occurrences(
        start=date(2026, 1, 1),
        value=1,
        unit="month",
        lead_days=3,
        today=date(2026, 1, 28),
        not_before=date(2026, 1, 1),
    )
    assert date(2026, 2, 1) not in result


def test_due_occurrences_not_before_excludes_older_dates():
    result = due_occurrences(
        start=date(2026, 1, 1),
        value=1,
        unit="month",
        lead_days=0,
        today=date(2026, 3, 1),
        not_before=date(2026, 2, 15),
    )
    assert result == [date(2026, 3, 1)]


def test_due_occurrences_never_back_fills_before_program_start():
    result = due_occurrences(
        start=date(2026, 2, 1),
        value=1,
        unit="month",
        lead_days=0,
        today=date(2026, 3, 1),
        not_before=date(2026, 1, 1),
    )
    assert date(2026, 1, 1) not in result
    assert result == [date(2026, 2, 1), date(2026, 3, 1)]


def test_due_occurrences_empty_when_window_closed():
    result = due_occurrences(
        start=date(2026, 5, 1),
        value=1,
        unit="month",
        lead_days=0,
        today=date(2026, 1, 1),
        not_before=date(2026, 1, 1),
    )
    assert result == []


# -- next_occurrence --------------------------------------------------------------


def test_next_occurrence_is_start_when_after_is_earlier():
    assert next_occurrence(date(2026, 1, 1), 1, "month", date(2025, 12, 1)) == date(2026, 1, 1)


def test_next_occurrence_is_start_when_after_equals_start():
    assert next_occurrence(date(2026, 1, 1), 1, "month", date(2026, 1, 1)) == date(2026, 1, 1)


def test_next_occurrence_advances_to_the_first_date_on_or_after():
    assert next_occurrence(date(2026, 1, 1), 1, "month", date(2026, 1, 15)) == date(2026, 2, 1)


def test_next_occurrence_daily():
    assert next_occurrence(date(2026, 1, 1), 5, "day", date(2026, 1, 3)) == date(2026, 1, 6)


def test_next_occurrence_weekly():
    assert next_occurrence(date(2026, 1, 1), 2, "week", date(2026, 1, 10)) == date(2026, 1, 15)


# -- validate_program --------------------------------------------------------------


def test_validate_program_rejects_zero_interval():
    assert validate_program(interval_value=0, interval_unit="day", lead_days=0, name="x").code == "INVALID_INTERVAL"


def test_validate_program_rejects_unknown_unit():
    assert validate_program(interval_value=1, interval_unit="year", lead_days=0, name="x").code == "INVALID_INTERVAL"


def test_validate_program_rejects_negative_lead_days():
    assert validate_program(interval_value=1, interval_unit="day", lead_days=-1, name="x").code == "INVALID_LEAD_DAYS"


def test_validate_program_rejects_blank_name():
    assert validate_program(interval_value=1, interval_unit="day", lead_days=0, name="   ").code == "NAME_REQUIRED"


def test_validate_program_accepts_valid_input():
    assert isinstance(validate_program(interval_value=1, interval_unit="month", lead_days=3, name="Graissage mensuel"), Ok)
