from core.domain.result import Err, Ok
from modules.sales.domain.entities import OrderLine, SalesOrder, confirm


def _order(status: str) -> SalesOrder:
    return SalesOrder(id="o1", partner_id="c1", location_id="loc1", status=status, lines=(OrderLine("p1", 2, 9.99),))


def test_confirm_draft_order_succeeds():
    result = confirm(_order("draft"))
    assert isinstance(result, Ok)
    assert result.value.status == "confirmed"


def test_confirm_already_confirmed_order_fails():
    result = confirm(_order("confirmed"))
    assert isinstance(result, Err)
    assert result.code == "INVALID_TRANSITION"


def test_total_amount_sums_lines():
    order = _order("draft")
    assert order.total_amount == 2 * 9.99
