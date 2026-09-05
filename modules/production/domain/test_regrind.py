from core.domain.result import Err, Ok
from modules.production.domain.regrind import validate_scrap, validate_team_assignment


def test_valid_scrap_passes():
    result = validate_scrap(scrap_type="cutting", quantity=12.5, work_order_id="wo-1", source_note=None)
    assert isinstance(result, Ok)


def test_invalid_scrap_type_is_rejected():
    result = validate_scrap(scrap_type="mixing", quantity=5, work_order_id="wo-1", source_note=None)
    assert isinstance(result, Err)
    assert result.code == "INVALID_SCRAP_TYPE"


def test_non_positive_quantity_is_rejected():
    result = validate_scrap(scrap_type="filling_dosing", quantity=0, work_order_id="wo-1", source_note=None)
    assert isinstance(result, Err)
    assert result.code == "INVALID_QUANTITY"


def test_scrap_without_work_order_needs_source_note():
    result = validate_scrap(scrap_type="cutting", quantity=5, work_order_id=None, source_note=None)
    assert isinstance(result, Err)
    assert result.code == "MISSING_SOURCE"


def test_scrap_without_work_order_but_with_source_note_passes():
    result = validate_scrap(scrap_type="cutting", quantity=5, work_order_id=None, source_note="found on the packaging line floor")
    assert isinstance(result, Ok)


def test_team_assignment_needs_a_name():
    result = validate_team_assignment("   ")
    assert isinstance(result, Err)
    assert result.code == "MISSING_TEAM"


def test_team_assignment_with_a_name_passes():
    assert isinstance(validate_team_assignment("Équipe A"), Ok)
