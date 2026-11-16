"""The batch ledger status other screens show: every state, one call for many documents, and who may ask."""
from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from fastapi import FastAPI
from ulid import ULID

pytest.importorskip("httpx", reason="the FastAPI test client needs httpx (requirements-dev.txt)")
from fastapi.testclient import TestClient  # noqa: E402

from core.domain.result import Err, Ok  # noqa: E402
from core.tenancy import TenantContext, require_session  # noqa: E402
from modules.finance.api import ledger_router as router_module  # noqa: E402
from modules.finance.api import treasury_ledger_service  # noqa: E402
from modules.finance.api.ledger_posting_service import LedgerPostingService  # noqa: E402
from modules.finance.api.ledger_status import LedgerStatusService  # noqa: E402
from modules.finance.api.posting_failure_service import PostingFailureService  # noqa: E402
from modules.finance.domain.ledger import EntryLine, SourceRef  # noqa: E402
from modules.finance.testing_support import NoCommitConnection  # noqa: E402

D = Decimal
DAY = datetime.date(2030, 1, 20)
LINES = [EntryLine("521", debit=D(5000)), EntryLine("411", credit=D(5000))]


class _Treasury:
    """Stands in for treasury's public read: the posting switch and each document's instruments."""

    def __init__(self, on: bool) -> None:
        self.on = on
        self.instruments: dict[str, list[dict]] = {}

    def ledger_posting_enabled(self, *, tenant_id: str) -> bool:
        return self.on

    def instruments_of_documents(self, *, tenant_id: str, document_ids: list[str]) -> dict[str, list[dict]]:
        return {d: self.instruments[d] for d in document_ids if d in self.instruments}


@pytest.fixture
def switch(monkeypatch) -> _Treasury:
    fake = _Treasury(False)
    monkeypatch.setattr(treasury_ledger_service, "TREASURY_API_FACTORY", lambda connection: fake)
    return fake


def _post(ledger, module, source_id, kind):
    result = LedgerPostingService(ledger["db"]).post_entry(
        tenant_id=ledger["tenant"], actor_id=ledger["actor"], journal_code="BNQ", entry_date=DAY, label="Règlement",
        lines=LINES, correlation_id=str(ULID()), source=SourceRef(module, source_id, kind), reference=source_id,
    )
    assert isinstance(result, Ok), result
    return result.value


def _refuse(ledger, module, source_id, kind):
    return PostingFailureService(ledger["db"]).record(
        tenant_id=ledger["tenant"], source_module=module, source_id=source_id, source_kind=kind,
        envelope={"event_id": str(ULID()), "event_type": "treasury.receipt.posted"},
        err=Err("RULE_MISSING", "no rule for receipt_payment", "aucune règle pour receipt_payment"),
    )


def _status(ledger, *sources):
    return LedgerStatusService(ledger["db"]).statuses(tenant_id=ledger["tenant"], sources=list(sources))


def test_every_state_in_one_call(ledger, switch):
    posted = _post(ledger, "treasury", "DOC-POSTED", "receipt_payment_cash")
    undone = _post(ledger, "treasury", "DOC-UNDONE", "receipt_payment_cash")
    LedgerPostingService(ledger["db"]).reverse_entry(
        tenant_id=ledger["tenant"], actor_id=ledger["actor"], entry_id=undone["id"], entry_date=DAY, correlation_id="c")
    failure_id = _refuse(ledger, "treasury", "DOC-REFUSED", "receipt_payment")
    statuses = _status(ledger, ("treasury", "DOC-POSTED"), ("treasury", "DOC-UNDONE"), ("treasury", "DOC-REFUSED"),
                       ("treasury", "DOC-NOTHING"), ("procurement", "INV-NOTHING"))
    assert statuses[("treasury", "DOC-POSTED")].status == "posted"
    assert [e.number for e in statuses[("treasury", "DOC-POSTED")].entries] == [posted["number"]]
    assert statuses[("treasury", "DOC-UNDONE")].status == "reversed"
    refused = statuses[("treasury", "DOC-REFUSED")]
    assert refused.status == "failed" and refused.failure.id == failure_id and refused.failure.error_message_fr.startswith("aucune règle")
    # Treasury posting is off: its untouched documents say so; other modules' read "not posted".
    assert statuses[("treasury", "DOC-NOTHING")].status == "off"
    assert statuses[("procurement", "INV-NOTHING")].status == "not_posted"
    switch.on = True
    assert _status(ledger, ("treasury", "DOC-NOTHING"))[("treasury", "DOC-NOTHING")].status == "not_posted"


def _instrument(switch, document_id, instrument_id, status, fee=False):
    switch.instruments.setdefault(document_id, []).append(
        {"id": instrument_id, "number": f"CH-{instrument_id}", "status": status, "has_rejection_fee": fee})


def test_a_treasury_document_counts_its_instruments_postings(ledger, switch):
    switch.on = True
    # A pending cheque doesn't hold the document back.
    _post(ledger, "treasury", "DOC-A", "receipt_payment_cheque")
    _instrument(switch, "DOC-A", "I-A", "pending")
    # Collected but its collection not in the ledger yet: not posted.
    _post(ledger, "treasury", "DOC-B", "receipt_payment_cheque")
    _instrument(switch, "DOC-B", "I-B", "collected")
    # Collected and posted: posted, with both entries.
    _post(ledger, "treasury", "DOC-C", "receipt_payment_cheque")
    _instrument(switch, "DOC-C", "I-C", "collected")
    collected = _post(ledger, "treasury", "I-C", "instrument_collected")
    # Bounced with a fee: the refused fee wins even though the document and the unpaid are posted.
    _post(ledger, "treasury", "DOC-D", "receipt_payment_cheque")
    _instrument(switch, "DOC-D", "I-D", "unpaid", fee=True)
    _post(ledger, "treasury", "I-D", "instrument_unpaid")
    failure_id = _refuse(ledger, "treasury", "I-D", "instrument_rejection_fee")
    statuses = _status(ledger, *[("treasury", d) for d in ("DOC-A", "DOC-B", "DOC-C", "DOC-D")])
    assert statuses[("treasury", "DOC-A")].status == "posted"
    assert [p.part for p in statuses[("treasury", "DOC-A")].parts] == ["document"]
    b = statuses[("treasury", "DOC-B")]
    assert b.status == "not_posted"
    assert [(p.part, p.instrument_number, p.status.status) for p in b.parts] == [
        ("document", None, "posted"), ("collection", "CH-I-B", "not_posted")]
    c = statuses[("treasury", "DOC-C")]
    assert c.status == "posted" and collected["id"] in [e.id for e in c.entries] and len(c.entries) == 2
    d = statuses[("treasury", "DOC-D")]
    assert d.status == "failed" and d.failure.id == failure_id
    assert [(p.part, p.status.status) for p in d.parts] == [("document", "posted"), ("unpaid", "posted"), ("rejection_fee", "failed")]


def test_a_treasury_page_costs_the_same_queries_however_many_documents(ledger, switch, monkeypatch):
    def run(n):
        for i in range(n):
            _post(ledger, "treasury", f"P{n}-{i}", "receipt_payment_cheque")
            _instrument(switch, f"P{n}-{i}", f"P{n}-I{i}", "collected")
            _post(ledger, "treasury", f"P{n}-I{i}", "instrument_collected")
        executed: list[str] = []
        original = ledger["db"].execute

        def counting(query, *args, **kwargs):
            executed.append(str(query))
            return original(query, *args, **kwargs)

        monkeypatch.setattr(ledger["db"], "execute", counting)
        statuses = _status(ledger, *[("treasury", f"P{n}-{i}") for i in range(n)])
        monkeypatch.setattr(ledger["db"], "execute", original)
        assert all(s.status == "posted" for s in statuses.values())
        return len(executed)

    # Entries and refusals; the fake treasury read and switch issue none here.
    assert run(2) == run(25) == 2


def test_a_resolved_refusal_no_longer_counts(ledger, switch):
    failure_id = _refuse(ledger, "procurement", "INV-1", "purchase_invoice_validated")
    PostingFailureService(ledger["db"]).resolve(tenant_id=ledger["tenant"], source_module="procurement", source_id="INV-1",
                                                source_kind="purchase_invoice_validated")
    assert _status(ledger, ("procurement", "INV-1"))[("procurement", "INV-1")].status == "not_posted"
    assert failure_id


def test_a_page_of_documents_costs_two_queries(ledger, switch, monkeypatch):
    for n in range(30):
        _post(ledger, "procurement", f"INV-{n}", "purchase_invoice_validated")
    executed: list[str] = []
    original = ledger["db"].execute

    def counting(query, *args, **kwargs):
        executed.append(str(query))
        return original(query, *args, **kwargs)

    monkeypatch.setattr(ledger["db"], "execute", counting)
    statuses = _status(ledger, *[("procurement", f"INV-{n}") for n in range(30)])
    assert len(statuses) == 30 and all(s.status == "posted" for s in statuses.values())
    assert len(executed) == 2


# ---- HTTP ---------------------------------------------------------------------------------------


@pytest.fixture
def api(ledger, switch, monkeypatch) -> dict:
    wrapped = NoCommitConnection(ledger["db"])
    monkeypatch.setattr(router_module, "get_connection", lambda: wrapped)
    monkeypatch.setattr("core.tenancy.get_connection", lambda: wrapped)
    app = FastAPI()
    app.include_router(router_module.router)
    app.dependency_overrides[require_session] = lambda: TenantContext(
        tenant_id=ledger["tenant"], user_id=ledger["actor"], session_token="t"
    )

    def grant(*permissions: str) -> None:
        for permission in permissions:
            ledger["db"].execute(
                "INSERT INTO core.user_permissions (user_id, permission) VALUES (%s, %s)", (ledger["actor"], permission)
            )

    return {"client": TestClient(app), "grant": grant}


def test_the_status_route_needs_the_documents_own_view_permission(api, ledger):
    posted = _post(ledger, "treasury", "DOC-1", "receipt_payment_cash")
    body = {"source_module": "treasury", "ids": ["DOC-1", "DOC-2"]}
    refused = api["client"].post("/finance/ledger-status", json=body)
    assert refused.status_code == 403 and refused.json()["detail"]["code"] == "FORBIDDEN"
    api["grant"]("treasury.view")
    response = api["client"].post("/finance/ledger-status", json=body)
    assert response.status_code == 200, response.text
    statuses = response.json()["statuses"]
    assert statuses["DOC-1"] == {
        "status": "posted",
        "entries": [{"id": posted["id"], "number": posted["number"], "entry_date": "2030-01-20"}],
        "failure": None,
        "parts": [{"part": "document", "instrument_number": None, "status": "posted",
                   "entries": [{"id": posted["id"], "number": posted["number"], "entry_date": "2030-01-20"}], "failure": None}],
    }
    assert statuses["DOC-2"]["status"] == "off"


def test_the_ledger_reader_may_ask_for_any_module_and_unknown_modules_are_refused(api):
    api["grant"]("finance.view_ledger")
    assert api["client"].post("/finance/ledger-status", json={"source_module": "procurement", "ids": ["X"]}).json() == {
        "statuses": {"X": {"status": "not_posted", "entries": [], "failure": None, "parts": []}}
    }
    unknown = api["client"].post("/finance/ledger-status", json={"source_module": "warehouse", "ids": ["X"]})
    assert unknown.status_code == 400 and unknown.json()["detail"]["code"] == "INVALID_SOURCE_MODULE"
