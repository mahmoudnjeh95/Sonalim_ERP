from __future__ import annotations

import datetime
from dataclasses import dataclass, replace

from core.domain.result import Err, Ok, Result

EQUIPMENT_VALID_TRANSITIONS = {
    "operational": {"down", "maintenance"},
    "down": {"operational", "maintenance"},
    "maintenance": {"operational"},
}

# The stages of a production line a machine can work at, in the order a line runs
# them. The registry is where a machine's stage is declared, so the production
# dashboard draws each line from here instead of asking anyone to enter it twice.
PRODUCTION_STAGES = ("versement", "extrusion", "conditionnement")


@dataclass(frozen=True)
class Equipment:
    id: str
    work_center_id: str
    code: str
    name: str
    status: str
    # None for a machine that works at none of the stages (a grinder off the main
    # flow, say) and for every machine registered before the field existed.
    production_stage: str | None = None
    # Set when the machine is retired from the active registry; unset to bring
    # it back. None for every equipment row, always, until first archived.
    archived_at: datetime.datetime | None = None


def validate_equipment_code(code: str) -> Result[None]:
    if not code.strip():
        return Err("INVALID_CODE", "equipment code is required")
    return Ok(None)


def validate_production_stage(stage: str | None) -> Result[None]:
    if stage is not None and stage not in PRODUCTION_STAGES:
        return Err("INVALID_STAGE", f"production stage must be one of {list(PRODUCTION_STAGES)}")
    return Ok(None)


def transition_equipment(equipment: Equipment, new_status: str) -> Result[Equipment]:
    if new_status not in EQUIPMENT_VALID_TRANSITIONS.get(equipment.status, set()):
        return Err("INVALID_TRANSITION", f"cannot move equipment from {equipment.status} to {new_status}")
    return Ok(replace(equipment, status=new_status))
