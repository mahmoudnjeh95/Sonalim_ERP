from decimal import Decimal

from core.domain.result import Err, Ok
from modules.treasury.domain.accounts import apply_movement, normalize_iban, validate_account

D = Decimal


def test_bank_needs_branch_and_number():
    base = {"name": "SGBM", "currency": "XOF"}
    assert validate_account("bank", base).code == "ACCOUNT_FIELD_REQUIRED"
    assert isinstance(validate_account("bank", {**base, "branch_id": "b", "account_number": "123"}), Ok)


def test_mobile_money_needs_operator_and_phone():
    base = {"name": "Orange", "currency": "XOF", "operator": "orange_money"}
    assert validate_account("mobile_money", base).code == "ACCOUNT_FIELD_REQUIRED"
    assert isinstance(validate_account("mobile_money", {**base, "phone": "70000000"}), Ok)


def test_cash_needs_only_name_and_currency():
    assert isinstance(validate_account("cash", {"name": "Caisse", "currency": "XOF"}), Ok)
    assert validate_account("cash", {"name": "Caisse"}).code == "ACCOUNT_FIELD_REQUIRED"


def test_unknown_kind_refused():
    assert validate_account("crypto", {"name": "x", "currency": "XOF"}).code == "INVALID_ACCOUNT_KIND"


def test_configured_format_rule_applies_only_to_its_kind():
    rules = [{"kind": "bank", "regex": r"\d{5}", "hint_en": "5 digits", "hint_fr": "5 chiffres"}]
    bank = {"name": "B", "currency": "XOF", "branch_id": "b"}
    assert validate_account("bank", {**bank, "account_number": "12345"}, rules) == Ok(None)
    refused = validate_account("bank", {**bank, "account_number": "abc"}, rules)
    assert isinstance(refused, Err) and refused.message_fr == "5 chiffres"
    assert isinstance(validate_account("mobile_money", {"name": "M", "currency": "XOF", "operator": "o", "phone": "1", "account_number": "abc"}, rules), Ok)


def test_movement_applies_signed_amount():
    assert apply_movement(D("100"), D("-40"), allow_negative=False) == Ok(D("60"))
    assert apply_movement(D("100"), D("25"), allow_negative=False) == Ok(D("125"))


def test_movement_refuses_overdraft_unless_allowed():
    assert apply_movement(D("100"), D("-101"), allow_negative=False).code == "INSUFFICIENT_BALANCE"
    assert apply_movement(D("100"), D("-101"), allow_negative=True) == Ok(D("-1"))


def test_zero_movement_refused():
    assert apply_movement(D("100"), D("0"), allow_negative=True).code == "INVALID_AMOUNT"


def test_iban_normalised():
    assert normalize_iban(" ml12 3456 ") == "ML123456"
    assert normalize_iban("  ") is None
    assert normalize_iban(None) is None
