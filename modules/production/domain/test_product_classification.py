from core.domain.result import Err, Ok
from modules.production.domain.product_classification import validate_classification


def test_validate_classification_accepts_known_category():
    result = validate_classification("raw_material", False)
    assert isinstance(result, Ok)


def test_validate_classification_rejects_unknown_category():
    result = validate_classification("bogus", False)
    assert isinstance(result, Err)
    assert result.code == "INVALID_CATEGORY"


def test_validate_classification_rejects_regrind_flag_on_non_raw_material():
    result = validate_classification("finished_good", True)
    assert isinstance(result, Err)
    assert result.code == "REGRIND_FLAG_INVALID"


def test_validate_classification_accepts_packaging_format_on_finished_good():
    result = validate_classification("finished_good", False, packaging_format="packet")
    assert isinstance(result, Ok)


def test_validate_classification_rejects_packaging_format_on_non_finished_good():
    result = validate_classification("raw_material", False, packaging_format="packet")
    assert isinstance(result, Err)
    assert result.code == "PACKAGING_FORMAT_INVALID"


def test_validate_classification_rejects_unknown_packaging_format():
    result = validate_classification("finished_good", False, packaging_format="bogus")
    assert isinstance(result, Err)
    assert result.code == "INVALID_PACKAGING_FORMAT"


def test_validate_classification_rejects_water_flag_on_non_raw_material():
    result = validate_classification("finished_good", False, is_water=True)
    assert isinstance(result, Err)
    assert result.code == "WATER_FLAG_INVALID"


def test_validate_classification_rejects_regrind_and_water_together():
    result = validate_classification("raw_material", True, is_water=True)
    assert isinstance(result, Err)
    assert result.code == "REGRIND_WATER_CONFLICT"


def test_validate_classification_accepts_water_flag_on_raw_material():
    result = validate_classification("raw_material", False, is_water=True)
    assert isinstance(result, Ok)
