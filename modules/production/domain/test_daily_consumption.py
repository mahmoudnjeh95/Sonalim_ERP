from core.domain.result import Err, Ok
from modules.production.domain.daily_consumption import validate_consumption, validate_resource_type


def test_validate_resource_type_accepts_valid_input():
    result = validate_resource_type(code="electricity", name="Électricité", unit="kWh")
    assert isinstance(result, Ok)


def test_validate_resource_type_rejects_missing_unit():
    result = validate_resource_type(code="electricity", name="Électricité", unit="")
    assert isinstance(result, Err)
    assert result.code == "INVALID_UNIT"


def test_validate_consumption_accepts_zero():
    result = validate_consumption(quantity=0)
    assert isinstance(result, Ok)


def test_validate_consumption_rejects_negative():
    result = validate_consumption(quantity=-1)
    assert isinstance(result, Err)
    assert result.code == "INVALID_QUANTITY"
