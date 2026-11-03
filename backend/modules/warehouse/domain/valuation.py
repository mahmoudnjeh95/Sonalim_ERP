"""FIFO inventory valuation -- pure rules, no database.

Valuation is per product across the whole plant, not per location: moving a
carton from one bin to another doesn't change what it cost. The quantity
valued is what the plant owns -- on hand plus in production -- so sending
stock to the line is neutral and it is the line's consumption that draws the
oldest layers down.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass

# Moves that relocate stock without changing what the plant owns.
NEUTRAL_MOVE_TYPES = frozenset({"transfer_in", "transfer_out", "send_to_production"})


@dataclass(frozen=True)
class CostLayer:
    id: str
    tenant_id: str
    product_id: str
    reference: str
    move_type: str
    quantity_in: float
    quantity_remaining: float
    # XOF per product unit; None when nothing was known at receipt (no landed
    # cost and no catalog purchase price) -- such stock is counted, not valued.
    unit_cost: float | None
    received_at: datetime.datetime


@dataclass(frozen=True)
class Allocation:
    layer_id: str | None  # None for the part no layer covered (a shortfall)
    quantity: float
    unit_cost: float | None


def allocate_fifo(layers: list[tuple[str, float, float | None]], quantity: float) -> list[Allocation]:
    """Draws `quantity` from `layers` -- (layer_id, remaining, unit_cost),
    already oldest first. Whatever no layer covers comes back as one
    allocation with layer_id None: production is allowed to consume more than
    the books hold (it records what physically happened), and valuation must
    record that shortfall rather than refuse or silently drop it."""
    allocations: list[Allocation] = []
    left = quantity
    for layer_id, remaining, unit_cost in layers:
        if left <= 0:
            break
        if remaining <= 0:
            continue
        taken = min(remaining, left)
        allocations.append(Allocation(layer_id=layer_id, quantity=taken, unit_cost=unit_cost))
        left -= taken
    if left > 1e-9:
        allocations.append(Allocation(layer_id=None, quantity=left, unit_cost=None))
    return allocations


def allocation_cost(allocations: list[Allocation]) -> tuple[float, float]:
    """(valued cost, unvalued quantity) of a consumption."""
    cost = sum(a.quantity * a.unit_cost for a in allocations if a.unit_cost is not None)
    unvalued = sum(a.quantity for a in allocations if a.unit_cost is None)
    return cost, unvalued


@dataclass(frozen=True)
class ProductValuation:
    product_id: str
    quantity: float
    value: float
    unvalued_quantity: float

    @property
    def average_unit_cost(self) -> float | None:
        valued = self.quantity - self.unvalued_quantity
        return self.value / valued if valued > 0 else None


def value_layers(product_id: str, layers: list[CostLayer]) -> ProductValuation:
    quantity = sum(layer.quantity_remaining for layer in layers)
    value = sum(layer.quantity_remaining * layer.unit_cost for layer in layers if layer.unit_cost is not None)
    unvalued = sum(layer.quantity_remaining for layer in layers if layer.unit_cost is None)
    return ProductValuation(product_id=product_id, quantity=quantity, value=value, unvalued_quantity=unvalued)
