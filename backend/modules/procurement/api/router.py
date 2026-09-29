from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from core.db import get_connection
from core.domain.result import Err, err_detail
from core.tenancy import TenantContext, require_permission
from modules.procurement.api.service import PurchaseOrderService
from modules.procurement.domain.entities import (
    PURCHASE_ORDER_MANUAL_TRANSITIONS,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderReceipt,
    PurchaseOrderReceiptLine,
)

router = APIRouter(prefix="/procurement", tags=["procurement"])

RECEIVING_STATUSES = {"partially_received", "fully_received"}
ALL_PURCHASE_ORDER_STATUSES = sorted(set(PURCHASE_ORDER_MANUAL_TRANSITIONS.keys()) | RECEIVING_STATUSES)


class PurchaseOrderLineRequest(BaseModel):
    product_id: str
    uom_id: str
    quantity_ordered: float
    unit_price: float = 0
    unit_price_currency: str = "XOF"


class CreatePurchaseOrderRequest(BaseModel):
    lines: list[PurchaseOrderLineRequest]
    supplier_id: str | None = None
    currency_code: str | None = None
    order_date: datetime.date | None = None
    expected_date: datetime.date | None = None
    notes: str | None = None
    is_import: bool = False


class AddPurchaseOrderLineRequest(BaseModel):
    product_id: str
    uom_id: str
    quantity_ordered: float
    unit_price: float = 0
    unit_price_currency: str = "XOF"


class UpdatePurchaseOrderRequest(BaseModel):
    supplier_id: str | None = None
    order_date: datetime.date | None = None
    expected_date: datetime.date | None = None
    currency_code: str | None = None
    notes: str | None = None
    is_import: bool | None = None


class ReceiptLineRequest(BaseModel):
    purchase_order_line_id: str
    quantity: float
    lot_number: str | None = None


class CreateReceiptRequest(BaseModel):
    location_id: str
    currency_code: str
    lines: list[ReceiptLineRequest]
    invoice_number: str | None = None
    invoice_date: datetime.date | None = None
    origin_country: str | None = None
    carrier: str | None = None
    transport_company_name: str | None = None
    driver_name: str | None = None
    base_cost: float = 0
    license_fee: float = 0
    insurance_fee: float = 0
    transit_fee: float = 0
    transport_fee: float = 0
    customs_duty: float = 0
    handling_fee: float = 0


class ConfirmReceiptRequest(BaseModel):
    correlation_id: str


def _order_response(order: PurchaseOrder) -> dict:
    return {
        "id": order.id,
        "supplier_id": order.supplier_id,
        "status": order.status,
        "order_date": order.order_date,
        "expected_date": order.expected_date,
        "currency_code": order.currency_code,
        "notes": order.notes,
        "is_import": order.is_import,
    }


def _line_response(line: PurchaseOrderLine) -> dict:
    return {
        "id": line.id,
        "purchase_order_id": line.purchase_order_id,
        "product_id": line.product_id,
        "uom_id": line.uom_id,
        "quantity_ordered": line.quantity_ordered,
        "quantity_received": line.quantity_received,
        "status": line.status,
        "unit_price": line.unit_price,
        "unit_price_currency": line.unit_price_currency,
    }


def _receipt_response(receipt: PurchaseOrderReceipt) -> dict:
    return {
        "id": receipt.id,
        "purchase_order_id": receipt.purchase_order_id,
        "location_id": receipt.location_id,
        "status": receipt.status,
        "currency_code": receipt.currency_code,
        "invoice_number": receipt.invoice_number,
        "invoice_date": receipt.invoice_date,
        "origin_country": receipt.origin_country,
        "carrier": receipt.carrier,
        "transport_company_name": receipt.transport_company_name,
        "driver_name": receipt.driver_name,
        "base_cost": receipt.base_cost,
        "license_fee": receipt.license_fee,
        "insurance_fee": receipt.insurance_fee,
        "transit_fee": receipt.transit_fee,
        "transport_fee": receipt.transport_fee,
        "customs_duty": receipt.customs_duty,
        "handling_fee": receipt.handling_fee,
        "total_cost": receipt.total_cost,
        "confirmed_at": receipt.confirmed_at,
    }


def _receipt_line_response(line: PurchaseOrderReceiptLine) -> dict:
    return {
        "id": line.id,
        "purchase_order_receipt_id": line.purchase_order_receipt_id,
        "purchase_order_line_id": line.purchase_order_line_id,
        "quantity": line.quantity,
        "lot_number": line.lot_number,
        "cost_per_unit": line.cost_per_unit,
    }


def _err_status(code: str) -> int:
    if code == "NOT_FOUND":
        return status.HTTP_404_NOT_FOUND
    if code in ("INVALID_TRANSITION", "OVER_RECEIPT"):
        return status.HTTP_409_CONFLICT
    return status.HTTP_400_BAD_REQUEST


@router.get("/purchase-orders/statuses")
def list_purchase_order_statuses(
    tenant: TenantContext = Depends(require_permission("procurement.view_purchase_orders")),
) -> list[str]:
    return ALL_PURCHASE_ORDER_STATUSES


@router.post("/purchase-orders", status_code=status.HTTP_201_CREATED)
def create_purchase_order(
    body: CreatePurchaseOrderRequest, tenant: TenantContext = Depends(require_permission("procurement.manage_purchase_orders"))
) -> dict:
    with get_connection() as connection:
        service = PurchaseOrderService(connection)
        result = service.create_purchase_order(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            lines=[line.model_dump() for line in body.lines],
            supplier_id=body.supplier_id,
            currency_code=body.currency_code,
            order_date=body.order_date,
            expected_date=body.expected_date,
            notes=body.notes,
            is_import=body.is_import,
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_err_status(result.code), err_detail(result))
        connection.commit()
    return _order_response(result.value)


@router.get("/purchase-orders")
def list_purchase_orders(
    status_filter: str | None = None,
    supplier_id: str | None = None,
    tenant: TenantContext = Depends(require_permission("procurement.view_purchase_orders")),
) -> list[dict]:
    with get_connection() as connection:
        service = PurchaseOrderService(connection)
        orders = service.list_purchase_orders(tenant_id=tenant.tenant_id, status=status_filter, supplier_id=supplier_id)
    return [_order_response(order) for order in orders]


@router.get("/purchase-orders/{order_id}/lines")
def list_purchase_order_lines(
    order_id: str, tenant: TenantContext = Depends(require_permission("procurement.view_purchase_orders"))
) -> list[dict]:
    with get_connection() as connection:
        service = PurchaseOrderService(connection)
        lines = service.list_lines(tenant_id=tenant.tenant_id, purchase_order_id=order_id)
    return [_line_response(line) for line in lines]


@router.post("/purchase-orders/{order_id}/lines", status_code=status.HTTP_201_CREATED)
def add_purchase_order_line(
    order_id: str,
    body: AddPurchaseOrderLineRequest,
    tenant: TenantContext = Depends(require_permission("procurement.manage_purchase_orders")),
) -> dict:
    with get_connection() as connection:
        service = PurchaseOrderService(connection)
        result = service.add_line(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            purchase_order_id=order_id,
            product_id=body.product_id,
            uom_id=body.uom_id,
            quantity_ordered=body.quantity_ordered,
            unit_price=body.unit_price,
            unit_price_currency=body.unit_price_currency,
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_err_status(result.code), err_detail(result))
        connection.commit()
    return _line_response(result.value)


def _do_order_transition(service: PurchaseOrderService, connection, *, tenant_id: str, actor_id: str, order_id: str, method_name: str) -> dict:
    method = getattr(service, method_name)
    result = method(tenant_id=tenant_id, actor_id=actor_id, order_id=order_id)
    if isinstance(result, Err):
        connection.rollback()
        raise HTTPException(_err_status(result.code), err_detail(result))
    connection.commit()
    return _order_response(result.value)


@router.post("/purchase-orders/{order_id}/validate")
def validate_purchase_order(
    order_id: str, tenant: TenantContext = Depends(require_permission("procurement.manage_purchase_orders"))
) -> dict:
    with get_connection() as connection:
        service = PurchaseOrderService(connection)
        return _do_order_transition(service, connection, tenant_id=tenant.tenant_id, actor_id=tenant.user_id, order_id=order_id, method_name="validate_order")


@router.post("/purchase-orders/{order_id}/approve")
def approve_purchase_order(
    order_id: str, tenant: TenantContext = Depends(require_permission("procurement.manage_purchase_orders"))
) -> dict:
    with get_connection() as connection:
        service = PurchaseOrderService(connection)
        return _do_order_transition(service, connection, tenant_id=tenant.tenant_id, actor_id=tenant.user_id, order_id=order_id, method_name="approve_order")


@router.post("/purchase-orders/{order_id}/place-order")
def place_purchase_order(
    order_id: str, tenant: TenantContext = Depends(require_permission("procurement.manage_purchase_orders"))
) -> dict:
    with get_connection() as connection:
        service = PurchaseOrderService(connection)
        return _do_order_transition(service, connection, tenant_id=tenant.tenant_id, actor_id=tenant.user_id, order_id=order_id, method_name="place_order")


@router.post("/purchase-orders/{order_id}/refuse")
def refuse_purchase_order(
    order_id: str, tenant: TenantContext = Depends(require_permission("procurement.manage_purchase_orders"))
) -> dict:
    with get_connection() as connection:
        service = PurchaseOrderService(connection)
        return _do_order_transition(service, connection, tenant_id=tenant.tenant_id, actor_id=tenant.user_id, order_id=order_id, method_name="refuse_order")


@router.post("/purchase-orders/{order_id}/cancel")
def cancel_purchase_order(
    order_id: str, tenant: TenantContext = Depends(require_permission("procurement.manage_purchase_orders"))
) -> dict:
    with get_connection() as connection:
        service = PurchaseOrderService(connection)
        return _do_order_transition(service, connection, tenant_id=tenant.tenant_id, actor_id=tenant.user_id, order_id=order_id, method_name="cancel_order")


@router.patch("/purchase-orders/{order_id}")
def update_purchase_order(
    order_id: str,
    body: UpdatePurchaseOrderRequest,
    tenant: TenantContext = Depends(require_permission("procurement.admin_purchase_orders")),
) -> dict:
    with get_connection() as connection:
        service = PurchaseOrderService(connection)
        result = service.admin_update_purchase_order(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            order_id=order_id,
            supplier_id=body.supplier_id,
            order_date=body.order_date,
            expected_date=body.expected_date,
            currency_code=body.currency_code,
            notes=body.notes,
            is_import=body.is_import,
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_err_status(result.code), err_detail(result))
        connection.commit()
    return _order_response(result.value)


# --- Goods receipts -----------------------------------------------------------------------


@router.post("/purchase-orders/{order_id}/receipts", status_code=status.HTTP_201_CREATED)
def create_purchase_order_receipt(
    order_id: str,
    body: CreateReceiptRequest,
    tenant: TenantContext = Depends(require_permission("procurement.manage_purchase_orders")),
) -> dict:
    with get_connection() as connection:
        service = PurchaseOrderService(connection)
        result = service.create_receipt(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            purchase_order_id=order_id,
            location_id=body.location_id,
            currency_code=body.currency_code,
            lines=[line.model_dump() for line in body.lines],
            invoice_number=body.invoice_number,
            invoice_date=body.invoice_date,
            origin_country=body.origin_country,
            carrier=body.carrier,
            transport_company_name=body.transport_company_name,
            driver_name=body.driver_name,
            base_cost=body.base_cost,
            license_fee=body.license_fee,
            insurance_fee=body.insurance_fee,
            transit_fee=body.transit_fee,
            transport_fee=body.transport_fee,
            customs_duty=body.customs_duty,
            handling_fee=body.handling_fee,
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_err_status(result.code), err_detail(result))
        connection.commit()
    return _receipt_response(result.value)


@router.get("/purchase-orders/{order_id}/receipts")
def list_purchase_order_receipts(
    order_id: str, tenant: TenantContext = Depends(require_permission("procurement.view_purchase_orders"))
) -> list[dict]:
    with get_connection() as connection:
        service = PurchaseOrderService(connection)
        receipts = service.list_receipts(tenant_id=tenant.tenant_id, purchase_order_id=order_id)
    return [_receipt_response(receipt) for receipt in receipts]


@router.get("/receipts/{receipt_id}")
def get_purchase_order_receipt(
    receipt_id: str, tenant: TenantContext = Depends(require_permission("procurement.view_purchase_orders"))
) -> dict:
    with get_connection() as connection:
        service = PurchaseOrderService(connection)
        receipt = service.get_receipt(tenant_id=tenant.tenant_id, receipt_id=receipt_id)
        if receipt is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                {
                    "code": "NOT_FOUND",
                    "message": f"purchase order receipt {receipt_id} not found",
                    "message_fr": f"réception de commande d'achat {receipt_id} introuvable",
                },
            )
    return _receipt_response(receipt)


@router.get("/receipts/{receipt_id}/lines")
def list_purchase_order_receipt_lines(
    receipt_id: str, tenant: TenantContext = Depends(require_permission("procurement.view_purchase_orders"))
) -> list[dict]:
    with get_connection() as connection:
        service = PurchaseOrderService(connection)
        lines = service.list_receipt_lines(tenant_id=tenant.tenant_id, purchase_order_receipt_id=receipt_id)
    return [_receipt_line_response(line) for line in lines]


@router.post("/receipts/{receipt_id}/confirm")
def confirm_purchase_order_receipt_endpoint(
    receipt_id: str,
    body: ConfirmReceiptRequest,
    tenant: TenantContext = Depends(require_permission("procurement.manage_purchase_orders")),
) -> dict:
    with get_connection() as connection:
        service = PurchaseOrderService(connection)
        result = service.confirm_receipt(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, receipt_id=receipt_id, correlation_id=body.correlation_id
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_err_status(result.code), err_detail(result))
        connection.commit()
    return _order_response(result.value)


@router.get("/cost-summary")
def get_cost_summary(tenant: TenantContext = Depends(require_permission("procurement.view_purchase_orders"))) -> list[dict]:
    with get_connection() as connection:
        service = PurchaseOrderService(connection)
        return service.cost_summary(tenant_id=tenant.tenant_id)


@router.get("/last-prices")
def list_last_prices(
    supplier_id: str,
    product_ids: list[str] = Query(...),
    tenant: TenantContext = Depends(require_permission("procurement.view_purchase_orders")),
) -> list[dict]:
    with get_connection() as connection:
        service = PurchaseOrderService(connection)
        prices = service.list_last_prices(tenant_id=tenant.tenant_id, supplier_id=supplier_id, product_ids=product_ids)
    return [
        {
            "product_id": price.product_id,
            "unit_price": price.unit_price,
            "unit_price_currency": price.unit_price_currency,
            "order_date": price.order_date,
        }
        for price in prices
    ]


@router.get("/price-history")
def list_price_history(
    product_id: str,
    supplier_id: str | None = None,
    tenant: TenantContext = Depends(require_permission("procurement.view_purchase_orders")),
) -> list[dict]:
    """Every recorded purchase-order price for one product, oldest to newest,
    converted to CFA -- the price *trend*, unlike /last-prices' single latest figure."""
    with get_connection() as connection:
        service = PurchaseOrderService(connection)
        return service.list_price_history(tenant_id=tenant.tenant_id, product_id=product_id, supplier_id=supplier_id)


@router.get("/supplier-leaderboard")
def get_supplier_leaderboard(
    tenant: TenantContext = Depends(require_permission("procurement.view_purchase_orders")),
) -> list[dict]:
    """Ranks every supplier ever ordered from by how often they held the lowest
    recorded price across products -- the aggregate view behind price
    history's per-product best-supplier highlight."""
    with get_connection() as connection:
        service = PurchaseOrderService(connection)
        return service.list_supplier_leaderboard(tenant_id=tenant.tenant_id)


@router.get("/receipt-lines")
def list_confirmed_receipt_line_details(
    tenant: TenantContext = Depends(require_permission("procurement.view_purchase_orders")),
) -> list[dict]:
    with get_connection() as connection:
        service = PurchaseOrderService(connection)
        return service.list_confirmed_receipt_line_details(tenant_id=tenant.tenant_id)
