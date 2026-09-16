from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import psycopg
from psycopg.types.json import Jsonb
from ulid import ULID


def publish_event(
    connection: psycopg.Connection,
    *,
    event_type: str,
    producer: str,
    tenant_id: str,
    correlation_id: str,
    payload: dict[str, Any],
    causation_id: str | None = None,
    event_version: str = "1.0",
) -> str:
    """Inserts an outbox row in the caller's open transaction; the caller commits."""
    event_id = str(ULID())
    envelope = {
        "event_id": event_id,
        "event_type": event_type,
        "event_version": event_version,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "producer": producer,
        "tenant_id": tenant_id,
        "correlation_id": correlation_id,
        "causation_id": causation_id,
        "payload": payload,
    }
    connection.execute(
        """
        INSERT INTO events.outbox (event_id, event_type, payload, tenant_id, correlation_id, causation_id)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (event_id, event_type, Jsonb(envelope), tenant_id, correlation_id, causation_id),
    )
    return event_id
