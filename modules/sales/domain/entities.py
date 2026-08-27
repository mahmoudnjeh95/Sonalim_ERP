from __future__ import annotations

from dataclasses import dataclass

from core.domain.result import Err, Ok, Result

VALID_TRANSITIONS = {
    "draft": {"confirmed"},
    "confirmed": set(),
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

    @property
    def total_amount(self) -> float:
        return sum(line.quantity * line.unit_price for line in self.lines)


def confirm(order: SalesOrder) -> Result[SalesOrder]:
    if "confirmed" not in VALID_TRANSITIONS.get(order.status, set()):
        return Err("INVALID_TRANSITION", f"cannot confirm order in status {order.status}")
    return Ok(
        SalesOrder(id=order.id, partner_id=order.partner_id, location_id=order.location_id, status="confirmed", lines=order.lines)
    )
