import datetime

import pytest

from modules.scan.domain.text import (
    NOTHING, UNREADABLE, decode_lot, find_intervals, find_times, first_number, is_short_lot, minutes_between,
    normalize, parse_date, parse_decimal, parse_int, parse_lot, parse_percent, parse_time, team_and_hours,
    team_letter, tokens,
)


def test_normalize_drops_case_accents_and_punctuation():
    assert normalize("  Déchet  Presse! ") == "dechet presse"
    assert normalize(None) == ""


def test_tokens_meet_singular_and_plural():
    assert tokens("Vermicelles") == {"vermicelle"}


@pytest.mark.parametrize("text, value, sure", [
    ("02,46kg", 2.46, True), ("0,35Kg", 0.35, True), ("75,28Kgs", 75.28, True), ("00", 0.0, True),
    ("3,25", 3.25, True), ("(500g)", 500.0, True), ("O5", 5.0, False), ("|", 1.0, False),
])
def test_decimals(text, value, sure):
    parsed = parse_decimal(text)
    assert parsed.value == pytest.approx(value) and parsed.sure is sure


def test_decimal_empty_and_unreadable():
    assert parse_decimal("") == NOTHING
    assert parse_decimal("-") == UNREADABLE


def test_percent_over_100_is_not_a_percent():
    assert parse_percent("29 %").value == 29
    assert parse_percent("129") == UNREADABLE


def test_int():
    assert parse_int("65").value == 65
    assert parse_int("6,5") == UNREADABLE


@pytest.mark.parametrize("text, expected", [
    ("09h27mn", datetime.time(9, 27)), ("14h", datetime.time(14, 0)), ("12H18", datetime.time(12, 18)),
    ("07:00", datetime.time(7, 0)), ("07 H", datetime.time(7, 0)),
])
def test_times(text, expected):
    assert parse_time(text).value == expected


def test_a_cell_with_two_times_is_not_one_time():
    assert parse_time("10h43-10h53") == UNREADABLE


def test_times_inside_a_sentence():
    assert [p.value for p in find_times("Démarrage de la production à 09h27mn")] == [datetime.time(9, 27)]


def test_intervals():
    pairs = find_intervals("Alarme silo à reprises 10h43-10h53, 12h56-12h58")
    assert [(a.value, b.value) for a, b in pairs] == [
        (datetime.time(10, 43), datetime.time(10, 53)), (datetime.time(12, 56), datetime.time(12, 58)),
    ]


@pytest.mark.parametrize("text, expected, sure", [
    ("Le07/09/2026", datetime.date(2026, 9, 7), True), ("07/09/26", datetime.date(2026, 9, 7), True),
    ("07.09.26", datetime.date(2026, 9, 7), True), ("07-0926", datetime.date(2026, 9, 7), False),
])
def test_dates(text, expected, sure):
    parsed = parse_date(text)
    assert parsed.value == expected and parsed.sure is sure


def test_lots():
    assert parse_lot("D6249SNL").value == "D6249SNL"
    assert parse_lot("d6249 snl").value == "D6249SNL"
    assert parse_lot("D6249").value == "D6249" and is_short_lot("D6249")
    odd = parse_lot("vermicelle")
    assert odd.value == "VERMICELLE" and odd.sure is False


def test_decode_lot_is_team_year_digit_and_day_of_year():
    assert decode_lot("D6249SNL", datetime.date(2026, 9, 7)) == ("D", datetime.date(2026, 9, 6))
    assert decode_lot("nonsense", datetime.date(2026, 9, 7)) is None


def test_team_letters():
    assert team_letter("Equipe D") == "D"
    assert team_letter("Eq A") == "A"
    assert team_letter("") is None
    assert team_and_hours("D 07 H à 14H00") == ("D", datetime.time(7, 0))


def test_first_number_and_minutes():
    assert first_number("(500g)") == 500
    assert first_number("Active") is None
    assert minutes_between(datetime.time(7, 0), datetime.time(14, 0)) == 420
    assert minutes_between(datetime.time(23, 0), datetime.time(7, 0)) == 480
