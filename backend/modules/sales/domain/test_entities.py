from decimal import Decimal

from core.domain.result import Err, Ok
from modules.sales.domain.entities import OrderLine, SalesOrder, confirm, covers_all_lines


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


def test_total_amount_sums_lines_in_whole_francs():
    # 2 x 9.99 = 19.98; XOF has no cents, so the total is rounded half up like the invoice it becomes.
    order = _order("draft")
    assert order.total_amount == 20.0


def test_total_amount_applies_line_then_order_discount_then_vat():
    order = SalesOrder(
        id="o2", partner_id="c1", location_id="loc1", status="draft", discount_rate=5.0,
        lines=(OrderLine(product_id="p1", quantity=10, unit_price=1000, discount_rate=10.0, vat_rate=18.0),),
    )
    # 10 000 gross, -10 % = 9 000, -5 % = 8 550 excl. tax, 18 % VAT = 1 539, 10 089 incl. tax
    totals = order.totals
    assert (totals.gross, totals.excl_tax, totals.vat, totals.incl_tax) == (10000, 8550, 1539, 10089)
    assert order.total_amount == 10089.0
    assert order.net_unit_price(order.lines[0]) == 855


def test_covers_all_lines_counts_lines_of_one_product_together():
    lines = (OrderLine("a", 10, 1.0), OrderLine("a", 5, 1.0), OrderLine("b", 2, 1.0))
    assert covers_all_lines(lines, {"a": 15, "b": 2}) is True
    assert covers_all_lines(lines, {"a": 10, "b": 2}) is False
    assert covers_all_lines(lines, {"a": 15}) is False


def test_amounts_are_decimal_even_from_float_callers():
    # CRM and the seed scripts still build lines from floats.
    line = OrderLine("p1", 0.1, 0.2)
    assert (line.quantity, line.unit_price) == (Decimal("0.1"), Decimal("0.2"))
    order = SalesOrder(id="o3", partner_id="c1", location_id="loc1", status="draft", discount_rate=2.5, lines=(line,))
    assert order.discount_rate == Decimal("2.5")
    assert isinstance(order.total_amount, Decimal)
