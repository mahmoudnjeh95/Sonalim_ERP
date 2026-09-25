from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from core.api.service import CoreService
from core.db import get_connection
from core.domain.partner import Partner, PartnerTagLink
from core.domain.result import Err, err_detail
from core.tenancy import TenantContext, require_permission

router = APIRouter(prefix="/core/partners", tags=["core.partners"])


class SetPartnerTagsRequest(BaseModel):
    tag_ids: list[str]


class UpdatePartnerTagLinkRequest(BaseModel):
    is_preferred: bool | None = None
    lead_time_days: int | None = None
    min_order_qty: float | None = None


def partner_tag_link_response(link: PartnerTagLink) -> dict:
    return {
        "partner_id": link.partner_id,
        "tag_id": link.tag_id,
        "tag_name": link.tag_name,
        "is_preferred": link.is_preferred,
        "lead_time_days": link.lead_time_days,
        "min_order_qty": link.min_order_qty,
    }


def partner_response(partner: Partner) -> dict:
    return {
        "id": partner.id,
        "name": partner.name,
        "kind": partner.kind,
        "industry": partner.industry,
        "website": partner.website,
        "phone": partner.phone,
        "email": partner.email,
        "status": partner.status,
    }


class CreatePartnerRequest(BaseModel):
    name: str
    kind: str
    industry: str | None = None
    website: str | None = None
    phone: str | None = None
    email: str | None = None


class UpdatePartnerRequest(BaseModel):
    name: str | None = None
    kind: str | None = None
    industry: str | None = None
    website: str | None = None
    phone: str | None = None
    email: str | None = None


@router.post("", status_code=status.HTTP_201_CREATED)
def create_partner(
    body: CreatePartnerRequest, tenant: TenantContext = Depends(require_permission("core.manage_partners"))
) -> dict:
    with get_connection() as connection:
        service = CoreService(connection)
        result = service.create_partner(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            name=body.name,
            kind=body.kind,
            industry=body.industry,
            website=body.website,
            phone=body.phone,
            email=body.email,
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, err_detail(result))
        connection.commit()
    return partner_response(result.value)


@router.get("")
def list_partners(
    kind: str | None = None,
    status_filter: str | None = None,
    tenant: TenantContext = Depends(require_permission("core.view_partners")),
) -> list[dict]:
    with get_connection() as connection:
        service = CoreService(connection)
        partners = service.list_partners(tenant_id=tenant.tenant_id, kind=kind, status=status_filter)
    return [partner_response(partner) for partner in partners]


@router.get("/{partner_id}")
def get_partner(partner_id: str, tenant: TenantContext = Depends(require_permission("core.view_partners"))) -> dict:
    with get_connection() as connection:
        service = CoreService(connection)
        partner = service.get_partner(tenant.tenant_id, partner_id)
    if partner is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            {"code": "NOT_FOUND", "message": f"partner {partner_id} not found", "message_fr": f"partenaire {partner_id} introuvable"},
        )
    return partner_response(partner)


@router.patch("/{partner_id}")
def update_partner(
    partner_id: str, body: UpdatePartnerRequest, tenant: TenantContext = Depends(require_permission("core.admin_partners"))
) -> dict:
    with get_connection() as connection:
        service = CoreService(connection)
        result = service.update_partner(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            partner_id=partner_id,
            name=body.name,
            kind=body.kind,
            industry=body.industry,
            website=body.website,
            phone=body.phone,
            email=body.email,
        )
        if isinstance(result, Err):
            connection.rollback()
            code = status.HTTP_404_NOT_FOUND if result.code == "NOT_FOUND" else status.HTTP_400_BAD_REQUEST
            raise HTTPException(code, err_detail(result))
        connection.commit()
    return partner_response(result.value)


@router.post("/{partner_id}/archive")
def archive_partner(partner_id: str, tenant: TenantContext = Depends(require_permission("core.manage_partners"))) -> dict:
    with get_connection() as connection:
        service = CoreService(connection)
        result = service.archive_partner(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, partner_id=partner_id)
        if isinstance(result, Err):
            connection.rollback()
            code = status.HTTP_404_NOT_FOUND if result.code == "NOT_FOUND" else status.HTTP_409_CONFLICT
            raise HTTPException(code, err_detail(result))
        connection.commit()
    return partner_response(result.value)


@router.post("/{partner_id}/activate")
def activate_partner(partner_id: str, tenant: TenantContext = Depends(require_permission("core.manage_partners"))) -> dict:
    with get_connection() as connection:
        service = CoreService(connection)
        result = service.activate_partner(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, partner_id=partner_id)
        if isinstance(result, Err):
            connection.rollback()
            code = status.HTTP_404_NOT_FOUND if result.code == "NOT_FOUND" else status.HTTP_409_CONFLICT
            raise HTTPException(code, err_detail(result))
        connection.commit()
    return partner_response(result.value)


@router.get("/{partner_id}/tags")
def list_partner_tags(partner_id: str, tenant: TenantContext = Depends(require_permission("core.view_partners"))) -> list[dict]:
    with get_connection() as connection:
        service = CoreService(connection)
        links = service.list_tags_for_partner(tenant.tenant_id, partner_id)
    return [partner_tag_link_response(link) for link in links]


@router.put("/{partner_id}/tags")
def set_partner_tags(
    partner_id: str,
    body: SetPartnerTagsRequest,
    tenant: TenantContext = Depends(require_permission("core.manage_partners")),
) -> list[dict]:
    with get_connection() as connection:
        service = CoreService(connection)
        result = service.set_partner_tags(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, partner_id=partner_id, tag_ids=body.tag_ids
        )
        if isinstance(result, Err):
            connection.rollback()
            code = status.HTTP_404_NOT_FOUND if result.code == "NOT_FOUND" else status.HTTP_400_BAD_REQUEST
            raise HTTPException(code, err_detail(result))
        connection.commit()
    return [partner_tag_link_response(link) for link in result.value]


@router.patch("/{partner_id}/tags/{tag_id}")
def update_partner_tag_link(
    partner_id: str,
    tag_id: str,
    body: UpdatePartnerTagLinkRequest,
    tenant: TenantContext = Depends(require_permission("core.manage_partners")),
) -> dict:
    with get_connection() as connection:
        service = CoreService(connection)
        result = service.update_partner_tag_link(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            partner_id=partner_id,
            tag_id=tag_id,
            is_preferred=body.is_preferred,
            lead_time_days=body.lead_time_days,
            min_order_qty=body.min_order_qty,
        )
        if isinstance(result, Err):
            connection.rollback()
            code = status.HTTP_404_NOT_FOUND if result.code == "NOT_FOUND" else status.HTTP_400_BAD_REQUEST
            raise HTTPException(code, err_detail(result))
        connection.commit()
    return partner_tag_link_response(result.value)
