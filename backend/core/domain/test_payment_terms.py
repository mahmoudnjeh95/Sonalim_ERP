import datetime
from decimal import Decimal

from core.domain.payment_terms import DEFAULT_TERMS, Installment, due_date, parse_installments, schedule
from core.domain.result import Err, Ok

D = Decimal
JAN_15 = datetime.date(2026, 1, 15)


def test_net_days_count_from_the_invoice_date():
    assert due_date(JAN_15, Installment(D("100"), 30)) == datetime.date(2026, 2, 14)
    assert due_date(JAN_15, Installment(D("100"), 0)) == JAN_15


def test_end_of_month_moves_to_the_last_day_of_the_month_the_delay_lands_in():
    assert due_date(JAN_15, Installment(D("100"), 30, end_of_month=True)) == datetime.date(2026, 2, 28)
    assert due_date(datetime.date(2028, 1, 15), Installment(D("100"), 30, end_of_month=True)) == datetime.date(2028, 2, 29)


def test_end_of_month_on_the_10th_is_the_10th_of_the_following_month():
    # 15 Jan + 45 days = 1 Mar, end of March, then 10 April.
    assert due_date(JAN_15, Installment(D("100"), 45, end_of_month=True, day_of_month=10)) == datetime.date(2026, 4, 10)


def test_a_day_of_the_month_alone_is_the_next_such_day():
    assert due_date(JAN_15, Installment(D("100"), 0, day_of_month=20)) == datetime.date(2026, 1, 20)
    assert due_date(JAN_15, Installment(D("100"), 0, day_of_month=10)) == datetime.date(2026, 2, 10)
    assert due_date(datetime.date(2026, 1, 31), Installment(D("100"), 0, day_of_month=31)) == datetime.date(2026, 1, 31)
    assert due_date(datetime.date(2026, 2, 1), Installment(D("100"), 0, day_of_month=31)) == datetime.date(2026, 2, 28)


def test_a_split_term_shares_in_whole_francs_and_the_last_share_takes_the_rounding():
    rows = schedule(JAN_15, D("1001"), (Installment(D("50"), 0), Installment(D("50"), 30)))
    assert rows == [(JAN_15, D("501")), (datetime.date(2026, 2, 14), D("500"))]


def test_installments_must_add_up_to_a_hundred_percent():
    assert isinstance(parse_installments([{"percent": 60, "days": 0}, {"percent": 50, "days": 30}]), Err)
    assert isinstance(parse_installments([]), Err)
    assert isinstance(parse_installments([{"percent": 100, "days": -1}]), Err)
    assert isinstance(parse_installments([{"percent": 100, "days": 30, "day_of_month": 32}]), Err)
    parsed = parse_installments([{"percent": "100", "days": "45", "end_of_month": True, "day_of_month": "10"}])
    assert isinstance(parsed, Ok) and parsed.value == (Installment(D("100"), 45, True, 10),)


def test_every_default_term_is_valid():
    for _code, _fr, _en, installments in DEFAULT_TERMS:
        assert isinstance(parse_installments([i.as_dict() for i in installments]), Ok)
