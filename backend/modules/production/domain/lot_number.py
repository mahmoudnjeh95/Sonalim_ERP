"""Lot numbers as the plant writes them.

A finished-goods lot is a running counter with a fixed suffix (`4187SNL`), one per
production day: every shift of that day's sheet carries the same lot, and the counter
moves on by one for each calendar day -- a day the line did not run still uses up its
number, so the gap between two lots is the number of days between them, days off and
maintenance days included.

The app only ever *suggests* the next one. Nothing here decides a lot number: a plant
that numbers differently, or skipped one, types its own and the suggestion follows.
"""
from __future__ import annotations

import datetime
import re

_LOT = re.compile(r"^(\d+)([A-Za-z]*)$")


def suggest_lot_number(
    *, last_lot: str | None, last_date: datetime.date | None, report_date: datetime.date
) -> str | None:
    """The lot a report filed on `report_date` most likely carries, given the last lot the
    line filed on or before that day and the day it was filed.

    The suffix and the width of the counter are copied from the last lot rather than
    fixed here, so a plant whose lots read `4187SNL` and one whose read `0042` are both
    followed. Returns None when there is nothing to follow: no earlier lot, or one that
    is not a counter with an optional suffix (a free-text lot such as `2026-lot3`), or
    a last lot dated after the report -- a report filed for an earlier day than the
    line's last lot has no counter to be counted on from.
    """
    if not last_lot or last_date is None:
        return None
    match = _LOT.match(last_lot.strip())
    if match is None:
        return None
    elapsed = (report_date - last_date).days
    if elapsed < 0:
        return None
    digits, suffix = match.groups()
    return f"{int(digits) + elapsed:0{len(digits)}d}{suffix}"
