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
from core.tabular_export import tabular_response
from core.tenancy import TenantContext, require_permission, user_has_permission
from modules.procurement.api.credit_note_service import PurchaseCreditNoteService
from modules.procurement.api.invoice_attachment_service import PurchaseInvoiceAttachmentService
from modules.procurement.api.invoice_service import PurchaseInvoiceService
from modules.procurement.api.payables_service import PayablesService
from modules.procurement.domain.payables import BUCKETS

router = APIRouter(prefix="/purchase-invoices", tags=["procurement"])
credit_note_router = APIRouter(prefix="/purchase-credit-notes", tags=["procurement"])

VIEW = "procurement.view_purchase_invoices"
MANAGE = "procurement.manage_purchase_invoices"
ADMIN = "procurement.admin_purchase_invoices"
# Validating an invoice that bills more than was received and not yet invoiced; held back from every
# default role (see core.permissions_registry.ADMINISTRATOR_HELD_BACK_PERMISSIONS).
OVER_RECEIPT = "procurement.admin_invoice_beyond_receipts"


class InvoiceLine(BaseModel):
    product_id: str | None = None
    description: str | None = None
    quantity: Decimal
    uom_id: str | None = None
    unit_price: Decimal
    discount_rate: Decimal = Decimal("0")
    vat_rate: Decimal | None = None
    purchase_order_line_id: str | None = None
    receipt_id: str | None = None


class CreatePurchaseInvoiceRequest(BaseModel):
    partner_id: str
    supplier_invoice_number: str
    invoice_date: datetime.date
    amount: Decimal | None = None
    currency: str = "XOF"
    due_date: datetime.date | None = None
    purchase_order_id: str | None = None
    note: str | None = None
    lines: list[InvoiceLine] = []
    receipt_ids: list[str] = []


class FromReceiptsRequest(BaseModel):
    receipt_ids: list[str]
    supplier_invoice_number: str
    invoice_date: datetime.date
    due_date: datetime.date | None = None
    note: str | None = None


class UpdatePurchaseInvoiceRequest(BaseModel):
    partner_id: str | None = None
    supplier_invoice_number: str | None = None
    invoice_date: datetime.date | None = None
    amount: Decimal | None = None
    currency: str | None = None
    due_date: datetime.date | None = None
    purchase_order_id: str | None = None
    note: str | None = None
    lines: list[InvoiceLine] | None = None
    receipt_ids: list[str] | None = None


class SettingsRequest(BaseModel):
    default_vat_rate: Decimal


class AttachmentRequest(BaseModel):
    filename: str
    content_type: str | None = None
    content_base64: str


class CreditLine(BaseModel):
    invoice_line_id: str
    quantity: Decimal
    unit_price: Decimal | None = None
    discount_rate: Decimal | None = None
    vat_rate: Decimal | None = None
    description: str | None = None


class CreateCreditNoteRequest(BaseModel):
    invoice_id: str
    note_date: datetime.date
    reason: str
    lines: list[CreditLine]


class UpdateCreditNoteRequest(BaseModel):
    note_date: datetime.date | None = None
    reason: str | None = None
    lines: list[CreditLine] | None = None


_CONFLICTS = {
    "INVALID_TRANSITION", "INVOICE_NOT_DRAFT", "INVOICE_HAS_PAYMENTS", "INVOICE_HAS_CREDIT_NOTES", "DUPLICATE_SUPPLIER_INVOICE",
    "INVOICED_MORE_THAN_RECEIVED", "CREDIT_NOTE_NOT_DRAFT", "CREDIT_EXCEEDS_INVOICE", "INVOICE_NOT_VALIDATED",
    "RECEIPT_NOT_INVOICEABLE",
}


def _err_status(code: str) -> int:
    if code == "NOT_FOUND":
        return status.HTTP_404_NOT_FOUND
    if code in _CONFLICTS:
        return status.HTTP_409_CONFLICT
    return status.HTTP_400_BAD_REQUEST


def _raise(result: Err) -> None:
    raise HTTPException(_err_status(result.code), err_detail(result))


def _detail(connection, tenant_id: str, invoice_id: str) -> dict[str, Any]:
    result = PurchaseInvoiceService(connection).get_detail(tenant_id=tenant_id, invoice_id=invoice_id)
    if isinstance(result, Err):
        _raise(result)
    return result.value


def _finish(connection, result, tenant_id: str) -> dict[str, Any]:
    if isinstance(result, Err):
        connection.rollback()
        _raise(result)
    connection.commit()
    return _detail(connection, tenant_id, result.value["id"])


def _commit(connection, result) -> Any:
    if isinstance(result, Err):
        connection.rollback()
        _raise(result)
    connection.commit()
    return result.value


@router.get("")
def list_purchase_invoices(
    status_filter: str | None = None,
    partner_id: str | None = None,
    overdue: bool = False,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    tenant: TenantContext = Depends(require_permission(VIEW)),
) -> list[dict]:
    with get_connection() as connection:
        return PurchaseInvoiceService(connection).list_invoices(
            tenant_id=tenant.tenant_id, status=status_filter, partner_id=partner_id, overdue=overdue,
            date_from=date_from, date_to=date_to,
        )


EXPORT_HEADERS = {
    "fr": ["N°", "Fournisseur", "N° fournisseur", "Date", "Échéance", "Total HT", "Remise", "TVA", "Total TTC", "Avoirs",
           "Net à payer", "Payé", "Reste dû", "Statut"],
    "en": ["No.", "Supplier", "Supplier ref.", "Date", "Due date", "Total excl. tax", "Discount", "VAT", "Total incl. tax",
           "Credit notes", "Amount due", "Paid", "Remaining", "Status"],
}


@router.get("/export")
def export_purchase_invoices(
    fmt: str = "xlsx",
    lang: str = "fr",
    status_filter: str | None = None,
    partner_id: str | None = None,
    overdue: bool = False,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    tenant: TenantContext = Depends(require_permission(VIEW)),
) -> Response:
    with get_connection() as connection:
        invoices = PurchaseInvoiceService(connection).list_invoices(
            tenant_id=tenant.tenant_id, status=status_filter, partner_id=partner_id, overdue=overdue,
            date_from=date_from, date_to=date_to,
        )
        names = dict(connection.execute("SELECT id, name FROM core.partners WHERE tenant_id = %s", (tenant.tenant_id,)).fetchall())
    rows = [
        [i["number"] or "", names.get(i["partner_id"], ""), i["supplier_invoice_number"], i["invoice_date"].isoformat(),
         i["due_date"].isoformat() if i["due_date"] else "", i["total_excl_tax"], i["total_discount"], i["total_vat"],
         i["total_incl_tax"], i["credited_amount"], i["amount"], i["amount_paid"], i["remaining"], i["status"]]
        for i in invoices
    ]
    headers = EXPORT_HEADERS["en" if lang == "en" else "fr"]
    return tabular_response(headers, rows, "csv" if fmt == "csv" else "xlsx", "factures-achat" if lang != "en" else "purchase-invoices")


AGING_HEADERS = {
    "fr": ["Fournisseur", "Reste dû", "Non échu", "1-30 j", "31-60 j", "61-90 j", "> 90 j", "Retard max (j)"],
    "en": ["Supplier", "Remaining", "Not due", "1-30 d", "31-60 d", "61-90 d", "> 90 d", "Max days late"],
}


@router.get("/payables/aging", response_model=None)
def payables_aging(format: str | None = None, lang: str = "fr", tenant: TenantContext = Depends(require_permission(VIEW))):
    """What we owe each supplier, aged by days past the invoice's due date."""
    with get_connection() as connection:
        rows = PayablesService(connection).aging(tenant_id=tenant.tenant_id)
    if format not in ("csv", "xlsx"):
        return rows
    table = [[r["partner_name"], r["remaining"], *[r[f"bucket_{k}"] for k, _, _ in BUCKETS], r["max_days_overdue"]] for r in rows]
    language = "en" if lang == "en" else "fr"
    return tabular_response(AGING_HEADERS[language], table, format, "balance-agee-fournisseurs" if language == "fr" else "payables-aging")


@router.get("/payables/statement/{partner_id}")
def payables_statement(partner_id: str, date_from: datetime.date | None = None, date_to: datetime.date | None = None,
                       tenant: TenantContext = Depends(require_permission(VIEW))) -> dict:
    """A supplier's account: invoices, credit notes and payments with a running balance (positive = we owe)."""
    with get_connection() as connection:
        return PayablesService(connection).statement(
            tenant_id=tenant.tenant_id, partner_id=partner_id, date_from=date_from, date_to=date_to)


@router.get("/settings")
def get_invoice_settings(tenant: TenantContext = Depends(require_permission(VIEW))) -> dict:
    with get_connection() as connection:
        return {"default_vat_rate": PurchaseInvoiceService(connection).default_vat_rate(tenant_id=tenant.tenant_id)}


@router.put("/settings")
def update_invoice_settings(body: SettingsRequest, tenant: TenantContext = Depends(require_permission(ADMIN))) -> dict:
    with get_connection() as connection:
        return _commit(connection, PurchaseInvoiceService(connection).set_default_vat_rate(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, rate=body.default_vat_rate))


@router.get("/invoiceable-receipts")
def list_invoiceable_receipts(partner_id: str | None = None, tenant: TenantContext = Depends(require_permission(VIEW))) -> list[dict]:
    with get_connection() as connection:
        return PurchaseInvoiceService(connection).invoiceable_receipts(tenant_id=tenant.tenant_id, partner_id=partner_id)


@router.post("/from-receipts", status_code=status.HTTP_201_CREATED)
def create_from_receipts(body: FromReceiptsRequest, tenant: TenantContext = Depends(require_permission(MANAGE))) -> dict:
    with get_connection() as connection:
        result = PurchaseInvoiceService(connection).create_from_receipts(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, receipt_ids=body.receipt_ids,
            supplier_invoice_number=body.supplier_invoice_number, invoice_date=body.invoice_date, due_date=body.due_date,
            note=body.note,
        )
        return _finish(connection, result, tenant.tenant_id)


@router.get("/{invoice_id}")
def get_purchase_invoice(invoice_id: str, tenant: TenantContext = Depends(require_permission(VIEW))) -> dict:
    with get_connection() as connection:
        return _detail(connection, tenant.tenant_id, invoice_id)


@router.post("", status_code=status.HTTP_201_CREATED)
def create_purchase_invoice(body: CreatePurchaseInvoiceRequest, tenant: TenantContext = Depends(require_permission(MANAGE))) -> dict:
    with get_connection() as connection:
        result = PurchaseInvoiceService(connection).create_draft(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, partner_id=body.partner_id,
            supplier_invoice_number=body.supplier_invoice_number, invoice_date=body.invoice_date,
            amount=body.amount, currency=body.currency, due_date=body.due_date,
            purchase_order_id=body.purchase_order_id, note=body.note,
            lines=[line.model_dump() for line in body.lines], receipt_ids=body.receipt_ids,
        )
        return _finish(connection, result, tenant.tenant_id)


@router.patch("/{invoice_id}")
def update_purchase_invoice(
    invoice_id: str, body: UpdatePurchaseInvoiceRequest, tenant: TenantContext = Depends(require_permission(MANAGE)),
) -> dict:
    changes = body.model_dump(exclude_unset=True)
    if changes.get("lines") is not None:
        changes["lines"] = [dict(line) for line in changes["lines"]]
    with get_connection() as connection:
        result = PurchaseInvoiceService(connection).update_draft(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, invoice_id=invoice_id, changes=changes)
        return _finish(connection, result, tenant.tenant_id)


@router.post("/{invoice_id}/validate")
def validate_purchase_invoice(invoice_id: str, tenant: TenantContext = Depends(require_permission(MANAGE))) -> dict:
    with get_connection() as connection:
        may_exceed = user_has_permission(connection, user_id=tenant.user_id, permission=OVER_RECEIPT)
        result = PurchaseInvoiceService(connection).validate(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, invoice_id=invoice_id, correlation_id=str(uuid4()),
            may_exceed_receipts=may_exceed,
        )
        return _finish(connection, result, tenant.tenant_id)


@router.post("/{invoice_id}/cancel")
def cancel_purchase_invoice(invoice_id: str, tenant: TenantContext = Depends(require_permission(MANAGE))) -> dict:
    with get_connection() as connection:
        result = PurchaseInvoiceService(connection).cancel(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, invoice_id=invoice_id, correlation_id=str(uuid4()))
        return _finish(connection, result, tenant.tenant_id)


@router.get("/{invoice_id}/attachments")
def list_invoice_attachments(invoice_id: str, tenant: TenantContext = Depends(require_permission(VIEW))) -> list[dict]:
    with get_connection() as connection:
        result = PurchaseInvoiceAttachmentService(connection).list(tenant_id=tenant.tenant_id, invoice_id=invoice_id)
        if isinstance(result, Err):
            _raise(result)
        return result.value


@router.post("/{invoice_id}/attachments", status_code=status.HTTP_201_CREATED)
def add_invoice_attachment(invoice_id: str, body: AttachmentRequest, tenant: TenantContext = Depends(require_permission(MANAGE))) -> dict:
    with get_connection() as connection:
        return _commit(connection, PurchaseInvoiceAttachmentService(connection).add(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, invoice_id=invoice_id, filename=body.filename,
            content_type=body.content_type, content_base64=body.content_base64))


@router.get("/{invoice_id}/attachments/{attachment_id}")
def download_invoice_attachment(invoice_id: str, attachment_id: str, tenant: TenantContext = Depends(require_permission(VIEW))) -> Response:
    with get_connection() as connection:
        result = PurchaseInvoiceAttachmentService(connection).read(tenant_id=tenant.tenant_id, invoice_id=invoice_id, attachment_id=attachment_id)
        if isinstance(result, Err):
            _raise(result)
    return Response(result.value["content"], media_type=result.value["content_type"],
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(result.value['filename'])}"})


@router.delete("/{invoice_id}/attachments/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_invoice_attachment(invoice_id: str, attachment_id: str, tenant: TenantContext = Depends(require_permission(MANAGE))) -> Response:
    with get_connection() as connection:
        _commit(connection, PurchaseInvoiceAttachmentService(connection).delete(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, invoice_id=invoice_id, attachment_id=attachment_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---- credit notes --------------------------------------------------------------------------------

def _note(connection, result) -> dict[str, Any]:
    return _commit(connection, result)


@credit_note_router.get("")
def list_credit_notes(invoice_id: str | None = None, tenant: TenantContext = Depends(require_permission(VIEW))) -> list[dict]:
    with get_connection() as connection:
        return PurchaseCreditNoteService(connection).list_credit_notes(tenant_id=tenant.tenant_id, invoice_id=invoice_id)


@credit_note_router.get("/{note_id}")
def get_credit_note(note_id: str, tenant: TenantContext = Depends(require_permission(VIEW))) -> dict:
    with get_connection() as connection:
        result = PurchaseCreditNoteService(connection).get_credit_note(tenant_id=tenant.tenant_id, note_id=note_id)
        if isinstance(result, Err):
            _raise(result)
        return result.value


@credit_note_router.post("", status_code=status.HTTP_201_CREATED)
def create_credit_note(body: CreateCreditNoteRequest, tenant: TenantContext = Depends(require_permission(MANAGE))) -> dict:
    with get_connection() as connection:
        return _note(connection, PurchaseCreditNoteService(connection).create_draft(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, invoice_id=body.invoice_id, note_date=body.note_date,
            reason=body.reason, lines=[line.model_dump() for line in body.lines]))


@credit_note_router.patch("/{note_id}")
def update_credit_note(note_id: str, body: UpdateCreditNoteRequest, tenant: TenantContext = Depends(require_permission(MANAGE))) -> dict:
    changes = body.model_dump(exclude_unset=True)
    if changes.get("lines") is not None:
        changes["lines"] = [dict(line) for line in changes["lines"]]
    with get_connection() as connection:
        return _note(connection, PurchaseCreditNoteService(connection).update_draft(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, note_id=note_id, changes=changes))


@credit_note_router.post("/{note_id}/validate")
def validate_credit_note(note_id: str, tenant: TenantContext = Depends(require_permission(MANAGE))) -> dict:
    with get_connection() as connection:
        return _note(connection, PurchaseCreditNoteService(connection).validate(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, note_id=note_id, correlation_id=str(uuid4())))


@credit_note_router.post("/{note_id}/cancel")
def cancel_credit_note(note_id: str, tenant: TenantContext = Depends(require_permission(MANAGE))) -> dict:
    with get_connection() as connection:
        return _note(connection, PurchaseCreditNoteService(connection).cancel(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, note_id=note_id))
