"""hr reacts to payroll: while a payroll run of a month is approved, that month's presence
cannot be reopened. Phase 3 publishes these events; until it ships the handlers never fire.

Idempotent twice over: the registry skips an event_id a consumer already processed, and the
handlers are no-ops on a repeat (insert on conflict do nothing / delete).
"""
from __future__ import annotations

import datetime

import psycopg

from core.events.consumers import register

APPROVED_CONSUMER = "hr.payroll_run_approved"
REVERSED_CONSUMER = "hr.payroll_run_reversed"


def _period(payload: dict) -> datetime.date:
    return datetime.date.fromisoformat(str(payload["period"])[:10])


def _handle_run_approved(connection: psycopg.Connection, envelope: dict) -> None:
    payload = envelope["payload"]
    connection.execute(
        """
        INSERT INTO hr.presence_month_payroll_locks (tenant_id, run_id, period) VALUES (%s, %s, %s)
        ON CONFLICT (tenant_id, run_id) DO NOTHING
        """,
        (envelope["tenant_id"], payload["run_id"], _period(payload)),
    )


def _handle_run_reversed(connection: psycopg.Connection, envelope: dict) -> None:
    connection.execute(
        "DELETE FROM hr.presence_month_payroll_locks WHERE tenant_id = %s AND run_id = %s",
        (envelope["tenant_id"], envelope["payload"]["run_id"]),
    )


register(APPROVED_CONSUMER, "payroll.run.approved", _handle_run_approved)
register(REVERSED_CONSUMER, "payroll.run.reversed", _handle_run_reversed)
