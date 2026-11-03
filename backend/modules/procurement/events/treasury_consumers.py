from __future__ import annotations

from decimal import Decimal

import psycopg

from core.domain.result import Err
from core.events.consumers import register
from modules.procurement.api.invoice_service import apply_document_delta

SYSTEM_ACTOR = "system:event-consumer"


def _apply(connection: psycopg.Connection, envelope: dict, sign: int) -> None:
    payload = envelope["payload"]
    for allocation in payload["allocations"]:
        result = apply_document_delta(
            connection,
            tenant_id=envelope["tenant_id"],
            actor_id=SYSTEM_ACTOR,
            invoice_id=allocation["invoice_id"],
            delta=sign * Decimal(allocation["amount"]),
            event_type=envelope["event_type"],
            document_id=payload["disbursement_id"],
        )
        if isinstance(result, Err):
            # Raising rolls the whole event back and nacks it to the dead-letter queue, where the
            # cause (invoice missing or over-paid) is visible rather than silently skipped.
            raise RuntimeError(f"{result.code}: {result.message}")


def _handle_posted(connection: psycopg.Connection, envelope: dict) -> None:
    _apply(connection, envelope, 1)


def _handle_cancelled(connection: psycopg.Connection, envelope: dict) -> None:
    _apply(connection, envelope, -1)


register("procurement.treasury_disbursement_posted", "treasury.disbursement.posted", _handle_posted)
register("procurement.treasury_disbursement_cancelled", "treasury.disbursement.cancelled", _handle_cancelled)
