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
