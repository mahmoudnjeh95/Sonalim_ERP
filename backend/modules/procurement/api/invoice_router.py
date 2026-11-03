from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from core.db import get_connection
from core.domain.result import Err, err_detail
from core.tenancy import TenantContext, require_permission
from modules.procurement.api.invoice_service import PurchaseInvoiceService

router = APIRouter(prefix="/purchase-invoices", tags=["procurement"])


class InvoiceLine(BaseModel):
    description: str
    quantity: Decimal
    unit_price: Decimal


class CreatePurchaseInvoiceRequest(BaseModel):
    partner_id: str
    supplier_invoice_number: str
    invoice_date: datetime.date
    amount: Decimal
    currency: str = "XOF"
    due_date: datetime.date | None = None
    purchase_order_id: str | None = None
    note: str | None = None
    lines: list[InvoiceLine] = []


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


def _err_status(code: str) -> int:
    if code == "NOT_FOUND":
        return status.HTTP_404_NOT_FOUND
    if code in ("INVALID_TRANSITION", "INVOICE_NOT_DRAFT", "INVOICE_HAS_PAYMENTS", "DUPLICATE_SUPPLIER_INVOICE"):
        return status.HTTP_409_CONFLICT
    return status.HTTP_400_BAD_REQUEST


def _with_lines(service: PurchaseInvoiceService, tenant_id: str, invoice: dict[str, Any]) -> dict[str, Any]:
    return {**invoice, "lines": service.list_lines(tenant_id=tenant_id, invoice_id=invoice["id"])}


def _finish(connection, result, service: PurchaseInvoiceService, tenant_id: str, *, created: bool = False) -> dict[str, Any]:
    if isinstance(result, Err):
        connection.rollback()
        raise HTTPException(_err_status(result.code), err_detail(result))
    connection.commit()
    return _with_lines(service, tenant_id, result.value)


@router.get("")
def list_purchase_invoices(
    status_filter: str | None = None,
    partner_id: str | None = None,
    overdue: bool = False,
    tenant: TenantContext = Depends(require_permission("procurement.view_purchase_invoices")),
) -> list[dict]:
    with get_connection() as connection:
        return PurchaseInvoiceService(connection).list_invoices(
            tenant_id=tenant.tenant_id, status=status_filter, partner_id=partner_id, overdue=overdue
        )


@router.get("/{invoice_id}")
def get_purchase_invoice(
    invoice_id: str, tenant: TenantContext = Depends(require_permission("procurement.view_purchase_invoices"))
) -> dict:
    with get_connection() as connection:
        service = PurchaseInvoiceService(connection)
        result = service.get_invoice(tenant_id=tenant.tenant_id, invoice_id=invoice_id)
        if isinstance(result, Err):
            raise HTTPException(_err_status(result.code), err_detail(result))
        return _with_lines(service, tenant.tenant_id, result.value)


@router.post("", status_code=status.HTTP_201_CREATED)
def create_purchase_invoice(
    body: CreatePurchaseInvoiceRequest,
    tenant: TenantContext = Depends(require_permission("procurement.manage_purchase_invoices")),
) -> dict:
    with get_connection() as connection:
        service = PurchaseInvoiceService(connection)
        result = service.create_draft(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, partner_id=body.partner_id,
            supplier_invoice_number=body.supplier_invoice_number, invoice_date=body.invoice_date,
            amount=body.amount, currency=body.currency, due_date=body.due_date,
            purchase_order_id=body.purchase_order_id, note=body.note,
            lines=[line.model_dump() for line in body.lines],
        )
        return _finish(connection, result, service, tenant.tenant_id)


@router.patch("/{invoice_id}")
def update_purchase_invoice(
    invoice_id: str,
    body: UpdatePurchaseInvoiceRequest,
    tenant: TenantContext = Depends(require_permission("procurement.manage_purchase_invoices")),
) -> dict:
    changes = body.model_dump(exclude_unset=True)
    if "lines" in changes and changes["lines"] is not None:
        changes["lines"] = [dict(line) for line in changes["lines"]]
    with get_connection() as connection:
        service = PurchaseInvoiceService(connection)
        result = service.update_draft(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, invoice_id=invoice_id, changes=changes)
        return _finish(connection, result, service, tenant.tenant_id)


@router.post("/{invoice_id}/validate")
def validate_purchase_invoice(
    invoice_id: str, tenant: TenantContext = Depends(require_permission("procurement.manage_purchase_invoices"))
) -> dict:
    with get_connection() as connection:
        service = PurchaseInvoiceService(connection)
        result = service.validate(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, invoice_id=invoice_id, correlation_id=str(uuid4())
        )
        return _finish(connection, result, service, tenant.tenant_id)


@router.post("/{invoice_id}/cancel")
def cancel_purchase_invoice(
    invoice_id: str, tenant: TenantContext = Depends(require_permission("procurement.manage_purchase_invoices"))
) -> dict:
    with get_connection() as connection:
        service = PurchaseInvoiceService(connection)
        result = service.cancel(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, invoice_id=invoice_id)
        return _finish(connection, result, service, tenant.tenant_id)
