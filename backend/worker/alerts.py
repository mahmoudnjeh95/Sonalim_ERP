"""Operator alerts: the dead-letter queue and refused automatic postings.

Every ALERT_CHECK_INTERVAL_SECONDS the worker reads how many messages sit in the dead-letter queue
and how many posting failures are open per tenant, publishes both as Prometheus gauges, and calls
`send_alert` when either grew past what was already announced (`GrowthWatch`). Tenants' own users
are told about posting failures in-app by finance itself (`PostingFailureService.record`)."""
from __future__ import annotations

import logging
import os
import time
from typing import Callable

import pika
from prometheus_client import Gauge

from core.db import get_connection
from core.events.consumers import DEAD_LETTER_QUEUE
from core.observability import GrowthWatch, report_exception, send_alert
from modules.finance.api.posting_failure_service import PostingFailureService

logger = logging.getLogger("erp.worker.alerts")

ALERT_CHECK_INTERVAL_SECONDS = int(os.environ.get("ALERT_CHECK_INTERVAL_SECONDS", "300"))

DEAD_LETTERS = Gauge("erp_dead_letter_messages", "Messages waiting in the dead-letter queue")
POSTING_FAILURES = Gauge("erp_posting_failures_open", "Open refused automatic postings", ["tenant"])


def dead_letter_count(rabbitmq_url: str) -> int:
    connection = pika.BlockingConnection(pika.URLParameters(rabbitmq_url))
    try:
        # Same declaration as consume_forever's (idempotent), so the first round, which may run
        # before the consumer has started, does not fail on a queue that does not exist yet.
        frame = connection.channel().queue_declare(queue=DEAD_LETTER_QUEUE, durable=True)
        return frame.method.message_count
    finally:
        connection.close()


def open_posting_failures() -> dict[str, int]:
    with get_connection() as db_connection:
        return PostingFailureService(db_connection).open_counts_by_tenant()


class AlertMonitor:
    def __init__(
        self,
        *,
        read_dead_letters: Callable[[], int],
        read_posting_failures: Callable[[], dict[str, int]],
        alert: Callable[..., None] = send_alert,
    ) -> None:
        self._read_dead_letters = read_dead_letters
        self._read_posting_failures = read_posting_failures
        self._alert = alert
        self._watch = GrowthWatch()
        self._tenants_seen: set[str] = set()

    def check(self) -> None:
        """One round. Each source is read on its own, so a broker outage still lets postings be watched."""
        try:
            count = self._read_dead_letters()
        except Exception as error:  # reported, retried next round
            report_exception(error, where="alert_monitor", source="dead_letter_queue")
        else:
            DEAD_LETTERS.set(count)
            if self._watch.check("dead_letters", count):
                self._alert(
                    "Dead-letter queue growing",
                    f"{count} event(s) in {DEAD_LETTER_QUEUE} failed in a consumer and were not processed. "
                    "The worker log (or Sentry) has the error for each one.",
                    {"queue": DEAD_LETTER_QUEUE, "messages": count},
                )
        try:
            counts = self._read_posting_failures()
        except Exception as error:  # reported, retried next round
            report_exception(error, where="alert_monitor", source="posting_failures")
            return
        for tenant_id in self._tenants_seen | set(counts):
            value = counts.get(tenant_id, 0)
            POSTING_FAILURES.labels(tenant=tenant_id).set(value)
            if self._watch.check(f"posting_failures:{tenant_id}", value):
                self._alert(
                    "Automatic postings refused",
                    f"Tenant {tenant_id} has {value} open refused posting(s) in finance.posting_failures "
                    "(Finance > Entries lists them, with the reason and a retry button).",
                    {"tenant_id": tenant_id, "open_failures": value},
                )
        self._tenants_seen |= set(counts)


def run_alert_monitor(rabbitmq_url: str) -> None:
    logger.info("Alert monitor started (every %s s)", ALERT_CHECK_INTERVAL_SECONDS)
    monitor = AlertMonitor(
        read_dead_letters=lambda: dead_letter_count(rabbitmq_url),
        read_posting_failures=open_posting_failures,
    )
    while True:
        monitor.check()
        time.sleep(ALERT_CHECK_INTERVAL_SECONDS)
