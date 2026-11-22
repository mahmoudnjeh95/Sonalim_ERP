"""Invoices typed in by hand: lines with discount and VAT, draft editing, issuing, and the lump-sum rows."""
from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from core.tax_codes import TaxCodeService
from modules.finance.api.service import InvoiceService
from modules.finance.api.vat_report_service import VatReportService

D = Decimal
TENANT = "integration-test-manual-invoices"
ACTOR = "actor-manual"
DAY = datetime.date(2026, 6, 15)


@pytest.fixture
def env(db):
    partner, uom, product = (str(ULID()) for _ in range(3))
    db.execute("INSERT INTO core.partners (id, tenant_id, name, kind) VALUES (%s, %s, 'Boulangerie Kati', 'customer')", (partner, TENANT))
    db.execute("INSERT INTO core.uoms (id, tenant_id, code, name, category) VALUES (%s, %s, 'pc', 'Piece', 'count')", (uom, TENANT))
    db.execute("INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, 'MAN-1', 'Pasta', %s)", (product, TENANT, uom))
    return {"db": db, "partner": partner, "product": product, "service": InvoiceService(db)}


def _create(env, lines, **kw):
    return env["service"].create_invoice(tenant_id=TENANT, actor_id=ACTOR, partner_id=env["partner"], lines=lines, invoice_date=DAY, **kw)


def test_multi_line_invoice_with_discount_and_vat(env):
    result = _create(env, [
        {"product_id": env["product"], "quantity": 10, "unit_price": 1000, "discount_rate": 10, "tax_code": "TVA18"},
        {"description": "Transport", "quantity": 1, "unit_price": 5000, "tax_code": "EXO"},
    ])
    assert isinstance(result, Ok)
    invoice = result.value
    assert invoice["status"] == "draft" and invoice["number"].startswith("FV-2026-")
    assert invoice["amount_excl_tax"] == D("14000") and invoice["vat_amount"] == D("1620")
    assert invoice["total"] == D("15620") and invoice["invoice_date"] == DAY
    first, second = invoice["lines"]
    assert first["unit_price"] == D("900") and first["list_price"] == D("1000") and first["vat_rate"] == D("18") and first["discount_rate"] == D("10")
    assert second["description"] == "Transport" and second["product_id"] is None and second["vat_rate"] == D("0")


def test_default_sales_rate_applies_without_a_tax_code(env):
    invoice = _create(env, [{"description": "Service", "quantity": 1, "unit_price": 1000}]).value
    assert invoice["lines"][0]["vat_rate"] == D("18") and invoice["total"] == D("1180")
    TaxCodeService(env["db"]).set_default_rate(tenant_id=TENANT, actor_id=ACTOR, side="sales", rate=D("10"))
    assert _create(env, [{"description": "Service", "quantity": 1, "unit_price": 1000}]).value["total"] == D("1100")


def test_invalid_input_is_refused(env):
    assert _create(env, []).code == "INVOICE_EMPTY"
    assert _create(env, [{"description": "x", "quantity": 1, "unit_price": 1, "tax_code": "NOPE"}]).code == "INVALID_TAX_CODE"
    assert _create(env, [{"quantity": 1, "unit_price": 1}]).code == "INVALID_LINE"
    assert _create(env, [{"product_id": "ghost", "quantity": 1, "unit_price": 1}]).code == "NOT_FOUND"
    assert env["service"].create_invoice(tenant_id=TENANT, actor_id=ACTOR, partner_id="ghost",
                                         lines=[{"description": "x", "unit_price": 1}]).code == "NOT_FOUND"
    assert _create(env, [{"description": "x", "unit_price": 1}], currency="EUR").code == "INVOICE_CURRENCY_NOT_XOF"


def test_draft_lines_can_be_replaced_and_instalments_follow(env):
    invoice = _create(env, [{"description": "A", "quantity": 1, "unit_price": 1000, "tax_code": "EXO"}]).value
    replaced = env["service"].replace_lines(
        tenant_id=TENANT, actor_id=ACTOR, invoice_id=invoice["id"], invoice_date=datetime.date(2026, 7, 1),
        lines=[{"description": "B", "quantity": 3, "unit_price": 2000, "tax_code": "TVA18"}])
    assert isinstance(replaced, Ok)
    detail = replaced.value
    assert [l["description"] for l in detail["lines"]] == ["B"] and detail["total"] == D("7080")
    assert detail["invoice_date"] == datetime.date(2026, 7, 1) and detail["number"] == invoice["number"]
    total = env["db"].execute("SELECT SUM(amount) FROM finance.invoice_installments WHERE invoice_id = %s", (invoice["id"],)).fetchone()[0]
    assert total == D("7080")


def test_issued_invoice_cannot_be_re_edited_and_empty_cannot_be_issued(env):
    invoice = _create(env, [{"description": "A", "quantity": 1, "unit_price": 1000}]).value
    assert isinstance(env["service"].issue_invoice(tenant_id=TENANT, actor_id=ACTOR, invoice_id=invoice["id"], correlation_id="c"), Ok)
    refused = env["service"].replace_lines(tenant_id=TENANT, actor_id=ACTOR, invoice_id=invoice["id"],
                                           lines=[{"description": "B", "unit_price": 1}])
    assert refused.code == "INVOICE_NOT_DRAFT"
    env["db"].execute("DELETE FROM finance.invoice_lines WHERE invoice_id = %s", (invoice["id"],))
    bare = env["service"].create_draft_invoice(tenant_id=TENANT, partner_id=env["partner"], amount=D("500"))
    env["db"].execute("DELETE FROM finance.invoice_lines WHERE invoice_id = %s", (bare.id,))
    assert env["service"].issue_invoice(tenant_id=TENANT, actor_id=ACTOR, invoice_id=bare.id, correlation_id="c").code == "INVOICE_EMPTY"


def test_single_amount_invoice_has_one_lump_sum_line_and_keeps_admin_edit(env):
    draft = env["service"].create_draft_invoice(tenant_id=TENANT, partner_id=env["partner"], amount=D("2500"))
    detail = env["service"].get_invoice_detail(tenant_id=TENANT, invoice_id=draft.id).value
    assert len(detail["lines"]) == 1 and detail["lines"][0]["product_id"] is None and detail["amount_excl_tax"] == D("2500")
    assert isinstance(env["service"].admin_update_invoice(tenant_id=TENANT, actor_id=ACTOR, invoice_id=draft.id, amount=D("3000")), Ok)
    detail = env["service"].get_invoice_detail(tenant_id=TENANT, invoice_id=draft.id).value
    assert detail["lines"][0]["amount"] == D("3000") and detail["amount_excl_tax"] == D("3000") and detail["total"] == D("3000")


def test_admin_cannot_overwrite_a_total_that_comes_from_lines(env):
    invoice = _create(env, [{"description": "A", "quantity": 1, "unit_price": 1000},
                            {"description": "B", "quantity": 1, "unit_price": 1000}]).value
    refused = env["service"].admin_update_invoice(tenant_id=TENANT, actor_id=ACTOR, invoice_id=invoice["id"], amount=D("1"))
    assert isinstance(refused, Err) and refused.code == "AMOUNT_FROM_LINES"


def test_vat_report_counts_manual_invoices(env):
    invoice = _create(env, [{"description": "A", "quantity": 1, "unit_price": 10000, "tax_code": "TVA18"},
                            {"description": "B", "quantity": 1, "unit_price": 4000, "tax_code": "EXO"}]).value
    env["service"].issue_invoice(tenant_id=TENANT, actor_id=ACTOR, invoice_id=invoice["id"], correlation_id="c")
    rows = VatReportService(env["db"]).sales_by_rate(tenant_id=TENANT, date_from=DAY, date_to=DAY)
    assert [(r["vat_rate"], r["base"], r["vat"]) for r in rows] == [(D("18.00"), D("10000.00"), D("1800.00")), (D("0.00"), D("4000.00"), D("0.00"))]


def test_backfill_gives_every_old_invoice_a_line(env):
    db = env["db"]
    old = str(ULID())
    db.execute("INSERT INTO finance.invoices (id, tenant_id, partner_id, amount, amount_excl_tax, status) VALUES (%s, %s, %s, 1234, 1234, 'issued')",
               (old, TENANT, env["partner"]))
    from pathlib import Path
    sql = (Path(__file__).parents[1] / "migrations" / "0014_finance_invoice_free_lines.sql").read_text(encoding="utf-8")
    db.execute(sql)
    db.execute(sql)  # idempotent
    lines = db.execute("SELECT quantity, unit_price, amount, vat_rate, product_id FROM finance.invoice_lines WHERE invoice_id = %s", (old,)).fetchall()
    assert lines == [(D("1"), D("1234.0000"), D("1234.00"), D("0.00"), None)]
