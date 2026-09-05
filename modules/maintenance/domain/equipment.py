from __future__ import annotations

from dataclasses import dataclass

from core.domain.result import Err, Ok, Result

EQUIPMENT_VALID_TRANSITIONS = {
    "operational": {"down", "maintenance"},
    "down": {"operational", "maintenance"},
    "maintenance": {"operational"},
}


@dataclass(frozen=True)
class Equipment:
    id: str
    work_center_id: str
    code: str
    name: str
    status: str


def validate_equipment_code(code: str) -> Result[None]:
    if not code.strip():
        return Err("INVALID_CODE", "equipment code is required")
    return Ok(None)


def transition_equipment(equipment: Equipment, new_status: str) -> Result[Equipment]:
    if new_status not in EQUIPMENT_VALID_TRANSITIONS.get(equipment.status, set()):
        return Err("INVALID_TRANSITION", f"cannot move equipment from {equipment.status} to {new_status}")
    return Ok(
        Equipment(
            id=equipment.id,
            work_center_id=equipment.work_center_id,
            code=equipment.code,
            name=equipment.name,
            status=new_status,
        )
    )
