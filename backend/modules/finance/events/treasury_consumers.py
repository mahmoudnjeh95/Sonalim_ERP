from __future__ import annotations

from decimal import Decimal

import psycopg

from core.domain.result import Err
from core.events.consumers import register
from modules.finance.api.service import InvoiceService

SYSTEM_ACTOR = "system:event-consumer"


def _apply(connection: psycopg.Connection, envelope: dict, sign: int) -> None:
    payload = envelope["payload"]
    service = InvoiceService(connection)
    for allocation in payload["allocations"]:
        result = service.apply_payment_delta(
            tenant_id=envelope["tenant_id"],
            actor_id=SYSTEM_ACTOR,
            invoice_id=allocation["invoice_id"],
            delta=sign * Decimal(allocation["amount"]),
            event_type=envelope["event_type"],
            document_id=payload["receipt_id"],
        )
        if isinstance(result, Err):
            raise RuntimeError(f"{result.code}: {result.message}")


def _handle_posted(connection: psycopg.Connection, envelope: dict) -> None:
    _apply(connection, envelope, 1)


def _handle_cancelled(connection: psycopg.Connection, envelope: dict) -> None:
    _apply(connection, envelope, -1)


register("finance.treasury_receipt_posted", "treasury.receipt.posted", _handle_posted)
register("finance.treasury_receipt_cancelled", "treasury.receipt.cancelled", _handle_cancelled)


def _handle_instrument_unpaid(connection: psycopg.Connection, envelope: dict) -> None:
    """A bounced cheque takes its amount back off the invoices it paid (receipts only)."""
    payload = envelope["payload"]
    if payload["direction"] != "in":
        return
    service = InvoiceService(connection)
    for allocation in payload["allocations"]:
        result = service.apply_payment_delta(
            tenant_id=envelope["tenant_id"], actor_id=SYSTEM_ACTOR, invoice_id=allocation["invoice_id"],
            delta=-Decimal(allocation["amount"]), event_type=envelope["event_type"], document_id=payload["instrument_id"],
        )
        if isinstance(result, Err):
            raise RuntimeError(f"{result.code}: {result.message}")


register("finance.treasury_instrument_unpaid", "treasury.instrument.unpaid", _handle_instrument_unpaid)
