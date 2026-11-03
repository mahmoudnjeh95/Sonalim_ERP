from datetime import date
from decimal import Decimal

from core.domain.result import Ok
from modules.hr.domain.payment import PaymentMethod, set_in_force, validate_payment_set


def bank(share: str = "100", primary: bool = True) -> PaymentMethod:
    return PaymentMethod(method="bank", share_percent=Decimal(share), is_primary=primary, bank_name="BDM-SA", account_no="ML001 01001 000000000001 12")


def mobile(share: str, primary: bool = False) -> PaymentMethod:
    return PaymentMethod(method="mobile_money", share_percent=Decimal(share), is_primary=primary, mobile_operator="orange_money", mobile_number="76 00 00 00")


def test_one_bank_account_taking_everything_is_valid():
    assert isinstance(validate_payment_set([bank()]), Ok)


def test_a_split_must_add_up_to_exactly_one_hundred():
    assert isinstance(validate_payment_set([bank("70"), mobile("30")]), Ok)
    refused = validate_payment_set([bank("70"), mobile("20")])
    assert refused.code == "PAYOUT_SPLIT_INVALID" and "90" in refused.message


def test_a_share_has_at_most_two_decimals():
    """NUMERIC(5,2) would silently round 33.333 into a split that no longer adds up."""
    assert validate_payment_set([bank("33.333"), mobile("66.667")]).code == "PAYOUT_SPLIT_INVALID"
    cash = PaymentMethod(method="cash", share_percent=Decimal("33.34"))
    assert isinstance(validate_payment_set([bank("33.33"), mobile("33.33"), cash]), Ok)


def test_a_share_is_above_zero_and_at_most_one_hundred():
    assert validate_payment_set([bank("0"), mobile("100", primary=False)]).code == "PAYOUT_SPLIT_INVALID"
    assert validate_payment_set([bank("150"), mobile("-50")]).code == "PAYOUT_SPLIT_INVALID"


def test_exactly_one_method_is_primary():
    assert validate_payment_set([bank("50", primary=True), mobile("50", primary=True)]).code == "PAYOUT_SPLIT_INVALID"
    assert validate_payment_set([bank("50", primary=False), mobile("50")]).code == "PAYOUT_SPLIT_INVALID"


def test_a_bank_transfer_needs_the_account_and_mobile_money_a_known_operator_and_number():
    no_account = PaymentMethod(method="bank", share_percent=Decimal("100"), is_primary=True, bank_name="BDM-SA")
    assert validate_payment_set([no_account]).code == "INVALID_PAYMENT_METHOD"
    unknown_operator = PaymentMethod(method="mobile_money", share_percent=Decimal("100"), is_primary=True, mobile_operator="wave", mobile_number="1")
    assert validate_payment_set([unknown_operator]).code == "INVALID_PAYMENT_METHOD"
    assert validate_payment_set([PaymentMethod(method="cheque", share_percent=Decimal("100"), is_primary=True)]).code == "INVALID_CHOICE"


def test_cash_drops_details_that_do_not_apply():
    [cash] = validate_payment_set(
        [PaymentMethod(method="cash", share_percent=Decimal("100"), is_primary=True, bank_name="BDM-SA", account_no="x")]
    ).value
    assert (cash.bank_name, cash.account_no) == (None, None)


def test_an_empty_arrangement_is_refused():
    assert validate_payment_set([]).code == "PAYOUT_SPLIT_INVALID"


def test_the_arrangement_in_force_is_the_latest_started_on_or_before_the_day():
    starts = [date(2025, 1, 1), date(2026, 7, 1), date(2026, 10, 1)]
    assert set_in_force(starts, date(2026, 9, 30)) == date(2026, 7, 1)
    assert set_in_force(starts, date(2024, 12, 31)) is None
