from __future__ import annotations

import calendar
from datetime import date, timedelta

from core.domain.result import Err, Ok, Result

INTERVAL_UNITS = ("day", "week", "month")

# A machine's round every 100 years is already past any plant's horizon, and beyond this the
# date math runs out of year (date's maximum is 9999), which would surface as an opaque 500
# instead of a refusal the user can read. Same ceiling for every unit, the strictest case
# being "month" (1200 months = 100 years from a start date near the end of date's range).
MAX_INTERVAL_VALUE = 1200


def validate_program(*, interval_value: int, interval_unit: str, lead_days: int, name: str) -> Result[None]:
    if interval_value < 1:
        return Err(
            "INVALID_INTERVAL",
            "interval_value must be at least 1",
            "l'intervalle doit être d'au moins 1",
        )
    if interval_value > MAX_INTERVAL_VALUE:
        return Err(
            "INVALID_INTERVAL",
            f"interval_value cannot exceed {MAX_INTERVAL_VALUE}",
            f"l'intervalle ne peut pas dépasser {MAX_INTERVAL_VALUE}",
        )
    if interval_unit not in INTERVAL_UNITS:
        return Err(
            "INVALID_INTERVAL",
            f"interval_unit must be one of {list(INTERVAL_UNITS)}",
            f"l'unité d'intervalle doit être l'une de {list(INTERVAL_UNITS)}",
        )
    if lead_days < 0:
        return Err(
            "INVALID_LEAD_DAYS",
            "lead_days cannot be negative",
            "le délai de préavis ne peut pas être négatif",
        )
    if not name.strip():
        return Err("NAME_REQUIRED", "name is required", "le nom est obligatoire")
    return Ok(None)


def nth_occurrence(start: date, value: int, unit: str, n: int) -> date:
    """The n-th occurrence of the program's recurrence, counting the start date
    itself as occurrence 0. Month arithmetic is computed from `start` each time
    (not by repeatedly adding a month to the previous result), so a clamp on one
    occurrence (Jan 31 -> Feb 28) never carries over to the next (Mar 31 stays
    Mar 31, not Feb 28 + 1 month).
    """
    if unit == "day":
        return start + timedelta(days=value * n)
    if unit == "week":
        return start + timedelta(weeks=value * n)
    if unit == "month":
        total_months = start.month - 1 + value * n
        year = start.year + total_months // 12
        month = total_months % 12 + 1
        day = min(start.day, calendar.monthrange(year, month)[1])
        return date(year, month, day)
    raise ValueError(f"unknown interval unit: {unit}")


def occurrences(start: date, value: int, unit: str, from_date: date, to_date: date) -> list[date]:
    """Every occurrence date in the inclusive window [from_date, to_date], ascending."""
    result: list[date] = []
    n = 0
    occurrence = nth_occurrence(start, value, unit, n)
    # Advance past occurrences before the window without emitting them.
    while occurrence < from_date:
        n += 1
        occurrence = nth_occurrence(start, value, unit, n)
    while occurrence <= to_date:
        result.append(occurrence)
        n += 1
        occurrence = nth_occurrence(start, value, unit, n)
    return result


def due_occurrences(
    start: date,
    value: int,
    unit: str,
    lead_days: int,
    today: date,
    not_before: date,
) -> list[date]:
    """Occurrences whose notice window has opened: date - lead_days <= today,
    i.e. date <= today + lead_days. Never back-fills before `not_before` (the
    program's creation date), and never before the program's own start.
    """
    window_start = max(start, not_before)
    window_end = today + timedelta(days=lead_days)
    if window_start > window_end:
        return []
    return occurrences(start, value, unit, window_start, window_end)


def next_occurrence(start: date, value: int, unit: str, after: date) -> date:
    """The first occurrence on or after `after`."""
    if unit == "day":
        step_days = value
    elif unit == "week":
        step_days = value * 7
    else:
        step_days = None

    if step_days is not None:
        if after <= start:
            return start
        elapsed = (after - start).days
        n = -(-elapsed // step_days)  # ceil division
        return start + timedelta(days=step_days * n)

    n = 0
    occurrence = nth_occurrence(start, value, unit, n)
    while occurrence < after:
        n += 1
        occurrence = nth_occurrence(start, value, unit, n)
    return occurrence
