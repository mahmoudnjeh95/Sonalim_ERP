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
    # These tests are about money reaching the account at once; the deposit slip has its own in test_manual_requirements_integration.
    db.execute("INSERT INTO treasury.settings (tenant_id, key, value_json) VALUES (%s, 'receipts_collect_on_slip', 'false') ON CONFLICT DO NOTHING", (TENANT,))
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
    _cheque_receipt(db, env, 10, number="A1")  # received cheque, due 2026-04-01, alert from the due date
    service = InstrumentService(db)
    assert service.alerts(tenant_id=TENANT, today=datetime.date(2026, 3, 31)) == []
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


def _bounce(db, env, instrument_id, fee=None, account=None):
    return InstrumentService(db).mark_unpaid(tenant_id=TENANT, actor_id=env["actor"], instrument_id=instrument_id, correlation_id="c",
                                             rejection_fee=fee, rejection_fee_account_id=account)


def test_rejection_fee_reduces_the_account_appears_in_the_journal_and_is_recorded(db, env):
    instrument_id, _ = _cheque_receipt(db, env, 400)
    before = _balance(db, env["bank"])
    result = _bounce(db, env, instrument_id, D("2500"), env["bank"])
    assert isinstance(result, Ok), result
    assert (result.value["status"], result.value["rejection_fee"], result.value["rejection_fee_account_id"]) == ("unpaid", D("2500"), env["bank"])
    assert _balance(db, env["bank"]) == before - D("2500")
    journal = InstrumentService(db).cash_journal(tenant_id=TENANT, account_id=env["bank"]).value
    assert [(r["label"], r["money_out"]) for r in journal["rows"] if r["source_type"] == "instrument_rejection_fee"] == [("Frais de rejet CH1", D("2500"))]
    assert journal["closing_balance"] == before - D("2500")


def test_no_fee_is_still_allowed_and_records_nothing(db, env):
    instrument_id, _ = _cheque_receipt(db, env, 400)
    result = _bounce(db, env, instrument_id)
    assert isinstance(result, Ok), result
    assert result.value["rejection_fee"] is None


@pytest.mark.parametrize("fee, code", [(D("0"), "INVALID_REJECTION_FEE"), (D("-5"), "INVALID_REJECTION_FEE"), (D("10.50"), "AMOUNT_NOT_WHOLE")])
def test_a_zero_negative_or_fractional_fee_is_refused_and_the_cheque_stays_as_it_was(db, env, fee, code):
    instrument_id, _ = _cheque_receipt(db, env, 400)
    before = _balance(db, env["bank"])
    result = _bounce(db, env, instrument_id, fee, env["bank"])
    assert isinstance(result, Err) and result.code == code
    assert _balance(db, env["bank"]) == before
    status = db.execute("SELECT status FROM treasury.instruments WHERE id = %s", (instrument_id,)).fetchone()[0]
    assert status == "pending"


def test_a_fee_needs_its_account_and_an_account_needs_its_fee(db, env):
    instrument_id, _ = _cheque_receipt(db, env, 400)
    no_account = _bounce(db, env, instrument_id, D("100"), None)
    assert isinstance(no_account, Err) and no_account.code == "REJECTION_FEE_ACCOUNT_REQUIRED"
    no_amount = _bounce(db, env, instrument_id, None, env["bank"])
    assert isinstance(no_amount, Err) and no_amount.code == "REJECTION_FEE_REQUIRED"


def test_a_fee_the_account_cannot_cover_undoes_the_whole_rejection(db, env):
    accounts = AccountService(db)
    empty = accounts.create_account(tenant_id=TENANT, actor_id=env["actor"], kind="cash",
                                    fields={"name": "Vide", "currency": "XOF", "opening_balance": 0}).value["id"]
    instrument_id, _ = _cheque_receipt(db, env, 400)
    result = _bounce(db, env, instrument_id, D("100"), empty)
    assert isinstance(result, Err)
    assert _balance(db, empty) == D("0")
    status = db.execute("SELECT status, rejection_fee FROM treasury.instruments WHERE id = %s", (instrument_id,)).fetchone()
    assert status == ("pending", None)
    events = db.execute(
        "SELECT count(*) FROM events.outbox WHERE event_type = 'treasury.instrument.unpaid' AND payload -> 'payload' ->> 'instrument_id' = %s",
        (instrument_id,),
    ).fetchone()[0]
    assert events == 0


def test_a_fee_on_a_cheque_already_collected_comes_on_top_of_taking_the_money_back(db, env):
    instrument_id, _ = _cheque_receipt(db, env, 400)
    assert isinstance(_slip(db, env, [{"instrument_id": instrument_id, "outcome": "collected"}]), Ok)
    collected = _balance(db, env["bank"])
    assert isinstance(_bounce(db, env, instrument_id, D("100"), env["bank"]), Ok)
    assert _balance(db, env["bank"]) == collected - D("400") - D("100")


def test_the_prior_year_permission_migration_moves_grants_and_is_idempotent(db, env):
    import pathlib

    migrations = pathlib.Path(__file__).parents[1] / "migrations"
    sql = (migrations / "0007_treasury_rename_prior_year_permission.sql").read_text(encoding="utf-8")
    old, new = "treasury.add_prior_year_invoice", "treasury.admin_add_prior_year_invoice"
    both = str(ULID())
    db.execute("INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')", (both, TENANT, f"{both}@test.local"))
    for user, permission in ((env["actor"], old), (both, old), (both, new)):
        db.execute("INSERT INTO core.user_permissions (user_id, permission) VALUES (%s, %s)", (user, permission))
    role = str(ULID())
    db.execute("INSERT INTO core.roles (id, tenant_id, code, name) VALUES (%s, %s, %s, %s)", (role, TENANT, f"r-{role}", "R"))
    db.execute("INSERT INTO core.role_permissions (role_id, permission) VALUES (%s, %s)", (role, old))

    db.execute(sql)
    db.execute(sql)

    held = db.execute("SELECT user_id, permission FROM core.user_permissions WHERE user_id = ANY(%s) ORDER BY user_id", ([env["actor"], both],)).fetchall()
    assert sorted(held) == sorted([(env["actor"], new), (both, new)])
    assert db.execute("SELECT permission FROM core.role_permissions WHERE role_id = %s", (role,)).fetchall() == [(new,)]


def test_the_ledger_reads_each_documents_instruments_in_one_call(db, env):
    from modules.treasury.api.posting_service import TreasuryPostingService

    first_instrument, first_doc = _cheque_receipt(db, env, 400, number="CH-A")
    second_instrument, second_doc = _cheque_receipt(db, env, 300, number="CH-B")
    assert isinstance(_bounce(db, env, second_instrument, D("2500"), env["bank"]), Ok)
    found = TreasuryPostingService(db).instruments_of_documents(tenant_id=TENANT, document_ids=[first_doc, second_doc, "unknown"])
    assert found == {
        first_doc: [{"id": first_instrument, "number": "CH-A", "status": "pending", "has_rejection_fee": False}],
        second_doc: [{"id": second_instrument, "number": "CH-B", "status": "unpaid", "has_rejection_fee": True}],
    }
    assert TreasuryPostingService(db).instruments_of_documents(tenant_id=TENANT, document_ids=[]) == {}
