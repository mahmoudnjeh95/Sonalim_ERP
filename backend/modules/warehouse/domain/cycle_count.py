from __future__ import annotations

import datetime
from dataclasses import dataclass

from core.domain.result import Err, Ok, Result


@dataclass(frozen=True)
class CycleCount:
    id: str
    tenant_id: str
    site_id: str
    scope_location_id: str | None
    count_type: str
    status: str
    scheduled_for: datetime.date | None
    started_at: datetime.datetime | None
    completed_at: datetime.datetime | None
    created_by: str
    created_at: datetime.datetime
    number: str | None = None
    # full freezes its scope and corrects the stock; interim does neither and only records the variances.
    mode: str = "full"
    note: str | None = None


@dataclass(frozen=True)
class CycleCountLine:
    id: str
    tenant_id: str
    cycle_count_id: str
    location_id: str
    product_id: str
    expected_quantity: float | None  # None when redacted for a pending blind-count line
    counted_quantity: float | None
    status: str
    resolution: str | None
    counted_by: str | None
    counted_at: datetime.datetime | None
    resolved_by: str | None
    resolved_at: datetime.datetime | None
    # The raw counts as entered, in order; counted_quantity is the settled figure and stays None
    # until they settle (see settle_counts). Whoever reads an unsettled line gets only how many
    # counts were entered, never their values: a second count must not be able to copy the first.
    count_1: float | None = None
    count_2: float | None = None
    count_3: float | None = None
    counts_recorded: int = 0
    observation: str | None = None


CYCLE_COUNT_VALID_TRANSITIONS = {
    "draft": {"in_progress", "cancelled"},
    "in_progress": {"completed", "cancelled"},
    "completed": set(),
    "cancelled": set(),
}


def transition_cycle_count(status: str, new_status: str) -> Result[str]:
    if new_status not in CYCLE_COUNT_VALID_TRANSITIONS.get(status, set()):
        return Err(
            "INVALID_TRANSITION",
            f"cannot move cycle count from {status} to {new_status}",
            f"impossible de faire passer l'inventaire de {status} à {new_status}",
        )
    return Ok(new_status)


def validate_counted_quantity(quantity: float) -> Result[None]:
    if quantity < 0:
        return Err("INVALID_QUANTITY", "counted quantity cannot be negative", "la quantité comptée ne peut pas être négative")
    return Ok(None)


def resolve_count(*, expected_quantity: float, counted_quantity: float) -> str | None:
    """A count that matches the books needs no decision -- only a real variance
    is left for a supervisor to approve or reject."""
    return "matched" if counted_quantity == expected_quantity else None


def check_decision(*, mode: str, decision: str, observation: str | None) -> Result[None]:
    """A variance always needs an observation. A full inventory approves or rejects it; an interim one
    changes no stock, so it can only note it."""
    allowed = ("note",) if mode == "interim" else ("approve", "reject")
    if decision not in allowed:
        return Err("INVALID_DECISION", f"decision must be one of {', '.join(allowed)}", f"la décision doit être parmi {', '.join(allowed)}")
    if not observation or not observation.strip():
        return Err("OBSERVATION_REQUIRED", "a variance needs an observation", "un écart exige une observation")
    return Ok(None)


def settle_counts(count_1: float | None, count_2: float | None, count_3: float | None) -> float | None:
    """The settled quantity of a line, or None while it needs another count.

    Two equal counts settle a line; two different ones need a third, which then decides. A first
    count never settles, even when it matches the books: the books are compared only afterwards, so
    the counter learns nothing from entering a figure. The variance of a settled line is
    settled - expected, positive when more was found than the books say."""
    if count_1 is None or count_2 is None:
        return None
    return count_1 if count_1 == count_2 else count_3
