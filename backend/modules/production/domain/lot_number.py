"""Lot numbers as the plant writes them.

A finished-goods lot is a running counter with a fixed suffix (`4187SNL`), one per
production day: every shift of that day's sheet carries the same lot, and the counter
moves on by one for each calendar day -- a day the line did not run still uses up its
number, so the gap between two lots is the number of days between them, days off and
maintenance days included.

The app only ever *suggests* the next one. Nothing here decides a lot number: a plant
that numbers differently, or skipped one, types its own and the suggestion follows.

A shift's own lot is written from what the shift records -- its team, its date and the
plant's code (`B6030SNL`: team B, 2026, the 30th day of the year) -- and only fills the
box a person is free to overwrite.
"""
from __future__ import annotations

import datetime
import re

_LOT = re.compile(r"^(\d+)([A-Za-z]*)$")

# The plant's code on every lot, after the counter.
COMPANY_CODE = "SNL"

# The team's letter is the last word of what was typed in the header ("B", "Équipe B"); a
# name that ends in anything else names no team this rule knows.
_TEAM_LETTER = re.compile(r"(?:^|[^0-9A-Za-z])([A-Da-d])$")


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


def team_letter(team: str | None) -> str | None:
    """The team's letter, A to D, read from the header's free text; None when it names none."""
    match = _TEAM_LETTER.search((team or "").strip())
    return match.group(1).upper() if match else None


def default_lot_number(*, team: str | None, report_date: datetime.date) -> str | None:
    """The lot a shift's rows start with: team letter, last digit of the year, day of the
    year over three digits, then the plant's code. None while the team names no letter --
    a letter is never guessed."""
    letter = team_letter(team)
    if letter is None:
        return None
    return f"{letter}{report_date.year % 10}{report_date.timetuple().tm_yday:03d}{COMPANY_CODE}"
