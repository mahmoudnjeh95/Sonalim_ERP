"""Payables: the aged balance by supplier and a supplier's account statement."""
from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from ulid import ULID

from core.domain.result import Ok
from modules.procurement.api.credit_note_service import PurchaseCreditNoteService
from modules.procurement.api.invoice_service import PurchaseInvoiceService, apply_document_delta
from modules.procurement.api.payables_service import PayablesService

TENANT = "integration-test-payables"
D = Decimal
TODAY = datetime.date(2026, 11, 22)


def _days(n: int) -> datetime.date:
    return TODAY - datetime.timedelta(days=n)


@pytest.fixture
def env(db):
    actor, supplier, other = (str(ULID()) for _ in range(3))
    db.execute("INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')", (actor, TENANT, f"{actor}@test.local"))
    for pid, name in ((supplier, "Moulins du Sahel"), (other, "Emballages SA")):
        db.execute("INSERT INTO core.partners (id, tenant_id, name, kind, status) VALUES (%s, %s, %s, 'supplier', 'active')", (pid, TENANT, name))
    return {"actor": actor, "supplier": supplier, "other": other}


def _invoice(db, env, number, amount, invoice_day, due_day, partner=None, validate=True):
    service = PurchaseInvoiceService(db)
    created = service.create_draft(
        tenant_id=TENANT, actor_id=env["actor"], partner_id=partner or env["supplier"], supplier_invoice_number=number,
        invoice_date=invoice_day, due_date=due_day, lines=[{"description": number, "quantity": 1, "unit_price": amount, "vat_rate": 0}])
    assert isinstance(created, Ok), created
    if validate:
        assert isinstance(service.validate(tenant_id=TENANT, actor_id=env["actor"], invoice_id=created.value["id"], correlation_id="c"), Ok)
    return created.value["id"]


def test_the_aged_balance_buckets_each_open_invoice_by_days_past_due(db, env):
    _invoice(db, env, "NOT-DUE", 1000, _days(5), TODAY + datetime.timedelta(days=10))
    _invoice(db, env, "LATE-10", 2000, _days(40), _days(10))
    _invoice(db, env, "LATE-45", 4000, _days(80), _days(45))
    _invoice(db, env, "LATE-120", 8000, _days(200), _days(120))
    _invoice(db, env, "OTHER", 500, _days(30), _days(1), partner=env["other"])
    _invoice(db, env, "DRAFT", 99999, _days(30), _days(20), validate=False)
    rows = PayablesService(db).aging(tenant_id=TENANT, today=TODAY)
    assert [r["partner_name"] for r in rows] == ["Moulins du Sahel", "Emballages SA"]  # most overdue first
    sahel = rows[0]
    assert (sahel["remaining"], sahel["overdue"], sahel["invoices"], sahel["max_days_overdue"]) == (D("15000"), D("14000"), 4, 120)
    assert (sahel["bucket_not_due"], sahel["bucket_1_30"], sahel["bucket_31_60"], sahel["bucket_61_90"], sahel["bucket_over_90"]) == \
        (D("1000"), D("2000"), D("4000"), D("0"), D("8000"))
    assert rows[1]["bucket_1_30"] == D("500")


def test_a_payment_and_a_credit_note_shrink_the_balance_and_a_settled_invoice_leaves_it(db, env):
    late = _invoice(db, env, "LATE", 10000, _days(40), _days(10))
    settled = _invoice(db, env, "SETTLED", 3000, _days(40), _days(10))
    for invoice_id, delta in ((late, D("4000")), (settled, D("3000"))):
        assert isinstance(apply_document_delta(db, tenant_id=TENANT, actor_id=env["actor"], invoice_id=invoice_id, delta=delta,
                                               event_type="treasury.disbursement.posted", document_id=f"doc-{invoice_id}"), Ok)
    rows = PayablesService(db).aging(tenant_id=TENANT, today=TODAY)
    assert (rows[0]["remaining"], rows[0]["invoices"]) == (D("6000"), 1)
    lines = PurchaseInvoiceService(db).list_lines(tenant_id=TENANT, invoice_id=late)
    note = PurchaseCreditNoteService(db).create_draft(
        tenant_id=TENANT, actor_id=env["actor"], invoice_id=late, note_date=_days(2), reason="Retour",
        lines=[{"invoice_line_id": lines[0]["id"], "quantity": 0.2}]).value  # 2000 off 10000
    assert isinstance(PurchaseCreditNoteService(db).validate(tenant_id=TENANT, actor_id=env["actor"], note_id=note["id"], correlation_id="c"), Ok)
    assert PayablesService(db).aging(tenant_id=TENANT, today=TODAY)[0]["remaining"] == D("4000")


def test_the_statement_runs_a_balance_over_invoices_credit_notes_and_payments(db, env):
    first = _invoice(db, env, "S-1", 10000, _days(60), _days(30))
    _invoice(db, env, "S-2", 5000, _days(20), _days(-10))
    _invoice(db, env, "S-CANCELLED", 777, _days(20), _days(-10), validate=False)
    lines = PurchaseInvoiceService(db).list_lines(tenant_id=TENANT, invoice_id=first)
    note = PurchaseCreditNoteService(db).create_draft(
        tenant_id=TENANT, actor_id=env["actor"], invoice_id=first, note_date=_days(50), reason="Retour",
        lines=[{"invoice_line_id": lines[0]["id"], "quantity": 0.1}]).value  # 1000
    PurchaseCreditNoteService(db).validate(tenant_id=TENANT, actor_id=env["actor"], note_id=note["id"], correlation_id="c")
    apply_document_delta(db, tenant_id=TENANT, actor_id=env["actor"], invoice_id=first, delta=D("3000"),
                         event_type="treasury.disbursement.posted", document_id="D-1")
    statement = PayablesService(db).statement(tenant_id=TENANT, partner_id=env["supplier"], today=TODAY)
    assert statement["partner_name"] == "Moulins du Sahel"
    kinds = [(l["kind"], l["debit"], l["credit"]) for l in statement["lines"]]
    assert kinds[0] == ("invoice", D("0"), D("10000")) and ("credit_note", D("1000"), D("0")) in kinds
    assert ("payment", D("3000"), D("0")) in kinds and ("invoice", D("0"), D("5000")) in kinds
    assert len(kinds) == 4  # the draft is not on the statement
    assert statement["closing_balance"] == D("11000") == statement["remaining"]  # 10000 + 5000 - 1000 - 3000
    assert statement["overdue"] == D("6000") and len(statement["open_invoices"]) == 2
    # An opening balance carries what came before the period.
    later = PayablesService(db).statement(tenant_id=TENANT, partner_id=env["supplier"], date_from=_days(25), today=TODAY)
    assert later["opening_balance"] == D("9000")  # S-1 less its credit note, both before the period
    assert [l["kind"] for l in later["lines"]] == ["invoice", "payment"] and later["lines"][0]["balance"] == D("14000")
    assert later["closing_balance"] == D("11000")
