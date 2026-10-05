"""Invoice events into the ledger (finance consumes its own events), through the real registry."""
from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from ulid import ULID

from core.domain.result import Ok
from core.events.consumers import _process
from modules.finance.api.period_service import PeriodService
from modules.finance.api.service import InvoiceService
from modules.finance.events import ledger_consumers  # noqa: F401  (registers the handlers)
from modules.finance.testing_support import NoCommitConnection

D = Decimal


@pytest.fixture
def partner(ledger) -> str:
    partner_id = str(ULID())
    ledger["db"].execute(
        "INSERT INTO core.partners (id, tenant_id, name, kind) VALUES (%s, %s, %s, 'customer')",
        (partner_id, ledger["tenant"], f"Client {partner_id}"),
    )
    return partner_id


def _envelope(ledger, event_type, invoice_id, partner_id, *, amount=150000.0, currency="XOF",
              occurred_at="2030-03-04T10:00:00+00:00") -> dict:
    return {
        "event_id": str(ULID()),
        "event_type": event_type,
        "event_version": "1.0",
        "occurred_at": occurred_at,
        "producer": "finance",
        "tenant_id": ledger["tenant"],
        "correlation_id": str(ULID()),
        "causation_id": None,
        "payload": {"invoice_id": invoice_id, "partner_id": partner_id, "amount": amount, "currency": currency},
    }


def _deliver(ledger, envelope: dict) -> bool:
    return _process(NoCommitConnection(ledger["db"]), envelope)


def _lines(ledger, invoice_id: str, kind: str) -> list[tuple]:
    return ledger["db"].execute(
        """
        SELECT e.journal_code, l.account_code, l.debit, l.credit, l.partner_id
        FROM finance.journal_lines l
        JOIN finance.journal_entries e ON e.id = l.entry_id
        WHERE e.tenant_id = %s AND e.source_module = 'finance' AND e.source_id = %s AND e.source_kind = %s
        ORDER BY l.line_no
        """,
        (ledger["tenant"], invoice_id, kind),
    ).fetchall()


def _failure(ledger, invoice_id: str) -> tuple | None:
    return ledger["db"].execute(
        "SELECT source_kind, error_code, status FROM finance.posting_failures WHERE tenant_id = %s AND source_id = %s",
        (ledger["tenant"], invoice_id),
    ).fetchone()


def test_an_issued_invoice_posts_to_vte_with_the_customer_on_411(ledger, partner):
    invoice_id = str(ULID())
    assert _deliver(ledger, _envelope(ledger, "finance.invoice.issued", invoice_id, partner, amount=150000.4)) is True
    assert _lines(ledger, invoice_id, "invoice_issued") == [
        ("VTE", "411", D(150000), D(0), partner),
        ("VTE", "702", D(0), D(150000), None),
    ]


def test_the_same_issued_event_delivered_twice_posts_once(ledger, partner):
    invoice_id = str(ULID())
    envelope = _envelope(ledger, "finance.invoice.issued", invoice_id, partner)
    assert _deliver(ledger, envelope) is True
    assert _deliver(ledger, envelope) is True
    assert _deliver(ledger, _envelope(ledger, "finance.invoice.issued", invoice_id, partner)) is True  # new event id
    count = ledger["db"].execute(
        "SELECT count(*) FROM finance.journal_entries WHERE tenant_id = %s AND source_id = %s", (ledger["tenant"], invoice_id)
    ).fetchone()[0]
    assert count == 1


def test_a_paid_invoice_clears_the_customer_through_the_bank_once(ledger, partner):
    invoice_id = str(ULID())
    _deliver(ledger, _envelope(ledger, "finance.invoice.issued", invoice_id, partner))
    paid = _envelope(ledger, "finance.invoice.paid", invoice_id, partner, occurred_at="2030-03-20T15:00:00+00:00")
    assert _deliver(ledger, paid) is True
    assert _deliver(ledger, paid) is True
    assert _lines(ledger, invoice_id, "invoice_paid") == [
        ("BNQ", "521", D(150000), D(0), None),
        ("BNQ", "411", D(0), D(150000), partner),
    ]


def test_a_payment_before_its_invoice_is_posted_is_refused(ledger, partner):
    invoice_id = str(ULID())
    assert _deliver(ledger, _envelope(ledger, "finance.invoice.paid", invoice_id, partner)) is False
    assert _failure(ledger, invoice_id) == ("invoice_paid", "INVOICE_NOT_POSTED", "open")


def test_a_foreign_currency_invoice_is_refused_and_recorded(ledger, partner):
    invoice_id = str(ULID())
    assert _deliver(ledger, _envelope(ledger, "finance.invoice.issued", invoice_id, partner, currency="EUR")) is False
    assert _failure(ledger, invoice_id) == ("invoice_issued", "CURRENCY_NOT_XOF", "open")


def test_an_invoice_in_a_closed_period_is_refused_and_recorded(ledger, partner):
    PeriodService(ledger["db"]).close_period(
        tenant_id=ledger["tenant"], actor_id=ledger["actor"], period=datetime.date(2030, 3, 1)
    )
    invoice_id = str(ULID())
    assert _deliver(ledger, _envelope(ledger, "finance.invoice.issued", invoice_id, partner)) is False
    assert _failure(ledger, invoice_id) == ("invoice_issued", "PERIOD_CLOSED", "open")


def test_the_envelope_invoice_service_publishes_is_the_one_the_ledger_posts(ledger, partner):
    db = ledger["db"]
    year = datetime.datetime.now(datetime.timezone.utc).year
    if year != ledger["year"]:
        PeriodService(db).open_fiscal_year(tenant_id=ledger["tenant"], actor_id=ledger["actor"], year=year)
    invoices = InvoiceService(db)
    invoice = invoices.create_draft_invoice(
        tenant_id=ledger["tenant"], partner_id=partner, amount=98000, currency="XOF", actor_id=ledger["actor"]
    )
    issued = invoices.issue_invoice(
        tenant_id=ledger["tenant"], actor_id=ledger["actor"], invoice_id=invoice.id, correlation_id=str(ULID())
    )
    assert isinstance(issued, Ok)
    envelope = db.execute(
        """
        SELECT payload FROM events.outbox
        WHERE event_type = 'finance.invoice.issued' AND payload -> 'payload' ->> 'invoice_id' = %s
        """,
        (invoice.id,),
    ).fetchone()[0]
    assert _deliver(ledger, envelope) is True
    lines = _lines(ledger, invoice.id, "invoice_issued")
    assert [(code, debit, credit) for _, code, debit, credit, _ in lines] == [
        ("411", D(98000), D(0)),
        ("702", D(0), D(98000)),
    ]
