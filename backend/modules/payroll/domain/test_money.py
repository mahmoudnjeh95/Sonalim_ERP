from decimal import Decimal

import pytest

from modules.payroll.domain.money import percent_of, round_amount

D = Decimal


def test_half_up_rounds_halves_away_from_zero_on_both_signs():
    assert round_amount(D("2.5")) == 3
    assert round_amount(D("-2.5")) == -3
    assert round_amount(D("2.49")) == 2


def test_down_to_tens_truncates_toward_zero():
    assert round_amount(D("46675"), round_to=10, mode="down") == D("46670")
    assert round_amount(D("-46675"), round_to=10, mode="down") == D("-46670")


def test_up_to_hundreds_goes_away_from_zero():
    assert round_amount(D("101"), round_to=100, mode="up") == 200


def test_an_exact_multiple_is_unchanged():
    assert round_amount(D("500"), round_to=100, mode="up") == 500


def test_a_bad_step_or_mode_is_a_programming_error():
    with pytest.raises(ValueError):
        round_amount(D("1"), round_to=0)
    with pytest.raises(ValueError):
        round_amount(D("1"), mode="banker")


def test_percent_is_read_as_written():
    assert percent_of(D("487500"), D("3.6")) == D("17550")
