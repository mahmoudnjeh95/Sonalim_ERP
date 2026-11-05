from __future__ import annotations

import datetime
import base64
import binascii
from decimal import Decimal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel

from core.db import get_connection
from core.api.service import CoreService
from core.domain.result import Err, err_detail
from core.tabular_export import tabular_response
from core.tenancy import TenantContext, require_permission, require_session
from modules.warehouse.api.attachment_service import AttachmentService
from modules.warehouse.api.movements_report_service import MovementsReportService
from modules.warehouse.api.valuation_service import ValuationService
from modules.warehouse.api.voucher_service import VoucherService

# Vouchers and valuation reports. Mounted on the warehouse router (prefix /warehouse).
router = APIRouter(tags=["warehouse"])

_CONFLICT = {"VOUCHER_NOT_DRAFT", "LOCATION_FROZEN", "ORDER_IN_FULFILLMENT", "ORDER_NOT_CONFIRMED", "STOCK_INSUFFICIENT",
             "ORDER_QTY_EXCEEDED", "RETURN_QTY_EXCEEDED", "DELIVERY_QTY_EXCEEDED", "NOTHING_TO_DELIVER", "RECEIPT_NOT_CONFIRMED"}


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
    document_date: datetime.date | None = None
    lines: list[VoucherLineRequest]


class VoucherUpdateRequest(BaseModel):
    source_location_id: str | None = None
    dest_location_id: str | None = None
    partner_id: str | None = None
    note: str | None = None
    document_date: datetime.date | None = None
    lines: list[VoucherLineRequest] | None = None


class IssueFromOrderRequest(BaseModel):
    source_location_id: str
    quantities: dict[str, Decimal] | None = None


class DeliveryNoteRequest(BaseModel):
    quantities: dict[str, Decimal] | None = None


class ValuationMethodRequest(BaseModel):
    method: str


class AttachmentRequest(BaseModel):
    filename: str
    content_type: str = "application/octet-stream"
    content_base64: str


# ---- vouchers ----------------------------------------------------------------------------------
@router.get("/vouchers")
def list_vouchers(type: str | None = None, status_filter: str | None = None, ref_type: str | None = None, ref_id: str | None = None,
                  tenant: TenantContext = Depends(require_permission("warehouse.view_moves"))) -> list[dict]:
    with get_connection() as connection:
        return VoucherService(connection).list(tenant_id=tenant.tenant_id, type=type, status=status_filter, ref_type=ref_type, ref_id=ref_id)


@router.get("/vouchers/purchase-receipts")
def list_unvouchered_purchase_receipts(tenant: TenantContext = Depends(require_permission("warehouse.manage_vouchers"))) -> list[dict]:
    with get_connection() as connection:
        return VoucherService(connection).list_unvouchered_purchase_receipts(tenant_id=tenant.tenant_id)


@router.post("/vouchers/from-purchase-receipt/{receipt_id}", status_code=status.HTTP_201_CREATED)
def create_receipt_from_purchase_receipt(receipt_id: str, tenant: TenantContext = Depends(require_permission("warehouse.manage_vouchers"))) -> dict:
    with get_connection() as connection:
        return _unwrap(connection, VoucherService(connection).create_receipt_from_purchase_receipt(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, receipt_id=receipt_id, correlation_id=str(uuid4())))


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


@router.post("/vouchers/{voucher_id}/delivery-note", status_code=status.HTTP_201_CREATED)
def generate_delivery_note(voucher_id: str, body: DeliveryNoteRequest,
                           tenant: TenantContext = Depends(require_permission("warehouse.post_vouchers"))) -> dict:
    with get_connection() as connection:
        return _unwrap(connection, VoucherService(connection).generate_delivery_note(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, voucher_id=voucher_id, correlation_id=str(uuid4()), quantities=body.quantities))


@router.post("/vouchers/{voucher_id}/cancel")
def cancel_voucher(voucher_id: str, tenant: TenantContext = Depends(require_permission("warehouse.post_vouchers"))) -> dict:
    with get_connection() as connection:
        return _unwrap(connection, VoucherService(connection).cancel(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, voucher_id=voucher_id))


# ---- attached files ----------------------------------------------------------------------------
# On a voucher they follow warehouse.view_moves / manage_vouchers, on a count view / manage_cycle_counts.
_ATTACHMENT_VIEW = {"voucher": "warehouse.view_moves", "cycle_count": "warehouse.view_cycle_counts"}
_ATTACHMENT_MANAGE = {"voucher": "warehouse.manage_vouchers", "cycle_count": "warehouse.manage_cycle_counts"}


def _attachment_permission(table: dict[str, str]):
    def check(entity_type: str, tenant: TenantContext = Depends(require_session)) -> TenantContext:
        if entity_type not in table:
            raise HTTPException(status.HTTP_404_NOT_FOUND, err_detail(Err("NOT_FOUND", "unknown document type", "type de document inconnu")))
        return require_permission(table[entity_type])(tenant)

    return check


@router.get("/attachments/{entity_type}/{entity_id}")
def list_attachments(entity_type: str, entity_id: str, tenant: TenantContext = Depends(_attachment_permission(_ATTACHMENT_VIEW))) -> list[dict]:
    with get_connection() as connection:
        return AttachmentService(connection).list(tenant_id=tenant.tenant_id, entity_type=entity_type, entity_id=entity_id)


@router.post("/attachments/{entity_type}/{entity_id}", status_code=status.HTTP_201_CREATED)
def add_attachment(entity_type: str, entity_id: str, body: AttachmentRequest,
                   tenant: TenantContext = Depends(_attachment_permission(_ATTACHMENT_MANAGE))) -> dict:
    try:
        content = base64.b64decode(body.content_base64, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, err_detail(Err("INVALID_FILE", "the file could not be read", "le fichier n'a pas pu être lu")))
    with get_connection() as connection:
        return _unwrap(connection, AttachmentService(connection).add(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, entity_type=entity_type, entity_id=entity_id,
            filename=body.filename, content_type=body.content_type, content=content))


@router.get("/attachments/{entity_type}/{entity_id}/{attachment_id}")
def download_attachment(entity_type: str, entity_id: str, attachment_id: str,
                        tenant: TenantContext = Depends(_attachment_permission(_ATTACHMENT_VIEW))):
    with get_connection() as connection:
        result = AttachmentService(connection).get(tenant_id=tenant.tenant_id, entity_type=entity_type, entity_id=entity_id, attachment_id=attachment_id)
    if isinstance(result, Err):
        raise HTTPException(_err_status(result.code), err_detail(result))
    filename = result.value["filename"].replace('"', "")
    return Response(result.value["content"], media_type="application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.delete("/attachments/{entity_type}/{entity_id}/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_attachment(entity_type: str, entity_id: str, attachment_id: str,
                      tenant: TenantContext = Depends(_attachment_permission(_ATTACHMENT_MANAGE))) -> Response:
    with get_connection() as connection:
        _unwrap(connection, AttachmentService(connection).delete(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, entity_type=entity_type, entity_id=entity_id, attachment_id=attachment_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---- valuation method --------------------------------------------------------------------------
@router.get("/settings/valuation-method")
def get_valuation_method(tenant: TenantContext = Depends(require_permission("warehouse.view_valuation"))) -> dict:
    with get_connection() as connection:
        return {"method": ValuationService(connection).valuation_method(tenant_id=tenant.tenant_id)}


@router.put("/settings/valuation-method")
def set_valuation_method(body: ValuationMethodRequest, tenant: TenantContext = Depends(require_permission("warehouse.admin_stock"))) -> dict:
    with get_connection() as connection:
        method = _unwrap(connection, ValuationService(connection).set_valuation_method(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, method=body.method))
    return {"method": method}


# ---- valuation and movements report ------------------------------------------------------------
@router.get("/reports/valued-stock")
def valued_stock(format: str | None = None,
                 tenant: TenantContext = Depends(require_permission("warehouse.view_valuation"))):
    """The valuation (plant-wide, not per location) with product names, optionally as CSV/XLSX."""
    with get_connection() as connection:
        valuations = ValuationService(connection).get_valuation(tenant_id=tenant.tenant_id)
        products = {p.id: p for p in CoreService(connection).list_products(tenant.tenant_id)}
    items = []
    for v in valuations:
        product = products.get(v.product_id)
        items.append({
            "product_id": v.product_id, "sku": product.sku if product else "", "name": product.name if product else v.product_id,
            "quantity": v.quantity, "avg_cost": v.average_unit_cost, "value": v.value, "unvalued_quantity": v.unvalued_quantity,
            "last_received_at": v.last_received_at,
        })
    items.sort(key=lambda i: i["name"])
    if format in ("csv", "xlsx"):
        rows = [[i["sku"], i["name"], i["last_received_at"].date().isoformat() if i["last_received_at"] else "", i["quantity"], i["avg_cost"],
                 i["value"], i["unvalued_quantity"]] for i in items]
        return tabular_response(["sku", "name", "last_received", "quantity", "avg_cost", "value", "unvalued_quantity"], rows, format, "valued-stock")
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
