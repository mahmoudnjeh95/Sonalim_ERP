import datetime

import pytest

from modules.production.domain.lot_number import suggest_lot_number

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
