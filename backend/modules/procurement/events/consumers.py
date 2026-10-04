from __future__ import annotations

import psycopg

from core.domain.result import Err
from core.events.consumers import register
from modules.procurement.api.service import PurchaseOrderService

REPLENISHMENT_APPROVED_CONSUMER_NAME = "procurement.replenishment_approved"
MAINTENANCE_PARTS_CONSUMER_NAME = "procurement.maintenance_parts"
SYSTEM_ACTOR = "system:event-consumer"


def replenishment_note(proposal_id: str) -> str:
    return f"replenishment:{proposal_id}"


def maintenance_parts_note(request_id: str) -> str:
    return f"maintenance:{request_id}"


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


def _handle_maintenance_parts_purchase_requested(connection: psycopg.Connection, envelope: dict) -> None:
    """Drafts one purchase order for the parts a maintenance supervisor could not issue
    from stock: every line of the request on it, no supplier and no price yet -- a
    buyer completes it. Idempotent on the request through the order's notes, behind
    the processed-events log, like the replenishment draft above. Reads only the
    payload: procurement needs nothing from the maintenance module."""
    payload = envelope["payload"]
    tenant_id = envelope["tenant_id"]
    note = maintenance_parts_note(payload["request_id"])
    existing = connection.execute(
        "SELECT 1 FROM procurement.purchase_orders WHERE tenant_id = %s AND notes = %s", (tenant_id, note)
    ).fetchone()
    if existing:
        return
    result = PurchaseOrderService(connection).create_purchase_order(
        tenant_id=tenant_id,
        actor_id=SYSTEM_ACTOR,
        supplier_id=None,
        notes=note,
        lines=[
            {
                "product_id": line["product_id"],
                "uom_id": line["uom_id"],
                "quantity_ordered": line["quantity"],
                "unit_price": 0,
                "unit_price_currency": "XOF",
            }
            for line in payload["lines"]
        ],
    )
    if isinstance(result, Err):
        raise RuntimeError(
            f"failed to draft a purchase order for maintenance parts request {payload['request_id']}: {result.message}"
        )


register(
    MAINTENANCE_PARTS_CONSUMER_NAME, "maintenance.parts.purchase_requested", _handle_maintenance_parts_purchase_requested
)
