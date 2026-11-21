"""Price lists, customer pricing, sales settings and price resolution.

`resolve_price` is the public read quotes and orders use: the customer's list (or the default list) on the
day, the best quantity break, else the product's catalog price (core.products.selling_price, shared kernel)."""
from __future__ import annotations

import base64
import binascii
import csv
import datetime
import io
from decimal import Decimal, InvalidOperation
from typing import Any

import psycopg
from openpyxl import load_workbook
from ulid import ULID

from core.atomic import atomic
from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from core.tax_codes import TaxCodeService
from modules.sales.domain.pricing import ListWindow, PriceBreak, check_price_list, check_rate, resolve

MAX_IMPORT_BYTES = 5 * 1024 * 1024
DEFAULT_SETTINGS = {"default_vat_rate": Decimal("18"), "max_discount_rate": Decimal("10"), "quote_validity_days": 30}
# The columns of an import/export file: product SKU, minimum quantity, unit price excl. tax.
IMPORT_HEADERS = ("sku", "min_quantity", "unit_price")


class PricingService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    # ---- settings -----------------------------------------------------------------------------

    def get_settings(self, *, tenant_id: str) -> dict[str, Any]:
        row = self._connection.execute(
            "SELECT default_vat_rate, max_discount_rate, quote_validity_days FROM sales.settings WHERE tenant_id = %s", (tenant_id,)
        ).fetchone()
        settings = dict(DEFAULT_SETTINGS) if row is None else {
            "default_vat_rate": row[0], "max_discount_rate": row[1], "quote_validity_days": row[2]}
        # The default VAT rate is the tenant's default sales tax code (core.tax_codes); the stored value is the
        # fallback and what the catalogue adopts the first time it is filled.
        code_rate = TaxCodeService(self._connection).default_rate(
            tenant_id=tenant_id, side="sales", legacy_rate=Decimal(str(settings["default_vat_rate"])))
        if code_rate is not None:
            settings["default_vat_rate"] = code_rate
        return settings

    def update_settings(self, *, tenant_id: str, actor_id: str, default_vat_rate: Decimal | None = None,
                        max_discount_rate: Decimal | None = None, quote_validity_days: int | None = None) -> Result[dict[str, Any]]:
        current = self.get_settings(tenant_id=tenant_id)
        merged = {
            "default_vat_rate": default_vat_rate if default_vat_rate is not None else current["default_vat_rate"],
            "max_discount_rate": max_discount_rate if max_discount_rate is not None else current["max_discount_rate"],
            "quote_validity_days": quote_validity_days if quote_validity_days is not None else current["quote_validity_days"],
        }
        for value, what in ((merged["default_vat_rate"], "vat"), (merged["max_discount_rate"], "discount")):
            checked = check_rate(Decimal(str(value)), what=what)
            if isinstance(checked, Err):
                return checked
        if int(merged["quote_validity_days"]) < 1:
            return Err("INVALID_VALIDITY", "a quote stays valid at least one day", "un devis reste valable au moins un jour")
        self._connection.execute(
            """
            INSERT INTO sales.settings (tenant_id, default_vat_rate, max_discount_rate, quote_validity_days, updated_by, updated_at)
            VALUES (%s, %s, %s, %s, %s, NOW())
            ON CONFLICT (tenant_id) DO UPDATE SET default_vat_rate = EXCLUDED.default_vat_rate,
                max_discount_rate = EXCLUDED.max_discount_rate, quote_validity_days = EXCLUDED.quote_validity_days,
                updated_by = EXCLUDED.updated_by, updated_at = NOW()
            """,
            (tenant_id, merged["default_vat_rate"], merged["max_discount_rate"], merged["quote_validity_days"], actor_id),
        )
        if default_vat_rate is not None:
            made_default = TaxCodeService(self._connection).set_default_rate(
                tenant_id=tenant_id, actor_id=actor_id, side="sales", rate=Decimal(str(merged["default_vat_rate"])))
            if isinstance(made_default, Err):
                return made_default
        record_audit(self._connection, tenant_id=tenant_id, actor_id=actor_id, action="sales_settings.updated",
                     entity_type="sales_settings", entity_id=tenant_id, payload={k: str(v) for k, v in merged.items()})
        return Ok(self.get_settings(tenant_id=tenant_id))

    # ---- price lists --------------------------------------------------------------------------

    def list_price_lists(self, *, tenant_id: str) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            """
            SELECT l.id, l.name, l.valid_from, l.valid_to, l.is_default, l.active, l.note,
                   (SELECT COUNT(*) FROM sales.price_list_items i WHERE i.price_list_id = l.id),
                   (SELECT COUNT(*) FROM sales.customer_pricing c WHERE c.price_list_id = l.id)
            FROM sales.price_lists l WHERE l.tenant_id = %s ORDER BY l.is_default DESC, l.name
            """,
            (tenant_id,),
        ).fetchall()
        return [self._list_row(r) for r in rows]

    @staticmethod
    def _list_row(r) -> dict[str, Any]:
        return {"id": r[0], "name": r[1], "valid_from": r[2], "valid_to": r[3], "is_default": r[4], "active": r[5],
                "note": r[6], "item_count": r[7], "customer_count": r[8]}

    def get_price_list(self, *, tenant_id: str, price_list_id: str) -> Result[dict[str, Any]]:
        row = self._connection.execute(
            """
            SELECT l.id, l.name, l.valid_from, l.valid_to, l.is_default, l.active, l.note,
                   (SELECT COUNT(*) FROM sales.price_list_items i WHERE i.price_list_id = l.id),
                   (SELECT COUNT(*) FROM sales.customer_pricing c WHERE c.price_list_id = l.id)
            FROM sales.price_lists l WHERE l.tenant_id = %s AND l.id = %s
            """,
            (tenant_id, price_list_id),
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", "price list not found", "liste de prix introuvable")
        result = self._list_row(row)
        result["items"] = self.list_items(tenant_id=tenant_id, price_list_id=price_list_id)
        return Ok(result)

    def list_items(self, *, tenant_id: str, price_list_id: str) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            """
            SELECT i.id, i.product_id, p.sku, p.name, i.min_quantity, i.unit_price, p.selling_price
            FROM sales.price_list_items i JOIN core.products p ON p.id = i.product_id
            WHERE i.tenant_id = %s AND i.price_list_id = %s ORDER BY p.name, i.min_quantity
            """,
            (tenant_id, price_list_id),
        ).fetchall()
        return [{"id": r[0], "product_id": r[1], "sku": r[2], "product_name": r[3], "min_quantity": r[4], "unit_price": r[5],
                 "catalog_price": r[6]} for r in rows]

    def save_price_list(self, *, tenant_id: str, actor_id: str, price_list_id: str | None = None, name: str,
                        valid_from: datetime.date | None = None, valid_to: datetime.date | None = None,
                        is_default: bool = False, active: bool = True, note: str | None = None) -> Result[dict[str, Any]]:
        """Creates a list, or updates one when `price_list_id` is given. Making a list the default unsets the
        previous default."""
        checked = check_price_list(name=name, valid_from=valid_from, valid_to=valid_to)
        if isinstance(checked, Err):
            return checked
        name = name.strip()
        clash = self._connection.execute(
            "SELECT id FROM sales.price_lists WHERE tenant_id = %s AND lower(name) = lower(%s) AND id <> COALESCE(%s, '')",
            (tenant_id, name, price_list_id),
        ).fetchone()
        if clash:
            return Err("PRICE_LIST_EXISTS", f"a price list named {name} already exists", f"une liste de prix nommée {name} existe déjà")
        if is_default:
            self._connection.execute(
                "UPDATE sales.price_lists SET is_default = FALSE WHERE tenant_id = %s AND is_default AND id <> COALESCE(%s, '')",
                (tenant_id, price_list_id),
            )
        if price_list_id is None:
            price_list_id = str(ULID())
            self._connection.execute(
                """
                INSERT INTO sales.price_lists (id, tenant_id, name, valid_from, valid_to, is_default, active, note, created_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (price_list_id, tenant_id, name, valid_from, valid_to, is_default, active, note, actor_id),
            )
            action = "price_list.created"
        else:
            updated = self._connection.execute(
                """
                UPDATE sales.price_lists SET name = %s, valid_from = %s, valid_to = %s, is_default = %s, active = %s, note = %s
                WHERE tenant_id = %s AND id = %s
                """,
                (name, valid_from, valid_to, is_default, active, note, tenant_id, price_list_id),
            )
            if updated.rowcount == 0:
                return Err("NOT_FOUND", "price list not found", "liste de prix introuvable")
            action = "price_list.updated"
        record_audit(self._connection, tenant_id=tenant_id, actor_id=actor_id, action=action, entity_type="price_list",
                     entity_id=price_list_id, payload={"name": name, "valid_from": str(valid_from), "valid_to": str(valid_to),
                                                       "is_default": is_default, "active": active})
        return self.get_price_list(tenant_id=tenant_id, price_list_id=price_list_id)

    def delete_price_list(self, *, tenant_id: str, actor_id: str, price_list_id: str) -> Result[None]:
        found = self.get_price_list(tenant_id=tenant_id, price_list_id=price_list_id)
        if isinstance(found, Err):
            return found
        self._connection.execute("DELETE FROM sales.price_lists WHERE tenant_id = %s AND id = %s", (tenant_id, price_list_id))
        record_audit(self._connection, tenant_id=tenant_id, actor_id=actor_id, action="price_list.deleted", entity_type="price_list",
                     entity_id=price_list_id, payload={"name": found.value["name"], "item_count": found.value["item_count"]})
        return Ok(None)

    @atomic
    def replace_items(self, *, tenant_id: str, actor_id: str, price_list_id: str, items: list[dict[str, Any]]) -> Result[dict[str, Any]]:
        """Sets the list's prices to exactly `items` (product_id, min_quantity, unit_price)."""
        found = self.get_price_list(tenant_id=tenant_id, price_list_id=price_list_id)
        if isinstance(found, Err):
            return found
        seen: set[tuple[str, Decimal]] = set()
        clean = []
        for item in items:
            try:
                min_quantity = Decimal(str(item.get("min_quantity") or 1))
                unit_price = Decimal(str(item["unit_price"]))
            except (InvalidOperation, KeyError):
                return Err("INVALID_PRICE", "every price needs a number", "chaque prix doit être un nombre")
            if min_quantity <= 0:
                return Err("INVALID_QUANTITY", "a quantity break starts above zero", "un palier de quantité commence au-dessus de zéro")
            if unit_price < 0:
                return Err("INVALID_PRICE", "a price can't be negative", "un prix ne peut pas être négatif")
            key = (str(item["product_id"]), min_quantity)
            if key in seen:
                return Err("DUPLICATE_PRICE", "a product has the same quantity break twice",
                           "un produit a deux fois le même palier de quantité")
            seen.add(key)
            clean.append((key[0], min_quantity, unit_price))
        known = {r[0] for r in self._connection.execute(
            "SELECT id FROM core.products WHERE tenant_id = %s AND id = ANY(%s)", (tenant_id, [c[0] for c in clean])
        ).fetchall()}
        if any(c[0] not in known for c in clean):
            return Err("NOT_FOUND", "a product of this list doesn't exist", "un produit de cette liste n'existe pas")
        self._connection.execute("DELETE FROM sales.price_list_items WHERE price_list_id = %s", (price_list_id,))
        for product_id, min_quantity, unit_price in clean:
            self._connection.execute(
                "INSERT INTO sales.price_list_items (id, tenant_id, price_list_id, product_id, min_quantity, unit_price) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (str(ULID()), tenant_id, price_list_id, product_id, min_quantity, unit_price),
            )
        record_audit(self._connection, tenant_id=tenant_id, actor_id=actor_id, action="price_list.prices_replaced",
                     entity_type="price_list", entity_id=price_list_id, payload={"item_count": len(clean)})
        return self.get_price_list(tenant_id=tenant_id, price_list_id=price_list_id)

    def import_items(self, *, tenant_id: str, actor_id: str, price_list_id: str, filename: str, content_base64: str,
                     commit: bool) -> Result[dict[str, Any]]:
        """A CSV or XLSX of sku, min_quantity, unit_price replaces the list's prices. `commit=False` previews."""
        try:
            content = base64.b64decode(content_base64, validate=True)
        except (binascii.Error, ValueError):
            return Err("FILE_UNREADABLE", "the file could not be read", "le fichier n'a pas pu être lu")
        if len(content) > MAX_IMPORT_BYTES:
            return Err("FILE_TOO_LARGE", "the file is larger than 5 MB", "le fichier dépasse 5 Mo")
        rows = _read_rows(filename, content)
        if isinstance(rows, Err):
            return rows
        products = {r[0].strip().lower(): r[1] for r in self._connection.execute(
            "SELECT sku, id FROM core.products WHERE tenant_id = %s", (tenant_id,)
        ).fetchall() if r[0]}
        items, errors = [], []
        for number, row in enumerate(rows.value, start=2):
            sku = str(row[0] or "").strip() if row else ""
            if not sku:
                continue
            product_id = products.get(sku.lower())
            if product_id is None:
                errors.append({"row": number, "message": f"unknown SKU {sku}", "message_fr": f"référence inconnue {sku}"})
                continue
            try:
                min_quantity = Decimal(str(row[1] if len(row) > 1 and row[1] not in (None, "") else 1).replace(",", "."))
                unit_price = Decimal(str(row[2]).replace(" ", "").replace(",", "."))
            except (InvalidOperation, IndexError):
                errors.append({"row": number, "message": "quantity and price must be numbers",
                               "message_fr": "la quantité et le prix doivent être des nombres"})
                continue
            items.append({"product_id": product_id, "sku": sku, "min_quantity": min_quantity, "unit_price": unit_price})
        preview = {"items": items, "errors": errors}
        if not commit:
            return Ok(preview)
        if errors:
            return Err("IMPORT_HAS_ERRORS", "fix the rows in error before importing", "corrigez les lignes en erreur avant d'importer")
        replaced = self.replace_items(tenant_id=tenant_id, actor_id=actor_id, price_list_id=price_list_id, items=items)
        if isinstance(replaced, Err):
            return replaced
        return Ok({**preview, "price_list": replaced.value})

    def export_rows(self, *, tenant_id: str, price_list_id: str) -> list[list[Any]]:
        return [[i["sku"], i["product_name"], i["min_quantity"], i["unit_price"]]
                for i in self.list_items(tenant_id=tenant_id, price_list_id=price_list_id)]

    # ---- customers ----------------------------------------------------------------------------

    def get_customer_pricing(self, *, tenant_id: str, partner_id: str) -> dict[str, Any]:
        row = self._connection.execute(
            "SELECT c.price_list_id, l.name, c.discount_rate FROM sales.customer_pricing c "
            "LEFT JOIN sales.price_lists l ON l.id = c.price_list_id WHERE c.tenant_id = %s AND c.partner_id = %s",
            (tenant_id, partner_id),
        ).fetchone()
        if row is None:
            return {"partner_id": partner_id, "price_list_id": None, "price_list_name": None, "discount_rate": Decimal("0")}
        return {"partner_id": partner_id, "price_list_id": row[0], "price_list_name": row[1], "discount_rate": row[2]}

    def list_customer_pricing(self, *, tenant_id: str) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            """
            SELECT c.partner_id, p.name, c.price_list_id, l.name, c.discount_rate
            FROM sales.customer_pricing c JOIN core.partners p ON p.id = c.partner_id
            LEFT JOIN sales.price_lists l ON l.id = c.price_list_id
            WHERE c.tenant_id = %s ORDER BY p.name
            """,
            (tenant_id,),
        ).fetchall()
        return [{"partner_id": r[0], "partner_name": r[1], "price_list_id": r[2], "price_list_name": r[3], "discount_rate": r[4]}
                for r in rows]

    def set_customer_pricing(self, *, tenant_id: str, actor_id: str, partner_id: str, price_list_id: str | None,
                             discount_rate: Decimal) -> Result[dict[str, Any]]:
        checked = check_rate(discount_rate, what="discount")
        if isinstance(checked, Err):
            return checked
        if not self._connection.execute("SELECT 1 FROM core.partners WHERE tenant_id = %s AND id = %s", (tenant_id, partner_id)).fetchone():
            return Err("NOT_FOUND", "customer not found", "client introuvable")
        if price_list_id and isinstance(self.get_price_list(tenant_id=tenant_id, price_list_id=price_list_id), Err):
            return Err("NOT_FOUND", "price list not found", "liste de prix introuvable")
        self._connection.execute(
            """
            INSERT INTO sales.customer_pricing (tenant_id, partner_id, price_list_id, discount_rate, updated_by, updated_at)
            VALUES (%s, %s, %s, %s, %s, NOW())
            ON CONFLICT (tenant_id, partner_id) DO UPDATE SET price_list_id = EXCLUDED.price_list_id,
                discount_rate = EXCLUDED.discount_rate, updated_by = EXCLUDED.updated_by, updated_at = NOW()
            """,
            (tenant_id, partner_id, price_list_id, discount_rate, actor_id),
        )
        record_audit(self._connection, tenant_id=tenant_id, actor_id=actor_id, action="customer_pricing.updated",
                     entity_type="partner", entity_id=partner_id,
                     payload={"price_list_id": price_list_id, "discount_rate": str(discount_rate)})
        return Ok(self.get_customer_pricing(tenant_id=tenant_id, partner_id=partner_id))

    # ---- resolution ---------------------------------------------------------------------------

    def resolve_price(self, *, tenant_id: str, partner_id: str | None, product_id: str, quantity: Decimal,
                      on: datetime.date | None = None) -> Result[dict[str, Any]]:
        """The price of `quantity` of a product for a customer on a day, and the customer's standing discount."""
        resolved = self.resolve_prices(tenant_id=tenant_id, partner_id=partner_id, items=[(product_id, quantity)], on=on)
        if isinstance(resolved, Err):
            return resolved
        return Ok(resolved.value[0])

    def resolve_prices(self, *, tenant_id: str, partner_id: str | None, items: list[tuple[str, Decimal]],
                       on: datetime.date | None = None) -> Result[list[dict[str, Any]]]:
        """Several products at once: one read of the lists, one of the catalog."""
        on = on or datetime.date.today()
        product_ids = list({product_id for product_id, _ in items})
        catalog = {r[0]: Decimal(str(r[1] or 0)) for r in self._connection.execute(
            "SELECT id, selling_price FROM core.products WHERE tenant_id = %s AND id = ANY(%s)", (tenant_id, product_ids)
        ).fetchall()}
        missing = [p for p in product_ids if p not in catalog]
        if missing:
            return Err("NOT_FOUND", f"product {missing[0]} not found", f"produit {missing[0]} introuvable")
        customer = self.get_customer_pricing(tenant_id=tenant_id, partner_id=partner_id) if partner_id else None
        windows = {r[0]: ListWindow(r[0], r[1], r[2], r[3], r[4]) for r in self._connection.execute(
            "SELECT id, name, valid_from, valid_to, active FROM sales.price_lists WHERE tenant_id = %s", (tenant_id,)
        ).fetchall()}
        default_id = next((r[0] for r in self._connection.execute(
            "SELECT id FROM sales.price_lists WHERE tenant_id = %s AND is_default", (tenant_id,)
        ).fetchall()), None)
        by_product: dict[str, list[PriceBreak]] = {}
        for row in self._connection.execute(
            "SELECT price_list_id, min_quantity, unit_price, product_id FROM sales.price_list_items "
            "WHERE tenant_id = %s AND product_id = ANY(%s)", (tenant_id, product_ids)
        ).fetchall():
            by_product.setdefault(row[3], []).append(PriceBreak(row[0], Decimal(str(row[1])), Decimal(str(row[2]))))
        customer_list = windows.get(customer["price_list_id"]) if customer and customer["price_list_id"] else None
        discount = Decimal(str(customer["discount_rate"])) if customer else Decimal("0")
        result = []
        for product_id, quantity in items:
            price = resolve(quantity=Decimal(str(quantity)), on=on, customer_list=customer_list,
                            default_list=windows.get(default_id) if default_id else None,
                            breaks=by_product.get(product_id, []), catalog_price=catalog[product_id], customer_discount=discount)
            result.append({"product_id": product_id, "quantity": Decimal(str(quantity)), **price.as_dict()})
        return Ok(result)


def _read_rows(filename: str, content: bytes) -> Result[list[list[Any]]]:
    """The data rows of a CSV/TXT or XLSX file, header row dropped."""
    lower = filename.lower()
    try:
        if lower.endswith(".xlsx"):
            sheet = load_workbook(io.BytesIO(content), read_only=True, data_only=True).active
            rows = [list(row) for row in sheet.iter_rows(values_only=True)]
        elif lower.endswith((".csv", ".txt")):
            text = content.decode("utf-8-sig", errors="replace")
            dialect = csv.Sniffer().sniff(text.splitlines()[0] if text else ",", delimiters=",;\t")
            rows = [row for row in csv.reader(io.StringIO(text), dialect)]
        else:
            return Err("UNSUPPORTED_FILE", "use a .csv or .xlsx file", "utilisez un fichier .csv ou .xlsx")
    except Exception:  # noqa: BLE001 -- any parse failure is the user's file, not ours
        return Err("FILE_UNREADABLE", "the file could not be read", "le fichier n'a pas pu être lu")
    return Ok(rows[1:])
