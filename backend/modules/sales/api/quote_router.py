"""Quotes, price lists, customer pricing and sales settings over HTTP (mounted under /sales)."""
from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel

from core.db import get_connection
from core.domain.result import Err, err_detail
from core.tabular_export import tabular_response
from core.tenancy import TenantContext, require_permission, user_has_permission
from modules.sales.api.pricing_service import PricingService
from modules.sales.api.quote_service import QuoteService

VIEW_QUOTES = "sales.view_quotes"
MANAGE_QUOTES = "sales.manage_quotes"
MANAGE_PRICE_LISTS = "sales.manage_price_lists"
VIEW_ORDERS = "sales.view_orders"
ADMIN_DISCOUNTS = "sales.admin_discounts"
ADMIN_SETTINGS = "sales.admin_orders"

quote_router = APIRouter(prefix="/quotes", tags=["sales"])
pricing_router = APIRouter(tags=["sales"])

_CONFLICTS = {
    "INVALID_TRANSITION", "QUOTE_NOT_DRAFT", "QUOTE_EXPIRED", "QUOTE_NOT_REVISABLE", "QUOTE_ALREADY_ORDERED",
    "QUOTE_NOT_ACCEPTED", "PRICE_LIST_EXISTS", "IMPORT_HAS_ERRORS",
}


def _raise(result: Err) -> None:
    if result.code == "NOT_FOUND":
        code = status.HTTP_404_NOT_FOUND
    elif result.code in _CONFLICTS:
        code = status.HTTP_409_CONFLICT
    elif result.code == "DISCOUNT_ABOVE_LIMIT":
        code = status.HTTP_403_FORBIDDEN
    else:
        code = status.HTTP_400_BAD_REQUEST
    raise HTTPException(code, err_detail(result))


def _done(connection, result) -> Any:
    if isinstance(result, Err):
        connection.rollback()
        _raise(result)
    connection.commit()
    return result.value


# ---- quotes ---------------------------------------------------------------------------------------

class QuoteLineRequest(BaseModel):
    product_id: str
    quantity: Decimal
    # left out: the price comes from the customer's price list, the VAT rate from the settings
    unit_price: Decimal | None = None
    discount_rate: Decimal | None = None
    vat_rate: Decimal | None = None
    # a tax code gives the rate; left out with vat_rate: the customer's, then the product's code
    tax_code: str | None = None
    price_list_id: str | None = None


class CreateQuoteRequest(BaseModel):
    partner_id: str
    lines: list[QuoteLineRequest]
    quote_date: datetime.date | None = None
    valid_until: datetime.date | None = None
    discount_rate: Decimal | None = None
    opportunity_id: str | None = None
    location_id: str | None = None
    note: str | None = None


class UpdateQuoteRequest(BaseModel):
    lines: list[QuoteLineRequest] | None = None
    quote_date: datetime.date | None = None
    valid_until: datetime.date | None = None
    discount_rate: Decimal | None = None
    opportunity_id: str | None = None
    location_id: str | None = None
    note: str | None = None


class RefuseRequest(BaseModel):
    reason: str | None = None


class ConvertRequest(BaseModel):
    location_id: str | None = None
    requested_ship_date: datetime.date | None = None


@quote_router.get("")
def list_quotes(
    status_filter: str | None = Query(default=None, alias="status"),
    partner_id: str | None = None,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    tenant: TenantContext = Depends(require_permission(VIEW_QUOTES)),
) -> list[dict]:
    with get_connection() as connection:
        quotes = QuoteService(connection).list_quotes(tenant_id=tenant.tenant_id, status=status_filter, partner_id=partner_id,
                                                      date_from=date_from, date_to=date_to)
        connection.commit()  # expiry may have changed statuses
    return quotes


@quote_router.get("/stats")
def quote_stats(date_from: datetime.date | None = None, date_to: datetime.date | None = None,
                tenant: TenantContext = Depends(require_permission(VIEW_QUOTES))) -> dict:
    with get_connection() as connection:
        stats = QuoteService(connection).stats(tenant_id=tenant.tenant_id, date_from=date_from, date_to=date_to)
        connection.commit()
    return stats


@quote_router.get("/{quote_id}")
def get_quote(quote_id: str, tenant: TenantContext = Depends(require_permission(VIEW_QUOTES))) -> dict:
    with get_connection() as connection:
        return _done(connection, QuoteService(connection).get_quote(tenant_id=tenant.tenant_id, quote_id=quote_id))


@quote_router.post("", status_code=status.HTTP_201_CREATED)
def create_quote(body: CreateQuoteRequest, tenant: TenantContext = Depends(require_permission(MANAGE_QUOTES))) -> dict:
    with get_connection() as connection:
        may_exceed = user_has_permission(connection, user_id=tenant.user_id, permission=ADMIN_DISCOUNTS)
        result = QuoteService(connection).create_quote(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, partner_id=body.partner_id,
            lines=[line.model_dump() for line in body.lines], quote_date=body.quote_date, valid_until=body.valid_until,
            discount_rate=body.discount_rate, opportunity_id=body.opportunity_id, location_id=body.location_id, note=body.note,
            may_exceed_discount=may_exceed,
        )
        return _done(connection, result)


@quote_router.patch("/{quote_id}")
def update_quote(quote_id: str, body: UpdateQuoteRequest, tenant: TenantContext = Depends(require_permission(MANAGE_QUOTES))) -> dict:
    with get_connection() as connection:
        may_exceed = user_has_permission(connection, user_id=tenant.user_id, permission=ADMIN_DISCOUNTS)
        result = QuoteService(connection).update_quote(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, quote_id=quote_id,
            lines=[line.model_dump() for line in body.lines] if body.lines is not None else None,
            quote_date=body.quote_date, valid_until=body.valid_until, discount_rate=body.discount_rate,
            opportunity_id=body.opportunity_id, location_id=body.location_id, note=body.note, may_exceed_discount=may_exceed,
        )
        return _done(connection, result)


@quote_router.post("/{quote_id}/send")
def send_quote(quote_id: str, tenant: TenantContext = Depends(require_permission(MANAGE_QUOTES))) -> dict:
    with get_connection() as connection:
        return _done(connection, QuoteService(connection).send(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, quote_id=quote_id))


@quote_router.post("/{quote_id}/accept")
def accept_quote(quote_id: str, tenant: TenantContext = Depends(require_permission(MANAGE_QUOTES))) -> dict:
    with get_connection() as connection:
        return _done(connection, QuoteService(connection).accept(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, quote_id=quote_id))


@quote_router.post("/{quote_id}/refuse")
def refuse_quote(quote_id: str, body: RefuseRequest, tenant: TenantContext = Depends(require_permission(MANAGE_QUOTES))) -> dict:
    with get_connection() as connection:
        return _done(connection, QuoteService(connection).refuse(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, quote_id=quote_id,
                                                                 reason=body.reason))


@quote_router.post("/{quote_id}/revise", status_code=status.HTTP_201_CREATED)
def revise_quote(quote_id: str, tenant: TenantContext = Depends(require_permission(MANAGE_QUOTES))) -> dict:
    with get_connection() as connection:
        return _done(connection, QuoteService(connection).revise(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, quote_id=quote_id))


@quote_router.post("/{quote_id}/convert", status_code=status.HTTP_201_CREATED)
def convert_quote(quote_id: str, body: ConvertRequest, tenant: TenantContext = Depends(require_permission(MANAGE_QUOTES))) -> dict:
    with get_connection() as connection:
        if not user_has_permission(connection, user_id=tenant.user_id, permission="sales.manage_orders"):
            raise HTTPException(status.HTTP_403_FORBIDDEN, {"code": "FORBIDDEN", "message": "missing permission sales.manage_orders",
                                                            "message_fr": "permission sales.manage_orders manquante"})
        return _done(connection, QuoteService(connection).convert_to_order(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, quote_id=quote_id, location_id=body.location_id,
            requested_ship_date=body.requested_ship_date,
        ))


# ---- pricing --------------------------------------------------------------------------------------

class PriceListRequest(BaseModel):
    name: str
    valid_from: datetime.date | None = None
    valid_to: datetime.date | None = None
    is_default: bool = False
    active: bool = True
    note: str | None = None


class PriceItemRequest(BaseModel):
    product_id: str
    min_quantity: Decimal = Decimal("1")
    unit_price: Decimal


class ReplaceItemsRequest(BaseModel):
    items: list[PriceItemRequest]


class ImportRequest(BaseModel):
    filename: str
    content_base64: str
    commit: bool = False


class CustomerPricingRequest(BaseModel):
    price_list_id: str | None = None
    discount_rate: Decimal = Decimal("0")


class SettingsRequest(BaseModel):
    default_vat_rate: Decimal | None = None
    max_discount_rate: Decimal | None = None
    quote_validity_days: int | None = None


class ResolveItem(BaseModel):
    product_id: str
    quantity: Decimal = Decimal("1")


class ResolveRequest(BaseModel):
    partner_id: str | None = None
    on: datetime.date | None = None
    items: list[ResolveItem]


@pricing_router.get("/price-lists")
def list_price_lists(tenant: TenantContext = Depends(require_permission(VIEW_ORDERS))) -> list[dict]:
    with get_connection() as connection:
        return PricingService(connection).list_price_lists(tenant_id=tenant.tenant_id)


@pricing_router.get("/price-lists/{price_list_id}")
def get_price_list(price_list_id: str, tenant: TenantContext = Depends(require_permission(VIEW_ORDERS))) -> dict:
    with get_connection() as connection:
        return _done(connection, PricingService(connection).get_price_list(tenant_id=tenant.tenant_id, price_list_id=price_list_id))


@pricing_router.post("/price-lists", status_code=status.HTTP_201_CREATED)
def create_price_list(body: PriceListRequest, tenant: TenantContext = Depends(require_permission(MANAGE_PRICE_LISTS))) -> dict:
    with get_connection() as connection:
        return _done(connection, PricingService(connection).save_price_list(tenant_id=tenant.tenant_id, actor_id=tenant.user_id,
                                                                            **body.model_dump()))


@pricing_router.patch("/price-lists/{price_list_id}")
def update_price_list(price_list_id: str, body: PriceListRequest,
                      tenant: TenantContext = Depends(require_permission(MANAGE_PRICE_LISTS))) -> dict:
    with get_connection() as connection:
        return _done(connection, PricingService(connection).save_price_list(tenant_id=tenant.tenant_id, actor_id=tenant.user_id,
                                                                            price_list_id=price_list_id, **body.model_dump()))


@pricing_router.delete("/price-lists/{price_list_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_price_list(price_list_id: str, tenant: TenantContext = Depends(require_permission(MANAGE_PRICE_LISTS))) -> Response:
    with get_connection() as connection:
        _done(connection, PricingService(connection).delete_price_list(tenant_id=tenant.tenant_id, actor_id=tenant.user_id,
                                                                       price_list_id=price_list_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@pricing_router.put("/price-lists/{price_list_id}/items")
def replace_price_items(price_list_id: str, body: ReplaceItemsRequest,
                        tenant: TenantContext = Depends(require_permission(MANAGE_PRICE_LISTS))) -> dict:
    with get_connection() as connection:
        return _done(connection, PricingService(connection).replace_items(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, price_list_id=price_list_id,
            items=[item.model_dump() for item in body.items],
        ))


@pricing_router.post("/price-lists/{price_list_id}/import")
def import_price_items(price_list_id: str, body: ImportRequest,
                       tenant: TenantContext = Depends(require_permission(MANAGE_PRICE_LISTS))) -> dict:
    with get_connection() as connection:
        return _done(connection, PricingService(connection).import_items(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, price_list_id=price_list_id, filename=body.filename,
            content_base64=body.content_base64, commit=body.commit,
        ))


@pricing_router.get("/price-lists/{price_list_id}/export")
def export_price_items(price_list_id: str, format: str = Query(default="xlsx", pattern="^(csv|xlsx)$"), lang: str = "fr",
                       tenant: TenantContext = Depends(require_permission(VIEW_ORDERS))) -> Response:
    with get_connection() as connection:
        service = PricingService(connection)
        found = service.get_price_list(tenant_id=tenant.tenant_id, price_list_id=price_list_id)
        if isinstance(found, Err):
            _raise(found)
        rows = service.export_rows(tenant_id=tenant.tenant_id, price_list_id=price_list_id)
    headers = (["sku", "produit", "min_quantity", "unit_price"] if lang == "fr" else ["sku", "product", "min_quantity", "unit_price"])
    return tabular_response(headers, rows, format, "liste-de-prix" if lang == "fr" else "price-list")


@pricing_router.get("/customer-pricing")
def list_customer_pricing(tenant: TenantContext = Depends(require_permission(VIEW_ORDERS))) -> list[dict]:
    with get_connection() as connection:
        return PricingService(connection).list_customer_pricing(tenant_id=tenant.tenant_id)


@pricing_router.get("/customer-pricing/{partner_id}")
def get_customer_pricing(partner_id: str, tenant: TenantContext = Depends(require_permission(VIEW_ORDERS))) -> dict:
    with get_connection() as connection:
        return PricingService(connection).get_customer_pricing(tenant_id=tenant.tenant_id, partner_id=partner_id)


@pricing_router.put("/customer-pricing/{partner_id}")
def set_customer_pricing(partner_id: str, body: CustomerPricingRequest,
                         tenant: TenantContext = Depends(require_permission(MANAGE_PRICE_LISTS))) -> dict:
    with get_connection() as connection:
        return _done(connection, PricingService(connection).set_customer_pricing(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, partner_id=partner_id, price_list_id=body.price_list_id,
            discount_rate=body.discount_rate,
        ))


@pricing_router.post("/prices/resolve")
def resolve_prices(body: ResolveRequest, tenant: TenantContext = Depends(require_permission(VIEW_ORDERS))) -> list[dict]:
    with get_connection() as connection:
        return _done(connection, PricingService(connection).resolve_prices(
            tenant_id=tenant.tenant_id, partner_id=body.partner_id, items=[(i.product_id, i.quantity) for i in body.items], on=body.on,
        ))


@pricing_router.get("/settings")
def get_settings(tenant: TenantContext = Depends(require_permission(VIEW_ORDERS))) -> dict:
    with get_connection() as connection:
        settings = PricingService(connection).get_settings(tenant_id=tenant.tenant_id)
        settings["may_exceed_discount"] = user_has_permission(connection, user_id=tenant.user_id, permission=ADMIN_DISCOUNTS)
    return settings


@pricing_router.put("/settings")
def update_settings(body: SettingsRequest, tenant: TenantContext = Depends(require_permission(ADMIN_SETTINGS))) -> dict:
    with get_connection() as connection:
        return _done(connection, PricingService(connection).update_settings(tenant_id=tenant.tenant_id, actor_id=tenant.user_id,
                                                                            **body.model_dump()))
