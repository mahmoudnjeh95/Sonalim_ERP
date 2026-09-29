"""HTTP routes for bank file templates, payout batches and marking a run paid."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, status

from core.tenancy import TenantContext, require_permission
from modules.payroll.api import http
from modules.payroll.api.payout_service import PayoutService
from modules.payroll.api.run_service import RunService

router = APIRouter()


@router.get("/bank-file-templates")
def list_templates(tenant: TenantContext = Depends(require_permission("payroll.view_runs"))):
    with http.get_connection() as connection:
        return PayoutService(connection).list_templates(tenant_id=tenant.tenant_id)


@router.post("/bank-file-templates", status_code=status.HTTP_201_CREATED)
def create_template(values: dict[str, Any] = Body(...), tenant: TenantContext = Depends(require_permission("payroll.pay_runs"))):
    with http.get_connection() as connection:
        return http.finish(connection, PayoutService(connection).create_template(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, values=values))


@router.patch("/bank-file-templates/{template_id}")
def update_template(template_id: str, changes: dict[str, Any] = Body(...), tenant: TenantContext = Depends(require_permission("payroll.pay_runs"))):
    with http.get_connection() as connection:
        result = PayoutService(connection).update_template(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, template_id=template_id, changes=changes)
        return http.finish(connection, result)


@router.delete("/bank-file-templates/{template_id}")
def delete_template(template_id: str, tenant: TenantContext = Depends(require_permission("payroll.pay_runs"))):
    with http.get_connection() as connection:
        return http.finish(connection, PayoutService(connection).delete_template(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, template_id=template_id))


@router.post("/runs/{run_id}/payouts")
def generate_payouts(run_id: str, tenant: TenantContext = Depends(require_permission("payroll.pay_runs"))):
    with http.get_connection() as connection:
        return http.finish(connection, PayoutService(connection).generate(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, run_id=run_id))


@router.get("/runs/{run_id}/payouts")
def list_payouts(run_id: str, tenant: TenantContext = Depends(require_permission("payroll.view_runs"))):
    with http.get_connection() as connection:
        return PayoutService(connection).list_batches(tenant_id=tenant.tenant_id, run_id=run_id)


@router.post("/payout-batches/{batch_id}/confirm")
def confirm_batch(batch_id: str, tenant: TenantContext = Depends(require_permission("payroll.pay_runs"))):
    with http.get_connection() as connection:
        return http.finish(connection, PayoutService(connection).confirm_batch(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, batch_id=batch_id))


@router.get("/payout-batches/{batch_id}/file")
def batch_file(batch_id: str, tenant: TenantContext = Depends(require_permission("payroll.pay_runs"))):
    with http.get_connection() as connection:
        file_name, text = http.finish(connection, PayoutService(connection).batch_file(tenant_id=tenant.tenant_id, batch_id=batch_id))
    return http.csv_response(file_name, text)


@router.get("/payout-batches/{batch_id}/cash-sheet")
def cash_sheet(batch_id: str, tenant: TenantContext = Depends(require_permission("payroll.pay_runs"))):
    with http.get_connection() as connection:
        return http.finish(connection, PayoutService(connection).cash_sheet(tenant_id=tenant.tenant_id, batch_id=batch_id))


@router.post("/runs/{run_id}/mark-paid")
def mark_paid(run_id: str, tenant: TenantContext = Depends(require_permission("payroll.pay_runs"))):
    with http.get_connection() as connection:
        return http.finish(connection, RunService(connection).mark_paid(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, run_id=run_id))
