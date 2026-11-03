from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel

from core.db import get_connection
from core.domain.result import Err, err_detail
from core.tenancy import TenantContext, require_permission, user_has_permission
from modules.treasury.api.document_service import DocumentService
from modules.treasury.api.instrument_service import InstrumentService
from modules.treasury.api.service import AccountService, BankService, SettingsService

router = APIRouter(prefix="/treasury", tags=["treasury"])

_CONFLICT = {"INSTRUMENT_NOT_PENDING", "UNPAID_CHEQUE_ONLY", "DOCUMENT_NOT_POSTED", "INSTRUMENT_ALREADY_PROCESSED", "BANK_DUPLICATE", "ACCOUNT_NUMBER_DUPLICATE", "ACCOUNT_LOCKED", "ACCOUNT_HAS_MOVEMENTS"}


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


@router.delete("/accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_account(account_id: str, tenant: TenantContext = Depends(require_permission("treasury.manage_accounts"))) -> Response:
    with get_connection() as connection:
        _unwrap(connection, AccountService(connection).delete_account(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, account_id=account_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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


# ---- receipts and disbursements ----------------------------------------------------------------
class PaymentRequest(BaseModel):
    method: str
    amount: Decimal
    account_id: str | None = None
    number: str | None = None
    bank_name: str | None = None
    due_date: datetime.date | None = None
    reference: str | None = None


class AllocationRequest(BaseModel):
    invoice_id: str
    amount: Decimal


class DocumentRequest(BaseModel):
    partner_id: str
    doc_date: datetime.date
    currency: str = "XOF"
    reason: str = "full"
    with_details: bool = True
    note: str | None = None
    payments: list[PaymentRequest]
    allocations: list[AllocationRequest] = []


def _create_document(direction: str, body: DocumentRequest, tenant: TenantContext) -> dict:
    with get_connection() as connection:
        allowed = user_has_permission(connection, user_id=tenant.user_id, permission="treasury.add_prior_year_invoice")
        result = DocumentService(connection).create_and_post(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, direction=direction, partner_id=body.partner_id,
            doc_date=body.doc_date, currency=body.currency, reason=body.reason, with_details=body.with_details,
            note=body.note, can_add_prior_year=allowed, correlation_id=str(uuid4()),
            payments=[p.model_dump() for p in body.payments], allocations=[a.model_dump() for a in body.allocations],
        )
        return _unwrap(connection, result)


def _get_document(direction: str, document_id: str, tenant: TenantContext) -> dict:
    with get_connection() as connection:
        result = DocumentService(connection).get(tenant_id=tenant.tenant_id, document_id=document_id, direction=direction)
        if isinstance(result, Err):
            raise HTTPException(_err_status(result.code), err_detail(result))
        return result.value


def _cancel_document(direction: str, document_id: str, tenant: TenantContext) -> dict:
    with get_connection() as connection:
        result = DocumentService(connection).cancel(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, document_id=document_id, direction=direction,
            correlation_id=str(uuid4()))
        return _unwrap(connection, result)


@router.get("/receipts")
def list_receipts(partner_id: str | None = None, status_filter: str | None = None,
                  date_from: datetime.date | None = None, date_to: datetime.date | None = None,
                  tenant: TenantContext = Depends(require_permission("treasury.view"))) -> list[dict]:
    with get_connection() as connection:
        return DocumentService(connection).list(tenant_id=tenant.tenant_id, direction="in", partner_id=partner_id,
                                                status=status_filter, date_from=date_from, date_to=date_to)


@router.post("/receipts", status_code=status.HTTP_201_CREATED)
def create_receipt(body: DocumentRequest, tenant: TenantContext = Depends(require_permission("treasury.manage_receipts"))) -> dict:
    return _create_document("in", body, tenant)


@router.get("/receipts/{document_id}")
def get_receipt(document_id: str, tenant: TenantContext = Depends(require_permission("treasury.view"))) -> dict:
    return _get_document("in", document_id, tenant)


@router.post("/receipts/{document_id}/cancel")
def cancel_receipt(document_id: str, tenant: TenantContext = Depends(require_permission("treasury.manage_receipts"))) -> dict:
    return _cancel_document("in", document_id, tenant)


@router.get("/disbursements")
def list_disbursements(partner_id: str | None = None, status_filter: str | None = None,
                       date_from: datetime.date | None = None, date_to: datetime.date | None = None,
                       tenant: TenantContext = Depends(require_permission("treasury.view"))) -> list[dict]:
    with get_connection() as connection:
        return DocumentService(connection).list(tenant_id=tenant.tenant_id, direction="out", partner_id=partner_id,
                                                status=status_filter, date_from=date_from, date_to=date_to)


@router.post("/disbursements", status_code=status.HTTP_201_CREATED)
def create_disbursement(body: DocumentRequest, tenant: TenantContext = Depends(require_permission("treasury.manage_disbursements"))) -> dict:
    return _create_document("out", body, tenant)


@router.get("/disbursements/{document_id}")
def get_disbursement(document_id: str, tenant: TenantContext = Depends(require_permission("treasury.view"))) -> dict:
    return _get_document("out", document_id, tenant)


@router.post("/disbursements/{document_id}/cancel")
def cancel_disbursement(document_id: str, tenant: TenantContext = Depends(require_permission("treasury.manage_disbursements"))) -> dict:
    return _cancel_document("out", document_id, tenant)


@router.get("/open-invoices")
def list_open_invoices(direction: str, partner_id: str, tenant: TenantContext = Depends(require_permission("treasury.view"))) -> list[dict]:
    """Invoices a receipt (direction=in) or disbursement (direction=out) can still be allocated to,
    read through the owning modules' public services so treasury never touches their tables."""
    if direction not in ("in", "out"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, {"code": "INVALID_DIRECTION", "message": "direction must be in or out",
                                                          "message_fr": "le sens doit être in ou out"})
    with get_connection() as connection:
        if direction == "in":
            from modules.finance.api.service import InvoiceService

            service = InvoiceService(connection)
            rows = []
            for invoice in service.list_invoices(tenant.tenant_id):
                if invoice.partner_id == partner_id and invoice.status in ("issued", "partially_paid"):
                    detail = service.get_invoice(tenant_id=tenant.tenant_id, invoice_id=invoice.id)
                    if not isinstance(detail, Err):
                        rows.append(detail.value)
            return rows
        from modules.procurement.api.invoice_service import PurchaseInvoiceService

        return [
            i for status_name in ("validated", "partially_paid")
            for i in PurchaseInvoiceService(connection).list_invoices(tenant_id=tenant.tenant_id, status=status_name, partner_id=partner_id)
        ]


# ---- instruments, deposit slips, alerts, cash journal ------------------------------------------
class SlipItemRequest(BaseModel):
    instrument_id: str
    outcome: str


class SlipRequest(BaseModel):
    account_id: str
    slip_date: datetime.date
    note: str | None = None
    items: list[SlipItemRequest]


@router.get("/instruments")
def list_instruments(direction: str | None = None, status_filter: str | None = None, due_to: datetime.date | None = None,
                     tenant: TenantContext = Depends(require_permission("treasury.view"))) -> list[dict]:
    with get_connection() as connection:
        return InstrumentService(connection).list_instruments(
            tenant_id=tenant.tenant_id, direction=direction, status=status_filter, due_to=due_to)


@router.post("/deposit-slips", status_code=status.HTTP_201_CREATED)
def post_deposit_slip(body: SlipRequest, tenant: TenantContext = Depends(require_permission("treasury.collect_instruments"))) -> dict:
    with get_connection() as connection:
        return _unwrap(connection, InstrumentService(connection).post_slip(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, account_id=body.account_id, slip_date=body.slip_date,
            note=body.note, items=[i.model_dump() for i in body.items], correlation_id=str(uuid4())))


@router.post("/instruments/{instrument_id}/unpaid")
def mark_instrument_unpaid(instrument_id: str, tenant: TenantContext = Depends(require_permission("treasury.collect_instruments"))) -> dict:
    with get_connection() as connection:
        return _unwrap(connection, InstrumentService(connection).mark_unpaid(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, instrument_id=instrument_id, correlation_id=str(uuid4())))


@router.get("/alerts")
def list_alerts(tenant: TenantContext = Depends(require_permission("treasury.view"))) -> list[dict]:
    with get_connection() as connection:
        return InstrumentService(connection).alerts(tenant_id=tenant.tenant_id)


@router.get("/journals/cash")
def cash_journal(account_id: str, date_from: datetime.date | None = None, date_to: datetime.date | None = None,
                 tenant: TenantContext = Depends(require_permission("treasury.view"))) -> dict:
    with get_connection() as connection:
        result = InstrumentService(connection).cash_journal(
            tenant_id=tenant.tenant_id, account_id=account_id, date_from=date_from, date_to=date_to)
        if isinstance(result, Err):
            raise HTTPException(_err_status(result.code), err_detail(result))
        return result.value
