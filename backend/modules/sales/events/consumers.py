from __future__ import annotations

import psycopg

from core.domain.result import Err
from core.events.consumers import register
from modules.sales.api.service import SalesOrderService

SHIPMENT_SHIPPED_CONSUMER_NAME = "sales.shipment_shipped"


def _handle_shipment_shipped(connection: psycopg.Connection, envelope: dict) -> None:
    """A sales order is shipped once warehouse says its shipment left. Only
    shipments sourced from a sales order concern sales."""
    payload = envelope["payload"]
    if payload.get("source_type") != "sales_order":
        return
    result = SalesOrderService(connection).mark_order_shipped(
        tenant_id=envelope["tenant_id"], order_id=payload["source_id"], shipment_id=payload["shipment_id"]
    )
    if isinstance(result, Err):
        raise RuntimeError(f"failed to mark sales order {payload['source_id']} shipped: {result.message}")


register(SHIPMENT_SHIPPED_CONSUMER_NAME, "warehouse.shipment.shipped", _handle_shipment_shipped)
