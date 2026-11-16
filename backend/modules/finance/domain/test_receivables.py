import datetime
from decimal import Decimal

from modules.finance.domain.receivables import DEFAULT_LEVELS, bucket_for, credit_check, invoice_position, level_reached

D = Decimal
TODAY = datetime.date(2026, 6, 30)


def _day(offset: int) -> datetime.date:
    return TODAY + datetime.timedelta(days=offset)


def test_an_invoice_not_yet_due_owes_nothing_late():
    position = invoice_position(total=D("1000"), credited=D("0"), paid=D("0"), installments=[(_day(5), D("1000"))], today=TODAY)
    assert position.remaining == D("1000") and position.overdue == 0 and position.days_overdue == 0 and position.next_due == _day(5)


def test_due_today_is_not_yet_late():
    position = invoice_position(total=D("1000"), credited=D("0"), paid=D("0"), installments=[(TODAY, D("1000"))], today=TODAY)
    assert position.overdue == 0


def test_payments_settle_the_oldest_installment_first():
    installments = [(_day(-40), D("500")), (_day(-10), D("500")), (_day(20), D("1000"))]
    position = invoice_position(total=D("2000"), credited=D("0"), paid=D("600"), installments=installments, today=TODAY)
    assert position.remaining == D("1400")
    assert position.overdue == D("400") and position.oldest_due == _day(-10) and position.days_overdue == 10
    assert position.next_due == _day(20)


def test_a_credit_note_shrinks_every_installment():
    installments = [(_day(-30), D("500")), (_day(30), D("500"))]
    position = invoice_position(total=D("1000"), credited=D("500"), paid=D("0"), installments=installments, today=TODAY)
    assert position.remaining == D("500") and position.overdue == D("250") and position.days_overdue == 30


def test_a_paid_invoice_or_under_one_franc_is_settled():
    paid = invoice_position(total=D("1000.5"), credited=D("0"), paid=D("1000"), installments=[(_day(-50), D("1000.5"))], today=TODAY)
    assert paid.remaining == 0 and paid.overdue == 0 and paid.oldest_due is None


def test_buckets_follow_the_days_late():
    assert [bucket_for(d) for d in (0, 1, 30, 31, 60, 61, 90, 91, 400)] == [
        "not_due", "1_30", "1_30", "31_60", "31_60", "61_90", "61_90", "over_90", "over_90"]


LEVELS = [{"level": l, "days_after_due": d, "name_fr": fr, "name_en": en, "blocks_orders": b}
          for l, d, fr, en, b, _lf, _le in DEFAULT_LEVELS]


def test_the_level_reached_is_the_highest_delay_passed():
    assert level_reached(LEVELS, 0) is None
    assert level_reached(LEVELS, 6) is None
    assert level_reached(LEVELS, 7)["level"] == 1
    assert level_reached(LEVELS, 29)["level"] == 2
    assert level_reached(LEVELS, 45)["level"] == 4 and level_reached(LEVELS, 45)["blocks_orders"]


def _check(**overrides):
    values = dict(credit_limit=D("1000"), exposure=D("0"), order_amount=D("0"), max_days_overdue=0,
                  block_overdue_days=None, blocking_level=None, warn_ratio=D("0.9"))
    values.update(overrides)
    return credit_check(**values)


def test_no_limit_and_nothing_late_passes():
    check = _check(credit_limit=None, exposure=D("1000000"), order_amount=D("500000"))
    assert check.blocking == [] and check.warnings == []


def test_over_the_limit_blocks_and_near_it_warns():
    assert [c for c, _, _ in _check(exposure=D("800"), order_amount=D("201")).blocking] == ["OVER_CREDIT_LIMIT"]
    near = _check(exposure=D("800"), order_amount=D("150"))
    assert near.blocking == [] and [c for c, _, _ in near.warnings] == ["NEAR_CREDIT_LIMIT"]
    assert _check(exposure=D("800"), order_amount=D("200")).blocking == []  # exactly the limit is allowed


def test_lateness_beyond_the_tenant_delay_blocks_only_when_the_rule_is_on():
    assert _check(max_days_overdue=60).blocking == []
    assert [c for c, _, _ in _check(max_days_overdue=31, block_overdue_days=30).blocking] == ["OVERDUE_INVOICES"]
    assert _check(max_days_overdue=30, block_overdue_days=30).blocking == []


def test_a_blocking_dunning_level_blocks_and_every_reason_is_in_french_too():
    check = _check(blocking_level=LEVELS[3], exposure=D("2000"), max_days_overdue=50, block_overdue_days=30)
    assert [c for c, _, _ in check.blocking] == ["OVER_CREDIT_LIMIT", "OVERDUE_INVOICES", "DUNNING_BLOCK"]
    assert all(fr and fr != en for _, en, fr in check.blocking)
