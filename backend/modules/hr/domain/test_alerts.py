from datetime import date

from core.domain.result import Ok
from modules.hr.domain.alerts import expiry_state, validate_horizons, window_end

TODAY = date(2026, 9, 25)


def test_no_horizon_means_no_window_and_the_window_includes_its_last_day():
    assert window_end(TODAY, None) is None
    assert window_end(TODAY, 30) == date(2026, 10, 25)


def test_a_horizon_is_a_positive_number_of_days_or_nothing():
    empty = {"contract_expiry_horizon_days": None, "trial_end_horizon_days": None, "document_expiry_horizon_days": None}
    assert isinstance(validate_horizons(empty), Ok)
    assert validate_horizons({**empty, "trial_end_horizon_days": 0}).code == "INVALID_SETTING"
    assert validate_horizons({**empty, "contract_expiry_horizon_days": -5}).code == "INVALID_SETTING"


def test_expiry_state_is_a_fact_when_past_and_a_judgement_only_inside_a_set_horizon():
    assert expiry_state(date(2026, 9, 24), TODAY, 30) == "expired"
    assert expiry_state(date(2026, 9, 24), TODAY, None) == "expired"
    assert expiry_state(date(2026, 9, 25), TODAY, 30) == "expiring"
    assert expiry_state(date(2026, 10, 25), TODAY, 30) == "expiring"
    assert expiry_state(date(2026, 10, 26), TODAY, 30) == "valid"
    assert expiry_state(date(2026, 10, 1), TODAY, None) == "valid"
    assert expiry_state(None, TODAY, 30) is None
