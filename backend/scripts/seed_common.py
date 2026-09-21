"""What the month seeders (sales/finance, QC, CRM, production gaps) share: the demo tenant, the acting user,
the seed window, and the dry-run wrapper. Dev-only, like the rest of scripts/."""
from __future__ import annotations

import argparse
import datetime
import random
from typing import Callable

from core.db import get_connection

TENANT = "demo"
ACTOR_EMAIL = "demo@sonalim-erp.local"
FIRST_DAY = datetime.date(2026, 8, 20)
TODAY = datetime.date(2026, 9, 21)


def actor_id(conn) -> str:
    return conn.execute("SELECT id FROM core.users WHERE email = %s", (ACTOR_EMAIL,)).fetchone()[0]


def working_days(first: datetime.date = FIRST_DAY, last: datetime.date = TODAY) -> list[datetime.date]:
    """Every day of the window except Sundays; the plant does not book or inspect on those."""
    days = [first + datetime.timedelta(days=n) for n in range((last - first).days + 1)]
    return [day for day in days if day.weekday() != 6]


def business_time(rng: random.Random, day: datetime.date, start_hour: int = 8, end_hour: int = 17) -> datetime.datetime:
    minutes = rng.randint(start_hour * 60, end_hour * 60 - 1)
    return datetime.datetime.combine(day, datetime.time(minutes // 60, minutes % 60, rng.randint(0, 59)))


def clamp_to_now(moment: datetime.datetime) -> datetime.datetime:
    """A history row can never be dated after the seed ran on `TODAY`."""
    return min(moment, datetime.datetime.combine(TODAY, datetime.time(15, 0)))


def run(description: str, work: Callable[[object, argparse.Namespace], int]) -> int:
    """Open one connection, hand it to `work`, then commit, or roll everything back on --dry-run."""
    parser = argparse.ArgumentParser(description=description, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="do everything, then roll it all back")
    args = parser.parse_args()
    with get_connection() as conn:
        status = work(conn, args)
        if args.dry_run:
            conn.rollback()
            print("DRY RUN: everything above was rolled back")
        else:
            conn.commit()
    return status


def stamp_audit(conn, entity_id: str, moment: datetime.datetime) -> None:
    """Date the audit rows the last service call wrote for `entity_id`.

    Every row written in one transaction carries the transaction's own NOW(), so the rows not yet stamped are
    exactly the ones at or after it, and moving them into the past takes them out of that set for the next call.
    """
    conn.execute("UPDATE core.audit_log SET occurred_at = %s WHERE entity_id = %s AND occurred_at >= now()", (moment, entity_id))


def stamp_events(conn, correlation_id: str, moment: datetime.datetime) -> None:
    conn.execute("UPDATE events.outbox SET created_at = %s WHERE correlation_id = %s", (moment, correlation_id))
