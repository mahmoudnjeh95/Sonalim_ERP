"""Sales invoices follow the delivery, as the manual has it: a billable delivery note or a shipped pick list
is billed, and a return against an invoiced delivery is credited. Orders are no longer invoiced when they
are confirmed; sales.order.confirmed is not consumed here any more."""
from __future__ import annotations

import datetime
from decimal import Decimal

import psycopg

from core.domain.result import Err
from core.events.consumers import register
from modules.finance.api.billing_service import DeliveryBillingService

VOUCHER_POSTED_CONSUMER_NAME = "finance.voucher_posted"
SHIPMENT_SHIPPED_CONSUMER_NAME = "finance.shipment_shipped"


def _event_date(envelope: dict, payload: dict) -> datetime.date:
    if payload.get("document_date"):
        return datetime.date.fromisoformat(payload["document_date"])
    return datetime.datetime.fromisoformat(envelope["occurred_at"]).date()


def _quantities(lines: list[dict], key: str = "quantity") -> dict[str, Decimal]:
    totals: dict[str, Decimal] = {}
    for line in lines:
        totals[line["product_id"]] = totals.get(line["product_id"], Decimal("0")) + Decimal(str(line[key]))
    return totals


def _handle_voucher_posted(connection: psycopg.Connection, envelope: dict) -> None:
    """A 1.0/1.1 event carries no lines, so it bills or credits nothing: those vouchers predate this rule."""
    payload = envelope["payload"]
    if "lines" not in payload:
        return
    billing = DeliveryBillingService(connection)
    if payload.get("type") == "delivery":
        if not payload.get("billable") or not payload.get("order_id"):
            return  # a re-delivery after a return, or goods with no order and so no price
        result = billing.invoice_delivery(
            tenant_id=envelope["tenant_id"], source_type="delivery_note", source_id=payload["voucher_id"],
            source_number=payload.get("number"), order_id=payload["order_id"], delivered=_quantities(payload["lines"]),
            delivered_on=_event_date(envelope, payload),
        )
    elif payload.get("type") == "return" and payload.get("return_of_voucher_id"):
        result = billing.credit_return(
            tenant_id=envelope["tenant_id"], return_id=payload["voucher_id"], return_number=payload.get("number"),
            delivery_note_ids=payload.get("delivery_note_ids") or [], order_id=payload.get("order_id"),
            returned=_quantities(payload["lines"]), returned_on=_event_date(envelope, payload),
            correlation_id=envelope.get("correlation_id") or envelope["event_id"],
        )
    else:
        return
    if isinstance(result, Err):
        raise RuntimeError(f"billing voucher {payload['voucher_id']} failed: {result.message}")


def _handle_shipment_shipped(connection: psycopg.Connection, envelope: dict) -> None:
    payload = envelope["payload"]
    if payload.get("source_type") != "sales_order":
        return
    result = DeliveryBillingService(connection).invoice_delivery(
        tenant_id=envelope["tenant_id"], source_type="shipment", source_id=payload["shipment_id"], source_number=payload.get("number"),
        order_id=payload["source_id"], delivered=_quantities(payload["lines"], "quantity_shipped"),
        delivered_on=_event_date(envelope, payload),
    )
    if isinstance(result, Err):
        raise RuntimeError(f"billing shipment {payload['shipment_id']} failed: {result.message}")


register(VOUCHER_POSTED_CONSUMER_NAME, "warehouse.voucher.posted", _handle_voucher_posted)
register(SHIPMENT_SHIPPED_CONSUMER_NAME, "warehouse.shipment.shipped", _handle_shipment_shipped)
