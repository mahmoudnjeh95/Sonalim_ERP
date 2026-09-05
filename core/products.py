from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from core.api.service import CoreService
from core.db import get_connection
from core.domain.entities import Product, ProductAttribute, ProductAttributeValue, ProductTag, UnitOfMeasure
from core.domain.partner import SuggestedVendor
from core.domain.result import Err
from core.tenancy import TenantContext, require_permission

router = APIRouter(prefix="/core/products", tags=["core.products"])
uoms_router = APIRouter(prefix="/core/uoms", tags=["core.uoms"])
attributes_router = APIRouter(prefix="/core/product-attributes", tags=["core.product-attributes"])
tags_router = APIRouter(prefix="/core/product-tags", tags=["core.product-tags"])


class CreateProductRequest(BaseModel):
    sku: str
    name: str
    uom_id: str
    net_weight_grams: float | None = None
    packets_per_carton: float | None = None
    is_sellable: bool = True
    is_purchasable: bool = True
    lot_serial_tracking: str = "none"
    expiry_date_policy: str = "none"
    description: str | None = None
    default_location_id: str | None = None
    stock_alert_threshold: float | None = None
    internal_note: str | None = None
    selling_price: float = 0
    min_selling_price: float | None = None
    purchase_price: float = 0
    tax_rate: float = 0
    accounting_code_sale: str | None = None
    accounting_code_sale_export: str | None = None
    accounting_code_purchase: str | None = None
    accounting_code_purchase_import: str | None = None


class UpdateProductRequest(BaseModel):
    sku: str | None = None
    name: str | None = None
    uom_id: str | None = None
    net_weight_grams: float | None = None
    packets_per_carton: float | None = None
    is_sellable: bool | None = None
    is_purchasable: bool | None = None
    lot_serial_tracking: str | None = None
    expiry_date_policy: str | None = None
    description: str | None = None
    default_location_id: str | None = None
    stock_alert_threshold: float | None = None
    internal_note: str | None = None
    selling_price: float | None = None
    min_selling_price: float | None = None
    purchase_price: float | None = None
    tax_rate: float | None = None
    accounting_code_sale: str | None = None
    accounting_code_sale_export: str | None = None
    accounting_code_purchase: str | None = None
    accounting_code_purchase_import: str | None = None


class CreateProductAttributeRequest(BaseModel):
    name: str


class CreateProductAttributeValueRequest(BaseModel):
    value: str


class CreateProductVariantRequest(BaseModel):
    sku: str
    name: str
    attribute_value_ids: list[str]


class CreateProductTagRequest(BaseModel):
    name: str


class SetProductTagsRequest(BaseModel):
    tag_ids: list[str]


def _product_response(product: Product) -> dict:
    return {
        "id": product.id,
        "sku": product.sku,
        "name": product.name,
        "uom_id": product.uom_id,
        "net_weight_grams": product.net_weight_grams,
        "packets_per_carton": product.packets_per_carton,
        "parent_product_id": product.parent_product_id,
        "is_sellable": product.is_sellable,
        "is_purchasable": product.is_purchasable,
        "lot_serial_tracking": product.lot_serial_tracking,
        "expiry_date_policy": product.expiry_date_policy,
        "description": product.description,
        "default_location_id": product.default_location_id,
        "stock_alert_threshold": product.stock_alert_threshold,
        "internal_note": product.internal_note,
        "selling_price": product.selling_price,
        "min_selling_price": product.min_selling_price,
        "purchase_price": product.purchase_price,
        "tax_rate": product.tax_rate,
        "accounting_code_sale": product.accounting_code_sale,
        "accounting_code_sale_export": product.accounting_code_sale_export,
        "accounting_code_purchase": product.accounting_code_purchase,
        "accounting_code_purchase_import": product.accounting_code_purchase_import,
    }


def _uom_response(uom: UnitOfMeasure) -> dict:
    return {
        "id": uom.id,
        "code": uom.code,
        "name": uom.name,
        "category": uom.category,
        "ratio_to_base": uom.ratio_to_base,
        # What screens print. Separate from `code`, which stays the key clients match on.
        "symbol": uom.display,
        "is_integer_only": uom.is_integer_only,
    }


def _attribute_response(attribute: ProductAttribute) -> dict:
    return {"id": attribute.id, "name": attribute.name}


def _attribute_value_response(value: ProductAttributeValue) -> dict:
    return {"id": value.id, "attribute_id": value.attribute_id, "value": value.value}


def _tag_response(tag: ProductTag) -> dict:
    return {"id": tag.id, "name": tag.name}


def _suggested_vendor_response(vendor: SuggestedVendor) -> dict:
    return {
        "partner_id": vendor.partner_id,
        "name": vendor.name,
        "kind": vendor.kind,
        "industry": vendor.industry,
        "phone": vendor.phone,
        "email": vendor.email,
        "is_preferred": vendor.is_preferred,
        "lead_time_days": vendor.lead_time_days,
        "min_order_qty": vendor.min_order_qty,
    }


def _err_status(code: str) -> int:
    if code == "NOT_FOUND":
        return status.HTTP_404_NOT_FOUND
    if code in ("DUPLICATE_SKU", "DUPLICATE_NAME", "DUPLICATE_VALUE", "PRODUCT_IN_USE"):
        return status.HTTP_409_CONFLICT
    return status.HTTP_400_BAD_REQUEST


@router.get("")
def list_products(tenant: TenantContext = Depends(require_permission("core.view_products"))) -> list[dict]:
    with get_connection() as connection:
        service = CoreService(connection)
        products = service.list_products(tenant.tenant_id)
    return [_product_response(product) for product in products]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_product(
    body: CreateProductRequest, tenant: TenantContext = Depends(require_permission("core.manage_products"))
) -> dict:
    with get_connection() as connection:
        service = CoreService(connection)
        result = service.create_product(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, **body.model_dump())
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_err_status(result.code), {"code": result.code, "message": result.message})
        connection.commit()
    return _product_response(result.value)


@router.patch("/{product_id}")
def update_product(
    product_id: str,
    body: UpdateProductRequest,
    tenant: TenantContext = Depends(require_permission("core.manage_products")),
) -> dict:
    changes = {k: v for k, v in body.model_dump().items() if v is not None}
    with get_connection() as connection:
        service = CoreService(connection)
        result = service.update_product(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, product_id=product_id, **changes)
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_err_status(result.code), {"code": result.code, "message": result.message})
        connection.commit()
    return _product_response(result.value)


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def delete_product(
    product_id: str,
    tenant: TenantContext = Depends(require_permission("core.manage_products")),
) -> None:
    with get_connection() as connection:
        service = CoreService(connection)
        result = service.delete_product(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, product_id=product_id)
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_err_status(result.code), {"code": result.code, "message": result.message})
        connection.commit()


@router.get("/{product_id}/tags")
def list_product_tags_for_product(
    product_id: str, tenant: TenantContext = Depends(require_permission("core.view_products"))
) -> list[dict]:
    with get_connection() as connection:
        service = CoreService(connection)
        tags = service.list_tags_for_product(tenant.tenant_id, product_id)
    return [_tag_response(tag) for tag in tags]


@router.put("/{product_id}/tags")
def set_product_tags(
    product_id: str,
    body: SetProductTagsRequest,
    tenant: TenantContext = Depends(require_permission("core.manage_products")),
) -> list[dict]:
    with get_connection() as connection:
        service = CoreService(connection)
        result = service.set_product_tags(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, product_id=product_id, tag_ids=body.tag_ids
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_err_status(result.code), {"code": result.code, "message": result.message})
        connection.commit()
    return [_tag_response(tag) for tag in result.value]


@router.get("/{product_id}/suggested-vendors")
def list_suggested_vendors(
    product_id: str, tenant: TenantContext = Depends(require_permission("core.view_products"))
) -> list[dict]:
    with get_connection() as connection:
        service = CoreService(connection)
        vendors = service.list_suggested_vendors_for_product(tenant.tenant_id, product_id)
    return [_suggested_vendor_response(vendor) for vendor in vendors]


@router.get("/{product_id}/variants")
def list_product_variants(
    product_id: str, tenant: TenantContext = Depends(require_permission("core.view_products"))
) -> list[dict]:
    with get_connection() as connection:
        service = CoreService(connection)
        variants = service.list_product_variants(tenant.tenant_id, product_id)
    return [_product_response(variant) for variant in variants]


@router.post("/{product_id}/variants", status_code=status.HTTP_201_CREATED)
def create_product_variant(
    product_id: str,
    body: CreateProductVariantRequest,
    tenant: TenantContext = Depends(require_permission("core.manage_products")),
) -> dict:
    with get_connection() as connection:
        service = CoreService(connection)
        result = service.create_product_variant(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            parent_product_id=product_id,
            sku=body.sku,
            name=body.name,
            attribute_value_ids=body.attribute_value_ids,
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_err_status(result.code), {"code": result.code, "message": result.message})
        connection.commit()
    return _product_response(result.value)


@uoms_router.get("")
def list_uoms(tenant: TenantContext = Depends(require_permission("core.view_products"))) -> list[dict]:
    with get_connection() as connection:
        service = CoreService(connection)
        uoms = service.list_uoms(tenant.tenant_id)
    return [_uom_response(uom) for uom in uoms]


@attributes_router.get("")
def list_product_attributes(tenant: TenantContext = Depends(require_permission("core.view_products"))) -> list[dict]:
    with get_connection() as connection:
        service = CoreService(connection)
        attributes = service.list_product_attributes(tenant.tenant_id)
    return [_attribute_response(attribute) for attribute in attributes]


@attributes_router.post("", status_code=status.HTTP_201_CREATED)
def create_product_attribute(
    body: CreateProductAttributeRequest, tenant: TenantContext = Depends(require_permission("core.manage_products"))
) -> dict:
    with get_connection() as connection:
        service = CoreService(connection)
        result = service.create_product_attribute(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, name=body.name)
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_err_status(result.code), {"code": result.code, "message": result.message})
        connection.commit()
    return _attribute_response(result.value)


@attributes_router.get("/{attribute_id}/values")
def list_product_attribute_values(
    attribute_id: str, tenant: TenantContext = Depends(require_permission("core.view_products"))
) -> list[dict]:
    with get_connection() as connection:
        service = CoreService(connection)
        values = service.list_product_attribute_values(tenant.tenant_id, attribute_id)
    return [_attribute_value_response(value) for value in values]


@attributes_router.post("/{attribute_id}/values", status_code=status.HTTP_201_CREATED)
def create_product_attribute_value(
    attribute_id: str,
    body: CreateProductAttributeValueRequest,
    tenant: TenantContext = Depends(require_permission("core.manage_products")),
) -> dict:
    with get_connection() as connection:
        service = CoreService(connection)
        result = service.create_product_attribute_value(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, attribute_id=attribute_id, value=body.value
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_err_status(result.code), {"code": result.code, "message": result.message})
        connection.commit()
    return _attribute_value_response(result.value)


@tags_router.get("")
def list_product_tags(tenant: TenantContext = Depends(require_permission("core.view_products"))) -> list[dict]:
    with get_connection() as connection:
        service = CoreService(connection)
        tags = service.list_product_tags(tenant.tenant_id)
    return [_tag_response(tag) for tag in tags]


@tags_router.post("", status_code=status.HTTP_201_CREATED)
def create_product_tag(
    body: CreateProductTagRequest, tenant: TenantContext = Depends(require_permission("core.manage_products"))
) -> dict:
    with get_connection() as connection:
        service = CoreService(connection)
        result = service.create_product_tag(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, name=body.name)
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_err_status(result.code), {"code": result.code, "message": result.message})
        connection.commit()
    return _tag_response(result.value)
