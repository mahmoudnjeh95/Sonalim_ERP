"""HTTP routes of HR phase 2: schedules, holidays, presence, clock imports, leave, month close."""
from __future__ import annotations

import datetime
from typing import Callable, NoReturn

import psycopg
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from core.db import get_connection
from core.domain.result import Err, Result, err_detail
from core.tenancy import TenantContext, require_permission
from modules.hr.api.presence_service import PresenceService
from modules.hr.api.schedule_service import HolidayService, PresenceSettingsService, ScheduleService
from modules.hr.domain.presence import ManualEntry

router = APIRouter(prefix="/hr", tags=["hr.presence"])

# Refusals caused by the current state of the data rather than by a malformed request.
_CONFLICT_CODES = frozenset({
    "ASSIGNMENT_OVERLAP", "PRESENCE_MONTH_CLOSED", "PRESENCE_DAY_FROM_LEAVE", "PRESENCE_INCOMPLETE",
    "PRESENCE_PAYROLL_APPROVED", "LEAVE_PENDING", "LEAVE_OVERLAP", "LEAVE_OVERLAPS_WORK",
    "LEAVE_BALANCE_INSUFFICIENT", "INVALID_TRANSITION", "IMPORT_NOT_STAGED",
})


def _fail(err: Err) -> NoReturn:
    if err.code == "NOT_FOUND":
        code = status.HTTP_404_NOT_FOUND
    elif err.code in _CONFLICT_CODES or err.code.startswith("DUPLICATE"):
        code = status.HTTP_409_CONFLICT
    else:
        code = status.HTTP_422_UNPROCESSABLE_ENTITY
    raise HTTPException(code, err_detail(err))


def _write(action: Callable[[psycopg.Connection], Result]):
    with get_connection() as connection:
        result = action(connection)
        if isinstance(result, Err):
            connection.rollback()
            _fail(result)
        connection.commit()
        return result.value


def _read(action: Callable[[psycopg.Connection], object]):
    with get_connection() as connection:
        return action(connection)


def _read_result(action: Callable[[psycopg.Connection], Result]):
    with get_connection() as connection:
        result = action(connection)
    if isinstance(result, Err):
        _fail(result)
    return result.value


def _period(value: datetime.date) -> datetime.date:
    if value.day != 1:
        _fail(Err("INVALID_PERIOD", "a period is the first day of a month", "une période est le premier jour d'un mois"))
    return value


# ---- schedules, rotations, assignments, holidays, settings --------------------------

class ScheduleDayBody(BaseModel):
    weekday: int
    start_minute: int
    end_minute: int
    break_minutes: int = 0


class ScheduleBody(BaseModel):
    code: str
    name: str
    is_night: bool = False
    days: list[ScheduleDayBody]


class ScheduleUpdateBody(BaseModel):
    code: str | None = None
    name: str | None = None
    is_night: bool | None = None
    active: bool | None = None
    days: list[ScheduleDayBody] | None = None


class RotationBody(BaseModel):
    code: str
    name: str
    anchor_date: datetime.date
    schedule_ids: list[str]


class RotationUpdateBody(BaseModel):
    code: str | None = None
    name: str | None = None
    anchor_date: datetime.date | None = None
    schedule_ids: list[str] | None = None
    active: bool | None = None


class AssignmentBody(BaseModel):
    employee_id: str
    valid_from: datetime.date
    valid_to: datetime.date | None = None
    schedule_id: str | None = None
    rotation_pattern_id: str | None = None
    rotation_offset_weeks: int = 0


class AssignmentUpdateBody(BaseModel):
    valid_from: datetime.date | None = None
    valid_to: datetime.date | None = None
    clear_valid_to: bool = False
    schedule_id: str | None = None
    rotation_pattern_id: str | None = None
    rotation_offset_weeks: int | None = None


class HolidayBody(BaseModel):
    country_code: str
    holiday_date: datetime.date
    name: str
    paid: bool = True
    confirmed: bool = False


class HolidayUpdateBody(BaseModel):
    holiday_date: datetime.date | None = None
    name: str | None = None
    paid: bool | None = None
    confirmed: bool | None = None


class PresenceSettingsBody(BaseModel):
    night_start_minute: int | None = None
    night_end_minute: int | None = None
    punch_attach_minutes: int | None = None
    punch_dedupe_seconds: int | None = None
    late_grace_minutes: int | None = None
    confirm: bool = False


@router.get("/schedules")
def list_schedules(tenant: TenantContext = Depends(require_permission("hr.view_presence"))):
    return _read(lambda c: ScheduleService(c).list_schedules(tenant_id=tenant.tenant_id))


@router.post("/schedules", status_code=status.HTTP_201_CREATED)
def create_schedule(body: ScheduleBody, tenant: TenantContext = Depends(require_permission("hr.manage_presence"))):
    return _write(lambda c: ScheduleService(c).create_schedule(
        tenant_id=tenant.tenant_id, actor_id=tenant.user_id, code=body.code, name=body.name,
        is_night=body.is_night, days=[day.model_dump() for day in body.days],
    ))


@router.patch("/schedules/{schedule_id}")
def update_schedule(schedule_id: str, body: ScheduleUpdateBody, tenant: TenantContext = Depends(require_permission("hr.admin_presence"))):
    return _write(lambda c: ScheduleService(c).update_schedule(
        tenant_id=tenant.tenant_id, actor_id=tenant.user_id, schedule_id=schedule_id, code=body.code, name=body.name,
        is_night=body.is_night, active=body.active,
        days=[day.model_dump() for day in body.days] if body.days is not None else None,
    ))


@router.get("/rotation-patterns")
def list_rotations(tenant: TenantContext = Depends(require_permission("hr.view_presence"))):
    return _read(lambda c: ScheduleService(c).list_rotations(tenant_id=tenant.tenant_id))


@router.post("/rotation-patterns", status_code=status.HTTP_201_CREATED)
def create_rotation(body: RotationBody, tenant: TenantContext = Depends(require_permission("hr.manage_presence"))):
    return _write(lambda c: ScheduleService(c).create_rotation(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, **body.model_dump()))


@router.patch("/rotation-patterns/{rotation_id}")
def update_rotation(rotation_id: str, body: RotationUpdateBody, tenant: TenantContext = Depends(require_permission("hr.admin_presence"))):
    return _write(lambda c: ScheduleService(c).update_rotation(
        tenant_id=tenant.tenant_id, actor_id=tenant.user_id, rotation_id=rotation_id, **body.model_dump()
    ))


@router.get("/schedule-assignments")
def list_assignments(employee_id: str | None = None, tenant: TenantContext = Depends(require_permission("hr.view_presence"))):
    return _read(lambda c: ScheduleService(c).list_assignments(tenant_id=tenant.tenant_id, employee_id=employee_id))


@router.post("/schedule-assignments", status_code=status.HTTP_201_CREATED)
def create_assignment(body: AssignmentBody, tenant: TenantContext = Depends(require_permission("hr.manage_presence"))):
    return _write(lambda c: ScheduleService(c).create_assignment(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, **body.model_dump()))


@router.patch("/schedule-assignments/{assignment_id}")
def update_assignment(assignment_id: str, body: AssignmentUpdateBody, tenant: TenantContext = Depends(require_permission("hr.admin_presence"))):
    return _write(lambda c: ScheduleService(c).update_assignment(
        tenant_id=tenant.tenant_id, actor_id=tenant.user_id, assignment_id=assignment_id, **body.model_dump()
    ))


@router.get("/public-holidays")
def list_holidays(year: int | None = None, tenant: TenantContext = Depends(require_permission("hr.view_presence"))):
    return _read(lambda c: HolidayService(c).list_holidays(tenant_id=tenant.tenant_id, year=year))


@router.post("/public-holidays", status_code=status.HTTP_201_CREATED)
def create_holiday(body: HolidayBody, tenant: TenantContext = Depends(require_permission("hr.manage_presence"))):
    return _write(lambda c: HolidayService(c).create_holiday(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, **body.model_dump()))


@router.patch("/public-holidays/{holiday_id}")
def update_holiday(holiday_id: str, body: HolidayUpdateBody, tenant: TenantContext = Depends(require_permission("hr.admin_presence"))):
    return _write(lambda c: HolidayService(c).update_holiday(
        tenant_id=tenant.tenant_id, actor_id=tenant.user_id, holiday_id=holiday_id, **body.model_dump()
    ))


@router.get("/presence/settings")
def get_presence_settings(tenant: TenantContext = Depends(require_permission("hr.view_presence"))):
    return _read(lambda c: PresenceSettingsService(c).get(tenant_id=tenant.tenant_id))


@router.put("/presence/settings")
def save_presence_settings(body: PresenceSettingsBody, tenant: TenantContext = Depends(require_permission("hr.admin_presence"))):
    return _write(lambda c: PresenceSettingsService(c).update(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, **body.model_dump()))


# ---- presence grid ------------------------------------------------------------------

class PresenceEntryBody(BaseModel):
    employee_id: str
    work_date: datetime.date
    status: str
    worked_minutes: int | None = None
    late_minutes: int = 0
    ot_minutes_day: int = 0
    ot_minutes_night: int = 0
    justified: bool = False
    note: str | None = None


class PresenceDaysBody(BaseModel):
    entries: list[PresenceEntryBody]


@router.get("/presence/grid")
def presence_grid(
    work_date: datetime.date,
    department_id: str | None = None,
    schedule_id: str | None = None,
    tenant: TenantContext = Depends(require_permission("hr.view_presence")),
):
    return _read(lambda c: PresenceService(c).grid(tenant_id=tenant.tenant_id, work_date=work_date, department_id=department_id, schedule_id=schedule_id))


@router.get("/presence/week")
def presence_week(
    date_from: datetime.date,
    department_id: str | None = None,
    schedule_id: str | None = None,
    tenant: TenantContext = Depends(require_permission("hr.view_presence")),
):
    return _read(lambda c: PresenceService(c).week(tenant_id=tenant.tenant_id, date_from=date_from, department_id=department_id, schedule_id=schedule_id))


@router.put("/presence/days")
def save_presence_days(body: PresenceDaysBody, tenant: TenantContext = Depends(require_permission("hr.manage_presence"))):
    entries = [ManualEntry(**entry.model_dump()) for entry in body.entries]
    return _write(lambda c: PresenceService(c).save_days(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, entries=entries))


@router.get("/presence/employee-month")
def presence_employee_month(employee_id: str, period: datetime.date, tenant: TenantContext = Depends(require_permission("hr.view_presence"))):
    return _read_result(lambda c: PresenceService(c).employee_month(tenant_id=tenant.tenant_id, employee_id=employee_id, period=_period(period)))
