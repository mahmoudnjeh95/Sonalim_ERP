"""Loan instalments: the principal split in whole francs, the remainder on the last instalment."""
from __future__ import annotations

import datetime
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Instalment:
    seq: int
    period: datetime.date
    amount: Decimal


def add_months(period: datetime.date, months: int) -> datetime.date:
    index = period.year * 12 + (period.month - 1) + months
    return datetime.date(index // 12, index % 12 + 1, 1)


def instalment_schedule(principal: Decimal, count: int, first_period: datetime.date) -> list[Instalment]:
    if count < 1 or principal < count:
        raise ValueError("a loan needs at least one instalment of at least one franc")
    each = principal // count
    last = principal - each * (count - 1)
    return [
        Instalment(seq=number + 1, period=add_months(first_period, number), amount=last if number == count - 1 else each)
        for number in range(count)
    ]
