from core.domain.result import Err, Ok
from modules.production.domain.machine import Machine, transition_machine, validate_machine_code


def _machine(status: str = "operational") -> Machine:
    return Machine(id="1", work_center_id="wc1", code="M-1", name="Mixer 1", status=status)


def test_operational_machine_can_go_down():
    result = transition_machine(_machine(), "down")
    assert isinstance(result, Ok)
    assert result.value.status == "down"


def test_down_machine_can_return_to_operational():
    result = transition_machine(_machine("down"), "operational")
    assert isinstance(result, Ok)
    assert result.value.status == "operational"


def test_maintenance_machine_cannot_go_directly_down():
    result = transition_machine(_machine("maintenance"), "down")
    assert isinstance(result, Err)
    assert result.code == "INVALID_TRANSITION"


def test_blank_code_is_invalid():
    result = validate_machine_code("")
    assert isinstance(result, Err)
    assert result.code == "INVALID_CODE"
