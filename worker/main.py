from __future__ import annotations

import datetime
import os
import threading
import time

import pika

from core.db import get_connection
from core.events import consumers as event_consumers
from core.events.dispatcher import EXCHANGE, dispatch_pending
from core.exchange_rate_rollover import roll_forward_missing_rates
from core.migrations.runner import apply_all_migrations

# Imported for the side effect of registering their event handlers with core.events.consumers.
from modules.finance.events import consumers as _finance_consumers  # noqa: F401
from modules.warehouse.events import consumers as _warehouse_consumers  # noqa: F401

# West Africa (BCEAO/XOF) is UTC+0 with no DST, so this compares directly against UTC.
EXCHANGE_RATE_ROLLOVER_HOUR_UTC = 18


def run_outbox_dispatcher(rabbitmq_url: str) -> None:
    connection = pika.BlockingConnection(pika.URLParameters(rabbitmq_url))
    channel = connection.channel()
    channel.exchange_declare(exchange=EXCHANGE, exchange_type="topic", durable=True)
    print("Outbox dispatcher started", flush=True)
    while True:
        with get_connection() as db_connection:
            dispatch_pending(db_connection, channel)
        time.sleep(5)


def run_exchange_rate_rollover() -> None:
    print("Exchange rate rollover scheduler started", flush=True)
    last_rolled_date: datetime.date | None = None
    while True:
        now = datetime.datetime.now(datetime.timezone.utc)
        if now.hour >= EXCHANGE_RATE_ROLLOVER_HOUR_UTC and last_rolled_date != now.date():
            with get_connection() as db_connection:
                rolled = roll_forward_missing_rates(db_connection, as_of=now.date())
            print(f"Exchange rate rollover: carried forward {rolled} rate(s) for {now.date()}", flush=True)
            last_rolled_date = now.date()
        time.sleep(300)


def run() -> None:
    apply_all_migrations()
    rabbitmq_url = os.environ["RABBITMQ_URL"]
    threading.Thread(target=run_outbox_dispatcher, args=(rabbitmq_url,), daemon=True).start()
    threading.Thread(target=run_exchange_rate_rollover, daemon=True).start()
    event_consumers.consume_forever(rabbitmq_url)


if __name__ == "__main__":
    run()
