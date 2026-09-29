"""Posting rules: how payroll lines and invoices become journal lines, with no database."""
from decimal import Decimal

from core.domain.result import Err, Ok
from modules.finance.domain.ledger import Account, EntryLine, build_entry
from modules.finance.domain.posting import (
    PostingRule,
    invoice_entry,
    payroll_payment_entries,
    payroll_run_lines,
    resolve_rule,
    to_xof,
    validate_rule,
)

D = Decimal


def _rule(source, kind, code, debit, credit, journal=None) -> PostingRule:
    return PostingRule(
        source=source, source_kind=kind, code=code,
        debit_account_code=debit, credit_account_code=credit, journal_code=journal,
    )


RULES = [
    _rule("payroll", "earning", "*", "661", None),
    _rule("payroll", "deduction", "*", None, "421"),
    _rule("payroll", "employee_contribution", "*", None, "431"),
    _rule("payroll", "employer_contribution", "*", "664", "431"),
    _rule("payroll", "employer_charge", "*", "641", "442"),
    _rule("payroll", "tax", "*", None, "447"),
    _rule("payroll", "net", "*", None, "422"),
    _rule("payroll", "payment", "bank", "422", "521", "BNQ"),
    _rule("payroll", "payment", "cash", "422", "571", "CAI"),
    _rule("invoice", "issued", "*", "411", "702", "VTE"),
    _rule("invoice", "paid", "*", "521", "411", "BNQ"),
]
ACCOUNTS = {
    code: Account(code, code, int(code[0]), "asset", True)
    for code in ("411", "421", "422", "431", "433", "442", "447", "521", "571", "641", "661", "664", "702")
}
JOURNALS = {"PAIE", "VTE", "ACH", "BNQ", "CAI", "OD"}

# One employee: gross 320 000 = INPS 11 040 + ITS 25 000 + advance 10 000 + net 273 960.
RUN = [
    {"source_kind": "earning", "code": "BASE", "amount": D(300000), "employee_id": "e1"},
    {"source_kind": "earning", "code": "OT_DAY", "amount": D(20000), "employee_id": "e1"},
    {"source_kind": "employee_contribution", "code": "INPS_EE", "amount": D(11040), "employee_id": "e1"},
    {"source_kind": "tax", "code": "ITS", "amount": D(25000), "employee_id": "e1"},
    {"source_kind": "deduction", "code": "ADVANCE", "amount": D(10000), "employee_id": "e1"},
    {"source_kind": "net", "code": "NET", "amount": D(273960), "employee_id": "e1"},
    {"source_kind": "employer_contribution", "code": "INPS_ER", "amount": D(60000), "employee_id": "e1"},
    {"source_kind": "employer_charge", "code": "TL", "amount": D(3200), "employee_id": "e1"},
]


def test_the_exact_code_wins_over_the_fallback():
    rules = RULES + [_rule("payroll", "employee_contribution", "AMO_EE", None, "433")]
    amo = resolve_rule(rules, source="payroll", source_kind="employee_contribution", code="AMO_EE")
    inps = resolve_rule(rules, source="payroll", source_kind="employee_contribution", code="INPS_EE")
    assert amo.value.credit_account_code == "433"
    assert inps.value.credit_account_code == "431"


def test_no_rule_and_no_fallback_is_posting_rule_missing():
    result = resolve_rule(RULES, source="payroll", source_kind="benefit", code="CAR")
    assert isinstance(result, Err) and result.code == "POSTING_RULE_MISSING" and result.message_fr


def test_a_run_becomes_one_balanced_entry_aggregated_by_account():
    result = payroll_run_lines(RUN, RULES)
    assert isinstance(result, Ok), result
    assert result.value == [
        EntryLine("641", debit=D(3200)),
        EntryLine("661", debit=D(320000)),
        EntryLine("664", debit=D(60000)),
        EntryLine("421", credit=D(10000)),
        EntryLine("422", credit=D(273960)),
        EntryLine("431", credit=D(71040)),
        EntryLine("442", credit=D(3200)),
        EntryLine("447", credit=D(25000)),
    ]
    assert isinstance(build_entry(result.value, ACCOUNTS), Ok)


def test_many_employees_add_up_on_the_same_account():
    two = RUN + [dict(line, employee_id="e2") for line in RUN]
    lines = {(line.account_code, line.debit > 0): line for line in payroll_run_lines(two, RULES).value}
    assert lines[("661", True)].debit == D(640000)
    assert lines[("422", False)].credit == D(547920)


def test_zero_lines_are_skipped_and_negative_lines_refused():
    with_zero = RUN + [{"source_kind": "earning", "code": "BONUS", "amount": D(0), "employee_id": "e1"}]
    assert payroll_run_lines(with_zero, RULES).value == payroll_run_lines(RUN, RULES).value
    negative = payroll_run_lines([{"source_kind": "earning", "code": "BASE", "amount": D(-5), "employee_id": "e1"}], RULES)
    assert isinstance(negative, Err) and negative.code == "INVALID_ENTRY_LINE"


def test_an_unmapped_kind_refuses_the_whole_run():
    extra = RUN + [{"source_kind": "benefit", "code": "CAR", "amount": D(5), "employee_id": "e1"}]
    result = payroll_run_lines(extra, RULES)
    assert isinstance(result, Err) and result.code == "POSTING_RULE_MISSING"


def test_payments_make_one_entry_per_method_clearing_net_pay():
    result = payroll_payment_entries(
        [
            {"method": "bank", "amount": D(200000), "employee_id": "e1"},
            {"method": "cash", "amount": D(23960), "employee_id": "e2"},
            {"method": "bank", "amount": D(50000), "employee_id": "e3"},
        ],
        RULES,
    )
    assert isinstance(result, Ok), result
    assert [(entry.method, entry.journal_code) for entry in result.value] == [("bank", "BNQ"), ("cash", "CAI")]
    assert result.value[0].lines == [EntryLine("422", debit=D(250000)), EntryLine("521", credit=D(250000))]


def test_a_payment_method_without_a_complete_rule_is_refused():
    lines = [{"method": "mobile_money", "amount": D(1000), "employee_id": "e1"}]
    missing = payroll_payment_entries(lines, RULES)
    assert isinstance(missing, Err) and missing.code == "POSTING_RULE_MISSING"
    partial = payroll_payment_entries(lines, RULES + [_rule("payroll", "payment", "mobile_money", "422", None)])
    assert isinstance(partial, Err) and partial.code == "POSTING_RULE_MISSING"


def test_an_unknown_payment_method_is_refused():
    result = payroll_payment_entries([{"method": "cheque", "amount": D(1000), "employee_id": "e1"}], RULES)
    assert isinstance(result, Err) and result.code == "INVALID_ENTRY_LINE"


def test_invoice_amounts_are_whole_xof_rounded_half_up():
    assert to_xof(1500.4, currency="XOF").value == D(1500)
    assert to_xof("1500.5", currency="XOF").value == D(1501)
    assert to_xof(1500, currency="EUR").code == "CURRENCY_NOT_XOF"
    assert to_xof(0, currency="XOF").code == "INVALID_ENTRY_LINE"
    assert to_xof("abc", currency="XOF").code == "INVALID_ENTRY_LINE"


def test_an_issued_invoice_debits_the_customer_and_its_payment_credits_it():
    issued = invoice_entry("issued", amount=D(150000), partner_id="p1", label="Facture F1", rules=RULES)
    assert issued.value == (
        "VTE",
        [
            EntryLine("411", debit=D(150000), label="Facture F1", partner_id="p1"),
            EntryLine("702", credit=D(150000), label="Facture F1"),
        ],
    )
    paid = invoice_entry("paid", amount=D(150000), partner_id="p1", label="Règlement F1", rules=RULES)
    assert paid.value == (
        "BNQ",
        [
            EntryLine("521", debit=D(150000), label="Règlement F1"),
            EntryLine("411", credit=D(150000), label="Règlement F1", partner_id="p1"),
        ],
    )


def test_a_valid_rule_comes_back_with_its_code_trimmed():
    result = validate_rule(_rule("payroll", "employee_contribution", " AMO_EE ", None, "433"), ACCOUNTS, JOURNALS)
    assert isinstance(result, Ok) and result.value.code == "AMO_EE"


def test_invalid_rules_are_refused():
    cases = [
        (_rule("stock", "earning", "*", "661", None), "INVALID_POSTING_RULE"),
        (_rule("payroll", "bonus", "*", "661", None), "INVALID_POSTING_RULE"),
        (_rule("payroll", "earning", "", "661", None), "INVALID_POSTING_RULE"),
        (_rule("payroll", "earning", "*", None, None), "INVALID_POSTING_RULE"),
        (_rule("payroll", "earning", "*", "999", None), "ACCOUNT_NOT_POSTABLE"),
        (_rule("payroll", "payment", "cheque", "422", "521", "BNQ"), "INVALID_POSTING_RULE"),
        (_rule("payroll", "payment", "bank", "422", "521", None), "INVALID_POSTING_RULE"),
        (_rule("payroll", "payment", "bank", "422", "521", "XXX"), "INVALID_POSTING_RULE"),
        (_rule("invoice", "issued", "P1", "411", "702", "VTE"), "INVALID_POSTING_RULE"),
    ]
    for rule, code in cases:
        result = validate_rule(rule, ACCOUNTS, JOURNALS)
        assert isinstance(result, Err) and result.code == code, rule
        assert result.message_fr, rule
