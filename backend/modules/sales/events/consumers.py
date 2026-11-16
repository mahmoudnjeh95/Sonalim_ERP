from __future__ import annotations

import psycopg

from core.domain.result import Err
from core.events.consumers import register
from modules.sales.api.service import SalesOrderService

SHIPMENT_SHIPPED_CONSUMER_NAME = "sales.shipment_shipped"
VOUCHER_POSTED_CONSUMER_NAME = "sales.voucher_posted"


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


def _handle_voucher_posted(connection: psycopg.Connection, envelope: dict) -> None:
    """Only an issue from a sales order concerns sales. A 1.0 event has no issued_to_date; a later
    voucher's event carries the whole figure, so skipping it loses nothing."""
    payload = envelope["payload"]
    if payload.get("type") != "issue" or payload.get("ref_type") != "sales_order" or "issued_to_date" not in payload:
        return
    result = SalesOrderService(connection).mark_order_issued(
        tenant_id=envelope["tenant_id"], order_id=payload["ref_id"], voucher_id=payload["voucher_id"], issued_to_date=payload["issued_to_date"]
    )
    if isinstance(result, Err):
        raise RuntimeError(f"failed to mark sales order {payload['ref_id']} shipped: {result.message}")


register(SHIPMENT_SHIPPED_CONSUMER_NAME, "warehouse.shipment.shipped", _handle_shipment_shipped)
register(VOUCHER_POSTED_CONSUMER_NAME, "warehouse.voucher.posted", _handle_voucher_posted)
