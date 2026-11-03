from decimal import Decimal

import pytest

from modules.warehouse.domain.valuation import value_of, weighted_average

D = Decimal


def test_average_of_two_receipts():
    # 100 @ 10 then 100 @ 20 -> 15
    assert weighted_average(D("100"), D("10"), D("100"), D("20")) == D("15.0000")


def test_first_receipt_takes_its_own_cost():
    assert weighted_average(D("0"), D("0"), D("40"), D("12.5")) == D("12.5000")


def test_negative_stock_does_not_dilute_the_new_cost():
    assert weighted_average(D("-30"), D("10"), D("50"), D("20")) == D("20.0000")


def test_rounds_half_up_to_four_places():
    assert weighted_average(D("1"), D("1"), D("2"), D("1.00005")) == D("1.0000")
    assert weighted_average(D("3"), D("10"), D("1"), D("10.0002")) == D("10.0001")


def test_incoming_quantity_must_be_positive():
    with pytest.raises(ValueError):
        weighted_average(D("1"), D("1"), D("0"), D("1"))


def test_value_ignores_negative_balance():
    assert value_of(D("10"), D("2.5")) == D("25.00")
    assert value_of(D("-5"), D("2.5")) == D("0.00")
