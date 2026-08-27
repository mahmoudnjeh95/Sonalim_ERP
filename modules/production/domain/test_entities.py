from core.domain.result import Err, Ok
from modules.production.domain.entities import WorkOrder, transition


def test_draft_to_in_progress_succeeds():
    order = WorkOrder(id="1", product_id="p1", quantity=10, status="draft")
    result = transition(order, "in_progress")
    assert isinstance(result, Ok)
    assert result.value.status == "in_progress"


def test_draft_to_completed_fails():
    order = WorkOrder(id="1", product_id="p1", quantity=10, status="draft")
    result = transition(order, "completed")
    assert isinstance(result, Err)
    assert result.code == "INVALID_TRANSITION"


def test_completed_has_no_further_transitions():
    order = WorkOrder(id="1", product_id="p1", quantity=10, status="completed")
    result = transition(order, "in_progress")
    assert isinstance(result, Err)
