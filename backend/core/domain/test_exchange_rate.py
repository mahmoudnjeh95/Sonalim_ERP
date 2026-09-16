from core.domain.result import Err, Ok
from core.domain.exchange_rate import BASE_CURRENCY, convert_to_base, validate_rate


def test_base_currency_amount_passes_through_unchanged():
    result = convert_to_base(amount=100, currency_code=BASE_CURRENCY, rate_to_base=999)
    assert isinstance(result, Ok)
    assert result.value == 100


def test_foreign_currency_amount_is_multiplied_by_rate():
    result = convert_to_base(amount=100, currency_code="EUR", rate_to_base=655.957)
    assert isinstance(result, Ok)
    assert result.value == 100 * 655.957


def test_rejects_non_positive_rate():
    result = convert_to_base(amount=100, currency_code="EUR", rate_to_base=0)
    assert isinstance(result, Err)
    assert result.code == "INVALID_RATE"


def test_validate_rate_rejects_negative():
    result = validate_rate(-1)
    assert isinstance(result, Err)
    assert result.code == "INVALID_RATE"


def test_validate_rate_accepts_positive():
    result = validate_rate(1.5)
    assert isinstance(result, Ok)
