"""Integration tests for receipts and disbursements, including the consumers that turn a posted
document into invoice paid-status (run in-process on the outbox envelope)."""
from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from modules.finance.api.service import InvoiceService
from modules.finance.events import treasury_consumers as finance_consumers
from modules.procurement.api.invoice_service import PurchaseInvoiceService
from modules.procurement.events import treasury_consumers as procurement_consumers
from modules.treasury.api.document_service import DocumentService
from modules.treasury.api.service import AccountService, BankService, SettingsService

TENANT = "integration-test-treasury-documents"
D = Decimal
TODAY = datetime.date(2026, 3, 1)


@pytest.fixture
def env(db):
    # These tests are about money reaching the account at once; the deposit slip has its own in test_manual_requirements_integration.
    db.execute("INSERT INTO treasury.settings (tenant_id, key, value_json) VALUES (%s, 'receipts_collect_on_slip', 'false') ON CONFLICT DO NOTHING", (TENANT,))
    actor = str(ULID())
    customer, supplier = str(ULID()), str(ULID())
    db.execute("INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
               (actor, TENANT, f"{actor}@test.local"))
    for pid, name, kind in ((customer, "Customer", "customer"), (supplier, "Supplier", "supplier")):
        db.execute("INSERT INTO core.partners (id, tenant_id, name, kind, status) VALUES (%s, %s, %s, %s, 'active')",
                   (pid, TENANT, name, kind))
    bank = BankService(db).create_bank(tenant_id=TENANT, actor_id=actor, name="BDM").value
    branch = BankService(db).add_branch(tenant_id=TENANT, actor_id=actor, bank_id=bank["id"], name="Centre").value
    accounts = AccountService(db)
    cash = accounts.create_account(tenant_id=TENANT, actor_id=actor, kind="cash",
                                   fields={"name": "Caisse", "currency": "XOF", "opening_balance": 1000}).value
    bank_account = accounts.create_account(tenant_id=TENANT, actor_id=actor, kind="bank",
                                           fields={"name": "BDM XOF", "currency": "XOF", "branch_id": branch["id"],
                                                   "account_number": "001", "opening_balance": 0}).value
    mobile = accounts.create_account(tenant_id=TENANT, actor_id=actor, kind="mobile_money",
                                     fields={"name": "Orange", "currency": "XOF", "operator": "orange_money", "phone": "7"}).value
    return {"actor": actor, "customer": customer, "supplier": supplier, "cash": cash["id"], "bank": bank_account["id"], "mobile": mobile["id"]}


def _sales_invoice(db, env, amount=1000.0):
    invoice = InvoiceService(db).create_draft_invoice(tenant_id=TENANT, partner_id=env["customer"], amount=amount, currency="XOF")
    InvoiceService(db).issue_invoice(tenant_id=TENANT, actor_id=env["actor"], invoice_id=invoice.id, correlation_id="c")
    return invoice.id


def _purchase_invoice(db, env, amount=D("1000")):
    service = PurchaseInvoiceService(db)
    created = service.create_draft(tenant_id=TENANT, actor_id=env["actor"], partner_id=env["supplier"],
                                   supplier_invoice_number=str(ULID()), invoice_date=TODAY, amount=amount)
    service.validate(tenant_id=TENANT, actor_id=env["actor"], invoice_id=created.value["id"], correlation_id="c")
    return created.value["id"]


def _post(db, env, direction, payments, allocations=None, partner=None, **extra):
    return DocumentService(db).create_and_post(
        tenant_id=TENANT, actor_id=env["actor"], direction=direction,
        partner_id=partner or (env["customer"] if direction == "in" else env["supplier"]), doc_date=TODAY, currency="XOF",
        payments=payments, allocations=allocations, correlation_id="c", **extra,
    )


def _deliver(db, handler_module, event_type, document_id):
    """Hand the newest outbox event of this type to the consumer, as the worker would."""
    rows = db.execute(
        "SELECT payload FROM events.outbox WHERE tenant_id = %s AND event_type = %s "
        "AND (payload->'payload'->>'receipt_id' = %s OR payload->'payload'->>'disbursement_id' = %s) LIMIT 1", (TENANT, event_type, document_id, document_id)).fetchall()
    envelope = rows[0][0]
    kind = envelope["event_type"]
    handler = handler_module._handle_posted if kind.endswith("posted") else handler_module._handle_cancelled
    handler(db, envelope)
    return envelope


def _balance(db, account_id):
    return AccountService(db).get_account(tenant_id=TENANT, account_id=account_id).value["balance"]


def test_cash_receipt_moves_cash_and_pays_invoice_through_the_consumer(db, env):
    invoice_id = _sales_invoice(db, env, 1000.0)
    doc = _post(db, env, "in", [{"method": "cash", "amount": 400, "account_id": env["cash"]}],
                [{"invoice_id": invoice_id, "amount": 400}], reason="advance")
    assert isinstance(doc, Ok) and doc.value["number"] == "ENC-2026-000001"
    assert _balance(db, env["cash"]) == D("1400")

    _deliver(db, finance_consumers, "treasury.receipt.posted", doc.value["id"])
    invoice = InvoiceService(db).get_invoice(tenant_id=TENANT, invoice_id=invoice_id).value
    assert invoice["status"] == "partially_paid" and invoice["remaining"] == D("600")

    second = _post(db, env, "in", [{"method": "transfer", "amount": 600, "account_id": env["bank"]}],
                   [{"invoice_id": invoice_id, "amount": 600}])
    assert isinstance(second, Ok) and _balance(db, env["bank"]) == D("600")
    envelope = _deliver(db, finance_consumers, "treasury.receipt.posted", second.value["id"])
    assert InvoiceService(db).get_invoice(tenant_id=TENANT, invoice_id=invoice_id).value["status"] == "paid"

    finance_consumers._handle_posted(db, envelope)  # replay
    assert InvoiceService(db).get_invoice(tenant_id=TENANT, invoice_id=invoice_id).value["amount_paid"] == D("1000")


def test_manual_mark_paid_refused_once_payments_exist(db, env):
    invoice_id = _sales_invoice(db, env)
    posted = _post(db, env, "in", [{"method": "cash", "amount": 100, "account_id": env["cash"]}], [{"invoice_id": invoice_id, "amount": 100}], reason="advance")
    _deliver(db, finance_consumers, "treasury.receipt.posted", posted.value["id"])
    result = InvoiceService(db).mark_paid(tenant_id=TENANT, actor_id=env["actor"], invoice_id=invoice_id, correlation_id="c")
    assert isinstance(result, Err) and result.code in ("INVOICE_HAS_PAYMENTS", "INVALID_TRANSITION")


def test_over_allocation_and_draft_invoice_refused(db, env):
    invoice_id = _sales_invoice(db, env, 1000.0)
    over = _post(db, env, "in", [{"method": "cash", "amount": 1500, "account_id": env["cash"]}], [{"invoice_id": invoice_id, "amount": 1500}])
    assert isinstance(over, Err) and over.code == "OVER_ALLOCATION"
    draft = InvoiceService(db).create_draft_invoice(tenant_id=TENANT, partner_id=env["customer"], amount=100.0, currency="XOF")
    refused = _post(db, env, "in", [{"method": "cash", "amount": 100, "account_id": env["cash"]}], [{"invoice_id": draft.id, "amount": 100}])
    assert isinstance(refused, Err) and refused.code == "INVOICE_NOT_VALIDATED"
    assert _balance(db, env["cash"]) == D("1000")


def test_account_kind_and_currency_rules(db, env):
    wrong_kind = _post(db, env, "in", [{"method": "cash", "amount": 10, "account_id": env["bank"]}], with_details=False)
    assert isinstance(wrong_kind, Err) and wrong_kind.code == "ACCOUNT_KIND_MISMATCH"
    missing = _post(db, env, "in", [{"method": "mobile_money", "amount": 10}], with_details=False)
    assert isinstance(missing, Err) and missing.code == "ACCOUNT_REQUIRED"
    ok = _post(db, env, "in", [{"method": "mobile_money", "amount": 10, "account_id": env["mobile"]}], with_details=False)
    assert isinstance(ok, Ok) and _balance(db, env["mobile"]) == D("10")


def test_cheque_creates_pending_instrument_and_moves_nothing(db, env):
    doc = _post(db, env, "in", [{"method": "cheque", "amount": 300, "number": "CH1", "bank_name": "BIM", "due_date": datetime.date(2026, 4, 1)}],
                with_details=False)
    assert isinstance(doc, Ok)
    assert doc.value["instruments"][0]["status"] == "pending"
    assert _balance(db, env["cash"]) == D("1000") and _balance(db, env["bank"]) == D("0")


def test_cash_limit_enforced_when_configured(db, env):
    SettingsService(db).set_setting(tenant_id=TENANT, actor_id=env["actor"], key="cash_payment_limit", value=500)
    refused = _post(db, env, "in", [{"method": "cash", "amount": 600, "account_id": env["cash"]}], with_details=False)
    assert isinstance(refused, Err) and refused.code == "CASH_LIMIT_EXCEEDED"


def test_prior_year_invoice_needs_permission(db, env):
    service = PurchaseInvoiceService(db)
    created = service.create_draft(tenant_id=TENANT, actor_id=env["actor"], partner_id=env["supplier"], supplier_invoice_number="OLD",
                                   invoice_date=datetime.date(2025, 6, 1), amount=D("100"))
    service.validate(tenant_id=TENANT, actor_id=env["actor"], invoice_id=created.value["id"], correlation_id="c")
    pay = [{"method": "cash", "amount": 100, "account_id": env["cash"]}]
    alloc = [{"invoice_id": created.value["id"], "amount": 100}]
    refused = _post(db, env, "out", pay, alloc)
    assert isinstance(refused, Err) and refused.code == "PRIOR_YEAR_NOT_ALLOWED"
    allowed = _post(db, env, "out", pay, alloc, can_add_prior_year=True)
    assert isinstance(allowed, Ok)


def test_disbursement_pays_purchase_invoice_and_cancel_reverses(db, env):
    invoice_id = _purchase_invoice(db, env, D("1000"))
    doc = _post(db, env, "out", [{"method": "transfer", "amount": 1000, "account_id": env["bank"]}], [{"invoice_id": invoice_id, "amount": 1000}])
    assert isinstance(doc, Err) and doc.code == "INSUFFICIENT_BALANCE"

    _post(db, env, "in", [{"method": "transfer", "amount": 1500, "account_id": env["bank"]}], with_details=False)
    doc = _post(db, env, "out", [{"method": "transfer", "amount": 1000, "account_id": env["bank"]}], [{"invoice_id": invoice_id, "amount": 1000}])
    assert isinstance(doc, Ok) and doc.value["number"].startswith("DEC-2026-")
    assert _balance(db, env["bank"]) == D("500")
    _deliver(db, procurement_consumers, "treasury.disbursement.posted", doc.value["id"])
    assert PurchaseInvoiceService(db).get_invoice(tenant_id=TENANT, invoice_id=invoice_id).value["status"] == "paid"

    cancelled = DocumentService(db).cancel(tenant_id=TENANT, actor_id=env["actor"], document_id=doc.value["id"],
                                           direction="out", correlation_id="c")
    assert isinstance(cancelled, Ok) and cancelled.value["status"] == "cancelled"
    assert _balance(db, env["bank"]) == D("1500")
    _deliver(db, procurement_consumers, "treasury.disbursement.cancelled", doc.value["id"])
    restored = PurchaseInvoiceService(db).get_invoice(tenant_id=TENANT, invoice_id=invoice_id).value
    assert restored["status"] == "validated" and restored["amount_paid"] == D("0")
    again = DocumentService(db).cancel(tenant_id=TENANT, actor_id=env["actor"], document_id=doc.value["id"],
                                       direction="out", correlation_id="c")
    assert isinstance(again, Err) and again.code == "DOCUMENT_NOT_POSTED"


def test_cancel_refused_when_instrument_collected(db, env):
    doc = _post(db, env, "in", [{"method": "cheque", "amount": 50, "number": "CH9", "bank_name": "BIM", "due_date": TODAY}], with_details=False)
    db.execute("UPDATE treasury.instruments SET status = 'collected' WHERE document_id = %s", (doc.value["id"],))
    result = DocumentService(db).cancel(tenant_id=TENANT, actor_id=env["actor"], document_id=doc.value["id"], direction="in", correlation_id="c")
    assert isinstance(result, Err) and result.code == "INSTRUMENT_ALREADY_PROCESSED"


def test_listing_filters_by_direction(db, env):
    _post(db, env, "in", [{"method": "cash", "amount": 10, "account_id": env["cash"]}], with_details=False)
    assert len(DocumentService(db).list(tenant_id=TENANT, direction="in")) == 1
    assert DocumentService(db).list(tenant_id=TENANT, direction="out") == []


def test_two_documents_cannot_both_claim_the_same_remaining_before_events_are_applied(db, env):
    invoice_id = _sales_invoice(db, env, 1000.0)
    first = _post(db, env, "in", [{"method": "cash", "amount": 700, "account_id": env["cash"]}], [{"invoice_id": invoice_id, "amount": 700}], reason="advance")
    assert isinstance(first, Ok)
    # The finance consumer has not run yet, so the invoice still reads 1000 remaining.
    assert InvoiceService(db).get_invoice(tenant_id=TENANT, invoice_id=invoice_id).value["remaining"] == D("1000")
    second = _post(db, env, "in", [{"method": "cash", "amount": 400, "account_id": env["cash"]}], [{"invoice_id": invoice_id, "amount": 400}], reason="advance")
    assert isinstance(second, Err) and second.code == "OVER_ALLOCATION"
    fits = _post(db, env, "in", [{"method": "cash", "amount": 300, "account_id": env["cash"]}], [{"invoice_id": invoice_id, "amount": 300}], reason="advance")
    assert isinstance(fits, Ok)
    open_view = DocumentService(db).open_invoice(TENANT, "in", invoice_id).value
    assert open_view["remaining"] == D("0")
    DocumentService(db).cancel(tenant_id=TENANT, actor_id=env["actor"], document_id=first.value["id"], direction="in", correlation_id="c")
    assert DocumentService(db).open_invoice(TENANT, "in", invoice_id).value["remaining"] == D("700")


def test_a_refused_document_leaves_nothing_behind(db, env):
    before = db.execute("SELECT count(*) FROM treasury.documents WHERE tenant_id = %s", (TENANT,)).fetchone()[0]
    refused = _post(db, env, "out", [{"method": "cash", "amount": 5000, "account_id": env["cash"]}], with_details=False)
    assert isinstance(refused, Err) and refused.code == "INSUFFICIENT_BALANCE"
    assert db.execute("SELECT count(*) FROM treasury.documents WHERE tenant_id = %s", (TENANT,)).fetchone()[0] == before
    assert db.execute("SELECT count(*) FROM events.outbox WHERE tenant_id = %s AND event_type = 'treasury.disbursement.posted'", (TENANT,)).fetchone()[0] == 0
    assert _balance(db, env["cash"]) == D("1000")


def test_posting_service_exposes_ledger_codes_and_the_unallocated_advance(db, env):
    from modules.treasury.api.posting_service import TreasuryPostingService

    AccountService(db).update_account(tenant_id=TENANT, actor_id=env["actor"], account_id=env["bank"], changes={"ledger_account_code": "521"})
    doc = _post(db, env, "in", [{"method": "transfer", "amount": 800, "account_id": env["bank"]},
                                {"method": "cheque", "amount": 200, "number": "C9", "bank_name": "BIM", "due_date": TODAY}],
                with_details=False)
    lines = TreasuryPostingService(db).document_lines(tenant_id=TENANT, document_id=doc.value["id"]).value
    assert lines["direction"] == "in" and lines["unallocated"] == D("1000")
    by_method = {p["method"]: p for p in lines["payments"]}
    assert by_method["transfer"]["ledger_account_code"] == "521" and by_method["cheque"]["account_id"] is None
    instrument = TreasuryPostingService(db).instrument_lines(tenant_id=TENANT, instrument_id=doc.value["instruments"][0]["id"]).value
    assert instrument["status"] == "pending" and instrument["document_number"] == doc.value["number"]
    assert isinstance(TreasuryPostingService(db).document_lines(tenant_id=TENANT, document_id="nope"), Err)


# ---- XOF and whole francs only -------------------------------------------------------------------

def test_an_account_in_another_currency_or_with_cents_is_refused(db, env):
    accounts = AccountService(db)
    euro = accounts.create_account(tenant_id=TENANT, actor_id=env["actor"], kind="cash", fields={"name": "E", "currency": "EUR"})
    assert isinstance(euro, Err) and euro.code == "TREASURY_CURRENCY_NOT_XOF"
    cents = accounts.create_account(tenant_id=TENANT, actor_id=env["actor"], kind="cash",
                                    fields={"name": "C", "currency": "XOF", "opening_balance": "10.50"})
    assert isinstance(cents, Err) and cents.code == "AMOUNT_NOT_WHOLE"

    fresh = accounts.create_account(tenant_id=TENANT, actor_id=env["actor"], kind="cash", fields={"name": "F", "currency": "XOF"}).value
    changed = accounts.update_account(tenant_id=TENANT, actor_id=env["actor"], account_id=fresh["id"], changes={"currency": "USD"})
    assert isinstance(changed, Err) and changed.code == "TREASURY_CURRENCY_NOT_XOF"
    changed = accounts.update_account(tenant_id=TENANT, actor_id=env["actor"], account_id=fresh["id"], changes={"opening_balance": "0.50"})
    assert isinstance(changed, Err) and changed.code == "AMOUNT_NOT_WHOLE"


def test_a_document_in_another_currency_or_with_cents_is_refused_and_moves_nothing(db, env):
    before = _balance(db, env["cash"])
    other = DocumentService(db).create_and_post(
        tenant_id=TENANT, actor_id=env["actor"], direction="in", partner_id=env["customer"], doc_date=TODAY, currency="EUR",
        payments=[{"method": "cash", "amount": 100, "account_id": env["cash"]}], reason="advance", with_details=False, correlation_id="c")
    assert isinstance(other, Err) and other.code == "TREASURY_CURRENCY_NOT_XOF"
    cents = _post(db, env, "in", [{"method": "cash", "amount": "100.50", "account_id": env["cash"]}], reason="advance", with_details=False)
    assert isinstance(cents, Err) and cents.code == "AMOUNT_NOT_WHOLE"
    cheque = _post(db, env, "in", [{"method": "cheque", "amount": "100.50", "number": "C", "bank_name": "B", "due_date": TODAY}],
                   reason="advance", with_details=False)
    assert isinstance(cheque, Err) and cheque.code == "AMOUNT_NOT_WHOLE"
    assert _balance(db, env["cash"]) == before


def test_a_payment_order_on_a_disbursement_that_is_not_whole_xof_is_refused(db, env):
    from modules.treasury.api.payment_order_service import PaymentOrderService

    doc = _post(db, env, "out", [{"method": "cash", "amount": 100, "account_id": env["cash"]}], reason="advance", with_details=False).value
    orders = PaymentOrderService(db)
    db.execute("UPDATE treasury.documents SET currency = 'EUR' WHERE id = %s", (doc["id"],))
    refused = orders.create_for_disbursement(tenant_id=TENANT, actor_id=env["actor"], disbursement_id=doc["id"])
    assert isinstance(refused, Err) and refused.code == "TREASURY_CURRENCY_NOT_XOF"
    db.execute("UPDATE treasury.documents SET currency = 'XOF', total = 100.50 WHERE id = %s", (doc["id"],))
    refused = orders.create_for_disbursement(tenant_id=TENANT, actor_id=env["actor"], disbursement_id=doc["id"])
    assert isinstance(refused, Err) and refused.code == "AMOUNT_NOT_WHOLE"


def test_a_sales_invoice_of_1000_50_is_settled_by_1000_and_not_stuck_on_50_cents(db, env):
    invoice_id = _sales_invoice(db, env, 1000.50)
    service = DocumentService(db)
    assert service.open_invoice(TENANT, "in", invoice_id).value["remaining"] == D("1000")

    too_much = _post(db, env, "in", [{"method": "cash", "amount": 1001, "account_id": env["cash"]}],
                     [{"invoice_id": invoice_id, "amount": 1001}])
    assert isinstance(too_much, Err) and too_much.code == "OVER_ALLOCATION"
    cents = _post(db, env, "in", [{"method": "cash", "amount": "1000.50", "account_id": env["cash"]}],
                  [{"invoice_id": invoice_id, "amount": "1000.50"}])
    assert isinstance(cents, Err) and cents.code == "AMOUNT_NOT_WHOLE"

    first = _post(db, env, "in", [{"method": "cash", "amount": 600, "account_id": env["cash"]}],
                  [{"invoice_id": invoice_id, "amount": 600}], reason="advance")
    _deliver(db, finance_consumers, "treasury.receipt.posted", first.value["id"])
    invoice = InvoiceService(db).get_invoice(tenant_id=TENANT, invoice_id=invoice_id).value
    assert (invoice["status"], invoice["amount_paid"], invoice["remaining"]) == ("partially_paid", D("600"), D("400.50"))
    assert service.open_invoice(TENANT, "in", invoice_id).value["remaining"] == D("400")

    second = _post(db, env, "in", [{"method": "cash", "amount": 400, "account_id": env["cash"]}],
                   [{"invoice_id": invoice_id, "amount": 400}])
    assert isinstance(second, Ok), second
    _deliver(db, finance_consumers, "treasury.receipt.posted", second.value["id"])
    invoice = InvoiceService(db).get_invoice(tenant_id=TENANT, invoice_id=invoice_id).value
    assert (invoice["status"], invoice["amount_paid"], invoice["remaining"]) == ("paid", D("1000"), D("0"))


def test_a_purchase_invoice_of_1000_50_is_settled_by_1000_and_not_stuck_on_50_cents(db, env):
    invoice_id = _purchase_invoice(db, env, D("1000.50"))
    doc = _post(db, env, "out", [{"method": "cash", "amount": 1000, "account_id": env["cash"]}], [{"invoice_id": invoice_id, "amount": 1000}])
    assert isinstance(doc, Ok), doc
    _deliver(db, procurement_consumers, "treasury.disbursement.posted", doc.value["id"])
    invoice = PurchaseInvoiceService(db).get_invoice(tenant_id=TENANT, invoice_id=invoice_id).value
    assert (invoice["status"], invoice["amount_paid"], invoice["remaining"]) == ("paid", D("1000"), D("0"))


def test_cancelling_the_payment_of_a_settled_invoice_with_cents_reopens_it(db, env):
    invoice_id = _sales_invoice(db, env, 1000.50)
    doc = _post(db, env, "in", [{"method": "cash", "amount": 1000, "account_id": env["cash"]}], [{"invoice_id": invoice_id, "amount": 1000}])
    _deliver(db, finance_consumers, "treasury.receipt.posted", doc.value["id"])
    assert InvoiceService(db).get_invoice(tenant_id=TENANT, invoice_id=invoice_id).value["status"] == "paid"
    assert isinstance(DocumentService(db).cancel(tenant_id=TENANT, actor_id=env["actor"], document_id=doc.value["id"], direction="in", correlation_id="c"), Ok)
    _deliver(db, finance_consumers, "treasury.receipt.cancelled", doc.value["id"])
    invoice = InvoiceService(db).get_invoice(tenant_id=TENANT, invoice_id=invoice_id).value
    assert (invoice["status"], invoice["amount_paid"], invoice["remaining"]) == ("issued", D("0"), D("1000.50"))


def test_an_invoice_in_another_currency_cannot_be_settled_through_treasury(db, env):
    sales = InvoiceService(db).create_draft_invoice(tenant_id=TENANT, partner_id=env["customer"], amount=500.0, currency="EUR")
    InvoiceService(db).issue_invoice(tenant_id=TENANT, actor_id=env["actor"], invoice_id=sales.id, correlation_id="c")
    refused = _post(db, env, "in", [{"method": "cash", "amount": 500, "account_id": env["cash"]}], [{"invoice_id": sales.id, "amount": 500}])
    assert isinstance(refused, Err) and refused.code == "INVOICE_CURRENCY_NOT_XOF"
    assert "XOF" in refused.message_fr

    service = PurchaseInvoiceService(db)
    created = service.create_draft(tenant_id=TENANT, actor_id=env["actor"], partner_id=env["supplier"], supplier_invoice_number=str(ULID()),
                                   invoice_date=TODAY, amount=D("500"))
    # Such an invoice can no longer be created; one from before that rule is what this guards against.
    db.execute("UPDATE procurement.purchase_invoices SET currency = 'USD' WHERE id = %s", (created.value["id"],))
    service.validate(tenant_id=TENANT, actor_id=env["actor"], invoice_id=created.value["id"], correlation_id="c")
    refused = _post(db, env, "out", [{"method": "cash", "amount": 500, "account_id": env["cash"]}], [{"invoice_id": created.value["id"], "amount": 500}])
    assert isinstance(refused, Err) and refused.code == "INVOICE_CURRENCY_NOT_XOF"
