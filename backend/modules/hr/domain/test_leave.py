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
