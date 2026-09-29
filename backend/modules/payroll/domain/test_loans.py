from datetime import date
from decimal import Decimal

import pytest

from modules.payroll.domain.loans import Instalment, add_months, instalment_schedule

D = Decimal


def test_the_last_instalment_takes_the_rounding_remainder():
    assert instalment_schedule(D(100000), 3, date(2026, 9, 1)) == [
        Instalment(1, date(2026, 9, 1), D(33333)),
        Instalment(2, date(2026, 10, 1), D(33333)),
        Instalment(3, date(2026, 11, 1), D(33334)),
    ]


def test_an_even_split_across_a_year_change():
    schedule = instalment_schedule(D(90000), 3, date(2026, 11, 1))
    assert [(item.period, item.amount) for item in schedule] == [
        (date(2026, 11, 1), D(30000)), (date(2026, 12, 1), D(30000)), (date(2027, 1, 1), D(30000)),
    ]


def test_add_months_goes_both_ways():
    assert add_months(date(2026, 1, 1), -1) == date(2025, 12, 1)
    assert add_months(date(2026, 12, 1), 13) == date(2028, 1, 1)


def test_a_loan_needs_at_least_one_franc_per_instalment():
    with pytest.raises(ValueError):
        instalment_schedule(D(2), 3, date(2026, 9, 1))
    with pytest.raises(ValueError):
        instalment_schedule(D(100), 0, date(2026, 9, 1))
