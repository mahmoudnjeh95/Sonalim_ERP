from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from ulid import ULID

from core.db import get_connection
from core.domain.result import Err, err_detail
from core.tenancy import TenantContext, require_permission, user_has_permission
from modules.maintenance.api.notifications import PLAN_PERMISSION
from modules.maintenance.api.parts_service import REQUEST_STATUSES, PartsService, get_part_request, list_part_requests

# No prefix: included into modules/maintenance/api/router.py, which carries /maintenance.
router = APIRouter(tags=["maintenance.parts"])

# Every other refusal is a 422: the request was understood but the data or the request's state forbids it.
_STATUS_BY_CODE = {
    "NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "NOT_JOB_CHEF": status.HTTP_403_FORBIDDEN,
}


class PartLineRequest(BaseModel):
    product_id: str
    uom_id: str
    quantity: float


class CreatePartRequestRequest(BaseModel):
    lines: list[PartLineRequest]
    note: str | None = None


class ApproveLineRequest(BaseModel):
    line_id: str
    location_id: str | None = None
    issue_quantity: float


class ApprovePartRequestRequest(BaseModel):
    lines: list[ApproveLineRequest]
    note: str | None = None


class RejectPartRequestRequest(BaseModel):
    # Optional here so a missing note is answered with the service's own NOTE_REQUIRED.
    note: str | None = None


def _request_not_found(request_id: str) -> HTTPException:
    return HTTPException(
        status.HTTP_404_NOT_FOUND,
        {
            "code": "NOT_FOUND",
            "message": f"parts request {request_id} not found",
            "message_fr": f"demande de pièces {request_id} introuvable",
        },
    )


def _request_after(connection, tenant: TenantContext, result, request_id: str | None = None) -> dict:
    """Rolls back and raises on a refusal; otherwise commits and answers with the request as it now is.
    `request_id` defaults to the value of the result (a creation returns the new request's id)."""
    if isinstance(result, Err):
        connection.rollback()
        raise HTTPException(_STATUS_BY_CODE.get(result.code, status.HTTP_422_UNPROCESSABLE_ENTITY), err_detail(result))
    detail = get_part_request(connection, tenant.tenant_id, request_id if request_id is not None else result.value)
    connection.commit()
    return detail


@router.get("/part-requests")
def list_part_requests_route(
    request_status: str | None = Query(default=None, alias="status"),
    tenant: TenantContext = Depends(require_permission("maintenance.view_jobs")),
) -> list[dict]:
    if request_status is not None and request_status not in REQUEST_STATUSES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            {
                "code": "INVALID_STATUS",
                "message": f"unknown parts request status: {request_status}",
                "message_fr": f"statut de demande de pièces inconnu : {request_status}",
            },
        )
    with get_connection() as connection:
        return list_part_requests(connection, tenant.tenant_id, status=request_status)


@router.post("/jobs/{job_id}/part-requests", status_code=status.HTTP_201_CREATED)
def create_part_request(
    job_id: str,
    body: CreatePartRequestRequest,
    tenant: TenantContext = Depends(require_permission("maintenance.execute_jobs")),
) -> dict:
    """The job's chef asks for parts; a supervisor may ask on any job."""
    with get_connection() as connection:
        result = PartsService(connection).create_request(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            job_id=job_id,
            lines=[line.model_dump() for line in body.lines],
            note=body.note,
            actor_can_plan=user_has_permission(connection, user_id=tenant.user_id, permission=PLAN_PERMISSION),
        )
        return _request_after(connection, tenant, result)


@router.get("/part-requests/{request_id}/availability")
def part_request_availability(
    request_id: str, tenant: TenantContext = Depends(require_permission("maintenance.plan_jobs"))
) -> dict:
    with get_connection() as connection:
        found = PartsService(connection).availability(tenant.tenant_id, request_id)
    if found is None:
        raise _request_not_found(request_id)
    return found


@router.post("/part-requests/{request_id}/approve")
def approve_part_request(
    request_id: str,
    body: ApprovePartRequestRequest,
    tenant: TenantContext = Depends(require_permission("maintenance.plan_jobs")),
) -> dict:
    """All or nothing: stock is issued, the split stored and the remainder sent to
    procurement in one transaction, or nothing at all on a refusal."""
    with get_connection() as connection:
        result = PartsService(connection).approve(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            request_id=request_id,
            lines=[line.model_dump() for line in body.lines],
            note=body.note,
            correlation_id=str(ULID()),
        )
        return _request_after(connection, tenant, result, request_id)


@router.post("/part-requests/{request_id}/reject")
def reject_part_request(
    request_id: str,
    body: RejectPartRequestRequest,
    tenant: TenantContext = Depends(require_permission("maintenance.plan_jobs")),
) -> dict:
    with get_connection() as connection:
        result = PartsService(connection).reject(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, request_id=request_id, note=body.note
        )
        return _request_after(connection, tenant, result, request_id)
