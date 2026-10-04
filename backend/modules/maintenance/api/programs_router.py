from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from core.db import get_connection
from core.domain.result import Err, err_detail
from core.tenancy import TenantContext, require_permission
from modules.maintenance.api.program_service import ProgramService

# No prefix: included into modules/maintenance/api/router.py, which carries /maintenance.
router = APIRouter(tags=["maintenance.programs"])

_STATUS_BY_CODE = {"NOT_FOUND": status.HTTP_404_NOT_FOUND}


def _today() -> datetime.date:
    return datetime.date.today()


def _result(connection, result):
    if isinstance(result, Err):
        connection.rollback()
        raise HTTPException(_STATUS_BY_CODE.get(result.code, status.HTTP_422_UNPROCESSABLE_ENTITY), err_detail(result))
    connection.commit()
    return result.value


class CreateProgramRequest(BaseModel):
    equipment_id: str
    name: str
    description: str | None = None
    interval_value: int
    interval_unit: str
    start_date: datetime.date
    lead_days: int
    estimated_minutes: int | None = None
    default_team_id: str | None = None
    stops_machine: bool
    checkpoint_ids: list[str] = []


class UpdateProgramRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    interval_value: int | None = None
    interval_unit: str | None = None
    start_date: datetime.date | None = None
    lead_days: int | None = None
    estimated_minutes: int | None = None
    default_team_id: str | None = None
    stops_machine: bool | None = None
    checkpoint_ids: list[str] | None = None
    active: bool | None = None


@router.get("/programs")
def list_programs(tenant: TenantContext = Depends(require_permission("maintenance.view_jobs"))) -> list[dict]:
    with get_connection() as connection:
        return ProgramService(connection).list_programs(tenant.tenant_id, _today())


@router.post("/programs", status_code=status.HTTP_201_CREATED)
def create_program(
    body: CreateProgramRequest, tenant: TenantContext = Depends(require_permission("maintenance.plan_jobs"))
) -> dict:
    with get_connection() as connection:
        return _result(
            connection,
            ProgramService(connection).create_program(
                tenant_id=tenant.tenant_id,
                actor_id=tenant.user_id,
                equipment_id=body.equipment_id,
                name=body.name,
                description=body.description,
                interval_value=body.interval_value,
                interval_unit=body.interval_unit,
                start_date=body.start_date,
                lead_days=body.lead_days,
                estimated_minutes=body.estimated_minutes,
                default_team_id=body.default_team_id,
                stops_machine=body.stops_machine,
                checkpoint_ids=body.checkpoint_ids,
            ),
        )


@router.patch("/programs/{program_id}")
def update_program(
    program_id: str,
    body: UpdateProgramRequest,
    tenant: TenantContext = Depends(require_permission("maintenance.plan_jobs")),
) -> dict:
    fields_set = body.model_fields_set
    with get_connection() as connection:
        return _result(
            connection,
            ProgramService(connection).update_program(
                tenant_id=tenant.tenant_id,
                actor_id=tenant.user_id,
                program_id=program_id,
                name=body.name,
                description=body.description,
                description_set="description" in fields_set,
                interval_value=body.interval_value,
                interval_unit=body.interval_unit,
                start_date=body.start_date,
                lead_days=body.lead_days,
                estimated_minutes=body.estimated_minutes,
                estimated_minutes_set="estimated_minutes" in fields_set,
                default_team_id=body.default_team_id,
                default_team_id_set="default_team_id" in fields_set,
                stops_machine=body.stops_machine,
                checkpoint_ids=body.checkpoint_ids,
                active=body.active,
            ),
        )


@router.post("/programs/run-due")
def run_due_programs(tenant: TenantContext = Depends(require_permission("maintenance.plan_jobs"))) -> dict:
    with get_connection() as connection:
        result = ProgramService(connection).run_due(tenant_id=tenant.tenant_id, today=_today())
        connection.commit()
        return result


@router.get("/calendar")
def calendar(
    date_from: datetime.date = Query(..., alias="from"),
    date_to: datetime.date = Query(..., alias="to"),
    tenant: TenantContext = Depends(require_permission("maintenance.view_jobs")),
) -> dict:
    with get_connection() as connection:
        return ProgramService(connection).calendar(tenant.tenant_id, date_from, date_to, _today())
