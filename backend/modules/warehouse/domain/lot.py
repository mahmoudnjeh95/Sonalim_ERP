from __future__ import annotations

import datetime
from dataclasses import dataclass

from core.domain.result import Err, Ok, Result

LOT_VALID_TRANSITIONS = {
    "active": {"consumed", "expired"},
    "consumed": set(),
    "expired": set(),
}


@dataclass(frozen=True)
class Lot:
    id: str
    tenant_id: str
    product_id: str
    lot_number: str
    status: str
    expiry_date: str | None
    produced_at: str | None
    source_type: str | None
    source_id: str | None


def validate_lot_number(*, lot_number: str) -> Result[None]:
    """A lot's identity, independent of any stock arriving in it.

    Registering a lot and receiving into it are separate acts: production names a
    lot and its expiry date when a conditionnement report is validated, while the
    quantity that lands in it is a stock movement of its own.
    """
    if not lot_number.strip():
        return Err("INVALID_LOT_NUMBER", "lot_number is required", "lot_number est obligatoire")
    return Ok(None)


def validate_expiry_date(*, expiry_date: datetime.date, produced_at: str | None) -> Result[None]:
    """A DLC is the last day the product is good, so it cannot fall before the day the lot
    was made. Checked only when the lot says when it was made -- a lot received from a
    supplier has no production day to compare against."""
    if produced_at is not None and expiry_date < datetime.datetime.fromisoformat(produced_at).date():
        return Err(
            "INVALID_EXPIRY",
            "the expiry date cannot be before the day the lot was produced",
            "la DLC ne peut pas être antérieure au jour de production du lot",
        )
    return Ok(None)


def validate_new_lot(*, lot_number: str, quantity: float) -> Result[None]:
    number = validate_lot_number(lot_number=lot_number)
    if isinstance(number, Err):
        return number
    if quantity <= 0:
        return Err("INVALID_QUANTITY", "initial lot quantity must be positive", "la quantité initiale du lot doit être positive")
    return Ok(None)


def transition_lot(lot: Lot, new_status: str) -> Result[Lot]:
    if new_status not in LOT_VALID_TRANSITIONS.get(lot.status, set()):
        return Err(
            "INVALID_TRANSITION",
            f"cannot move lot from {lot.status} to {new_status}",
            f"impossible de faire passer le lot de {lot.status} à {new_status}",
        )
    return Ok(
        Lot(
            id=lot.id,
            tenant_id=lot.tenant_id,
            product_id=lot.product_id,
            lot_number=lot.lot_number,
            status=new_status,
            expiry_date=lot.expiry_date,
            produced_at=lot.produced_at,
            source_type=lot.source_type,
            source_id=lot.source_id,
        )
    )


@dataclass(frozen=True)
class LotStock:
    lot_id: str
    location_id: str
    quantity_on_hand: float


def receive_into_lot(stock: LotStock, quantity: float) -> Result[LotStock]:
    if quantity <= 0:
        return Err("INVALID_QUANTITY", "received quantity must be positive", "la quantité reçue doit être positive")
    return Ok(LotStock(lot_id=stock.lot_id, location_id=stock.location_id, quantity_on_hand=stock.quantity_on_hand + quantity))


def issue_from_lot(stock: LotStock, quantity: float) -> Result[LotStock]:
    if quantity <= 0:
        return Err("INVALID_QUANTITY", "issued quantity must be positive", "la quantité sortie doit être positive")
    if quantity > stock.quantity_on_hand:
        return Err(
            "INSUFFICIENT_STOCK",
            f"cannot issue {quantity}, only {stock.quantity_on_hand} on hand in lot {stock.lot_id}",
            f"impossible de sortir {quantity}, seulement {stock.quantity_on_hand} en stock dans le lot {stock.lot_id}",
        )
    return Ok(LotStock(lot_id=stock.lot_id, location_id=stock.location_id, quantity_on_hand=stock.quantity_on_hand - quantity))
