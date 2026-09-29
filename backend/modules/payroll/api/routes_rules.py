"""HTTP routes for the payroll country and the rule sets (Payroll → Rules)."""
from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Body, Depends, status
from pydantic import BaseModel

from core.domain.result import Err
from core.tenancy import TenantContext, require_permission
from modules.payroll.api import http
from modules.payroll.api.rule_set_service import CHILD_KINDS, RuleSetService

router = APIRouter()


class SettingsBody(BaseModel):
    country: str
    company_address: str | None = None
    employer_inps_no: str | None = None
    employer_tax_id: str | None = None


class RuleSetBody(BaseModel):
    country: str
    name: str
    valid_from: datetime.date
    working_days_per_month: Decimal
    working_hours_per_month: Decimal
    round_to: int = 1
    round_mode: str = "half_up"
    tax_round_to: int = 1
    tax_round_mode: str = "half_up"
    settlement_reference_months: int = 12
    daily_rest_day_pay: str = "overtime_only"
    notes: str | None = None


class RuleSetPatch(BaseModel):
    country: str | None = None
    name: str | None = None
    valid_from: datetime.date | None = None
    working_days_per_month: Decimal | None = None
    working_hours_per_month: Decimal | None = None
    round_to: int | None = None
    round_mode: str | None = None
    tax_round_to: int | None = None
    tax_round_mode: str | None = None
    settlement_reference_months: int | None = None
    daily_rest_day_pay: str | None = None
    notes: str | None = None


class CopyBody(BaseModel):
    valid_from: datetime.date
    name: str


def _known_kind(kind: str) -> None:
    if kind not in CHILD_KINDS:
        http.fail(Err("NOT_FOUND", f"unknown rule table {kind}", f"table de règles inconnue {kind}"))


@router.get("/settings")
def get_settings(tenant: TenantContext = Depends(require_permission("payroll.view_rules"))):
    with http.get_connection() as connection:
        return RuleSetService(connection).get_settings(tenant_id=tenant.tenant_id)


@router.put("/settings")
def save_settings(body: SettingsBody, tenant: TenantContext = Depends(require_permission("payroll.manage_rules"))):
    with http.get_connection() as connection:
        result = RuleSetService(connection).save_settings(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, **body.model_dump())
        return http.finish(connection, result)


@router.get("/rule-sets")
def list_rule_sets(tenant: TenantContext = Depends(require_permission("payroll.view_rules"))):
    with http.get_connection() as connection:
        return RuleSetService(connection).list_rule_sets(tenant_id=tenant.tenant_id)


@router.post("/rule-sets", status_code=status.HTTP_201_CREATED)
def create_rule_set(body: RuleSetBody, tenant: TenantContext = Depends(require_permission("payroll.manage_rules"))):
    with http.get_connection() as connection:
        result = RuleSetService(connection).create_rule_set(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, **body.model_dump())
        return http.finish(connection, result)


@router.get("/rule-sets/{rule_set_id}")
def get_rule_set(rule_set_id: str, tenant: TenantContext = Depends(require_permission("payroll.view_rules"))):
    with http.get_connection() as connection:
        document = RuleSetService(connection).get_rule_set(tenant_id=tenant.tenant_id, rule_set_id=rule_set_id)
        return http.found(document, "rule set", "jeu de règles")


@router.patch("/rule-sets/{rule_set_id}")
def update_rule_set(rule_set_id: str, body: RuleSetPatch, tenant: TenantContext = Depends(require_permission("payroll.manage_rules"))):
    with http.get_connection() as connection:
        result = RuleSetService(connection).update_rule_set(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, rule_set_id=rule_set_id,
            changes=body.model_dump(exclude_unset=True),
        )
        return http.finish(connection, result)


@router.delete("/rule-sets/{rule_set_id}")
def delete_rule_set(rule_set_id: str, tenant: TenantContext = Depends(require_permission("payroll.manage_rules"))):
    with http.get_connection() as connection:
        result = RuleSetService(connection).delete_rule_set(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, rule_set_id=rule_set_id)
        return http.finish(connection, result)


@router.post("/rule-sets/{rule_set_id}/copy", status_code=status.HTTP_201_CREATED)
def copy_rule_set(rule_set_id: str, body: CopyBody, tenant: TenantContext = Depends(require_permission("payroll.manage_rules"))):
    with http.get_connection() as connection:
        result = RuleSetService(connection).copy_rule_set(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, rule_set_id=rule_set_id,
            valid_from=body.valid_from, name=body.name,
        )
        return http.finish(connection, result)


@router.post("/rule-sets/{rule_set_id}/confirm")
def confirm_rule_set(rule_set_id: str, tenant: TenantContext = Depends(require_permission("payroll.confirm_rules"))):
    with http.get_connection() as connection:
        result = RuleSetService(connection).confirm_rule_set(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, rule_set_id=rule_set_id)
        return http.finish(connection, result)


@router.post("/rule-sets/{rule_set_id}/reopen")
def reopen_rule_set(rule_set_id: str, tenant: TenantContext = Depends(require_permission("payroll.confirm_rules"))):
    with http.get_connection() as connection:
        result = RuleSetService(connection).reopen_rule_set(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, rule_set_id=rule_set_id)
        return http.finish(connection, result)


# Generic rule-table routes stay LAST: "/rule-sets/{id}/{kind}" would otherwise swallow copy/confirm/reopen.
@router.get("/rule-sets/{rule_set_id}/{kind}")
def list_rule_rows(rule_set_id: str, kind: str, tenant: TenantContext = Depends(require_permission("payroll.view_rules"))):
    _known_kind(kind)
    with http.get_connection() as connection:
        return RuleSetService(connection).list_children(tenant_id=tenant.tenant_id, rule_set_id=rule_set_id, kind=kind)


@router.post("/rule-sets/{rule_set_id}/{kind}", status_code=status.HTTP_201_CREATED)
def add_rule_row(rule_set_id: str, kind: str, values: dict[str, Any] = Body(...),
                 tenant: TenantContext = Depends(require_permission("payroll.manage_rules"))):
    _known_kind(kind)
    with http.get_connection() as connection:
        result = RuleSetService(connection).add_child(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, rule_set_id=rule_set_id, kind=kind, values=values,
        )
        return http.finish(connection, result)


@router.patch("/rule-sets/{rule_set_id}/{kind}/{row_id}")
def update_rule_row(rule_set_id: str, kind: str, row_id: str, changes: dict[str, Any] = Body(...),
                    tenant: TenantContext = Depends(require_permission("payroll.manage_rules"))):
    _known_kind(kind)
    with http.get_connection() as connection:
        result = RuleSetService(connection).update_child(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, rule_set_id=rule_set_id, kind=kind,
            row_id=row_id, changes=changes,
        )
        return http.finish(connection, result)


@router.delete("/rule-sets/{rule_set_id}/{kind}/{row_id}")
def delete_rule_row(rule_set_id: str, kind: str, row_id: str,
                    tenant: TenantContext = Depends(require_permission("payroll.manage_rules"))):
    _known_kind(kind)
    with http.get_connection() as connection:
        result = RuleSetService(connection).delete_child(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, rule_set_id=rule_set_id, kind=kind, row_id=row_id,
        )
        return http.finish(connection, result)
