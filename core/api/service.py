from __future__ import annotations

import dataclasses
import datetime

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.entities import (
    Currency,
    Product,
    ProductAttribute,
    ProductAttributeValue,
    ProductTag,
    UnitOfMeasure,
    validate_new_currency,
    validate_new_product,
    validate_new_product_attribute,
    validate_new_product_attribute_value,
    validate_new_product_tag,
)
from core.domain.exchange_rate import BASE_CURRENCY, ExchangeRate, convert_to_base, validate_rate
from core.domain.partner import (
    Partner,
    PartnerTagLink,
    SuggestedVendor,
    transition_partner,
    validate_partner_name,
    validate_partner_tag_link,
)
from core.domain.result import Err, Ok, Result
from core.events.outbox import publish_event

_PRODUCT_COLUMNS = """
    id, tenant_id, sku, name, product_type, product_family, uom_id, net_weight_grams, empty_packaging_weight_grams, sachets_per_package,
    packets_per_carton, carton_weight_grams, cartons_per_pallet, parent_product_id, is_sellable, is_purchasable,
    lot_serial_tracking, expiry_date_policy, description, default_location_id, stock_alert_threshold,
    internal_note, selling_price, min_selling_price, purchase_price, tax_rate, accounting_code_sale,
    accounting_code_sale_export, accounting_code_purchase, accounting_code_purchase_import
"""

_PRODUCT_EDITABLE_FIELDS = (
    "sku",
    "name",
    "product_type",
    "product_family",
    "uom_id",
    "net_weight_grams",
    "empty_packaging_weight_grams",
    "sachets_per_package",
    "packets_per_carton",
    "carton_weight_grams",
    "cartons_per_pallet",
    "is_sellable",
    "is_purchasable",
    "lot_serial_tracking",
    "expiry_date_policy",
    "description",
    "default_location_id",
    "stock_alert_threshold",
    "internal_note",
    "selling_price",
    "min_selling_price",
    "purchase_price",
    "tax_rate",
    "accounting_code_sale",
    "accounting_code_sale_export",
    "accounting_code_purchase",
    "accounting_code_purchase_import",
)


def _row_to_product(row: tuple) -> Product:
    (
        pid, tenant_id, sku, name, product_type, product_family, uom_id, net_weight_grams, empty_packaging_weight_grams, sachets_per_package,
        packets_per_carton, carton_weight_grams, cartons_per_pallet, parent_product_id, is_sellable, is_purchasable,
        lot_serial_tracking, expiry_date_policy, description, default_location_id, stock_alert_threshold,
        internal_note, selling_price, min_selling_price, purchase_price, tax_rate, accounting_code_sale,
        accounting_code_sale_export, accounting_code_purchase, accounting_code_purchase_import,
    ) = row
    return Product(
        id=pid,
        tenant_id=tenant_id,
        sku=sku,
        name=name,
        product_type=product_type,
        product_family=product_family,
        uom_id=uom_id,
        net_weight_grams=float(net_weight_grams) if net_weight_grams is not None else None,
        empty_packaging_weight_grams=float(empty_packaging_weight_grams) if empty_packaging_weight_grams is not None else None,
        sachets_per_package=float(sachets_per_package) if sachets_per_package is not None else None,
        packets_per_carton=float(packets_per_carton) if packets_per_carton is not None else None,
        carton_weight_grams=float(carton_weight_grams) if carton_weight_grams is not None else None,
        cartons_per_pallet=float(cartons_per_pallet) if cartons_per_pallet is not None else None,
        parent_product_id=parent_product_id,
        is_sellable=is_sellable,
        is_purchasable=is_purchasable,
        lot_serial_tracking=lot_serial_tracking,
        expiry_date_policy=expiry_date_policy,
        description=description,
        default_location_id=default_location_id,
        stock_alert_threshold=float(stock_alert_threshold) if stock_alert_threshold is not None else None,
        internal_note=internal_note,
        selling_price=float(selling_price),
        min_selling_price=float(min_selling_price) if min_selling_price is not None else None,
        purchase_price=float(purchase_price),
        tax_rate=float(tax_rate),
        accounting_code_sale=accounting_code_sale,
        accounting_code_sale_export=accounting_code_sale_export,
        accounting_code_purchase=accounting_code_purchase,
        accounting_code_purchase_import=accounting_code_purchase_import,
    )


class CoreService:
    """Public API surface for shared-kernel lookups (Product, Partner, ...) used by other modules."""

    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def list_products(self, tenant_id: str) -> list[Product]:
        rows = self._connection.execute(
            f"SELECT {_PRODUCT_COLUMNS} FROM core.products WHERE tenant_id = %s ORDER BY name",
            (tenant_id,),
        ).fetchall()
        products = [_row_to_product(row) for row in rows]

        # One extra query for the whole tenant rather than one per product: a
        # screen that needs "which products are tagged Film/Carton/Ruban" (e.g.
        # to filter a packaging picker) would otherwise be an N+1.
        tag_rows = self._connection.execute(
            "SELECT product_id, tag_id FROM core.product_tag_links WHERE product_id = ANY(%s)",
            ([p.id for p in products],),
        ).fetchall()
        tag_ids_by_product: dict[str, list[str]] = {}
        for product_id, tag_id in tag_rows:
            tag_ids_by_product.setdefault(product_id, []).append(tag_id)

        return [
            dataclasses.replace(product, tag_ids=tuple(tag_ids_by_product.get(product.id, ())))
            for product in products
        ]

    def get_product(self, tenant_id: str, product_id: str) -> Product | None:
        row = self._connection.execute(
            f"SELECT {_PRODUCT_COLUMNS} FROM core.products WHERE id = %s AND tenant_id = %s",
            (product_id, tenant_id),
        ).fetchone()
        return _row_to_product(row) if row else None

    def create_product(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        sku: str,
        name: str,
        product_type: str,
        uom_id: str,
        product_family: str | None = None,
        net_weight_grams: float | None = None,
        empty_packaging_weight_grams: float | None = None,
        sachets_per_package: float | None = None,
        packets_per_carton: float | None = None,
        carton_weight_grams: float | None = None,
        cartons_per_pallet: float | None = None,
        is_sellable: bool = True,
        is_purchasable: bool = True,
        lot_serial_tracking: str = "none",
        expiry_date_policy: str = "none",
        description: str | None = None,
        default_location_id: str | None = None,
        stock_alert_threshold: float | None = None,
        internal_note: str | None = None,
        selling_price: float = 0,
        min_selling_price: float | None = None,
        purchase_price: float = 0,
        tax_rate: float = 0,
        accounting_code_sale: str | None = None,
        accounting_code_sale_export: str | None = None,
        accounting_code_purchase: str | None = None,
        accounting_code_purchase_import: str | None = None,
    ) -> Result[Product]:
        validation = validate_new_product(
            sku=sku,
            name=name,
            product_type=product_type,
            uom_id=uom_id,
            net_weight_grams=net_weight_grams,
            empty_packaging_weight_grams=empty_packaging_weight_grams,
            sachets_per_package=sachets_per_package,
            packets_per_carton=packets_per_carton,
            carton_weight_grams=carton_weight_grams,
            cartons_per_pallet=cartons_per_pallet,
            lot_serial_tracking=lot_serial_tracking,
            expiry_date_policy=expiry_date_policy,
            selling_price=selling_price,
            min_selling_price=min_selling_price,
            purchase_price=purchase_price,
            tax_rate=tax_rate,
        )
        if isinstance(validation, Err):
            return validation

        existing = self._connection.execute(
            "SELECT 1 FROM core.products WHERE tenant_id = %s AND sku = %s", (tenant_id, sku)
        ).fetchone()
        if existing is not None:
            return Err("DUPLICATE_SKU", f"a product with sku {sku!r} already exists")

        product_id = str(ULID())
        self._connection.execute(
            """
            INSERT INTO core.products (
                id, tenant_id, sku, name, product_type, product_family, uom_id, net_weight_grams, empty_packaging_weight_grams, sachets_per_package,
                packets_per_carton, carton_weight_grams, cartons_per_pallet, is_sellable, is_purchasable,
                lot_serial_tracking, expiry_date_policy, description, default_location_id, stock_alert_threshold,
                internal_note, selling_price, min_selling_price, purchase_price, tax_rate, accounting_code_sale,
                accounting_code_sale_export, accounting_code_purchase, accounting_code_purchase_import
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                product_id, tenant_id, sku, name, product_type, product_family, uom_id, net_weight_grams, empty_packaging_weight_grams, sachets_per_package,
                packets_per_carton, carton_weight_grams, cartons_per_pallet, is_sellable, is_purchasable,
                lot_serial_tracking, expiry_date_policy, description, default_location_id, stock_alert_threshold,
                internal_note, selling_price, min_selling_price, purchase_price, tax_rate, accounting_code_sale,
                accounting_code_sale_export, accounting_code_purchase, accounting_code_purchase_import,
            ),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="product.created",
            entity_type="product",
            entity_id=product_id,
            payload={"sku": sku, "name": name, "uom_id": uom_id},
        )
        publish_event(
            self._connection,
            event_type="core.product.created",
            producer="core",
            tenant_id=tenant_id,
            correlation_id=str(ULID()),
            payload={"product_id": product_id, "sku": sku, "is_sellable": is_sellable},
        )
        return Ok(self.get_product(tenant_id, product_id))

    def update_product(self, *, tenant_id: str, actor_id: str, product_id: str, **changes: object) -> Result[Product]:
        current = self.get_product(tenant_id, product_id)
        if current is None:
            return Err("NOT_FOUND", f"product {product_id} not found")

        unknown = set(changes) - set(_PRODUCT_EDITABLE_FIELDS)
        if unknown:
            return Err("INVALID_FIELD", f"cannot edit field(s): {', '.join(sorted(unknown))}")
        merged = {field: changes.get(field, getattr(current, field)) for field in _PRODUCT_EDITABLE_FIELDS}

        validation = validate_new_product(
            sku=merged["sku"],
            name=merged["name"],
            product_type=merged["product_type"],
            uom_id=merged["uom_id"],
            net_weight_grams=merged["net_weight_grams"],
            empty_packaging_weight_grams=merged["empty_packaging_weight_grams"],
            sachets_per_package=merged["sachets_per_package"],
            packets_per_carton=merged["packets_per_carton"],
            carton_weight_grams=merged["carton_weight_grams"],
            cartons_per_pallet=merged["cartons_per_pallet"],
            lot_serial_tracking=merged["lot_serial_tracking"],
            expiry_date_policy=merged["expiry_date_policy"],
            selling_price=merged["selling_price"],
            min_selling_price=merged["min_selling_price"],
            purchase_price=merged["purchase_price"],
            tax_rate=merged["tax_rate"],
        )
        if isinstance(validation, Err):
            return validation

        if merged["sku"] != current.sku:
            existing = self._connection.execute(
                "SELECT 1 FROM core.products WHERE tenant_id = %s AND sku = %s AND id != %s", (tenant_id, merged["sku"], product_id)
            ).fetchone()
            if existing is not None:
                return Err("DUPLICATE_SKU", f"a product with sku {merged['sku']!r} already exists")

        set_clauses = ", ".join(f"{field} = %s" for field in _PRODUCT_EDITABLE_FIELDS)
        self._connection.execute(
            f"UPDATE core.products SET {set_clauses} WHERE id = %s AND tenant_id = %s",
            (*[merged[field] for field in _PRODUCT_EDITABLE_FIELDS], product_id, tenant_id),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="product.updated",
            entity_type="product",
            entity_id=product_id,
            payload={"changes": {k: str(v) for k, v in changes.items()}},
        )
        return Ok(self.get_product(tenant_id, product_id))

    def delete_product(self, *, tenant_id: str, actor_id: str, product_id: str) -> Result[str]:
        current = self.get_product(tenant_id, product_id)
        if current is None:
            return Err("NOT_FOUND", f"product {product_id} not found")

        try:
            self._connection.execute(
                "DELETE FROM core.products WHERE id = %s AND tenant_id = %s", (product_id, tenant_id)
            )
        except psycopg.errors.ForeignKeyViolation:
            return Err(
                "PRODUCT_IN_USE",
                "this product is referenced elsewhere (stock, orders, recipes, ...) and cannot be deleted",
            )

        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="product.deleted",
            entity_type="product",
            entity_id=product_id,
            payload={"sku": current.sku, "name": current.name},
        )
        return Ok(product_id)

    # --- Variant attributes ---------------------------------------------------------------

    def list_product_attributes(self, tenant_id: str) -> list[ProductAttribute]:
        rows = self._connection.execute(
            "SELECT id, tenant_id, name FROM core.product_attributes WHERE tenant_id = %s ORDER BY name", (tenant_id,)
        ).fetchall()
        return [ProductAttribute(id=r[0], tenant_id=r[1], name=r[2]) for r in rows]

    def create_product_attribute(self, *, tenant_id: str, actor_id: str, name: str) -> Result[ProductAttribute]:
        validation = validate_new_product_attribute(name=name)
        if isinstance(validation, Err):
            return validation
        existing = self._connection.execute(
            "SELECT 1 FROM core.product_attributes WHERE tenant_id = %s AND name = %s", (tenant_id, name)
        ).fetchone()
        if existing is not None:
            return Err("DUPLICATE_NAME", f"an attribute named {name!r} already exists")
        attribute_id = str(ULID())
        self._connection.execute(
            "INSERT INTO core.product_attributes (id, tenant_id, name) VALUES (%s, %s, %s)", (attribute_id, tenant_id, name)
        )
        record_audit(
            self._connection, tenant_id=tenant_id, actor_id=actor_id, action="product_attribute.created",
            entity_type="product_attribute", entity_id=attribute_id, payload={"name": name},
        )
        return Ok(ProductAttribute(id=attribute_id, tenant_id=tenant_id, name=name))

    def list_product_attribute_values(self, tenant_id: str, attribute_id: str | None = None) -> list[ProductAttributeValue]:
        clauses = ["tenant_id = %s"]
        params: list[object] = [tenant_id]
        if attribute_id is not None:
            clauses.append("attribute_id = %s")
            params.append(attribute_id)
        rows = self._connection.execute(
            f"SELECT id, tenant_id, attribute_id, value FROM core.product_attribute_values WHERE {' AND '.join(clauses)} ORDER BY value",
            params,
        ).fetchall()
        return [ProductAttributeValue(id=r[0], tenant_id=r[1], attribute_id=r[2], value=r[3]) for r in rows]

    def create_product_attribute_value(
        self, *, tenant_id: str, actor_id: str, attribute_id: str, value: str
    ) -> Result[ProductAttributeValue]:
        validation = validate_new_product_attribute_value(value=value)
        if isinstance(validation, Err):
            return validation
        existing = self._connection.execute(
            "SELECT 1 FROM core.product_attribute_values WHERE attribute_id = %s AND value = %s", (attribute_id, value)
        ).fetchone()
        if existing is not None:
            return Err("DUPLICATE_VALUE", f"value {value!r} already exists for this attribute")
        value_id = str(ULID())
        self._connection.execute(
            "INSERT INTO core.product_attribute_values (id, tenant_id, attribute_id, value) VALUES (%s, %s, %s, %s)",
            (value_id, tenant_id, attribute_id, value),
        )
        record_audit(
            self._connection, tenant_id=tenant_id, actor_id=actor_id, action="product_attribute_value.created",
            entity_type="product_attribute_value", entity_id=value_id, payload={"attribute_id": attribute_id, "value": value},
        )
        return Ok(ProductAttributeValue(id=value_id, tenant_id=tenant_id, attribute_id=attribute_id, value=value))

    def create_product_variant(
        self, *, tenant_id: str, actor_id: str, parent_product_id: str, sku: str, name: str, attribute_value_ids: list[str]
    ) -> Result[Product]:
        parent = self.get_product(tenant_id, parent_product_id)
        if parent is None:
            return Err("NOT_FOUND", f"product {parent_product_id} not found")
        if not attribute_value_ids:
            return Err("INVALID_VARIANT", "a variant needs at least one attribute value")

        result = self.create_product(
            tenant_id=tenant_id,
            actor_id=actor_id,
            sku=sku,
            name=name,
            product_type=parent.product_type,
            product_family=parent.product_family,
            uom_id=parent.uom_id,
        )
        if isinstance(result, Err):
            return result
        variant = result.value
        self._connection.execute("UPDATE core.products SET parent_product_id = %s WHERE id = %s", (parent_product_id, variant.id))
        for value_id in attribute_value_ids:
            self._connection.execute(
                "INSERT INTO core.product_variant_values (product_id, attribute_value_id) VALUES (%s, %s)",
                (variant.id, value_id),
            )
        record_audit(
            self._connection, tenant_id=tenant_id, actor_id=actor_id, action="product_variant.created",
            entity_type="product", entity_id=variant.id,
            payload={"parent_product_id": parent_product_id, "attribute_value_ids": attribute_value_ids},
        )
        return Ok(self.get_product(tenant_id, variant.id))

    def list_product_variants(self, tenant_id: str, parent_product_id: str) -> list[Product]:
        rows = self._connection.execute(
            f"SELECT {_PRODUCT_COLUMNS} FROM core.products WHERE tenant_id = %s AND parent_product_id = %s ORDER BY name",
            (tenant_id, parent_product_id),
        ).fetchall()
        return [_row_to_product(row) for row in rows]

    # --- Tags -------------------------------------------------------------------------------

    def list_product_tags(self, tenant_id: str) -> list[ProductTag]:
        rows = self._connection.execute(
            "SELECT id, tenant_id, name FROM core.product_tags WHERE tenant_id = %s ORDER BY name", (tenant_id,)
        ).fetchall()
        return [ProductTag(id=r[0], tenant_id=r[1], name=r[2]) for r in rows]

    def create_product_tag(self, *, tenant_id: str, actor_id: str, name: str) -> Result[ProductTag]:
        validation = validate_new_product_tag(name=name)
        if isinstance(validation, Err):
            return validation
        existing = self._connection.execute(
            "SELECT 1 FROM core.product_tags WHERE tenant_id = %s AND name = %s", (tenant_id, name)
        ).fetchone()
        if existing is not None:
            return Err("DUPLICATE_NAME", f"a tag named {name!r} already exists")
        tag_id = str(ULID())
        self._connection.execute("INSERT INTO core.product_tags (id, tenant_id, name) VALUES (%s, %s, %s)", (tag_id, tenant_id, name))
        record_audit(
            self._connection, tenant_id=tenant_id, actor_id=actor_id, action="product_tag.created",
            entity_type="product_tag", entity_id=tag_id, payload={"name": name},
        )
        return Ok(ProductTag(id=tag_id, tenant_id=tenant_id, name=name))

    def list_tags_for_product(self, tenant_id: str, product_id: str) -> list[ProductTag]:
        rows = self._connection.execute(
            """
            SELECT t.id, t.tenant_id, t.name
            FROM core.product_tag_links l
            JOIN core.product_tags t ON t.id = l.tag_id AND t.tenant_id = %s
            WHERE l.product_id = %s
            ORDER BY t.name
            """,
            (tenant_id, product_id),
        ).fetchall()
        return [ProductTag(id=r[0], tenant_id=r[1], name=r[2]) for r in rows]

    def set_product_tags(self, *, tenant_id: str, actor_id: str, product_id: str, tag_ids: list[str]) -> Result[list[ProductTag]]:
        if self.get_product(tenant_id, product_id) is None:
            return Err("NOT_FOUND", f"product {product_id} not found")
        self._connection.execute("DELETE FROM core.product_tag_links WHERE product_id = %s", (product_id,))
        for tag_id in tag_ids:
            self._connection.execute(
                "INSERT INTO core.product_tag_links (product_id, tag_id) VALUES (%s, %s)", (product_id, tag_id)
            )
        record_audit(
            self._connection, tenant_id=tenant_id, actor_id=actor_id, action="product.tags_set",
            entity_type="product", entity_id=product_id, payload={"tag_ids": tag_ids},
        )
        return Ok(self.list_tags_for_product(tenant_id, product_id))

    def list_uoms(self, tenant_id: str) -> list[UnitOfMeasure]:
        rows = self._connection.execute(
            """
            SELECT id, tenant_id, code, name, category, ratio_to_base, symbol, is_integer_only
            FROM core.uoms WHERE tenant_id = %s ORDER BY code
            """,
            (tenant_id,),
        ).fetchall()
        return [
            UnitOfMeasure(
                id=r[0], tenant_id=r[1], code=r[2], name=r[3], category=r[4],
                ratio_to_base=float(r[5]), symbol=r[6], is_integer_only=r[7],
            )
            for r in rows
        ]

    def get_uom(self, tenant_id: str, uom_id: str) -> UnitOfMeasure | None:
        row = self._connection.execute(
            """
            SELECT id, tenant_id, code, name, category, ratio_to_base, symbol, is_integer_only
            FROM core.uoms WHERE id = %s AND tenant_id = %s
            """,
            (uom_id, tenant_id),
        ).fetchone()
        if row is None:
            return None
        return UnitOfMeasure(
            id=row[0], tenant_id=row[1], code=row[2], name=row[3], category=row[4],
            ratio_to_base=float(row[5]), symbol=row[6], is_integer_only=row[7],
        )

    def get_product_uom(self, tenant_id: str, product_id: str) -> UnitOfMeasure | None:
        """The unit a product is tracked in -- one query, not get_product() + get_uom()."""
        row = self._connection.execute(
            """
            SELECT u.id, u.tenant_id, u.code, u.name, u.category, u.ratio_to_base, u.symbol, u.is_integer_only
            FROM core.products p JOIN core.uoms u ON u.id = p.uom_id AND u.tenant_id = p.tenant_id
            WHERE p.id = %s AND p.tenant_id = %s
            """,
            (product_id, tenant_id),
        ).fetchone()
        if row is None:
            return None
        return UnitOfMeasure(
            id=row[0], tenant_id=row[1], code=row[2], name=row[3], category=row[4],
            ratio_to_base=float(row[5]), symbol=row[6], is_integer_only=row[7],
        )

    def get_partner(self, tenant_id: str, partner_id: str) -> Partner | None:
        row = self._connection.execute(
            """
            SELECT id, tenant_id, name, kind, industry, website, phone, email, status
            FROM core.partners
            WHERE id = %s AND tenant_id = %s
            """,
            (partner_id, tenant_id),
        ).fetchone()
        return Partner(*row) if row else None

    def create_partner(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        name: str,
        kind: str,
        industry: str | None = None,
        website: str | None = None,
        phone: str | None = None,
        email: str | None = None,
    ) -> Result[Partner]:
        validation = validate_partner_name(name)
        if isinstance(validation, Err):
            return validation

        partner_id = str(ULID())
        self._connection.execute(
            """
            INSERT INTO core.partners (id, tenant_id, name, kind, industry, website, phone, email, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'active')
            """,
            (partner_id, tenant_id, name, kind, industry, website, phone, email),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="partner.created",
            entity_type="partner",
            entity_id=partner_id,
            payload={"name": name, "kind": kind},
        )
        return Ok(
            Partner(
                id=partner_id,
                tenant_id=tenant_id,
                name=name,
                kind=kind,
                industry=industry,
                website=website,
                phone=phone,
                email=email,
                status="active",
            )
        )

    def list_partners(self, *, tenant_id: str, kind: str | None = None, status: str | None = None) -> list[Partner]:
        clauses = ["tenant_id = %s"]
        params: list[str] = [tenant_id]
        if kind is not None:
            clauses.append("kind = %s")
            params.append(kind)
        if status is not None:
            clauses.append("status = %s")
            params.append(status)

        rows = self._connection.execute(
            f"""
            SELECT id, tenant_id, name, kind, industry, website, phone, email, status
            FROM core.partners
            WHERE {' AND '.join(clauses)}
            ORDER BY created_at DESC
            """,
            params,
        ).fetchall()
        return [Partner(*row) for row in rows]

    def update_partner(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        partner_id: str,
        name: str | None = None,
        kind: str | None = None,
        industry: str | None = None,
        website: str | None = None,
        phone: str | None = None,
        email: str | None = None,
    ) -> Result[Partner]:
        current = self.get_partner(tenant_id, partner_id)
        if current is None:
            return Err("NOT_FOUND", f"partner {partner_id} not found")

        updated = Partner(
            id=current.id,
            tenant_id=current.tenant_id,
            name=name if name is not None else current.name,
            kind=kind if kind is not None else current.kind,
            industry=industry if industry is not None else current.industry,
            website=website if website is not None else current.website,
            phone=phone if phone is not None else current.phone,
            email=email if email is not None else current.email,
            status=current.status,
        )
        validation = validate_partner_name(updated.name)
        if isinstance(validation, Err):
            return validation

        self._connection.execute(
            """
            UPDATE core.partners SET name = %s, kind = %s, industry = %s, website = %s, phone = %s, email = %s
            WHERE id = %s AND tenant_id = %s
            """,
            (updated.name, updated.kind, updated.industry, updated.website, updated.phone, updated.email, partner_id, tenant_id),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="partner.updated",
            entity_type="partner",
            entity_id=partner_id,
            payload={"name": updated.name, "kind": updated.kind, "industry": updated.industry, "website": updated.website, "phone": updated.phone, "email": updated.email},
        )
        return Ok(updated)

    def archive_partner(self, *, tenant_id: str, actor_id: str, partner_id: str) -> Result[Partner]:
        row = self._connection.execute(
            """
            SELECT id, tenant_id, name, kind, industry, website, phone, email, status
            FROM core.partners
            WHERE id = %s AND tenant_id = %s FOR UPDATE
            """,
            (partner_id, tenant_id),
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"partner {partner_id} not found")

        partner = Partner(*row)
        result = transition_partner(partner, "archived")
        if isinstance(result, Err):
            return result

        self._connection.execute("UPDATE core.partners SET status = 'archived' WHERE id = %s", (partner_id,))
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="partner.archived",
            entity_type="partner",
            entity_id=partner_id,
            payload={"name": partner.name},
        )
        return result

    def activate_partner(self, *, tenant_id: str, actor_id: str, partner_id: str) -> Result[Partner]:
        row = self._connection.execute(
            """
            SELECT id, tenant_id, name, kind, industry, website, phone, email, status
            FROM core.partners
            WHERE id = %s AND tenant_id = %s FOR UPDATE
            """,
            (partner_id, tenant_id),
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"partner {partner_id} not found")

        partner = Partner(*row)
        result = transition_partner(partner, "active")
        if isinstance(result, Err):
            return result

        self._connection.execute("UPDATE core.partners SET status = 'active' WHERE id = %s", (partner_id,))
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="partner.activated",
            entity_type="partner",
            entity_id=partner_id,
            payload={"name": partner.name},
        )
        return result

    # --- Partner tags (vendor specialties, sharing core.product_tags) --------------------

    def list_tags_for_partner(self, tenant_id: str, partner_id: str) -> list[PartnerTagLink]:
        rows = self._connection.execute(
            """
            SELECT l.partner_id, l.tag_id, t.name, l.is_preferred, l.lead_time_days, l.min_order_qty
            FROM core.partner_tag_links l
            JOIN core.product_tags t ON t.id = l.tag_id AND t.tenant_id = %s
            WHERE l.partner_id = %s
            ORDER BY t.name
            """,
            (tenant_id, partner_id),
        ).fetchall()
        return [
            PartnerTagLink(
                partner_id=r[0], tag_id=r[1], tag_name=r[2], is_preferred=r[3],
                lead_time_days=r[4], min_order_qty=float(r[5]) if r[5] is not None else None,
            )
            for r in rows
        ]

    def set_partner_tags(self, *, tenant_id: str, actor_id: str, partner_id: str, tag_ids: list[str]) -> Result[list[PartnerTagLink]]:
        if self.get_partner(tenant_id, partner_id) is None:
            return Err("NOT_FOUND", f"partner {partner_id} not found")
        # Only remove tags being unassigned and only insert newly-assigned ones (ON CONFLICT
        # DO NOTHING) rather than delete-all-then-reinsert, so is_preferred/lead_time_days/
        # min_order_qty on tags that stay assigned survive a bulk tag-picker save.
        self._connection.execute(
            "DELETE FROM core.partner_tag_links WHERE partner_id = %s AND tag_id != ALL(%s)", (partner_id, tag_ids)
        )
        for tag_id in tag_ids:
            self._connection.execute(
                """
                INSERT INTO core.partner_tag_links (partner_id, tag_id) VALUES (%s, %s)
                ON CONFLICT (partner_id, tag_id) DO NOTHING
                """,
                (partner_id, tag_id),
            )
        record_audit(
            self._connection, tenant_id=tenant_id, actor_id=actor_id, action="partner.tags_set",
            entity_type="partner", entity_id=partner_id, payload={"tag_ids": tag_ids},
        )
        return Ok(self.list_tags_for_partner(tenant_id, partner_id))

    def update_partner_tag_link(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        partner_id: str,
        tag_id: str,
        is_preferred: bool | None = None,
        lead_time_days: int | None = None,
        min_order_qty: float | None = None,
    ) -> Result[PartnerTagLink]:
        current = self._connection.execute(
            "SELECT is_preferred, lead_time_days, min_order_qty FROM core.partner_tag_links WHERE partner_id = %s AND tag_id = %s",
            (partner_id, tag_id),
        ).fetchone()
        if current is None:
            return Err("NOT_FOUND", f"partner {partner_id} is not tagged with {tag_id}")

        merged_preferred = is_preferred if is_preferred is not None else current[0]
        merged_lead_time = lead_time_days if lead_time_days is not None else current[1]
        merged_min_qty = min_order_qty if min_order_qty is not None else (float(current[2]) if current[2] is not None else None)

        validation = validate_partner_tag_link(lead_time_days=merged_lead_time, min_order_qty=merged_min_qty)
        if isinstance(validation, Err):
            return validation

        self._connection.execute(
            """
            UPDATE core.partner_tag_links SET is_preferred = %s, lead_time_days = %s, min_order_qty = %s
            WHERE partner_id = %s AND tag_id = %s
            """,
            (merged_preferred, merged_lead_time, merged_min_qty, partner_id, tag_id),
        )
        record_audit(
            self._connection, tenant_id=tenant_id, actor_id=actor_id, action="partner.tag_link_updated",
            entity_type="partner", entity_id=partner_id,
            payload={"tag_id": tag_id, "is_preferred": merged_preferred, "lead_time_days": merged_lead_time, "min_order_qty": merged_min_qty},
        )
        tag_name = self._connection.execute("SELECT name FROM core.product_tags WHERE id = %s", (tag_id,)).fetchone()[0]
        return Ok(
            PartnerTagLink(
                partner_id=partner_id, tag_id=tag_id, tag_name=tag_name,
                is_preferred=merged_preferred, lead_time_days=merged_lead_time, min_order_qty=merged_min_qty,
            )
        )

    def list_suggested_vendors_for_product(self, tenant_id: str, product_id: str) -> list[SuggestedVendor]:
        rows = self._connection.execute(
            """
            SELECT DISTINCT p.id, p.name, p.kind, p.industry, p.phone, p.email,
                   ptl.is_preferred, ptl.lead_time_days, ptl.min_order_qty
            FROM core.product_tag_links cptl
            JOIN core.partner_tag_links ptl ON ptl.tag_id = cptl.tag_id
            JOIN core.partners p ON p.id = ptl.partner_id
            WHERE cptl.product_id = %s AND p.tenant_id = %s AND p.kind IN ('supplier', 'both') AND p.status = 'active'
            ORDER BY ptl.is_preferred DESC, ptl.lead_time_days ASC NULLS LAST, p.name
            """,
            (product_id, tenant_id),
        ).fetchall()
        return [
            SuggestedVendor(
                partner_id=r[0], name=r[1], kind=r[2], industry=r[3], phone=r[4], email=r[5],
                is_preferred=r[6], lead_time_days=r[7], min_order_qty=float(r[8]) if r[8] is not None else None,
            )
            for r in rows
        ]

    def list_currencies(self) -> list[Currency]:
        rows = self._connection.execute(
            "SELECT code, name, decimal_places FROM core.currencies ORDER BY code"
        ).fetchall()
        return [Currency(code=code, name=name, decimal_places=decimal_places) for code, name, decimal_places in rows]

    def create_currency(self, *, tenant_id: str, actor_id: str, code: str, name: str, decimal_places: int = 2) -> Result[Currency]:
        validation = validate_new_currency(code=code, name=name, decimal_places=decimal_places)
        if isinstance(validation, Err):
            return validation

        code = code.strip().upper()
        self._connection.execute(
            """
            INSERT INTO core.currencies (code, name, decimal_places)
            VALUES (%s, %s, %s)
            ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name, decimal_places = EXCLUDED.decimal_places
            """,
            (code, name, decimal_places),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="currency.created",
            entity_type="currency",
            entity_id=code,
            payload={"name": name, "decimal_places": decimal_places},
        )
        return Ok(Currency(code=code, name=name, decimal_places=decimal_places))

    def record_exchange_rate(
        self,
        *,
        tenant_id: str,
        currency_code: str,
        rate_to_base: float,
        effective_date: datetime.date,
        source: str = "manual",
        actor_id: str | None = None,
    ) -> Result[ExchangeRate]:
        validation = validate_rate(rate_to_base)
        if isinstance(validation, Err):
            return validation

        rate_id = str(ULID())
        self._connection.execute(
            """
            INSERT INTO core.exchange_rates (id, tenant_id, currency_code, rate_to_base, effective_date, source)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id, currency_code, effective_date)
            DO UPDATE SET rate_to_base = EXCLUDED.rate_to_base, source = EXCLUDED.source
            """,
            (rate_id, tenant_id, currency_code, rate_to_base, effective_date, source),
        )
        if actor_id is not None:
            record_audit(
                self._connection,
                tenant_id=tenant_id,
                actor_id=actor_id,
                action="exchange_rate.recorded",
                entity_type="exchange_rate",
                entity_id=f"{currency_code}:{effective_date.isoformat()}",
                payload={"currency_code": currency_code, "rate_to_base": rate_to_base, "source": source},
            )
        return Ok(
            ExchangeRate(
                id=rate_id,
                tenant_id=tenant_id,
                currency_code=currency_code,
                rate_to_base=rate_to_base,
                effective_date=effective_date.isoformat(),
                source=source,
            )
        )

    def list_exchange_rates(self, *, tenant_id: str, currency_code: str | None = None) -> list[ExchangeRate]:
        clauses = ["tenant_id = %s"]
        params: list[str] = [tenant_id]
        if currency_code is not None:
            clauses.append("currency_code = %s")
            params.append(currency_code)

        rows = self._connection.execute(
            f"""
            SELECT id, tenant_id, currency_code, rate_to_base, effective_date, source
            FROM core.exchange_rates
            WHERE {' AND '.join(clauses)}
            ORDER BY currency_code, effective_date DESC
            """,
            params,
        ).fetchall()
        return [
            ExchangeRate(id=rid, tenant_id=tid, currency_code=code, rate_to_base=float(rate), effective_date=date.isoformat(), source=source)
            for rid, tid, code, rate, date, source in rows
        ]

    def get_exchange_rate(
        self, *, tenant_id: str, currency_code: str, as_of_date: datetime.date
    ) -> ExchangeRate | None:
        if currency_code == BASE_CURRENCY:
            return ExchangeRate(
                id="base",
                tenant_id=tenant_id,
                currency_code=BASE_CURRENCY,
                rate_to_base=1.0,
                effective_date=as_of_date.isoformat(),
                source="base",
            )
        row = self._connection.execute(
            """
            SELECT id, tenant_id, currency_code, rate_to_base, effective_date, source
            FROM core.exchange_rates
            WHERE tenant_id = %s AND currency_code = %s AND effective_date <= %s
            ORDER BY effective_date DESC
            LIMIT 1
            """,
            (tenant_id, currency_code, as_of_date),
        ).fetchone()
        if row is None:
            return None
        rid, tid, code, rate, date, source = row
        return ExchangeRate(id=rid, tenant_id=tid, currency_code=code, rate_to_base=float(rate), effective_date=date.isoformat(), source=source)

    def convert_amount(
        self, *, tenant_id: str, amount: float, currency_code: str, as_of_date: datetime.date
    ) -> Result[tuple[float, float]]:
        rate = self.get_exchange_rate(tenant_id=tenant_id, currency_code=currency_code, as_of_date=as_of_date)
        if rate is None:
            return Err(
                "NO_RATE_AVAILABLE",
                f"no exchange rate for {currency_code} on or before {as_of_date.isoformat()}",
            )
        converted = convert_to_base(amount=amount, currency_code=currency_code, rate_to_base=rate.rate_to_base)
        if isinstance(converted, Err):
            return converted
        return Ok((converted.value, rate.rate_to_base))
