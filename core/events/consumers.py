from __future__ import annotations

import json
from typing import Callable

import pika
import psycopg

from core.db import get_connection

EXCHANGE = "erp.events"
DEAD_LETTER_EXCHANGE = "erp.events.dlx"
QUEUE_NAME = "erp.worker.consumers"
DEAD_LETTER_QUEUE = "erp.events.dlq"

Handler = Callable[[psycopg.Connection, dict], None]

_registry: dict[str, list[tuple[str, Handler]]] = {}


def register(consumer_name: str, event_type: str, handler: Handler) -> None:
    """Registers a handler for an event type. consumer_name is the idempotency key in events.processed_events."""
    _registry.setdefault(event_type, []).append((consumer_name, handler))


def _process(connection: psycopg.Connection, envelope: dict) -> bool:
    """Runs every handler registered for this event. Returns False if any handler raised."""
    event_id = envelope["event_id"]
    event_type = envelope["event_type"]

    for consumer_name, handler in _registry.get(event_type, []):
        already_processed = connection.execute(
            "SELECT 1 FROM events.processed_events WHERE event_id = %s AND consumer = %s",
            (event_id, consumer_name),
        ).fetchone()
        if already_processed:
            continue
        try:
            handler(connection, envelope)
            connection.execute(
                "INSERT INTO events.processed_events (event_id, consumer) VALUES (%s, %s)",
                (event_id, consumer_name),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            return False
    return True


def consume_forever(rabbitmq_url: str) -> None:
    connection = pika.BlockingConnection(pika.URLParameters(rabbitmq_url))
    channel = connection.channel()
    channel.exchange_declare(exchange=EXCHANGE, exchange_type="topic", durable=True)
    channel.exchange_declare(exchange=DEAD_LETTER_EXCHANGE, exchange_type="fanout", durable=True)

    channel.queue_declare(queue=DEAD_LETTER_QUEUE, durable=True)
    channel.queue_bind(queue=DEAD_LETTER_QUEUE, exchange=DEAD_LETTER_EXCHANGE)

    channel.queue_declare(
        queue=QUEUE_NAME,
        durable=True,
        arguments={"x-dead-letter-exchange": DEAD_LETTER_EXCHANGE},
    )
    for event_type in _registry:
        channel.queue_bind(queue=QUEUE_NAME, exchange=EXCHANGE, routing_key=event_type)

    def on_message(ch, method, properties, body: bytes) -> None:
        envelope = json.loads(body)
        with get_connection() as db_connection:
            succeeded = _process(db_connection, envelope)
        if succeeded:
            ch.basic_ack(delivery_tag=method.delivery_tag)
        else:
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

    channel.basic_consume(queue=QUEUE_NAME, on_message_callback=on_message)
    print("Event consumer started", flush=True)
    channel.start_consuming()
