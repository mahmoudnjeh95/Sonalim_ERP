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
from modules.warehouse.domain.voucher_rules import (
    PREFIX,
    VOUCHER_TYPES,
    below_minimum,
    check_issue_available,
    check_lines,
    check_order_cumulative,
    check_return,
    check_transfer,
)

VOUCHER_COLUMNS = (
    "id, number, type, status, source_location_id, dest_location_id, partner_id, ref_type, ref_id, "
    "return_of_voucher_id, note, created_by, created_at, posted_by, posted_at"
)
VOUCHER_KEYS = ["id", "number", "type", "status", "source_location_id", "dest_location_id", "partner_id", "ref_type",
                "ref_id", "return_of_voucher_id", "note", "created_by", "created_at", "posted_by", "posted_at"]


def _not_found(voucher_id: str) -> Err:
    return Err("NOT_FOUND", f"voucher {voucher_id} not found", f"bon {voucher_id} introuvable")


class VoucherService:
    """Receipt, issue, return and transfer vouchers: a document header over the move ledger.
    Posting runs every line through StockService in the caller's transaction; callers commit."""

    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection
        self._stock = StockService(connection)

    # ---- reads ------------------------------------------------------------------------------

    def get(self, *, tenant_id: str, voucher_id: str) -> Result[dict[str, Any]]:
        row = self._connection.execute(
            f"SELECT {VOUCHER_COLUMNS} FROM warehouse.vouchers WHERE id = %s AND tenant_id = %s", (voucher_id, tenant_id)
        ).fetchone()
        if row is None:
            return _not_found(voucher_id)
        voucher = dict(zip(VOUCHER_KEYS, row, strict=True))
        voucher["lines"] = self._lines(voucher_id)
        return Ok(voucher)

    def list(self, *, tenant_id: str, type: str | None = None, status: str | None = None,
             ref_type: str | None = None, ref_id: str | None = None) -> list[dict[str, Any]]:
        clauses, params = ["tenant_id = %s"], [tenant_id]
        for column, value in (("type", type), ("status", status), ("ref_type", ref_type), ("ref_id", ref_id)):
            if value:
                clauses.append(f"{column} = %s")
                params.append(value)
        rows = self._connection.execute(
            f"SELECT {VOUCHER_COLUMNS} FROM warehouse.vouchers WHERE {' AND '.join(clauses)} ORDER BY created_at DESC, id DESC",
            params,
        ).fetchall()
        return [dict(zip(VOUCHER_KEYS, r, strict=True)) for r in rows]

    # ---- drafts -----------------------------------------------------------------------------

    def create_draft(self, *, tenant_id: str, actor_id: str, type: str, lines: list[dict[str, Any]],
                     source_location_id: str | None = None, dest_location_id: str | None = None,
                     partner_id: str | None = None, ref_type: str | None = None, ref_id: str | None = None,
                     return_of_voucher_id: str | None = None, note: str | None = None) -> Result[dict[str, Any]]:
        if type not in VOUCHER_TYPES:
            return Err("INVALID_VOUCHER_TYPE", f"unknown voucher type {type}", f"type de bon inconnu {type}")
        shape = self._check_shape(type, source_location_id, dest_location_id, return_of_voucher_id)
        if isinstance(shape, Err):
            return shape
        checked = check_lines(type, lines)
        if isinstance(checked, Err):
            return checked
        voucher_id = str(ULID())
        self._connection.execute(
            "INSERT INTO warehouse.vouchers (id, tenant_id, type, source_location_id, dest_location_id, partner_id, ref_type, "
            "ref_id, return_of_voucher_id, note, created_by) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (voucher_id, tenant_id, type, source_location_id, dest_location_id, partner_id, ref_type, ref_id,
             return_of_voucher_id, note, actor_id),
        )
        self._replace_lines(tenant_id, voucher_id, lines)
        record_audit(self._connection, tenant_id=tenant_id, actor_id=actor_id, action="warehouse.voucher.created",
                     entity_type="voucher", entity_id=voucher_id, payload={"type": type, "lines": len(lines)})
        return self.get(tenant_id=tenant_id, voucher_id=voucher_id)

    def update_draft(self, *, tenant_id: str, actor_id: str, voucher_id: str, changes: dict[str, Any]) -> Result[dict[str, Any]]:
        current = self._lock(tenant_id, voucher_id)
        if isinstance(current, Err):
            return current
        if current["status"] != "draft":
            return Err("VOUCHER_NOT_DRAFT", "only a draft voucher can be edited", "seul un bon brouillon peut être modifié")
        allowed = {"source_location_id", "dest_location_id", "partner_id", "note"}
        values = {k: v for k, v in changes.items() if k in allowed}
        merged = {**current, **values}
        shape = self._check_shape(current["type"], merged["source_location_id"], merged["dest_location_id"], merged["return_of_voucher_id"])
        if isinstance(shape, Err):
            return shape
        lines = changes.get("lines")
        if lines is not None:
            checked = check_lines(current["type"], lines)
            if isinstance(checked, Err):
                return checked
        if values:
            assignments = ", ".join(f"{k} = %s" for k in values)
            self._connection.execute(
                f"UPDATE warehouse.vouchers SET {assignments} WHERE id = %s AND tenant_id = %s", [*values.values(), voucher_id, tenant_id])
        if lines is not None:
            self._replace_lines(tenant_id, voucher_id, lines)
        record_audit(self._connection, tenant_id=tenant_id, actor_id=actor_id, action="warehouse.voucher.updated",
                     entity_type="voucher", entity_id=voucher_id, payload={k: str(v) for k, v in values.items()})
        return self.get(tenant_id=tenant_id, voucher_id=voucher_id)

    def cancel(self, *, tenant_id: str, actor_id: str, voucher_id: str) -> Result[dict[str, Any]]:
        current = self._lock(tenant_id, voucher_id)
        if isinstance(current, Err):
            return current
        if current["status"] != "draft":
            return Err("VOUCHER_NOT_DRAFT", "only a draft voucher can be cancelled; correct a posted one with a return or an adjustment",
                       "seul un bon brouillon peut être annulé ; corrigez un bon validé par un retour ou un ajustement")
        self._connection.execute("UPDATE warehouse.vouchers SET status = 'cancelled' WHERE id = %s", (voucher_id,))
        record_audit(self._connection, tenant_id=tenant_id, actor_id=actor_id, action="warehouse.voucher.cancelled",
                     entity_type="voucher", entity_id=voucher_id, payload={})
        return self.get(tenant_id=tenant_id, voucher_id=voucher_id)

    def create_issue_from_order(self, *, tenant_id: str, actor_id: str, order_id: str, source_location_id: str,
                                quantities: dict[str, Decimal] | None = None) -> Result[dict[str, Any]]:
        """Draft an issue voucher from a sales order: customer and lines prefilled; the user picked the
        location and may lower quantities (`quantities` maps product id to the amount to ship now)."""
        from modules.sales.api.service import SalesOrderService

        order = SalesOrderService(self._connection).get_order(tenant_id=tenant_id, order_id=order_id)
        if isinstance(order, Err):
            return order
        lines = []
        for line in order.value.lines:
            quantity = (quantities or {}).get(line.product_id, Decimal(str(line.quantity)))
            if quantity > 0:
                lines.append({"product_id": line.product_id, "quantity": quantity})
        return self.create_draft(tenant_id=tenant_id, actor_id=actor_id, type="issue", lines=lines,
                                 source_location_id=source_location_id, partner_id=order.value.partner_id,
                                 ref_type="sales_order", ref_id=order_id)

    # ---- posting ----------------------------------------------------------------------------

    @atomic
    def post(self, *, tenant_id: str, actor_id: str, voucher_id: str, correlation_id: str) -> Result[dict[str, Any]]:
        current = self._lock(tenant_id, voucher_id)
        if isinstance(current, Err):
            return current
        if current["status"] != "draft":
            return Err("VOUCHER_NOT_DRAFT", "this voucher is already posted or cancelled", "ce bon est déjà validé ou annulé")
        lines = self._lines(voucher_id)
        checked = check_lines(current["type"], lines)
        if isinstance(checked, Err):
            return checked
        merged = self._merge_by_product(lines)

        number = self._next_number(tenant_id, current["type"], current["created_at"].year)
        warnings: list[dict[str, Any]] = []
        handler = getattr(self, f"_post_{current['type']}")
        done = handler(tenant_id, actor_id, correlation_id, current, number, lines, merged, warnings)
        if isinstance(done, Err):
            return done

        self._connection.execute(
            "UPDATE warehouse.stock_moves SET source_type = 'voucher', source_id = %s WHERE tenant_id = %s AND reference = %s "
            "AND source_id IS NULL",
            (voucher_id, tenant_id, number),
        )
        self._connection.execute(
            "UPDATE warehouse.vouchers SET status = 'posted', number = %s, posted_by = %s, posted_at = NOW() WHERE id = %s",
            (number, actor_id, voucher_id),
        )
        publish_event(self._connection, event_type="warehouse.voucher.posted", producer="warehouse", tenant_id=tenant_id,
                      correlation_id=correlation_id, payload={"voucher_id": voucher_id, "type": current["type"], "number": number})
        record_audit(self._connection, tenant_id=tenant_id, actor_id=actor_id, action="warehouse.voucher.posted",
                     entity_type="voucher", entity_id=voucher_id, payload={"number": number, "type": current["type"]})
        posted = self.get(tenant_id=tenant_id, voucher_id=voucher_id)
        return Ok({**posted.value, "warnings": warnings})

    def _post_receipt(self, tenant_id, actor_id, correlation_id, voucher, number, lines, merged, warnings) -> Result[None]:
        for line in lines:
            result = self._stock.receive_stock(
                tenant_id=tenant_id, product_id=line["product_id"], location_id=voucher["dest_location_id"],
                quantity=float(line["quantity"]), correlation_id=correlation_id, reference=number, actor_id=actor_id,
                unit_cost=Decimal(str(line["unit_cost"])),
            )
            if isinstance(result, Err):
                return result
        return Ok(None)

    def _post_issue(self, tenant_id, actor_id, correlation_id, voucher, number, lines, merged, warnings) -> Result[None]:
        location = voucher["source_location_id"]
        for product_id, quantity in merged.items():
            available = Decimal(str(self._stock.get_available_quantity(tenant_id, product_id, location)))
            checked = check_issue_available(available, quantity)
            if isinstance(checked, Err):
                return checked
            if voucher["ref_type"] == "sales_order" and voucher["ref_id"]:
                capped = self._check_order_cap(tenant_id, voucher, product_id, quantity)
                if isinstance(capped, Err):
                    return capped
        for line in lines:
            result = self._stock.issue_stock(tenant_id=tenant_id, product_id=line["product_id"], location_id=location,
                                             quantity=float(line["quantity"]), reference=number, actor_id=actor_id)
            if isinstance(result, Err):
                return result
            # Record the cost the goods left at, so a later return restocks at the same figure.
            cost = self._connection.execute(
                "SELECT avg_cost FROM warehouse.stock_valuation WHERE tenant_id = %s AND product_id = %s",
                (tenant_id, line["product_id"]),
            ).fetchone()
            if cost:
                self._connection.execute("UPDATE warehouse.voucher_lines SET unit_cost = %s WHERE id = %s", (cost[0], line["id"]))
        self._warn_minimum(tenant_id, location, merged, warnings)
        return Ok(None)

    def _post_transfer(self, tenant_id, actor_id, correlation_id, voucher, number, lines, merged, warnings) -> Result[None]:
        source, dest = voucher["source_location_id"], voucher["dest_location_id"]
        for product_id, quantity in merged.items():
            available = Decimal(str(self._stock.get_available_quantity(tenant_id, product_id, source)))
            checked = check_transfer(source, dest, available, quantity)
            if isinstance(checked, Err):
                return checked
        for line in lines:
            result = self._stock.transfer_stock(
                tenant_id=tenant_id, product_id=line["product_id"], from_location_id=source, to_location_id=dest,
                quantity=float(line["quantity"]), correlation_id=correlation_id, reference=number, actor_id=actor_id)
            if isinstance(result, Err):
                return result
        self._warn_minimum(tenant_id, source, merged, warnings)
        return Ok(None)

    def _post_return(self, tenant_id, actor_id, correlation_id, voucher, number, lines, merged, warnings) -> Result[None]:
        original = self._connection.execute(
            "SELECT status, type FROM warehouse.vouchers WHERE id = %s AND tenant_id = %s",
            (voucher["return_of_voucher_id"], tenant_id),
        ).fetchone()
        if original is None or original[0] != "posted" or original[1] != "issue":
            return Err("RETURN_SOURCE_INVALID", "a return must refer to a posted issue voucher",
                       "un retour doit se référer à un bon de sortie validé")
        for product_id, quantity in merged.items():
            issued = self._connection.execute(
                "SELECT COALESCE(SUM(quantity), 0) FROM warehouse.voucher_lines WHERE voucher_id = %s AND product_id = %s",
                (voucher["return_of_voucher_id"], product_id),
            ).fetchone()[0]
            returned = self._connection.execute(
                """
                SELECT COALESCE(SUM(l.quantity), 0) FROM warehouse.voucher_lines l JOIN warehouse.vouchers v ON v.id = l.voucher_id
                WHERE v.return_of_voucher_id = %s AND v.status = 'posted' AND l.product_id = %s
                """,
                (voucher["return_of_voucher_id"], product_id),
            ).fetchone()[0]
            checked = check_return(issued, returned, quantity)
            if isinstance(checked, Err):
                return checked
        for line in lines:
            result = self._stock.receive_stock(
                tenant_id=tenant_id, product_id=line["product_id"], location_id=voucher["dest_location_id"],
                quantity=float(line["quantity"]), correlation_id=correlation_id, reference=number, actor_id=actor_id,
                move_type="return")
            if isinstance(result, Err):
                return result
        return Ok(None)

    # ---- helpers ----------------------------------------------------------------------------

    def _check_order_cap(self, tenant_id: str, voucher: dict[str, Any], product_id: str, quantity: Decimal) -> Result[None]:
        from modules.sales.api.service import SalesOrderService

        order = SalesOrderService(self._connection).get_order(tenant_id=tenant_id, order_id=voucher["ref_id"])
        if isinstance(order, Err):
            return order
        ordered = sum((Decimal(str(l.quantity)) for l in order.value.lines if l.product_id == product_id), Decimal("0"))
        issued = self._connection.execute(
            """
            SELECT COALESCE(SUM(l.quantity), 0) FROM warehouse.voucher_lines l JOIN warehouse.vouchers v ON v.id = l.voucher_id
            WHERE v.tenant_id = %s AND v.type = 'issue' AND v.status = 'posted' AND v.ref_type = 'sales_order'
              AND v.ref_id = %s AND l.product_id = %s
            """,
            (tenant_id, voucher["ref_id"], product_id),
        ).fetchone()[0]
        returned = self._connection.execute(
            """
            SELECT COALESCE(SUM(r.quantity), 0) FROM warehouse.voucher_lines r
            JOIN warehouse.vouchers rv ON rv.id = r.voucher_id
            JOIN warehouse.vouchers iv ON iv.id = rv.return_of_voucher_id
            WHERE rv.status = 'posted' AND iv.tenant_id = %s AND iv.ref_type = 'sales_order' AND iv.ref_id = %s AND r.product_id = %s
            """,
            (tenant_id, voucher["ref_id"], product_id),
        ).fetchone()[0]
        return check_order_cumulative(ordered, issued - returned, quantity)

    def _warn_minimum(self, tenant_id: str, location_id: str, merged: dict[str, Decimal], warnings: list[dict[str, Any]]) -> None:
        for product_id in merged:
            row = self._connection.execute(
                "SELECT stock_alert_threshold FROM core.products WHERE id = %s AND tenant_id = %s", (product_id, tenant_id)
            ).fetchone()
            on_hand = self._connection.execute(
                "SELECT COALESCE(SUM(quantity_on_hand), 0) FROM warehouse.stock_items WHERE tenant_id = %s AND product_id = %s",
                (tenant_id, product_id),
            ).fetchone()[0]
            minimum = Decimal(str(row[0])) if row and row[0] is not None else None
            if below_minimum(on_hand, minimum):
                warnings.append({"code": "BELOW_MINIMUM", "product_id": product_id, "on_hand": on_hand, "minimum": minimum})

    @staticmethod
    def _merge_by_product(lines: list[dict[str, Any]]) -> dict[str, Decimal]:
        merged: dict[str, Decimal] = {}
        for line in lines:
            merged[line["product_id"]] = merged.get(line["product_id"], Decimal("0")) + Decimal(str(line["quantity"]))
        return merged

    @staticmethod
    def _check_shape(type: str, source: str | None, dest: str | None, return_of: str | None) -> Result[None]:
        needs = {"receipt": (False, True), "issue": (True, False), "return": (False, True), "transfer": (True, True)}[type]
        if (needs[0] and not source) or (needs[1] and not dest):
            return Err("LOCATION_REQUIRED", f"a {type} voucher needs " + ("a source and a destination" if needs == (True, True) else
                       "a source location" if needs[0] else "a destination location"),
                       f"un bon de type {type} exige " + ("un emplacement source et un de destination" if needs == (True, True) else
                       "un emplacement source" if needs[0] else "un emplacement de destination"))
        if type == "return" and not return_of:
            return Err("RETURN_SOURCE_INVALID", "a return must refer to an issue voucher", "un retour doit se référer à un bon de sortie")
        return Ok(None)

    def _lock(self, tenant_id: str, voucher_id: str) -> Result[dict[str, Any]]:
        row = self._connection.execute(
            f"SELECT {VOUCHER_COLUMNS} FROM warehouse.vouchers WHERE id = %s AND tenant_id = %s FOR UPDATE", (voucher_id, tenant_id)
        ).fetchone()
        if row is None:
            return _not_found(voucher_id)
        return dict(zip(VOUCHER_KEYS, row, strict=True))  # type: ignore[return-value]

    def _lines(self, voucher_id: str) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            "SELECT id, product_id, quantity, unit_cost, return_of_line_id FROM warehouse.voucher_lines WHERE voucher_id = %s ORDER BY id",
            (voucher_id,),
        ).fetchall()
        return [{"id": r[0], "product_id": r[1], "quantity": r[2], "unit_cost": r[3], "return_of_line_id": r[4]} for r in rows]

    def _replace_lines(self, tenant_id: str, voucher_id: str, lines: list[dict[str, Any]]) -> None:
        self._connection.execute("DELETE FROM warehouse.voucher_lines WHERE voucher_id = %s", (voucher_id,))
        for line in lines:
            self._connection.execute(
                "INSERT INTO warehouse.voucher_lines (id, tenant_id, voucher_id, product_id, quantity, unit_cost) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (str(ULID()), tenant_id, voucher_id, line["product_id"], line["quantity"], line.get("unit_cost")),
            )

    def _next_number(self, tenant_id: str, voucher_type: str, year: int) -> str:
        row = self._connection.execute(
            """
            INSERT INTO warehouse.voucher_counters (tenant_id, voucher_type, year, last_number) VALUES (%s, %s, %s, 1)
            ON CONFLICT (tenant_id, voucher_type, year)
            DO UPDATE SET last_number = warehouse.voucher_counters.last_number + 1
            RETURNING last_number
            """,
            (tenant_id, voucher_type, year),
        ).fetchone()
        return f"{PREFIX[voucher_type]}-{year}-{row[0]:06d}"
