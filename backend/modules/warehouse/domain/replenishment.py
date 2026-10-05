from __future__ import annotations

import datetime
import math
from dataclasses import dataclass

from core.domain.result import Err, Ok, Result


@dataclass(frozen=True)
class ReorderRule:
    id: str
    tenant_id: str
    product_id: str
    site_id: str | None
    reorder_point: float
    order_up_to: float
    min_order_quantity: float
    preferred_supplier_id: str | None
    is_active: bool
    created_by: str
    created_at: datetime.datetime


@dataclass(frozen=True)
class ReplenishmentProposal:
    id: str
    tenant_id: str
    rule_id: str
    product_id: str
    site_id: str | None
    available_at_proposal: float
    quantity: float
    supplier_id: str | None
    status: str
    created_at: datetime.datetime
    decided_by: str | None
    decided_at: datetime.datetime | None
    closed_at: datetime.datetime | None


def validate_rule(*, reorder_point: float, order_up_to: float, min_order_quantity: float) -> Result[None]:
    if reorder_point < 0 or min_order_quantity < 0:
        return Err(
            "INVALID_QUANTITY",
            "reorder point and minimum order quantity cannot be negative",
            "le point de commande et la quantité minimale ne peuvent pas être négatifs",
        )
    if order_up_to <= reorder_point:
        return Err(
            "INVALID_RULE",
            "the order-up-to level must be above the reorder point",
            "le niveau de réapprovisionnement doit être supérieur au point de commande",
        )
    return Ok(None)


def needs_replenishment(*, available: float, reorder_point: float) -> bool:
    return available <= reorder_point


def proposal_quantity(*, available: float, order_up_to: float, min_order_quantity: float, integer_only: bool) -> float:
    """Back up to the max level, never less than the supplier's minimum, and
    a whole number for a whole-count unit (rounded up -- ordering one carton
    short of the target would leave the rule breached)."""
    quantity = max(order_up_to - available, min_order_quantity)
    if integer_only:
        quantity = float(math.ceil(quantity - 1e-9))
    return quantity


def validate_proposal_decision(status: str) -> Result[None]:
    if status != "open":
        return Err(
            "INVALID_STATE",
            f"proposal is already {status}",
            f"la proposition est déjà {status}",
        )
    return Ok(None)
