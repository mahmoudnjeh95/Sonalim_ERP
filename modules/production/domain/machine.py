from __future__ import annotations

from dataclasses import dataclass

from core.domain.result import Err, Ok, Result

MACHINE_VALID_TRANSITIONS = {
    "operational": {"down", "maintenance"},
    "down": {"operational", "maintenance"},
    "maintenance": {"operational"},
}


@dataclass(frozen=True)
class Machine:
    id: str
    work_center_id: str
    code: str
    name: str
    status: str


def validate_machine_code(code: str) -> Result[None]:
    if not code.strip():
        return Err("INVALID_CODE", "machine code is required")
    return Ok(None)


def transition_machine(machine: Machine, new_status: str) -> Result[Machine]:
    if new_status not in MACHINE_VALID_TRANSITIONS.get(machine.status, set()):
        return Err("INVALID_TRANSITION", f"cannot move machine from {machine.status} to {new_status}")
    return Ok(
        Machine(
            id=machine.id,
            work_center_id=machine.work_center_id,
            code=machine.code,
            name=machine.name,
            status=new_status,
        )
    )
