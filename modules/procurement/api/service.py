from __future__ import annotations

import datetime

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from core.events.outbox import publish_event
from modules.procurement.domain.entities import (
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderReceipt,
    PurchaseOrderReceiptLine,
    apply_receipt_to_line,
    compute_landed_cost,
    confirm_purchase_order_receipt,
    receive_against_order,
    transition_purchase_order,
    validate_new_purchase_order,
    validate_new_purchase_order_line,
)
from modules.warehouse.api.lot_service import LotService
from modules.warehouse.api.service import StockService

_ORDER_COLUMNS = "id, tenant_id, supplier_id, status, order_date, expected_date, currency_code, notes"
_LINE_COLUMNS = (
    "id, tenant_id, purchase_order_id, product_id, uom_id, quantity_ordered, quantity_received, "
    "status, unit_price, unit_price_currency"
)
_RECEIPT_COLUMNS = (
    "id, tenant_id, purchase_order_id, location_id, status, invoice_number, invoice_date, origin_country, "
    "carrier, base_cost, license_fee, insurance_fee, transit_fee, transport_fee, customs_duty, total_cost, confirmed_at"
)
_RECEIPT_LINE_COLUMNS = "id, tenant_id, purchase_order_receipt_id, purchase_order_line_id, quantity, lot_number, cost_per_unit"


def _row_to_order(row: tuple) -> PurchaseOrder:
    rid, tenant_id, supplier_id, status, order_date, expected_date, currency_code, notes = row
    return PurchaseOrder(
        id=rid,
        tenant_id=tenant_id,
        supplier_id=supplier_id,
        status=status,
        order_date=order_date.isoformat() if order_date else None,
        expected_date=expected_date.isoformat() if expected_date else None,
        currency_code=currency_code,
        notes=notes,
    )


def _row_to_line(row: tuple) -> PurchaseOrderLine:
    rid, tenant_id, purchase_order_id, product_id, uom_id, quantity_ordered, quantity_received, status, unit_price, unit_price_currency = row
    return PurchaseOrderLine(
        id=rid,
        tenant_id=tenant_id,
        purchase_order_id=purchase_order_id,
        product_id=product_id,
        uom_id=uom_id,
        quantity_ordered=float(quantity_ordered),
        quantity_received=float(quantity_received),
        status=status,
        unit_price=float(unit_price),
        unit_price_currency=unit_price_currency,
    )


def _row_to_receipt(row: tuple) -> PurchaseOrderReceipt:
    (
        rid, tenant_id, purchase_order_id, location_id, status, invoice_number, invoice_date, origin_country,
        carrier, base_cost, license_fee, insurance_fee, transit_fee, transport_fee, customs_duty, total_cost, confirmed_at,
    ) = row
    return PurchaseOrderReceipt(
        id=rid,
        tenant_id=tenant_id,
        purchase_order_id=purchase_order_id,
        location_id=location_id,
        status=status,
        invoice_number=invoice_number,
        invoice_date=invoice_date.isoformat() if invoice_date else None,
        origin_country=origin_country,
        carrier=carrier,
        base_cost=float(base_cost),
        license_fee=float(license_fee),
        insurance_fee=float(insurance_fee),
        transit_fee=float(transit_fee),
        transport_fee=float(transport_fee),
        customs_duty=float(customs_duty),
        total_cost=float(total_cost),
        confirmed_at=confirmed_at.isoformat() if confirmed_at else None,
    )


def _row_to_receipt_line(row: tuple) -> PurchaseOrderReceiptLine:
    rid, tenant_id, purchase_order_receipt_id, purchase_order_line_id, quantity, lot_number, cost_per_unit = row
    return PurchaseOrderReceiptLine(
        id=rid,
        tenant_id=tenant_id,
        purchase_order_receipt_id=purchase_order_receipt_id,
        purchase_order_line_id=purchase_order_line_id,
        quantity=float(quantity),
        lot_number=lot_number,
        cost_per_unit=float(cost_per_unit),
    )


class PurchaseOrderService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    # --- Orders -------------------------------------------------------------------------

    def create_purchase_order(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        lines: list[dict],
        supplier_id: str | None = None,
        currency_code: str = "EUR",
        order_date: datetime.date | None = None,
        expected_date: datetime.date | None = None,
        notes: str | None = None,
    ) -> Result[PurchaseOrder]:
        header_validation = validate_new_purchase_order(currency_code=currency_code)
        if isinstance(header_validation, Err):
            return header_validation
        if not lines:
            return Err("INVALID_LINES", "a purchase order needs at least one line")
        for line in lines:
            line_validation = validate_new_purchase_order_line(
                quantity_ordered=line["quantity_ordered"], unit_price=line.get("unit_price", 0)
            )
            if isinstance(line_validation, Err):
                return line_validation

        order_id = str(ULID())
        self._connection.execute(
            """
            INSERT INTO procurement.purchase_orders
                (id, tenant_id, supplier_id, status, order_date, expected_date, currency_code, notes)
            VALUES (%s, %s, %s, 'draft', %s, %s, %s, %s)
            """,
            (order_id, tenant_id, supplier_id, order_date, expected_date, currency_code, notes),
        )
        for line in lines:
            self._connection.execute(
                """
                INSERT INTO procurement.purchase_order_lines
                    (id, tenant_id, purchase_order_id, product_id, uom_id, quantity_ordered, unit_price, unit_price_currency)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    str(ULID()),
                    tenant_id,
                    order_id,
                    line["product_id"],
                    line["uom_id"],
                    line["quantity_ordered"],
                    line.get("unit_price", 0),
                    line.get("unit_price_currency", "EUR"),
                ),
            )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="purchase_order.created",
            entity_type="purchase_order",
            entity_id=order_id,
            payload={"supplier_id": supplier_id, "line_count": len(lines)},
        )
        return Ok(self._get_order(tenant_id, order_id))

    def list_purchase_orders(self, *, tenant_id: str, status: str | None = None, supplier_id: str | None = None) -> list[PurchaseOrder]:
        clauses = ["tenant_id = %s"]
        params: list[object] = [tenant_id]
        if status is not None:
            clauses.append("status = %s")
            params.append(status)
        if supplier_id is not None:
            clauses.append("supplier_id = %s")
            params.append(supplier_id)
        rows = self._connection.execute(
            f"SELECT {_ORDER_COLUMNS} FROM procurement.purchase_orders WHERE {' AND '.join(clauses)} ORDER BY created_at DESC",
            params,
        ).fetchall()
        return [_row_to_order(row) for row in rows]

    def _get_order(self, tenant_id: str, order_id: str, *, for_update: bool = False) -> PurchaseOrder | None:
        suffix = " FOR UPDATE" if for_update else ""
        row = self._connection.execute(
            f"SELECT {_ORDER_COLUMNS} FROM procurement.purchase_orders WHERE id = %s AND tenant_id = %s{suffix}",
            (order_id, tenant_id),
        ).fetchone()
        return _row_to_order(row) if row else None

    def list_lines(self, *, tenant_id: str, purchase_order_id: str) -> list[PurchaseOrderLine]:
        rows = self._connection.execute(
            f"SELECT {_LINE_COLUMNS} FROM procurement.purchase_order_lines WHERE tenant_id = %s AND purchase_order_id = %s ORDER BY created_at",
            (tenant_id, purchase_order_id),
        ).fetchall()
        return [_row_to_line(row) for row in rows]

    def add_line(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        purchase_order_id: str,
        product_id: str,
        uom_id: str,
        quantity_ordered: float,
        unit_price: float = 0,
        unit_price_currency: str = "EUR",
    ) -> Result[PurchaseOrderLine]:
        order = self._get_order(tenant_id, purchase_order_id, for_update=True)
        if order is None:
            return Err("NOT_FOUND", f"purchase order {purchase_order_id} not found")
        if order.status != "draft":
            return Err("INVALID_TRANSITION", "lines can only be added while the order is in draft")
        validation = validate_new_purchase_order_line(quantity_ordered=quantity_ordered, unit_price=unit_price)
        if isinstance(validation, Err):
            return validation

        line_id = str(ULID())
        self._connection.execute(
            """
            INSERT INTO procurement.purchase_order_lines
                (id, tenant_id, purchase_order_id, product_id, uom_id, quantity_ordered, unit_price, unit_price_currency)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (line_id, tenant_id, purchase_order_id, product_id, uom_id, quantity_ordered, unit_price, unit_price_currency),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="purchase_order.line_added",
            entity_type="purchase_order",
            entity_id=purchase_order_id,
            payload={"line_id": line_id, "product_id": product_id, "quantity_ordered": quantity_ordered},
        )
        row = self._connection.execute(
            f"SELECT {_LINE_COLUMNS} FROM procurement.purchase_order_lines WHERE id = %s", (line_id,)
        ).fetchone()
        return Ok(_row_to_line(row))

    def _transition(self, *, tenant_id: str, actor_id: str, order_id: str, new_status: str) -> Result[PurchaseOrder]:
        order = self._get_order(tenant_id, order_id, for_update=True)
        if order is None:
            return Err("NOT_FOUND", f"purchase order {order_id} not found")
        result = transition_purchase_order(order, new_status)
        if isinstance(result, Err):
            return result
        self._connection.execute("UPDATE procurement.purchase_orders SET status = %s WHERE id = %s", (new_status, order_id))
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="purchase_order.status_changed",
            entity_type="purchase_order",
            entity_id=order_id,
            payload={"from_status": order.status, "to_status": new_status},
        )
        publish_event(
            self._connection,
            event_type="procurement.purchase_order.status_changed",
            producer="procurement",
            tenant_id=tenant_id,
            correlation_id=str(ULID()),
            payload={"purchase_order_id": order_id, "from_status": order.status, "to_status": new_status},
        )
        return result

    def validate_order(self, *, tenant_id: str, actor_id: str, order_id: str) -> Result[PurchaseOrder]:
        return self._transition(tenant_id=tenant_id, actor_id=actor_id, order_id=order_id, new_status="validated")

    def approve_order(self, *, tenant_id: str, actor_id: str, order_id: str) -> Result[PurchaseOrder]:
        return self._transition(tenant_id=tenant_id, actor_id=actor_id, order_id=order_id, new_status="approved")

    def place_order(self, *, tenant_id: str, actor_id: str, order_id: str) -> Result[PurchaseOrder]:
        return self._transition(tenant_id=tenant_id, actor_id=actor_id, order_id=order_id, new_status="ordered")

    def refuse_order(self, *, tenant_id: str, actor_id: str, order_id: str) -> Result[PurchaseOrder]:
        return self._transition(tenant_id=tenant_id, actor_id=actor_id, order_id=order_id, new_status="refused")

    def cancel_order(self, *, tenant_id: str, actor_id: str, order_id: str) -> Result[PurchaseOrder]:
        return self._transition(tenant_id=tenant_id, actor_id=actor_id, order_id=order_id, new_status="canceled")

    def admin_update_purchase_order(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        order_id: str,
        supplier_id: str | None = None,
        order_date: datetime.date | None = None,
        expected_date: datetime.date | None = None,
        currency_code: str | None = None,
        notes: str | None = None,
    ) -> Result[PurchaseOrder]:
        """Direct edit of header fields, gated by procurement.admin_purchase_orders. Allowed
        regardless of the order's current status -- the elevated permission is what limits
        blast radius here, matching warehouse.admin_material_receipts."""
        current = self._get_order(tenant_id, order_id, for_update=True)
        if current is None:
            return Err("NOT_FOUND", f"purchase order {order_id} not found")

        merged_currency = currency_code if currency_code is not None else current.currency_code
        validation = validate_new_purchase_order(currency_code=merged_currency)
        if isinstance(validation, Err):
            return validation

        merged_supplier = supplier_id if supplier_id is not None else current.supplier_id
        merged_order_date = order_date if order_date is not None else current.order_date
        merged_expected_date = expected_date if expected_date is not None else current.expected_date
        merged_notes = notes if notes is not None else current.notes

        self._connection.execute(
            """
            UPDATE procurement.purchase_orders
            SET supplier_id = %s, order_date = %s, expected_date = %s, currency_code = %s, notes = %s
            WHERE id = %s AND tenant_id = %s
            """,
            (merged_supplier, merged_order_date, merged_expected_date, merged_currency, merged_notes, order_id, tenant_id),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="purchase_order.updated",
            entity_type="purchase_order",
            entity_id=order_id,
            payload={
                "supplier_id": merged_supplier,
                "order_date": str(merged_order_date) if merged_order_date else None,
                "expected_date": str(merged_expected_date) if merged_expected_date else None,
                "currency_code": merged_currency,
                "notes": merged_notes,
            },
        )
        return Ok(self._get_order(tenant_id, order_id))

    # --- Goods receipts ------------------------------------------------------------------

    def create_receipt(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        purchase_order_id: str,
        location_id: str,
        lines: list[dict],
        invoice_number: str | None = None,
        invoice_date: datetime.date | None = None,
        origin_country: str | None = None,
        carrier: str | None = None,
        base_cost: float = 0,
        license_fee: float = 0,
        insurance_fee: float = 0,
        transit_fee: float = 0,
        transport_fee: float = 0,
        customs_duty: float = 0,
    ) -> Result[PurchaseOrderReceipt]:
        """Drafts a goods-receipt event covering one or more lines of one order. No stock or
        line quantities are touched yet -- that only happens on confirm_receipt, so a draft
        can be corrected freely before it's committed."""
        order = self._get_order(tenant_id, purchase_order_id)
        if order is None:
            return Err("NOT_FOUND", f"purchase order {purchase_order_id} not found")
        if order.status not in ("ordered", "partially_received"):
            return Err("INVALID_TRANSITION", f"cannot record a receipt against a purchase order in status {order.status}")
        if not lines:
            return Err("INVALID_LINES", "a goods receipt needs at least one line")
        for line in lines:
            if line["quantity"] <= 0:
                return Err("INVALID_QUANTITY", "received quantity must be positive")

        total_quantity = sum(line["quantity"] for line in lines)
        cost_result = compute_landed_cost(
            base_cost=base_cost,
            license_fee=license_fee,
            insurance_fee=insurance_fee,
            transit_fee=transit_fee,
            transport_fee=transport_fee,
            customs_duty=customs_duty,
            quantity=total_quantity,
        )
        if isinstance(cost_result, Err):
            return cost_result
        total_cost, cost_per_unit = cost_result.value

        receipt_id = str(ULID())
        self._connection.execute(
            f"""
            INSERT INTO procurement.purchase_order_receipts
                (id, tenant_id, purchase_order_id, location_id, status, invoice_number, invoice_date, origin_country,
                 carrier, base_cost, license_fee, insurance_fee, transit_fee, transport_fee, customs_duty, total_cost)
            VALUES (%s, %s, %s, %s, 'draft', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                receipt_id, tenant_id, purchase_order_id, location_id, invoice_number, invoice_date, origin_country,
                carrier, base_cost, license_fee, insurance_fee, transit_fee, transport_fee, customs_duty, total_cost,
            ),
        )
        for line in lines:
            self._connection.execute(
                """
                INSERT INTO procurement.purchase_order_receipt_lines
                    (id, tenant_id, purchase_order_receipt_id, purchase_order_line_id, quantity, lot_number, cost_per_unit)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (str(ULID()), tenant_id, receipt_id, line["purchase_order_line_id"], line["quantity"], line.get("lot_number"), cost_per_unit),
            )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="purchase_order_receipt.created",
            entity_type="purchase_order_receipt",
            entity_id=receipt_id,
            payload={"purchase_order_id": purchase_order_id, "line_count": len(lines), "total_cost": total_cost},
        )
        row = self._connection.execute(
            f"SELECT {_RECEIPT_COLUMNS} FROM procurement.purchase_order_receipts WHERE id = %s", (receipt_id,)
        ).fetchone()
        return Ok(_row_to_receipt(row))

    def list_receipts(self, *, tenant_id: str, purchase_order_id: str | None = None) -> list[PurchaseOrderReceipt]:
        clauses = ["tenant_id = %s"]
        params: list[object] = [tenant_id]
        if purchase_order_id is not None:
            clauses.append("purchase_order_id = %s")
            params.append(purchase_order_id)
        rows = self._connection.execute(
            f"SELECT {_RECEIPT_COLUMNS} FROM procurement.purchase_order_receipts WHERE {' AND '.join(clauses)} ORDER BY created_at DESC",
            params,
        ).fetchall()
        return [_row_to_receipt(row) for row in rows]

    def list_receipt_lines(self, *, tenant_id: str, purchase_order_receipt_id: str) -> list[PurchaseOrderReceiptLine]:
        rows = self._connection.execute(
            f"""
            SELECT {_RECEIPT_LINE_COLUMNS} FROM procurement.purchase_order_receipt_lines
            WHERE tenant_id = %s AND purchase_order_receipt_id = %s
            """,
            (tenant_id, purchase_order_receipt_id),
        ).fetchall()
        return [_row_to_receipt_line(row) for row in rows]

    def confirm_receipt(self, *, tenant_id: str, actor_id: str, receipt_id: str, correlation_id: str) -> Result[PurchaseOrder]:
        """Applies a drafted receipt's lines to their purchase-order lines, re-derives the
        order's receiving status from every one of its lines, and posts stock plus
        creates/tops-up the lot for each line. All in one transaction: line/order
        updates, the audit rows, the stock/lot writes, and the outbox insert commit
        or roll back together."""
        receipt_row = self._connection.execute(
            f"SELECT {_RECEIPT_COLUMNS} FROM procurement.purchase_order_receipts WHERE id = %s AND tenant_id = %s FOR UPDATE",
            (receipt_id, tenant_id),
        ).fetchone()
        if receipt_row is None:
            return Err("NOT_FOUND", f"purchase order receipt {receipt_id} not found")
        receipt = _row_to_receipt(receipt_row)

        transition_result = confirm_purchase_order_receipt(receipt.status)
        if isinstance(transition_result, Err):
            return transition_result

        order = self._get_order(tenant_id, receipt.purchase_order_id, for_update=True)
        if order is None:
            return Err("NOT_FOUND", f"purchase order {receipt.purchase_order_id} not found")

        receipt_lines = self.list_receipt_lines(tenant_id=tenant_id, purchase_order_receipt_id=receipt_id)
        event_lines: list[dict] = []
        for receipt_line in receipt_lines:
            line_row = self._connection.execute(
                f"SELECT {_LINE_COLUMNS} FROM procurement.purchase_order_lines WHERE id = %s AND tenant_id = %s FOR UPDATE",
                (receipt_line.purchase_order_line_id, tenant_id),
            ).fetchone()
            if line_row is None:
                return Err("NOT_FOUND", f"purchase order line {receipt_line.purchase_order_line_id} not found")
            line = _row_to_line(line_row)
            applied = apply_receipt_to_line(line, receipt_line.quantity)
            if isinstance(applied, Err):
                return applied
            updated_line = applied.value
            self._connection.execute(
                "UPDATE procurement.purchase_order_lines SET quantity_received = %s, status = %s WHERE id = %s",
                (updated_line.quantity_received, updated_line.status, updated_line.id),
            )
            event_lines.append(
                {
                    "product_id": updated_line.product_id,
                    "quantity": receipt_line.quantity,
                    "uom_id": updated_line.uom_id,
                    "lot_number": receipt_line.lot_number,
                }
            )

        all_line_statuses = [line.status for line in self.list_lines(tenant_id=tenant_id, purchase_order_id=order.id)]
        order_result = receive_against_order(order, all_line_statuses)
        if isinstance(order_result, Err):
            return order_result
        updated_order = order_result.value

        self._connection.execute(
            "UPDATE procurement.purchase_orders SET status = %s WHERE id = %s", (updated_order.status, updated_order.id)
        )
        self._connection.execute(
            "UPDATE procurement.purchase_order_receipts SET status = 'confirmed', confirmed_at = NOW() WHERE id = %s",
            (receipt_id,),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="purchase_order_receipt.confirmed",
            entity_type="purchase_order_receipt",
            entity_id=receipt_id,
            payload={"purchase_order_id": order.id, "from_status": order.status, "to_status": updated_order.status},
        )

        # Post stock (and top up/create the lot) synchronously, in the same
        # transaction as the rest of this confirmation, rather than only via
        # the outbox event below — this deployment has no running message
        # broker/worker to consume it, so relying on that alone silently never
        # moves stock. The event is still published (for audit/future
        # consumers) but immediately marked sent so a worker that does show up
        # later never reprocesses it and double-posts this receipt's stock.
        stock_service = StockService(self._connection)
        lot_service = LotService(self._connection)
        for event_line in event_lines:
            stock_result = stock_service.receive_stock(
                tenant_id=tenant_id,
                product_id=event_line["product_id"],
                location_id=receipt.location_id,
                quantity=event_line["quantity"],
                correlation_id=correlation_id,
                reference=f"purchase_order_receipt:{receipt_id}",
                actor_id=actor_id,
            )
            if isinstance(stock_result, Err):
                return stock_result
            if event_line["lot_number"]:
                lot_result = lot_service.receive_lot(
                    tenant_id=tenant_id,
                    product_id=event_line["product_id"],
                    location_id=receipt.location_id,
                    lot_number=event_line["lot_number"],
                    quantity=event_line["quantity"],
                    actor_id=actor_id,
                    source_type="purchase_order_receipt",
                    source_id=receipt_id,
                )
                if isinstance(lot_result, Err):
                    return lot_result

        event_id = publish_event(
            self._connection,
            event_type="procurement.purchase_order_receipt.confirmed",
            producer="procurement",
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            payload={
                "purchase_order_receipt_id": receipt_id,
                "purchase_order_id": order.id,
                "location_id": receipt.location_id,
                "lines": event_lines,
            },
        )
        self._connection.execute("UPDATE events.outbox SET sent_at = NOW() WHERE event_id = %s", (event_id,))
        return Ok(updated_order)

    def list_confirmed_receipt_line_details(self, *, tenant_id: str) -> list[dict]:
        """Flat, one-row-per-receipt-line view of every confirmed goods receipt, for
        product-level cost/trend analysis. cost_per_unit * quantity is this line's own
        share of its shipment's total landed cost -- a receipt spanning multiple products
        splits its freight/customs/insurance costs proportionally across their quantities,
        so this is the right granularity for a per-product report (unlike the receipt's own
        total_cost, which covers every line on it)."""
        rows = self._connection.execute(
            """
            SELECT l.product_id, l.uom_id, rl.quantity, r.invoice_date, rl.quantity * rl.cost_per_unit
            FROM procurement.purchase_order_receipt_lines rl
            JOIN procurement.purchase_order_receipts r ON r.id = rl.purchase_order_receipt_id AND r.tenant_id = rl.tenant_id
            JOIN procurement.purchase_order_lines l ON l.id = rl.purchase_order_line_id AND l.tenant_id = rl.tenant_id
            WHERE rl.tenant_id = %s AND r.status = 'confirmed'
            ORDER BY r.invoice_date
            """,
            (tenant_id,),
        ).fetchall()
        return [
            {
                "product_id": product_id,
                "uom_id": uom_id,
                "quantity": float(quantity),
                "invoice_date": invoice_date.isoformat() if invoice_date else None,
                "total_cost": float(total_cost),
            }
            for product_id, uom_id, quantity, invoice_date, total_cost in rows
        ]

    def cost_summary(self, *, tenant_id: str) -> list[dict]:
        rows = self._connection.execute(
            """
            SELECT l.product_id, r.origin_country,
                   SUM(rl.quantity),
                   AVG(rl.cost_per_unit),
                   COUNT(DISTINCT r.id)
            FROM procurement.purchase_order_receipt_lines rl
            JOIN procurement.purchase_order_receipts r ON r.id = rl.purchase_order_receipt_id AND r.tenant_id = rl.tenant_id
            JOIN procurement.purchase_order_lines l ON l.id = rl.purchase_order_line_id AND l.tenant_id = rl.tenant_id
            WHERE rl.tenant_id = %s AND r.status = 'confirmed'
            GROUP BY l.product_id, r.origin_country
            ORDER BY l.product_id, r.origin_country
            """,
            (tenant_id,),
        ).fetchall()
        return [
            {
                "product_id": product_id,
                "origin_country": origin_country,
                "total_quantity": float(total_quantity),
                "average_cost_per_unit": float(average_cost_per_unit),
                "receipt_count": receipt_count,
            }
            for product_id, origin_country, total_quantity, average_cost_per_unit, receipt_count in rows
        ]
