from __future__ import annotations

import datetime
from dataclasses import dataclass

from core.domain.result import Err, Ok, Result


@dataclass(frozen=True)
class StockReservation:
    id: str
    tenant_id: str
    product_id: str
    location_id: str
    reference: str
    quantity: float
    quantity_open: float
    status: str
    expires_at: datetime.datetime | None
    created_by: str | None
    created_at: datetime.datetime
    closed_at: datetime.datetime | None


def validate_reservation_expiry(*, expires_at: datetime.datetime, now: datetime.datetime) -> Result[None]:
    """An expiry must be an absolute instant (a naive datetime is ambiguous on
    a server in another timezone) and in the future -- a hold that is already
    lapsed would be released by the next worker tick, which is just a
    confusing way to not reserve."""
    if expires_at.tzinfo is None:
        return Err(
            "INVALID_EXPIRY",
            "expires_at must include a timezone",
            "expires_at doit inclure un fuseau horaire",
        )
    if expires_at <= now:
        return Err("INVALID_EXPIRY", "expires_at must be in the future", "expires_at doit être dans le futur")
    return Ok(None)


def expiry_release_quantity(*, quantity_open: float, quantity_reserved_now: float) -> float:
    """How much an expiring reservation can actually give back. The counter
    on stock_items is authoritative; an admin overwrite can have lowered it
    below what the ledger still thinks is open, and releasing more than is
    reserved would fail the whole sweep over one stale row."""
    return max(0.0, min(quantity_open, quantity_reserved_now))
