"""The worker's alert monitor (worker/alerts.py), with fake readers. No broker, no database."""
from __future__ import annotations

from worker.alerts import DEAD_LETTERS, POSTING_FAILURES, AlertMonitor


class _Readings:
    def __init__(self):
        self.dead_letters = 0
        self.failures: dict[str, int] = {}
        self.broker_down = False

    def read_dead_letters(self) -> int:
        if self.broker_down:
            raise ConnectionError("broker unreachable")
        return self.dead_letters


def _monitor(readings: _Readings, alerts: list):
    return AlertMonitor(
        read_dead_letters=readings.read_dead_letters,
        read_posting_failures=lambda: dict(readings.failures),
        alert=lambda title, text, details: alerts.append((title, details)),
    )


def test_dead_letter_growth_alerts_once_per_rise_and_sets_the_gauge():
    readings, alerts = _Readings(), []
    monitor = _monitor(readings, alerts)
    monitor.check()
    assert alerts == []
    readings.dead_letters = 2
    monitor.check()
    monitor.check()
    assert alerts == [("Dead-letter queue growing", {"queue": "erp.events.dlq", "messages": 2})]
    assert DEAD_LETTERS._value.get() == 2


def test_posting_failures_alert_per_tenant_and_the_gauge_returns_to_zero():
    readings, alerts = _Readings(), []
    monitor = _monitor(readings, alerts)
    readings.failures = {"t1": 1}
    monitor.check()
    readings.failures = {"t1": 1, "t2": 3}
    monitor.check()
    assert alerts == [
        ("Automatic postings refused", {"tenant_id": "t1", "open_failures": 1}),
        ("Automatic postings refused", {"tenant_id": "t2", "open_failures": 3}),
    ]
    readings.failures = {"t2": 3}  # t1's failure was retried and posted
    monitor.check()
    assert POSTING_FAILURES.labels(tenant="t1")._value.get() == 0
    assert len(alerts) == 2


def test_a_broker_outage_is_reported_and_postings_are_still_watched(caplog):
    readings, alerts = _Readings(), []
    readings.broker_down = True
    readings.failures = {"t1": 1}
    _monitor(readings, alerts).check()
    assert alerts == [("Automatic postings refused", {"tenant_id": "t1", "open_failures": 1})]
    assert any("source=dead_letter_queue" in record.getMessage() for record in caplog.records)
