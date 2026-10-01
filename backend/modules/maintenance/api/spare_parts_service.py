"""Spare parts: where they are kept, and what each checkpoint needs.

A supervisor names the warehouse location spare parts live in; every location
under it (shelves, bins) counts as part of it, blocked ones (quarantine) aside.
The map editor offers the products kept there -- by default location or by stock
on hand -- and a checkpoint lists the parts its work needs, in each product's own
unit. A job's check shows those parts with what that location has available,
shelf by shelf, and the parts approval puts that location first.

Locations and stock are read only through the warehouse's public services;
products and units come from the shared kernel.
"""
from __future__ import annotations

import math
from decimal import Decimal, InvalidOperation

import psycopg

from core.api.service import CoreService
from core.audit import record_audit
from core.domain.entities import validate_quantity_for_uom
from core.domain.result import Err, Ok, Result
from modules.warehouse.api.location_service import LocationService
from modules.warehouse.api.service import StockService

__all__ = ["SparePartsService", "checkpoint_parts", "save_checkpoint_parts", "validate_parts"]

_PATH_SEPARATOR = " › "
_ZERO = Decimal(0)


def _decimal(value: object) -> Decimal | None:
    """A finite number as an exact Decimal (through its shortest text, so 0.1 stays 0.1); None otherwise."""
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


# ---- parts on a checkpoint -----------------------------------------------------------


def validate_parts(connection: psycopg.Connection, tenant_id: str, parts: list[dict]) -> Result[list[tuple[str, Decimal]]]:
    """`parts` are `{product_id, quantity}` in the product's own unit: a known product,
    listed once, a positive quantity, whole for a whole-count unit. Returns
    `(product_id, quantity)` pairs in the given order."""
    core = CoreService(connection)
    checked: list[tuple[str, Decimal]] = []
    seen: set[str] = set()
    for part in parts:
        product_id = part.get("product_id") or ""
        if product_id in seen:
            return Err("DUPLICATE_PART", "a part is listed once per checkpoint", "une pièce n'est listée qu'une fois par point")
        seen.add(product_id)
        quantity = _decimal(part.get("quantity"))
        if quantity is None or quantity <= _ZERO:
            return Err("INVALID_QUANTITY", "every quantity must be positive", "chaque quantité doit être positive")
        uom = core.get_product_uom(tenant_id, product_id)
        if uom is None:
            return Err("UNKNOWN_PRODUCT", f"product {product_id} not found", f"article {product_id} introuvable")
        whole = validate_quantity_for_uom(float(quantity), uom)
        if isinstance(whole, Err):
            return whole
        checked.append((product_id, quantity))
    return Ok(checked)


def save_checkpoint_parts(
    connection: psycopg.Connection, tenant_id: str, checkpoint_id: str, parts: list[tuple[str, Decimal]]
) -> None:
    """Replaces the checkpoint's parts with `parts` (already validated)."""
    connection.execute("DELETE FROM maintenance.checkpoint_parts WHERE checkpoint_id = %s", (checkpoint_id,))
    for sort_order, (product_id, quantity) in enumerate(parts):
        connection.execute(
            """
            INSERT INTO maintenance.checkpoint_parts (checkpoint_id, tenant_id, product_id, quantity, sort_order)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (checkpoint_id, tenant_id, product_id, quantity, sort_order),
        )


def checkpoint_parts(connection: psycopg.Connection, tenant_id: str, checkpoint_ids: list[str]) -> dict[str, list[dict]]:
    """Each checkpoint's parts, in the order they were listed."""
    if not checkpoint_ids:
        return {}
    rows = connection.execute(
        """
        SELECT cp.checkpoint_id, p.id, p.name, p.sku, u.id, u.code, cp.quantity
        FROM maintenance.checkpoint_parts cp
        JOIN core.products p ON p.id = cp.product_id AND p.tenant_id = cp.tenant_id
        JOIN core.uoms u ON u.id = p.uom_id AND u.tenant_id = p.tenant_id
        WHERE cp.tenant_id = %s AND cp.checkpoint_id = ANY(%s)
        ORDER BY cp.checkpoint_id, cp.sort_order
        """,
        (tenant_id, list(checkpoint_ids)),
    ).fetchall()
    found: dict[str, list[dict]] = {}
    for checkpoint_id, product_id, name, sku, uom_id, uom_code, quantity in rows:
        found.setdefault(checkpoint_id, []).append(
            {
                "product_id": product_id,
                "product_name": name,
                "sku": sku,
                "uom_id": uom_id,
                "uom_code": uom_code,
                "quantity": float(quantity),
            }
        )
    return found


# ---- the spare-parts location ----------------------------------------------------------


class SparePartsService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def settings(self, tenant_id: str) -> dict:
        location_id = self._location_id(tenant_id)
        name = None
        if location_id is not None:
            found = LocationService(self._connection).get_locations_by_ids(tenant_id=tenant_id, location_ids=[location_id])
            name = found[0].name if found else None
        return {"spare_parts_location_id": location_id, "spare_parts_location_name": name}

    def set_location(self, *, tenant_id: str, actor_id: str, location_id: str | None) -> Result[dict]:
        """Names the location spare parts are kept in; None clears it. A blocked
        location (quarantine) cannot hold parts anyone may take, so it is refused."""
        if location_id is not None:
            found = LocationService(self._connection).get_locations_by_ids(tenant_id=tenant_id, location_ids=[location_id])
            if not found or found[0].is_blocked:
                return Err(
                    "UNKNOWN_LOCATION",
                    f"location {location_id} not found or blocked",
                    f"emplacement {location_id} introuvable ou bloqué",
                )
        self._connection.execute(
            """
            INSERT INTO maintenance.settings (tenant_id, spare_parts_location_id, updated_by, updated_at)
            VALUES (%s, %s, %s, NOW())
            ON CONFLICT (tenant_id) DO UPDATE
            SET spare_parts_location_id = EXCLUDED.spare_parts_location_id,
                updated_by = EXCLUDED.updated_by,
                updated_at = EXCLUDED.updated_at
            """,
            (tenant_id, location_id, actor_id),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="maintenance_settings.updated",
            entity_type="maintenance_settings",
            entity_id=tenant_id,
            payload={"spare_parts_location_id": location_id},
        )
        return Ok(self.settings(tenant_id))

    def location_options(self, tenant_id: str) -> list[dict]:
        """Every unblocked location, labelled with its path ("Magasin › Étagère B"), by that label."""
        locations = LocationService(self._connection).list_locations(tenant_id=tenant_id)
        by_id = {location.id: location for location in locations}

        def path(location_id: str) -> str:
            names: list[str] = []
            seen: set[str] = set()
            current = by_id.get(location_id)
            while current is not None and current.id not in seen:
                seen.add(current.id)
                names.append(current.name)
                current = by_id.get(current.parent_location_id) if current.parent_location_id else None
            return _PATH_SEPARATOR.join(reversed(names))

        options = [
            {"id": location.id, "code": location.code, "name": location.name, "label": path(location.id)}
            for location in locations
            if not location.is_blocked
        ]
        options.sort(key=lambda option: (option["label"].casefold(), option["id"]))
        return options

    def spare_locations(self, tenant_id: str) -> dict[str, str]:
        """The chosen location and every unblocked location under it, each with its
        label from the chosen one down ("Pièces de rechange › Étagère B"). Empty when
        no location is chosen or it no longer exists."""
        root_id = self._location_id(tenant_id)
        if root_id is None:
            return {}
        locations = LocationService(self._connection).list_locations(tenant_id=tenant_id)
        root = next((location for location in locations if location.id == root_id), None)
        if root is None or root.is_blocked:
            return {}
        children: dict[str, list] = {}
        for location in locations:
            if location.parent_location_id is not None:
                children.setdefault(location.parent_location_id, []).append(location)

        labels = {root.id: root.name}
        pending = [root]
        while pending:
            parent = pending.pop()
            for child in children.get(parent.id, []):
                if child.is_blocked or child.id in labels:
                    continue
                labels[child.id] = f"{labels[parent.id]}{_PATH_SEPARATOR}{child.name}"
                pending.append(child)
        return labels

    def stock_by_product(self, tenant_id: str, spare: dict[str, str] | None = None) -> dict[str, list[dict]]:
        """Per product, each spare-parts location with something available
        (`on hand - reserved`), by label."""
        spare = self.spare_locations(tenant_id) if spare is None else spare
        stock = StockService(self._connection)
        found: dict[str, list[dict]] = {}
        for location_id, label in spare.items():
            for level in stock.list_stock_items(tenant_id, location_id=location_id):
                # Each side through its own text, so float noise from the subtraction never shows.
                available = (_decimal(level.quantity_on_hand) or _ZERO) - (_decimal(level.quantity_reserved) or _ZERO)
                if available > _ZERO:
                    found.setdefault(level.product_id, []).append(
                        {"location_id": location_id, "location_name": label, "available": float(available)}
                    )
        for entries in found.values():
            entries.sort(key=lambda entry: (entry["location_name"].casefold(), entry["location_id"]))
        return found

    def catalog(self, tenant_id: str) -> dict:
        """What the map editor offers: products whose default location is a
        spare-parts location, or with stock available in one, by name."""
        settings = self.settings(tenant_id)
        empty = {"location_id": None, "location_name": None, "products": []}
        if settings["spare_parts_location_id"] is None:
            return empty
        spare = self.spare_locations(tenant_id)
        if not spare:
            return empty
        stock = self.stock_by_product(tenant_id, spare)
        rows = self._connection.execute(
            """
            SELECT p.id, p.name, p.sku, u.id, u.code, u.is_integer_only
            FROM core.products p
            JOIN core.uoms u ON u.id = p.uom_id AND u.tenant_id = p.tenant_id
            WHERE p.tenant_id = %s AND (p.id = ANY(%s) OR p.default_location_id = ANY(%s))
            ORDER BY p.name, p.id
            """,
            (tenant_id, list(stock), list(spare)),
        ).fetchall()
        products = []
        for product_id, name, sku, uom_id, uom_code, integer_only in rows:
            locations = stock.get(product_id, [])
            products.append(
                {
                    "product_id": product_id,
                    "name": name,
                    "sku": sku,
                    "uom_id": uom_id,
                    "uom_code": uom_code,
                    "uom_integer_only": integer_only,
                    "available": float(sum((Decimal(str(entry["available"])) for entry in locations), _ZERO)),
                    "locations": locations,
                }
            )
        return {
            "location_id": settings["spare_parts_location_id"],
            "location_name": settings["spare_parts_location_name"],
            "products": products,
        }

    def request_products(self, tenant_id: str) -> list[dict]:
        """Every product a parts request may name, with its unit, the spare parts
        (the catalog's products) first, then by name. The request form reads this
        rather than the core product list, which a technician has no right to."""
        spare_ids = {product["product_id"] for product in self.catalog(tenant_id)["products"]}
        rows = self._connection.execute(
            """
            SELECT p.id, p.name, p.sku, u.id, u.code, u.is_integer_only
            FROM core.products p
            JOIN core.uoms u ON u.id = p.uom_id AND u.tenant_id = p.tenant_id
            WHERE p.tenant_id = %s
            """,
            (tenant_id,),
        ).fetchall()
        products = [
            {
                "product_id": product_id,
                "name": name,
                "sku": sku,
                "uom_id": uom_id,
                "uom_code": uom_code,
                "uom_integer_only": integer_only,
                "in_spare_parts": product_id in spare_ids,
            }
            for product_id, name, sku, uom_id, uom_code, integer_only in rows
        ]
        products.sort(key=lambda product: (not product["in_spare_parts"], product["name"].casefold(), product["product_id"]))
        return products

    def parts_with_stock(self, tenant_id: str, checkpoint_ids: list[str]) -> dict[str, list[dict]]:
        """Each checkpoint's parts, with what the spare-parts location has available
        in total and shelf by shelf."""
        parts = checkpoint_parts(self._connection, tenant_id, checkpoint_ids)
        if not parts:
            return {}
        stock = self.stock_by_product(tenant_id)
        result: dict[str, list[dict]] = {}
        for checkpoint_id, listed in parts.items():
            result[checkpoint_id] = []
            for part in listed:
                locations = stock.get(part["product_id"], [])
                total = sum((Decimal(str(entry["available"])) for entry in locations), _ZERO)
                result[checkpoint_id].append({**part, "available": float(total), "locations": locations})
        return result

    def _location_id(self, tenant_id: str) -> str | None:
        row = self._connection.execute(
            "SELECT spare_parts_location_id FROM maintenance.settings WHERE tenant_id = %s", (tenant_id,)
        ).fetchone()
        return row[0] if row is not None else None
