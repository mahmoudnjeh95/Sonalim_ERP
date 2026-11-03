"""Reading handwritten cells: numbers, times, dates, lots, and text to compare.

Every parser returns a `Parsed`. `value` is None when nothing usable was read; `sure`
is False when the reading had to be bent to fit (an O read as a zero, a stroke read as
a one) or could not be read at all. Nothing here judges whether a value is plausible
for the plant -- only whether the handwriting can be read as that kind of value.
"""
from __future__ import annotations

import calendar
import datetime
import re
import unicodedata
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Parsed:
    value: Any
    sure: bool = True


NOTHING = Parsed(None, True)  # an empty cell: nothing to read, nothing to doubt
UNREADABLE = Parsed(None, False)  # ink that is not a value of this kind

# Characters handwriting and OCR confuse with digits; folded only where a digit is expected.
_LOOKALIKES = str.maketrans({"o": "0", "O": "0", "l": "1", "I": "1", "|": "1"})
_TRAILING_UNIT = re.compile(r"(kgs?|g|t|mn|min|%)$", re.IGNORECASE)
_TIME = re.compile(r"(?<!\d)(\d{1,2})\s*[hH:]\s*(\d{2})?(?!\d)")
_DATE = re.compile(r"(\d{1,2})\s*[/.\-]\s*(\d{1,2})\s*[/.\-]\s*(\d{2,4})")
# 07-0926: the second separator left out.
_DATE_RUN_ON = re.compile(r"(\d{1,2})\s*[/.\-]\s*(\d{2})(\d{2})(?!\d)")
_LOT = re.compile(r"([A-Z])(\d)(\d{3})([A-Z]{2,4})?")
_INTERVAL_SEPARATORS = {"-", "–", "—", "a", "à", "au", "/"}


def normalize(text: str | None) -> str:
    """Lower case, no accents, punctuation as spaces, single spaces: the form compared and learned."""
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", text)
    plain = "".join(c for c in decomposed if not unicodedata.combining(c)).lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", plain).split())


def tokens(text: str | None) -> set[str]:
    """The words of a text, a plural `s` dropped so "Vermicelles" meets "Vermicelle"."""
    return {w[:-1] if len(w) > 3 and w.endswith("s") else w for w in normalize(text).split()}


def _exact(raw: str, folded: str, start: int, end: int) -> bool:
    return raw[start:end] == folded[start:end]


def parse_decimal(text: str | None) -> Parsed:
    raw = (text or "").strip()
    if not raw:
        return NOTHING
    compact = _TRAILING_UNIT.sub("", raw.replace(" ", "").strip("()"))
    folded = compact.translate(_LOOKALIKES)
    candidate = folded.replace(",", ".")
    if not re.fullmatch(r"\d+(\.\d+)?", candidate):
        return UNREADABLE
    return Parsed(float(candidate), folded == compact)


def parse_percent(text: str | None) -> Parsed:
    parsed = parse_decimal(text)
    if parsed.value is not None and parsed.value > 100:
        return UNREADABLE
    return parsed


def parse_int(text: str | None) -> Parsed:
    parsed = parse_decimal(text)
    if parsed.value is None:
        return parsed
    if not float(parsed.value).is_integer():
        return UNREADABLE
    return Parsed(int(parsed.value), parsed.sure)


def _time_matches(text: str) -> list[tuple[re.Match, Parsed]]:
    raw = text or ""
    folded = raw.translate(_LOOKALIKES)
    found = []
    for match in _TIME.finditer(folded):
        hour, minute = int(match[1]), int(match[2] or 0)
        if hour > 23 or minute > 59:
            continue
        found.append((match, Parsed(datetime.time(hour, minute), _exact(raw, folded, match.start(), match.end()))))
    return found


def find_times(text: str | None) -> list[Parsed]:
    """Every time written in the text, in order: 09h27mn, 14h, 12H18, 07:00."""
    return [parsed for _, parsed in _time_matches(text or "")]


def parse_time(text: str | None) -> Parsed:
    if not (text or "").strip():
        return NOTHING
    found = find_times(text)
    return found[0] if len(found) == 1 else UNREADABLE


def find_intervals(text: str | None) -> list[tuple[Parsed, Parsed]]:
    """Pairs of times written from-to (10h43-10h53, 12h56-12h58), in order."""
    raw = text or ""
    matches = _time_matches(raw)
    pairs: list[tuple[Parsed, Parsed]] = []
    index = 0
    while index + 1 < len(matches):
        (first, start), (second, end) = matches[index], matches[index + 1]
        between = raw[first.end():second.start()].strip().lower()
        if between in _INTERVAL_SEPARATORS:
            pairs.append((start, end))
            index += 2
        else:
            index += 1
    return pairs


def parse_date(text: str | None) -> Parsed:
    raw = (text or "").strip()
    if not raw:
        return NOTHING
    folded = raw.translate(_LOOKALIKES)
    for pattern, well_formed in ((_DATE, True), (_DATE_RUN_ON, False)):
        match = pattern.search(folded)
        if match is None:
            continue
        day, month, year = int(match[1]), int(match[2]), int(match[3])
        if year < 100:
            year += 2000
        try:
            value = datetime.date(year, month, day)
        except ValueError:
            return UNREADABLE
        return Parsed(value, well_formed and _exact(raw, folded, match.start(), match.end()))
    return UNREADABLE


def parse_lot(text: str | None) -> Parsed:
    """A lot as the plant writes it: team letter, year digit, day of the year, plant code (D6249SNL).

    A fiche often leaves the plant code off (D6249); the value is then that short form,
    completed later from a full lot on the same fiches. Text that is no lot at all is
    kept, marked unsure, so the user sees what was written.
    """
    raw = (text or "").strip()
    if not raw:
        return NOTHING
    compact = re.sub(r"\s+", "", raw).upper()
    match = _LOT.search(compact)
    if match is None:
        return Parsed(compact, False)
    return Parsed(match.group(0), True)


def is_short_lot(lot: str | None) -> bool:
    return bool(lot) and re.fullmatch(r"[A-Z]\d{4}", lot) is not None


def decode_lot(lot: str | None, around: datetime.date) -> tuple[str, datetime.date] | None:
    """(team letter, date) a lot names, read the way production's default_lot_number writes it.

    The lot carries only the year's last digit; the year is the nearest to `around` ending in it.
    """
    match = re.match(r"([A-Z])(\d)(\d{3})", lot or "")
    if match is None:
        return None
    letter, digit, day = match[1], int(match[2]), int(match[3])
    year = min((y for y in range(around.year - 5, around.year + 6) if y % 10 == digit), key=lambda y: abs(y - around.year))
    if not 1 <= day <= (366 if calendar.isleap(year) else 365):
        return None
    return letter, datetime.date(year, 1, 1) + datetime.timedelta(days=day - 1)


def team_letter(text: str | None) -> str | None:
    """The team letter in a team's name ("Equipe D", "Eq A", "D"), or None."""
    letters = [w for w in normalize(text).split() if len(w) == 1 and w.isalpha()]
    return letters[-1].upper() if len(letters) == 1 else None


def team_and_hours(text: str | None) -> tuple[str | None, datetime.time | None]:
    """What follows "Equipe :" on a fiche -- "D 07 H à 14H00" -- as (team letter, start hour)."""
    words = normalize(text).split()
    letter = words[0].upper() if words and len(words[0]) == 1 and words[0].isalpha() else None
    times = find_times(text)
    return letter, (times[0].value if times else None)


def first_number(text: str | None) -> float | None:
    match = re.search(r"\d+(?:[.,]\d+)?", text or "")
    return float(match.group(0).replace(",", ".")) if match else None


def minutes_between(start: datetime.time, end: datetime.time) -> int:
    """Minutes from start to end, across midnight when end is earlier."""
    return ((end.hour * 60 + end.minute) - (start.hour * 60 + start.minute)) % (24 * 60)
