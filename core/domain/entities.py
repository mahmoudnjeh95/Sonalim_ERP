from __future__ import annotations

from dataclasses import dataclass

from core.domain.result import Err, Ok, Result


@dataclass(frozen=True)
class Company:
    id: str
    tenant_id: str
    name: str


@dataclass(frozen=True)
class Currency:
    code: str
    name: str
    decimal_places: int


def validate_new_currency(*, code: str, name: str, decimal_places: int) -> Result[None]:
    if len(code.strip()) != 3 or not code.strip().isalpha():
        return Err("INVALID_CODE", "currency code must be a 3-letter ISO 4217 code")
    if not name.strip():
        return Err("INVALID_NAME", "currency name is required")
    if decimal_places < 0:
        return Err("INVALID_DECIMAL_PLACES", "decimal_places must be >= 0")
    return Ok(None)


@dataclass(frozen=True)
class UnitOfMeasure:
    id: str
    tenant_id: str
    code: str
    name: str
    category: str
    ratio_to_base: float


LOT_SERIAL_TRACKING_MODES = {"none", "lot", "serial"}
EXPIRY_DATE_POLICIES = {"none", "sell_by", "eat_by"}


@dataclass(frozen=True)
class Product:
    id: str
    tenant_id: str
    sku: str
    name: str
    uom_id: str
    net_weight_grams: float | None = None
    parent_product_id: str | None = None
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


def validate_new_product(
    *,
    sku: str,
    name: str,
    uom_id: str,
    net_weight_grams: float | None = None,
    lot_serial_tracking: str = "none",
    expiry_date_policy: str = "none",
    selling_price: float = 0,
    min_selling_price: float | None = None,
    purchase_price: float = 0,
    tax_rate: float = 0,
) -> Result[None]:
    if not sku.strip():
        return Err("INVALID_SKU", "sku is required")
    if not name.strip():
        return Err("INVALID_NAME", "name is required")
    if not uom_id.strip():
        return Err("INVALID_UOM", "uom_id is required")
    if net_weight_grams is not None and net_weight_grams <= 0:
        return Err("INVALID_WEIGHT", "net_weight_grams must be positive")
    if lot_serial_tracking not in LOT_SERIAL_TRACKING_MODES:
        return Err("INVALID_LOT_SERIAL_TRACKING", f"lot_serial_tracking must be one of {sorted(LOT_SERIAL_TRACKING_MODES)}")
    if expiry_date_policy not in EXPIRY_DATE_POLICIES:
        return Err("INVALID_EXPIRY_DATE_POLICY", f"expiry_date_policy must be one of {sorted(EXPIRY_DATE_POLICIES)}")
    if selling_price < 0:
        return Err("INVALID_PRICE", "selling_price cannot be negative")
    if purchase_price < 0:
        return Err("INVALID_PRICE", "purchase_price cannot be negative")
    if tax_rate < 0:
        return Err("INVALID_TAX_RATE", "tax_rate cannot be negative")
    if min_selling_price is not None:
        if min_selling_price < 0:
            return Err("INVALID_PRICE", "min_selling_price cannot be negative")
        if min_selling_price > selling_price:
            return Err("INVALID_PRICE", "min_selling_price cannot exceed selling_price")
    return Ok(None)


@dataclass(frozen=True)
class ProductAttribute:
    id: str
    tenant_id: str
    name: str


def validate_new_product_attribute(*, name: str) -> Result[None]:
    if not name.strip():
        return Err("INVALID_NAME", "attribute name is required")
    return Ok(None)


@dataclass(frozen=True)
class ProductAttributeValue:
    id: str
    tenant_id: str
    attribute_id: str
    value: str


def validate_new_product_attribute_value(*, value: str) -> Result[None]:
    if not value.strip():
        return Err("INVALID_VALUE", "attribute value is required")
    return Ok(None)


@dataclass(frozen=True)
class ProductTag:
    id: str
    tenant_id: str
    name: str


def validate_new_product_tag(*, name: str) -> Result[None]:
    if not name.strip():
        return Err("INVALID_NAME", "tag name is required")
    return Ok(None)
