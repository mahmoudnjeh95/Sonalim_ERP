from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from core.db import get_connection
from core.domain.result import Err, err_detail
from core.tenancy import TenantContext, require_permission
from modules.finance.api.service import InvoiceService
from modules.finance.domain.entities import check_new_invoice_currency

router = APIRouter(prefix="/finance", tags=["finance"])


class CreateInvoiceRequest(BaseModel):
    partner_id: str
    amount: float
    currency: str = "XOF"


class TransitionRequest(BaseModel):
    correlation_id: str


class UpdateInvoiceRequest(BaseModel):
    partner_id: str | None = None
    amount: float | None = None
    currency: str | None = None


def _invoice_response(invoice) -> dict:
    return {
        "id": invoice.id,
        "partner_id": invoice.partner_id,
        "amount": invoice.amount,
        "currency": invoice.currency,
        "status": invoice.status,
        "amount_paid": invoice.amount_paid,
    }


@router.get("/invoices")
def list_invoices(
    status_filter: str | None = Query(default=None, alias="status"),
    tenant: TenantContext = Depends(require_permission("finance.view_invoices")),
) -> list[dict]:
    with get_connection() as connection:
        service = InvoiceService(connection)
        invoices = service.list_invoices(tenant.tenant_id, status=status_filter)
    return [_invoice_response(invoice) for invoice in invoices]


@router.post("/invoices", status_code=status.HTTP_201_CREATED)
def create_invoice(
    body: CreateInvoiceRequest, tenant: TenantContext = Depends(require_permission("finance.manage_invoices"))
) -> dict:
    currency_checked = check_new_invoice_currency(body.currency)
    if isinstance(currency_checked, Err):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, err_detail(currency_checked))
    with get_connection() as connection:
        service = InvoiceService(connection)
        invoice = service.create_draft_invoice(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            partner_id=body.partner_id,
            amount=body.amount,
            currency=body.currency,
        )
        connection.commit()
    return _invoice_response(invoice)


@router.patch("/invoices/{invoice_id}")
def update_invoice(
    invoice_id: str,
    body: UpdateInvoiceRequest,
    tenant: TenantContext = Depends(require_permission("finance.admin_invoices")),
) -> dict:
    with get_connection() as connection:
        service = InvoiceService(connection)
        result = service.admin_update_invoice(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            invoice_id=invoice_id,
            partner_id=body.partner_id,
            amount=body.amount,
            currency=body.currency,
        )
        if isinstance(result, Err):
            connection.rollback()
            code = status.HTTP_404_NOT_FOUND if result.code == "NOT_FOUND" else status.HTTP_400_BAD_REQUEST
            raise HTTPException(code, err_detail(result))
        connection.commit()
    return _invoice_response(result.value)


def _transition_response(connection, result) -> dict:
    if isinstance(result, Err):
        connection.rollback()
        code = status.HTTP_404_NOT_FOUND if result.code == "NOT_FOUND" else status.HTTP_409_CONFLICT
        raise HTTPException(code, err_detail(result))
    connection.commit()
    return _invoice_response(result.value)


@router.post("/invoices/{invoice_id}/issue")
def issue_invoice(
    invoice_id: str,
    body: TransitionRequest,
    tenant: TenantContext = Depends(require_permission("finance.manage_invoices")),
) -> dict:
    with get_connection() as connection:
        service = InvoiceService(connection)
        result = service.issue_invoice(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, invoice_id=invoice_id, correlation_id=body.correlation_id
        )
        return _transition_response(connection, result)


@router.post("/invoices/{invoice_id}/pay")
def pay_invoice(
    invoice_id: str,
    body: TransitionRequest,
    tenant: TenantContext = Depends(require_permission("finance.manage_invoices")),
) -> dict:
    with get_connection() as connection:
        service = InvoiceService(connection)
        result = service.mark_paid(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, invoice_id=invoice_id, correlation_id=body.correlation_id
        )
        return _transition_response(connection, result)
