"""Load a month of sales orders and their invoices, through the real services, so Sales and Finance have history.

    cd backend
    PYTHONPATH=. .venv/Scripts/python.exe scripts/seed_sales_finance_month.py --dry-run
    PYTHONPATH=. .venv/Scripts/python.exe scripts/seed_sales_finance_month.py

Orders are placed for the existing customers against the finished-goods store, only for products that hold
stock there (confirming reserves it). Most are confirmed; the newest may still be drafts. Each confirmed order
gets its invoice the way the finance consumer would make it (the event worker is not running in dev), and the
older invoices are issued and then paid. Timestamps are back-dated so the history reads as a month of work.

The confirm events are marked as already sent, so a worker started later does not invoice these orders twice.
Product selling prices are set where they are still 0 (demo prices in F CFA).

Test data, generated from a fixed seed. It skips itself when orders older than the first hand-made one exist.
"""
from __future__ import annotations

import datetime
import random
from collections import Counter

from ulid import ULID

from core.domain.result import Err
from modules.finance.api.service import InvoiceService
from modules.sales.api.service import SalesOrderService
from modules.sales.domain.entities import OrderLine
from scripts.seed_common import FIRST_DAY, TENANT, TODAY, actor_id, business_time, clamp_to_now, run, working_days

# Demo selling prices per pack in F CFA (XOF, the plant's currency), and the pack counts a customer orders at a
# time. Confirming reserves stock and nothing here ships it, so the counts are kept small enough that the month
# leaves most of the stock free.
CATALOGUE = {
    "doman-pl-500g": dict(price=372, quantities=range(4000, 30001, 1000)),
    "doman-pc-500g": dict(price=348, quantities=range(1000, 5001, 500)),
    "COQ6-500G": dict(price=360, quantities=range(1000, 5001, 500)),
    "doman-pc-200g": dict(price=162, quantities=range(2000, 8001, 500)),
}
# Distributors buy more often than the small accounts.
CUSTOMER_WEIGHT = {
    "Global Foods Distribution": 4, "Mediterra Retail Group": 4, "comalim": 3, "Acme Corp": 2, "polina": 1, "Tarek Fassi": 1,
}
HAND_MADE_FROM = datetime.datetime(2026, 9, 15)


def plan_orders() -> list[tuple[datetime.date, random.Random]]:
    """One (day, rng) per order; the day's rng also drives everything else about that order."""
    planned = []
    for day in working_days(FIRST_DAY, TODAY):
        rng = random.Random(f"sales-{day.isoformat()}")
        for n in range(rng.choices([0, 1, 2, 3], weights=[1, 4, 4, 2])[0]):
            planned.append((day, random.Random(f"sales-{day.isoformat()}-{n}")))
    return planned


def invoice_track(rng: random.Random, confirmed_at: datetime.datetime) -> list[tuple[str, datetime.datetime]]:
    """The statuses an invoice went through and when. Nothing is dated after today."""
    age = (TODAY - confirmed_at.date()).days
    track: list[tuple[str, datetime.datetime]] = []
    if age <= 4 and rng.random() < 0.7:
        return track
    issued_at = confirmed_at + datetime.timedelta(days=rng.randint(0, 2), hours=rng.randint(1, 5))
    if issued_at.date() > TODAY:
        return track
    track.append(("issued", issued_at))
    paid_at = issued_at + datetime.timedelta(days=rng.randint(4, 16), hours=rng.randint(0, 6))
    if paid_at.date() <= TODAY and rng.random() < 0.85:
        track.append(("paid", paid_at))
    return track


def work(conn, args) -> int:
    if conn.execute("SELECT 1 FROM sales.orders WHERE tenant_id = %s AND created_at < %s", (TENANT, HAND_MADE_FROM)).fetchone():
        print("older orders already exist; skipping")
        return 0
    actor = actor_id(conn)
    location = conn.execute("SELECT id FROM warehouse.locations WHERE tenant_id = %s AND code = 'produits-finis'", (TENANT,)).fetchone()[0]
    products = dict(conn.execute("SELECT sku, id FROM core.products WHERE tenant_id = %s AND sku = ANY(%s)", (TENANT, list(CATALOGUE))).fetchall())
    customers = {name: pid for name, pid in conn.execute(
        "SELECT name, id FROM core.partners WHERE tenant_id = %s AND kind = 'customer'", (TENANT,)).fetchall() if name in CUSTOMER_WEIGHT}
    for sku, spec in CATALOGUE.items():
        conn.execute("UPDATE core.products SET selling_price = %s WHERE id = %s AND (selling_price IS NULL OR selling_price = 0)", (spec["price"], products[sku]))

    sales, invoices = SalesOrderService(conn), InvoiceService(conn)
    names = sorted(customers)
    outcomes: Counter = Counter()
    for day, rng in plan_orders():
        created_at = business_time(rng, day, 8, 16)
        customer = customers[rng.choices(names, weights=[CUSTOMER_WEIGHT[n] for n in names])[0]]
        chosen = rng.sample(sorted(CATALOGUE), k=rng.choice([1, 1, 2, 2, 3]))
        lines = [OrderLine(product_id=products[sku], quantity=float(rng.choice(CATALOGUE[sku]["quantities"])),
                           unit_price=float(round(CATALOGUE[sku]["price"] * rng.uniform(0.94, 1.0)))) for sku in chosen]
        ship_by = day + datetime.timedelta(days=rng.randint(3, 14))
        age = (TODAY - day).days
        stays_draft = rng.random() < (0.5 if age <= 3 else 0.04)

        with conn.transaction():
            order = sales.create_order(tenant_id=TENANT, actor_id=actor, partner_id=customer, location_id=location, lines=lines, requested_ship_date=ship_by)
            trail = [("sales_order.created", order.id, created_at)]
            correlations: list[str] = []
            if not stays_draft:
                correlation = str(ULID())
                confirmed = sales.confirm_order(tenant_id=TENANT, actor_id=actor, order_id=order.id, correlation_id=correlation)
                if isinstance(confirmed, Err):
                    outcomes[f"left draft ({confirmed.code})"] += 1
                else:
                    correlations.append(correlation)
                    confirmed_at = clamp_to_now(created_at + datetime.timedelta(hours=rng.randint(1, 5), minutes=rng.randint(0, 59)))
                    trail.append(("sales_order.confirmed", order.id, confirmed_at))
                    invoice = invoices.create_draft_invoice(
                        tenant_id=TENANT, partner_id=customer, amount=order.total_amount, currency="XOF", source_order_id=order.id, actor_id=actor)
                    trail.append(("invoice.created", invoice.id, confirmed_at))
                    conn.execute("UPDATE finance.invoices SET created_at = %s WHERE id = %s", (confirmed_at, invoice.id))
                    conn.execute("UPDATE warehouse.stock_moves SET created_at = %s WHERE reference = %s", (confirmed_at, f"sales_order:{order.id}"))
                    final = "draft"
                    for status, moment in invoice_track(rng, confirmed_at):
                        correlation = str(ULID())
                        step = (invoices.issue_invoice if status == "issued" else invoices.mark_paid)(
                            tenant_id=TENANT, actor_id=actor, invoice_id=invoice.id, correlation_id=correlation)
                        if isinstance(step, Err):
                            break
                        correlations.append(correlation)
                        trail.append((f"invoice.{status}", invoice.id, moment))
                        final = status
                    outcomes[f"confirmed, invoice {final}"] += 1
            if stays_draft:
                outcomes["draft"] += 1

            conn.execute("UPDATE sales.orders SET created_at = %s WHERE id = %s", (created_at, order.id))
            for action, entity_id, moment in trail:
                conn.execute("UPDATE core.audit_log SET occurred_at = %s WHERE entity_id = %s AND action = %s", (moment, entity_id, action))
            moments = {a: m for a, _, m in trail}
            for correlation, action in zip(correlations, ["sales_order.confirmed", "invoice.issued", "invoice.paid"]):
                # The outbox rows share the order's timeline, and are marked sent so no worker replays them.
                conn.execute("UPDATE events.outbox SET created_at = %s, sent_at = %s WHERE correlation_id = %s",
                             (moments[action], moments[action] + datetime.timedelta(seconds=1), correlation))

    print("orders by outcome:", dict(outcomes))
    for label, sql in [("orders", "SELECT status, count(*) FROM sales.orders GROUP BY 1"), ("invoices", "SELECT status, count(*) FROM finance.invoices GROUP BY 1")]:
        print(f"{label} now:", conn.execute(sql).fetchall())
    return 0


if __name__ == "__main__":
    raise SystemExit(run(__doc__, work))
