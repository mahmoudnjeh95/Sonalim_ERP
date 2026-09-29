from __future__ import annotations

import psycopg

from core.domain.result import Err
from core.events.consumers import register
from modules.procurement.api.service import PurchaseOrderService

REPLENISHMENT_APPROVED_CONSUMER_NAME = "procurement.replenishment_approved"
SYSTEM_ACTOR = "system:event-consumer"


def replenishment_note(proposal_id: str) -> str:
    return f"replenishment:{proposal_id}"


def _handle_replenishment_approved(connection: psycopg.Connection, envelope: dict) -> None:
    """Drafts the purchase order for an approved warehouse replenishment
    proposal. A draft, not a sent order: prices and the final supplier are
    still a buyer's call. Idempotent on the proposal through the order's
    notes, behind the processed-events log."""
    payload = envelope["payload"]
    tenant_id = envelope["tenant_id"]
    note = replenishment_note(payload["proposal_id"])
    existing = connection.execute(
        "SELECT 1 FROM procurement.purchase_orders WHERE tenant_id = %s AND notes = %s", (tenant_id, note)
    ).fetchone()
    if existing:
        return
    result = PurchaseOrderService(connection).create_purchase_order(
        tenant_id=tenant_id,
        actor_id=SYSTEM_ACTOR,
        supplier_id=payload.get("supplier_id"),
        notes=note,
        lines=[
            {
                "product_id": payload["product_id"],
                "uom_id": payload["uom_id"],
                "quantity_ordered": payload["quantity"],
                "unit_price": 0,
                "unit_price_currency": "XOF",
            }
        ],
    )
    if isinstance(result, Err):
        raise RuntimeError(f"failed to draft a purchase order for replenishment {payload['proposal_id']}: {result.message}")


register(REPLENISHMENT_APPROVED_CONSUMER_NAME, "warehouse.replenishment.approved", _handle_replenishment_approved)
