from core.domain.result import Err, Ok
from modules.warehouse.domain.site import validate_reparent, validate_site_code


def test_validate_site_code_accepts_a_real_code():
    result = validate_site_code("main")
    assert isinstance(result, Ok)
    assert result.value == "main"


def test_validate_site_code_trims_whitespace():
    result = validate_site_code("  main  ")
    assert isinstance(result, Ok)
    assert result.value == "main"


def test_validate_site_code_rejects_blank():
    result = validate_site_code("   ")
    assert isinstance(result, Err)
    assert result.code == "INVALID_CODE"


def test_reparent_to_none_is_always_allowed():
    assert isinstance(validate_reparent("bin1", None, {}), Ok)


def test_reparent_under_an_unrelated_parent_is_allowed():
    parents = {"rack1": "aisle1", "aisle1": "zone1", "zone1": None}
    assert isinstance(validate_reparent("bin1", "rack1", parents), Ok)


def test_a_location_cannot_become_its_own_parent():
    result = validate_reparent("rack1", "rack1", {"rack1": "aisle1"})
    assert isinstance(result, Err)
    assert result.code == "INVALID_PARENT"


def test_a_location_cannot_be_reparented_under_its_own_descendant():
    # bin1 -> rack1 -> aisle1 -- moving aisle1 under bin1 would create a cycle.
    parents = {"bin1": "rack1", "rack1": "aisle1", "aisle1": None}
    result = validate_reparent("aisle1", "bin1", parents)
    assert isinstance(result, Err)
    assert result.code == "INVALID_PARENT"

    # And moving rack1 under itself two levels down (via bin1) is the same problem.
    result = validate_reparent("rack1", "bin1", parents)
    assert isinstance(result, Err)
    assert result.code == "INVALID_PARENT"
