from __future__ import annotations

import psycopg

from core.domain.result import Err
from core.events.consumers import register
from modules.warehouse.api.lot_service import LotService
from modules.warehouse.api.service import StockService

CONSUMER_NAME = "warehouse.purchase_order_receipt_confirmed"


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


register(CONSUMER_NAME, "procurement.purchase_order_receipt.confirmed", _handle_purchase_order_receipt_confirmed)
