"""The balanced-entry builder: what the ledger accepts as an entry, with no database."""
from decimal import Decimal

from core.domain.result import Err, Ok
from modules.finance.domain.ledger import (
    Account,
    EntryLine,
    build_entry,
    reverse_lines,
    split_balance,
    totals,
    validate_account,
    validate_lines,
)

D = Decimal
ACCOUNTS = {
    "42": Account("42", "Personnel", 4, "liability", False, "4"),
    "422": Account("422", "Personnel, rémunérations dues", 4, "liability", True, "42"),
    "661": Account("661", "Rémunérations directes versées au personnel national", 6, "expense", True, "66"),
}


def _code(result) -> str:
    assert isinstance(result, Err), result
    return result.code


def test_a_balanced_entry_builds():
    result = build_entry([EntryLine("661", debit=D(320000)), EntryLine("422", credit=D(320000))], ACCOUNTS)
    assert isinstance(result, Ok)
    assert totals(result.value) == (D(320000), D(320000))


def test_unequal_sides_are_refused():
    lines = [EntryLine("661", debit=D(100)), EntryLine("422", credit=D(90))]
    assert _code(build_entry(lines, ACCOUNTS)) == "ENTRY_UNBALANCED"


def test_an_entry_needs_a_line_on_each_side():
    assert _code(build_entry([EntryLine("661", debit=D(100))], ACCOUNTS)) == "ENTRY_UNBALANCED"
    assert _code(build_entry([], ACCOUNTS)) == "ENTRY_UNBALANCED"


def test_a_heading_account_cannot_be_posted_to():
    lines = [EntryLine("42", debit=D(5)), EntryLine("422", credit=D(5))]
    assert _code(build_entry(lines, ACCOUNTS)) == "ACCOUNT_NOT_POSTABLE"


def test_an_unknown_account_cannot_be_posted_to():
    lines = [EntryLine("999", debit=D(5)), EntryLine("422", credit=D(5))]
    assert _code(build_entry(lines, ACCOUNTS)) == "ACCOUNT_NOT_POSTABLE"


def test_a_line_carries_exactly_one_side():
    assert _code(validate_lines([EntryLine("661", debit=D(5), credit=D(5))], ACCOUNTS)) == "INVALID_ENTRY_LINE"
    assert _code(validate_lines([EntryLine("661")], ACCOUNTS)) == "INVALID_ENTRY_LINE"


def test_amounts_are_whole_non_negative_francs():
    assert _code(validate_lines([EntryLine("661", debit=D("10.5"))], ACCOUNTS)) == "INVALID_ENTRY_LINE"
    assert _code(validate_lines([EntryLine("661", debit=D(-10))], ACCOUNTS)) == "INVALID_ENTRY_LINE"


def test_a_draft_may_be_unbalanced():
    assert isinstance(validate_lines([EntryLine("661", debit=D(100))], ACCOUNTS), Ok)


def test_every_refusal_speaks_french():
    result = build_entry([EntryLine("661", debit=D(100))], ACCOUNTS)
    assert isinstance(result, Err) and result.message_fr


def test_reversing_swaps_every_side():
    mirrored = reverse_lines([EntryLine("661", debit=D(7), label="x"), EntryLine("422", credit=D(7))])
    assert mirrored == [EntryLine("661", credit=D(7), label="x"), EntryLine("422", debit=D(7))]


def test_split_balance_prints_the_side_the_balance_is_on():
    assert split_balance(D(50)) == (D(50), D(0))
    assert split_balance(D(-20)) == (D(0), D(20))
    assert split_balance(D(0)) == (D(0), D(0))


def test_an_account_number_starts_with_its_class():
    assert _code(validate_account(Account("521", "Banques locales", 6, "asset", True), None)) == "INVALID_ACCOUNT"


def test_an_account_extends_its_parent_number():
    parent = Account("52", "Banques", 5, "asset", False, "5")
    assert isinstance(validate_account(Account("5211", "BDM", 5, "asset", True, "52"), parent), Ok)
    assert _code(validate_account(Account("5711", "Caisse", 5, "asset", True, "52"), parent)) == "INVALID_ACCOUNT"
    assert _code(validate_account(Account("5211", "BDM", 5, "asset", True, "52"), None)) == "INVALID_ACCOUNT"


def test_an_account_code_is_digits_not_starting_with_zero():
    assert _code(validate_account(Account("0521", "x", 0, "asset", True), None)) == "INVALID_ACCOUNT"
    assert _code(validate_account(Account("52A", "x", 5, "asset", True), None)) == "INVALID_ACCOUNT"


def test_an_account_has_a_known_type_and_a_name():
    assert _code(validate_account(Account("521", "x", 5, "cash", True), None)) == "INVALID_ACCOUNT"
    assert _code(validate_account(Account("521", " ", 5, "asset", True), None)) == "INVALID_ACCOUNT"
