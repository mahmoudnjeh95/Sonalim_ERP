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
from modules.finance.api.dunning_service import DunningService
from modules.maintenance.api.program_service import ProgramService
from modules.scan.api.claude_reader import ClaudeReader
from modules.scan.api.ocr_client import OcrClient
from modules.scan.api.reader import read_next_page, requeue_stale_reads
from modules.warehouse.api.replenishment_service import ReplenishmentService
from modules.warehouse.api.reservation_service import ReservationService

# Imported for the side effect of registering their event handlers with core.events.consumers.
from modules.finance.events import consumers as _finance_consumers  # noqa: F401
from modules.finance.events import ledger_consumers as _finance_ledger_consumers  # noqa: F401
from modules.hr.events import consumers as _hr_consumers  # noqa: F401
from modules.procurement.events import consumers as _procurement_consumers  # noqa: F401
from modules.finance.events import treasury_consumers as _finance_treasury_consumers  # noqa: F401
from modules.procurement.events import treasury_consumers as _procurement_treasury_consumers  # noqa: F401
from modules.production.events import consumers as _production_consumers  # noqa: F401
from modules.sales.events import consumers as _sales_consumers  # noqa: F401
from modules.warehouse.events import consumers as _warehouse_consumers  # noqa: F401

# West Africa (BCEAO/XOF) is UTC+0 with no DST, so this compares directly against UTC.
EXCHANGE_RATE_ROLLOVER_HOUR_UTC = 18
RESERVATION_EXPIRY_INTERVAL_SECONDS = 60
REPLENISHMENT_INTERVAL_SECONDS = 900
MAINTENANCE_SWEEP_INTERVAL_SECONDS = int(os.environ.get("MAINTENANCE_SWEEP_INTERVAL_SECONDS", "3600"))
DUNNING_SWEEP_INTERVAL_SECONDS = int(os.environ.get("DUNNING_SWEEP_INTERVAL_SECONDS", "3600"))
SCAN_READER_IDLE_SECONDS = 2
SCAN_READER_RETRY_SECONDS = 15


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


def run_maintenance_programs() -> None:
    """Materialises every tenant's due preventive-program occurrences into jobs and
    raises the overdue notice for the ones nobody has acted on. An hourly cadence is
    plenty: a program's own `lead_days` is what decides how far ahead a job appears,
    so running more often only matters at the margin of that one-hour slack. A user
    can always trigger the same sweep for their tenant from `POST /programs/run-due`."""
    print("Maintenance program sweep started", flush=True)
    while True:
        try:
            with get_connection() as db_connection:
                service = ProgramService(db_connection)
                created = 0
                overdue = 0
                for tenant_id in service.tenants_to_sweep():
                    result = service.run_due(tenant_id=tenant_id, today=datetime.date.today())
                    created += result["created"]
                    overdue += result["overdue_notified"]
                db_connection.commit()
            if created or overdue:
                print(f"Maintenance sweep: created {created} job(s), notified {overdue} overdue job(s)", flush=True)
        except Exception as error:  # retried next tick, never kills the thread
            print(f"Maintenance program sweep failed: {error}", flush=True)
        time.sleep(MAINTENANCE_SWEEP_INTERVAL_SECONDS)


def run_dunning() -> None:
    """Settles promises to pay whose date passed and tells the people who chase about customers reaching a
    new dunning level. Each customer and level is announced once, so the hourly cadence only bounds how
    soon after midnight a new day's lateness shows up. `POST /finance/dunning/run` does the same on demand."""
    print("Dunning sweep started", flush=True)
    while True:
        try:
            with get_connection() as db_connection:
                service = DunningService(db_connection)
                totals = {"promises_broken": 0, "levels_announced": 0}
                for tenant_id in service.tenants_to_run():
                    result = service.run(tenant_id=tenant_id, today=datetime.date.today())
                    for key in totals:
                        totals[key] += result[key]
                db_connection.commit()
            if any(totals.values()):
                print(f"Dunning sweep: {totals['levels_announced']} level(s) announced, {totals['promises_broken']} promise(s) broken", flush=True)
        except Exception as error:  # retried next tick, never kills the thread
            print(f"Dunning sweep failed: {error}", flush=True)
        time.sleep(DUNNING_SWEEP_INTERVAL_SECONDS)


def run_scan_reader(readers: dict) -> None:
    """Has each scan's reader (the OCR container or Claude) read the queued photos, one at a
    time, in their own thread so a slow page never holds up the event consumers."""
    print(f"Scan reader started ({', '.join(readers)})", flush=True)
    try:
        with get_connection() as db_connection:
            requeued = requeue_stale_reads(db_connection)
        if requeued:
            print(f"Scan reader: put {requeued} interrupted page(s) back in the queue", flush=True)
    except Exception as error:  # a startup DB hiccup must not silently kill the reader thread
        print(f"Scan reader: requeue of stale reads failed at startup: {error}", flush=True)
    while True:
        try:
            with get_connection() as db_connection:
                step = read_next_page(db_connection, readers)
        except Exception as error:  # retried next tick, never kills the thread
            print(f"Scan reader failed: {error}", flush=True)
            step = ("", "retry")
        if step is None:
            time.sleep(SCAN_READER_IDLE_SECONDS)
        elif step[1] in ("retry", "failed"):
            time.sleep(SCAN_READER_RETRY_SECONDS)


def run() -> None:
    migrate_on_startup()
    rabbitmq_url = os.environ["RABBITMQ_URL"]
    threading.Thread(target=run_outbox_dispatcher, args=(rabbitmq_url,), daemon=True).start()
    threading.Thread(target=run_exchange_rate_rollover, daemon=True).start()
    threading.Thread(target=run_reservation_expiry, daemon=True).start()
    threading.Thread(target=run_replenishment, daemon=True).start()
    threading.Thread(target=run_maintenance_programs, daemon=True).start()
    threading.Thread(target=run_dunning, daemon=True).start()
    # Each scan picks its reader in the UI: the local OCR container (OCR_URL) or Claude
    # (CLAUDE_API_KEY, the photos are sent to the Anthropic API). Both run when configured.
    readers = {}
    if os.environ.get("OCR_URL"):
        readers["ocr"] = OcrClient(os.environ["OCR_URL"]).read
    if os.environ.get("CLAUDE_API_KEY", "").strip():
        readers["claude"] = ClaudeReader(os.environ["CLAUDE_API_KEY"].strip()).read
    if readers:
        threading.Thread(target=run_scan_reader, args=(readers,), daemon=True).start()
    else:
        print("Neither OCR_URL nor CLAUDE_API_KEY set: scanned photos stay queued until one is", flush=True)
    event_consumers.consume_forever(rabbitmq_url)


if __name__ == "__main__":
    run()
