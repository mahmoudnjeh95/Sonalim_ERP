from decimal import Decimal

from core.domain.result import Err, Ok
from modules.finance.domain.posting import PostingRule, validate_rule
from modules.finance.domain.treasury_posting import document_entries, instrument_entry, opening_entry, rejection_fee_entry, valid_rule_code

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


PARKING = [rule("receipt_payment", "cheque", debit="H1", credit="C1"), rule("disbursement_payment", "cheque", debit="S1", credit="H2")]


def _instrument(kind, rules, direction="in", method="cheque", amount=D("400"), ledger_code="B1"):
    return instrument_entry(kind, direction=direction, method=method, amount=amount, currency="XOF", partner_id="P",
                            account_ledger_code=ledger_code, label="L", rules=PARKING + rules)


def test_collecting_an_instrument_moves_it_from_holding_to_the_slip_account():
    result = _instrument("instrument_collected", [rule("instrument_collected", "in", journal="BNQ")])
    assert [(l.account_code, l.debit, l.credit) for l in result.value.lines] == [("B1", 400, 0), ("H1", 0, 400)]


def test_a_collection_posts_in_the_journal_of_the_account_it_lands_in():
    rules = [rule("instrument_collected", "in", journal="BNQ"), rule("instrument_collected", "cash", journal="CAI")]
    into_register = instrument_entry("instrument_collected", direction="in", method="cheque", amount=D("400"), currency="XOF",
                                     partner_id="P", account_ledger_code="571", label="L", rules=PARKING + rules, account_kind="cash")
    into_bank = instrument_entry("instrument_collected", direction="in", method="cheque", amount=D("400"), currency="XOF",
                                 partner_id="P", account_ledger_code="521", label="L", rules=PARKING + rules, account_kind="bank")
    assert (into_register.value.journal_code, into_bank.value.journal_code) == ("CAI", "BNQ")


def test_an_opening_entry_debits_the_account_or_credits_it_when_overdrawn():
    rules = [rule("account_opening", "*", credit="471", journal="OD")]
    opened = opening_entry(account_kind="bank", balance=D("1000"), currency="XOF", account_ledger_code="521", label="L", rules=rules)
    overdrawn = opening_entry(account_kind="bank", balance=D("-300"), currency="XOF", account_ledger_code="521", label="L", rules=rules)
    empty = opening_entry(account_kind="bank", balance=D("0"), currency="XOF", account_ledger_code="521", label="L", rules=rules)
    assert [(l.account_code, l.debit, l.credit) for l in opened.value.lines] == [("521", 1000, 0), ("471", 0, 1000)]
    assert [(l.account_code, l.debit, l.credit) for l in overdrawn.value.lines] == [("471", 300, 0), ("521", 0, 300)]
    assert empty.value is None


def test_an_opening_entry_needs_its_rule_and_the_account_ledger_code():
    missing_rule = opening_entry(account_kind="bank", balance=D("1"), currency="XOF", account_ledger_code="521", label="L", rules=[])
    no_code = opening_entry(account_kind="bank", balance=D("1"), currency="XOF", account_ledger_code=None, label="L",
                            rules=[rule("account_opening", "*", credit="471")])
    assert (missing_rule.code, no_code.code) == ("POSTING_RULE_MISSING", "LEDGER_ACCOUNT_MISSING")


def test_collecting_without_the_account_ledger_code_is_refused():
    result = _instrument("instrument_collected", [rule("instrument_collected", "in")], ledger_code=None)
    assert isinstance(result, Err) and result.code == "LEDGER_ACCOUNT_MISSING"


def test_a_bounced_instrument_puts_the_debt_back_on_the_customer():
    result = _instrument("instrument_unpaid", [rule("instrument_unpaid", "*", debit="C1", journal="OD")], ledger_code=None)
    assert [(l.account_code, l.debit, l.credit, l.partner_id) for l in result.value.lines] == [("C1", 400, 0, "P"), ("H1", 0, 400, None)]


def test_an_issued_instrument_that_bounces_puts_the_debt_back_on_the_supplier():
    result = _instrument("instrument_unpaid", [rule("instrument_unpaid", "out", credit="S1", journal="OD")], direction="out",
                         ledger_code=None)
    assert [(l.account_code, l.debit, l.credit, l.partner_id) for l in result.value.lines] == [("H2", 400, 0, None), ("S1", 0, 400, "P")]


def test_each_payment_leaves_the_holding_account_its_own_rule_parked_it_on():
    # A cheque and a cash payment wait on the same slip in different holding accounts. One collection rule per
    # direction used to credit its own account for both, so one holding account never cleared and the other
    # went into credit (found when posting was first switched on end to end).
    rules = [rule("receipt_payment", "cheque", debit="513", credit="411"), rule("receipt_payment", "cash", debit="585", credit="411"),
             rule("instrument_collected", "in", credit="513", journal="BNQ")]
    for method, holding in (("cheque", "513"), ("cash", "585")):
        parked = document_entries("in", payments=[{"method": method, "amount": D("100"), "account_id": None, "ledger_account_code": None}],
                                  unallocated="0", partner_id="P", currency="XOF", label="L", rules=rules)
        collected = instrument_entry("instrument_collected", direction="in", method=method, amount=D("100"), currency="XOF",
                                     partner_id="P", account_ledger_code="571", label="L", rules=rules)
        assert parked.value[0].lines[0].account_code == holding
        assert [(l.account_code, l.debit, l.credit) for l in collected.value.lines] == [("571", 100, 0), (holding, 0, 100)]


def test_collecting_a_payment_whose_rule_has_no_holding_account_is_refused():
    result = instrument_entry("instrument_collected", direction="in", method="cash", amount=D("1"), currency="XOF", partner_id="P",
                              account_ledger_code="571", label="L",
                              rules=[rule("receipt_payment", "cash", credit="411"), rule("instrument_collected", "in")])
    assert isinstance(result, Err) and result.code == "POSTING_RULE_MISSING"


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
    assert valid_rule_code("instrument_collected", "out") and not valid_rule_code("instrument_collected", "cheque")
    # A collection rule may also be written for the kind of account the money lands in, for its journal.
    assert valid_rule_code("instrument_collected", "cash") and not valid_rule_code("instrument_unpaid", "cash")
    assert valid_rule_code("account_opening", "bank") and not valid_rule_code("account_opening", "in")


def test_the_rule_validator_knows_the_treasury_source():
    accounts: dict = {}
    bad = validate_rule(rule("receipt_payment", "in", credit="411"), accounts, {"BNQ"})
    assert isinstance(bad, Err) and bad.code == "INVALID_POSTING_RULE"
    unknown = validate_rule(rule("nonsense", "*", credit="411"), accounts, {"BNQ"})
    assert isinstance(unknown, Err) and unknown.code == "INVALID_POSTING_RULE"


def test_what_the_customer_withheld_is_booked_by_its_own_rule():
    rules = [*RECEIPT_RULES, rule("receipt_withheld", "*", debit="4449", credit="411")]
    result = document_entries(
        "in", payments=[{"method": "transfer", "amount": D("900"), "account_id": "a", "ledger_account_code": "521"}], unallocated="0",
        partner_id="p", currency="XOF", label="L", rules=rules, withheld=D("100"),
    )
    entry = next(e for e in result.value if e.suffix == "withheld")
    assert [(line.account_code, line.debit, line.credit) for line in entry.lines] == [("4449", D("100"), D("0")), ("411", D("0"), D("100"))]
    assert entry.lines[1].partner_id == "p"


def test_a_withheld_amount_with_no_rule_refuses_the_posting():
    result = document_entries(
        "in", payments=[{"method": "transfer", "amount": D("900"), "account_id": "a", "ledger_account_code": "521"}], unallocated="0",
        partner_id="p", currency="XOF", label="L", rules=RECEIPT_RULES, withheld=D("100"),
    )
    assert result.code == "POSTING_RULE_MISSING"


def test_a_cash_payment_waiting_on_the_slip_debits_the_holding_account():
    result = document_entries(
        "in", payments=[{"method": "cash", "amount": D("100"), "account_id": None, "ledger_account_code": None}], unallocated="0",
        partner_id="p", currency="XOF", label="L", rules=[rule("receipt_payment", "*", debit="5112", credit="411")],
    )
    assert [line.account_code for line in result.value[0].lines] == ["5112", "411"]
