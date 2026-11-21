from decimal import Decimal

from core.domain.result import Err, Ok
from core.domain.tax import DEFAULT_CODES, applies_to_side, validate


def test_valid_code_is_normalised():
    result = validate(" tva10 ", "TVA 10 %", "", "10", "sales", False)
    assert isinstance(result, Ok)
    assert result.value.code == "TVA10" and result.value.name_en == "TVA 10 %" and result.value.rate == Decimal("10.00")


def test_rate_bounds_and_type():
    for rate in (-1, 100.5, "abc", "NaN"):
        result = validate("X", "x", "x", rate, "both", False)
        assert isinstance(result, Err) and result.code == "INVALID_TAX_RATE"
    assert isinstance(validate("X", "x", "x", 100, "both", False), Ok)


def test_exempt_needs_zero_rate_and_name_and_scope():
    assert validate("X", "x", "x", 5, "both", True).code == "INVALID_TAX_CODE"
    assert validate("", "x", "x", 0, "both", False).code == "INVALID_TAX_CODE"
    assert validate("X", "x", "x", 0, "everyone", False).code == "INVALID_TAX_CODE"


def test_applies_to_side():
    assert applies_to_side("both", "sales") and applies_to_side("sales", "sales")
    assert not applies_to_side("purchase", "sales")


def test_defaults_are_valid():
    for code, fr, en, rate, applies, exempt in DEFAULT_CODES:
        assert isinstance(validate(code, fr, en, rate, applies, exempt), Ok)
