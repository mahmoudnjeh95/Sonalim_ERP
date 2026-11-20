from decimal import Decimal

import pytest

from core.domain.money import json_number, to_decimal


def test_to_decimal_keeps_what_a_float_caller_wrote():
    assert to_decimal(0.1) == Decimal("0.1")
    assert to_decimal(0.1) + to_decimal(0.2) == Decimal("0.3")
    assert to_decimal(1500) == Decimal("1500")
    assert to_decimal("12.50") == Decimal("12.50")


def test_to_decimal_returns_a_decimal_unchanged():
    value = Decimal("3.14")
    assert to_decimal(value) is value


def test_to_decimal_refuses_a_boolean():
    with pytest.raises(TypeError):
        to_decimal(True)


def test_json_number():
    assert json_number(Decimal("12.50")) == 12.5
    assert isinstance(json_number(Decimal("1000")), float)
    assert json_number(None) is None
