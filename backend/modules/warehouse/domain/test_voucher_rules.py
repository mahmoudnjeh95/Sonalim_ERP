from decimal import Decimal

from core.domain.result import Ok
from modules.warehouse.domain.voucher_rules import (
    below_minimum,
    check_issue_available,
    check_lines,
    check_order_cumulative,
    check_return,
    check_transfer,
)

D = Decimal


def test_issue_limited_by_available():
    assert isinstance(check_issue_available(D("10"), D("10")), Ok)
    assert check_issue_available(D("10"), D("10.5")).code == "STOCK_INSUFFICIENT"


def test_order_cap_is_cumulative():
    assert isinstance(check_order_cumulative(D("100"), D("60"), D("40")), Ok)
    assert check_order_cumulative(D("100"), D("60"), D("41")).code == "ORDER_QTY_EXCEEDED"


def test_return_cap_is_issued_minus_returned():
    assert isinstance(check_return(D("10"), D("4"), D("6")), Ok)
    assert check_return(D("10"), D("4"), D("7")).code == "RETURN_QTY_EXCEEDED"


def test_transfer_needs_two_different_locations_and_stock():
    assert isinstance(check_transfer("a", "b", D("5"), D("5")), Ok)
    assert check_transfer("a", "a", D("5"), D("1")).code == "INVALID_TRANSFER"
    assert check_transfer("a", None, D("5"), D("1")).code == "INVALID_TRANSFER"
    assert check_transfer("a", "b", D("5"), D("6")).code == "STOCK_INSUFFICIENT"


def test_below_minimum_is_a_boolean_warning():
    assert below_minimum(D("3"), D("5"))
    assert not below_minimum(D("5"), D("5"))
    assert not below_minimum(D("1"), None)
    assert not below_minimum(D("1"), D("0"))


def test_lines_need_quantity_and_receipts_need_cost():
    assert check_lines("issue", []).code == "NO_LINES"
    assert check_lines("issue", [{"quantity": 0}]).code == "INVALID_QUANTITY"
    assert check_lines("receipt", [{"quantity": 1}]).code == "COST_REQUIRED"
    assert isinstance(check_lines("receipt", [{"quantity": 1, "unit_cost": 5}]), Ok)
    assert isinstance(check_lines("issue", [{"quantity": 1}]), Ok)
