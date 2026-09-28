from __future__ import annotations

import datetime
from dataclasses import dataclass

from core.domain.result import Err, Ok, Result


@dataclass(frozen=True)
class PickList:
    id: str
    tenant_id: str
    number: str
    source_type: str
    source_id: str
    partner_id: str | None
    location_id: str
    reservation_reference: str
    status: str
    created_at: datetime.datetime
    picked_at: datetime.datetime | None
    cancelled_at: datetime.datetime | None


@dataclass(frozen=True)
class PickListLine:
    id: str
    tenant_id: str
    pick_list_id: str
    product_id: str
    quantity_requested: float
    quantity_picked: float | None
    picked_by: str | None
    picked_at: datetime.datetime | None


@dataclass(frozen=True)
class Shipment:
    id: str
    tenant_id: str
    number: str
    pick_list_id: str
    status: str
    package_count: int
    total_weight_kg: float | None
    carrier: str | None
    tracking_reference: str | None
    packed_by: str
    packed_at: datetime.datetime
    shipped_by: str | None
    shipped_at: datetime.datetime | None


PICK_LIST_VALID_TRANSITIONS = {
    "open": {"picking", "cancelled"},
    "picking": {"picked", "cancelled"},
    "picked": {"shipped", "cancelled"},
    "shipped": set(),
    "cancelled": set(),
}

# A pick can be recorded (or corrected) until picking is closed.
PICKABLE_STATUSES = frozenset({"open", "picking"})


def transition_pick_list(status: str, new_status: str) -> Result[str]:
    if new_status not in PICK_LIST_VALID_TRANSITIONS.get(status, set()):
        return Err(
            "INVALID_TRANSITION",
            f"cannot move pick list from {status} to {new_status}",
            f"impossible de faire passer la liste de prélèvement de {status} à {new_status}",
        )
    return Ok(new_status)


def aggregate_order_lines(lines: list[dict]) -> dict[str, float]:
    """One pick line per product: an order that lists the same product twice
    was reserved twice at the same location, so the two quantities add up to
    one reservation to pick against and later release."""
    totals: dict[str, float] = {}
    for line in lines:
        quantity = float(line["quantity"])
        if quantity <= 0:
            continue
        totals[line["product_id"]] = totals.get(line["product_id"], 0.0) + quantity
    return totals


def validate_picked_quantity(*, quantity_picked: float, quantity_requested: float) -> Result[None]:
    """A short pick is allowed (the rest of the reservation is released at
    shipping); over-picking isn't -- only the requested quantity is reserved
    for this order, anything beyond it belongs to someone else's promise."""
    if quantity_picked < 0:
        return Err("INVALID_QUANTITY", "picked quantity cannot be negative", "la quantité prélevée ne peut pas être négative")
    if quantity_picked > quantity_requested:
        return Err(
            "OVER_PICK",
            f"picked {quantity_picked}, only {quantity_requested} requested",
            f"quantité prélevée {quantity_picked}, seulement {quantity_requested} demandée",
        )
    return Ok(None)


def check_picking_complete(lines: list[PickListLine]) -> Result[None]:
    if any(line.quantity_picked is None for line in lines):
        return Err(
            "LINES_UNPICKED",
            "every line needs a picked quantity (0 for nothing) before picking can be closed",
            "chaque ligne doit avoir une quantité prélevée (0 si rien) avant de clôturer le prélèvement",
        )
    if all((line.quantity_picked or 0) == 0 for line in lines):
        return Err(
            "NOTHING_PICKED",
            "nothing was picked -- cancel the pick list instead",
            "rien n'a été prélevé -- annulez plutôt la liste de prélèvement",
        )
    return Ok(None)


def validate_packing(*, package_count: int, total_weight_kg: float | None) -> Result[None]:
    if package_count <= 0:
        return Err("INVALID_PACKAGE_COUNT", "a shipment needs at least one package", "une expédition doit contenir au moins un colis")
    if total_weight_kg is not None and total_weight_kg < 0:
        return Err("INVALID_WEIGHT", "weight cannot be negative", "le poids ne peut pas être négatif")
    return Ok(None)
