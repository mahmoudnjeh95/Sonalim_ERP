from __future__ import annotations

from dataclasses import dataclass

from core.domain.result import Err, Ok, Result

VALID_KINDS = {"customer", "supplier", "both"}

PARTNER_VALID_TRANSITIONS = {
    "active": {"archived"},
    "archived": set(),
}


@dataclass(frozen=True)
class Partner:
    id: str
    tenant_id: str
    name: str
    kind: str
    industry: str | None
    website: str | None
    phone: str | None
    email: str | None
    status: str


def validate_partner_name(name: str) -> Result[None]:
    if not name.strip():
        return Err("INVALID_NAME", "partner name is required")
    return Ok(None)


def transition_partner(partner: Partner, new_status: str) -> Result[Partner]:
    if new_status not in PARTNER_VALID_TRANSITIONS.get(partner.status, set()):
        return Err("INVALID_TRANSITION", f"cannot move partner from {partner.status} to {new_status}")
    return Ok(
        Partner(
            id=partner.id,
            tenant_id=partner.tenant_id,
            name=partner.name,
            kind=partner.kind,
            industry=partner.industry,
            website=partner.website,
            phone=partner.phone,
            email=partner.email,
            status=new_status,
        )
    )
