from core.domain.result import Err, Ok
from modules.production.domain.entities import WorkOrder, transition


def _order(status: str) -> WorkOrder:
    return WorkOrder(id="1", product_id="p1", planned_quantity=10, status=status)


def test_planned_to_ongoing_succeeds():
    result = transition(_order("planned"), "ongoing")
    assert isinstance(result, Ok)
    assert result.value.status == "ongoing"


def test_planned_to_closed_fails():
    result = transition(_order("planned"), "closed")
    assert isinstance(result, Err)
    assert result.code == "INVALID_TRANSITION"


def test_ongoing_can_suspend_and_suspended_can_resume():
    suspended = transition(_order("ongoing"), "suspended")
    assert isinstance(suspended, Ok)
    resumed = transition(suspended.value, "ongoing")
    assert isinstance(resumed, Ok)
    assert resumed.value.status == "ongoing"


def test_ongoing_to_closed_succeeds():
    result = transition(_order("ongoing"), "closed")
    assert isinstance(result, Ok)
    assert result.value.status == "closed"


def test_ongoing_cannot_be_cancelled_directly():
    # Cancelling a running OF means suspending it first, so the stop is recorded
    # before the order is written off.
    result = transition(_order("ongoing"), "cancelled")
    assert isinstance(result, Err)
    assert result.code == "INVALID_TRANSITION"


def test_planned_and_suspended_can_be_cancelled():
    assert isinstance(transition(_order("planned"), "cancelled"), Ok)
    assert isinstance(transition(_order("suspended"), "cancelled"), Ok)


def test_closed_has_no_further_transitions():
    for target in ("ongoing", "suspended", "cancelled", "closed"):
        assert isinstance(transition(_order("closed"), target), Err)


def test_cancelled_has_no_further_transitions():
    for target in ("planned", "ongoing", "closed"):
        assert isinstance(transition(_order("cancelled"), target), Err)


def test_transition_preserves_the_other_fields():
    order = WorkOrder(
        id="1",
        product_id="p1",
        planned_quantity=10,
        status="planned",
        reference="OF-000001",
        work_center_id="wc1",
        product_type="short",
    )
    result = transition(order, "ongoing")
    assert isinstance(result, Ok)
    assert result.value.reference == "OF-000001"
    assert result.value.work_center_id == "wc1"
    assert result.value.product_type == "short"
