import datetime
from decimal import Decimal

from modules.treasury.domain.statement import dedupe_key, parse_amount, parse_date, parse_rows, suggest_matches

D = Decimal
HEADER = ["DATE", "LIBELLE", "DEBIT", "CREDIT", "SOLDE"]


def test_amounts_from_text_and_numbers():
    assert parse_amount("1 250,50") == D("1250.50")
    assert parse_amount("1.250,50") == D("1250.50")
    assert parse_amount("1,250.50", ".") == D("1250.50")
    assert parse_amount(None) == D("0")
    assert parse_amount("") == D("0")
    assert parse_amount(12.5) == D("12.5")


def test_dates_from_cells_and_text():
    assert parse_date(datetime.datetime(2026, 3, 5, 0, 0), []) == datetime.date(2026, 3, 5)
    formats = ["%d-%b-%y", "%d/%m/%Y"]
    assert parse_date("05-Mar-26", formats) == datetime.date(2026, 3, 5)
    assert parse_date("05/03/2026", formats) == datetime.date(2026, 3, 5)
    assert parse_date("05-mars-26", formats) == datetime.date(2026, 3, 5)


def test_parse_manual_layout():
    rows = [HEADER, ["05-Mar-26", "VIREMENT CLIENT", "1000", "", "6000"], ["06-Mar-26", "FRAIS", "", "50", "5950"]]
    result = parse_rows(rows)
    assert not result.errors and not result.warnings
    assert [l.debit for l in result.lines] == [D("1000"), D("0")]
    assert result.lines[1].credit == D("50") and result.lines[1].row == 3


def test_bad_rows_are_reported_with_row_numbers():
    rows = [HEADER, ["05-Mar-26", "A", "10", "10", ""], ["nope", "B", "10", "", ""], ["06-Mar-26", "C", "", "", ""], ["06-Mar-26", "OK", "5", "", ""]]
    result = parse_rows(rows)
    assert [e["row"] for e in result.errors] == [2, 3, 4]
    assert len(result.lines) == 1 and result.lines[0].label == "OK"


def test_missing_columns_and_empty_file():
    assert parse_rows([["DATE", "LIBELLE"]]).errors[0]["message"].startswith("missing columns")
    assert parse_rows([]).errors[0]["message"] == "empty file"


def test_custom_profile_and_no_header():
    profile = {"has_header": False, "date_formats": ["%Y-%m-%d"]}
    result = parse_rows([["2026-03-05", "X", "", "40", "960"]], profile)
    assert result.lines[0].credit == D("40")


def test_balance_that_does_not_follow_is_a_warning_not_an_error():
    rows = [HEADER, ["05-Mar-26", "A", "100", "", "1100"], ["06-Mar-26", "B", "", "50", "999"]]
    result = parse_rows(rows)
    assert len(result.lines) == 2 and not result.errors
    assert result.warnings[0]["row"] == 3


def test_dedupe_key_ignores_row_number():
    a = parse_rows([HEADER, ["05-Mar-26", "A", "100", "", "1100"]]).lines[0]
    b = parse_rows([HEADER, ["", "", "", "", ""], ["05-Mar-26", "A", "100", "", "1100"]]).lines[0]
    assert a.row != b.row and dedupe_key(a) == dedupe_key(b)


def _line(i, debit="0", credit="0", day=5):
    return {"id": i, "debit": D(debit), "credit": D(credit), "line_date": datetime.date(2026, 3, day)}


def _pay(i, direction, amount, day):
    return {"id": i, "direction": direction, "amount": D(amount), "date": datetime.date(2026, 3, day)}


def test_matching_uses_amount_direction_and_window():
    lines = [_line("l1", debit="100", day=10), _line("l2", credit="40", day=10)]
    payments = [_pay("p1", "in", "100", 8), _pay("p2", "out", "40", 20), _pay("p3", "out", "40", 11)]
    assert suggest_matches(lines, payments) == {"l1": "p1", "l2": "p3"}


def test_a_payment_matches_one_line_only_nearest_first():
    lines = [_line("l1", debit="100", day=10), _line("l2", debit="100", day=14)]
    payments = [_pay("p1", "in", "100", 13)]
    assert suggest_matches(lines, payments) == {"l2": "p1"} or suggest_matches(lines, payments) == {"l1": "p1"}
    assert len(suggest_matches(lines, payments)) == 1
