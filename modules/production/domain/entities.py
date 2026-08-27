from __future__ import annotations

from dataclasses import dataclass

from core.domain.result import Err, Ok, Result

VALID_TRANSITIONS = {
    "draft": {"in_progress"},
    "in_progress": {"completed"},
    "completed": set(),
}


@dataclass(frozen=True)
class WorkOrder:
    id: str
    product_id: str
    quantity: float
    status: str
    reference: str = ""
    work_center_id: str | None = None
    recipe_id: str | None = None
    packaging_bom_id: str | None = None
    actual_output_quantity: float | None = None


def transition(order: WorkOrder, new_status: str) -> Result[WorkOrder]:
    if new_status not in VALID_TRANSITIONS.get(order.status, set()):
        return Err("INVALID_TRANSITION", f"cannot move work order from {order.status} to {new_status}")
    return Ok(
        WorkOrder(
            id=order.id,
            product_id=order.product_id,
            quantity=order.quantity,
            status=new_status,
            reference=order.reference,
            work_center_id=order.work_center_id,
            recipe_id=order.recipe_id,
            packaging_bom_id=order.packaging_bom_id,
            actual_output_quantity=order.actual_output_quantity,
        )
    )
