from core.domain.result import Err, Ok
from modules.maintenance.domain.parts import fulfilment, split_line


# -- split_line -----------------------------------------------------------------


def test_split_line_fully_from_stock():
    result = split_line(quantity=10, issue_quantity=10, available=10)
    assert isinstance(result, Ok)
    assert result.value == (10, 0)


def test_split_line_partial_issue_leaves_a_purchase_remainder():
    result = split_line(quantity=10, issue_quantity=4, available=20)
    assert result.value == (4, 6)


def test_split_line_zero_issue_is_all_purchase():
    result = split_line(quantity=10, issue_quantity=0, available=20)
    assert result.value == (0, 10)


def test_split_line_rejects_issue_above_requested_quantity():
    assert split_line(quantity=10, issue_quantity=11, available=20).code == "INVALID_QUANTITY"


def test_split_line_rejects_negative_issue():
    assert split_line(quantity=10, issue_quantity=-1, available=20).code == "INVALID_QUANTITY"


def test_split_line_rejects_issue_above_available_stock():
    assert split_line(quantity=10, issue_quantity=8, available=5).code == "INSUFFICIENT_STOCK"


def test_split_line_issue_equal_to_available_is_allowed():
    result = split_line(quantity=10, issue_quantity=5, available=5)
    assert isinstance(result, Ok)
    assert result.value == (5, 5)


# -- fulfilment -------------------------------------------------------------------


def test_fulfilment_undecided_before_approval():
    assert fulfilment(None, None) is None


def test_fulfilment_fully_from_stock():
    assert fulfilment(10, 0) == "stock"


def test_fulfilment_fully_purchased():
    assert fulfilment(0, 10) == "purchase"


def test_fulfilment_split_between_stock_and_purchase():
    assert fulfilment(4, 6) == "split"
