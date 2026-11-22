"""Payables ageing: how late each open supplier invoice is against its due date. Pure functions, no database.

Supplier invoices have one due date (no instalments), so an invoice is either not yet due or wholly late."""
from __future__ import annotations

import datetime
from decimal import Decimal

# (key, first day late, last day late) -- "not_due" covers everything not yet late.
BUCKETS = (("not_due", None, 0), ("1_30", 1, 30), ("31_60", 31, 60), ("61_90", 61, 90), ("over_90", 91, None))


def days_overdue(due_date: datetime.date | None, today: datetime.date) -> int:
    """0 when there is no due date or it has not passed."""
    if due_date is None or due_date >= today:
        return 0
    return (today - due_date).days


def bucket_for(days_late: int) -> str:
    for key, first, last in BUCKETS:
        if days_late <= 0:
            return "not_due"
        if first is not None and days_late >= first and (last is None or days_late <= last):
            return key
    return "over_90"


def empty_buckets() -> dict[str, Decimal]:
    return {f"bucket_{key}": Decimal("0") for key, _, _ in BUCKETS}
