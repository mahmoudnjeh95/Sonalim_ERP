from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any
from urllib.parse import quote
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel

from core.db import get_connection
from core.domain.result import Err, err_detail
from core.tenancy import TenantContext, require_permission, require_session, user_has_permission
from modules.treasury.api.attachment_service import DocumentAttachmentService
from modules.treasury.api.document_service import DocumentService
from modules.treasury.api.instrument_service import InstrumentService
from modules.treasury.api.payment_order_service import PaymentOrderService
from modules.treasury.api.report_service import InvoiceStatusReportService, tabular_response
from modules.treasury.api.statement_service import StatementImportService
from modules.treasury.api.service import AccountService, BankService, SettingsService

router = APIRouter(prefix="/treasury", tags=["treasury"])

_CONFLICT = {"PAYMENT_ORDER_EXISTS", "NO_TRANSFER", "LINE_MATCHED", "INSTRUMENT_NOT_PENDING", "UNPAID_CHEQUE_ONLY", "DOCUMENT_NOT_POSTED", "INSTRUMENT_ALREADY_PROCESSED", "BANK_DUPLICATE", "ACCOUNT_NUMBER_DUPLICATE", "ACCOUNT_LOCKED", "ACCOUNT_HAS_MOVEMENTS"}


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


class BankUpdateRequest(BaseModel):
    name: str | None = None
    code: str | None = None
    swift: str | None = None
    country: str | None = None


class BranchUpdateRequest(BaseModel):
    name: str | None = None
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
    cash_type: str | None = None


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
    cash_type: str | None = None


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


@router.patch("/banks/{bank_id}")
def update_bank(bank_id: str, body: BankUpdateRequest, tenant: TenantContext = Depends(require_permission("treasury.manage_accounts"))) -> dict:
    with get_connection() as connection:
        return _unwrap(connection, BankService(connection).update_bank(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, bank_id=bank_id, changes=body.model_dump(exclude_unset=True)))


@router.patch("/branches/{branch_id}")
def update_branch(branch_id: str, body: BranchUpdateRequest, tenant: TenantContext = Depends(require_permission("treasury.manage_accounts"))) -> dict:
    with get_connection() as connection:
        return _unwrap(connection, BankService(connection).update_branch(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, branch_id=branch_id, changes=body.model_dump(exclude_unset=True)))


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


# Settings that need their own permission rather than treasury.admin_config: turning ledger posting on
# writes journal entries, which is not the same decision as adjusting a treasury setting.
SETTING_PERMISSIONS = {"ledger_posting_enabled": "treasury.admin_ledger_posting"}


@router.put("/settings/{key}")
def set_setting(key: str, body: SettingRequest, tenant: TenantContext = Depends(require_session)) -> dict:
    permission = SETTING_PERMISSIONS.get(key, "treasury.admin_config")
    with get_connection() as connection:
        if not user_has_permission(connection, user_id=tenant.user_id, permission=permission):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                {"code": "FORBIDDEN", "message": f"missing permission: {permission}", "message_fr": f"permission manquante : {permission}"},
            )
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
    issue_date: datetime.date | None = None
    branch_name: str | None = None
    deposit_date: datetime.date | None = None
    slip_reference: str | None = None
    denominations: dict[str, int] | None = None


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
    withheld_amount: Decimal = Decimal("0")
    payments: list[PaymentRequest]
    allocations: list[AllocationRequest] = []


def _create_document(direction: str, body: DocumentRequest, tenant: TenantContext) -> dict:
    with get_connection() as connection:
        allowed = user_has_permission(connection, user_id=tenant.user_id, permission="treasury.admin_add_prior_year_invoice")
        result = DocumentService(connection).create_and_post(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, direction=direction, partner_id=body.partner_id,
            doc_date=body.doc_date, currency=body.currency, reason=body.reason, with_details=body.with_details,
            note=body.note, can_add_prior_year=allowed, correlation_id=str(uuid4()), withheld_amount=body.withheld_amount,
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


class AttachmentRequest(BaseModel):
    filename: str
    content_type: str | None = None
    content_base64: str


ATTACHMENT_MANAGE_PERMISSION = {"in": "treasury.manage_receipts", "out": "treasury.manage_disbursements"}


def _attachment_direction(kind: str) -> str:
    if kind not in ("receipts", "disbursements"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, {"code": "NOT_FOUND", "message": "unknown document type", "message_fr": "type de document inconnu"})
    return "in" if kind == "receipts" else "out"


def _check_attachment_manager(connection, tenant: TenantContext, direction: str) -> None:
    permission = ATTACHMENT_MANAGE_PERMISSION[direction]
    if not user_has_permission(connection, user_id=tenant.user_id, permission=permission):
        raise HTTPException(status.HTTP_403_FORBIDDEN, {"code": "FORBIDDEN", "message": f"missing permission: {permission}",
                                                        "message_fr": f"permission manquante : {permission}"})


@router.get("/{kind}/{document_id}/attachments")
def list_attachments(kind: str, document_id: str, tenant: TenantContext = Depends(require_permission("treasury.view"))) -> list[dict]:
    direction = _attachment_direction(kind)
    with get_connection() as connection:
        result = DocumentAttachmentService(connection).list(tenant_id=tenant.tenant_id, direction=direction, document_id=document_id)
        if isinstance(result, Err):
            raise HTTPException(_err_status(result.code), err_detail(result))
        return result.value


@router.post("/{kind}/{document_id}/attachments", status_code=status.HTTP_201_CREATED)
def add_attachment(kind: str, document_id: str, body: AttachmentRequest, tenant: TenantContext = Depends(require_session)) -> dict:
    direction = _attachment_direction(kind)
    with get_connection() as connection:
        _check_attachment_manager(connection, tenant, direction)
        return _unwrap(connection, DocumentAttachmentService(connection).add(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, direction=direction, document_id=document_id,
            filename=body.filename, content_type=body.content_type, content_base64=body.content_base64))


@router.get("/{kind}/{document_id}/attachments/{attachment_id}")
def download_attachment(kind: str, document_id: str, attachment_id: str, tenant: TenantContext = Depends(require_permission("treasury.view"))) -> Response:
    direction = _attachment_direction(kind)
    with get_connection() as connection:
        result = DocumentAttachmentService(connection).read(
            tenant_id=tenant.tenant_id, direction=direction, document_id=document_id, attachment_id=attachment_id)
        if isinstance(result, Err):
            raise HTTPException(_err_status(result.code), err_detail(result))
    safe_name = quote(result.value["filename"])
    return Response(result.value["content"], media_type=result.value["content_type"],
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{safe_name}"})


@router.delete("/{kind}/{document_id}/attachments/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_attachment(kind: str, document_id: str, attachment_id: str, tenant: TenantContext = Depends(require_session)) -> Response:
    direction = _attachment_direction(kind)
    with get_connection() as connection:
        _check_attachment_manager(connection, tenant, direction)
        _unwrap(connection, DocumentAttachmentService(connection).delete(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, direction=direction, document_id=document_id, attachment_id=attachment_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
    read through the owning modules' public services so treasury never touches their tables. The
    remaining amount already accounts for documents posted but not yet applied by the invoice's owner."""
    if direction not in ("in", "out"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, {"code": "INVALID_DIRECTION", "message": "direction must be in or out",
                                                          "message_fr": "le sens doit être in ou out"})
    with get_connection() as connection:
        documents = DocumentService(connection)
        if direction == "in":
            from modules.finance.api.service import InvoiceService

            candidates = [i.id for i in InvoiceService(connection).list_invoices(tenant.tenant_id)
                          if i.partner_id == partner_id and i.status in ("issued", "partially_paid")]
        else:
            from modules.procurement.api.invoice_service import PurchaseInvoiceService

            service = PurchaseInvoiceService(connection)
            candidates = [i["id"] for s in ("validated", "partially_paid")
                          for i in service.list_invoices(tenant_id=tenant.tenant_id, status=s, partner_id=partner_id)]
        rows = []
        for invoice_id in candidates:
            detail = documents.open_invoice(tenant.tenant_id, direction, invoice_id)
            # An invoice in another currency cannot be settled here, so it is not offered.
            if not isinstance(detail, Err) and detail.value["remaining"] > 0 and detail.value["currency"] == "XOF":
                rows.append(detail.value)
        return rows


# ---- instruments, deposit slips, alerts, cash journal ------------------------------------------
class SlipItemRequest(BaseModel):
    instrument_id: str
    outcome: str
    rejection_fee: Decimal | None = None
    rejection_fee_account_id: str | None = None


class SlipRequest(BaseModel):
    # Empty: each payment goes to the account named when it was recorded.
    account_id: str | None = None
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


class MarkUnpaidRequest(BaseModel):
    rejection_fee: Decimal | None = None
    rejection_fee_account_id: str | None = None


@router.post("/instruments/{instrument_id}/unpaid")
def mark_instrument_unpaid(instrument_id: str, body: MarkUnpaidRequest | None = None,
                           tenant: TenantContext = Depends(require_permission("treasury.collect_instruments"))) -> dict:
    fee = body or MarkUnpaidRequest()
    with get_connection() as connection:
        return _unwrap(connection, InstrumentService(connection).mark_unpaid(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, instrument_id=instrument_id, correlation_id=str(uuid4()),
            rejection_fee=fee.rejection_fee, rejection_fee_account_id=fee.rejection_fee_account_id))


@router.get("/alerts")
def list_alerts(tenant: TenantContext = Depends(require_permission("treasury.view"))) -> list[dict]:
    with get_connection() as connection:
        return InstrumentService(connection).alerts(tenant_id=tenant.tenant_id)


@router.get("/journals/cash")
def cash_journal(account_id: str | None = None, year: int | None = None, date_from: datetime.date | None = None,
                 date_to: datetime.date | None = None, tenant: TenantContext = Depends(require_permission("treasury.view"))) -> dict:
    """One register over a date range, or (with `year`) one year across every register, or one."""
    with get_connection() as connection:
        if year is not None or account_id is None:
            return InstrumentService(connection).cash_journal_for_year(
                tenant_id=tenant.tenant_id, year=year or datetime.date.today().year, account_id=account_id)
        result = InstrumentService(connection).cash_journal(
            tenant_id=tenant.tenant_id, account_id=account_id, date_from=date_from, date_to=date_to)
        if isinstance(result, Err):
            raise HTTPException(_err_status(result.code), err_detail(result))
        return result.value


# ---- bank statements and reports ---------------------------------------------------------------
class StatementImportRequest(BaseModel):
    account_id: str
    filename: str
    content_base64: str
    commit: bool = False


class LinePartnerRequest(BaseModel):
    partner_id: str | None = None


class LineMatchRequest(BaseModel):
    payment_id: str | None = None


@router.post("/statements/import")
def import_statement(body: StatementImportRequest, tenant: TenantContext = Depends(require_permission("treasury.import_statements"))) -> dict:
    with get_connection() as connection:
        return _unwrap(connection, StatementImportService(connection).import_statement(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, account_id=body.account_id, filename=body.filename,
            content_base64=body.content_base64, commit=body.commit))


@router.get("/statements/lines")
def list_statement_lines(account_id: str, unmatched_only: bool = False,
                         tenant: TenantContext = Depends(require_permission("treasury.view"))) -> list[dict]:
    with get_connection() as connection:
        return StatementImportService(connection).list_lines(tenant_id=tenant.tenant_id, account_id=account_id, unmatched_only=unmatched_only)


@router.get("/statements/suggestions")
def statement_suggestions(account_id: str, tenant: TenantContext = Depends(require_permission("treasury.view"))) -> dict:
    with get_connection() as connection:
        service = StatementImportService(connection)
        return {
            "suggestions": service.suggestions(tenant_id=tenant.tenant_id, account_id=account_id),
            "payments": service.candidate_payments(tenant_id=tenant.tenant_id, account_id=account_id),
        }


@router.get("/statements/summary")
def statement_summary(account_id: str, tenant: TenantContext = Depends(require_permission("treasury.view"))) -> dict:
    with get_connection() as connection:
        result = StatementImportService(connection).summary(tenant_id=tenant.tenant_id, account_id=account_id)
        if isinstance(result, Err):
            raise HTTPException(_err_status(result.code), err_detail(result))
        return result.value


@router.patch("/statements/lines/{line_id}/partner")
def set_line_partner(line_id: str, body: LinePartnerRequest, tenant: TenantContext = Depends(require_permission("treasury.import_statements"))) -> dict:
    with get_connection() as connection:
        return _unwrap(connection, StatementImportService(connection).set_partner(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, line_id=line_id, partner_id=body.partner_id))


@router.patch("/statements/lines/{line_id}/match")
def match_statement_line(line_id: str, body: LineMatchRequest, tenant: TenantContext = Depends(require_permission("treasury.import_statements"))) -> dict:
    with get_connection() as connection:
        return _unwrap(connection, StatementImportService(connection).match(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, line_id=line_id, payment_id=body.payment_id))


@router.delete("/statements/lines/{line_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_statement_line(line_id: str, tenant: TenantContext = Depends(require_permission("treasury.import_statements"))) -> Response:
    with get_connection() as connection:
        _unwrap(connection, StatementImportService(connection).delete_line(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, line_id=line_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/statements/profile")
def get_statement_profile(account_id: str, tenant: TenantContext = Depends(require_permission("treasury.view"))) -> dict:
    with get_connection() as connection:
        return StatementImportService(connection).get_profile(tenant_id=tenant.tenant_id, account_id=account_id)


@router.put("/statements/profile")
def put_statement_profile(account_id: str, body: dict[str, Any], tenant: TenantContext = Depends(require_permission("treasury.admin_config"))) -> dict:
    with get_connection() as connection:
        return _unwrap(connection, StatementImportService(connection).set_profile(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, account_id=account_id, profile=body))


REPORT_HEADERS = {
    ("sales", "fr"): ["Client", "Encaissement", "Numéro", "Date", "Montant de facture", "Montant de règlement", "Montant restant", "Etat"],
    ("purchases", "fr"): ["Fournisseur", "Décaissement", "Numéro", "Date", "Montant de facture", "Montant de règlement", "Montant restant", "Etat"],
    ("sales", "en"): ["Customer", "Receipt", "Number", "Date", "Invoice amount", "Settled amount", "Remaining amount", "Status"],
    ("purchases", "en"): ["Supplier", "Disbursement", "Number", "Date", "Invoice amount", "Settled amount", "Remaining amount", "Status"],
}
REPORT_WITHOUT_DOCUMENT = {
    ("sales", "fr"): "Sans encaissement", ("purchases", "fr"): "Sans décaissement",
    ("sales", "en"): "No receipt", ("purchases", "en"): "No disbursement",
}


def _report(kind: str, fmt: str | None, lang: str, tenant: TenantContext):
    direction = "in" if kind == "sales" else "out"
    language = "fr" if lang == "fr" else "en"
    with get_connection() as connection:
        service = InvoiceStatusReportService(connection)
        rows = service.sales(tenant_id=tenant.tenant_id) if kind == "sales" else service.purchases(tenant_id=tenant.tenant_id)
        summary = InvoiceStatusReportService.by_partner(rows)
        groups = service.by_partner_and_document(tenant_id=tenant.tenant_id, direction=direction, rows=rows)
    if fmt in ("csv", "xlsx"):
        data = InvoiceStatusReportService.flat_rows(groups, without_label=REPORT_WITHOUT_DOCUMENT[(kind, language)])
        return tabular_response(REPORT_HEADERS[(kind, language)], data, fmt, f"{kind}-invoice-status")
    return {"partners": summary, "groups": groups, "invoices": rows}


@router.get("/reports/sales-invoices")
def sales_invoice_report(format: str | None = None, lang: str = "en", tenant: TenantContext = Depends(require_permission("treasury.view"))):
    return _report("sales", format, lang, tenant)


@router.get("/reports/purchase-invoices")
def purchase_invoice_report(format: str | None = None, lang: str = "en", tenant: TenantContext = Depends(require_permission("treasury.view"))):
    return _report("purchases", format, lang, tenant)


# ---- payment orders and notifications ----------------------------------------------------------
class NotifyRequest(BaseModel):
    user_id: str


class PaymentOrderRequest(BaseModel):
    note: str | None = None


@router.get("/payment-orders")
def list_payment_orders(tenant: TenantContext = Depends(require_permission("treasury.view"))) -> list[dict]:
    with get_connection() as connection:
        return PaymentOrderService(connection).list(tenant_id=tenant.tenant_id)


@router.post("/disbursements/{document_id}/payment-order", status_code=status.HTTP_201_CREATED)
def create_payment_order(document_id: str, body: PaymentOrderRequest,
                         tenant: TenantContext = Depends(require_permission("treasury.manage_disbursements"))) -> dict:
    with get_connection() as connection:
        return _unwrap(connection, PaymentOrderService(connection).create_for_disbursement(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, disbursement_id=document_id, note=body.note))


@router.get("/payment-orders/{order_id}")
def get_payment_order(order_id: str, tenant: TenantContext = Depends(require_permission("treasury.view"))) -> dict:
    with get_connection() as connection:
        result = PaymentOrderService(connection).get(tenant_id=tenant.tenant_id, order_id=order_id)
        if isinstance(result, Err):
            raise HTTPException(_err_status(result.code), err_detail(result))
        return result.value


@router.post("/payment-orders/{order_id}/notify", status_code=status.HTTP_201_CREATED)
def notify_payment_order(order_id: str, body: NotifyRequest,
                         tenant: TenantContext = Depends(require_permission("treasury.manage_disbursements"))) -> dict:
    with get_connection() as connection:
        return _unwrap(connection, PaymentOrderService(connection).notify(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, order_id=order_id, user_id=body.user_id))


class InvoicePaymentOrderRequest(BaseModel):
    order_date: datetime.date
    due_date: datetime.date
    method: str
    invoice_id: str
    employee_user_id: str
    department: str | None = None
    note: str | None = None


@router.get("/invoice-activity")
def invoice_activity(direction: str, invoice_id: str, tenant: TenantContext = Depends(require_permission("treasury.view"))) -> dict:
    """What treasury did for one invoice -- its receipts or disbursements and, for a purchase invoice, its
    payment orders -- so the invoice's own screen can show it without reading treasury's tables."""
    if direction not in ("in", "out"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, {"code": "INVALID_DIRECTION", "message": "direction must be in or out",
                                                          "message_fr": "le sens doit être in ou out"})
    with get_connection() as connection:
        orders = PaymentOrderService(connection).list_invoice_orders(tenant_id=tenant.tenant_id) if direction == "out" else []
        return {
            "documents": DocumentService(connection).payments_for_invoice(tenant_id=tenant.tenant_id, direction=direction, invoice_id=invoice_id),
            "payment_orders": [o for o in orders if o["invoice_id"] == invoice_id],
        }


@router.get("/invoice-payment-orders")
def list_invoice_payment_orders(tenant: TenantContext = Depends(require_permission("treasury.view"))) -> list[dict]:
    with get_connection() as connection:
        return PaymentOrderService(connection).list_invoice_orders(tenant_id=tenant.tenant_id)


@router.post("/invoice-payment-orders", status_code=status.HTTP_201_CREATED)
def create_invoice_payment_order(body: InvoicePaymentOrderRequest,
                                 tenant: TenantContext = Depends(require_permission("treasury.manage_disbursements"))) -> dict:
    with get_connection() as connection:
        return _unwrap(connection, PaymentOrderService(connection).create_invoice_order(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, **body.model_dump()))


@router.post("/invoice-payment-orders/{order_id}/notify", status_code=status.HTTP_201_CREATED)
def notify_invoice_payment_order(order_id: str, body: NotifyRequest,
                                 tenant: TenantContext = Depends(require_permission("treasury.manage_disbursements"))) -> dict:
    with get_connection() as connection:
        return _unwrap(connection, PaymentOrderService(connection).notify_invoice_order(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, order_id=order_id, user_id=body.user_id))


@router.get("/notifiable-users")
def notifiable_users(tenant: TenantContext = Depends(require_permission("treasury.manage_disbursements"))) -> list[dict]:
    with get_connection() as connection:
        return PaymentOrderService(connection).notifiable_users(tenant_id=tenant.tenant_id)


@router.get("/notifications")
def my_notifications(tenant: TenantContext = Depends(require_permission("treasury.view"))) -> list[dict]:
    with get_connection() as connection:
        return PaymentOrderService(connection).notifications(tenant_id=tenant.tenant_id, user_id=tenant.user_id)


@router.post("/notifications/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def read_notification(notification_id: str, tenant: TenantContext = Depends(require_permission("treasury.view"))) -> Response:
    with get_connection() as connection:
        _unwrap(connection, PaymentOrderService(connection).mark_read(
            tenant_id=tenant.tenant_id, user_id=tenant.user_id, notification_id=notification_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
