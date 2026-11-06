from __future__ import annotations

import datetime
from dataclasses import replace
from decimal import Decimal

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from core.events.outbox import publish_event
from modules.sales.domain.entities import OrderLine, SalesOrder, confirm, covers_all_lines, mark_shipped
from modules.sales.domain.pricing import check_discount_limit, check_line, check_rate
from modules.warehouse.api.service import StockService


_ORDER_COLUMNS = "partner_id, location_id, status, requested_ship_date, opportunity_id, discount_rate, quote_id"


class SalesOrderService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def _lines_of(self, order_id: str) -> tuple[OrderLine, ...]:
        rows = self._connection.execute(
            "SELECT product_id, quantity, unit_price, discount_rate, vat_rate, price_list_id FROM sales.order_lines "
            "WHERE order_id = %s ORDER BY id",
            (order_id,),
        ).fetchall()
        return tuple(
            OrderLine(product_id=r[0], quantity=float(r[1]), unit_price=float(r[2]), discount_rate=float(r[3]),
                      vat_rate=float(r[4]), price_list_id=r[5])
            for r in rows
        )

    def _order_from_row(self, order_id: str, row) -> SalesOrder:
        partner_id, location_id, status, requested_ship_date, opportunity_id, discount_rate, quote_id = row
        return SalesOrder(
            id=order_id, partner_id=partner_id, location_id=location_id, status=status, lines=self._lines_of(order_id),
            requested_ship_date=requested_ship_date, opportunity_id=opportunity_id, discount_rate=float(discount_rate),
            quote_id=quote_id,
        )

    def _insert_lines(self, tenant_id: str, order_id: str, lines) -> None:
        for line in lines:
            self._connection.execute(
                """
                INSERT INTO sales.order_lines (id, order_id, tenant_id, product_id, quantity, unit_price, discount_rate, vat_rate, price_list_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (str(ULID()), order_id, tenant_id, line.product_id, line.quantity, line.unit_price, line.discount_rate,
                 line.vat_rate, line.price_list_id),
            )

    def check_pricing(self, *, tenant_id: str, lines, discount_rate: float, may_exceed_discount: bool) -> Result[None]:
        """Every line well formed, and no discount above what the user may give (sales.settings)."""
        from modules.sales.api.pricing_service import PricingService

        checked = check_rate(Decimal(str(discount_rate)), what="discount")
        if isinstance(checked, Err):
            return checked
        for line in lines:
            checked = check_line(quantity=Decimal(str(line.quantity)), unit_price=Decimal(str(line.unit_price)),
                                 discount_rate=Decimal(str(line.discount_rate)), vat_rate=Decimal(str(line.vat_rate)))
            if isinstance(checked, Err):
                return checked
        settings = PricingService(self._connection).get_settings(tenant_id=tenant_id)
        return check_discount_limit((Decimal(str(line.discount_rate)) for line in lines), Decimal(str(discount_rate)),
                                    limit=Decimal(str(settings["max_discount_rate"])), may_exceed=may_exceed_discount)

    def create_order(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        partner_id: str,
        location_id: str,
        lines: list[OrderLine],
        requested_ship_date: datetime.date | None = None,
        opportunity_id: str | None = None,
        discount_rate: float = 0.0,
        quote_id: str | None = None,
    ) -> SalesOrder:
        """Creates a draft order as given; callers that take prices from a person run check_pricing first."""
        order_id = str(ULID())
        self._connection.execute(
            """
            INSERT INTO sales.orders (id, tenant_id, partner_id, location_id, status, requested_ship_date, opportunity_id,
                                      discount_rate, quote_id)
            VALUES (%s, %s, %s, %s, 'draft', %s, %s, %s, %s)
            """,
            (order_id, tenant_id, partner_id, location_id, requested_ship_date, opportunity_id, discount_rate, quote_id),
        )
        self._insert_lines(tenant_id, order_id, lines)
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="sales_order.created",
            entity_type="sales_order",
            entity_id=order_id,
            payload={"partner_id": partner_id, "line_count": len(lines), "opportunity_id": opportunity_id,
                     "discount_rate": discount_rate, "quote_id": quote_id},
        )
        return SalesOrder(
            id=order_id,
            partner_id=partner_id,
            location_id=location_id,
            status="draft",
            lines=tuple(lines),
            requested_ship_date=requested_ship_date,
            opportunity_id=opportunity_id,
            discount_rate=discount_rate,
            quote_id=quote_id,
        )

    def get_order(self, *, tenant_id: str, order_id: str) -> Result[SalesOrder]:
        """Public single-order read (with lines) for other modules, e.g. a warehouse issue voucher."""
        order = next((o for o in self.list_orders(tenant_id) if o.id == order_id), None)
        if order is None:
            return Err("NOT_FOUND", f"order {order_id} not found", f"commande {order_id} introuvable")
        return Ok(order)

    def list_orders(self, tenant_id: str, status: str | None = None) -> list[SalesOrder]:
        query = f"SELECT id, {_ORDER_COLUMNS} FROM sales.orders WHERE tenant_id = %s"
        params: list = [tenant_id]
        if status is not None:
            query += " AND status = %s"
            params.append(status)
        rows = self._connection.execute(query + " ORDER BY id DESC", params).fetchall()
        return [self._order_from_row(row[0], row[1:]) for row in rows]

    def admin_update_order(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        order_id: str,
        partner_id: str | None = None,
        location_id: str | None = None,
        lines: list[OrderLine] | None = None,
        requested_ship_date: datetime.date | None = None,
        discount_rate: float | None = None,
    ) -> Result[SalesOrder]:
        row = self._connection.execute(
            f"SELECT {_ORDER_COLUMNS} FROM sales.orders WHERE id = %s AND tenant_id = %s FOR UPDATE", (order_id, tenant_id)
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"order {order_id} not found", f"commande {order_id} introuvable")
        current = self._order_from_row(order_id, row)
        updated = replace(
            current,
            partner_id=partner_id if partner_id is not None else current.partner_id,
            location_id=location_id if location_id is not None else current.location_id,
            lines=tuple(lines) if lines is not None else current.lines,
            requested_ship_date=requested_ship_date if requested_ship_date is not None else current.requested_ship_date,
            discount_rate=discount_rate if discount_rate is not None else current.discount_rate,
        )
        self._connection.execute(
            "UPDATE sales.orders SET partner_id = %s, location_id = %s, requested_ship_date = %s, discount_rate = %s "
            "WHERE id = %s AND tenant_id = %s",
            (updated.partner_id, updated.location_id, updated.requested_ship_date, updated.discount_rate, order_id, tenant_id),
        )
        if lines is not None:
            self._connection.execute("DELETE FROM sales.order_lines WHERE order_id = %s", (order_id,))
            self._insert_lines(tenant_id, order_id, updated.lines)
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="sales_order.updated",
            entity_type="sales_order",
            entity_id=order_id,
            payload={"partner_id": updated.partner_id, "location_id": updated.location_id, "line_count": len(updated.lines),
                     "discount_rate": updated.discount_rate},
        )
        return Ok(updated)

    def confirm_order(self, *, tenant_id: str, actor_id: str, order_id: str, correlation_id: str,
                      override_credit: bool = False) -> Result[SalesOrder]:
        row = self._connection.execute(
            f"SELECT {_ORDER_COLUMNS} FROM sales.orders WHERE id = %s AND tenant_id = %s FOR UPDATE", (order_id, tenant_id)
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"order {order_id} not found", f"commande {order_id} introuvable")
        order = self._order_from_row(order_id, row)
        partner_id, location_id, lines = order.partner_id, order.location_id, order.lines

        result = confirm(order)
        if isinstance(result, Err):
            return result

        # Credit control, also an immediate answer from another module: finance refuses a customer over its
        # credit limit, too late paying, or on hold after dunning, unless the caller may and asked to override.
        from modules.finance.api.receivables_service import ReceivablesService

        credit = ReceivablesService(self._connection).check_order_credit(
            tenant_id=tenant_id, actor_id=actor_id, partner_id=partner_id, order_id=order_id,
            order_amount=Decimal(str(result.value.total_amount)), override=override_credit)
        if isinstance(credit, Err):
            return credit

        # Immediate stock check: a synchronous cross-module call (same transaction), not an event,
        # because confirmation needs the current answer before it can proceed.
        stock_service = StockService(self._connection)
        for line in lines:
            reservation = stock_service.reserve_stock(
                tenant_id=tenant_id,
                actor_id=actor_id,
                product_id=line.product_id,
                location_id=location_id,
                quantity=line.quantity,
                correlation_id=correlation_id,
                reference=f"sales_order:{order_id}",
            )
            if isinstance(reservation, Err):
                return reservation

        self._connection.execute("UPDATE sales.orders SET status = 'confirmed' WHERE id = %s", (order_id,))
        publish_event(
            self._connection,
            event_type="sales.order.confirmed",
            event_version="1.1",
            producer="sales",
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            payload={
                "order_id": order_id,
                "partner_id": partner_id,
                "total_amount": result.value.total_amount,
                "currency": "XOF",
                # 1.1 (additive): what warehouse needs to open a pick list
                # against the reservation made just above.
                "location_id": location_id,
                "reservation_reference": f"sales_order:{order_id}",
                "lines": [{"product_id": line.product_id, "quantity": line.quantity} for line in lines],
            },
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="sales_order.confirmed",
            entity_type="sales_order",
            entity_id=order_id,
            payload={"total_amount": result.value.total_amount},
        )
        return result

    def mark_order_issued(
        self, *, tenant_id: str, order_id: str, voucher_id: str, issued_to_date: dict[str, float], actor_id: str = "system:event-consumer"
    ) -> Result[None]:
        """Issue vouchers are the other way an order leaves: shipped once they cover every line, and
        left confirmed while part of it is still to go."""
        order = self.get_order(tenant_id=tenant_id, order_id=order_id)
        if isinstance(order, Err):
            return order
        if not covers_all_lines(order.value.lines, issued_to_date):
            return Ok(None)
        return self.mark_order_shipped(tenant_id=tenant_id, order_id=order_id, voucher_id=voucher_id, actor_id=actor_id)

    def mark_order_shipped(
        self,
        *,
        tenant_id: str,
        order_id: str,
        shipment_id: str | None = None,
        voucher_id: str | None = None,
        actor_id: str = "system:event-consumer",
    ) -> Result[None]:
        """Idempotent: an order already shipped is left alone, so a redelivered
        warehouse.shipment.shipped is harmless even past the processed-events log."""
        row = self._connection.execute(
            "SELECT status FROM sales.orders WHERE id = %s AND tenant_id = %s FOR UPDATE", (order_id, tenant_id)
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"order {order_id} not found", f"commande {order_id} introuvable")
        if row[0] == "shipped":
            return Ok(None)
        transition = mark_shipped(row[0])
        if isinstance(transition, Err):
            return transition
        self._connection.execute("UPDATE sales.orders SET status = 'shipped' WHERE id = %s AND tenant_id = %s", (order_id, tenant_id))
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="sales_order.status_changed",
            entity_type="sales_order",
            entity_id=order_id,
            payload={"from_status": row[0], "to_status": "shipped", "shipment_id": shipment_id, "voucher_id": voucher_id},
        )
        return Ok(None)
