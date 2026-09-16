from __future__ import annotations

import psycopg

from core.events.consumers import register
from modules.finance.api.service import InvoiceService

CONSUMER_NAME = "finance.sales_order_confirmed"


def _handle_sales_order_confirmed(connection: psycopg.Connection, envelope: dict) -> None:
    payload = envelope["payload"]
    service = InvoiceService(connection)
    service.create_draft_invoice(
        tenant_id=envelope["tenant_id"],
        partner_id=payload["partner_id"],
        amount=payload["total_amount"],
        currency=payload["currency"],
        source_order_id=payload["order_id"],
    )


register(CONSUMER_NAME, "sales.order.confirmed", _handle_sales_order_confirmed)
