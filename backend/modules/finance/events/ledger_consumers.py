"""The ledger's event consumers: payroll runs and invoices become journal entries.

Idempotent twice over: the registry skips an event_id this consumer already processed, and every
posting returns the entry already posted for the same (source_module, source_id, source_kind).
A refused posting (closed period, missing rule, …) is written to finance.posting_failures in its
own committed transaction, then the handler raises: the registry nacks and the message goes to
the dead-letter queue, while the run page can show why and
POST /finance/posting-failures/{id}/retry replays it once the cause is fixed."""
from __future__ import annotations

import psycopg

from core.domain.result import Err
from core.events.consumers import register
from modules.finance.api.ledger_event_postings import SOURCES, post_for_event, source_of
from modules.finance.api.posting_failure_service import PostingFailureService


class PostingRefused(Exception):
    def __init__(self, err: Err) -> None:
        super().__init__(f"{err.code}: {err.message}")
        self.err = err


def consumer_name(event_type: str) -> str:
    return "finance.ledger." + event_type.replace(".", "_")


def _treasury_posting_enabled(connection: psycopg.Connection, tenant_id: str) -> bool:
    from modules.finance.api.treasury_ledger_service import ledger_posting_enabled

    return ledger_posting_enabled(connection, tenant_id)


def handle_ledger_event(connection: psycopg.Connection, envelope: dict) -> None:
    source_module, source_id, source_kind = source_of(envelope)
    tenant_id = envelope["tenant_id"]
    if source_module == "treasury" and not _treasury_posting_enabled(connection, tenant_id):
        # Off until the accountant confirms the accounts: no entry and, deliberately, no failure row.
        return
    result = post_for_event(connection, envelope)
    failures = PostingFailureService(connection)
    if isinstance(result, Err):
        connection.rollback()
        failures.record(
            tenant_id=tenant_id,
            source_module=source_module,
            source_id=source_id,
            source_kind=source_kind,
            envelope=envelope,
            err=result,
        )
        connection.commit()
        raise PostingRefused(result)
    failures.resolve(tenant_id=tenant_id, source_module=source_module, source_id=source_id, source_kind=source_kind)


for _event_type in SOURCES:
    register(consumer_name(_event_type), _event_type, handle_ledger_event)
