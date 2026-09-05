from core.domain.result import Err, Ok
from modules.maintenance.domain.equipment import Equipment, transition_equipment, validate_equipment_code


def _equipment(status: str = "operational") -> Equipment:
    return Equipment(id="1", work_center_id="wc1", code="M-1", name="Mixer 1", status=status)


def test_operational_equipment_can_go_down():
    result = transition_equipment(_equipment(), "down")
    assert isinstance(result, Ok)
    assert result.value.status == "down"


def test_down_equipment_can_return_to_operational():
    result = transition_equipment(_equipment("down"), "operational")
    assert isinstance(result, Ok)
    assert result.value.status == "operational"


def test_maintenance_equipment_cannot_go_directly_down():
    result = transition_equipment(_equipment("maintenance"), "down")
    assert isinstance(result, Err)
    assert result.code == "INVALID_TRANSITION"


def test_blank_code_is_invalid():
    result = validate_equipment_code("")
    assert isinstance(result, Err)
    assert result.code == "INVALID_CODE"
