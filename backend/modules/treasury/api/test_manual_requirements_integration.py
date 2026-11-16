"""What the vendor manual asks of treasury beyond the first build: payments waiting on the deposit slip,
the withheld amount, the 16 March cutoff, the yearly cash journal, the grouped invoice reports, the ordre de
paiement, attachments and the editable master data. Rolled back by the db fixture."""
from __future__ import annotations

import base64
import datetime
from decimal import Decimal as D
from uuid import uuid4

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from modules.finance.api.service import InvoiceService
from modules.procurement.api.invoice_service import PurchaseInvoiceService
from modules.treasury.api.attachment_service import DocumentAttachmentService
from modules.treasury.api.document_service import DocumentService
from modules.treasury.api.instrument_service import InstrumentService
from modules.treasury.api.payment_order_service import PaymentOrderService
from modules.treasury.api.posting_service import TreasuryPostingService
from modules.treasury.api.report_service import InvoiceStatusReportService
from modules.treasury.api.service import AccountService, BankService, SettingsService

TENANT = "tenant-manual-" + uuid4().hex[:6]
TODAY = datetime.date(2026, 6, 1)


@pytest.fixture
def env(db):
    actor, customer, supplier = (str(ULID()) for _ in range(3))
    db.execute("INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
               (actor, TENANT, f"{actor}@x.local"))
    db.execute("INSERT INTO core.partners (id, tenant_id, name, kind) VALUES (%s, %s, 'Client Un', 'customer')", (customer, TENANT))
    db.execute("INSERT INTO core.partners (id, tenant_id, name, kind) VALUES (%s, %s, 'Fournisseur Un', 'supplier')", (supplier, TENANT))
    accounts = AccountService(db)
    cash = accounts.create_account(tenant_id=TENANT, actor_id=actor, kind="cash",
                                   fields={"name": "Caisse", "currency": "XOF", "opening_balance": D("1000")}).value
    second = accounts.create_account(tenant_id=TENANT, actor_id=actor, kind="cash",
                                     fields={"name": "Caisse 2", "currency": "XOF", "opening_balance": D("500"), "cash_type": "secondary"}).value
    bank = BankService(db).create_bank(tenant_id=TENANT, actor_id=actor, name="BDM").value
    branch = BankService(db).add_branch(tenant_id=TENANT, actor_id=actor, bank_id=bank["id"], name="Bamako").value
    account = accounts.create_account(tenant_id=TENANT, actor_id=actor, kind="bank",
                                      fields={"name": "BDM", "currency": "XOF", "account_number": "ML-" + uuid4().hex[:8],
                                              "branch_id": branch["id"]}).value
    return {"actor": actor, "customer": customer, "supplier": supplier, "cash": cash["id"], "second": second["id"],
            "bank": account["id"], "bank_id": bank["id"], "branch_id": branch["id"]}


def _sales_invoice(db, env, amount=1000):
    service = InvoiceService(db)
    invoice = service.create_draft_invoice(tenant_id=TENANT, partner_id=env["customer"], amount=amount, currency="XOF", actor_id=env["actor"])
    assert isinstance(service.issue_invoice(tenant_id=TENANT, actor_id=env["actor"], invoice_id=invoice.id, correlation_id="c"), Ok)
    return invoice.id


def _purchase_invoice(db, env, amount=D("750")):
    service = PurchaseInvoiceService(db)
    invoice = service.create_draft(tenant_id=TENANT, actor_id=env["actor"], partner_id=env["supplier"],
                                   supplier_invoice_number="S-" + uuid4().hex[:6], invoice_date=TODAY, amount=amount).value
    return service.validate(tenant_id=TENANT, actor_id=env["actor"], invoice_id=invoice["id"], correlation_id="c").value


def _receipt(db, env, payments, allocations=None, **kwargs):
    defaults = {"reason": "full", "with_details": bool(allocations), "doc_date": datetime.date.today()}
    return DocumentService(db).create_and_post(
        tenant_id=TENANT, actor_id=env["actor"], direction="in", partner_id=env["customer"], currency="XOF",
        payments=payments, allocations=allocations or [], correlation_id="c", **{**defaults, **kwargs})


def _balance(db, account_id):
    return AccountService(db).get_account(tenant_id=TENANT, account_id=account_id).value["balance"]


# ---- every receipt payment waits on the deposit slip ----------------------------------------------


def test_a_cash_receipt_waits_on_the_slip_and_reaches_its_own_register_when_collected(db, env):
    document = _receipt(db, env, [{"method": "cash", "amount": 300, "account_id": env["second"]}]).value
    assert _balance(db, env["second"]) == D("500")
    pending = InstrumentService(db).list_instruments(tenant_id=TENANT, status="pending")
    assert [(i["method"], i["account_name"], i["number"]) for i in pending] == [("cash", "Caisse 2", document["number"])]

    slips = InstrumentService(db).post_slip(tenant_id=TENANT, actor_id=env["actor"], account_id=None, slip_date=TODAY,
                                            items=[{"instrument_id": pending[0]["id"], "outcome": "collected"}], correlation_id="c")
    assert isinstance(slips, Ok) and len(slips.value["slips"]) == 1
    assert _balance(db, env["second"]) == D("800")
    collected = InstrumentService(db).list_instruments(tenant_id=TENANT, status="collected")[0]
    assert collected["deposit_date"] == TODAY and collected["slip_reference"] == slips.value["slips"][0]["number"]


def test_collecting_without_a_chosen_account_makes_one_slip_per_account(db, env):
    _receipt(db, env, [{"method": "cash", "amount": 100, "account_id": env["cash"]},
                       {"method": "cash", "amount": 200, "account_id": env["second"]},
                       {"method": "transfer", "amount": 400, "account_id": env["bank"]}])
    items = [{"instrument_id": i["id"], "outcome": "collected"}
             for i in InstrumentService(db).list_instruments(tenant_id=TENANT, status="pending")]
    slips = InstrumentService(db).post_slip(tenant_id=TENANT, actor_id=env["actor"], account_id=None, slip_date=TODAY, items=items, correlation_id="c")
    assert len(slips.value["slips"]) == 3
    assert (_balance(db, env["cash"]), _balance(db, env["second"]), _balance(db, env["bank"])) == (D("1100"), D("700"), D("400"))


def test_a_cheque_with_no_account_needs_one_chosen(db, env):
    _receipt(db, env, [{"method": "cheque", "amount": 100, "number": "C1", "bank_name": "BDM", "due_date": TODAY}])
    item = InstrumentService(db).list_instruments(tenant_id=TENANT, status="pending")[0]
    refused = InstrumentService(db).post_slip(tenant_id=TENANT, actor_id=env["actor"], account_id=None, slip_date=TODAY,
                                              items=[{"instrument_id": item["id"], "outcome": "collected"}], correlation_id="c")
    assert isinstance(refused, Err) and refused.code == "SLIP_ACCOUNT_REQUIRED"


def test_cash_cannot_be_collected_into_a_bank_account_and_only_cheques_go_unpaid(db, env):
    _receipt(db, env, [{"method": "cash", "amount": 100, "account_id": env["cash"]}])
    item = InstrumentService(db).list_instruments(tenant_id=TENANT, status="pending")[0]
    service = InstrumentService(db)
    wrong = service.post_slip(tenant_id=TENANT, actor_id=env["actor"], account_id=env["bank"], slip_date=TODAY,
                              items=[{"instrument_id": item["id"], "outcome": "collected"}], correlation_id="c")
    assert isinstance(wrong, Err) and wrong.code == "ACCOUNT_NOT_ELIGIBLE"
    unpaid = service.mark_unpaid(tenant_id=TENANT, actor_id=env["actor"], instrument_id=item["id"], correlation_id="c")
    assert isinstance(unpaid, Err) and unpaid.code == "UNPAID_CHEQUE_ONLY"


def test_cancelling_a_pending_cash_receipt_moves_nothing_and_a_collected_one_is_refused(db, env):
    first = _receipt(db, env, [{"method": "cash", "amount": 100, "account_id": env["cash"]}]).value
    service = DocumentService(db)
    assert isinstance(service.cancel(tenant_id=TENANT, actor_id=env["actor"], document_id=first["id"], direction="in", correlation_id="c"), Ok)
    assert _balance(db, env["cash"]) == D("1000")

    second = _receipt(db, env, [{"method": "cash", "amount": 100, "account_id": env["cash"]}]).value
    item = next(i for i in InstrumentService(db).list_instruments(tenant_id=TENANT, status="pending"))
    InstrumentService(db).post_slip(tenant_id=TENANT, actor_id=env["actor"], account_id=None, slip_date=TODAY,
                                    items=[{"instrument_id": item["id"], "outcome": "collected"}], correlation_id="c")
    refused = service.cancel(tenant_id=TENANT, actor_id=env["actor"], document_id=second["id"], direction="in", correlation_id="c")
    assert isinstance(refused, Err) and refused.code == "INSTRUMENT_ALREADY_PROCESSED"


def test_a_pending_payment_reads_as_no_account_for_the_ledger_until_collected(db, env):
    AccountService(db).update_account(tenant_id=TENANT, actor_id=env["actor"], account_id=env["cash"], changes={"ledger_account_code": "571"})
    document = _receipt(db, env, [{"method": "cash", "amount": 100, "account_id": env["cash"]}]).value
    lines = TreasuryPostingService(db).document_lines(tenant_id=TENANT, document_id=document["id"]).value
    assert lines["payments"][0]["account_id"] is None and lines["payments"][0]["ledger_account_code"] is None


def test_turned_off_cash_reaches_the_account_at_once_and_disbursements_never_wait(db, env):
    SettingsService(db).set_setting(tenant_id=TENANT, actor_id=env["actor"], key="receipts_collect_on_slip", value=False)
    _receipt(db, env, [{"method": "cash", "amount": 100, "account_id": env["cash"]}])
    assert _balance(db, env["cash"]) == D("1100")
    SettingsService(db).set_setting(tenant_id=TENANT, actor_id=env["actor"], key="receipts_collect_on_slip", value=True)
    DocumentService(db).create_and_post(
        tenant_id=TENANT, actor_id=env["actor"], direction="out", partner_id=env["supplier"], doc_date=datetime.date.today(), currency="XOF",
        with_details=False, payments=[{"method": "cash", "amount": 50, "account_id": env["cash"]}], correlation_id="c")
    assert _balance(db, env["cash"]) == D("1050")


def test_a_slip_can_carry_a_rejection_fee(db, env):
    _receipt(db, env, [{"method": "cheque", "amount": 100, "number": "C1", "bank_name": "BDM", "due_date": TODAY, "account_id": env["bank"]}])
    AccountService(db).update_account(tenant_id=TENANT, actor_id=env["actor"], account_id=env["cash"], changes={"allow_overdraft": False})
    item = InstrumentService(db).list_instruments(tenant_id=TENANT, status="pending")[0]
    done = InstrumentService(db).post_slip(
        tenant_id=TENANT, actor_id=env["actor"], account_id=env["bank"], slip_date=TODAY, correlation_id="c",
        items=[{"instrument_id": item["id"], "outcome": "unpaid", "rejection_fee": D("25"), "rejection_fee_account_id": env["cash"]}])
    assert isinstance(done, Ok)
    assert _balance(db, env["cash"]) == D("975")
    unpaid = InstrumentService(db).list_instruments(tenant_id=TENANT, status="unpaid")[0]
    assert unpaid["rejection_fee"] == D("25") and unpaid["slip_reference"] == done.value["number"]


# ---- instrument and cash fields ------------------------------------------------------------------


def test_a_cheque_keeps_its_date_branch_and_planned_deposit(db, env):
    document = _receipt(db, env, [{"method": "cheque", "amount": 100, "number": "C1", "bank_name": "BDM", "branch_name": "Bamako",
                                   "issue_date": datetime.date(2026, 5, 1), "deposit_date": datetime.date(2026, 5, 2),
                                   "slip_reference": "REF", "due_date": TODAY}]).value
    instrument = document["instruments"][0]
    assert (instrument["branch_name"], instrument["issue_date"], instrument["deposit_date"], instrument["slip_reference"]) == (
        "Bamako", datetime.date(2026, 5, 1), datetime.date(2026, 5, 2), "REF")


def test_notes_and_coins_must_add_up_to_the_cash_payment(db, env):
    bad = _receipt(db, env, [{"method": "cash", "amount": 15000, "account_id": env["cash"], "denominations": {"10000": 1}}])
    assert isinstance(bad, Err) and bad.code == "DENOMINATION_MISMATCH"
    unknown = _receipt(db, env, [{"method": "cash", "amount": 3, "account_id": env["cash"], "denominations": {"3": 1}}])
    assert isinstance(unknown, Err) and unknown.code == "INVALID_DENOMINATION"
    good = _receipt(db, env, [{"method": "cash", "amount": 15000, "account_id": env["cash"], "denominations": {"10000": 1, "5000": 1}}])
    assert good.value["payments"][0]["denominations"] == {"10000": 1, "5000": 1}


# ---- withheld amount -----------------------------------------------------------------------------


def test_what_the_customer_withheld_settles_the_invoice_alongside_the_payment(db, env):
    invoice = _sales_invoice(db, env, 1000)
    document = _receipt(db, env, [{"method": "transfer", "amount": 900, "account_id": env["bank"]}],
                        [{"invoice_id": invoice, "amount": 1000}], withheld_amount=D("100"))
    assert isinstance(document, Ok), document
    assert document.value["total"] == D("900") and document.value["withheld_amount"] == D("100") and document.value["unallocated"] == 0
    lines = TreasuryPostingService(db).document_lines(tenant_id=TENANT, document_id=document.value["id"]).value
    assert lines["withheld"] == D("100")
    assert DocumentService(db).open_invoice(TENANT, "in", invoice).value["remaining"] == 0


def test_withheld_needs_an_invoice_and_cannot_exceed_what_is_allocated(db, env):
    refused = _receipt(db, env, [{"method": "cash", "amount": 100, "account_id": env["cash"]}], withheld_amount=D("10"))
    assert isinstance(refused, Err) and refused.code == "WITHHELD_EXCEEDS_ALLOCATED"
    invoice = _sales_invoice(db, env, 1000)
    mismatch = _receipt(db, env, [{"method": "cash", "amount": 900, "account_id": env["cash"]}],
                        [{"invoice_id": invoice, "amount": 900}], withheld_amount=D("100"))
    assert isinstance(mismatch, Err) and mismatch.code == "ALLOCATION_MISMATCH"


# ---- prior-year cutoff ---------------------------------------------------------------------------


def test_last_years_invoice_can_be_added_until_the_cutoff_only(db, env):
    invoice = _sales_invoice(db, env, 100)
    this_year = datetime.date.today().year
    pay = [{"method": "cash", "amount": 100, "account_id": env["cash"]}]
    alloc = [{"invoice_id": invoice, "amount": 100}]
    next_year = this_year + 1
    before = _receipt(db, env, pay, alloc, doc_date=datetime.date(next_year, 3, 16), can_add_prior_year=False)
    assert isinstance(before, Err) and before.code == "PRIOR_YEAR_NOT_ALLOWED"
    late = _receipt(db, env, pay, alloc, doc_date=datetime.date(next_year, 3, 17), can_add_prior_year=True)
    assert isinstance(late, Err) and late.code == "PRIOR_YEAR_CUTOFF_PASSED"
    on_time = _receipt(db, env, pay, alloc, doc_date=datetime.date(next_year, 3, 16), can_add_prior_year=True)
    assert isinstance(on_time, Ok)


def test_the_cutoff_setting_is_validated_and_can_be_removed(db, env):
    settings = SettingsService(db)
    assert settings.get_settings(tenant_id=TENANT)["prior_year_invoice_cutoff"] == "03-16"
    bad = settings.set_setting(tenant_id=TENANT, actor_id=env["actor"], key="prior_year_invoice_cutoff", value="13-40")
    assert isinstance(bad, Err) and bad.code == "INVALID_SETTING"
    assert isinstance(settings.set_setting(tenant_id=TENANT, actor_id=env["actor"], key="prior_year_invoice_cutoff", value=None), Ok)


# ---- alert offsets -------------------------------------------------------------------------------


def test_a_received_cheque_alerts_from_its_due_date(db, env):
    _receipt(db, env, [{"method": "cheque", "amount": 100, "number": "C1", "bank_name": "BDM", "due_date": TODAY}])
    service = InstrumentService(db)
    assert service.alerts(tenant_id=TENANT, today=TODAY - datetime.timedelta(days=1)) == []
    assert [a["number"] for a in service.alerts(tenant_id=TENANT, today=TODAY)] == ["C1"]


def test_a_pending_cash_payment_raises_no_due_date_alert(db, env):
    _receipt(db, env, [{"method": "cash", "amount": 100, "account_id": env["cash"]}])
    assert InstrumentService(db).alerts(tenant_id=TENANT, today=datetime.date.today() + datetime.timedelta(days=400)) == []


# ---- cash journal --------------------------------------------------------------------------------


def test_the_yearly_journal_covers_every_register_with_its_third_party(db, env):
    year = datetime.date.today().year
    _receipt(db, env, [{"method": "cash", "amount": 100, "account_id": env["second"]}])
    item = InstrumentService(db).list_instruments(tenant_id=TENANT, status="pending")[0]
    InstrumentService(db).post_slip(tenant_id=TENANT, actor_id=env["actor"], account_id=None, slip_date=datetime.date.today(),
                                    items=[{"instrument_id": item["id"], "outcome": "collected"}], correlation_id="c")
    out = DocumentService(db).create_and_post(
        tenant_id=TENANT, actor_id=env["actor"], direction="out", partner_id=env["supplier"], doc_date=datetime.date.today(), currency="XOF",
        with_details=False, payments=[{"method": "cash", "amount": 40, "account_id": env["cash"]}], correlation_id="c").value

    journal = InstrumentService(db).cash_journal_for_year(tenant_id=TENANT, year=year)
    assert journal["opening_balance"] == D("1500") and journal["closing_balance"] == D("1560")
    rows = {(r["account_name"], r["partner_name"], r["money_in"], r["money_out"], r["balance"]) for r in journal["rows"]}
    assert rows == {("Caisse 2", "Client Un", D("100"), D("0"), D("600")), ("Caisse", "Fournisseur Un", D("0"), D("40"), D("960"))}
    assert out["number"] in {r["document_number"] for r in journal["rows"]}

    only_second = InstrumentService(db).cash_journal_for_year(tenant_id=TENANT, year=year, account_id=env["second"])
    assert only_second["opening_balance"] == D("500") and only_second["closing_balance"] == D("600")
    next_year = InstrumentService(db).cash_journal_for_year(tenant_id=TENANT, year=year + 1)
    assert next_year["opening_balance"] == D("1560") and next_year["rows"] == []


# ---- reports -------------------------------------------------------------------------------------


def test_the_report_groups_invoices_by_partner_and_receipt_then_those_without_one(db, env):
    paid = _sales_invoice(db, env, 1000)
    untouched = _sales_invoice(db, env, 300)
    document = _receipt(db, env, [{"method": "cash", "amount": 900, "account_id": env["cash"]}],
                        [{"invoice_id": paid, "amount": 1000}], withheld_amount=D("100")).value
    service = InvoiceStatusReportService(db)
    groups = service.by_partner_and_document(tenant_id=TENANT, direction="in", rows=service.sales(tenant_id=TENANT))
    client = next(g for g in groups if g["partner_id"] == env["customer"])
    assert client["partner_name"] == "Client Un"
    assert [(d["number"], d["net_to_pay"], d["withheld"]) for d in client["documents"]] == [(document["number"], D("900"), D("100"))]
    assert [i["invoice_id"] for i in client["documents"][0]["invoices"]] == [paid]
    assert [i["invoice_id"] for i in client["without_document"]] == [untouched]
    flat = InvoiceStatusReportService.flat_rows(groups, without_label="Sans encaissement")
    assert {(r[0], r[1]) for r in flat if r[0] == "Client Un"} == {("Client Un", document["number"]), ("Client Un", "Sans encaissement")}


# ---- ordre de paiement ---------------------------------------------------------------------------


def test_an_order_is_added_from_a_validated_purchase_invoice_and_notifies(db, env):
    invoice = _purchase_invoice(db, env)
    service = PaymentOrderService(db)
    order = service.create_invoice_order(tenant_id=TENANT, actor_id=env["actor"], order_date=TODAY, due_date=TODAY, method="cheque",
                                         invoice_id=invoice["id"], employee_user_id=env["actor"], department="Finance")
    assert isinstance(order, Ok), order
    value = order.value
    assert value["number"].startswith("ORDP-2026-") and value["partner_name"] == "Fournisseur Un"
    assert value["amount"] == D("750") and value["invoice_number"] == invoice["number"] and value["department"] == "Finance"
    assert [o["id"] for o in service.list_invoice_orders(tenant_id=TENANT)] == [value["id"]]

    assert isinstance(service.notify_invoice_order(tenant_id=TENANT, actor_id=env["actor"], order_id=value["id"], user_id=env["actor"]), Ok)
    notices = service.notifications(tenant_id=TENANT, user_id=env["actor"])
    assert notices[0]["kind"] == "invoice_payment_order" and value["number"] in notices[0]["message_fr"]


def test_an_order_refuses_a_draft_invoice_and_a_due_date_before_it(db, env):
    draft = PurchaseInvoiceService(db).create_draft(tenant_id=TENANT, actor_id=env["actor"], partner_id=env["supplier"],
                                                    supplier_invoice_number="D-" + uuid4().hex[:6], invoice_date=TODAY, amount=D("10")).value
    service = PaymentOrderService(db)
    refused = service.create_invoice_order(tenant_id=TENANT, actor_id=env["actor"], order_date=TODAY, due_date=TODAY, method="cash",
                                           invoice_id=draft["id"], employee_user_id=env["actor"])
    assert isinstance(refused, Err) and refused.code == "INVOICE_NOT_VALIDATED"
    invoice = _purchase_invoice(db, env)
    early = service.create_invoice_order(tenant_id=TENANT, actor_id=env["actor"], order_date=TODAY, due_date=TODAY - datetime.timedelta(days=1),
                                         method="cash", invoice_id=invoice["id"], employee_user_id=env["actor"])
    assert isinstance(early, Err) and early.code == "INVALID_DUE_DATE"


# ---- attachments ---------------------------------------------------------------------------------


def test_files_are_kept_on_the_document_and_can_be_removed(db, env):
    document = _receipt(db, env, [{"method": "cash", "amount": 100, "account_id": env["cash"]}]).value
    service = DocumentAttachmentService(db)
    content = base64.b64encode(b"bonjour").decode()
    added = service.add(tenant_id=TENANT, actor_id=env["actor"], direction="in", document_id=document["id"],
                        filename="reçu.pdf", content_type="application/pdf", content_base64=content)
    assert isinstance(added, Ok) and added.value["size_bytes"] == 7
    assert [a["filename"] for a in service.list(tenant_id=TENANT, direction="in", document_id=document["id"]).value] == ["reçu.pdf"]
    read = service.read(tenant_id=TENANT, direction="in", document_id=document["id"], attachment_id=added.value["id"])
    assert read.value["content"] == b"bonjour"
    wrong_side = service.read(tenant_id=TENANT, direction="out", document_id=document["id"], attachment_id=added.value["id"])
    assert isinstance(wrong_side, Err)
    assert isinstance(service.delete(tenant_id=TENANT, actor_id=env["actor"], direction="in", document_id=document["id"], attachment_id=added.value["id"]), Ok)
    assert service.list(tenant_id=TENANT, direction="in", document_id=document["id"]).value == []


def test_an_unreadable_or_empty_file_is_refused(db, env):
    document = _receipt(db, env, [{"method": "cash", "amount": 100, "account_id": env["cash"]}]).value
    service = DocumentAttachmentService(db)
    bad = service.add(tenant_id=TENANT, actor_id=env["actor"], direction="in", document_id=document["id"], filename="a", content_type=None, content_base64="!!")
    assert isinstance(bad, Err) and bad.code == "ATTACHMENT_UNREADABLE"
    empty = service.add(tenant_id=TENANT, actor_id=env["actor"], direction="in", document_id=document["id"], filename="a", content_type=None, content_base64="")
    assert isinstance(empty, Err) and empty.code == "ATTACHMENT_EMPTY"


# ---- master data ---------------------------------------------------------------------------------


def test_a_bank_and_a_branch_can_be_modified(db, env):
    banks = BankService(db)
    other = banks.create_bank(tenant_id=TENANT, actor_id=env["actor"], name="Ecobank").value
    updated = banks.update_bank(tenant_id=TENANT, actor_id=env["actor"], bank_id=env["bank_id"], changes={"name": "BDM SA", "swift": "BDMAMLBA"})
    assert updated.value["name"] == "BDM SA" and updated.value["swift"] == "BDMAMLBA"
    clash = banks.update_bank(tenant_id=TENANT, actor_id=env["actor"], bank_id=env["bank_id"], changes={"name": other["name"]})
    assert isinstance(clash, Err) and clash.code == "BANK_DUPLICATE"
    branch = banks.update_branch(tenant_id=TENANT, actor_id=env["actor"], branch_id=env["branch_id"], changes={"address": "ACI 2000", "phone": "+223 20"})
    assert branch.value["address"] == "ACI 2000" and branch.value["name"] == "Bamako"


def test_a_cash_register_is_principal_or_secondary(db, env):
    accounts = AccountService(db)
    assert accounts.get_account(tenant_id=TENANT, account_id=env["cash"]).value["cash_type"] == "principal"
    assert accounts.get_account(tenant_id=TENANT, account_id=env["second"]).value["cash_type"] == "secondary"
    assert accounts.get_account(tenant_id=TENANT, account_id=env["bank"]).value["cash_type"] is None
    bad = accounts.update_account(tenant_id=TENANT, actor_id=env["actor"], account_id=env["cash"], changes={"cash_type": "big"})
    assert isinstance(bad, Err) and bad.code == "INVALID_CASH_TYPE"


# ---- invoices are XOF at creation ----------------------------------------------------------------


def test_a_purchase_invoice_in_another_currency_is_refused(db, env):
    service = PurchaseInvoiceService(db)
    refused = service.create_draft(tenant_id=TENANT, actor_id=env["actor"], partner_id=env["supplier"], supplier_invoice_number="E1",
                                   invoice_date=TODAY, amount=D("10"), currency="EUR")
    assert isinstance(refused, Err) and refused.code == "INVOICE_CURRENCY_NOT_XOF" and refused.message_fr
    draft = service.create_draft(tenant_id=TENANT, actor_id=env["actor"], partner_id=env["supplier"], supplier_invoice_number="E2",
                                 invoice_date=TODAY, amount=D("10")).value
    changed = service.update_draft(tenant_id=TENANT, actor_id=env["actor"], invoice_id=draft["id"], changes={"currency": "EUR"})
    assert isinstance(changed, Err) and changed.code == "INVOICE_CURRENCY_NOT_XOF"


def test_a_sales_invoice_cannot_change_to_another_currency(db, env):
    invoice = _sales_invoice(db, env, 100)
    changed = InvoiceService(db).admin_update_invoice(tenant_id=TENANT, actor_id=env["actor"], invoice_id=invoice, currency="EUR")
    assert isinstance(changed, Err) and changed.code == "INVOICE_CURRENCY_NOT_XOF"
