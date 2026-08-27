from __future__ import annotations

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


def validate_new_lot(*, lot_number: str, quantity: float) -> Result[None]:
    if not lot_number.strip():
        return Err("INVALID_LOT_NUMBER", "lot_number is required")
    if quantity <= 0:
        return Err("INVALID_QUANTITY", "initial lot quantity must be positive")
    return Ok(None)


def transition_lot(lot: Lot, new_status: str) -> Result[Lot]:
    if new_status not in LOT_VALID_TRANSITIONS.get(lot.status, set()):
        return Err("INVALID_TRANSITION", f"cannot move lot from {lot.status} to {new_status}")
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
        return Err("INVALID_QUANTITY", "received quantity must be positive")
    return Ok(LotStock(lot_id=stock.lot_id, location_id=stock.location_id, quantity_on_hand=stock.quantity_on_hand + quantity))


def issue_from_lot(stock: LotStock, quantity: float) -> Result[LotStock]:
    if quantity <= 0:
        return Err("INVALID_QUANTITY", "issued quantity must be positive")
    if quantity > stock.quantity_on_hand:
        return Err(
            "INSUFFICIENT_STOCK", f"cannot issue {quantity}, only {stock.quantity_on_hand} on hand in lot {stock.lot_id}"
        )
    return Ok(LotStock(lot_id=stock.lot_id, location_id=stock.location_id, quantity_on_hand=stock.quantity_on_hand - quantity))
