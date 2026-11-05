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
    "procurement.purchase_invoice.validated": ("procurement", "invoice_id", "purchase_invoice_validated"),
    "procurement.purchase_invoice.cancelled": ("procurement", "invoice_id", "purchase_invoice_cancelled"),
    "treasury.receipt.posted": ("treasury", "receipt_id", "receipt_payment"),
    "treasury.receipt.cancelled": ("treasury", "receipt_id", "receipt_cancelled"),
    "treasury.disbursement.posted": ("treasury", "disbursement_id", "disbursement_payment"),
    "treasury.disbursement.cancelled": ("treasury", "disbursement_id", "disbursement_cancelled"),
    "treasury.instrument.collected": ("treasury", "instrument_id", "instrument_collected"),
    "treasury.instrument.unpaid": ("treasury", "instrument_id", "instrument_unpaid"),
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
    if event_type.startswith("procurement.purchase_invoice."):
        from modules.finance.api.purchase_invoice_ledger_service import PurchaseInvoiceLedgerService

        purchases = PurchaseInvoiceLedgerService(connection)
        invoice_id = str(payload["invoice_id"])
        if event_type == "procurement.purchase_invoice.validated":
            return purchases.post_validated(
                tenant_id=tenant_id, invoice_id=invoice_id, partner_id=str(payload["partner_id"]), amount=payload["amount"],
                currency=str(payload["currency"]), validated_on=occurred_on(envelope),
                correlation_id=correlation_id, causation_id=causation_id,
            )
        return purchases.post_cancelled(
            tenant_id=tenant_id, invoice_id=invoice_id, cancelled_on=occurred_on(envelope),
            correlation_id=correlation_id, causation_id=causation_id,
        )
    if event_type.startswith("treasury."):
        return _post_treasury(connection, envelope, correlation_id, causation_id)
    raise ValueError(f"the ledger has no posting for {event_type}")


def _post_treasury(
    connection: psycopg.Connection, envelope: dict, correlation_id: str, causation_id: str
) -> Result[list[dict]]:
    from modules.finance.api.treasury_ledger_service import TreasuryLedgerService

    treasury = TreasuryLedgerService(connection)
    event_type = envelope["event_type"]
    tenant_id = envelope["tenant_id"]
    payload = envelope["payload"]
    common = {"tenant_id": tenant_id, "correlation_id": correlation_id, "causation_id": causation_id}
    if event_type in ("treasury.receipt.posted", "treasury.disbursement.posted"):
        direction = "in" if event_type == "treasury.receipt.posted" else "out"
        key = "receipt_id" if direction == "in" else "disbursement_id"
        return treasury.post_document(direction=direction, document_id=str(payload[key]), **common)
    if event_type in ("treasury.receipt.cancelled", "treasury.disbursement.cancelled"):
        direction = "in" if event_type == "treasury.receipt.cancelled" else "out"
        key = "receipt_id" if direction == "in" else "disbursement_id"
        return treasury.cancel_document(
            direction=direction, document_id=str(payload[key]), cancelled_on=occurred_on(envelope), **common
        )
    if event_type == "treasury.instrument.collected":
        return treasury.post_instrument_collected(
            instrument_id=str(payload["instrument_id"]), account_id=payload.get("account_id"),
            collected_on=occurred_on(envelope), **common,
        )
    return treasury.post_instrument_unpaid(
        instrument_id=str(payload["instrument_id"]), unpaid_on=occurred_on(envelope), **common
    )


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
    if failure["source_module"] == "treasury":
        from modules.finance.api.treasury_ledger_service import ledger_posting_enabled

        if not ledger_posting_enabled(connection, tenant_id):
            return Err(
                "LEDGER_POSTING_DISABLED",
                "treasury ledger posting is switched off; turn it on before retrying",
                "la comptabilisation de la trésorerie est désactivée ; activez-la avant de réessayer",
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
