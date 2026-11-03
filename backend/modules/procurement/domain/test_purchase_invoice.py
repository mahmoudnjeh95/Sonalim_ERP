from decimal import Decimal

from core.domain.result import Err, Ok
from modules.procurement.domain.purchase_invoice import (
    check_lines_total,
    check_payment_delta,
    check_transition,
    remaining,
    status_for_payment,
)

D = Decimal


def test_draft_can_be_validated_or_cancelled():
    assert isinstance(check_transition("draft", "validated"), Ok)
    assert isinstance(check_transition("draft", "cancelled"), Ok)


def test_validated_can_only_be_cancelled_manually():
    assert isinstance(check_transition("validated", "cancelled"), Ok)
    assert isinstance(check_transition("validated", "paid"), Err)


def test_payment_states_are_not_manual_targets():
    assert check_transition("validated", "partially_paid").code == "INVALID_TRANSITION"
    assert check_transition("paid", "cancelled").code == "INVALID_TRANSITION"


def test_status_is_derived_from_amount_paid():
    assert status_for_payment(D("100"), D("0")) == "validated"
    assert status_for_payment(D("100"), D("40")) == "partially_paid"
    assert status_for_payment(D("100"), D("100")) == "paid"


def test_remaining_never_negative():
    assert remaining(D("100"), D("30")) == D("70")
    assert remaining(D("100"), D("100")) == D("0")


def test_payment_delta_bounds():
    assert check_payment_delta(D("100"), D("30"), D("70")) == Ok(D("100"))
    assert check_payment_delta(D("100"), D("30"), D("-30")) == Ok(D("0"))
    assert check_payment_delta(D("100"), D("30"), D("71")).code == "OVER_ALLOCATION"
    assert check_payment_delta(D("100"), D("30"), D("-31")).code == "OVER_ALLOCATION"


def test_lines_total_optional_and_tolerant():
    assert isinstance(check_lines_total(D("100"), []), Ok)
    assert isinstance(check_lines_total(D("100"), [(D("2"), D("50"))]), Ok)
    assert isinstance(check_lines_total(D("100"), [(D("3"), D("33.333"))]), Ok)
    assert check_lines_total(D("100"), [(D("1"), D("90"))]).code == "TOTAL_MISMATCH"
