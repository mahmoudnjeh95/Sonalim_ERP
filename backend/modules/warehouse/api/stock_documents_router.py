from __future__ import annotations

import datetime
from decimal import Decimal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from core.db import get_connection
from core.api.service import CoreService
from core.domain.result import Err, err_detail
from core.tabular_export import tabular_response
from core.tenancy import TenantContext, require_permission
from modules.warehouse.api.movements_report_service import MovementsReportService
from modules.warehouse.api.valuation_service import ValuationService
from modules.warehouse.api.voucher_service import VoucherService

# Vouchers and valuation reports. Mounted on the warehouse router (prefix /warehouse).
router = APIRouter(tags=["warehouse"])

_CONFLICT = {"VOUCHER_NOT_DRAFT", "LOCATION_FROZEN", "STOCK_INSUFFICIENT",
             "ORDER_QTY_EXCEEDED", "RETURN_QTY_EXCEEDED"}


def _err_status(code: str) -> int:
    if code == "NOT_FOUND":
        return status.HTTP_404_NOT_FOUND
    return status.HTTP_409_CONFLICT if code in _CONFLICT else status.HTTP_400_BAD_REQUEST


def _unwrap(connection, result):
    if isinstance(result, Err):
        connection.rollback()
        raise HTTPException(_err_status(result.code), err_detail(result))
    connection.commit()
    return result.value


class VoucherLineRequest(BaseModel):
    product_id: str
    quantity: Decimal
    unit_cost: Decimal | None = None


class VoucherRequest(BaseModel):
    type: str
    source_location_id: str | None = None
    dest_location_id: str | None = None
    partner_id: str | None = None
    ref_type: str | None = None
    ref_id: str | None = None
    return_of_voucher_id: str | None = None
    note: str | None = None
    lines: list[VoucherLineRequest]


class VoucherUpdateRequest(BaseModel):
    source_location_id: str | None = None
    dest_location_id: str | None = None
    partner_id: str | None = None
    note: str | None = None
    lines: list[VoucherLineRequest] | None = None


class IssueFromOrderRequest(BaseModel):
    source_location_id: str
    quantities: dict[str, Decimal] | None = None


# ---- vouchers ----------------------------------------------------------------------------------
@router.get("/vouchers")
def list_vouchers(type: str | None = None, status_filter: str | None = None, ref_type: str | None = None, ref_id: str | None = None,
                  tenant: TenantContext = Depends(require_permission("warehouse.view_moves"))) -> list[dict]:
    with get_connection() as connection:
        return VoucherService(connection).list(tenant_id=tenant.tenant_id, type=type, status=status_filter, ref_type=ref_type, ref_id=ref_id)


@router.get("/vouchers/{voucher_id}")
def get_voucher(voucher_id: str, tenant: TenantContext = Depends(require_permission("warehouse.view_moves"))) -> dict:
    with get_connection() as connection:
        result = VoucherService(connection).get(tenant_id=tenant.tenant_id, voucher_id=voucher_id)
        if isinstance(result, Err):
            raise HTTPException(_err_status(result.code), err_detail(result))
        return result.value


@router.post("/vouchers", status_code=status.HTTP_201_CREATED)
def create_voucher(body: VoucherRequest, tenant: TenantContext = Depends(require_permission("warehouse.manage_vouchers"))) -> dict:
    data = body.model_dump()
    with get_connection() as connection:
        return _unwrap(connection, VoucherService(connection).create_draft(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, **data))


@router.post("/vouchers/from-order/{order_id}", status_code=status.HTTP_201_CREATED)
def create_issue_from_order(order_id: str, body: IssueFromOrderRequest,
                            tenant: TenantContext = Depends(require_permission("warehouse.manage_vouchers"))) -> dict:
    with get_connection() as connection:
        return _unwrap(connection, VoucherService(connection).create_issue_from_order(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, order_id=order_id,
            source_location_id=body.source_location_id, quantities=body.quantities))


@router.patch("/vouchers/{voucher_id}")
def update_voucher(voucher_id: str, body: VoucherUpdateRequest,
                   tenant: TenantContext = Depends(require_permission("warehouse.manage_vouchers"))) -> dict:
    changes = body.model_dump(exclude_unset=True)
    with get_connection() as connection:
        return _unwrap(connection, VoucherService(connection).update_draft(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, voucher_id=voucher_id, changes=changes))


@router.post("/vouchers/{voucher_id}/post")
def post_voucher(voucher_id: str, tenant: TenantContext = Depends(require_permission("warehouse.post_vouchers"))) -> dict:
    with get_connection() as connection:
        return _unwrap(connection, VoucherService(connection).post(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, voucher_id=voucher_id, correlation_id=str(uuid4())))


@router.post("/vouchers/{voucher_id}/cancel")
def cancel_voucher(voucher_id: str, tenant: TenantContext = Depends(require_permission("warehouse.post_vouchers"))) -> dict:
    with get_connection() as connection:
        return _unwrap(connection, VoucherService(connection).cancel(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, voucher_id=voucher_id))


# ---- valuation and movements report ------------------------------------------------------------
@router.get("/reports/valued-stock")
def valued_stock(format: str | None = None,
                 tenant: TenantContext = Depends(require_permission("warehouse.view_valuation"))):
    """The FIFO valuation (plant-wide, not per location) with product names, optionally as CSV/XLSX."""
    with get_connection() as connection:
        valuations = ValuationService(connection).get_valuation(tenant_id=tenant.tenant_id)
        products = {p.id: p for p in CoreService(connection).list_products(tenant.tenant_id)}
    items = []
    for v in valuations:
        product = products.get(v.product_id)
        items.append({
            "product_id": v.product_id, "sku": product.sku if product else "", "name": product.name if product else v.product_id,
            "quantity": v.quantity, "avg_cost": v.average_unit_cost, "value": v.value, "unvalued_quantity": v.unvalued_quantity,
        })
    items.sort(key=lambda i: i["name"])
    if format in ("csv", "xlsx"):
        rows = [[i["sku"], i["name"], i["quantity"], i["avg_cost"], i["value"], i["unvalued_quantity"]] for i in items]
        return tabular_response(["sku", "name", "quantity", "avg_cost", "value", "unvalued_quantity"], rows, format, "valued-stock")
    return {"items": items, "total_value": sum(i["value"] or 0 for i in items),
            "missing_cost_count": sum(1 for i in items if i["unvalued_quantity"]), "currency": "XOF"}


@router.get("/reports/movements")
def movements_report(product_id: str | None = None, location_id: str | None = None, move_type: str | None = None,
                     date_from: datetime.date | None = None, date_to: datetime.date | None = None, format: str | None = None,
                     tenant: TenantContext = Depends(require_permission("warehouse.view_moves"))):
    with get_connection() as connection:
        rows = MovementsReportService(connection).movements_report(
            tenant_id=tenant.tenant_id, product_id=product_id, location_id=location_id, move_type=move_type,
            date_from=date_from, date_to=date_to)
    if format in ("csv", "xlsx"):
        data = [[r["created_at"].isoformat(), r["move_type"], r["sku"], r["product"], r["location"], r["quantity"], r["unit_cost"],
                 r["reference"], r["voucher_number"]] for r in rows]
        return tabular_response(["date", "type", "sku", "product", "location", "quantity", "unit_cost", "reference", "voucher"],
                                data, format, "stock-movements")
    return rows
