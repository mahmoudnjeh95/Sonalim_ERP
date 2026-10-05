from datetime import date

import pytest

from modules.hr.domain.snapshot import month_bounds, pick_contract


def test_month_bounds_know_month_lengths_and_leap_years():
    assert month_bounds(date(2026, 2, 1)) == (date(2026, 2, 1), date(2026, 2, 28))
    assert month_bounds(date(2028, 2, 1))[1] == date(2028, 2, 29)
    assert month_bounds(date(2026, 12, 1))[1] == date(2026, 12, 31)


def test_a_period_is_the_first_day_of_a_month():
    with pytest.raises(ValueError):
        month_bounds(date(2026, 2, 15))


def test_payroll_pays_from_the_latest_contract_that_touches_the_month():
    old = {"start_date": date(2025, 1, 1), "end_date": date(2026, 9, 14)}
    new = {"start_date": date(2026, 9, 15), "end_date": None}
    future = {"start_date": date(2026, 10, 1), "end_date": None}
    assert pick_contract([old, new, future], date(2026, 9, 1), date(2026, 9, 30)) is new
    assert pick_contract([old], date(2026, 10, 1), date(2026, 10, 31)) is None
