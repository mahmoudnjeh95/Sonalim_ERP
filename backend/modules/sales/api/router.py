from __future__ import annotations

import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from core.db import get_connection
from core.domain.money import json_number
from core.domain.result import Err, err_detail
from core.tenancy import TenantContext, require_permission, user_has_permission
from modules.sales.api.pricing_service import PricingService
from modules.sales.api.quote_router import pricing_router, quote_router
from modules.sales.api.service import SalesOrderService
from modules.sales.domain.entities import OrderLine

router = APIRouter(prefix="/sales", tags=["sales"])
router.include_router(quote_router)
router.include_router(pricing_router)


class OrderLineRequest(BaseModel):
    product_id: str
    quantity: Decimal
    unit_price: Decimal
    discount_rate: Decimal = Decimal("0")
    # left out: the tenant's default VAT rate (sales settings)
    vat_rate: Decimal | None = None
    price_list_id: str | None = None


class CreateOrderRequest(BaseModel):
    partner_id: str
    location_id: str
    lines: list[OrderLineRequest]
    requested_ship_date: datetime.date | None = None
    discount_rate: Decimal = Decimal("0")


class ConfirmOrderRequest(BaseModel):
    correlation_id: str
    # Confirm despite the credit rules; honoured only for holders of finance.admin_credit_override.
    override_credit: bool = False


class UpdateOrderRequest(BaseModel):
    partner_id: str | None = None
    location_id: str | None = None
    lines: list[OrderLineRequest] | None = None
    requested_ship_date: datetime.date | None = None
    discount_rate: Decimal | None = None


def _serialize_order(order) -> dict:
    totals = order.totals
    return {
        "id": order.id,
        "partner_id": order.partner_id,
        "location_id": order.location_id,
        "status": order.status,
        # JSON numbers, as before money became Decimal
        "total_amount": json_number(order.total_amount),
        "totals": {key: json_number(value) for key, value in totals.as_dict().items()},
        "discount_rate": json_number(order.discount_rate),
        "quote_id": order.quote_id,
        "requested_ship_date": order.requested_ship_date.isoformat() if order.requested_ship_date else None,
        "opportunity_id": order.opportunity_id,
        "lines": [
            {"product_id": line.product_id, "quantity": json_number(line.quantity), "unit_price": json_number(line.unit_price),
             "discount_rate": json_number(line.discount_rate), "vat_rate": json_number(line.vat_rate),
             "price_list_id": line.price_list_id}
            for line in order.lines
        ],
    }


def _lines(connection, tenant_id: str, requested: list[OrderLineRequest]) -> list[OrderLine]:
    default_vat = PricingService(connection).get_settings(tenant_id=tenant_id)["default_vat_rate"]
    return [
        OrderLine(product_id=line.product_id, quantity=line.quantity, unit_price=line.unit_price, discount_rate=line.discount_rate,
                  vat_rate=line.vat_rate if line.vat_rate is not None else default_vat, price_list_id=line.price_list_id)
        for line in requested
    ]


def _check_pricing(connection, tenant: TenantContext, lines: list[OrderLine], discount_rate: Decimal) -> None:
    checked = SalesOrderService(connection).check_pricing(
        tenant_id=tenant.tenant_id, lines=lines, discount_rate=discount_rate,
        may_exceed_discount=user_has_permission(connection, user_id=tenant.user_id, permission="sales.admin_discounts"),
    )
    if isinstance(checked, Err):
        code = status.HTTP_403_FORBIDDEN if checked.code == "DISCOUNT_ABOVE_LIMIT" else status.HTTP_400_BAD_REQUEST
        raise HTTPException(code, err_detail(checked))


@router.get("/orders")
def list_orders(
    status_filter: str | None = Query(default=None, alias="status"),
    tenant: TenantContext = Depends(require_permission("sales.view_orders")),
) -> list[dict]:
    with get_connection() as connection:
        service = SalesOrderService(connection)
        orders = service.list_orders(tenant.tenant_id, status=status_filter)
    return [_serialize_order(order) for order in orders]


@router.post("/orders", status_code=status.HTTP_201_CREATED)
def create_order(
    body: CreateOrderRequest, tenant: TenantContext = Depends(require_permission("sales.manage_orders"))
) -> dict:
    with get_connection() as connection:
        lines = _lines(connection, tenant.tenant_id, body.lines)
        _check_pricing(connection, tenant, lines, body.discount_rate)
        service = SalesOrderService(connection)
        order = service.create_order(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            partner_id=body.partner_id,
            location_id=body.location_id,
            lines=lines,
            requested_ship_date=body.requested_ship_date,
            discount_rate=body.discount_rate,
        )
        connection.commit()
    return _serialize_order(order)


@router.patch("/orders/{order_id}")
def update_order(
    order_id: str,
    body: UpdateOrderRequest,
    tenant: TenantContext = Depends(require_permission("sales.admin_orders")),
) -> dict:
    with get_connection() as connection:
        lines = _lines(connection, tenant.tenant_id, body.lines) if body.lines is not None else None
        service = SalesOrderService(connection)
        current = service.get_order(tenant_id=tenant.tenant_id, order_id=order_id)
        if isinstance(current, Err):
            raise HTTPException(status.HTTP_404_NOT_FOUND, err_detail(current))
        _check_pricing(connection, tenant, lines if lines is not None else list(current.value.lines),
                       body.discount_rate if body.discount_rate is not None else current.value.discount_rate)
        result = service.admin_update_order(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            order_id=order_id,
            partner_id=body.partner_id,
            location_id=body.location_id,
            lines=lines,
            requested_ship_date=body.requested_ship_date,
            discount_rate=body.discount_rate,
        )
        if isinstance(result, Err):
            connection.rollback()
            code = status.HTTP_404_NOT_FOUND if result.code == "NOT_FOUND" else status.HTTP_400_BAD_REQUEST
            raise HTTPException(code, err_detail(result))
        connection.commit()
    return _serialize_order(result.value)


@router.post("/orders/{order_id}/confirm")
def confirm_order(
    order_id: str,
    body: ConfirmOrderRequest,
    tenant: TenantContext = Depends(require_permission("sales.manage_orders")),
) -> dict:
    with get_connection() as connection:
        service = SalesOrderService(connection)
        override = body.override_credit and user_has_permission(
            connection, user_id=tenant.user_id, permission="finance.admin_credit_override")
        result = service.confirm_order(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, order_id=order_id, correlation_id=body.correlation_id,
            override_credit=override,
        )
        if isinstance(result, Err):
            connection.rollback()
            code = status.HTTP_404_NOT_FOUND if result.code == "NOT_FOUND" else status.HTTP_409_CONFLICT
            raise HTTPException(code, err_detail(result))
        connection.commit()
    return _serialize_order(result.value)
