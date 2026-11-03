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
    # The raw counts as entered, in order. counted_quantity is the settled figure and stays None
    # until the counts settle (see settle_counts).
    count_1: float | None = None
    count_2: float | None = None
    count_3: float | None = None


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


def settle_counts(
    expected_quantity: float, count_1: float | None, count_2: float | None, count_3: float | None
) -> tuple[float | None, bool]:
    """Returns (settled quantity, more_counts_needed).

    A first count that agrees with the books settles at once. Otherwise two equal counts settle the
    line; two different ones need a third, which then decides. The variance of a settled line is
    settled - expected, positive when more was found than the books say."""
    if count_1 is None:
        return None, True
    if count_2 is None:
        return (count_1, False) if count_1 == expected_quantity else (None, True)
    if count_1 == count_2:
        return count_1, False
    if count_3 is None:
        return None, True
    return count_3, False
