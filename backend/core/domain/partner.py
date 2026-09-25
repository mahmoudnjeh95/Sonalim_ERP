from __future__ import annotations

from dataclasses import dataclass

from core.domain.result import Err, Ok, Result

VALID_KINDS = {"customer", "supplier", "both"}

PARTNER_VALID_TRANSITIONS = {
    "active": {"archived"},
    "archived": {"active"},
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
        return Err("INVALID_NAME", "partner name is required", "le nom du partenaire est obligatoire")
    return Ok(None)


@dataclass(frozen=True)
class PartnerTagLink:
    partner_id: str
    tag_id: str
    tag_name: str
    is_preferred: bool
    lead_time_days: int | None
    min_order_qty: float | None


def validate_partner_tag_link(*, lead_time_days: int | None, min_order_qty: float | None) -> Result[None]:
    if lead_time_days is not None and lead_time_days < 0:
        return Err("INVALID_LEAD_TIME", "lead_time_days cannot be negative", "lead_time_days ne peut pas être négatif")
    if min_order_qty is not None and min_order_qty < 0:
        return Err("INVALID_MIN_ORDER_QTY", "min_order_qty cannot be negative", "min_order_qty ne peut pas être négatif")
    return Ok(None)


@dataclass(frozen=True)
class SuggestedVendor:
    partner_id: str
    name: str
    kind: str
    industry: str | None
    phone: str | None
    email: str | None
    is_preferred: bool
    lead_time_days: int | None
    min_order_qty: float | None


def transition_partner(partner: Partner, new_status: str) -> Result[Partner]:
    if new_status not in PARTNER_VALID_TRANSITIONS.get(partner.status, set()):
        return Err(
            "INVALID_TRANSITION",
            f"cannot move partner from {partner.status} to {new_status}",
            f"impossible de faire passer le partenaire de {partner.status} à {new_status}",
        )
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
