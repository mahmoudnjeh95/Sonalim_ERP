"""Which days a pay period covers and which contract payroll pays from. Pure rules, no database."""
from __future__ import annotations

import datetime
from collections.abc import Sequence


def month_bounds(period: datetime.date) -> tuple[datetime.date, datetime.date]:
    if period.day != 1:
        raise ValueError(f"a pay period is the first day of a month, not {period.isoformat()}")
    next_month = (period.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
    return period, next_month - datetime.timedelta(days=1)


def pick_contract(contracts: Sequence[dict], first: datetime.date, last: datetime.date) -> dict | None:
    """Of the contracts touching [first, last], the one that starts last (after an amendment in
    the month, the new terms)."""
    touching = [c for c in contracts if c["start_date"] <= last and (c["end_date"] is None or c["end_date"] >= first)]
    return max(touching, key=lambda c: c["start_date"], default=None)
