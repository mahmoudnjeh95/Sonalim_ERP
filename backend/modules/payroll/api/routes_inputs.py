"""HTTP routes for monthly inputs, advances and loans (Payroll → Inputs)."""
from __future__ import annotations

import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel

from core.tenancy import TenantContext, require_permission
from modules.payroll.api import http
from modules.payroll.api.input_service import InputService

router = APIRouter()
VIEW = require_permission("payroll.view_runs")
MANAGE = require_permission("payroll.manage_inputs")


class InputBody(BaseModel):
    employee_id: str
    component_code: str
    qty: Decimal | None = None
    amount: Decimal | None = None
    note: str | None = None


class InputPatch(BaseModel):
    component_code: str | None = None
    qty: Decimal | None = None
    amount: Decimal | None = None
    note: str | None = None


class AdvanceBody(BaseModel):
    employee_id: str
    amount: Decimal
    requested_on: datetime.date
    deduct_period: datetime.date
    note: str | None = None


class AdvancePatch(BaseModel):
    amount: Decimal | None = None
    requested_on: datetime.date | None = None
    deduct_period: datetime.date | None = None
    note: str | None = None


class LoanBody(BaseModel):
    employee_id: str
    principal: Decimal
    instalment_count: int
    first_period: datetime.date
    note: str | None = None


class LoanPatch(BaseModel):
    principal: Decimal | None = None
    instalment_count: int | None = None
    first_period: datetime.date | None = None
    note: str | None = None


@router.get("/runs/{run_id}/input-components")
def input_components(run_id: str, tenant: TenantContext = Depends(VIEW)):
    with http.get_connection() as connection:
        return http.finish(connection, InputService(connection).input_components(tenant_id=tenant.tenant_id, run_id=run_id))


@router.get("/runs/{run_id}/inputs")
def list_inputs(run_id: str, tenant: TenantContext = Depends(VIEW)):
    with http.get_connection() as connection:
        return InputService(connection).list_run_inputs(tenant_id=tenant.tenant_id, run_id=run_id)


@router.post("/runs/{run_id}/inputs", status_code=status.HTTP_201_CREATED)
def add_input(run_id: str, body: InputBody, tenant: TenantContext = Depends(MANAGE)):
    with http.get_connection() as connection:
        result = InputService(connection).add_run_input(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, run_id=run_id, **body.model_dump())
        return http.finish(connection, result)


@router.patch("/run-inputs/{input_id}")
def update_input(input_id: str, body: InputPatch, tenant: TenantContext = Depends(MANAGE)):
    with http.get_connection() as connection:
        result = InputService(connection).update_run_input(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, input_id=input_id,
                                                           changes=body.model_dump(exclude_unset=True))
        return http.finish(connection, result)


@router.delete("/run-inputs/{input_id}")
def delete_input(input_id: str, tenant: TenantContext = Depends(MANAGE)):
    with http.get_connection() as connection:
        return http.finish(connection, InputService(connection).delete_run_input(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, input_id=input_id))


@router.get("/advances")
def list_advances(status_filter: str | None = None, tenant: TenantContext = Depends(VIEW)):
    with http.get_connection() as connection:
        return InputService(connection).list_advances(tenant_id=tenant.tenant_id, status=status_filter)


@router.post("/advances", status_code=status.HTTP_201_CREATED)
def create_advance(body: AdvanceBody, tenant: TenantContext = Depends(MANAGE)):
    with http.get_connection() as connection:
        return http.finish(connection, InputService(connection).create_advance(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, **body.model_dump()))


@router.patch("/advances/{advance_id}")
def update_advance(advance_id: str, body: AdvancePatch, tenant: TenantContext = Depends(MANAGE)):
    with http.get_connection() as connection:
        result = InputService(connection).update_advance(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, advance_id=advance_id,
                                                         changes=body.model_dump(exclude_unset=True))
        return http.finish(connection, result)


@router.post("/advances/{advance_id}/approve")
def approve_advance(advance_id: str, tenant: TenantContext = Depends(MANAGE)):
    with http.get_connection() as connection:
        return http.finish(connection, InputService(connection).approve_advance(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, advance_id=advance_id))


@router.post("/advances/{advance_id}/cancel")
def cancel_advance(advance_id: str, tenant: TenantContext = Depends(MANAGE)):
    with http.get_connection() as connection:
        return http.finish(connection, InputService(connection).cancel_advance(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, advance_id=advance_id))


@router.get("/loans")
def list_loans(status_filter: str | None = None, tenant: TenantContext = Depends(VIEW)):
    with http.get_connection() as connection:
        return InputService(connection).list_loans(tenant_id=tenant.tenant_id, status=status_filter)


@router.post("/loans", status_code=status.HTTP_201_CREATED)
def create_loan(body: LoanBody, tenant: TenantContext = Depends(MANAGE)):
    with http.get_connection() as connection:
        return http.finish(connection, InputService(connection).create_loan(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, **body.model_dump()))


@router.patch("/loans/{loan_id}")
def update_loan(loan_id: str, body: LoanPatch, tenant: TenantContext = Depends(MANAGE)):
    with http.get_connection() as connection:
        result = InputService(connection).update_loan(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, loan_id=loan_id,
                                                      changes=body.model_dump(exclude_unset=True))
        return http.finish(connection, result)


@router.post("/loans/{loan_id}/cancel")
def cancel_loan(loan_id: str, tenant: TenantContext = Depends(MANAGE)):
    with http.get_connection() as connection:
        return http.finish(connection, InputService(connection).cancel_loan(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, loan_id=loan_id))
