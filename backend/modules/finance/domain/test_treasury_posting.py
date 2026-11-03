from decimal import Decimal

from core.domain.result import Err, Ok
from modules.finance.domain.posting import PostingRule, validate_rule
from modules.finance.domain.treasury_posting import document_entries, instrument_entry, rejection_fee_entry, valid_rule_code

D = Decimal


def rule(kind, code, debit=None, credit=None, journal="BNQ"):
    return PostingRule("treasury", kind, code, debit, credit, journal)


RECEIPT_RULES = [rule("receipt_payment", "*", credit="C1", journal="BNQ"), rule("receipt_payment", "cash", credit="C1", journal="CAI")]


def entries(direction="in", payments=None, unallocated="0", rules=RECEIPT_RULES, currency="XOF"):
    return document_entries(
        direction, payments=payments or [], unallocated=unallocated, partner_id="P", currency=currency, label="L", rules=rules
    )


def test_a_cash_receipt_debits_the_account_ledger_code_and_credits_the_customer_account():
    result = entries(payments=[{"method": "cash", "amount": D("1000"), "account_id": "a", "ledger_account_code": "M1"}])
    assert isinstance(result, Ok)
    [entry] = result.value
    assert (entry.suffix, entry.journal_code) == ("cash", "CAI")
    assert [(l.account_code, l.debit, l.credit, l.partner_id) for l in entry.lines] == [
        ("M1", D(1000), D(0), None),
        ("C1", D(0), D(1000), "P"),
    ]


def test_two_accounts_of_one_method_share_an_entry_each_on_its_own_ledger_code():
    result = entries(payments=[
        {"method": "transfer", "amount": D("300"), "account_id": "a", "ledger_account_code": "B2"},
        {"method": "transfer", "amount": D("200"), "account_id": "b", "ledger_account_code": "B1"},
    ])
    [entry] = result.value
    assert [(l.account_code, l.debit, l.credit) for l in entry.lines] == [("B1", 200, 0), ("B2", 300, 0), ("C1", 0, 500)]


def test_an_account_without_a_ledger_code_is_refused():
    result = entries(payments=[{"method": "cash", "amount": D("10"), "account_id": "a", "ledger_account_code": None}])
    assert isinstance(result, Err) and result.code == "LEDGER_ACCOUNT_MISSING"


def test_a_missing_rule_is_refused_and_nothing_is_guessed():
    result = entries(payments=[{"method": "cash", "amount": D("10"), "account_id": "a", "ledger_account_code": "M1"}], rules=[])
    assert isinstance(result, Err) and result.code == "POSTING_RULE_MISSING"


def test_a_pending_cheque_goes_to_the_holding_account_of_its_rule():
    rules = [rule("receipt_payment", "cheque", debit="H1", credit="C1", journal="BNQ")]
    result = entries(payments=[{"method": "cheque", "amount": D("400"), "account_id": None, "ledger_account_code": None}], rules=rules)
    [entry] = result.value
    assert [(l.account_code, l.debit, l.credit) for l in entry.lines] == [("H1", 400, 0), ("C1", 0, 400)]


def test_a_pending_cheque_with_no_holding_account_is_refused():
    rules = [rule("receipt_payment", "cheque", credit="C1")]
    result = entries(payments=[{"method": "cheque", "amount": D("400"), "account_id": None, "ledger_account_code": None}], rules=rules)
    assert isinstance(result, Err) and result.code == "POSTING_RULE_MISSING"


def test_a_disbursement_debits_the_supplier_account_with_the_partner():
    rules = [rule("disbursement_payment", "*", debit="S1", journal="BNQ")]
    result = entries("out", payments=[{"method": "transfer", "amount": D("700"), "account_id": "a", "ledger_account_code": "B1"}], rules=rules)
    [entry] = result.value
    assert [(l.account_code, l.debit, l.credit, l.partner_id) for l in entry.lines] == [("S1", 700, 0, "P"), ("B1", 0, 700, None)]


def test_the_unallocated_part_is_booked_by_the_advance_rule():
    rules = RECEIPT_RULES + [rule("receipt_advance", "*", debit="C1", credit="ADV", journal="OD")]
    result = entries(payments=[{"method": "cash", "amount": D("1000"), "account_id": "a", "ledger_account_code": "M1"}], unallocated="250", rules=rules)
    advance = result.value[-1]
    assert (advance.suffix, advance.journal_code) == ("advance", "OD")
    assert [(l.account_code, l.debit, l.credit, l.partner_id) for l in advance.lines] == [("C1", 250, 0, "P"), ("ADV", 0, 250, None)]


def test_a_foreign_currency_is_refused():
    result = entries(payments=[], currency="EUR")
    assert isinstance(result, Err) and result.code == "CURRENCY_NOT_XOF"


def test_the_ledger_still_refuses_a_fractional_amount_as_a_safety_net():
    result = entries(payments=[{"method": "cash", "amount": D("1000.50"), "account_id": "a", "ledger_account_code": "M1"}])
    assert isinstance(result, Err) and result.code == "INVALID_ENTRY_LINE"


def test_collecting_an_instrument_moves_it_from_holding_to_the_slip_account():
    rules = [rule("instrument_collected", "in", credit="H1", journal="BNQ")]
    result = instrument_entry("instrument_collected", direction="in", amount=D("400"), currency="XOF", partner_id="P",
                              account_ledger_code="B1", label="L", rules=rules)
    assert [(l.account_code, l.debit, l.credit) for l in result.value.lines] == [("B1", 400, 0), ("H1", 0, 400)]


def test_collecting_without_the_account_ledger_code_is_refused():
    rules = [rule("instrument_collected", "in", credit="H1")]
    result = instrument_entry("instrument_collected", direction="in", amount=D("1"), currency="XOF", partner_id="P",
                              account_ledger_code=None, label="L", rules=rules)
    assert isinstance(result, Err) and result.code == "LEDGER_ACCOUNT_MISSING"


def test_a_bounced_instrument_puts_the_debt_back_on_the_customer():
    rules = [rule("instrument_unpaid", "*", debit="C1", credit="H1", journal="OD")]
    result = instrument_entry("instrument_unpaid", direction="in", amount=D("400"), currency="XOF", partner_id="P",
                              account_ledger_code=None, label="L", rules=rules)
    assert [(l.account_code, l.debit, l.credit, l.partner_id) for l in result.value.lines] == [("C1", 400, 0, "P"), ("H1", 0, 400, None)]


def _fee(rules, ledger_code="B1", currency="XOF", amount=D("2500")):
    return rejection_fee_entry(direction="in", amount=amount, currency=currency, account_ledger_code=ledger_code, label="L", rules=rules)


def test_a_rejection_fee_debits_the_rule_account_and_credits_the_account_charged():
    result = _fee([rule("instrument_rejection_fee", "*", debit="X1", credit="IGNORED", journal="BNQ")])
    assert result.value.journal_code == "BNQ"
    assert [(l.account_code, l.debit, l.credit) for l in result.value.lines] == [("X1", 2500, 0), ("B1", 0, 2500)]


def test_a_rejection_fee_refuses_rather_than_guessing_an_account():
    assert _fee([]).code == "POSTING_RULE_MISSING"
    assert _fee([rule("instrument_rejection_fee", "*", credit="C1")]).code == "POSTING_RULE_MISSING"
    assert _fee([rule("instrument_rejection_fee", "*", debit="X1")], ledger_code=None).code == "LEDGER_ACCOUNT_MISSING"
    assert _fee([rule("instrument_rejection_fee", "*", debit="X1")], currency="EUR").code == "CURRENCY_NOT_XOF"


def test_rule_codes_are_methods_or_directions_for_instruments():
    assert valid_rule_code("receipt_payment", "mobile_money") and valid_rule_code("receipt_payment", "*")
    assert not valid_rule_code("receipt_payment", "in")
    assert valid_rule_code("instrument_collected", "out") and not valid_rule_code("instrument_collected", "cash")


def test_the_rule_validator_knows_the_treasury_source():
    accounts: dict = {}
    bad = validate_rule(rule("receipt_payment", "in", credit="411"), accounts, {"BNQ"})
    assert isinstance(bad, Err) and bad.code == "INVALID_POSTING_RULE"
    unknown = validate_rule(rule("nonsense", "*", credit="411"), accounts, {"BNQ"})
    assert isinstance(unknown, Err) and unknown.code == "INVALID_POSTING_RULE"
