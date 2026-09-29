"""HTTP routes for runs, payslips and final settlements (Payroll → Runs)."""
from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel

from core.tenancy import TenantContext, require_permission
from modules.payroll.api import http, run_service
from modules.payroll.api.payslip_service import PayslipService
from modules.payroll.api.run_service import RunService

router = APIRouter()


class RunBody(BaseModel):
    period: datetime.date
    run_type: str
    label: str | None = None
    employee_ids: list[str] | None = None


class RunPatch(BaseModel):
    label: str | None = None
    employee_ids: list[str] | None = None


class ReverseBody(BaseModel):
    reason: str


class SettlementBody(BaseModel):
    employee_id: str
    unused_leave_days: Decimal = Decimal(0)
    notice_months: Decimal = Decimal(0)


class SettlementPatch(BaseModel):
    unused_leave_days: Decimal | None = None
    notice_months: Decimal | None = None


class PayslipPatch(BaseModel):
    note: str | None = None
    payment_methods: list[dict[str, Any]] | None = None


VIEW = require_permission("payroll.view_runs")
CALCULATE = require_permission("payroll.calculate_runs")


@router.get("/employees")
def employees(period: datetime.date, tenant: TenantContext = Depends(VIEW)):
    """Who can appear on a payslip that month — names only; salaries stay behind the payslips."""
    with http.get_connection() as connection:
        found = run_service.PayrollSnapshotService(connection).employees_for_period(tenant_id=tenant.tenant_id, period=period, employee_ids=None)
    keys = ("employee_id", "employee_no", "full_name", "department_id", "termination_date")
    return [{key: (item.get(key).isoformat() if key == "termination_date" and item.get(key) else item.get(key)) for key in keys}
            for item in sorted(found, key=lambda employee: employee["full_name"])]


@router.get("/runs")
def list_runs(status_filter: str | None = None, tenant: TenantContext = Depends(VIEW)):
    with http.get_connection() as connection:
        return RunService(connection).list_runs(tenant_id=tenant.tenant_id, status=status_filter)


@router.post("/runs", status_code=status.HTTP_201_CREATED)
def create_run(body: RunBody, tenant: TenantContext = Depends(CALCULATE)):
    with http.get_connection() as connection:
        return http.finish(connection, RunService(connection).create_run(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, **body.model_dump()))


@router.get("/runs/{run_id}")
def get_run(run_id: str, tenant: TenantContext = Depends(VIEW)):
    with http.get_connection() as connection:
        return http.found(RunService(connection).get_run(tenant_id=tenant.tenant_id, run_id=run_id), "payroll run", "paie")


@router.patch("/runs/{run_id}")
def update_run(run_id: str, body: RunPatch, tenant: TenantContext = Depends(CALCULATE)):
    with http.get_connection() as connection:
        result = RunService(connection).update_run(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, run_id=run_id,
                                                   changes=body.model_dump(exclude_unset=True))
        return http.finish(connection, result)


@router.delete("/runs/{run_id}")
def delete_run(run_id: str, tenant: TenantContext = Depends(CALCULATE)):
    with http.get_connection() as connection:
        return http.finish(connection, RunService(connection).delete_run(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, run_id=run_id))


@router.post("/runs/{run_id}/calculate")
def calculate_run(run_id: str, tenant: TenantContext = Depends(CALCULATE)):
    with http.get_connection() as connection:
        return http.finish(connection, RunService(connection).calculate(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, run_id=run_id))


@router.post("/runs/{run_id}/approve")
def approve_run(run_id: str, tenant: TenantContext = Depends(require_permission("payroll.approve_runs"))):
    with http.get_connection() as connection:
        return http.finish(connection, RunService(connection).approve(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, run_id=run_id))


@router.post("/runs/{run_id}/reverse")
def reverse_run(run_id: str, body: ReverseBody, tenant: TenantContext = Depends(require_permission("payroll.reverse_runs"))):
    with http.get_connection() as connection:
        result = RunService(connection).reverse(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, run_id=run_id, reason=body.reason)
        return http.finish(connection, result)


@router.get("/runs/{run_id}/payslips")
def run_payslips(run_id: str, tenant: TenantContext = Depends(VIEW)):
    with http.get_connection() as connection:
        return PayslipService(connection).list_payslips(tenant_id=tenant.tenant_id, run_id=run_id)


@router.get("/runs/{run_id}/variance")
def run_variance(run_id: str, tenant: TenantContext = Depends(VIEW)):
    with http.get_connection() as connection:
        return http.found(PayslipService(connection).variance(tenant_id=tenant.tenant_id, run_id=run_id), "payroll run", "paie")


@router.get("/runs/{run_id}/print")
def run_print(run_id: str, tenant: TenantContext = Depends(VIEW)):
    with http.get_connection() as connection:
        return http.found(PayslipService(connection).run_print(tenant_id=tenant.tenant_id, run_id=run_id), "payroll run", "paie")


@router.get("/runs/{run_id}/final-settlements")
def list_settlements(run_id: str, tenant: TenantContext = Depends(VIEW)):
    with http.get_connection() as connection:
        return RunService(connection).list_final_settlements(tenant_id=tenant.tenant_id, run_id=run_id)


@router.post("/runs/{run_id}/final-settlements", status_code=status.HTTP_201_CREATED)
def add_settlement(run_id: str, body: SettlementBody, tenant: TenantContext = Depends(CALCULATE)):
    with http.get_connection() as connection:
        result = RunService(connection).add_final_settlement(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, run_id=run_id, **body.model_dump())
        return http.finish(connection, result)


@router.patch("/runs/{run_id}/final-settlements/{settlement_id}")
def update_settlement(run_id: str, settlement_id: str, body: SettlementPatch, tenant: TenantContext = Depends(CALCULATE)):
    with http.get_connection() as connection:
        result = RunService(connection).update_final_settlement(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, run_id=run_id,
                                                                settlement_id=settlement_id, changes=body.model_dump(exclude_unset=True))
        return http.finish(connection, result)


@router.delete("/runs/{run_id}/final-settlements/{settlement_id}")
def remove_settlement(run_id: str, settlement_id: str, tenant: TenantContext = Depends(CALCULATE)):
    with http.get_connection() as connection:
        result = RunService(connection).remove_final_settlement(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, run_id=run_id,
                                                                settlement_id=settlement_id)
        return http.finish(connection, result)


@router.get("/payslips/{payslip_id}")
def get_payslip(payslip_id: str, tenant: TenantContext = Depends(VIEW)):
    with http.get_connection() as connection:
        return http.found(PayslipService(connection).get_payslip(tenant_id=tenant.tenant_id, payslip_id=payslip_id), "payslip", "bulletin")


@router.patch("/payslips/{payslip_id}")
def update_payslip(payslip_id: str, body: PayslipPatch, tenant: TenantContext = Depends(require_permission("payroll.admin_payslips"))):
    with http.get_connection() as connection:
        result = PayslipService(connection).admin_update_payslip(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, payslip_id=payslip_id,
                                                                 changes=body.model_dump(exclude_unset=True))
        return http.finish(connection, result)


@router.get("/payslips/{payslip_id}/certificate")
def certificate(payslip_id: str, tenant: TenantContext = Depends(VIEW)):
    with http.get_connection() as connection:
        return http.finish(connection, PayslipService(connection).certificate(tenant_id=tenant.tenant_id, payslip_id=payslip_id))
