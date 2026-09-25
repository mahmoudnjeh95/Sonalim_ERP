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
        return Err(
            "INVALID_CODE",
            "currency code must be a 3-letter ISO 4217 code",
            "le code devise doit être un code ISO 4217 à 3 lettres",
        )
    if not name.strip():
        return Err("INVALID_NAME", "currency name is required", "le nom de la devise est obligatoire")
    if decimal_places < 0:
        return Err("INVALID_DECIMAL_PLACES", "decimal_places must be >= 0", "decimal_places doit être >= 0")
    return Ok(None)


@dataclass(frozen=True)
class UnitOfMeasure:
    id: str
    tenant_id: str
    code: str
    name: str
    category: str
    ratio_to_base: float
    # How the unit prints next to a quantity. `code` is a key -- short, ASCII,
    # what imports and integrations match on -- and is a poor label: "5 ea" is
    # not a thing a French plant reads. None means nothing better was recorded,
    # and the reader falls back to the code rather than to a guess.
    symbol: str | None = None
    # Whether a quantity in this unit must be a whole number -- a carton or a
    # pièce, never a kg or a litre. Separate from `category`: that names the
    # kind of measurement, this says whether it can be split.
    is_integer_only: bool = False

    @property
    def display(self) -> str:
        """The form to print. Never empty, never invented."""
        return self.symbol or self.code


def validate_quantity_for_uom(quantity: float, uom: UnitOfMeasure) -> Result[None]:
    """A quantity about to be recorded against this unit. Integer-only units --
    pièces, cartons -- reject a fractional value. Floating-point noise from a
    chain of additions (2.9999999999999996) is rounded away before the check --
    the intent is "must be a whole count", not "must be exactly representable
    in binary"."""
    if uom.is_integer_only and abs(quantity - round(quantity)) > 1e-6:
        return Err(
            "QUANTITY_MUST_BE_INTEGER",
            f"{uom.display} is a whole-count unit; {quantity} is not a whole number",
            f"{uom.display} est une unité de mesure à quantité entière ; {quantity} n'est pas un nombre entier",
        )
    return Ok(None)


LOT_SERIAL_TRACKING_MODES = {"none", "lot", "serial"}
EXPIRY_DATE_POLICIES = {"none", "sell_by", "eat_by"}
PRODUCT_TYPES = {"PL", "PC"}


@dataclass(frozen=True)
class Product:
    id: str
    tenant_id: str
    sku: str
    name: str
    product_type: str
    uom_id: str
    product_family: str | None = None
    net_weight_grams: float | None = None
    empty_packaging_weight_grams: float | None = None
    sachets_per_package: float | None = None
    # Phase 9, decision 20. Nullable because some finished goods have no carton
    # at all -- a 4.54 kg sac is its own selling unit -- so NULL means "no carton
    # line", not "not filled in yet".
    packets_per_carton: float | None = None
    carton_weight_grams: float | None = None
    cartons_per_pallet: float | None = None
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
    # Populated only by list_products (a single aggregate query for the whole
    # tenant) -- other lookups (get_product, create/update) leave this empty
    # rather than paying for a per-product tag query they don't need.
    tag_ids: tuple[str, ...] = ()


def validate_new_product(
    *,
    sku: str,
    name: str,
    product_type: str,
    uom_id: str,
    net_weight_grams: float | None = None,
    empty_packaging_weight_grams: float | None = None,
    sachets_per_package: float | None = None,
    packets_per_carton: float | None = None,
    carton_weight_grams: float | None = None,
    cartons_per_pallet: float | None = None,
    lot_serial_tracking: str = "none",
    expiry_date_policy: str = "none",
    selling_price: float = 0,
    min_selling_price: float | None = None,
    purchase_price: float = 0,
    tax_rate: float = 0,
) -> Result[None]:
    if not sku.strip():
        return Err("INVALID_SKU", "sku is required", "sku est obligatoire")
    if not name.strip():
        return Err("INVALID_NAME", "name is required", "le nom est obligatoire")
    if product_type not in PRODUCT_TYPES:
        return Err(
            "INVALID_PRODUCT_TYPE",
            f"product_type must be one of {sorted(PRODUCT_TYPES)}",
            f"product_type doit être l'un de {sorted(PRODUCT_TYPES)}",
        )
    if not uom_id.strip():
        return Err("INVALID_UOM", "uom_id is required", "uom_id est obligatoire")
    if net_weight_grams is not None and net_weight_grams <= 0:
        return Err("INVALID_WEIGHT", "net_weight_grams must be positive", "net_weight_grams doit être positif")
    if empty_packaging_weight_grams is not None and empty_packaging_weight_grams <= 0:
        return Err(
            "INVALID_WEIGHT",
            "empty_packaging_weight_grams must be positive",
            "empty_packaging_weight_grams doit être positif",
        )
    if sachets_per_package is not None and sachets_per_package <= 0:
        return Err("INVALID_QUANTITY", "sachets_per_package must be positive", "sachets_per_package doit être positif")
    if packets_per_carton is not None and packets_per_carton <= 0:
        return Err(
            "INVALID_PACKETS_PER_CARTON",
            "packets_per_carton must be positive",
            "packets_per_carton doit être positif",
        )
    if carton_weight_grams is not None and carton_weight_grams <= 0:
        return Err("INVALID_WEIGHT", "carton_weight_grams must be positive", "carton_weight_grams doit être positif")
    if cartons_per_pallet is not None and cartons_per_pallet <= 0:
        return Err("INVALID_QUANTITY", "cartons_per_pallet must be positive", "cartons_per_pallet doit être positif")
    if lot_serial_tracking not in LOT_SERIAL_TRACKING_MODES:
        return Err(
            "INVALID_LOT_SERIAL_TRACKING",
            f"lot_serial_tracking must be one of {sorted(LOT_SERIAL_TRACKING_MODES)}",
            f"lot_serial_tracking doit être l'un de {sorted(LOT_SERIAL_TRACKING_MODES)}",
        )
    if expiry_date_policy not in EXPIRY_DATE_POLICIES:
        return Err(
            "INVALID_EXPIRY_DATE_POLICY",
            f"expiry_date_policy must be one of {sorted(EXPIRY_DATE_POLICIES)}",
            f"expiry_date_policy doit être l'un de {sorted(EXPIRY_DATE_POLICIES)}",
        )
    if selling_price < 0:
        return Err("INVALID_PRICE", "selling_price cannot be negative", "selling_price ne peut pas être négatif")
    if purchase_price < 0:
        return Err("INVALID_PRICE", "purchase_price cannot be negative", "purchase_price ne peut pas être négatif")
    if tax_rate < 0:
        return Err("INVALID_TAX_RATE", "tax_rate cannot be negative", "tax_rate ne peut pas être négatif")
    if min_selling_price is not None:
        if min_selling_price < 0:
            return Err("INVALID_PRICE", "min_selling_price cannot be negative", "min_selling_price ne peut pas être négatif")
        if min_selling_price > selling_price:
            return Err(
                "INVALID_PRICE",
                "min_selling_price cannot exceed selling_price",
                "min_selling_price ne peut pas dépasser selling_price",
            )
    return Ok(None)


@dataclass(frozen=True)
class ProductAttribute:
    id: str
    tenant_id: str
    name: str


def validate_new_product_attribute(*, name: str) -> Result[None]:
    if not name.strip():
        return Err("INVALID_NAME", "attribute name is required", "le nom de l'attribut est obligatoire")
    return Ok(None)


@dataclass(frozen=True)
class ProductAttributeValue:
    id: str
    tenant_id: str
    attribute_id: str
    value: str


def validate_new_product_attribute_value(*, value: str) -> Result[None]:
    if not value.strip():
        return Err("INVALID_VALUE", "attribute value is required", "la valeur de l'attribut est obligatoire")
    return Ok(None)


@dataclass(frozen=True)
class ProductTag:
    id: str
    tenant_id: str
    name: str


def validate_new_product_tag(*, name: str) -> Result[None]:
    if not name.strip():
        return Err("INVALID_NAME", "tag name is required", "le nom de l'étiquette est obligatoire")
    return Ok(None)
