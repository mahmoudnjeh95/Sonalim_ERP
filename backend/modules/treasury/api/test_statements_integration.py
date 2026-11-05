"""Integration tests for bank statement import, partner assignment, reconciliation and the invoice reports."""
from __future__ import annotations

import base64
import datetime
import io
from decimal import Decimal

import pytest
from openpyxl import Workbook
from ulid import ULID

from core.domain.result import Err, Ok
from modules.finance.api.service import InvoiceService
from modules.treasury.api.document_service import DocumentService
from modules.treasury.api.instrument_service import InstrumentService
from modules.treasury.api.report_service import InvoiceStatusReportService, bucket_for, tabular_response
from modules.treasury.api.service import AccountService, BankService
from modules.treasury.api.statement_service import StatementImportService

TENANT = "integration-test-treasury-statements"
D = Decimal
DAY = datetime.date(2026, 3, 5)

CSV = "DATE;LIBELLE;DEBIT;CREDIT;SOLDE\n05-Mar-26;VIREMENT CLIENT;1000;;6000\n06-Mar-26;FRAIS BANCAIRES;;50;5950\n"


def b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


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
    cash = AccountService(db).create_account(tenant_id=TENANT, actor_id=actor, kind="cash", fields={"name": "Caisse", "currency": "XOF"}).value
    return {"actor": actor, "customer": customer, "supplier": supplier, "bank": account["id"], "cash": cash["id"]}


def _import(db, env, text=CSV, commit=True, filename="releve.csv"):
    return StatementImportService(db).import_statement(
        tenant_id=TENANT, actor_id=env["actor"], account_id=env["bank"], filename=filename, content_base64=b64(text), commit=commit)


def test_preview_writes_nothing_and_commit_inserts(db, env):
    preview = _import(db, env, commit=False)
    assert isinstance(preview, Ok) and len(preview.value["new_lines"]) == 2 and not preview.value["committed"]
    assert StatementImportService(db).list_lines(tenant_id=TENANT, account_id=env["bank"]) == []
    committed = _import(db, env)
    assert committed.value["committed"]
    lines = StatementImportService(db).list_lines(tenant_id=TENANT, account_id=env["bank"])
    assert [l["label"] for l in lines] == ["VIREMENT CLIENT", "FRAIS BANCAIRES"]


def test_reimport_skips_known_lines_and_refuses_empty_commit(db, env):
    _import(db, env)
    again = _import(db, env, commit=False)
    assert len(again.value["duplicate_lines"]) == 2 and again.value["new_lines"] == []
    refused = _import(db, env)
    assert isinstance(refused, Err) and refused.code == "STATEMENT_DUPLICATE_LINE"
    extended = _import(db, env, CSV + "07-Mar-26;AUTRE;200;;6150\n")
    assert extended.value["committed"] and len(extended.value["new_lines"]) == 1


def test_bad_rows_block_commit_but_show_in_preview(db, env):
    bad = CSV + "nope;X;5;;\n"
    preview = _import(db, env, bad, commit=False)
    assert preview.value["errors"][0]["row"] == 4
    refused = _import(db, env, bad)
    assert isinstance(refused, Err) and refused.code == "STATEMENT_FORMAT_INVALID"


def test_xlsx_with_real_dates(db, env):
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["DATE", "LIBELLE", "DEBIT", "CREDIT", "SOLDE"])
    sheet.append([datetime.datetime(2026, 3, 5), "VIR", 300, None, 5300])
    buffer = io.BytesIO()
    workbook.save(buffer)
    result = StatementImportService(db).import_statement(
        tenant_id=TENANT, actor_id=env["actor"], account_id=env["bank"], filename="releve.xlsx",
        content_base64=base64.b64encode(buffer.getvalue()).decode(), commit=True)
    assert isinstance(result, Ok)
    assert StatementImportService(db).list_lines(tenant_id=TENANT, account_id=env["bank"])[0]["debit"] == D("300")


def test_only_bank_accounts_and_known_extensions(db, env):
    cash = StatementImportService(db).import_statement(
        tenant_id=TENANT, actor_id=env["actor"], account_id=env["cash"], filename="a.csv", content_base64=b64(CSV), commit=False)
    assert isinstance(cash, Err) and cash.code == "ACCOUNT_NOT_BANK"
    assert _import(db, env, filename="a.pdf").code == "STATEMENT_FORMAT_INVALID"


def test_partner_follows_the_sign_of_the_line(db, env):
    _import(db, env)
    service = StatementImportService(db)
    debit, credit = service.list_lines(tenant_id=TENANT, account_id=env["bank"])
    ok = service.set_partner(tenant_id=TENANT, actor_id=env["actor"], line_id=debit["id"], partner_id=env["customer"])
    assert isinstance(ok, Ok) and ok.value["partner_id"] == env["customer"]
    wrong = service.set_partner(tenant_id=TENANT, actor_id=env["actor"], line_id=debit["id"], partner_id=env["supplier"])
    assert isinstance(wrong, Err) and wrong.code == "PARTNER_KIND_MISMATCH"
    assert isinstance(service.set_partner(tenant_id=TENANT, actor_id=env["actor"], line_id=credit["id"], partner_id=env["supplier"]), Ok)


def _transfer_receipt(db, env, amount=1000):
    doc = DocumentService(db).create_and_post(
        tenant_id=TENANT, actor_id=env["actor"], direction="in", partner_id=env["customer"], doc_date=DAY, currency="XOF",
        payments=[{"method": "transfer", "amount": amount, "account_id": env["bank"]}], with_details=False, correlation_id="c")
    return doc.value["payments"][0]["id"]


def test_suggestion_and_manual_match_and_summary(db, env):
    payment = _transfer_receipt(db, env)
    _import(db, env)
    service = StatementImportService(db)
    debit, credit = service.list_lines(tenant_id=TENANT, account_id=env["bank"])
    assert service.suggestions(tenant_id=TENANT, account_id=env["bank"]) == {debit["id"]: payment}

    wrong = service.match(tenant_id=TENANT, actor_id=env["actor"], line_id=credit["id"], payment_id=payment)
    assert isinstance(wrong, Err) and wrong.code == "MATCH_MISMATCH"
    matched = service.match(tenant_id=TENANT, actor_id=env["actor"], line_id=debit["id"], payment_id=payment)
    assert matched.value["matched_payment_id"] == payment and matched.value["reconciled_at"] is not None
    assert service.candidate_payments(tenant_id=TENANT, account_id=env["bank"]) == []

    summary = service.summary(tenant_id=TENANT, account_id=env["bank"]).value
    assert summary["matched"] == 1 and summary["unmatched"] == 1
    assert summary["statement_balance"] == D("5950") and summary["account_balance"] == D("6000")
    assert summary["difference"] == D("-50")

    refused = service.delete_line(tenant_id=TENANT, actor_id=env["actor"], line_id=debit["id"])
    assert isinstance(refused, Err) and refused.code == "LINE_MATCHED"
    service.match(tenant_id=TENANT, actor_id=env["actor"], line_id=debit["id"], payment_id=None)
    assert isinstance(service.delete_line(tenant_id=TENANT, actor_id=env["actor"], line_id=debit["id"]), Ok)


def test_a_payment_too_far_from_the_line_to_be_suggested_can_still_be_matched_by_hand(db, env):
    doc = DocumentService(db).create_and_post(
        tenant_id=TENANT, actor_id=env["actor"], direction="in", partner_id=env["customer"], doc_date=DAY - datetime.timedelta(days=20),
        currency="XOF", payments=[{"method": "transfer", "amount": 1000, "account_id": env["bank"]}], with_details=False, correlation_id="c")
    payment = doc.value["payments"][0]["id"]
    _import(db, env)
    service = StatementImportService(db)
    debit, _credit = service.list_lines(tenant_id=TENANT, account_id=env["bank"])
    assert service.suggestions(tenant_id=TENANT, account_id=env["bank"]) == {}
    assert [p["id"] for p in service.candidate_payments(tenant_id=TENANT, account_id=env["bank"])] == [payment]
    matched = service.match(tenant_id=TENANT, actor_id=env["actor"], line_id=debit["id"], payment_id=payment)
    assert isinstance(matched, Ok) and matched.value["matched_payment_id"] == payment


def test_a_payment_waiting_on_the_slip_is_matchable_once_and_only_after_collection(db, env):
    # A transfer received while receipts wait on the deposit slip: the payment has an instrument, and it used to be
    # offered twice once collected, and once already while still pending, before the account had received anything.
    db.execute("UPDATE treasury.settings SET value_json = 'true' WHERE tenant_id = %s AND key = 'receipts_collect_on_slip'", (TENANT,))
    payment = _transfer_receipt(db, env)
    _import(db, env)
    service = StatementImportService(db)
    debit, _ = service.list_lines(tenant_id=TENANT, account_id=env["bank"])
    assert service.candidate_payments(tenant_id=TENANT, account_id=env["bank"]) == []
    early = service.match(tenant_id=TENANT, actor_id=env["actor"], line_id=debit["id"], payment_id=payment)
    assert isinstance(early, Err) and early.code == "PAYMENT_NOT_MATCHABLE"

    pending = InstrumentService(db).list_instruments(tenant_id=TENANT, status="pending")
    InstrumentService(db).post_slip(tenant_id=TENANT, actor_id=env["actor"], account_id=None, slip_date=DAY,
                                    items=[{"instrument_id": pending[0]["id"], "outcome": "collected"}], correlation_id="c")
    assert [p["id"] for p in service.candidate_payments(tenant_id=TENANT, account_id=env["bank"])] == [payment]
    assert service.suggestions(tenant_id=TENANT, account_id=env["bank"]) == {debit["id"]: payment}
    assert service.match(tenant_id=TENANT, actor_id=env["actor"], line_id=debit["id"], payment_id=payment).value["matched_payment_id"] == payment


def test_profile_changes_column_names(db, env):
    service = StatementImportService(db)
    service.set_profile(tenant_id=TENANT, actor_id=env["actor"], account_id=env["bank"],
                        profile={"columns": {"date": "Date op", "label": "Details", "debit": "Entrees", "credit": "Sorties", "balance": "Solde"}})
    text = "Date op;Details;Entrees;Sorties;Solde\n05-Mar-26;VIR;10;;100\n"
    assert isinstance(_import(db, env, text), Ok)


def test_reports_group_by_partner_and_bucket(db, env):
    invoice = InvoiceService(db).create_draft_invoice(tenant_id=TENANT, partner_id=env["customer"], amount=1000.0, currency="XOF")
    InvoiceService(db).issue_invoice(tenant_id=TENANT, actor_id=env["actor"], invoice_id=invoice.id, correlation_id="c")
    service = InvoiceStatusReportService(db)
    rows = service.sales(tenant_id=TENANT, today=datetime.date.today() + datetime.timedelta(days=40))
    mine = [r for r in rows if r["partner_id"] == env["customer"]]
    assert len(mine) == 1 and mine[0]["bucket"] == "31-60"
    groups = InvoiceStatusReportService.by_partner(mine)
    assert groups[0]["remaining"] == D("1000") and groups[0]["bucket_31-60"] == D("1000")


def test_bucket_edges_and_export_formats():
    assert [bucket_for(d) for d in (-3, 0, 30, 31, 60, 61, 90, 91)] == ["0-30", "0-30", "0-30", "31-60", "31-60", "61-90", "61-90", "90+"]
    csv_response = tabular_response(["a", "b"], [["x", D("1.5")]], "csv", "t")
    assert csv_response.body.decode("utf-8-sig").splitlines() == ["a,b", "x,1.5"]
    xlsx_response = tabular_response(["a"], [[D("2")]], "xlsx", "t")
    assert xlsx_response.body[:2] == b"PK"
