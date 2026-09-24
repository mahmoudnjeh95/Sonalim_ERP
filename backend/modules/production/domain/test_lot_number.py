import datetime

import pytest

from modules.production.domain.lot_number import default_lot_number, suggest_lot_number, team_letter

D = datetime.date


def test_the_same_day_carries_the_same_lot():
    assert suggest_lot_number(last_lot="4187SNL", last_date=D(2026, 7, 5), report_date=D(2026, 7, 5)) == "4187SNL"


def test_the_counter_moves_on_by_the_days_elapsed():
    assert suggest_lot_number(last_lot="4187SNL", last_date=D(2026, 7, 5), report_date=D(2026, 7, 6)) == "4188SNL"
    assert suggest_lot_number(last_lot="4187SNL", last_date=D(2026, 7, 5), report_date=D(2026, 7, 9)) == "4191SNL"


def test_days_off_and_maintenance_days_use_up_their_number():
    # Nothing was made from the 6th to the 8th; the 9th is still four days on.
    assert suggest_lot_number(last_lot="4187SNL", last_date=D(2026, 7, 5), report_date=D(2026, 7, 9)) == "4191SNL"


def test_the_counter_carries_over_a_month_end():
    assert suggest_lot_number(last_lot="4210SNL", last_date=D(2026, 7, 30), report_date=D(2026, 8, 2)) == "4213SNL"


def test_the_suffix_is_copied_from_the_last_lot_not_fixed():
    assert suggest_lot_number(last_lot="118ABC", last_date=D(2026, 7, 5), report_date=D(2026, 7, 6)) == "119ABC"
    assert suggest_lot_number(last_lot="4187", last_date=D(2026, 7, 5), report_date=D(2026, 7, 6)) == "4188"


def test_the_width_of_the_counter_is_kept():
    assert suggest_lot_number(last_lot="0042SNL", last_date=D(2026, 7, 5), report_date=D(2026, 7, 6)) == "0043SNL"
    assert suggest_lot_number(last_lot="0099", last_date=D(2026, 7, 5), report_date=D(2026, 7, 6)) == "0100"
    assert suggest_lot_number(last_lot="99", last_date=D(2026, 7, 5), report_date=D(2026, 7, 6)) == "100"


def test_surrounding_spaces_do_not_stop_a_lot_being_followed():
    assert suggest_lot_number(last_lot=" 4187SNL ", last_date=D(2026, 7, 5), report_date=D(2026, 7, 6)) == "4188SNL"


@pytest.mark.parametrize("last_lot", ["2026-lot3", "SNL4187", "4187-SNL", "lot 12", "4187 SNL", ""])
def test_a_lot_that_is_not_a_counter_is_not_followed(last_lot):
    assert suggest_lot_number(last_lot=last_lot, last_date=D(2026, 7, 5), report_date=D(2026, 7, 6)) is None


def test_there_is_nothing_to_follow_without_an_earlier_lot():
    assert suggest_lot_number(last_lot=None, last_date=None, report_date=D(2026, 7, 6)) is None
    assert suggest_lot_number(last_lot="4187SNL", last_date=None, report_date=D(2026, 7, 6)) is None


def test_a_report_dated_before_the_last_lot_gets_no_guess():
    assert suggest_lot_number(last_lot="4187SNL", last_date=D(2026, 7, 5), report_date=D(2026, 7, 4)) is None


def test_the_default_lot_is_team_year_digit_day_of_year_and_company_code():
    assert default_lot_number(team="B", report_date=D(2026, 1, 1)) == "B6001SNL"
    assert default_lot_number(team="B", report_date=D(2026, 1, 30)) == "B6030SNL"
    assert default_lot_number(team="C", report_date=D(2026, 9, 21)) == "C6264SNL"
    assert default_lot_number(team="A", report_date=D(2026, 12, 31)) == "A6365SNL"


def test_the_default_lot_counts_the_extra_day_of_a_leap_year():
    assert default_lot_number(team="D", report_date=D(2028, 12, 31)) == "D8366SNL"
    assert default_lot_number(team="D", report_date=D(2028, 3, 1)) == "D8061SNL"


def test_the_year_is_its_last_digit():
    assert default_lot_number(team="A", report_date=D(2030, 2, 1)) == "A0032SNL"


@pytest.mark.parametrize(
    "team, letter",
    [("A", "A"), ("b", "B"), (" C ", "C"), ("Équipe B", "B"), ("Team D", "D"), ("équipe-c", "C"), ("Equipe A.", None)],
)
def test_the_team_letter_is_read_from_what_the_team_typed(team, letter):
    assert team_letter(team) == letter


@pytest.mark.parametrize("team", [None, "", "   ", "E", "AB", "Alpha", "Équipe 2", "Équipe B nuit"])
def test_no_team_letter_when_the_team_does_not_name_one_of_a_to_d(team):
    assert team_letter(team) is None


def test_there_is_no_default_lot_without_a_team_letter():
    assert default_lot_number(team=None, report_date=D(2026, 9, 21)) is None
    assert default_lot_number(team="Alpha", report_date=D(2026, 9, 21)) is None
