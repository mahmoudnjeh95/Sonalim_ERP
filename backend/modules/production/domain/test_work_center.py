from core.domain.result import Err, Ok
from modules.production.domain.work_center import (
    WorkCenter,
    block_work_center,
    unblock_work_center,
    validate_work_center_code,
)


def _work_center(is_blocked: bool = False, blocked_reason: str | None = None) -> WorkCenter:
    return WorkCenter(
        id="1", code="EXT-1", name="Extruder 1", hourly_rate=45.0, is_blocked=is_blocked, blocked_reason=blocked_reason
    )


def test_available_work_center_can_be_blocked():
    result = block_work_center(_work_center(), "Screw jam")
    assert isinstance(result, Ok)
    assert result.value.is_blocked is True
    assert result.value.blocked_reason == "Screw jam"


def test_blocking_requires_a_reason():
    result = block_work_center(_work_center(), "   ")
    assert isinstance(result, Err)
    assert result.code == "REASON_REQUIRED"


def test_already_blocked_work_center_cannot_be_blocked_again():
    result = block_work_center(_work_center(is_blocked=True, blocked_reason="Screw jam"), "Another reason")
    assert isinstance(result, Err)
    assert result.code == "ALREADY_BLOCKED"


def test_blocked_work_center_can_be_unblocked():
    result = unblock_work_center(_work_center(is_blocked=True, blocked_reason="Screw jam"))
    assert isinstance(result, Ok)
    assert result.value.is_blocked is False
    assert result.value.blocked_reason is None


def test_unblocking_a_non_blocked_work_center_fails():
    result = unblock_work_center(_work_center())
    assert isinstance(result, Err)
    assert result.code == "NOT_BLOCKED"


def test_blank_code_is_invalid():
    result = validate_work_center_code("  ")
    assert isinstance(result, Err)
    assert result.code == "INVALID_CODE"
