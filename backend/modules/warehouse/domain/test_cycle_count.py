from core.domain.result import Err, Ok
from modules.warehouse.domain.cycle_count import (
    resolve_count,
    settle_counts,
    transition_cycle_count,
    validate_counted_quantity,
)


def test_draft_can_start_or_be_cancelled():
    assert isinstance(transition_cycle_count("draft", "in_progress"), Ok)
    assert isinstance(transition_cycle_count("draft", "cancelled"), Ok)


def test_draft_cannot_complete_directly():
    result = transition_cycle_count("draft", "completed")
    assert isinstance(result, Err)
    assert result.code == "INVALID_TRANSITION"


def test_in_progress_can_complete_or_be_cancelled():
    assert isinstance(transition_cycle_count("in_progress", "completed"), Ok)
    assert isinstance(transition_cycle_count("in_progress", "cancelled"), Ok)


def test_completed_and_cancelled_are_terminal():
    assert isinstance(transition_cycle_count("completed", "in_progress"), Err)
    assert isinstance(transition_cycle_count("cancelled", "in_progress"), Err)


def test_validate_counted_quantity_rejects_negative():
    result = validate_counted_quantity(-1)
    assert isinstance(result, Err)
    assert result.code == "INVALID_QUANTITY"


def test_validate_counted_quantity_accepts_zero_and_positive():
    assert isinstance(validate_counted_quantity(0), Ok)
    assert isinstance(validate_counted_quantity(12.5), Ok)


def test_one_count_never_settles_a_line():
    assert settle_counts(None, None, None) is None
    assert settle_counts(8, None, None) is None


def test_two_equal_counts_settle_a_line():
    assert settle_counts(8, 8, None) == 8


def test_two_different_counts_need_a_third_which_decides():
    assert settle_counts(10, 8, None) is None
    assert settle_counts(8, 9, 7) == 7


def test_resolve_count_matches_when_equal():
    assert resolve_count(expected_quantity=10, counted_quantity=10) == "matched"


def test_resolve_count_leaves_a_real_variance_unresolved():
    assert resolve_count(expected_quantity=10, counted_quantity=8) is None
    assert resolve_count(expected_quantity=10, counted_quantity=12) is None
