from __future__ import annotations

import datetime
from dataclasses import dataclass, replace

from core.domain.result import Err, Ok, Result

# The OF's five-value lifecycle. An OF plans work and records that it happened;
# it never posts stock, so none of these transitions has an inventory effect —
# that belongs to report validation. `closed` is archival: reports, validations
# and quality history stay readable after it.
VALID_TRANSITIONS = {
    "planned": {"ongoing", "cancelled"},
    "ongoing": {"suspended", "closed"},
    "suspended": {"ongoing", "cancelled"},
    "closed": set(),
    "cancelled": set(),
}


@dataclass(frozen=True)
class WorkOrder:
    id: str
    # Nullable: creation names the work center, PC/PL and start date, not the
    # product. Conditionnement backfills it with the first packaging report.
    product_id: str | None
    # Nullable: quantity is assigned later, once known, via update.
    planned_quantity: float | None
    status: str
    reference: str = ""
    work_center_id: str | None = None
    # Opaque reference to the user (core.users) responsible for this OF. Optional:
    # unlike work_center_id, plenty of real OFs will never have one on file, and
    # creation must not be blocked on it.
    supervisor_id: str | None = None
    recipe_id: str | None = None
    packaging_bom_id: str | None = None
    start_date: datetime.date | None = None
    product_type: str | None = None
    notes: str | None = None
    created_by: str | None = None
    closed_at: datetime.datetime | None = None
    closed_by: str | None = None


def transition(order: WorkOrder, new_status: str) -> Result[WorkOrder]:
    if new_status not in VALID_TRANSITIONS.get(order.status, set()):
        return Err("INVALID_TRANSITION", f"cannot move work order from {order.status} to {new_status}")
    return Ok(replace(order, status=new_status))
