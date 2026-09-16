from __future__ import annotations

import json

import pika
import psycopg

EXCHANGE = "erp.events"


def dispatch_pending(connection: psycopg.Connection, channel: pika.adapters.blocking_connection.BlockingChannel) -> int:
    """Publishes pending outbox rows to the broker and marks them sent, in one DB transaction."""
    rows = connection.execute(
        """
        SELECT event_id, event_type, payload
        FROM events.outbox
        WHERE sent_at IS NULL
        ORDER BY created_at
        LIMIT 100
        FOR UPDATE SKIP LOCKED
        """
    ).fetchall()

    for event_id, event_type, payload in rows:
        channel.basic_publish(
            exchange=EXCHANGE,
            routing_key=event_type,
            body=json.dumps(payload).encode(),
            properties=pika.BasicProperties(
                message_id=event_id,
                content_type="application/json",
                delivery_mode=2,
            ),
        )
        connection.execute(
            "UPDATE events.outbox SET sent_at = NOW() WHERE event_id = %s",
            (event_id,),
        )

    connection.commit()
    return len(rows)
