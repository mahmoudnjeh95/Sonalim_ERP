from __future__ import annotations

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.warehouse.domain.barcode import (
    Gs1Data,
    ProductBarcode,
    is_valid_gtin,
    looks_like_gs1,
    normalize_gtin,
    parse_gs1,
    validate_barcode,
)

_COLUMNS = "id, tenant_id, product_id, barcode, barcode_type, units_per_scan, label, created_by, created_at"


def _from_row(row) -> ProductBarcode:
    return ProductBarcode(
        id=row[0], tenant_id=row[1], product_id=row[2], barcode=row[3], barcode_type=row[4],
        units_per_scan=float(row[5]), label=row[6], created_by=row[7], created_at=row[8],
    )


def _duplicate(barcode: str) -> Err:
    return Err("DUPLICATE_BARCODE", f"barcode {barcode} is already assigned", f"le code-barres {barcode} est déjà attribué")


class BarcodeService:
    """Product barcodes, and the one place a raw scan is turned into what it
    means -- so every scanning screen resolves a read the same way instead of
    each matching SKUs and location codes on its own."""

    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def list_barcodes(self, *, tenant_id: str, product_id: str | None = None) -> list[ProductBarcode]:
        clauses = ["tenant_id = %s"]
        params: list[object] = [tenant_id]
        if product_id is not None:
            clauses.append("product_id = %s")
            params.append(product_id)
        rows = self._connection.execute(
            f"SELECT {_COLUMNS} FROM warehouse.product_barcodes WHERE {' AND '.join(clauses)} ORDER BY product_id, units_per_scan",
            params,
        ).fetchall()
        return [_from_row(row) for row in rows]

    def _get(self, *, tenant_id: str, barcode_id: str) -> Result[ProductBarcode]:
        row = self._connection.execute(
            f"SELECT {_COLUMNS} FROM warehouse.product_barcodes WHERE id = %s AND tenant_id = %s FOR UPDATE",
            (barcode_id, tenant_id),
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"barcode {barcode_id} not found", f"code-barres {barcode_id} introuvable")
        return Ok(_from_row(row))

    def _taken(self, *, tenant_id: str, barcode: str, except_id: str | None = None) -> bool:
        row = self._connection.execute(
            "SELECT id FROM warehouse.product_barcodes WHERE tenant_id = %s AND barcode = %s", (tenant_id, barcode)
        ).fetchone()
        return row is not None and row[0] != except_id

    def create_barcode(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        product_id: str,
        barcode: str,
        barcode_type: str,
        units_per_scan: float = 1,
        label: str | None = None,
    ) -> Result[ProductBarcode]:
        validated = validate_barcode(barcode=barcode, barcode_type=barcode_type, units_per_scan=units_per_scan)
        if isinstance(validated, Err):
            return validated
        product = self._connection.execute(
            "SELECT 1 FROM core.products WHERE id = %s AND tenant_id = %s", (product_id, tenant_id)
        ).fetchone()
        if product is None:
            return Err("NOT_FOUND", f"product {product_id} not found", f"produit {product_id} introuvable")
        if self._taken(tenant_id=tenant_id, barcode=validated.value):
            return _duplicate(validated.value)

        barcode_id = str(ULID())
        self._connection.execute(
            """
            INSERT INTO warehouse.product_barcodes (id, tenant_id, product_id, barcode, barcode_type, units_per_scan, label, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (barcode_id, tenant_id, product_id, validated.value, barcode_type, units_per_scan, label, actor_id),
        )
        record_audit(
            self._connection, tenant_id=tenant_id, actor_id=actor_id, action="product_barcode.created",
            entity_type="product_barcode", entity_id=barcode_id,
            payload={"product_id": product_id, "barcode": validated.value, "barcode_type": barcode_type, "units_per_scan": units_per_scan},
        )
        return self._get(tenant_id=tenant_id, barcode_id=barcode_id)

    def update_barcode(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        barcode_id: str,
        barcode: str | None = None,
        barcode_type: str | None = None,
        units_per_scan: float | None = None,
        label: str | None = None,
    ) -> Result[ProductBarcode]:
        current = self._get(tenant_id=tenant_id, barcode_id=barcode_id)
        if isinstance(current, Err):
            return current
        updated_type = barcode_type if barcode_type is not None else current.value.barcode_type
        updated_units = units_per_scan if units_per_scan is not None else current.value.units_per_scan
        updated_label = label if label is not None else current.value.label
        validated = validate_barcode(
            barcode=barcode if barcode is not None else current.value.barcode,
            barcode_type=updated_type,
            units_per_scan=updated_units,
        )
        if isinstance(validated, Err):
            return validated
        if self._taken(tenant_id=tenant_id, barcode=validated.value, except_id=barcode_id):
            return _duplicate(validated.value)

        self._connection.execute(
            """
            UPDATE warehouse.product_barcodes SET barcode = %s, barcode_type = %s, units_per_scan = %s, label = %s
            WHERE id = %s AND tenant_id = %s
            """,
            (validated.value, updated_type, updated_units, updated_label, barcode_id, tenant_id),
        )
        changes = {
            key: value
            for key, value in {"barcode": barcode, "barcode_type": barcode_type, "units_per_scan": units_per_scan, "label": label}.items()
            if value is not None
        }
        record_audit(
            self._connection, tenant_id=tenant_id, actor_id=actor_id, action="product_barcode.updated",
            entity_type="product_barcode", entity_id=barcode_id, payload=changes,
        )
        return self._get(tenant_id=tenant_id, barcode_id=barcode_id)

    def delete_barcode(self, *, tenant_id: str, actor_id: str, barcode_id: str) -> Result[None]:
        current = self._get(tenant_id=tenant_id, barcode_id=barcode_id)
        if isinstance(current, Err):
            return current
        self._connection.execute("DELETE FROM warehouse.product_barcodes WHERE id = %s AND tenant_id = %s", (barcode_id, tenant_id))
        record_audit(
            self._connection, tenant_id=tenant_id, actor_id=actor_id, action="product_barcode.deleted",
            entity_type="product_barcode", entity_id=barcode_id,
            payload={"product_id": current.value.product_id, "barcode": current.value.barcode},
        )
        return Ok(None)

    # --- Scan resolution --------------------------------------------------------------

    def _barcode_row(self, tenant_id: str, barcode: str):
        return self._connection.execute(
            "SELECT product_id, units_per_scan FROM warehouse.product_barcodes WHERE tenant_id = %s AND barcode = %s",
            (tenant_id, barcode),
        ).fetchone()

    def _resolve_gs1(self, tenant_id: str, code: str, gs1: Gs1Data) -> dict | None:
        if gs1.gtin is None:
            return None
        row = self._barcode_row(tenant_id, normalize_gtin(gs1.gtin))
        if row is None:
            return None
        product_id, units_per_scan = row[0], float(row[1])
        lot_id = None
        if gs1.lot_number:
            lot_row = self._connection.execute(
                "SELECT id FROM warehouse.lots WHERE tenant_id = %s AND product_id = %s AND lot_number = %s",
                (tenant_id, product_id, gs1.lot_number),
            ).fetchone()
            lot_id = lot_row[0] if lot_row else None
        # AI 37 counts trade items inside a logistic unit; each is one
        # units_per_scan worth of the product.
        quantity = units_per_scan * gs1.count if gs1.count is not None else units_per_scan
        return {
            "code": code, "kind": "product", "matched_by": "gs1", "product_id": product_id, "quantity": quantity,
            "lot_number": gs1.lot_number, "lot_id": lot_id,
            "expiry_date": gs1.expiry_date.isoformat() if gs1.expiry_date else None,
        }

    def resolve(self, *, tenant_id: str, code: str) -> dict:
        """What a scan means, in priority order: a GS1-128 label, a registered
        barcode (a bare GTIN compared at 14 digits), a product SKU, a location
        code, then a lot number. Always returns a result -- "unknown" is an
        answer, not an error, since scanning something unregistered is normal."""
        value = code.strip()
        unknown = {"code": value, "kind": "unknown"}
        if not value:
            return unknown

        if looks_like_gs1(value) or (value.isdigit() and len(value) > 14 and value.startswith(("01", "02"))):
            gs1 = parse_gs1(value)
            if gs1 is not None:
                resolved = self._resolve_gs1(tenant_id, value, gs1)
                if resolved is not None:
                    return resolved

        lookup = normalize_gtin(value) if is_valid_gtin(value) else value
        row = self._barcode_row(tenant_id, lookup)
        if row is not None:
            return {"code": value, "kind": "product", "matched_by": "barcode", "product_id": row[0], "quantity": float(row[1])}

        # Product SKUs are shared-kernel data, so reading core.products is allowed.
        product = self._connection.execute(
            "SELECT id FROM core.products WHERE tenant_id = %s AND LOWER(sku) = LOWER(%s)", (tenant_id, value)
        ).fetchone()
        if product is not None:
            return {"code": value, "kind": "product", "matched_by": "sku", "product_id": product[0], "quantity": 1.0}

        location = self._connection.execute(
            "SELECT id FROM warehouse.locations WHERE tenant_id = %s AND LOWER(code) = LOWER(%s)", (tenant_id, value)
        ).fetchone()
        if location is not None:
            return {"code": value, "kind": "location", "matched_by": "location_code", "location_id": location[0]}

        lots = self._connection.execute(
            "SELECT id, product_id FROM warehouse.lots WHERE tenant_id = %s AND lot_number = %s", (tenant_id, value)
        ).fetchall()
        # A lot number is only unique per product; an ambiguous one isn't an answer.
        if len(lots) == 1:
            return {"code": value, "kind": "lot", "matched_by": "lot_number", "lot_id": lots[0][0], "product_id": lots[0][1]}

        return unknown
