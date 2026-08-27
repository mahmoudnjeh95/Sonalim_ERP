from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from core.db import get_connection
from core.domain.result import Err
from core.tenancy import TenantContext, require_permission
from modules.sales.api.service import SalesOrderService
from modules.sales.domain.entities import OrderLine

router = APIRouter(prefix="/sales", tags=["sales"])


class OrderLineRequest(BaseModel):
    product_id: str
    quantity: float
    unit_price: float


class CreateOrderRequest(BaseModel):
    partner_id: str
    location_id: str
    lines: list[OrderLineRequest]


class ConfirmOrderRequest(BaseModel):
    correlation_id: str


class UpdateOrderRequest(BaseModel):
    partner_id: str | None = None
    location_id: str | None = None
    lines: list[OrderLineRequest] | None = None


def _serialize_order(order) -> dict:
    return {
        "id": order.id,
        "partner_id": order.partner_id,
        "location_id": order.location_id,
        "status": order.status,
        "total_amount": order.total_amount,
        "lines": [
            {"product_id": line.product_id, "quantity": line.quantity, "unit_price": line.unit_price}
            for line in order.lines
        ],
    }


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
    lines = [OrderLine(product_id=line.product_id, quantity=line.quantity, unit_price=line.unit_price) for line in body.lines]
    with get_connection() as connection:
        service = SalesOrderService(connection)
        order = service.create_order(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            partner_id=body.partner_id,
            location_id=body.location_id,
            lines=lines,
        )
        connection.commit()
    return _serialize_order(order)


@router.patch("/orders/{order_id}")
def update_order(
    order_id: str,
    body: UpdateOrderRequest,
    tenant: TenantContext = Depends(require_permission("sales.admin_orders")),
) -> dict:
    lines = (
        [OrderLine(product_id=line.product_id, quantity=line.quantity, unit_price=line.unit_price) for line in body.lines]
        if body.lines is not None
        else None
    )
    with get_connection() as connection:
        service = SalesOrderService(connection)
        result = service.admin_update_order(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            order_id=order_id,
            partner_id=body.partner_id,
            location_id=body.location_id,
            lines=lines,
        )
        if isinstance(result, Err):
            connection.rollback()
            code = status.HTTP_404_NOT_FOUND if result.code == "NOT_FOUND" else status.HTTP_400_BAD_REQUEST
            raise HTTPException(code, {"code": result.code, "message": result.message})
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
        result = service.confirm_order(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, order_id=order_id, correlation_id=body.correlation_id
        )
        if isinstance(result, Err):
            connection.rollback()
            code = status.HTTP_404_NOT_FOUND if result.code == "NOT_FOUND" else status.HTTP_409_CONFLICT
            raise HTTPException(code, {"code": result.code, "message": result.message})
        connection.commit()
    return _serialize_order(result.value)
