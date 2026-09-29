"""Which ledger posting an event asks for — shared by the consumers and by the retry of a refused
posting, so both go through exactly the same code."""
from __future__ import annotations

import datetime

import psycopg

from core.audit import record_audit
from core.domain.result import Err, Result
from modules.finance.api.posting_failure_service import FAILURE_STATUS_FR, PostingFailureService

# event type -> (source_module, payload key holding the source id, failure kind)
SOURCES: dict[str, tuple[str, str, str]] = {
    "payroll.run.approved": ("payroll", "run_id", "payroll_run"),
    "payroll.run.paid": ("payroll", "run_id", "payroll_payment"),
    "payroll.run.reversed": ("payroll", "run_id", "payroll_reversal"),
    "finance.invoice.issued": ("finance", "invoice_id", "invoice_issued"),
    "finance.invoice.paid": ("finance", "invoice_id", "invoice_paid"),
}


def source_of(envelope: dict) -> tuple[str, str, str]:
    module, id_key, kind = SOURCES[envelope["event_type"]]
    return module, str(envelope["payload"][id_key]), kind


def occurred_on(envelope: dict) -> datetime.date:
    """The business date of an event. Mali is UTC+0, so the UTC date is the local date."""
    return datetime.datetime.fromisoformat(envelope["occurred_at"]).date()


def post_for_event(connection: psycopg.Connection, envelope: dict) -> Result[list[dict]]:
    event_type = envelope["event_type"]
    tenant_id = envelope["tenant_id"]
    payload = envelope["payload"]
    correlation_id = envelope.get("correlation_id") or envelope["event_id"]
    causation_id = envelope["event_id"]
    if event_type in ("payroll.run.approved", "payroll.run.paid", "payroll.run.reversed"):
        from modules.finance.api.payroll_ledger_service import PayrollLedgerService

        payroll = PayrollLedgerService(connection)
        run_id = str(payload["run_id"])
        if event_type == "payroll.run.approved":
            return payroll.post_run(
                tenant_id=tenant_id,
                run_id=run_id,
                period=datetime.date.fromisoformat(payload["period"]),
                correlation_id=correlation_id,
                causation_id=causation_id,
            )
        if event_type == "payroll.run.paid":
            return payroll.post_payment(
                tenant_id=tenant_id,
                run_id=run_id,
                period=datetime.date.fromisoformat(payload["period"]),
                paid_on=occurred_on(envelope),
                correlation_id=correlation_id,
                causation_id=causation_id,
            )
        return payroll.post_reversal(
            tenant_id=tenant_id,
            run_id=run_id,
            reversed_on=occurred_on(envelope),
            correlation_id=correlation_id,
            causation_id=causation_id,
        )
    if event_type in ("finance.invoice.issued", "finance.invoice.paid"):
        from modules.finance.api.invoice_ledger_service import InvoiceLedgerService

        invoices = InvoiceLedgerService(connection)
        common = {
            "tenant_id": tenant_id,
            "invoice_id": str(payload["invoice_id"]),
            "partner_id": str(payload["partner_id"]),
            "amount": payload["amount"],
            "currency": str(payload["currency"]),
            "correlation_id": correlation_id,
            "causation_id": causation_id,
        }
        if event_type == "finance.invoice.issued":
            return invoices.post_issued(issued_on=occurred_on(envelope), **common)
        return invoices.post_paid(paid_on=occurred_on(envelope), **common)
    raise ValueError(f"the ledger has no posting for {event_type}")


def retry_failure(connection: psycopg.Connection, *, tenant_id: str, actor_id: str, failure_id: str) -> Result[list[dict]]:
    """Replays the stored event of an open failure. On success the failure is resolved; on a new
    refusal the caller rolls back and the failure keeps its first reason."""
    failures = PostingFailureService(connection)
    failure = failures.get(tenant_id=tenant_id, failure_id=failure_id)
    if failure is None:
        return Err(
            "NOT_FOUND",
            f"posting failure {failure_id} not found",
            f"échec d'imputation {failure_id} introuvable",
        )
    if failure["status"] != "open":
        return Err(
            "INVALID_TRANSITION",
            f"posting failure {failure_id} is already {failure['status']}",
            f"l'échec d'imputation {failure_id} est déjà {FAILURE_STATUS_FR[failure['status']]}",
        )
    result = post_for_event(connection, failure["envelope"])
    if isinstance(result, Err):
        return result
    failures.resolve(
        tenant_id=tenant_id,
        source_module=failure["source_module"],
        source_id=failure["source_id"],
        source_kind=failure["source_kind"],
        actor_id=actor_id,
    )
    record_audit(
        connection,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="posting_failure.retried",
        entity_type="posting_failure",
        entity_id=failure_id,
        payload={"entries": [entry["id"] for entry in result.value]},
    )
    return result
