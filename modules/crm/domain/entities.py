from __future__ import annotations

from dataclasses import dataclass

from core.domain.result import Err, Ok, Result

VALID_TRANSITIONS = {
    "new": {"qualified"},
    "qualified": {"converted"},
    "converted": set(),
}


@dataclass(frozen=True)
class Lead:
    id: str
    contact_name: str
    email: str
    status: str


def transition(lead: Lead, new_status: str) -> Result[Lead]:
    if new_status not in VALID_TRANSITIONS.get(lead.status, set()):
        return Err("INVALID_TRANSITION", f"cannot move lead from {lead.status} to {new_status}")
    return Ok(Lead(id=lead.id, contact_name=lead.contact_name, email=lead.email, status=new_status))
