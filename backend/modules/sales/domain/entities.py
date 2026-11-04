from __future__ import annotations

import datetime
from dataclasses import dataclass

from core.domain.result import Err, Ok, Result

VALID_TRANSITIONS = {
    "draft": {"confirmed"},
    # Set by warehouse.shipment.shipped or by issue vouchers covering every line,
    # never by a user action: an order is shipped when the goods have physically
    # left, which only warehouse knows.
    "confirmed": {"shipped"},
    "shipped": set(),
}


@dataclass(frozen=True)
class OrderLine:
    product_id: str
    quantity: float
    unit_price: float


@dataclass(frozen=True)
class SalesOrder:
    id: str
    partner_id: str
    location_id: str
    status: str
    lines: tuple[OrderLine, ...]
    requested_ship_date: datetime.date | None = None
    opportunity_id: str | None = None

    @property
    def total_amount(self) -> float:
        return sum(line.quantity * line.unit_price for line in self.lines)


def confirm(order: SalesOrder) -> Result[SalesOrder]:
    if "confirmed" not in VALID_TRANSITIONS.get(order.status, set()):
        return Err(
            "INVALID_TRANSITION",
            f"cannot confirm order in status {order.status}",
            f"impossible de confirmer une commande au statut {order.status}",
        )
    return Ok(
        SalesOrder(
            id=order.id,
            partner_id=order.partner_id,
            location_id=order.location_id,
            status="confirmed",
            lines=order.lines,
            requested_ship_date=order.requested_ship_date,
            opportunity_id=order.opportunity_id,
        )
    )


def covers_all_lines(lines: tuple[OrderLine, ...], issued_to_date: dict[str, float]) -> bool:
    """Whether what left the warehouse covers everything ordered. Lines of one product count together."""
    ordered: dict[str, float] = {}
    for line in lines:
        ordered[line.product_id] = ordered.get(line.product_id, 0.0) + line.quantity
    return all(issued_to_date.get(product_id, 0.0) >= quantity - 1e-6 for product_id, quantity in ordered.items())


def mark_shipped(order_status: str) -> Result[str]:
    if "shipped" not in VALID_TRANSITIONS.get(order_status, set()):
        return Err(
            "INVALID_TRANSITION",
            f"cannot mark an order in status {order_status} as shipped",
            f"impossible de marquer comme expédiée une commande au statut {order_status}",
        )
    return Ok("shipped")
