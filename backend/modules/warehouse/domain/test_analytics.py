from __future__ import annotations

import pytest

from modules.warehouse.domain.analytics import (
    COVERAGE_CRITICAL_DAYS,
    COVERAGE_WARNING_DAYS,
    average_daily_consumption,
    coverage,
    is_dormant,
    signed_quantity,
    stock_value,
)


def test_signed_quantity_follows_direction_of_move_type():
    assert signed_quantity("receipt", 10) == 10
    assert signed_quantity("production", 10) == 10
    assert signed_quantity("transfer_in", 10) == 10
    assert signed_quantity("issue", 10) == -10
    assert signed_quantity("production_consumption", 10) == -10
    assert signed_quantity("send_to_production", 10) == -10
    assert signed_quantity("transfer_out", 10) == -10


def test_corrections_keep_their_own_sign():
    assert signed_quantity("adjustment", -3) == -3
    assert signed_quantity("adjustment", 3) == 3
    assert signed_quantity("admin_correction", -7.5) == -7.5


def test_reservations_never_touch_on_hand():
    assert signed_quantity("reservation", 10) == 0
    assert signed_quantity("reservation_released", 10) == 0


def test_average_daily_consumption_divides_over_the_window():
    assert average_daily_consumption(300, 30) == 10
    assert average_daily_consumption(0, 30) == 0
    assert average_daily_consumption(-5, 30) == 0


def test_average_daily_consumption_rejects_an_empty_window():
    with pytest.raises(ValueError):
        average_daily_consumption(10, 0)


def test_coverage_status_bands():
    critical = coverage(on_hand=50, consumed_quantity=300, window_days=30)  # 5 days
    assert critical.status == "critical"
    assert critical.days_of_cover == pytest.approx(5)
    assert critical.days_of_cover < COVERAGE_CRITICAL_DAYS

    warning = coverage(on_hand=150, consumed_quantity=300, window_days=30)  # 15 days
    assert warning.status == "warning"
    assert COVERAGE_CRITICAL_DAYS <= warning.days_of_cover < COVERAGE_WARNING_DAYS

    ok = coverage(on_hand=900, consumed_quantity=300, window_days=30)  # 90 days
    assert ok.status == "ok"
    assert ok.days_of_cover >= COVERAGE_WARNING_DAYS


def test_coverage_of_an_empty_shelf_is_out_whatever_the_rate():
    assert coverage(on_hand=0, consumed_quantity=300, window_days=30).status == "out"
    assert coverage(on_hand=-4, consumed_quantity=0, window_days=30).status == "out"
    assert coverage(on_hand=0, consumed_quantity=300, window_days=30).days_of_cover == 0


def test_coverage_of_unused_stock_is_idle_not_infinite():
    idle = coverage(on_hand=200, consumed_quantity=0, window_days=30)
    assert idle.status == "idle"
    assert idle.days_of_cover is None
    assert idle.avg_daily_consumption == 0


def test_dormant_needs_stock_on_hand():
    assert not is_dormant(on_hand=0, idle_days=400, dormant_after_days=60)
    assert is_dormant(on_hand=10, idle_days=60, dormant_after_days=60)
    assert not is_dormant(on_hand=10, idle_days=59, dormant_after_days=60)


def test_stock_that_never_moved_counts_as_dormant():
    assert is_dormant(on_hand=10, idle_days=None, dormant_after_days=60)


def test_stock_value_is_none_without_a_cost():
    assert stock_value(10, None) is None
    assert stock_value(10, 0) is None
    assert stock_value(10, 250) == 2500
