from __future__ import annotations

from dataclasses import dataclass

from core.domain.result import Err, Ok, Result

VALID_TRANSITIONS = {
    "new": {"qualified", "disqualified"},
    "qualified": {"converted", "disqualified"},
    "converted": set(),
    "disqualified": set(),
}


@dataclass(frozen=True)
class Lead:
    id: str
    contact_name: str
    email: str
    status: str
    source: str | None = None
    owner_id: str | None = None
    priority: str = "medium"
    disqualify_reason: str | None = None


def transition(lead: Lead, new_status: str) -> Result[Lead]:
    if new_status not in VALID_TRANSITIONS.get(lead.status, set()):
        return Err(
            "INVALID_TRANSITION",
            f"cannot move lead from {lead.status} to {new_status}",
            f"impossible de faire passer le prospect de {lead.status} à {new_status}",
        )
    return Ok(
        Lead(
            id=lead.id,
            contact_name=lead.contact_name,
            email=lead.email,
            status=new_status,
            source=lead.source,
            owner_id=lead.owner_id,
            priority=lead.priority,
            disqualify_reason=lead.disqualify_reason,
        )
    )


def validate_disqualify_reason(reason: str) -> Result[None]:
    if not reason.strip():
        return Err(
            "EMPTY_REASON",
            "a reason is required to disqualify a lead",
            "un motif est obligatoire pour disqualifier un prospect",
        )
    return Ok(None)
