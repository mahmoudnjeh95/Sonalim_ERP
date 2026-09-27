from datetime import date

from core.domain.result import Ok
from modules.hr.domain.alerts import expiry_state, validate_horizons, window_end

TODAY = date(2026, 9, 25)


def test_no_horizon_means_no_window_and_the_window_includes_its_last_day():
    assert window_end(TODAY, None) is None
    assert window_end(TODAY, 30) == date(2026, 10, 25)


def test_window_end_never_raises_even_for_a_horizon_that_cannot_be_a_real_date():
    assert window_end(TODAY, 3_000_000) == date.max
    assert window_end(TODAY, 10**18) == date.max
    assert window_end(date.max, 1) == date.max  # today itself already at the edge


def test_a_horizon_is_a_positive_number_of_days_or_nothing():
    empty = {"contract_expiry_horizon_days": None, "trial_end_horizon_days": None, "document_expiry_horizon_days": None}
    assert isinstance(validate_horizons(empty), Ok)
    assert validate_horizons({**empty, "trial_end_horizon_days": 0}).code == "INVALID_SETTING"
    assert validate_horizons({**empty, "contract_expiry_horizon_days": -5}).code == "INVALID_SETTING"


def test_a_horizon_whose_end_date_is_not_representable_is_refused_not_capped():
    # No invented threshold (e.g. a 3650-day cap): only what genuinely cannot be a date is
    # refused. 3_000_000 days (~8219 years) from today already overflows datetime.date.max.
    empty = {"contract_expiry_horizon_days": None, "trial_end_horizon_days": None, "document_expiry_horizon_days": None}
    refused = validate_horizons({**empty, "contract_expiry_horizon_days": 3_000_000}, today=TODAY)
    assert refused.code == "INVALID_SETTING" and refused.message_fr
    refused_huge = validate_horizons({**empty, "trial_end_horizon_days": 10**18}, today=TODAY)
    assert refused_huge.code == "INVALID_SETTING"
    # A horizon that keeps the resulting date inside range, however large the number of days
    # looks, is not refused: it is the reachability of the date that matters, not the count.
    reachable_from_far_past = validate_horizons({**empty, "document_expiry_horizon_days": 300_000}, today=date(1, 1, 1))
    assert isinstance(reachable_from_far_past, Ok)


def test_expiry_state_is_a_fact_when_past_and_a_judgement_only_inside_a_set_horizon():
    assert expiry_state(date(2026, 9, 24), TODAY, 30) == "expired"
    assert expiry_state(date(2026, 9, 24), TODAY, None) == "expired"
    assert expiry_state(date(2026, 9, 25), TODAY, 30) == "expiring"
    assert expiry_state(date(2026, 10, 25), TODAY, 30) == "expiring"
    assert expiry_state(date(2026, 10, 26), TODAY, 30) == "valid"
    assert expiry_state(date(2026, 10, 1), TODAY, None) == "valid"
    assert expiry_state(None, TODAY, 30) is None
