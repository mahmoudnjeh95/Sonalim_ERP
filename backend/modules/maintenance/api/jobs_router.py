from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from pydantic import BaseModel

from core.db import get_connection
from core.domain.result import Err, err_detail
from core.tenancy import TenantContext, require_permission, user_has_permission
from modules.maintenance.api.job_queries import entry_photo, job_detail, list_jobs
from modules.maintenance.api.job_service import JobService
from modules.maintenance.api.notifications import PLAN_PERMISSION

# No prefix: included into modules/maintenance/api/router.py, which carries /maintenance.
router = APIRouter(tags=["maintenance.jobs"])

# Every other refusal is a 422: the request was understood but the job's state or the data given forbids it.
_STATUS_BY_CODE = {
    "NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "NOT_JOB_CHEF": status.HTTP_403_FORBIDDEN,
}


class JobTaskRequest(BaseModel):
    label: str
    action: str
    instructions: str | None = None


class CreateJobRequest(BaseModel):
    equipment_id: str
    title: str
    description: str | None = None
    priority: str
    due_date: datetime.date
    stops_machine: bool
    checkpoint_ids: list[str] = []
    tasks: list[JobTaskRequest] = []
    team_id: str | None = None
    # Left out, a team brings its own chef; sent as null, the job waits for one ("assign later").
    chef_user_id: str | None = None


class AssignJobRequest(BaseModel):
    team_id: str | None = None
    # Optional only because a team may bring its own chef; without either the service answers CHEF_REQUIRED.
    chef_user_id: str | None = None


class DelegateAssignment(BaseModel):
    check_id: str
    employee_id: str | None = None


class DelegateRequest(BaseModel):
    assignments: list[DelegateAssignment]


class ReviewVerdict(BaseModel):
    check_id: str
    verdict: str
    reason: str | None = None


class ReviewRequest(BaseModel):
    verdicts: list[ReviewVerdict]


class CancelJobRequest(BaseModel):
    reason: str | None = None


def _today() -> datetime.date:
    return datetime.date.today()


def _job_not_found(job_id: str) -> HTTPException:
    return HTTPException(
        status.HTTP_404_NOT_FOUND,
        {"code": "NOT_FOUND", "message": f"job {job_id} not found", "message_fr": f"intervention {job_id} introuvable"},
    )


def _detail_after(connection, tenant: TenantContext, result, job_id: str | None = None) -> dict:
    """Rolls back and raises on a refusal; otherwise commits and answers with the job as it now is.
    `job_id` defaults to the value of the result (a creation returns the new job's id)."""
    if isinstance(result, Err):
        connection.rollback()
        raise HTTPException(_STATUS_BY_CODE.get(result.code, status.HTTP_422_UNPROCESSABLE_ENTITY), err_detail(result))
    detail = job_detail(connection, tenant.tenant_id, job_id if job_id is not None else result.value, _today())
    connection.commit()
    return detail


def _can_plan(connection, tenant: TenantContext) -> bool:
    """A supervisor may run any job; an executor only the jobs they are the chef of."""
    return user_has_permission(connection, user_id=tenant.user_id, permission=PLAN_PERMISSION)


@router.get("/jobs")
def list_jobs_route(
    job_status: str | None = Query(default=None, alias="status"),
    equipment_id: str | None = None,
    date_from: datetime.date | None = Query(default=None, alias="from"),
    date_to: datetime.date | None = Query(default=None, alias="to"),
    mine: bool = False,
    tenant: TenantContext = Depends(require_permission("maintenance.view_jobs")),
) -> list[dict]:
    statuses = [s.strip() for s in job_status.split(",") if s.strip()] if job_status else None
    with get_connection() as connection:
        return list_jobs(
            connection,
            tenant.tenant_id,
            statuses=statuses,
            equipment_id=equipment_id,
            date_from=date_from,
            date_to=date_to,
            chef_user_id=tenant.user_id if mine else None,
            today=_today(),
        )


@router.get("/jobs/{job_id}")
def get_job(job_id: str, tenant: TenantContext = Depends(require_permission("maintenance.view_jobs"))) -> dict:
    with get_connection() as connection:
        detail = job_detail(connection, tenant.tenant_id, job_id, _today())
    if detail is None:
        raise _job_not_found(job_id)
    return detail


@router.post("/jobs", status_code=status.HTTP_201_CREATED)
def create_job(
    body: CreateJobRequest, tenant: TenantContext = Depends(require_permission("maintenance.plan_jobs"))
) -> dict:
    """A job raised by a supervisor is corrective; preventive jobs come from the programs."""
    with get_connection() as connection:
        result = JobService(connection).create_job(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            equipment_id=body.equipment_id,
            title=body.title,
            description=body.description,
            kind="corrective",
            priority=body.priority,
            due_date=body.due_date,
            stops_machine=body.stops_machine,
            checkpoint_ids=body.checkpoint_ids,
            tasks=[task.model_dump() for task in body.tasks],
            team_id=body.team_id,
            chef_user_id=body.chef_user_id,
            chef_from_team="chef_user_id" not in body.model_fields_set,
        )
        return _detail_after(connection, tenant, result)


@router.post("/jobs/{job_id}/assign")
def assign_job(
    job_id: str, body: AssignJobRequest, tenant: TenantContext = Depends(require_permission("maintenance.plan_jobs"))
) -> dict:
    with get_connection() as connection:
        result = JobService(connection).assign_job(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            job_id=job_id,
            team_id=body.team_id,
            chef_user_id=body.chef_user_id,
        )
        return _detail_after(connection, tenant, result, job_id)


@router.post("/jobs/{job_id}/delegate")
def delegate_job(
    job_id: str, body: DelegateRequest, tenant: TenantContext = Depends(require_permission("maintenance.execute_jobs"))
) -> dict:
    with get_connection() as connection:
        result = JobService(connection).delegate(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            job_id=job_id,
            assignments=[(a.check_id, a.employee_id or None) for a in body.assignments],
            actor_can_plan=_can_plan(connection, tenant),
        )
        return _detail_after(connection, tenant, result, job_id)


@router.post("/jobs/{job_id}/checks/{check_id}/entries", status_code=status.HTTP_201_CREATED)
def record_check_entry(
    job_id: str,
    check_id: str,
    performer_employee_id: str = Form(...),
    outcome: str = Form(...),
    note: str | None = Form(default=None),
    measured_value: float | None = Form(default=None),
    started_at: datetime.datetime | None = Form(default=None),
    finished_at: datetime.datetime | None = Form(default=None),
    manual_minutes: float | None = Form(default=None),
    photo: UploadFile | None = File(default=None),
    tenant: TenantContext = Depends(require_permission("maintenance.execute_jobs")),
) -> dict:
    """One point of the guided check. Timing is either the timer's `started_at` + `finished_at`
    (ISO-8601 with offset) or a `manual_minutes` duration typed afterwards.

    A plain `def`, run in the thread pool: the database work (and the job detail it
    returns) must not hold the event loop while a photo comes in."""
    photo_part = (photo.file.read(), photo.content_type or "") if photo is not None else None
    with get_connection() as connection:
        result = JobService(connection).record_entry(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            job_id=job_id,
            check_id=check_id,
            performer_employee_id=performer_employee_id,
            outcome=outcome,
            note=note,
            measured_value=measured_value,
            started_at=started_at,
            finished_at=finished_at,
            manual_minutes=manual_minutes,
            photo=photo_part,
            actor_can_plan=_can_plan(connection, tenant),
            now=datetime.datetime.now(datetime.timezone.utc),
        )
        return _detail_after(connection, tenant, result, job_id)


@router.get("/check-entries/{entry_id}/photo")
def check_entry_photo(
    entry_id: str, tenant: TenantContext = Depends(require_permission("maintenance.view_jobs"))
) -> Response:
    with get_connection() as connection:
        found = entry_photo(connection, tenant.tenant_id, entry_id)
    if found is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            {"code": "NOT_FOUND", "message": "photo not found", "message_fr": "photo introuvable"},
        )
    image, mime = found
    # An entry is append-only, so its photo never changes: safe to cache privately.
    return Response(content=image, media_type=mime, headers={"Cache-Control": "private, max-age=86400"})


@router.post("/jobs/{job_id}/submit")
def submit_job(job_id: str, tenant: TenantContext = Depends(require_permission("maintenance.execute_jobs"))) -> dict:
    with get_connection() as connection:
        result = JobService(connection).submit(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            job_id=job_id,
            actor_can_plan=_can_plan(connection, tenant),
        )
        return _detail_after(connection, tenant, result, job_id)


@router.post("/jobs/{job_id}/review")
def review_job(
    job_id: str, body: ReviewRequest, tenant: TenantContext = Depends(require_permission("maintenance.plan_jobs"))
) -> dict:
    with get_connection() as connection:
        result = JobService(connection).review(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            job_id=job_id,
            verdicts=[(v.check_id, v.verdict, v.reason) for v in body.verdicts],
        )
        return _detail_after(connection, tenant, result, job_id)


@router.post("/jobs/{job_id}/close")
def close_job(job_id: str, tenant: TenantContext = Depends(require_permission("maintenance.plan_jobs"))) -> dict:
    with get_connection() as connection:
        result = JobService(connection).close(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, job_id=job_id)
        return _detail_after(connection, tenant, result, job_id)


@router.post("/jobs/{job_id}/cancel")
def cancel_job(
    job_id: str, body: CancelJobRequest, tenant: TenantContext = Depends(require_permission("maintenance.plan_jobs"))
) -> dict:
    with get_connection() as connection:
        result = JobService(connection).cancel(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, job_id=job_id, reason=body.reason
        )
        return _detail_after(connection, tenant, result, job_id)
