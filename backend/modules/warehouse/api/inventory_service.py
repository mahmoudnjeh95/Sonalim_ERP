from __future__ import annotations

from decimal import Decimal
from typing import Any

import psycopg
from ulid import ULID

from core.atomic import atomic
from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from core.events.outbox import publish_event
from modules.warehouse.api.service import StockService
from modules.warehouse.domain.inventory import resolve_count
from modules.warehouse.domain.voucher_rules import PREFIX

INVENTORY_COLUMNS = "id, number, location_id, type, status, note, opened_by, opened_at, closed_by, closed_at"
INVENTORY_KEYS = ["id", "number", "location_id", "type", "status", "note", "opened_by", "opened_at", "closed_by", "closed_at"]
LINE_COLUMNS = "l.id, l.product_id, p.sku, p.name, l.theoretical_qty, l.count_1, l.count_2, l.count_3, l.final_qty, l.variance, l.observation"
LINE_KEYS = ["id", "product_id", "sku", "name", "theoretical_qty", "count_1", "count_2", "count_3", "final_qty", "variance", "observation"]


def _not_found(inventory_id: str) -> Err:
    return Err("NOT_FOUND", f"inventory {inventory_id} not found", f"inventaire {inventory_id} introuvable")


class InventoryService:
    """Physical inventory. A full one freezes its location until it is closed (StockService refuses
    every other posting there); an interim one counts without freezing or adjusting. Callers commit."""

    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    # ---- reads ------------------------------------------------------------------------------

    def get(self, *, tenant_id: str, inventory_id: str) -> Result[dict[str, Any]]:
        row = self._connection.execute(
            f"SELECT {INVENTORY_COLUMNS} FROM warehouse.inventories WHERE id = %s AND tenant_id = %s", (inventory_id, tenant_id)
        ).fetchone()
        if row is None:
            return _not_found(inventory_id)
        inventory = dict(zip(INVENTORY_KEYS, row, strict=True))
        inventory["lines"] = self._lines(inventory_id)
        return Ok(inventory)

    def list(self, *, tenant_id: str, status: str | None = None, location_id: str | None = None) -> list[dict[str, Any]]:
        clauses, params = ["tenant_id = %s"], [tenant_id]
        for column, value in (("status", status), ("location_id", location_id)):
            if value:
                clauses.append(f"{column} = %s")
                params.append(value)
        rows = self._connection.execute(
            f"SELECT {INVENTORY_COLUMNS} FROM warehouse.inventories WHERE {' AND '.join(clauses)} ORDER BY opened_at DESC, id DESC", params
        ).fetchall()
        return [dict(zip(INVENTORY_KEYS, r, strict=True)) for r in rows]

    def blank_sheet(self, *, tenant_id: str, inventory_id: str) -> Result[dict[str, Any]]:
        """The sheet people carry onto the floor: products and theoretical quantities, counts empty."""
        inventory = self.get(tenant_id=tenant_id, inventory_id=inventory_id)
        if isinstance(inventory, Err):
            return inventory
        value = inventory.value
        value["lines"] = [
            {**line, "count_1": None, "count_2": None, "count_3": None, "final_qty": None, "variance": None, "observation": None}
            for line in value["lines"]
        ]
        return Ok(value)

    # ---- lifecycle --------------------------------------------------------------------------

    def open(self, *, tenant_id: str, actor_id: str, location_id: str, type: str = "full", note: str | None = None) -> Result[dict[str, Any]]:
        if type not in ("full", "interim"):
            return Err("INVALID_INVENTORY_TYPE", f"unknown inventory type {type}", f"type d'inventaire inconnu {type}")
        if self._connection.execute(
            "SELECT 1 FROM warehouse.locations WHERE id = %s AND tenant_id = %s", (location_id, tenant_id)
        ).fetchone() is None:
            return Err("NOT_FOUND", f"location {location_id} not found", f"emplacement {location_id} introuvable")
        if type == "full" and self._open_full(tenant_id, location_id):
            return Err("INVENTORY_ALREADY_OPEN", "this location already has an open full inventory",
                       "cet emplacement a déjà un inventaire complet ouvert")

        inventory_id = str(ULID())
        number = self._next_number(tenant_id)
        self._connection.execute(
            "INSERT INTO warehouse.inventories (id, tenant_id, number, location_id, type, note, opened_by) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (inventory_id, tenant_id, number, location_id, type, note, actor_id),
        )
        # Snapshot the books now. For a full inventory the location is frozen from this moment, so the
        # snapshot cannot drift; an interim one compares counts against the books as they were opened.
        self._connection.execute(
            """
            INSERT INTO warehouse.inventory_lines (id, tenant_id, inventory_id, product_id, theoretical_qty)
            SELECT gen_random_uuid()::text, tenant_id, %s, product_id, quantity_on_hand
            FROM warehouse.stock_items WHERE tenant_id = %s AND location_id = %s
            """,
            (inventory_id, tenant_id, location_id),
        )
        record_audit(self._connection, tenant_id=tenant_id, actor_id=actor_id, action="warehouse.inventory.opened",
                     entity_type="inventory", entity_id=inventory_id, payload={"number": number, "type": type, "location_id": location_id})
        return self.get(tenant_id=tenant_id, inventory_id=inventory_id)

    def add_line(self, *, tenant_id: str, actor_id: str, inventory_id: str, product_id: str) -> Result[dict[str, Any]]:
        """A product found on the shelf that the books do not list there: theoretical zero."""
        locked = self._lock_open(tenant_id, inventory_id)
        if isinstance(locked, Err):
            return locked
        if self._connection.execute(
            "SELECT 1 FROM core.products WHERE id = %s AND tenant_id = %s", (product_id, tenant_id)
        ).fetchone() is None:
            return Err("NOT_FOUND", f"product {product_id} not found", f"produit {product_id} introuvable")
        self._connection.execute(
            "INSERT INTO warehouse.inventory_lines (id, tenant_id, inventory_id, product_id, theoretical_qty) VALUES (%s, %s, %s, %s, 0) "
            "ON CONFLICT (inventory_id, product_id) DO NOTHING",
            (str(ULID()), tenant_id, inventory_id, product_id),
        )
        return self.get(tenant_id=tenant_id, inventory_id=inventory_id)

    def record_count(self, *, tenant_id: str, actor_id: str, inventory_id: str, line_id: str, which: int,
                     quantity: Decimal | None, observation: str | None = None) -> Result[dict[str, Any]]:
        locked = self._lock_open(tenant_id, inventory_id)
        if isinstance(locked, Err):
            return locked
        if which not in (1, 2, 3):
            return Err("INVALID_COUNT", "count number must be 1, 2 or 3", "le numéro de comptage doit être 1, 2 ou 3")
        if quantity is not None and quantity < 0:
            return Err("INVALID_QUANTITY", "a counted quantity cannot be negative", "une quantité comptée ne peut pas être négative")
        row = self._connection.execute(
            "SELECT theoretical_qty, count_1, count_2, count_3, observation FROM warehouse.inventory_lines "
            "WHERE id = %s AND inventory_id = %s FOR UPDATE",
            (line_id, inventory_id),
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"inventory line {line_id} not found", f"ligne d'inventaire {line_id} introuvable")
        theoretical, counts = row[0], [row[1], row[2], row[3]]
        counts[which - 1] = quantity
        resolved = resolve_count(theoretical, *counts)
        # A third count that no longer matters (the first two now agree) is cleared, never silently kept.
        if resolved.final_qty is not None and counts[0] == counts[1]:
            counts[2] = None
        self._connection.execute(
            "UPDATE warehouse.inventory_lines SET count_1 = %s, count_2 = %s, count_3 = %s, final_qty = %s, variance = %s, "
            "observation = COALESCE(%s, observation) WHERE id = %s",
            (counts[0], counts[1], counts[2], resolved.final_qty, resolved.variance, observation, line_id),
        )
        return self.get(tenant_id=tenant_id, inventory_id=inventory_id)

    @atomic
    def close(self, *, tenant_id: str, actor_id: str, inventory_id: str, correlation_id: str) -> Result[dict[str, Any]]:
        locked = self._lock_open(tenant_id, inventory_id)
        if isinstance(locked, Err):
            return locked
        inventory = locked
        lines = self._lines(inventory_id)
        for line in lines:
            resolved = resolve_count(line["theoretical_qty"], line["count_1"], line["count_2"], line["count_3"])
            if resolved.final_qty is None:
                return Err("COUNT_REQUIRED", f"{line['name']} has no settled count (two equal counts, or a third)",
                           f"{line['name']} n'a pas de comptage arrêté (deux comptages égaux, ou un troisième)")
            if resolved.observation_required and not (line["observation"] or "").strip():
                return Err("OBSERVATION_REQUIRED", f"{line['name']} differs from the books and needs an observation",
                           f"{line['name']} diffère du stock théorique et exige une observation")

        adjustments = 0
        if inventory["type"] == "full":
            stock = StockService(self._connection)
            for line in lines:
                variance = line["variance"]
                if variance:
                    result = stock.adjust_stock(
                        tenant_id=tenant_id, product_id=line["product_id"], location_id=inventory["location_id"],
                        delta=float(variance), reason=line["observation"] or inventory["number"], actor_id=actor_id,
                        reference=inventory["number"], _from_inventory=True)
                    if isinstance(result, Err):
                        return result
                    adjustments += 1
            self._connection.execute(
                "UPDATE warehouse.stock_moves SET source_type = 'inventory', source_id = %s WHERE tenant_id = %s AND reference = %s AND source_id IS NULL",
                (inventory_id, tenant_id, inventory["number"]),
            )
        self._connection.execute(
            "UPDATE warehouse.inventories SET status = 'closed', closed_by = %s, closed_at = NOW() WHERE id = %s", (actor_id, inventory_id))
        publish_event(self._connection, event_type="warehouse.inventory.closed", producer="warehouse", tenant_id=tenant_id,
                      correlation_id=correlation_id,
                      payload={"inventory_id": inventory_id, "location_id": inventory["location_id"], "adjustments": adjustments})
        record_audit(self._connection, tenant_id=tenant_id, actor_id=actor_id, action="warehouse.inventory.closed",
                     entity_type="inventory", entity_id=inventory_id, payload={"number": inventory["number"], "adjustments": adjustments})
        return self.get(tenant_id=tenant_id, inventory_id=inventory_id)

    def cancel(self, *, tenant_id: str, actor_id: str, inventory_id: str) -> Result[dict[str, Any]]:
        locked = self._lock_open(tenant_id, inventory_id)
        if isinstance(locked, Err):
            return locked
        self._connection.execute("UPDATE warehouse.inventories SET status = 'cancelled', closed_by = %s, closed_at = NOW() WHERE id = %s",
                                 (actor_id, inventory_id))
        record_audit(self._connection, tenant_id=tenant_id, actor_id=actor_id, action="warehouse.inventory.cancelled",
                     entity_type="inventory", entity_id=inventory_id, payload={})
        return self.get(tenant_id=tenant_id, inventory_id=inventory_id)

    # ---- helpers ----------------------------------------------------------------------------

    def _lock_open(self, tenant_id: str, inventory_id: str) -> Result[dict[str, Any]]:
        row = self._connection.execute(
            f"SELECT {INVENTORY_COLUMNS} FROM warehouse.inventories WHERE id = %s AND tenant_id = %s FOR UPDATE", (inventory_id, tenant_id)
        ).fetchone()
        if row is None:
            return _not_found(inventory_id)
        inventory = dict(zip(INVENTORY_KEYS, row, strict=True))
        if inventory["status"] != "open":
            return Err("INVENTORY_NOT_OPEN", "this inventory is already closed or cancelled", "cet inventaire est déjà clôturé ou annulé")
        return inventory  # type: ignore[return-value]

    def _open_full(self, tenant_id: str, location_id: str) -> bool:
        return self._connection.execute(
            "SELECT 1 FROM warehouse.inventories WHERE tenant_id = %s AND location_id = %s AND status = 'open' AND type = 'full'",
            (tenant_id, location_id),
        ).fetchone() is not None

    def _lines(self, inventory_id: str) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            f"SELECT {LINE_COLUMNS} FROM warehouse.inventory_lines l JOIN core.products p ON p.id = l.product_id "
            "WHERE l.inventory_id = %s ORDER BY p.name",
            (inventory_id,),
        ).fetchall()
        return [dict(zip(LINE_KEYS, r, strict=True)) for r in rows]

    def _next_number(self, tenant_id: str) -> str:
        import datetime

        year = datetime.date.today().year
        row = self._connection.execute(
            """
            INSERT INTO warehouse.voucher_counters (tenant_id, voucher_type, year, last_number) VALUES (%s, 'inventory', %s, 1)
            ON CONFLICT (tenant_id, voucher_type, year)
            DO UPDATE SET last_number = warehouse.voucher_counters.last_number + 1
            RETURNING last_number
            """,
            (tenant_id, year),
        ).fetchone()
        return f"{PREFIX['inventory']}-{year}-{row[0]:06d}"
