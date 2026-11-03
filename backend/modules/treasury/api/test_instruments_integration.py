"""Integration tests for the cheque/draft lifecycle: deposit slips, bounced cheques, alerts, cash journal."""
from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from modules.finance.api.service import InvoiceService
from modules.finance.events import treasury_consumers as finance_consumers
from modules.treasury.api.document_service import DocumentService
from modules.treasury.api.instrument_service import InstrumentService
from modules.treasury.api.service import AccountService, BankService

TENANT = "integration-test-treasury-instruments"
D = Decimal
TODAY = datetime.date(2026, 3, 1)
DUE = datetime.date(2026, 4, 1)


@pytest.fixture
def env(db):
    actor, customer, supplier = (str(ULID()) for _ in range(3))
    db.execute("INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
               (actor, TENANT, f"{actor}@test.local"))
    for pid, kind in ((customer, "customer"), (supplier, "supplier")):
        db.execute("INSERT INTO core.partners (id, tenant_id, name, kind, status) VALUES (%s, %s, %s, %s, 'active')",
                   (pid, TENANT, kind, kind))
    bank = BankService(db).create_bank(tenant_id=TENANT, actor_id=actor, name="BDM").value
    branch = BankService(db).add_branch(tenant_id=TENANT, actor_id=actor, bank_id=bank["id"], name="Centre").value
    account = AccountService(db).create_account(
        tenant_id=TENANT, actor_id=actor, kind="bank",
        fields={"name": "BDM XOF", "currency": "XOF", "branch_id": branch["id"], "account_number": "001", "opening_balance": 5000}).value
    cash = AccountService(db).create_account(
        tenant_id=TENANT, actor_id=actor, kind="cash", fields={"name": "Caisse", "currency": "XOF", "opening_balance": 100}).value
    return {"actor": actor, "customer": customer, "supplier": supplier, "bank": account["id"], "cash": cash["id"]}


def _cheque_receipt(db, env, amount=400, method="cheque", invoice_id=None, number="CH1"):
    allocations = [{"invoice_id": invoice_id, "amount": amount}] if invoice_id else []
    doc = DocumentService(db).create_and_post(
        tenant_id=TENANT, actor_id=env["actor"], direction="in", partner_id=env["customer"], doc_date=TODAY, currency="XOF",
        payments=[{"method": method, "amount": amount, "number": number, "bank_name": "BIM", "due_date": DUE}],
        allocations=allocations, with_details=bool(invoice_id), reason="advance", correlation_id="c")
    assert isinstance(doc, Ok), doc
    return doc.value["instruments"][0]["id"], doc.value["id"]


def _balance(db, account_id):
    return AccountService(db).get_account(tenant_id=TENANT, account_id=account_id).value["balance"]


def _slip(db, env, items, account=None):
    return InstrumentService(db).post_slip(tenant_id=TENANT, actor_id=env["actor"], account_id=account or env["bank"],
                                           slip_date=TODAY, items=items, correlation_id="c")


def test_slip_collects_pending_cheques_into_the_account(db, env):
    first, _ = _cheque_receipt(db, env, 400, number="A")
    second, _ = _cheque_receipt(db, env, 100, number="B")
    result = _slip(db, env, [{"instrument_id": first, "outcome": "collected"}, {"instrument_id": second, "outcome": "collected"}])
    assert isinstance(result, Ok) and result.value["number"] == "BV-2026-000001"
    assert _balance(db, env["bank"]) == D("5500")
    again = _slip(db, env, [{"instrument_id": first, "outcome": "collected"}])
    assert isinstance(again, Err) and again.code == "INSTRUMENT_NOT_PENDING"


def test_issued_cheque_collection_debits_the_account(db, env):
    doc = DocumentService(db).create_and_post(
        tenant_id=TENANT, actor_id=env["actor"], direction="out", partner_id=env["supplier"], doc_date=TODAY, currency="XOF",
        payments=[{"method": "cheque", "amount": 700, "number": "OUT1", "bank_name": "BDM", "due_date": DUE}],
        with_details=False, correlation_id="c")
    _slip(db, env, [{"instrument_id": doc.value["instruments"][0]["id"], "outcome": "collected"}])
    assert _balance(db, env["bank"]) == D("4300")


def test_draft_cannot_be_unpaid_and_cheque_unpaid_before_credit_moves_nothing(db, env):
    draft, _ = _cheque_receipt(db, env, 50, method="draft", number="D1")
    refused = _slip(db, env, [{"instrument_id": draft, "outcome": "unpaid"}])
    assert isinstance(refused, Err) and refused.code == "UNPAID_CHEQUE_ONLY"
    cheque, _ = _cheque_receipt(db, env, 60, number="C2")
    assert isinstance(_slip(db, env, [{"instrument_id": cheque, "outcome": "unpaid"}]), Ok)
    assert _balance(db, env["bank"]) == D("5000")


def test_bounced_cheque_after_credit_reverses_balance_and_reopens_invoice(db, env):
    invoice = InvoiceService(db).create_draft_invoice(tenant_id=TENANT, partner_id=env["customer"], amount=1000.0, currency="XOF")
    InvoiceService(db).issue_invoice(tenant_id=TENANT, actor_id=env["actor"], invoice_id=invoice.id, correlation_id="c")
    instrument_id, document_id = _cheque_receipt(db, env, 400, invoice_id=invoice.id)

    posted = db.execute("SELECT payload FROM events.outbox WHERE tenant_id = %s AND event_type = 'treasury.receipt.posted' "
                        "AND payload->'payload'->>'receipt_id' = %s", (TENANT, document_id)).fetchone()[0]
    finance_consumers._handle_posted(db, posted)
    assert InvoiceService(db).get_invoice(tenant_id=TENANT, invoice_id=invoice.id).value["status"] == "partially_paid"

    _slip(db, env, [{"instrument_id": instrument_id, "outcome": "collected"}])
    assert _balance(db, env["bank"]) == D("5400")
    result = InstrumentService(db).mark_unpaid(tenant_id=TENANT, actor_id=env["actor"], instrument_id=instrument_id, correlation_id="c")
    assert isinstance(result, Ok)
    assert _balance(db, env["bank"]) == D("5000")

    unpaid = db.execute("SELECT payload FROM events.outbox WHERE tenant_id = %s AND event_type = 'treasury.instrument.unpaid'",
                        (TENANT,)).fetchone()[0]
    assert unpaid["payload"]["allocations"] == [{"invoice_id": invoice.id, "amount": "400.00"}]
    finance_consumers._handle_instrument_unpaid(db, unpaid)
    finance_consumers._handle_instrument_unpaid(db, unpaid)  # replay
    reopened = InvoiceService(db).get_invoice(tenant_id=TENANT, invoice_id=invoice.id).value
    assert reopened["status"] == "issued" and reopened["amount_paid"] == D("0")

    twice = InstrumentService(db).mark_unpaid(tenant_id=TENANT, actor_id=env["actor"], instrument_id=instrument_id, correlation_id="c")
    assert isinstance(twice, Err)


def test_slip_rejects_mobile_money_and_empty(db, env):
    assert _slip(db, env, []).code == "NO_ITEMS"
    mobile = AccountService(db).create_account(tenant_id=TENANT, actor_id=env["actor"], kind="mobile_money",
                                               fields={"name": "O", "currency": "XOF", "operator": "o", "phone": "1"}).value
    instrument, _ = _cheque_receipt(db, env, 10, number="M1")
    assert _slip(db, env, [{"instrument_id": instrument, "outcome": "collected"}], account=mobile["id"]).code == "ACCOUNT_NOT_ELIGIBLE"


def test_alerts_follow_configured_offsets(db, env):
    _cheque_receipt(db, env, 10, number="A1")  # received cheque, due 2026-04-01, alert from 04-02
    service = InstrumentService(db)
    assert service.alerts(tenant_id=TENANT, today=datetime.date(2026, 4, 1)) == []
    alerts = service.alerts(tenant_id=TENANT, today=datetime.date(2026, 4, 5))
    assert len(alerts) == 1 and alerts[0]["days_overdue"] == 4
    _cheque_receipt(db, env, 10, method="draft", number="A2")  # received draft: +15 days
    assert len(service.alerts(tenant_id=TENANT, today=datetime.date(2026, 4, 5))) == 1
    assert len(service.alerts(tenant_id=TENANT, today=datetime.date(2026, 4, 20))) == 2


def test_cash_journal_has_running_balance(db, env):
    DocumentService(db).create_and_post(
        tenant_id=TENANT, actor_id=env["actor"], direction="in", partner_id=env["customer"], doc_date=TODAY, currency="XOF",
        payments=[{"method": "cash", "amount": 50, "account_id": env["cash"]}], with_details=False, correlation_id="c")
    DocumentService(db).create_and_post(
        tenant_id=TENANT, actor_id=env["actor"], direction="out", partner_id=env["supplier"], doc_date=TODAY, currency="XOF",
        payments=[{"method": "cash", "amount": 30, "account_id": env["cash"]}], with_details=False, correlation_id="c")
    journal = InstrumentService(db).cash_journal(tenant_id=TENANT, account_id=env["cash"]).value
    assert journal["opening_balance"] == D("100") and journal["closing_balance"] == D("120")
    assert [r["balance"] for r in journal["rows"]] == [D("150"), D("120")]
    assert journal["rows"][0]["money_in"] == D("50") and journal["rows"][1]["money_out"] == D("30")
    later = InstrumentService(db).cash_journal(tenant_id=TENANT, account_id=env["cash"], date_from=TODAY + datetime.timedelta(days=1)).value
    assert later["opening_balance"] == D("120") and later["rows"] == []
