from __future__ import annotations

import datetime

from core.domain.result import Err, Ok
from modules.warehouse.domain.reservation import expiry_release_quantity, validate_reservation_expiry

NOW = datetime.datetime(2026, 9, 28, 12, 0, tzinfo=datetime.timezone.utc)


def test_a_future_aware_expiry_is_accepted():
    assert validate_reservation_expiry(expires_at=NOW + datetime.timedelta(hours=1), now=NOW) == Ok(None)


def test_a_past_expiry_is_refused():
    result = validate_reservation_expiry(expires_at=NOW - datetime.timedelta(seconds=1), now=NOW)
    assert isinstance(result, Err) and result.code == "INVALID_EXPIRY"


def test_a_naive_expiry_is_refused():
    result = validate_reservation_expiry(expires_at=datetime.datetime(2030, 1, 1), now=NOW)
    assert isinstance(result, Err) and result.code == "INVALID_EXPIRY"


def test_expiry_releases_what_is_open():
    assert expiry_release_quantity(quantity_open=5, quantity_reserved_now=20) == 5


def test_expiry_never_releases_more_than_the_counter_holds():
    assert expiry_release_quantity(quantity_open=5, quantity_reserved_now=3) == 3
    assert expiry_release_quantity(quantity_open=5, quantity_reserved_now=0) == 0
