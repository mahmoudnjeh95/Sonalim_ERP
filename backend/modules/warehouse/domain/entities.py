from __future__ import annotations

from dataclasses import dataclass

from core.domain.result import Err, Ok, Result

INSUFFICIENT_STOCK = "INSUFFICIENT_STOCK"


LOCATION_TYPES = frozenset({"zone", "aisle", "rack", "bin"})


@dataclass(frozen=True)
class Location:
    id: str
    code: str
    name: str
    site_id: str
    # Every pre-existing location became a "bin" directly under its tenant's
    # synthetic default site when the hierarchy was introduced -- "bin" is the
    # leaf level stock actually lives at, so it is the right default for a
    # plain location nobody has placed in a zone/aisle/rack yet.
    location_type: str = "bin"
    parent_location_id: str | None = None
    sequence: int | None = None
    # A blocked location holds stock that exists but must not be promised —
    # quarantine above all. Excluded from available quantity.
    is_blocked: bool = False
    blocked_reason: str | None = None


@dataclass(frozen=True)
class Site:
    id: str
    tenant_id: str
    code: str
    name: str
    address: str | None = None
    is_active: bool = True


@dataclass(frozen=True)
class StockLevel:
    location_id: str
    product_id: str
    quantity_on_hand: float
    quantity_reserved: float
    quantity_in_production: float = 0.0

    @property
    def quantity_available(self) -> float:
        return self.quantity_on_hand - self.quantity_reserved


def reserve(level: StockLevel, quantity: float) -> Result[StockLevel]:
    if quantity <= 0:
        return Err("INVALID_QUANTITY", "reservation quantity must be positive", "la quantité de réservation doit être positive")
    if quantity > level.quantity_available:
        return Err(
            INSUFFICIENT_STOCK,
            f"requested {quantity}, available {level.quantity_available}",
            f"quantité demandée {quantity}, quantité disponible {level.quantity_available}",
        )
    return Ok(
        StockLevel(
            location_id=level.location_id,
            product_id=level.product_id,
            quantity_on_hand=level.quantity_on_hand,
            quantity_reserved=level.quantity_reserved + quantity,
            quantity_in_production=level.quantity_in_production,
        )
    )


def release_reservation(level: StockLevel, quantity: float) -> Result[StockLevel]:
    """Releases a previously-made reservation back to available on-hand stock —
    the mirror image of reserve(). Does not touch quantity_on_hand."""
    if quantity <= 0:
        return Err("INVALID_QUANTITY", "released quantity must be positive", "la quantité libérée doit être positive")
    if quantity > level.quantity_reserved:
        return Err(
            INSUFFICIENT_STOCK,
            f"cannot release {quantity}, only {level.quantity_reserved} reserved",
            f"impossible de libérer {quantity}, seulement {level.quantity_reserved} réservé",
        )
    return Ok(
        StockLevel(
            location_id=level.location_id,
            product_id=level.product_id,
            quantity_on_hand=level.quantity_on_hand,
            quantity_reserved=level.quantity_reserved - quantity,
            quantity_in_production=level.quantity_in_production,
        )
    )


def receive(level: StockLevel, quantity: float) -> Result[StockLevel]:
    if quantity <= 0:
        return Err("INVALID_QUANTITY", "received quantity must be positive", "la quantité reçue doit être positive")
    return Ok(
        StockLevel(
            location_id=level.location_id,
            product_id=level.product_id,
            quantity_on_hand=level.quantity_on_hand + quantity,
            quantity_reserved=level.quantity_reserved,
            quantity_in_production=level.quantity_in_production,
        )
    )


def issue(level: StockLevel, quantity: float) -> Result[StockLevel]:
    """Removes physically-consumed stock (a "sortie") from on-hand quantity."""
    if quantity <= 0:
        return Err("INVALID_QUANTITY", "issued quantity must be positive", "la quantité sortie doit être positive")
    if quantity > level.quantity_on_hand:
        return Err(
            INSUFFICIENT_STOCK,
            f"cannot issue {quantity}, only {level.quantity_on_hand} on hand",
            f"impossible de sortir {quantity}, seulement {level.quantity_on_hand} en stock",
        )
    return Ok(
        StockLevel(
            location_id=level.location_id,
            product_id=level.product_id,
            quantity_on_hand=level.quantity_on_hand - quantity,
            quantity_reserved=level.quantity_reserved,
            quantity_in_production=level.quantity_in_production,
        )
    )


def adjust(level: StockLevel, delta: float) -> Result[StockLevel]:
    """Applies a manual correction ("ajustement") of arbitrary sign to on-hand quantity."""
    if delta == 0:
        return Err("INVALID_QUANTITY", "adjustment delta must be non-zero", "l'écart d'ajustement doit être non nul")
    new_on_hand = level.quantity_on_hand + delta
    if new_on_hand < 0:
        return Err(
            "INVALID_QUANTITY",
            f"adjustment would take on-hand quantity negative ({new_on_hand})",
            f"cet ajustement rendrait la quantité en stock négative ({new_on_hand})",
        )
    return Ok(
        StockLevel(
            location_id=level.location_id,
            product_id=level.product_id,
            quantity_on_hand=new_on_hand,
            quantity_reserved=level.quantity_reserved,
            quantity_in_production=level.quantity_in_production,
        )
    )


def send_to_production(level: StockLevel, quantity: float) -> Result[StockLevel]:
    """Moves stock out of on-hand into the "en production" (WIP) bucket — called when
    a work order is created with poured raw-material quantities."""
    if quantity <= 0:
        return Err(
            "INVALID_QUANTITY", "quantity sent to production must be positive", "la quantité envoyée en production doit être positive"
        )
    if quantity > level.quantity_on_hand:
        return Err(
            INSUFFICIENT_STOCK,
            f"cannot send {quantity} to production, only {level.quantity_on_hand} on hand",
            f"impossible d'envoyer {quantity} en production, seulement {level.quantity_on_hand} en stock",
        )
    return Ok(
        StockLevel(
            location_id=level.location_id,
            product_id=level.product_id,
            quantity_on_hand=level.quantity_on_hand - quantity,
            quantity_reserved=level.quantity_reserved,
            quantity_in_production=level.quantity_in_production + quantity,
        )
    )


def consume_in_production(level: StockLevel, quantity: float) -> Result[StockLevel]:
    """Fully consumes stock previously sent to "en production", once the work order
    that poured it completes. This is final consumption, not a reservation release."""
    if quantity <= 0:
        return Err("INVALID_QUANTITY", "consumed quantity must be positive", "la quantité consommée doit être positive")
    if quantity > level.quantity_in_production:
        return Err(
            INSUFFICIENT_STOCK,
            f"cannot consume {quantity}, only {level.quantity_in_production} in production",
            f"impossible de consommer {quantity}, seulement {level.quantity_in_production} en production",
        )
    return Ok(
        StockLevel(
            location_id=level.location_id,
            product_id=level.product_id,
            quantity_on_hand=level.quantity_on_hand,
            quantity_reserved=level.quantity_reserved,
            quantity_in_production=level.quantity_in_production - quantity,
        )
    )
