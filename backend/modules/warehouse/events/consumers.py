from __future__ import annotations

import psycopg

from core.domain.result import Err
from core.events.consumers import register
from modules.warehouse.api.fulfillment_service import FulfillmentService
from modules.warehouse.api.lot_service import LotService
from modules.warehouse.api.service import StockService

CONSUMER_NAME = "warehouse.purchase_order_receipt_confirmed"
PRODUCT_CREATED_CONSUMER_NAME = "warehouse.product_created"
SALES_ORDER_CONFIRMED_CONSUMER_NAME = "warehouse.sales_order_confirmed"
FINISHED_GOODS_LOCATION_CODE = "produits-finis"


def _handle_purchase_order_receipt_confirmed(connection: psycopg.Connection, envelope: dict) -> None:
    payload = envelope["payload"]
    tenant_id = envelope["tenant_id"]
    correlation_id = envelope["correlation_id"]
    receipt_id = payload["purchase_order_receipt_id"]
    location_id = payload["location_id"]

    stock_service = StockService(connection)
    lot_service = LotService(connection)

    for line in payload["lines"]:
        stock_result = stock_service.receive_stock(
            tenant_id=tenant_id,
            product_id=line["product_id"],
            location_id=location_id,
            quantity=line["quantity"],
            correlation_id=correlation_id,
            reference=f"purchase_order_receipt:{receipt_id}",
        )
        if isinstance(stock_result, Err):
            raise RuntimeError(f"failed to post stock for purchase order receipt {receipt_id}: {stock_result.message}")

        if line.get("lot_number"):
            lot_result = lot_service.receive_lot(
                tenant_id=tenant_id,
                product_id=line["product_id"],
                location_id=location_id,
                lot_number=line["lot_number"],
                quantity=line["quantity"],
                source_type="purchase_order_receipt",
                source_id=receipt_id,
            )
            if isinstance(lot_result, Err):
                raise RuntimeError(f"failed to post lot stock for purchase order receipt {receipt_id}: {lot_result.message}")


def _handle_product_created(connection: psycopg.Connection, envelope: dict) -> None:
    """A new sellable product needs a home in finished-goods stock from day one,
    at 0, so it shows up in Entrepôt Produits Finis instead of being invisible
    until its first production movement. Raw materials/packaging (is_sellable
    False) don't belong in a finished-goods location, so they're skipped."""
    payload = envelope["payload"]
    tenant_id = envelope["tenant_id"]
    if not payload["is_sellable"]:
        return

    location_row = connection.execute(
        "SELECT id FROM warehouse.locations WHERE tenant_id = %s AND code = %s",
        (tenant_id, FINISHED_GOODS_LOCATION_CODE),
    ).fetchone()
    if location_row is None:
        raise RuntimeError(
            f"tenant {tenant_id!r} has no {FINISHED_GOODS_LOCATION_CODE!r} warehouse location to add product "
            f"{payload['product_id']!r} to"
        )
    location_id = location_row[0]

    connection.execute(
        """
        INSERT INTO warehouse.stock_items (tenant_id, location_id, product_id, quantity_on_hand, quantity_reserved)
        VALUES (%s, %s, %s, 0, 0)
        ON CONFLICT (tenant_id, location_id, product_id) DO NOTHING
        """,
        (tenant_id, location_id, payload["product_id"]),
    )


def _handle_sales_order_confirmed(connection: psycopg.Connection, envelope: dict) -> None:
    """Opens the pick list for a confirmed order. Sales already reserved the
    stock in its own transaction, so this only records what to pick, from
    where, and under which reservation reference.

    A 1.0 event (published before location_id/lines were added to the
    payload) carries nothing to build a pick list from; it is acknowledged
    and skipped rather than dead-lettered, since redelivering it would never
    make it any richer."""
    payload = envelope["payload"]
    if "lines" not in payload or "location_id" not in payload:
        return
    order_id = payload["order_id"]
    result = FulfillmentService(connection).create_pick_list_for_order(
        tenant_id=envelope["tenant_id"],
        order_id=order_id,
        partner_id=payload.get("partner_id"),
        location_id=payload["location_id"],
        lines=payload["lines"],
        reservation_reference=payload.get("reservation_reference", f"sales_order:{order_id}"),
    )
    if isinstance(result, Err) and result.code != "EMPTY_ORDER":
        raise RuntimeError(f"failed to open a pick list for sales order {order_id}: {result.message}")


register(CONSUMER_NAME, "procurement.purchase_order_receipt.confirmed", _handle_purchase_order_receipt_confirmed)
register(PRODUCT_CREATED_CONSUMER_NAME, "core.product.created", _handle_product_created)
register(SALES_ORDER_CONFIRMED_CONSUMER_NAME, "sales.order.confirmed", _handle_sales_order_confirmed)
