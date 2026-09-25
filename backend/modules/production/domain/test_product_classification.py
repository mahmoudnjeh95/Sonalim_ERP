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


def test_validate_classification_accepts_sac_packaging_format_on_finished_good():
    result = validate_classification("finished_good", False, packaging_format="sac")
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


def test_energy_flag_is_only_for_plain_raw_materials():
    assert isinstance(validate_classification("raw_material", False, is_energy=True), Ok)
    wrong_category = validate_classification("finished_good", False, is_energy=True)
    assert isinstance(wrong_category, Err) and wrong_category.code == "ENERGY_FLAG_INVALID"
    with_water = validate_classification("raw_material", False, is_water=True, is_energy=True)
    assert isinstance(with_water, Err) and with_water.code == "ENERGY_FLAG_CONFLICT"
    with_regrind = validate_classification("raw_material", True, is_energy=True)
    assert isinstance(with_regrind, Err) and with_regrind.code == "ENERGY_FLAG_CONFLICT"


def test_packaging_kind_is_only_for_packaging_components():
    ok = validate_classification("packaging_component", False, packaging_kind="film")
    assert isinstance(ok, Ok)
    wrong_category = validate_classification("raw_material", False, packaging_kind="film")
    assert isinstance(wrong_category, Err) and wrong_category.code == "PACKAGING_KIND_INVALID"


def test_packaging_kind_must_be_a_known_kind():
    result = validate_classification("packaging_component", False, packaging_kind="bogus")
    assert isinstance(result, Err) and result.code == "INVALID_PACKAGING_KIND"
