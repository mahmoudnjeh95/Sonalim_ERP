from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from core.db import get_connection
from core.domain.result import Err, err_detail
from core.tenancy import TenantContext, require_permission
from modules.treasury.api.service import AccountService, BankService, SettingsService

router = APIRouter(prefix="/treasury", tags=["treasury"])

_CONFLICT = {"BANK_DUPLICATE", "ACCOUNT_NUMBER_DUPLICATE", "ACCOUNT_LOCKED", "ACCOUNT_HAS_MOVEMENTS"}


def _err_status(code: str) -> int:
    if code == "NOT_FOUND":
        return status.HTTP_404_NOT_FOUND
    if code in _CONFLICT:
        return status.HTTP_409_CONFLICT
    return status.HTTP_400_BAD_REQUEST


def _unwrap(connection, result):
    if isinstance(result, Err):
        connection.rollback()
        raise HTTPException(_err_status(result.code), err_detail(result))
    connection.commit()
    return result.value


class BankRequest(BaseModel):
    name: str
    code: str | None = None
    swift: str | None = None
    country: str | None = None


class BranchRequest(BaseModel):
    name: str
    city: str | None = None
    address: str | None = None
    phone: str | None = None


class AccountRequest(BaseModel):
    kind: str
    name: str
    currency: str = "XOF"
    account_number: str | None = None
    iban: str | None = None
    branch_id: str | None = None
    operator: str | None = None
    phone: str | None = None
    opening_balance: Decimal = Decimal("0")
    allow_overdraft: bool = False
    ledger_account_code: str | None = None


class AccountUpdateRequest(BaseModel):
    name: str | None = None
    currency: str | None = None
    account_number: str | None = None
    iban: str | None = None
    branch_id: str | None = None
    operator: str | None = None
    phone: str | None = None
    opening_balance: Decimal | None = None
    allow_overdraft: bool | None = None
    ledger_account_code: str | None = None
    is_active: bool | None = None


class SettingRequest(BaseModel):
    value: Any = None


class AlertRuleRequest(BaseModel):
    offset_days: int


@router.get("/banks")
def list_banks(tenant: TenantContext = Depends(require_permission("treasury.view"))) -> list[dict]:
    with get_connection() as connection:
        return BankService(connection).list_banks(tenant_id=tenant.tenant_id)


@router.post("/banks", status_code=status.HTTP_201_CREATED)
def create_bank(body: BankRequest, tenant: TenantContext = Depends(require_permission("treasury.manage_accounts"))) -> dict:
    with get_connection() as connection:
        return _unwrap(connection, BankService(connection).create_bank(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, **body.model_dump()))


@router.post("/banks/{bank_id}/active")
def set_bank_active(bank_id: str, is_active: bool, tenant: TenantContext = Depends(require_permission("treasury.manage_accounts"))) -> dict:
    with get_connection() as connection:
        _unwrap(connection, BankService(connection).set_bank_active(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, bank_id=bank_id, is_active=is_active))
    return {"id": bank_id, "is_active": is_active}


@router.post("/banks/{bank_id}/branches", status_code=status.HTTP_201_CREATED)
def add_branch(bank_id: str, body: BranchRequest, tenant: TenantContext = Depends(require_permission("treasury.manage_accounts"))) -> dict:
    with get_connection() as connection:
        return _unwrap(connection, BankService(connection).add_branch(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, bank_id=bank_id, **body.model_dump()))


@router.get("/accounts")
def list_accounts(kind: str | None = None, currency: str | None = None, include_inactive: bool = False,
                  tenant: TenantContext = Depends(require_permission("treasury.view"))) -> list[dict]:
    with get_connection() as connection:
        return AccountService(connection).list_accounts(
            tenant_id=tenant.tenant_id, kind=kind, currency=currency, include_inactive=include_inactive)


@router.post("/accounts", status_code=status.HTTP_201_CREATED)
def create_account(body: AccountRequest, tenant: TenantContext = Depends(require_permission("treasury.manage_accounts"))) -> dict:
    fields = body.model_dump()
    kind = fields.pop("kind")
    with get_connection() as connection:
        return _unwrap(connection, AccountService(connection).create_account(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, kind=kind, fields=fields))


@router.patch("/accounts/{account_id}")
def update_account(account_id: str, body: AccountUpdateRequest,
                   tenant: TenantContext = Depends(require_permission("treasury.manage_accounts"))) -> dict:
    with get_connection() as connection:
        return _unwrap(connection, AccountService(connection).update_account(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, account_id=account_id,
            changes=body.model_dump(exclude_unset=True)))


@router.delete("/accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(account_id: str, tenant: TenantContext = Depends(require_permission("treasury.manage_accounts"))) -> None:
    with get_connection() as connection:
        _unwrap(connection, AccountService(connection).delete_account(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, account_id=account_id))


@router.get("/accounts/{account_id}/movements")
def list_movements(account_id: str, date_from: datetime.date | None = None, date_to: datetime.date | None = None,
                   tenant: TenantContext = Depends(require_permission("treasury.view"))) -> list[dict]:
    with get_connection() as connection:
        return AccountService(connection).list_movements(
            tenant_id=tenant.tenant_id, account_id=account_id, date_from=date_from, date_to=date_to)


@router.get("/settings")
def get_settings(tenant: TenantContext = Depends(require_permission("treasury.view"))) -> dict:
    with get_connection() as connection:
        return SettingsService(connection).get_settings(tenant_id=tenant.tenant_id)


@router.put("/settings/{key}")
def set_setting(key: str, body: SettingRequest, tenant: TenantContext = Depends(require_permission("treasury.admin_config"))) -> dict:
    with get_connection() as connection:
        _unwrap(connection, SettingsService(connection).set_setting(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, key=key, value=body.value))
        return SettingsService(connection).get_settings(tenant_id=tenant.tenant_id)


@router.get("/alert-rules")
def list_alert_rules(tenant: TenantContext = Depends(require_permission("treasury.view"))) -> list[dict]:
    with get_connection() as connection:
        return SettingsService(connection).list_alert_rules(tenant_id=tenant.tenant_id)


@router.put("/alert-rules/{direction}/{method}")
def set_alert_rule(direction: str, method: str, body: AlertRuleRequest,
                   tenant: TenantContext = Depends(require_permission("treasury.admin_config"))) -> list[dict]:
    with get_connection() as connection:
        _unwrap(connection, SettingsService(connection).set_alert_rule(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, direction=direction, method=method, offset_days=body.offset_days))
        return SettingsService(connection).list_alert_rules(tenant_id=tenant.tenant_id)
