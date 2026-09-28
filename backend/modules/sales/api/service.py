from __future__ import annotations

import datetime

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from core.events.outbox import publish_event
from modules.sales.domain.entities import OrderLine, SalesOrder, confirm, mark_shipped
from modules.warehouse.api.service import StockService


class SalesOrderService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

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
    ) -> SalesOrder:
        order_id = str(ULID())
        self._connection.execute(
            """
            INSERT INTO sales.orders (id, tenant_id, partner_id, location_id, status, requested_ship_date, opportunity_id)
            VALUES (%s, %s, %s, %s, 'draft', %s, %s)
            """,
            (order_id, tenant_id, partner_id, location_id, requested_ship_date, opportunity_id),
        )
        for line in lines:
            self._connection.execute(
                """
                INSERT INTO sales.order_lines (id, order_id, tenant_id, product_id, quantity, unit_price)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (str(ULID()), order_id, tenant_id, line.product_id, line.quantity, line.unit_price),
            )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="sales_order.created",
            entity_type="sales_order",
            entity_id=order_id,
            payload={"partner_id": partner_id, "line_count": len(lines), "opportunity_id": opportunity_id},
        )
        return SalesOrder(
            id=order_id,
            partner_id=partner_id,
            location_id=location_id,
            status="draft",
            lines=tuple(lines),
            requested_ship_date=requested_ship_date,
            opportunity_id=opportunity_id,
        )

    def list_orders(self, tenant_id: str, status: str | None = None) -> list[SalesOrder]:
        if status is not None:
            rows = self._connection.execute(
                """
                SELECT id, partner_id, location_id, status, requested_ship_date, opportunity_id
                FROM sales.orders WHERE tenant_id = %s AND status = %s ORDER BY id DESC
                """,
                (tenant_id, status),
            ).fetchall()
        else:
            rows = self._connection.execute(
                """
                SELECT id, partner_id, location_id, status, requested_ship_date, opportunity_id
                FROM sales.orders WHERE tenant_id = %s ORDER BY id DESC
                """,
                (tenant_id,),
            ).fetchall()

        orders = []
        for order_id, partner_id, location_id, order_status, requested_ship_date, opportunity_id in rows:
            line_rows = self._connection.execute(
                "SELECT product_id, quantity, unit_price FROM sales.order_lines WHERE order_id = %s",
                (order_id,),
            ).fetchall()
            lines = tuple(
                OrderLine(product_id=product_id, quantity=float(quantity), unit_price=float(unit_price))
                for product_id, quantity, unit_price in line_rows
            )
            orders.append(
                SalesOrder(
                    id=order_id,
                    partner_id=partner_id,
                    location_id=location_id,
                    status=order_status,
                    lines=lines,
                    requested_ship_date=requested_ship_date,
                    opportunity_id=opportunity_id,
                )
            )
        return orders

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
    ) -> Result[SalesOrder]:
        row = self._connection.execute(
            """
            SELECT partner_id, location_id, status, requested_ship_date, opportunity_id
            FROM sales.orders WHERE id = %s AND tenant_id = %s FOR UPDATE
            """,
            (order_id, tenant_id),
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"order {order_id} not found", f"commande {order_id} introuvable")
        current_partner_id, current_location_id, status, current_requested_ship_date, opportunity_id = row

        line_rows = self._connection.execute(
            "SELECT product_id, quantity, unit_price FROM sales.order_lines WHERE order_id = %s", (order_id,)
        ).fetchall()
        current_lines = tuple(
            OrderLine(product_id=product_id, quantity=float(quantity), unit_price=float(unit_price))
            for product_id, quantity, unit_price in line_rows
        )

        updated_partner_id = partner_id if partner_id is not None else current_partner_id
        updated_location_id = location_id if location_id is not None else current_location_id
        updated_lines = tuple(lines) if lines is not None else current_lines
        updated_requested_ship_date = requested_ship_date if requested_ship_date is not None else current_requested_ship_date

        self._connection.execute(
            "UPDATE sales.orders SET partner_id = %s, location_id = %s, requested_ship_date = %s WHERE id = %s AND tenant_id = %s",
            (updated_partner_id, updated_location_id, updated_requested_ship_date, order_id, tenant_id),
        )
        if lines is not None:
            self._connection.execute("DELETE FROM sales.order_lines WHERE order_id = %s", (order_id,))
            for line in updated_lines:
                self._connection.execute(
                    """
                    INSERT INTO sales.order_lines (id, order_id, tenant_id, product_id, quantity, unit_price)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (str(ULID()), order_id, tenant_id, line.product_id, line.quantity, line.unit_price),
                )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="sales_order.updated",
            entity_type="sales_order",
            entity_id=order_id,
            payload={"partner_id": updated_partner_id, "location_id": updated_location_id, "line_count": len(updated_lines)},
        )
        return Ok(
            SalesOrder(
                id=order_id,
                partner_id=updated_partner_id,
                location_id=updated_location_id,
                status=status,
                lines=updated_lines,
                requested_ship_date=updated_requested_ship_date,
                opportunity_id=opportunity_id,
            )
        )

    def confirm_order(self, *, tenant_id: str, actor_id: str, order_id: str, correlation_id: str) -> Result[SalesOrder]:
        row = self._connection.execute(
            """
            SELECT partner_id, location_id, status, requested_ship_date, opportunity_id
            FROM sales.orders WHERE id = %s AND tenant_id = %s FOR UPDATE
            """,
            (order_id, tenant_id),
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"order {order_id} not found", f"commande {order_id} introuvable")
        partner_id, location_id, status, requested_ship_date, opportunity_id = row

        line_rows = self._connection.execute(
            "SELECT product_id, quantity, unit_price FROM sales.order_lines WHERE order_id = %s",
            (order_id,),
        ).fetchall()
        lines = tuple(
            OrderLine(product_id=product_id, quantity=float(quantity), unit_price=float(unit_price))
            for product_id, quantity, unit_price in line_rows
        )
        order = SalesOrder(
            id=order_id,
            partner_id=partner_id,
            location_id=location_id,
            status=status,
            lines=lines,
            requested_ship_date=requested_ship_date,
            opportunity_id=opportunity_id,
        )

        result = confirm(order)
        if isinstance(result, Err):
            return result

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

    def mark_order_shipped(
        self, *, tenant_id: str, order_id: str, shipment_id: str, actor_id: str = "system:event-consumer"
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
            payload={"from_status": row[0], "to_status": "shipped", "shipment_id": shipment_id},
        )
        return Ok(None)
