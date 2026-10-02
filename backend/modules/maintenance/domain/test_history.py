"""Pure rules of a machine's history: status intervals and the indicator formulas."""
from __future__ import annotations

import datetime

from core.domain.result import Err
from modules.maintenance.domain.history import (
    Immobilisation,
    StatusChange,
    chain_in_order,
    immobilisation,
    maintenance_block,
    outcome_counts,
    period_bounds,
    production_block,
    status_at_start,
    validate_journal_filters,
    validate_period,
)

UTC = datetime.timezone.utc


def at(month: int, day: int, hour: int = 0) -> datetime.datetime:
    return datetime.datetime(2026, month, day, hour, tzinfo=UTC)


START, END = at(9, 1), at(9, 11)  # ten days = 14 400 minutes
DAY = 24 * 60


def change(when, from_status, to_status):
    return StatusChange(at=when, from_status=from_status, to_status=to_status)


def test_the_last_change_before_the_period_decides_the_start_status():
    changes = [change(at(8, 20), "operational", "down")]
    assert status_at_start(changes, START, "operational") == "down"
    assert immobilisation(changes, START, END, "operational") == Immobilisation(minutes=10 * DAY, episodes=1)


def test_without_an_earlier_change_the_first_change_tells_the_start_status():
    changes = [change(at(9, 5), "down", "operational")]
    assert status_at_start(changes, START, "operational") == "down"
    assert immobilisation(changes, START, END, "operational") == Immobilisation(minutes=4 * DAY, episodes=1)


def test_a_machine_that_never_changed_keeps_its_current_status():
    assert immobilisation([], START, END, "operational") == Immobilisation(minutes=0, episodes=0)
    assert immobilisation([], START, END, "maintenance") == Immobilisation(minutes=10 * DAY, episodes=1)


def test_down_then_maintenance_is_one_episode():
    changes = [
        change(at(9, 2), "operational", "down"),
        change(at(9, 3), "down", "maintenance"),
        change(at(9, 4), "maintenance", "operational"),
    ]
    assert immobilisation(changes, START, END, "operational") == Immobilisation(minutes=2 * DAY, episodes=1)


def test_two_stoppages_are_two_episodes_and_an_open_one_runs_to_the_end():
    changes = [
        change(at(9, 2), "operational", "down"),
        change(at(9, 3), "down", "operational"),
        change(at(9, 9), "operational", "maintenance"),
    ]
    assert immobilisation(changes, START, END, "maintenance") == Immobilisation(minutes=3 * DAY, episodes=2)


def test_changes_made_in_one_transaction_follow_their_chain_not_their_listing_order():
    # A cancel moves maintenance -> operational -> down in one transaction: both rows carry the
    # same NOW(), and their ids give no reliable order.
    same = at(9, 4, 10)
    listed = [
        change(at(9, 2), "operational", "maintenance"),
        change(same, "operational", "down"),
        change(same, "maintenance", "operational"),
    ]
    ordered = chain_in_order(listed)
    assert [(c.from_status, c.to_status) for c in ordered] == [
        ("operational", "maintenance"), ("maintenance", "operational"), ("operational", "down"),
    ]
    # the machine stays stopped from the 2nd to the end of the period: one stoppage, never released
    assert immobilisation(ordered, START, END, "down") == Immobilisation(minutes=9 * DAY, episodes=1)


def test_a_same_instant_group_with_nothing_before_starts_where_no_other_change_ends():
    same = at(9, 4, 10)
    ordered = chain_in_order([change(same, "operational", "down"), change(same, "maintenance", "operational")])
    assert [(c.from_status, c.to_status) for c in ordered] == [("maintenance", "operational"), ("operational", "down")]


def test_period_bounds_stop_at_now_and_a_future_period_is_empty():
    now = at(9, 10, 12)
    assert period_bounds(datetime.date(2026, 9, 1), datetime.date(2026, 9, 30), now) == (at(9, 1), now)
    start, end = period_bounds(datetime.date(2026, 10, 1), datetime.date(2026, 10, 31), now)
    assert start == end == at(10, 1)


def test_a_reversed_period_and_unknown_filters_are_refused():
    refused = validate_period(datetime.date(2026, 9, 30), datetime.date(2026, 9, 1))
    assert isinstance(refused, Err) and refused.code == "INVALID_PERIOD" and refused.message_fr
    assert validate_period(datetime.date(2026, 9, 1), datetime.date(2026, 9, 1)) is None
    assert validate_journal_filters("preventive", "closed") is None
    assert validate_journal_filters(None, "all") is None
    assert validate_journal_filters("emergency", "closed").code == "INVALID_FILTER"
    assert validate_journal_filters(None, "open").code == "INVALID_FILTER"


def _stop(minutes, downtime_type, classification=None):
    return {"minutes": minutes, "downtime_type": downtime_type, "classification": classification}


def test_production_block_counts_only_corrective_stops_as_breakdowns():
    block = production_block(
        [_stop(30, "corrective", "mechanical"), _stop(20, "corrective", "electric"), _stop(15, "preventive"), _stop(10, None)],
        running_minutes=600,
    )
    assert (block["stops"], block["stop_minutes"], block["breakdowns"], block["breakdown_minutes"]) == (4, 75, 2, 50)
    assert (block["mtbf_minutes"], block["mttr_minutes"]) == (300, 25)
    assert block["breakdowns_by_system"] == [
        {"classification": "mechanical", "count": 1, "minutes": 30},
        {"classification": "electric", "count": 1, "minutes": 20},
    ]
    assert {"type": None, "count": 1, "minutes": 10} in block["stops_by_type"]


def test_without_a_breakdown_mtbf_and_mttr_are_unknown_not_infinite():
    block = production_block([_stop(15, "preventive")], running_minutes=600)
    assert (block["breakdowns"], block["mtbf_minutes"], block["mttr_minutes"]) == (0, None, None)


def _maintenance(**overrides):
    arguments = dict(
        breakdowns=2, due=4, closed=3, closed_on_time=2, overdue=1,
        stopped=Immobilisation(minutes=400, episodes=2), calendar_minutes=14_400, technician_seconds=3_600,
        issued_lines=1, purchase_lines=1, parts_cost=12_000.0, parts_unvalued_quantity=0.0, status_changes=4,
    )
    arguments.update(overrides)
    return maintenance_block(**arguments)


def test_maintenance_block_formulas():
    block = _maintenance()
    assert block["preventive"] == {"due": 4, "closed": 3, "closed_on_time": 2, "overdue": 1}
    assert (block["immobilised_minutes"], block["immobilisations"], block["mean_immobilisation_minutes"]) == (400, 2, 200)
    assert block["calendar_mtbf_minutes"] == (14_400 - 400) / 2
    assert block["parts"] == {"issued_lines": 1, "purchase_lines": 1}


def test_maintenance_block_without_breakdowns_or_stoppages():
    block = _maintenance(breakdowns=0, stopped=Immobilisation(minutes=0, episodes=0))
    assert (block["calendar_mtbf_minutes"], block["mean_immobilisation_minutes"]) == (None, None)


def test_outcome_counts_count_unrecorded_checks_as_pending():
    assert outcome_counts(["ok", "ok", "issue"], checks_total=5) == {"ok": 2, "issue": 1, "not_done": 0, "pending": 2}
