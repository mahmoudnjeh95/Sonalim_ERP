from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from core.db import get_connection
from core.domain.result import Err
from core.partners import partner_response
from core.tenancy import TenantContext, require_permission
from modules.crm.api.activity_service import ActivityService
from modules.crm.api.contact_service import ContactService
from modules.crm.api.dashboard_service import CrmDashboardService
from modules.crm.api.lead_service import LeadService
from modules.crm.api.opportunity_service import OpportunityService
from modules.crm.domain.activity import Activity
from modules.crm.domain.opportunity import Opportunity

router = APIRouter(prefix="/crm", tags=["crm"])


def _err_status(code: str) -> int:
    return status.HTTP_404_NOT_FOUND if code == "NOT_FOUND" else status.HTTP_409_CONFLICT


def _opportunity_response(opportunity: Opportunity) -> dict:
    return {
        "id": opportunity.id,
        "partner_id": opportunity.partner_id,
        "name": opportunity.name,
        "stage": opportunity.stage,
        "amount": opportunity.amount,
        "expected_close_date": opportunity.expected_close_date,
    }


def _activity_response(activity: Activity) -> dict:
    return {
        "id": activity.id,
        "kind": activity.kind,
        "subject_type": activity.subject_type,
        "subject_id": activity.subject_id,
        "note": activity.note,
        "due_at": activity.due_at,
        "completed_at": activity.completed_at,
    }


# --- Leads ---------------------------------------------------------------


class CreateLeadRequest(BaseModel):
    contact_name: str
    email: str


class UpdateLeadRequest(BaseModel):
    contact_name: str | None = None
    email: str | None = None


class QualifyLeadRequest(BaseModel):
    correlation_id: str


class ConvertLeadRequest(BaseModel):
    correlation_id: str


class CreateContactRequest(BaseModel):
    partner_id: str
    first_name: str
    last_name: str
    job_title: str | None = None
    email: str | None = None
    phone: str | None = None
    is_primary: bool = False


@router.post("/contacts", status_code=status.HTTP_201_CREATED)
def create_contact(
    body: CreateContactRequest, tenant: TenantContext = Depends(require_permission("crm.manage_contacts"))
) -> dict:
    with get_connection() as connection:
        result = ContactService(connection).create_contact(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, partner_id=body.partner_id,
            first_name=body.first_name, last_name=body.last_name, job_title=body.job_title,
            email=body.email, phone=body.phone, is_primary=body.is_primary,
        )
        if isinstance(result, Err):
            connection.rollback()
            code = status.HTTP_404_NOT_FOUND if result.code == "NOT_FOUND" else status.HTTP_409_CONFLICT
            raise HTTPException(code, {"code": result.code, "message": result.message})
        connection.commit()
    return result.value


@router.get("/contacts")
def list_contacts(
    partner_id: str | None = None, tenant: TenantContext = Depends(require_permission("crm.view_contacts"))
) -> list[dict]:
    with get_connection() as connection:
        return ContactService(connection).list_contacts(tenant_id=tenant.tenant_id, partner_id=partner_id)


@router.post("/leads", status_code=status.HTTP_201_CREATED)
def create_lead(body: CreateLeadRequest, tenant: TenantContext = Depends(require_permission("crm.manage_leads"))) -> dict:
    with get_connection() as connection:
        service = LeadService(connection)
        lead = service.create_lead(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, contact_name=body.contact_name, email=body.email)
        connection.commit()
    return {"id": lead.id, "status": lead.status}


@router.get("/leads")
def list_leads(tenant: TenantContext = Depends(require_permission("crm.view_leads"))) -> list[dict]:
    with get_connection() as connection:
        service = LeadService(connection)
        leads = service.list_leads(tenant_id=tenant.tenant_id)
    return [
        {"id": lead.id, "contact_name": lead.contact_name, "email": lead.email, "status": lead.status}
        for lead in leads
    ]


@router.patch("/leads/{lead_id}")
def update_lead(
    lead_id: str, body: UpdateLeadRequest, tenant: TenantContext = Depends(require_permission("crm.admin_leads"))
) -> dict:
    with get_connection() as connection:
        service = LeadService(connection)
        result = service.update_lead(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, lead_id=lead_id, contact_name=body.contact_name, email=body.email
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_err_status(result.code), {"code": result.code, "message": result.message})
        connection.commit()
    return {"id": result.value.id, "contact_name": result.value.contact_name, "email": result.value.email, "status": result.value.status}


@router.post("/leads/{lead_id}/qualify")
def qualify_lead(
    lead_id: str, body: QualifyLeadRequest, tenant: TenantContext = Depends(require_permission("crm.manage_leads"))
) -> dict:
    with get_connection() as connection:
        service = LeadService(connection)
        result = service.qualify_lead(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, lead_id=lead_id, correlation_id=body.correlation_id
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_err_status(result.code), {"code": result.code, "message": result.message})
        connection.commit()
    return {"id": result.value.id, "status": result.value.status}


@router.post("/leads/{lead_id}/convert")
def convert_lead(
    lead_id: str, body: ConvertLeadRequest, tenant: TenantContext = Depends(require_permission("crm.manage_leads"))
) -> dict:
    with get_connection() as connection:
        service = LeadService(connection)
        result = service.convert_lead(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, lead_id=lead_id, correlation_id=body.correlation_id
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_err_status(result.code), {"code": result.code, "message": result.message})
        connection.commit()
    return {
        "id": result.value["lead"].id,
        "status": result.value["lead"].status,
        "partner": partner_response(result.value["partner"]),
        "opportunity": _opportunity_response(result.value["opportunity"]),
    }


# --- Opportunities -----------------------------------------------------------


class CreateOpportunityRequest(BaseModel):
    partner_id: str
    name: str
    amount: float = 0
    expected_close_date: datetime.date | None = None


class TransitionOpportunityRequest(BaseModel):
    stage: str


class UpdateOpportunityRequest(BaseModel):
    partner_id: str | None = None
    name: str | None = None
    amount: float | None = None
    expected_close_date: datetime.date | None = None


@router.post("/opportunities", status_code=status.HTTP_201_CREATED)
def create_opportunity(
    body: CreateOpportunityRequest, tenant: TenantContext = Depends(require_permission("crm.manage_opportunities"))
) -> dict:
    with get_connection() as connection:
        service = OpportunityService(connection)
        result = service.create_opportunity(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            partner_id=body.partner_id,
            name=body.name,
            amount=body.amount,
            expected_close_date=body.expected_close_date,
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"code": result.code, "message": result.message})
        connection.commit()
    return _opportunity_response(result.value)


@router.get("/opportunities")
def list_opportunities(
    partner_id: str | None = None, tenant: TenantContext = Depends(require_permission("crm.view_opportunities"))
) -> list[dict]:
    with get_connection() as connection:
        service = OpportunityService(connection)
        opportunities = service.list_opportunities(tenant_id=tenant.tenant_id, partner_id=partner_id)
    return [_opportunity_response(opportunity) for opportunity in opportunities]


@router.patch("/opportunities/{opportunity_id}")
def update_opportunity(
    opportunity_id: str,
    body: UpdateOpportunityRequest,
    tenant: TenantContext = Depends(require_permission("crm.admin_opportunities")),
) -> dict:
    with get_connection() as connection:
        service = OpportunityService(connection)
        result = service.update_opportunity(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            opportunity_id=opportunity_id,
            partner_id=body.partner_id,
            name=body.name,
            amount=body.amount,
            expected_close_date=body.expected_close_date,
        )
        if isinstance(result, Err):
            connection.rollback()
            code = status.HTTP_404_NOT_FOUND if result.code == "NOT_FOUND" else status.HTTP_400_BAD_REQUEST
            raise HTTPException(code, {"code": result.code, "message": result.message})
        connection.commit()
    return _opportunity_response(result.value)


@router.post("/opportunities/{opportunity_id}/transition")
def transition_opportunity(
    opportunity_id: str,
    body: TransitionOpportunityRequest,
    tenant: TenantContext = Depends(require_permission("crm.manage_opportunities")),
) -> dict:
    with get_connection() as connection:
        service = OpportunityService(connection)
        result = service.transition_stage(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, opportunity_id=opportunity_id, new_stage=body.stage
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_err_status(result.code), {"code": result.code, "message": result.message})
        connection.commit()
    return _opportunity_response(result.value)


# --- Activities --------------------------------------------------------------


class CreateActivityRequest(BaseModel):
    kind: str
    subject_type: str
    subject_id: str
    note: str
    due_at: datetime.datetime | None = None


@router.post("/activities", status_code=status.HTTP_201_CREATED)
def create_activity(
    body: CreateActivityRequest, tenant: TenantContext = Depends(require_permission("crm.manage_activities"))
) -> dict:
    with get_connection() as connection:
        service = ActivityService(connection)
        result = service.create_activity(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            kind=body.kind,
            subject_type=body.subject_type,
            subject_id=body.subject_id,
            note=body.note,
            due_at=body.due_at,
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"code": result.code, "message": result.message})
        connection.commit()
    return _activity_response(result.value)


@router.get("/activities")
def list_activities(
    subject_type: str | None = None,
    subject_id: str | None = None,
    limit: int = 20,
    tenant: TenantContext = Depends(require_permission("crm.view_activities")),
) -> list[dict]:
    with get_connection() as connection:
        service = ActivityService(connection)
        activities = service.list_activities(
            tenant_id=tenant.tenant_id, subject_type=subject_type, subject_id=subject_id, limit=limit
        )
    return [_activity_response(activity) for activity in activities]


@router.post("/activities/{activity_id}/complete")
def complete_activity(
    activity_id: str, tenant: TenantContext = Depends(require_permission("crm.manage_activities"))
) -> dict:
    with get_connection() as connection:
        service = ActivityService(connection)
        result = service.complete_activity(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, activity_id=activity_id)
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_err_status(result.code), {"code": result.code, "message": result.message})
        connection.commit()
    return _activity_response(result.value)


# --- Dashboard -----------------------------------------------------------


@router.get("/dashboard")
def get_dashboard(tenant: TenantContext = Depends(require_permission("crm.view_dashboard"))) -> dict:
    with get_connection() as connection:
        service = CrmDashboardService(connection)
        return service.get_dashboard(tenant_id=tenant.tenant_id)
