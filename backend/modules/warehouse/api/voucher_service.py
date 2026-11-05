from __future__ import annotations

import datetime
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
    check_delivery,
    check_issue_available,
    check_lines,
    check_order_cumulative,
    check_return,
    check_transfer,
)

VOUCHER_COLUMNS = (
    "id, number, type, status, source_location_id, dest_location_id, partner_id, ref_type, ref_id, "
    "return_of_voucher_id, note, created_by, created_at, posted_by, posted_at, document_date, from_voucher_id, billable"
)
VOUCHER_KEYS = ["id", "number", "type", "status", "source_location_id", "dest_location_id", "partner_id", "ref_type",
                "ref_id", "return_of_voucher_id", "note", "created_by", "created_at", "posted_by", "posted_at", "document_date",
                "from_voucher_id", "billable"]


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
                     return_of_voucher_id: str | None = None, note: str | None = None,
                     document_date: datetime.date | None = None) -> Result[dict[str, Any]]:
        if type not in VOUCHER_TYPES:
            return Err("INVALID_VOUCHER_TYPE", f"unknown voucher type {type}", f"type de bon inconnu {type}")
        if type == "return" and return_of_voucher_id:
            # The manual returns against a delivery note; a note issued from a voucher returns to that voucher.
            source = self._return_source(tenant_id, return_of_voucher_id)
            if isinstance(source, Err):
                return source
            return_of_voucher_id = source["id"]
            partner_id = partner_id or source["partner_id"]
        shape = self._check_shape(type, source_location_id, dest_location_id, return_of_voucher_id)
        if isinstance(shape, Err):
            return shape
        checked = check_lines(type, lines)
        if isinstance(checked, Err):
            return checked
        stock = self._check_draft_stock(tenant_id, type, source_location_id, dest_location_id, ref_type, ref_id, lines)
        if isinstance(stock, Err):
            return stock
        voucher_id = str(ULID())
        self._connection.execute(
            "INSERT INTO warehouse.vouchers (id, tenant_id, type, source_location_id, dest_location_id, partner_id, ref_type, "
            "ref_id, return_of_voucher_id, note, created_by, document_date) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, COALESCE(%s, CURRENT_DATE))",
            (voucher_id, tenant_id, type, source_location_id, dest_location_id, partner_id, ref_type, ref_id,
             return_of_voucher_id, note, actor_id, document_date),
        )
        self._replace_lines(tenant_id, voucher_id, lines)
        record_audit(self._connection, tenant_id=tenant_id, actor_id=actor_id, action="warehouse.voucher.created",
                     entity_type="voucher", entity_id=voucher_id, payload={"type": type, "lines": len(lines)})
        return self._draft_with_warnings(tenant_id, voucher_id, type, lines)

    def update_draft(self, *, tenant_id: str, actor_id: str, voucher_id: str, changes: dict[str, Any]) -> Result[dict[str, Any]]:
        current = self._lock(tenant_id, voucher_id)
        if isinstance(current, Err):
            return current
        if current["status"] != "draft":
            return Err("VOUCHER_NOT_DRAFT", "only a draft voucher can be edited", "seul un bon brouillon peut être modifié")
        allowed = {"source_location_id", "dest_location_id", "partner_id", "note", "document_date"}
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
        stock = self._check_draft_stock(tenant_id, current["type"], merged["source_location_id"], merged["dest_location_id"],
                                        current["ref_type"], current["ref_id"], lines if lines is not None else self._lines(voucher_id))
        if isinstance(stock, Err):
            return stock
        if values:
            assignments = ", ".join(f"{k} = %s" for k in values)
            self._connection.execute(
                f"UPDATE warehouse.vouchers SET {assignments} WHERE id = %s AND tenant_id = %s", [*values.values(), voucher_id, tenant_id])
        if lines is not None:
            self._replace_lines(tenant_id, voucher_id, lines)
        record_audit(self._connection, tenant_id=tenant_id, actor_id=actor_id, action="warehouse.voucher.updated",
                     entity_type="voucher", entity_id=voucher_id, payload={k: str(v) for k, v in values.items()})
        return self._draft_with_warnings(tenant_id, voucher_id, current["type"], lines if lines is not None else self._lines(voucher_id))

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
        issuable = self._check_order_issuable(tenant_id, order.value)
        if isinstance(issuable, Err):
            return issuable
        lines = []
        for line in order.value.lines:
            quantity = (quantities or {}).get(line.product_id, Decimal(str(line.quantity)))
            if quantity > 0:
                lines.append({"product_id": line.product_id, "quantity": quantity})
        return self.create_draft(tenant_id=tenant_id, actor_id=actor_id, type="issue", lines=lines,
                                 source_location_id=source_location_id, partner_id=order.value.partner_id,
                                 ref_type="sales_order", ref_id=order_id)

    @atomic
    def create_receipt_from_purchase_receipt(self, *, tenant_id: str, actor_id: str, receipt_id: str, correlation_id: str) -> Result[dict[str, Any]]:
        """The entry voucher of a confirmed goods receipt. Procurement already moved the stock at its landed
        cost, so this is the document only, posted as it is created. Asked twice, it returns the same one."""
        from modules.procurement.api.service import PurchaseOrderService

        existing = self._connection.execute(
            "SELECT id FROM warehouse.vouchers WHERE tenant_id = %s AND ref_type = 'purchase_receipt' AND ref_id = %s", (tenant_id, receipt_id)
        ).fetchone()
        if existing is not None:
            return self.get(tenant_id=tenant_id, voucher_id=existing[0])
        reference = f"purchase_order_receipt:{receipt_id}"
        moves = self._connection.execute(
            "SELECT id, product_id, location_id, quantity, unit_cost FROM warehouse.stock_moves "
            "WHERE tenant_id = %s AND reference = %s AND move_type = 'receipt' ORDER BY id",
            (tenant_id, reference),
        ).fetchall()
        if not moves:
            return Err("RECEIPT_NOT_CONFIRMED", "this goods receipt has moved no stock yet; confirm it first",
                       "ce bon de réception n'a encore mouvementé aucun stock ; confirmez-le d'abord")
        procurement = PurchaseOrderService(self._connection)
        receipt = procurement.get_receipt(tenant_id=tenant_id, receipt_id=receipt_id)
        order = next((o for o in procurement.list_purchase_orders(tenant_id=tenant_id) if receipt and o.id == receipt.purchase_order_id), None)
        voucher_id = str(ULID())
        number = self._next_number(tenant_id, "receipt", datetime.datetime.now(datetime.timezone.utc).year)
        self._connection.execute(
            "INSERT INTO warehouse.vouchers (id, tenant_id, number, type, status, dest_location_id, partner_id, ref_type, ref_id, "
            "created_by, posted_by, posted_at) VALUES (%s, %s, %s, 'receipt', 'posted', %s, %s, 'purchase_receipt', %s, %s, %s, NOW())",
            (voucher_id, tenant_id, number, moves[0][2], order.supplier_id if order else None, receipt_id, actor_id, actor_id),
        )
        self._replace_lines(tenant_id, voucher_id, [{"product_id": m[1], "quantity": m[3], "unit_cost": m[4]} for m in moves])
        self._connection.execute(
            "UPDATE warehouse.stock_moves SET source_type = 'voucher', source_id = %s WHERE tenant_id = %s AND reference = %s AND source_id IS NULL",
            (voucher_id, tenant_id, reference),
        )
        publish_event(self._connection, event_type="warehouse.voucher.posted", event_version="1.1", producer="warehouse", tenant_id=tenant_id,
                      correlation_id=correlation_id, payload={"voucher_id": voucher_id, "type": "receipt", "number": number,
                                                              "ref_type": "purchase_receipt", "ref_id": receipt_id})
        record_audit(self._connection, tenant_id=tenant_id, actor_id=actor_id, action="warehouse.voucher.posted",
                     entity_type="voucher", entity_id=voucher_id, payload={"number": number, "type": "receipt", "purchase_receipt": receipt_id})
        return self.get(tenant_id=tenant_id, voucher_id=voucher_id)

    def list_unvouchered_purchase_receipts(self, *, tenant_id: str) -> list[dict[str, Any]]:
        """Goods receipts whose stock has moved and which have no entry voucher yet."""
        rows = self._connection.execute(
            """
            SELECT split_part(m.reference, ':', 2), MIN(m.created_at), COUNT(*)
            FROM warehouse.stock_moves m
            WHERE m.tenant_id = %s AND m.reference LIKE 'purchase_order_receipt:%%' AND m.move_type = 'receipt'
              AND NOT EXISTS (SELECT 1 FROM warehouse.vouchers v WHERE v.tenant_id = m.tenant_id AND v.ref_type = 'purchase_receipt'
                              AND v.ref_id = split_part(m.reference, ':', 2))
            GROUP BY 1 ORDER BY 2 DESC LIMIT 200
            """,
            (tenant_id,),
        ).fetchall()
        return [{"receipt_id": r[0], "received_at": r[1], "lines": r[2]} for r in rows]

    @atomic
    def generate_delivery_note(self, *, tenant_id: str, actor_id: str, voucher_id: str, correlation_id: str,
                               quantities: dict[str, Decimal] | None = None) -> Result[dict[str, Any]]:
        """A delivery note (BL) from a posted issue or return voucher. From an issue it documents goods that
        already left, so no stock moves. From a return it re-delivers the returned goods to the same customer:
        stock goes down again, and the note is not billable."""
        source = self._lock(tenant_id, voucher_id)
        if isinstance(source, Err):
            return source
        if source["status"] != "posted" or source["type"] not in ("issue", "return"):
            return Err("DELIVERY_SOURCE_INVALID", "a delivery note comes from a posted issue or return voucher",
                       "un bon de livraison provient d'un bon de sortie ou de retour validé")
        from_return = source["type"] == "return"
        location = source["dest_location_id"] if from_return else source["source_location_id"]
        carried = self._merge_by_product(self._lines(voucher_id))
        delivered = dict(self._connection.execute(
            """
            SELECT l.product_id, SUM(l.quantity) FROM warehouse.voucher_lines l JOIN warehouse.vouchers v ON v.id = l.voucher_id
            WHERE v.tenant_id = %s AND v.from_voucher_id = %s AND v.type = 'delivery' AND v.status = 'posted'
            GROUP BY l.product_id
            """,
            (tenant_id, voucher_id),
        ).fetchall())
        lines = []
        for product_id, on_source in carried.items():
            done = Decimal(str(delivered.get(product_id, 0)))
            quantity = quantities[product_id] if quantities and product_id in quantities else on_source - done
            if quantity <= 0:
                continue
            checked = check_delivery(on_source, done, quantity)
            if isinstance(checked, Err):
                return checked
            lines.append({"product_id": product_id, "quantity": quantity})
        if not lines:
            return Err("NOTHING_TO_DELIVER", "everything on this voucher already has a delivery note",
                       "tout ce bon a déjà un bon de livraison")
        number = self._next_number(tenant_id, "delivery", datetime.datetime.now(datetime.timezone.utc).year)
        if from_return:
            for line in lines:
                available = Decimal(str(self._stock.get_available_quantity(tenant_id, line["product_id"], location)))
                checked = check_issue_available(available, line["quantity"])
                if isinstance(checked, Err):
                    return checked
                issued = self._stock.issue_stock(tenant_id=tenant_id, product_id=line["product_id"], location_id=location,
                                                 quantity=float(line["quantity"]), reference=number, actor_id=actor_id)
                if isinstance(issued, Err):
                    return issued
        delivery_id = str(ULID())
        self._connection.execute(
            "INSERT INTO warehouse.vouchers (id, tenant_id, number, type, status, source_location_id, partner_id, from_voucher_id, billable, "
            "created_by, posted_by, posted_at) VALUES (%s, %s, %s, 'delivery', 'posted', %s, %s, %s, %s, %s, %s, NOW())",
            (delivery_id, tenant_id, number, location, source["partner_id"], voucher_id, not from_return, actor_id, actor_id),
        )
        self._replace_lines(tenant_id, delivery_id, lines)
        self._connection.execute(
            "UPDATE warehouse.stock_moves SET source_type = 'voucher', source_id = %s WHERE tenant_id = %s AND reference = %s AND source_id IS NULL",
            (delivery_id, tenant_id, number),
        )
        publish_event(self._connection, event_type="warehouse.voucher.posted", event_version="1.1", producer="warehouse", tenant_id=tenant_id,
                      correlation_id=correlation_id, payload={"voucher_id": delivery_id, "type": "delivery", "number": number,
                                                              "ref_type": None, "ref_id": None})
        record_audit(self._connection, tenant_id=tenant_id, actor_id=actor_id, action="warehouse.voucher.posted",
                     entity_type="voucher", entity_id=delivery_id,
                     payload={"number": number, "type": "delivery", "from_voucher": voucher_id, "billable": not from_return})
        return self.get(tenant_id=tenant_id, voucher_id=delivery_id)

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
        payload: dict[str, Any] = {"voucher_id": voucher_id, "type": current["type"], "number": number,
                                   "ref_type": current["ref_type"], "ref_id": current["ref_id"]}
        if current["type"] == "issue" and current["ref_type"] == "sales_order" and current["ref_id"]:
            payload["issued_to_date"] = self._order_net_issued(tenant_id, current["ref_id"])
        publish_event(self._connection, event_type="warehouse.voucher.posted", event_version="1.1", producer="warehouse", tenant_id=tenant_id,
                      correlation_id=correlation_id, payload=payload)
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
        # Here as well as when drafting: a draft can wait while the order moves on.
        if voucher["ref_type"] == "sales_order" and voucher["ref_id"]:
            from modules.sales.api.service import SalesOrderService

            order = SalesOrderService(self._connection).get_order(tenant_id=tenant_id, order_id=voucher["ref_id"])
            if isinstance(order, Err):
                return order
            issuable = self._check_order_issuable(tenant_id, order.value)
            if isinstance(issuable, Err):
                return issuable
            taken_over = self._take_over_from_fulfillment(tenant_id, actor_id, correlation_id, voucher["ref_id"])
            if isinstance(taken_over, Err):
                return taken_over
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
            # The FIFO layers consumed under this voucher number give the average cost of the line.
            cost = self._connection.execute(
                """
                SELECT SUM(quantity * unit_cost) / NULLIF(SUM(quantity), 0)
                FROM warehouse.cost_layer_consumptions
                WHERE tenant_id = %s AND reference = %s AND product_id = %s AND unit_cost IS NOT NULL
                """,
                (tenant_id, number, line["product_id"]),
            ).fetchone()
            if cost and cost[0] is not None:
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
        source = self._return_source(tenant_id, voucher["return_of_voucher_id"])
        if isinstance(source, Err):
            return source
        for product_id, quantity in merged.items():
            issued = self._connection.execute(
                "SELECT COALESCE(SUM(quantity), 0) FROM warehouse.voucher_lines WHERE voucher_id = %s AND product_id = %s",
                (voucher["return_of_voucher_id"], product_id),
            ).fetchone()[0]
            if issued == 0:
                continue  # the manual lets a return add a product the source document didn't carry; only those it carried are capped
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
        costs = dict(self._connection.execute(
            "SELECT product_id, SUM(quantity * unit_cost) / NULLIF(SUM(quantity), 0) FROM warehouse.voucher_lines "
            "WHERE voucher_id = %s AND unit_cost IS NOT NULL GROUP BY product_id",
            (voucher["return_of_voucher_id"],),
        ).fetchall())
        for line in lines:
            # Back at the cost it left at; a product the source document didn't carry falls back like any other inflow.
            cost = costs.get(line["product_id"])
            result = self._stock.receive_stock(
                tenant_id=tenant_id, product_id=line["product_id"], location_id=voucher["dest_location_id"],
                quantity=float(line["quantity"]), correlation_id=correlation_id, reference=number, actor_id=actor_id,
                move_type="return", unit_cost=float(cost) if cost is not None else None)
            if isinstance(result, Err):
                return result
        return Ok(None)

    # ---- helpers ----------------------------------------------------------------------------

    def _return_source(self, tenant_id: str, voucher_id: str) -> Err | dict[str, Any]:
        row = self._connection.execute(
            "SELECT id, status, type, partner_id, from_voucher_id FROM warehouse.vouchers WHERE id = %s AND tenant_id = %s", (voucher_id, tenant_id)
        ).fetchone()
        if row is None or row[1] != "posted" or row[2] not in ("issue", "delivery"):
            return Err("RETURN_SOURCE_INVALID", "a return must refer to a posted issue voucher or delivery note",
                       "un retour doit se référer à un bon de sortie ou un bon de livraison validé")
        if row[2] == "delivery" and row[4] is not None:
            parent = self._connection.execute("SELECT type FROM warehouse.vouchers WHERE id = %s", (row[4],)).fetchone()
            if parent and parent[0] == "issue":
                return {"id": row[4], "partner_id": row[3]}
        return {"id": row[0], "partner_id": row[3]}

    def _held_for_order(self, tenant_id: str, order_id: str, product_id: str, location_id: str) -> Decimal:
        row = self._connection.execute(
            "SELECT COALESCE(SUM(quantity_open), 0) FROM warehouse.stock_reservations WHERE tenant_id = %s AND reference = %s "
            "AND product_id = %s AND location_id = %s AND status = 'active'",
            (tenant_id, f"sales_order:{order_id}", product_id, location_id),
        ).fetchone()
        return Decimal(str(row[0]))

    def _check_draft_stock(self, tenant_id: str, voucher_type: str, source: str | None, dest: str | None, ref_type: str | None,
                           ref_id: str | None, lines: list[dict[str, Any]]) -> Result[None]:
        """The manual refuses at entry, not only at posting: an out-of-stock product stops the voucher being
        added at all. Posting checks again, because stock can leave while a draft waits. What is reserved
        for this very order counts as available to it: posting takes it over from fulfillment."""
        if voucher_type not in ("issue", "transfer"):
            return Ok(None)
        for product_id, quantity in self._merge_by_product(lines).items():
            available = Decimal(str(self._stock.get_available_quantity(tenant_id, product_id, source)))
            if voucher_type == "transfer":
                checked = check_transfer(source, dest, available, quantity)
            else:
                if ref_type == "sales_order" and ref_id:
                    available += self._held_for_order(tenant_id, ref_id, product_id, source)
                checked = check_issue_available(available, quantity)
            if isinstance(checked, Err):
                return checked
            if voucher_type == "issue" and ref_type == "sales_order" and ref_id:
                capped = self._check_order_cap(tenant_id, {"ref_id": ref_id}, product_id, quantity)
                if isinstance(capped, Err):
                    return capped
        return Ok(None)

    def _draft_with_warnings(self, tenant_id: str, voucher_id: str, voucher_type: str, lines: list[dict[str, Any]]) -> Result[dict[str, Any]]:
        """The safety-quantity alert, raised as soon as the quantity is entered: where stock would stand once posted."""
        voucher = self.get(tenant_id=tenant_id, voucher_id=voucher_id)
        if isinstance(voucher, Err) or voucher_type not in ("issue", "transfer"):
            return voucher
        warnings: list[dict[str, Any]] = []
        self._warn_minimum(tenant_id, "", self._merge_by_product(lines), warnings, pending=voucher_type == "issue")
        return Ok({**voucher.value, "warnings": warnings})

    def _take_over_from_fulfillment(self, tenant_id: str, actor_id: str, correlation_id: str, order_id: str) -> Result[None]:
        """The voucher becomes the order's way out of the warehouse: a pick list nobody started is cancelled,
        which gives back its reservation, and a reservation with no pick list yet is released. Later vouchers
        and a late confirmation event then find nothing to hold (fulfillment refuses an order already issued)."""
        from modules.warehouse.api.fulfillment_service import FulfillmentService
        from modules.warehouse.api.reservation_service import ReservationService

        pick_lists = self._connection.execute(
            "SELECT id FROM warehouse.pick_lists WHERE tenant_id = %s AND source_type = 'sales_order' AND source_id = %s AND status = 'open'",
            (tenant_id, order_id),
        ).fetchall()
        for (pick_list_id,) in pick_lists:
            cancelled = FulfillmentService(self._connection).cancel_pick_list(
                tenant_id=tenant_id, actor_id=actor_id, pick_list_id=pick_list_id, correlation_id=correlation_id)
            if isinstance(cancelled, Err):
                return cancelled
        reservations = self._connection.execute(
            "SELECT id FROM warehouse.stock_reservations WHERE tenant_id = %s AND reference = %s AND status = 'active'",
            (tenant_id, f"sales_order:{order_id}"),
        ).fetchall()
        for (reservation_id,) in reservations:
            released = ReservationService(self._connection).release_reservation(tenant_id=tenant_id, actor_id=actor_id, reservation_id=reservation_id)
            if isinstance(released, Err):
                return released
        return Ok(None)

    def _order_net_issued(self, tenant_id: str, order_id: str) -> dict[str, float]:
        """Per product, what posted vouchers have issued for the order, net of returns. The whole figure
        rather than this voucher's lines, so a consumer needs no running total and a replay changes nothing."""
        issued = self._connection.execute(
            """
            SELECT l.product_id, SUM(l.quantity) FROM warehouse.voucher_lines l JOIN warehouse.vouchers v ON v.id = l.voucher_id
            WHERE v.tenant_id = %s AND v.type = 'issue' AND v.status = 'posted' AND v.ref_type = 'sales_order' AND v.ref_id = %s
            GROUP BY l.product_id
            """,
            (tenant_id, order_id),
        ).fetchall()
        returned = dict(self._connection.execute(
            """
            SELECT r.product_id, SUM(r.quantity) FROM warehouse.voucher_lines r
            JOIN warehouse.vouchers rv ON rv.id = r.voucher_id
            JOIN warehouse.vouchers iv ON iv.id = rv.return_of_voucher_id
            WHERE rv.status = 'posted' AND iv.tenant_id = %s AND iv.ref_type = 'sales_order' AND iv.ref_id = %s
            GROUP BY r.product_id
            """,
            (tenant_id, order_id),
        ).fetchall())
        return {product_id: float(quantity - returned.get(product_id, 0)) for product_id, quantity in issued}

    def _check_order_issuable(self, tenant_id: str, order: Any) -> Result[None]:
        """Fulfillment first, so a shipped order is refused for what actually happened to it. Before
        confirmation nothing is reserved and nothing stops fulfillment opening later on the same order."""
        held = self._check_order_not_in_fulfillment(tenant_id, order.id)
        if isinstance(held, Err):
            return held
        if order.status != "confirmed":
            return Err("ORDER_NOT_CONFIRMED", f"an issue voucher needs a confirmed order; this one is {order.status}",
                       f"un bon de sortie exige une commande confirmée ; celle-ci est au statut {order.status}")
        return Ok(None)

    def _check_order_not_in_fulfillment(self, tenant_id: str, order_id: str) -> Result[None]:
        """An order leaves the warehouse by one route only. Once someone has started picking it, or it has
        shipped, a voucher would issue the same goods a second time: the order cap counts only vouchers,
        and surplus stock passes the availability check. A pick list nobody started gives way to the
        voucher (see _take_over_from_fulfillment).
        FOR SHARE makes a ship running at the same moment finish first, so its status is the real one."""
        pick_list = self._connection.execute(
            "SELECT 1 FROM warehouse.pick_lists WHERE tenant_id = %s AND source_type = 'sales_order' AND source_id = %s "
            "AND status NOT IN ('cancelled', 'open') FOR SHARE",
            (tenant_id, order_id),
        ).fetchone()
        if pick_list is None:
            return Ok(None)
        return Err(
            "ORDER_IN_FULFILLMENT",
            "this order is handled by fulfillment (pick list and shipment); an issue voucher would deduct the stock twice",
            "cette commande est traitée par la préparation (liste de prélèvement et expédition) ; un bon de sortie déduirait le stock deux fois",
        )

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

    def _warn_minimum(self, tenant_id: str, location_id: str, merged: dict[str, Decimal], warnings: list[dict[str, Any]],
                      pending: bool = False) -> None:
        """`pending`: the quantities haven't left yet, so count them off what is on hand. Stock across the
        plant is what the safety quantity watches, so a transfer never changes it by itself."""
        for product_id in merged:
            row = self._connection.execute(
                "SELECT stock_alert_threshold FROM core.products WHERE id = %s AND tenant_id = %s", (product_id, tenant_id)
            ).fetchone()
            on_hand = self._connection.execute(
                "SELECT COALESCE(SUM(quantity_on_hand), 0) FROM warehouse.stock_items WHERE tenant_id = %s AND product_id = %s",
                (tenant_id, product_id),
            ).fetchone()[0]
            if pending:
                on_hand -= merged[product_id]
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
