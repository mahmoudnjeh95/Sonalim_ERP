import datetime
from decimal import Decimal

from core.domain.result import Ok
from modules.treasury.domain.instruments import (
    alert_due,
    alert_start,
    check_outcome,
    split_reduction,
    unpaid_reverses_balance,
)

D = Decimal


def test_collect_only_from_pending():
    assert isinstance(check_outcome("cheque", "pending", "collected"), Ok)
    assert check_outcome("cheque", "collected", "collected").code == "INSTRUMENT_NOT_PENDING"
    assert check_outcome("draft", "unpaid", "collected").code == "INSTRUMENT_NOT_PENDING"


def test_unpaid_is_cheque_only_and_from_pending_or_collected():
    assert isinstance(check_outcome("cheque", "pending", "unpaid"), Ok)
    assert isinstance(check_outcome("cheque", "collected", "unpaid"), Ok)
    assert check_outcome("draft", "pending", "unpaid").code == "UNPAID_CHEQUE_ONLY"
    assert check_outcome("cheque", "unpaid", "unpaid").code == "INSTRUMENT_NOT_PENDING"
    assert check_outcome("cheque", "pending", "lost").code == "INVALID_OUTCOME"


def test_balance_reversed_only_after_credit():
    assert unpaid_reverses_balance("collected")
    assert not unpaid_reverses_balance("pending")


def test_alert_windows_for_the_four_default_rules():
    due = datetime.date(2026, 5, 10)
    # received cheque: +1 day after due
    assert not alert_due(due, 1, datetime.date(2026, 5, 10))
    assert alert_due(due, 1, datetime.date(2026, 5, 11))
    # received draft: +15
    assert alert_start(due, 15) == datetime.date(2026, 5, 25)
    # issued cheque: 1 day before
    assert alert_due(due, -1, datetime.date(2026, 5, 9))
    assert not alert_due(due, -1, datetime.date(2026, 5, 8))
    # issued draft: 15 days before
    assert alert_due(due, -15, datetime.date(2026, 4, 25))


def test_split_reduction_walks_invoices_in_order():
    allocations = [("a", D("100"), D("0")), ("b", D("50"), D("0"))]
    assert split_reduction(allocations, D("120")) == [("a", D("100")), ("b", D("20"))]
    assert split_reduction(allocations, D("30")) == [("a", D("30"))]


def test_split_reduction_skips_what_was_already_taken_back():
    allocations = [("a", D("100"), D("100")), ("b", D("50"), D("10"))]
    assert split_reduction(allocations, D("60")) == [("b", D("40"))]
