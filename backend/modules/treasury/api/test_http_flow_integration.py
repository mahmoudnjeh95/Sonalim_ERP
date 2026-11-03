"""End-to-end through HTTP: auth, permissions, request models, status codes and file responses of the
treasury, purchase-invoice and stock-document routers. The services have their own tests; this one
catches wiring mistakes (a route that does not import, a body that does not parse, a 204 with a body).

Every router opens its own connection and commits, which would leave rows behind, so the connection
factory is replaced by the test's rolled-back connection with commit and rollback made no-ops."""
from __future__ import annotations

import base64
import datetime

import pytest
from fastapi.testclient import TestClient
from ulid import ULID

TENANT = "integration-test-http-flow"
TODAY = datetime.date.today().isoformat()

PERMISSIONS = [
    "treasury.view", "treasury.manage_accounts", "treasury.manage_receipts", "treasury.manage_disbursements",
    "treasury.collect_instruments", "treasury.import_statements", "treasury.admin_config",
    "procurement.view_purchase_invoices", "procurement.manage_purchase_invoices",
    "warehouse.view_moves", "warehouse.manage_vouchers", "warehouse.post_vouchers", "warehouse.view_valuation",
    "warehouse.view_cycle_counts", "warehouse.manage_cycle_counts",
]


class _SharedConnection:
    """The test's connection, with the transaction boundaries left to the fixture."""

    def __init__(self, connection) -> None:
        self._connection = connection

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass

    def __getattr__(self, name):
        return getattr(self._connection, name)


@pytest.fixture
def api(db, monkeypatch):
    from contextlib import contextmanager

    @contextmanager
    def shared():
        yield _SharedConnection(db)

    import core.tenancy
    import modules.procurement.api.invoice_router
    import modules.treasury.api.router
    import modules.warehouse.api.router
    import modules.warehouse.api.stock_documents_router

    for module in (core.tenancy, modules.procurement.api.invoice_router, modules.treasury.api.router,
                   modules.warehouse.api.router, modules.warehouse.api.stock_documents_router):
        monkeypatch.setattr(module, "get_connection", shared)

    from app.main import app

    user, token = str(ULID()), str(ULID())
    db.execute("INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')", (user, TENANT, f"{user}@test.local"))
    db.execute("INSERT INTO core.sessions (token, user_id, tenant_id, expires_at) VALUES (%s, %s, %s, NOW() + interval '1 hour')", (token, user, TENANT))
    for permission in PERMISSIONS:
        db.execute("INSERT INTO core.user_permissions (user_id, permission) VALUES (%s, %s)", (user, permission))
    client = TestClient(app)
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client


def _user_with(db, *permissions):
    """A second session holding only these permissions, for checks the main fixture's user would pass."""
    user, token = str(ULID()), str(ULID())
    db.execute("INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')", (user, TENANT, f"{user}@test.local"))
    db.execute("INSERT INTO core.sessions (token, user_id, tenant_id, expires_at) VALUES (%s, %s, %s, NOW() + interval '1 hour')", (token, user, TENANT))
    for permission in permissions:
        db.execute("INSERT INTO core.user_permissions (user_id, permission) VALUES (%s, %s)", (user, permission))
    return {"Authorization": f"Bearer {token}"}


def test_the_ledger_posting_switch_needs_its_own_permission(api, db):
    settings_only = _user_with(db, "treasury.admin_config", "treasury.view")
    switch_only = _user_with(db, "treasury.admin_ledger_posting", "treasury.view")

    refused = api.put("/treasury/settings/ledger_posting_enabled", json={"value": True}, headers=settings_only)
    assert refused.status_code == 403
    assert refused.json()["detail"]["code"] == "FORBIDDEN"
    assert "treasury.admin_ledger_posting" in refused.json()["detail"]["message_fr"]
    assert _ok(api.get("/treasury/settings", headers=settings_only))["ledger_posting_enabled"] is False

    assert _ok(api.put("/treasury/settings/cash_payment_limit", json={"value": 500000}, headers=settings_only))["cash_payment_limit"] == 500000
    assert api.put("/treasury/settings/cash_payment_limit", json={"value": 1}, headers=switch_only).status_code == 403

    assert _ok(api.put("/treasury/settings/ledger_posting_enabled", json={"value": True}, headers=switch_only))["ledger_posting_enabled"] is True


def _ok(response, status=200):
    assert response.status_code == status, response.text
    return response.json() if response.content else None


def test_treasury_master_data_over_http(api):
    bank = _ok(api.post("/treasury/banks", json={"name": "BDM"}), 201)
    branch = _ok(api.post(f"/treasury/banks/{bank['id']}/branches", json={"name": "Centre", "city": "Bamako"}), 201)
    account = _ok(api.post("/treasury/accounts", json={
        "kind": "bank", "name": "BDM XOF", "currency": "XOF", "branch_id": branch["id"], "account_number": "H-001", "opening_balance": 1000}), 201)
    assert account["balance"] == "1000.00"
    duplicate = api.post("/treasury/accounts", json={"kind": "bank", "name": "x", "currency": "XOF", "branch_id": branch["id"], "account_number": "H-001"})
    assert duplicate.status_code == 409 and duplicate.json()["detail"]["code"] == "ACCOUNT_NUMBER_DUPLICATE"
    assert duplicate.json()["detail"]["message_fr"]
    assert len(_ok(api.get("/treasury/accounts"))) == 1
    assert _ok(api.get("/treasury/banks"))[0]["branches"][0]["name"] == "Centre"
    assert _ok(api.put("/treasury/settings/cash_payment_limit", json={"value": 500}))["cash_payment_limit"] == 500
    assert len(_ok(api.get("/treasury/alert-rules"))) == 4
    cash = _ok(api.post("/treasury/accounts", json={"kind": "cash", "name": "Caisse", "currency": "XOF"}), 201)
    assert api.delete(f"/treasury/accounts/{cash['id']}").status_code == 204


def test_permissions_are_enforced(api, db):
    other = str(ULID())
    token = str(ULID())
    db.execute("INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')", (other, TENANT, f"{other}@test.local"))
    db.execute("INSERT INTO core.sessions (token, user_id, tenant_id, expires_at) VALUES (%s, %s, %s, NOW() + interval '1 hour')", (token, other, TENANT))
    db.execute("INSERT INTO core.user_permissions (user_id, permission) VALUES (%s, 'treasury.view')", (other,))
    api.headers["Authorization"] = f"Bearer {token}"
    assert api.get("/treasury/accounts").status_code == 200
    assert api.post("/treasury/banks", json={"name": "Nope"}).status_code == 403
    assert api.post("/treasury/receipts", json={"partner_id": "x", "doc_date": TODAY, "payments": []}).status_code == 403
    assert api.get("/warehouse/vouchers").status_code == 403
    api.headers["Authorization"] = "Bearer nonsense"
    assert api.get("/treasury/accounts").status_code == 401


def test_payment_flow_over_http(api, db):
    customer = str(ULID())
    db.execute("INSERT INTO core.partners (id, tenant_id, name, kind, status) VALUES (%s, %s, 'Client', 'customer', 'active')", (customer, TENANT))
    cash = _ok(api.post("/treasury/accounts", json={"kind": "cash", "name": "Caisse", "currency": "XOF"}), 201)

    receipt = _ok(api.post("/treasury/receipts", json={
        "partner_id": customer, "doc_date": TODAY, "currency": "XOF", "with_details": False,
        "payments": [{"method": "cash", "amount": 250, "account_id": cash["id"]},
                     {"method": "cheque", "amount": 100, "number": "H1", "bank_name": "BIM", "due_date": TODAY}]}), 201)
    assert receipt["number"].startswith("ENC-") and receipt["instruments"][0]["status"] == "pending"
    assert _ok(api.get(f"/treasury/receipts/{receipt['id']}"))["total"] == "350.00"
    assert [r["id"] for r in _ok(api.get("/treasury/receipts"))] == [receipt["id"]]
    assert _ok(api.get("/treasury/disbursements")) == []

    refused = api.post("/treasury/receipts", json={"partner_id": customer, "doc_date": TODAY, "currency": "XOF", "payments": []})
    assert refused.status_code == 400 and refused.json()["detail"]["code"] == "NO_PAYMENTS"
    assert api.get("/treasury/receipts/nope").status_code == 404

    # the cheque is due today, so its alert window (due + 1 day) opens tomorrow: nothing yet
    assert _ok(api.get("/treasury/alerts")) == []
    bank = _ok(api.post("/treasury/banks", json={"name": "BDM"}), 201)
    branch = _ok(api.post(f"/treasury/banks/{bank['id']}/branches", json={"name": "Centre"}), 201)
    account = _ok(api.post("/treasury/accounts", json={"kind": "bank", "name": "B", "currency": "XOF", "branch_id": branch["id"], "account_number": "H-9"}), 201)
    slip = _ok(api.post("/treasury/deposit-slips", json={"account_id": account["id"], "slip_date": TODAY,
                                                          "items": [{"instrument_id": receipt["instruments"][0]["id"], "outcome": "collected"}]}), 201)
    assert slip["number"].startswith("BV-")
    assert _ok(api.get("/treasury/instruments?status_filter=collected"))[0]["id"] == receipt["instruments"][0]["id"]
    journal = _ok(api.get(f"/treasury/journals/cash?account_id={cash['id']}"))
    assert journal["closing_balance"] == "250.00" and len(journal["rows"]) == 1

    stuck = api.post(f"/treasury/receipts/{receipt['id']}/cancel")
    assert stuck.status_code == 409 and stuck.json()["detail"]["code"] == "INSTRUMENT_ALREADY_PROCESSED"


def test_cancel_over_http_and_conflict_codes(api, db):
    customer = str(ULID())
    db.execute("INSERT INTO core.partners (id, tenant_id, name, kind, status) VALUES (%s, %s, 'Client', 'customer', 'active')", (customer, TENANT))
    cash = _ok(api.post("/treasury/accounts", json={"kind": "cash", "name": "Caisse", "currency": "XOF"}), 201)
    receipt = _ok(api.post("/treasury/receipts", json={
        "partner_id": customer, "doc_date": TODAY, "currency": "XOF", "with_details": False,
        "payments": [{"method": "cash", "amount": 80, "account_id": cash["id"]}]}), 201)
    assert _ok(api.post(f"/treasury/receipts/{receipt['id']}/cancel"))["status"] == "cancelled"
    again = api.post(f"/treasury/receipts/{receipt['id']}/cancel")
    assert again.status_code == 409 and again.json()["detail"]["code"] == "DOCUMENT_NOT_POSTED"


def test_statement_import_and_reports_over_http(api):
    bank = _ok(api.post("/treasury/banks", json={"name": "BDM"}), 201)
    branch = _ok(api.post(f"/treasury/banks/{bank['id']}/branches", json={"name": "Centre"}), 201)
    account = _ok(api.post("/treasury/accounts", json={"kind": "bank", "name": "B", "currency": "XOF", "branch_id": branch["id"], "account_number": "H-7"}), 201)
    csv_text = "DATE;LIBELLE;DEBIT;CREDIT;SOLDE\n05-Mar-26;VIR;100;;100\n"
    body = {"account_id": account["id"], "filename": "r.csv", "content_base64": base64.b64encode(csv_text.encode()).decode(), "commit": False}
    preview = _ok(api.post("/treasury/statements/import", json=body))
    assert len(preview["new_lines"]) == 1 and not preview["committed"]
    assert _ok(api.post("/treasury/statements/import", json={**body, "commit": True}))["committed"]
    lines = _ok(api.get(f"/treasury/statements/lines?account_id={account['id']}"))
    assert len(lines) == 1
    assert _ok(api.get(f"/treasury/statements/summary?account_id={account['id']}"))["unmatched"] == 1
    assert api.delete(f"/treasury/statements/lines/{lines[0]['id']}").status_code == 204

    report = api.get("/treasury/reports/purchase-invoices?format=csv")
    assert report.status_code == 200 and report.headers["content-type"].startswith("text/csv")
    xlsx = api.get("/treasury/reports/sales-invoices?format=xlsx")
    assert xlsx.status_code == 200 and xlsx.content[:2] == b"PK"
    assert "partners" in _ok(api.get("/treasury/reports/sales-invoices"))


def test_purchase_invoice_over_http(api, db):
    supplier = str(ULID())
    db.execute("INSERT INTO core.partners (id, tenant_id, name, kind, status) VALUES (%s, %s, 'Fournisseur', 'supplier', 'active')", (supplier, TENANT))
    created = _ok(api.post("/procurement/purchase-invoices", json={
        "partner_id": supplier, "supplier_invoice_number": "H-1", "invoice_date": TODAY, "amount": "100",
        "lines": [{"description": "Film", "quantity": "2", "unit_price": "50"}]}), 201)
    assert created["status"] == "draft" and created["lines"][0]["description"] == "Film"
    mismatch = api.post("/procurement/purchase-invoices", json={
        "partner_id": supplier, "supplier_invoice_number": "H-2", "invoice_date": TODAY, "amount": "100",
        "lines": [{"description": "Film", "quantity": "1", "unit_price": "10"}]})
    assert mismatch.status_code == 400 and mismatch.json()["detail"]["code"] == "TOTAL_MISMATCH"
    validated = _ok(api.post(f"/procurement/purchase-invoices/{created['id']}/validate"))
    assert validated["number"].startswith("FA-") and validated["remaining"] == "100.00"
    edit = api.patch(f"/procurement/purchase-invoices/{created['id']}", json={"note": "x"})
    assert edit.status_code == 409 and edit.json()["detail"]["code"] == "INVOICE_NOT_DRAFT"
    assert len(_ok(api.get("/procurement/purchase-invoices?status_filter=validated"))) == 1
    duplicate = api.post("/procurement/purchase-invoices", json={"partner_id": supplier, "supplier_invoice_number": "H-1", "invoice_date": TODAY, "amount": "5"})
    assert duplicate.status_code == 409


def test_stock_documents_over_http(api, db):
    uom, product, main = (str(ULID()) for _ in range(3))
    db.execute("INSERT INTO core.uoms (id, tenant_id, code, name, category) VALUES (%s, %s, 'pc', 'Piece', 'count')", (uom, TENANT))
    db.execute("INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, 'HF', 'HF', %s)", (product, TENANT, uom))
    db.execute("INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, 'HF-L', 'Main')", (main, TENANT))

    draft = _ok(api.post("/warehouse/vouchers", json={"type": "receipt", "dest_location_id": main,
                                                      "lines": [{"product_id": product, "quantity": "10", "unit_cost": "5"}]}), 201)
    assert draft["status"] == "draft"
    posted = _ok(api.post(f"/warehouse/vouchers/{draft['id']}/post"))
    assert posted["status"] == "posted" and posted["number"].startswith("RCP-")
    assert api.post(f"/warehouse/vouchers/{draft['id']}/post").status_code == 409

    issue = _ok(api.post("/warehouse/vouchers", json={"type": "issue", "source_location_id": main, "lines": [{"product_id": product, "quantity": "99"}]}), 201)
    short = api.post(f"/warehouse/vouchers/{issue['id']}/post")
    assert short.status_code == 409 and short.json()["detail"]["code"] == "STOCK_INSUFFICIENT"

    valuation = _ok(api.get("/warehouse/reports/valued-stock"))
    item = next(i for i in valuation["items"] if i["product_id"] == product)
    assert float(item["value"]) == 50 and float(item["avg_cost"]) == 5
    assert api.get("/warehouse/reports/valued-stock?format=csv").headers["content-type"].startswith("text/csv")
    assert api.get("/warehouse/reports/movements?format=xlsx").content[:2] == b"PK"
    assert _ok(api.get("/warehouse/reports/movements"))[0]["voucher_number"] == posted["number"]

    from modules.warehouse.api.site_service import SiteService

    site = SiteService(db).create_site(tenant_id=TENANT, actor_id=str(ULID()), code="hf-site", name="HF").value
    db.execute("UPDATE warehouse.locations SET site_id = %s, location_type = 'bin' WHERE id = %s", (site.id, main))
    count = _ok(api.post("/warehouse/cycle-counts", json={"site_id": site.id, "scope_location_id": main}), 201)
    _ok(api.post(f"/warehouse/cycle-counts/{count['id']}/start"))
    frozen = api.post("/warehouse/vouchers", json={"type": "receipt", "dest_location_id": main, "lines": [{"product_id": product, "quantity": "1", "unit_cost": "5"}]})
    frozen_post = api.post(f"/warehouse/vouchers/{frozen.json()['id']}/post")
    assert frozen_post.status_code == 409 and frozen_post.json()["detail"]["code"] == "LOCATION_FROZEN"
    line = _ok(api.get(f"/warehouse/cycle-counts/{count['id']}"))["lines"][0]
    first = _ok(api.post(f"/warehouse/cycle-counts/{count['id']}/lines/{line['id']}/count", json={"counted_quantity": 10}))
    assert first["status"] == "pending" and first["count_1"] is None and first["counts_recorded"] == 1
    counted = _ok(api.post(f"/warehouse/cycle-counts/{count['id']}/lines/{line['id']}/count", json={"counted_quantity": 10}))
    assert counted["resolution"] == "matched" and counted["count_2"] == 10
    completed = _ok(api.post(f"/warehouse/cycle-counts/{count['id']}/complete", json={"correlation_id": "http-flow"}))
    assert completed["status"] == "completed"
    assert api.post(f"/warehouse/cycle-counts/{count['id']}/complete", json={"correlation_id": "http-flow"}).status_code == 409
    assert api.post(f"/warehouse/vouchers/{frozen.json()['id']}/post").status_code == 200
