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
from core.migrations.runner import migrate_on_startup
from modules.warehouse.api.replenishment_service import ReplenishmentService
from modules.warehouse.api.reservation_service import ReservationService

# Imported for the side effect of registering their event handlers with core.events.consumers.
from modules.finance.events import consumers as _finance_consumers  # noqa: F401
from modules.finance.events import ledger_consumers as _finance_ledger_consumers  # noqa: F401
from modules.hr.events import consumers as _hr_consumers  # noqa: F401
from modules.procurement.events import consumers as _procurement_consumers  # noqa: F401
from modules.production.events import consumers as _production_consumers  # noqa: F401
from modules.sales.events import consumers as _sales_consumers  # noqa: F401
from modules.warehouse.events import consumers as _warehouse_consumers  # noqa: F401

# West Africa (BCEAO/XOF) is UTC+0 with no DST, so this compares directly against UTC.
EXCHANGE_RATE_ROLLOVER_HOUR_UTC = 18
RESERVATION_EXPIRY_INTERVAL_SECONDS = 60
REPLENISHMENT_INTERVAL_SECONDS = 900


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


def run_reservation_expiry() -> None:
    """Gives lapsed stock holds back to available stock. Only reservations
    made with an explicit expiry are ever touched -- a confirmed sales order's
    reservation has none."""
    print("Reservation expiry sweep started", flush=True)
    while True:
        try:
            with get_connection() as db_connection:
                expired = ReservationService(db_connection).expire_due_reservations(
                    now=datetime.datetime.now(datetime.timezone.utc)
                )
                db_connection.commit()
            if expired:
                print(f"Reservation expiry: released {len(expired)} lapsed reservation(s)", flush=True)
        except Exception as error:  # a failed sweep is retried next tick, never kills the thread
            print(f"Reservation expiry sweep failed: {error}", flush=True)
        time.sleep(RESERVATION_EXPIRY_INTERVAL_SECONDS)


def run_replenishment() -> None:
    """Evaluates every tenant's reorder rules on a slow cadence -- stock
    levels that matter for purchasing don't change minute to minute, and a
    user can always trigger an evaluation from the Replenishment tab."""
    print("Replenishment evaluation started", flush=True)
    while True:
        try:
            with get_connection() as db_connection:
                service = ReplenishmentService(db_connection)
                raised = 0
                for tenant_id in service.tenants_with_active_rules():
                    raised += len(service.evaluate(tenant_id=tenant_id)["created"])
                db_connection.commit()
            if raised:
                print(f"Replenishment: raised {raised} proposal(s)", flush=True)
        except Exception as error:  # retried next tick, never kills the thread
            print(f"Replenishment evaluation failed: {error}", flush=True)
        time.sleep(REPLENISHMENT_INTERVAL_SECONDS)


def run() -> None:
    migrate_on_startup()
    rabbitmq_url = os.environ["RABBITMQ_URL"]
    threading.Thread(target=run_outbox_dispatcher, args=(rabbitmq_url,), daemon=True).start()
    threading.Thread(target=run_exchange_rate_rollover, daemon=True).start()
    threading.Thread(target=run_reservation_expiry, daemon=True).start()
    threading.Thread(target=run_replenishment, daemon=True).start()
    event_consumers.consume_forever(rabbitmq_url)


if __name__ == "__main__":
    run()
