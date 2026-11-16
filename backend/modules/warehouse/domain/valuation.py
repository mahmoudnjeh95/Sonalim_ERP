"""Inventory valuation on cost layers -- pure rules, no database. FIFO by default; a tenant can
choose the weighted average (CMUP), which keeps every open layer at the one average cost.

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

VALUATION_METHODS = ("fifo", "average")


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


def weighted_average(layers: list[tuple[float, float | None]]) -> float | None:
    """(remaining, unit_cost) of the open layers ->
    (old quantity * old cost + new quantity * new cost) / (old quantity + new quantity).
    Unvalued stock has no cost to weigh, so it stays out instead of dragging the average to 0."""
    valued = [(remaining, cost) for remaining, cost in layers if cost is not None and remaining > 0]
    quantity = sum(remaining for remaining, _ in valued)
    return sum(remaining * cost for remaining, cost in valued) / quantity if quantity > 0 else None


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
    last_received_at: datetime.datetime | None = None

    @property
    def average_unit_cost(self) -> float | None:
        valued = self.quantity - self.unvalued_quantity
        return self.value / valued if valued > 0 else None


def value_layers(product_id: str, layers: list[CostLayer]) -> ProductValuation:
    quantity = sum(layer.quantity_remaining for layer in layers)
    value = sum(layer.quantity_remaining * layer.unit_cost for layer in layers if layer.unit_cost is not None)
    unvalued = sum(layer.quantity_remaining for layer in layers if layer.unit_cost is None)
    last_received_at = max((layer.received_at for layer in layers), default=None)
    return ProductValuation(product_id=product_id, quantity=quantity, value=value, unvalued_quantity=unvalued, last_received_at=last_received_at)
