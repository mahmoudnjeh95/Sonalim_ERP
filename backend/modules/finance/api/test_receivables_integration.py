"""Receivables end to end: payment terms dating invoices, credit control at order confirmation, dunning,
statements, and the routes behind the screens."""
from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from fastapi import FastAPI
from ulid import ULID

pytest.importorskip("httpx", reason="the FastAPI test client needs httpx (requirements-dev.txt)")
from fastapi.testclient import TestClient  # noqa: E402

from core.domain.result import Err, Ok  # noqa: E402
from core.payment_terms import PaymentTermService  # noqa: E402
from core.tenancy import TenantContext, require_session  # noqa: E402
from modules.finance.api import receivables_router as router_module  # noqa: E402
from modules.finance.api.dunning_service import DunningService  # noqa: E402
from modules.finance.api.receivables_service import ReceivablesService  # noqa: E402
from modules.finance.api.service import InvoiceService  # noqa: E402
from modules.finance.testing_support import NoCommitConnection  # noqa: E402
from modules.sales.api.service import SalesOrderService  # noqa: E402
from modules.sales.domain.entities import OrderLine  # noqa: E402
from modules.warehouse.api.service import StockService  # noqa: E402

D = Decimal
TENANT = "integration-test-receivables"
TODAY = datetime.date.today()


@pytest.fixture
def env(db):
    actor, chaser, uom, product, customer, supplier, location = (str(ULID()) for _ in range(7))
    for user in (actor, chaser):
        db.execute("INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')", (user, TENANT, f"{user}@t.local"))
    db.execute("INSERT INTO core.user_permissions (user_id, permission) VALUES (%s, 'finance.manage_dunning')", (chaser,))
    db.execute("INSERT INTO core.uoms (id, tenant_id, code, name, category) VALUES (%s, %s, 'pc', 'Piece', 'count')", (uom, TENANT))
    db.execute("INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, 'RCV-PASTA', 'Pasta', %s)", (product, TENANT, uom))
    db.execute("INSERT INTO core.partners (id, tenant_id, name, kind) VALUES (%s, %s, 'Boulangerie Kati', 'customer')", (customer, TENANT))
    db.execute("INSERT INTO core.partners (id, tenant_id, name, kind) VALUES (%s, %s, 'Moulins du Sahel', 'supplier')", (supplier, TENANT))
    db.execute("INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, 'MAIN', 'Main')", (location, TENANT))
    StockService(db).receive_stock(tenant_id=TENANT, product_id=product, location_id=location, quantity=1000, correlation_id="c",
                                   reference="initial")
    return {"db": db, "actor": actor, "chaser": chaser, "product": product, "customer": customer, "supplier": supplier,
            "location": location}


def _term(db, code):
    return next(t for t in PaymentTermService(db).list_terms(tenant_id=TENANT) if t["code"] == code)


def _set_term(env, code, side="customer", partner=None):
    result = PaymentTermService(env["db"]).set_partner_term(
        tenant_id=TENANT, actor_id=env["actor"], partner_id=partner or env["customer"], side=side, term_id=_term(env["db"], code)["id"])
    assert isinstance(result, Ok), result


def _invoice(env, amount, *, due=None, issue=True):
    """An issued invoice; `due` (days from today, negative = late) replaces its schedule with one due date."""
    service = InvoiceService(env["db"])
    invoice = service.create_draft_invoice(tenant_id=TENANT, partner_id=env["customer"], amount=amount, actor_id=env["actor"])
    if due is not None:
        updated = service.admin_update_invoice(tenant_id=TENANT, actor_id=env["actor"], invoice_id=invoice.id,
                                               due_date=TODAY + datetime.timedelta(days=due))
        assert isinstance(updated, Ok), updated
    if issue:
        assert isinstance(service.issue_invoice(tenant_id=TENANT, actor_id=env["actor"], invoice_id=invoice.id, correlation_id="c"), Ok)
    return invoice.id


def _order(env, amount):
    return SalesOrderService(env["db"]).create_order(
        tenant_id=TENANT, actor_id=env["actor"], partner_id=env["customer"], location_id=env["location"],
        lines=[OrderLine(product_id=env["product"], quantity=1, unit_price=amount)])


def _confirm(env, order, override=False):
    return SalesOrderService(env["db"]).confirm_order(tenant_id=TENANT, actor_id=env["actor"], order_id=order.id, correlation_id="c",
                                                      override_credit=override)


def _invoice_row(db, invoice_id):
    return db.execute("SELECT due_date, payment_term_code FROM finance.invoices WHERE id = %s", (invoice_id,)).fetchone()


# ---- payment terms ---------------------------------------------------------------------------------------

def test_an_invoice_takes_its_customers_terms_and_keeps_them(env):
    db = env["db"]
    assert _invoice_row(db, _invoice(env, 1000, issue=False)) == (TODAY, None)  # no term: due on the invoice date
    _set_term(env, "30N")
    dated = _invoice(env, 1000, issue=False)
    assert _invoice_row(db, dated) == (TODAY + datetime.timedelta(days=30), "30N")
    _set_term(env, "COMPTANT")
    assert _invoice_row(db, dated) == (TODAY + datetime.timedelta(days=30), "30N")  # changing terms never redates
    assert _invoice_row(db, _invoice(env, 1000, issue=False))[1] == "COMPTANT"


def test_a_split_term_gives_two_installments_and_a_new_amount_is_spread_the_same_way(env):
    db = env["db"]
    _set_term(env, "50C-50/30")
    invoice_id = _invoice(env, 1001, issue=False)
    rows = db.execute("SELECT due_date, amount FROM finance.invoice_installments WHERE invoice_id = %s ORDER BY seq", (invoice_id,)).fetchall()
    assert rows == [(TODAY, D("501")), (TODAY + datetime.timedelta(days=30), D("500"))]
    _set_term(env, "COMPTANT")
    InvoiceService(db).admin_update_invoice(tenant_id=TENANT, actor_id=env["actor"], invoice_id=invoice_id, amount=2000)
    rows = db.execute("SELECT amount FROM finance.invoice_installments WHERE invoice_id = %s ORDER BY seq", (invoice_id,)).fetchall()
    assert rows == [(D("1000"),), (D("1000"),)]  # the rule it was given, not today's COMPTANT


def test_a_term_must_add_up_and_its_code_is_unique(env):
    service = PaymentTermService(env["db"])
    bad = service.create_term(tenant_id=TENANT, actor_id=env["actor"], code="X", name_fr="X", name_en="X",
                              installments=[{"percent": 40, "days": 0}])
    assert isinstance(bad, Err) and bad.code == "INVALID_PAYMENT_TERM"
    dup = service.create_term(tenant_id=TENANT, actor_id=env["actor"], code="30n", name_fr="X", name_en="X",
                              installments=[{"percent": 100, "days": 30}])
    assert isinstance(dup, Err) and dup.code == "PAYMENT_TERM_EXISTS"


def test_a_purchase_invoice_left_without_due_date_follows_the_suppliers_terms(env):
    from modules.procurement.api.invoice_service import PurchaseInvoiceService

    _set_term(env, "60N", side="supplier", partner=env["supplier"])
    created = PurchaseInvoiceService(env["db"]).create_draft(
        tenant_id=TENANT, actor_id=env["actor"], partner_id=env["supplier"], supplier_invoice_number="F-77",
        invoice_date=datetime.date(2026, 3, 1), amount=D("5000"))
    assert isinstance(created, Ok), created
    assert created.value["due_date"] == datetime.date(2026, 4, 30)


# ---- position and credit control --------------------------------------------------------------------------

def test_exposure_is_open_invoices_plus_deliveries_not_issued_plus_orders_not_delivered(env):
    _invoice(env, 3000, due=10)
    _invoice(env, 700, issue=False)
    order = _order(env, 1200)
    assert isinstance(_confirm(env, order), Ok)
    position = ReceivablesService(env["db"]).position(tenant_id=TENANT, partner_id=env["customer"])
    assert (position["open_invoices"], position["uninvoiced_deliveries"], position["undelivered_orders"]) == (D("3000"), D("700"), D("1200"))
    assert position["exposure"] == D("4900") and position["overdue"] == 0 and position["buckets"]["not_due"] == D("3000")


def test_an_order_over_the_credit_limit_is_refused_unless_overridden_and_the_override_is_audited(env):
    db = env["db"]
    ReceivablesService(db).set_credit_limit(tenant_id=TENANT, actor_id=env["actor"], partner_id=env["customer"], credit_limit=D("5000"))
    _invoice(env, 4000, due=10)
    order = _order(env, 1500)
    refused = _confirm(env, order)
    assert isinstance(refused, Err) and refused.code == "CREDIT_BLOCKED" and "limite de crédit" in refused.message_fr
    assert db.execute("SELECT status FROM sales.orders WHERE id = %s", (order.id,)).fetchone()[0] == "draft"
    assert isinstance(_confirm(env, order, override=True), Ok)
    audit = db.execute("SELECT payload FROM core.audit_log WHERE tenant_id = %s AND action = 'customer.credit_override_used'", (TENANT,)).fetchone()
    assert audit and audit[0]["order_id"] == order.id and audit[0]["reasons"] == ["OVER_CREDIT_LIMIT"]


def test_near_the_limit_the_preview_warns_without_blocking(env):
    service = ReceivablesService(env["db"])
    service.set_credit_limit(tenant_id=TENANT, actor_id=env["actor"], partner_id=env["customer"], credit_limit=D("1000"))
    preview = service.credit_preview(tenant_id=TENANT, partner_id=env["customer"], order_amount=D("950"))
    assert preview["blocking"] == [] and [w["code"] for w in preview["warnings"]] == ["NEAR_CREDIT_LIMIT"]


def test_an_invoice_later_than_the_tenant_allows_blocks_new_orders(env):
    service = ReceivablesService(env["db"])
    assert isinstance(service.update_settings(tenant_id=TENANT, actor_id=env["actor"], changes={"block_overdue_days": 3}), Ok)
    _invoice(env, 1000, due=-5)
    refused = _confirm(env, _order(env, 10))
    assert isinstance(refused, Err) and refused.code == "CREDIT_BLOCKED" and "en retard de 5 jours" in refused.message_fr


def test_the_dunning_hold_blocks_new_orders(env):
    _invoice(env, 1000, due=-50)
    refused = _confirm(env, _order(env, 10))
    assert isinstance(refused, Err) and refused.code == "CREDIT_BLOCKED" and "niveau de relance 4" in refused.message_fr


def test_installments_due_before_the_chasing_start_date_neither_dun_nor_hold(env):
    """At go-live, old invoices may look unpaid only because their payments predate treasury."""
    service = ReceivablesService(env["db"])
    _invoice(env, 1000, due=-60)
    assert isinstance(service.update_settings(tenant_id=TENANT, actor_id=env["actor"],
                                              changes={"chase_from": TODAY - datetime.timedelta(days=10)}), Ok)
    assert DunningService(env["db"]).worklist(tenant_id=TENANT) == []
    assert isinstance(_confirm(env, _order(env, 10)), Ok)
    position = service.position(tenant_id=TENANT, partner_id=env["customer"])
    assert position["overdue"] == D("1000") and position["dunning_level"] is None and position["buckets"]["31_60"] == D("1000")
    _invoice(env, 500, due=-8)  # late after the start date: chased as usual
    [row] = DunningService(env["db"]).worklist(tenant_id=TENANT)
    assert row["overdue"] == D("500") and row["level_reached"]["level"] == 1


def test_the_company_details_are_trimmed_kept_and_printed_on_the_letter(env):
    service = ReceivablesService(env["db"])
    saved = service.update_settings(tenant_id=TENANT, actor_id=env["actor"], changes={
        "company_name": " SONALIM SA ", "company_address": "Zone industrielle, Bamako", "company_email": "",
        "company_tax_id": "NIF 0812345", "company_rccm": "MA.BKO.2010.B.1234", "signatory": "A. Traoré", "signatory_title": "Directeur financier"})
    assert isinstance(saved, Ok)
    assert saved.value["company_name"] == "SONALIM SA" and saved.value["company_email"] is None
    _invoice(env, 1000, due=-10)
    letter = DunningService(env["db"]).letter(tenant_id=TENANT, partner_id=env["customer"]).value
    assert letter["company"]["company_rccm"] == "MA.BKO.2010.B.1234" and letter["company"]["signatory_title"] == "Directeur financier"


# ---- dunning ---------------------------------------------------------------------------------------------

def test_the_worklist_follows_letters_promises_and_their_dates(env):
    db = env["db"]
    dunning = DunningService(db)
    _invoice(env, 1000, due=-20)
    [row] = dunning.worklist(tenant_id=TENANT)
    assert row["days_overdue"] == 20 and row["overdue"] == D("1000") and row["level_reached"]["level"] == 2 and row["to_chase"]

    letter = dunning.record_action(tenant_id=TENANT, actor_id=env["actor"], partner_id=env["customer"], kind="letter", level=2)
    assert isinstance(letter, Ok) and letter.value["amount_due"] == D("1000")
    [row] = dunning.worklist(tenant_id=TENANT)
    assert not row["to_chase"] and row["level_sent"] == 2

    call = dunning.record_action(tenant_id=TENANT, actor_id=env["actor"], partner_id=env["customer"], kind="call")
    assert isinstance(call, Err) and call.code == "NOTE_REQUIRED"
    promise = dunning.record_action(tenant_id=TENANT, actor_id=env["actor"], partner_id=env["customer"], kind="promise",
                                    promise_date=TODAY + datetime.timedelta(days=3), promise_amount=D("1000"), note="paiera vendredi")
    assert isinstance(promise, Ok) and promise.value["promise_status"] == "open"

    # Three days on, nothing paid: the run breaks the promise and tells whoever chases.
    later = TODAY + datetime.timedelta(days=4)
    result = dunning.run(tenant_id=TENANT, today=later)
    assert result["promises_broken"] == 1
    assert db.execute("SELECT promise_status FROM finance.dunning_actions WHERE id = %s", (promise.value["id"],)).fetchone()[0] == "broken"
    notes = db.execute("SELECT kind, title_fr FROM core.notifications WHERE tenant_id = %s AND user_id = %s ORDER BY created_at",
                       (TENANT, env["chaser"])).fetchall()
    assert ("finance.dunning.promise_broken" in [k for k, _ in notes]) and any("comme promis" in t for _, t in notes)
    [row] = dunning.worklist(tenant_id=TENANT, today=later)
    assert row["to_chase"] and row["broken_promise"]["id"] == promise.value["id"]


def test_each_level_is_announced_once_and_a_paid_promise_is_kept(env):
    db = env["db"]
    dunning = DunningService(db)
    invoice_id = _invoice(env, 1000, due=-8)
    assert dunning.run(tenant_id=TENANT)["levels_announced"] == 1
    assert dunning.run(tenant_id=TENANT)["levels_announced"] == 0
    dunning.record_action(tenant_id=TENANT, actor_id=env["actor"], partner_id=env["customer"], kind="promise",
                          promise_date=TODAY, note="virement demain")
    InvoiceService(db).apply_payment_delta(tenant_id=TENANT, actor_id=env["actor"], invoice_id=invoice_id, delta=D("1000"),
                                           event_type="treasury.receipt.posted", document_id="DOC-1")
    assert dunning.worklist(tenant_id=TENANT) == []
    assert dunning.run(tenant_id=TENANT, today=TODAY + datetime.timedelta(days=1))["promises_kept"] == 1


def test_the_letter_lists_the_late_invoices_with_the_reached_level(env):
    _invoice(env, 1000, due=-35)
    _invoice(env, 500, due=5)
    letter = DunningService(env["db"]).letter(tenant_id=TENANT, partner_id=env["customer"])
    assert isinstance(letter, Ok)
    assert letter.value["level"]["level"] == 3 and letter.value["overdue"] == D("1000") and len(letter.value["invoices"]) == 1
    assert letter.value["level"]["name_fr"] == "Mise en demeure" and "en demeure" in letter.value["level"]["letter_fr"]


def test_levels_must_have_increasing_delays(env):
    dunning = DunningService(env["db"])
    bad = dunning.save_levels(tenant_id=TENANT, actor_id=env["actor"], levels=[
        {"days_after_due": 10, "name_fr": "A"}, {"days_after_due": 10, "name_fr": "B"}])
    assert isinstance(bad, Err) and bad.code == "INVALID_DUNNING_LEVELS"
    good = dunning.save_levels(tenant_id=TENANT, actor_id=env["actor"], levels=[
        {"days_after_due": 20, "name_fr": "Deuxième", "blocks_orders": True}, {"days_after_due": 5, "name_fr": "Premier"}])
    assert isinstance(good, Ok) and [(l["level"], l["days_after_due"], l["blocks_orders"]) for l in good.value] == [(1, 5, False), (2, 20, True)]


# ---- statement -------------------------------------------------------------------------------------------

def test_the_statement_runs_a_balance_over_invoices_and_payments(env):
    db = env["db"]
    first = _invoice(env, 1000, due=-40)
    _invoice(env, 600, due=10)
    InvoiceService(db).apply_payment_delta(tenant_id=TENANT, actor_id=env["actor"], invoice_id=first, delta=D("400"),
                                           event_type="treasury.receipt.posted", document_id="DOC-9")
    statement = ReceivablesService(db).statement(tenant_id=TENANT, partner_id=env["customer"])
    assert [(l["kind"], l["debit"], l["credit"], l["balance"]) for l in statement["lines"]] == [
        ("invoice", D("1000"), 0, D("1000")), ("invoice", D("600"), 0, D("1600")), ("payment", 0, D("400"), D("1200"))]
    assert statement["closing_balance"] == D("1200")
    assert statement["position"]["overdue"] == D("600") and statement["position"]["buckets"]["31_60"] == D("600")


# ---- routes ----------------------------------------------------------------------------------------------

@pytest.fixture
def api(env, monkeypatch):
    wrapped = NoCommitConnection(env["db"])
    monkeypatch.setattr(router_module, "get_connection", lambda: wrapped)
    monkeypatch.setattr("core.tenancy.get_connection", lambda: wrapped)
    app = FastAPI()
    app.include_router(router_module.router)
    app.dependency_overrides[require_session] = lambda: TenantContext(tenant_id=TENANT, user_id=env["actor"], session_token="t")

    def grant(*permissions):
        for permission in permissions:
            env["db"].execute("INSERT INTO core.user_permissions (user_id, permission) VALUES (%s, %s)", (env["actor"], permission))

    return {"client": TestClient(app), "grant": grant}


def test_the_routes_need_their_permissions(api, env):
    client = api["client"]
    assert client.get("/finance/dunning").status_code == 403
    assert client.get(f"/finance/customers/{env['customer']}/credit-check?order_amount=10").status_code == 403
    api["grant"]("finance.view_receivables")
    assert client.get("/finance/dunning").status_code == 200
    refused = client.put(f"/finance/customers/{env['customer']}/credit-limit", json={"credit_limit": 100})
    assert refused.status_code == 403
    api["grant"]("finance.manage_receivables")
    assert client.put(f"/finance/customers/{env['customer']}/credit-limit", json={"credit_limit": 100}).status_code == 200
    assert client.put("/finance/receivables/settings", json={"block_overdue_days": 5}).status_code == 403


def test_terms_aging_statement_export_and_actions_over_http(api, env):
    client = api["client"]
    api["grant"]("finance.view_receivables", "finance.manage_receivables", "finance.manage_dunning", "finance.admin_receivables")
    terms = client.get("/finance/payment-terms").json()
    assert {t["code"] for t in terms} >= {"COMPTANT", "30N", "30FDM", "60N", "45FDM10"}
    term = next(t for t in terms if t["code"] == "30FDM")
    assert client.put(f"/finance/partners/{env['customer']}/payment-terms", json={"side": "customer", "term_id": term["id"]}).status_code == 200
    created = client.post("/finance/payment-terms", json={"code": "90N", "name_fr": "90 jours", "installments": [{"percent": 100, "days": 90}]})
    assert created.status_code == 201, created.text
    bad = client.post("/finance/payment-terms", json={"code": "BAD", "name_fr": "x", "installments": [{"percent": 30, "days": 0}]})
    assert bad.status_code == 400 and bad.json()["detail"]["message_fr"]

    _invoice(env, 2500, due=-12)
    aging = client.get("/finance/receivables/aging").json()
    assert aging[0]["partner_name"] == "Boulangerie Kati" and D(str(aging[0]["bucket_1_30"])) == D("2500")
    csv = client.get(f"/finance/customers/{env['customer']}/statement?format=csv")
    assert csv.status_code == 200 and "Solde d'ouverture" in csv.content.decode("utf-8-sig")
    assert client.get("/finance/receivables/aging?format=xlsx").status_code == 200

    action = client.post("/finance/dunning/actions", json={"partner_id": env["customer"], "kind": "letter", "level": 1})
    assert action.status_code == 201, action.text
    assert client.get(f"/finance/dunning/actions?partner_id={env['customer']}").json()[0]["kind"] == "letter"
    assert client.get(f"/finance/dunning/letter/{env['customer']}").json()["level"]["level"] == 1  # 12 days late
    preview = client.get(f"/finance/customers/{env['customer']}/credit-check?order_amount=100").json()
    assert preview["can_override"] is False and D(str(preview["exposure"])) == D("2500")
    assert client.post("/finance/dunning/run").json()["levels_announced"] == 0  # level 1 was already written
