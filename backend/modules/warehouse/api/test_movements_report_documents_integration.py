"""Invoices and credit notes in the stock movements report: the manual lists them among the movement types,
but they move no stock, so they come out as information rows that no stock figure adds up."""
from __future__ import annotations

import csv
import datetime
import io
from contextlib import contextmanager
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from ulid import ULID

from core.domain.result import Ok
from modules.procurement.api.credit_note_service import PurchaseCreditNoteService
from modules.procurement.api.invoice_service import PurchaseInvoiceService
from modules.warehouse.api.movements_report_service import MovementsReportService
from modules.warehouse.api.voucher_service import VoucherService

TENANT = "integration-test-movements-documents"
DAY = datetime.date(2026, 10, 1)
D = Decimal


@pytest.fixture
def env(db):
    actor, supplier, uom, film, pasta, main = (str(ULID()) for _ in range(6))
    db.execute("INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')", (actor, TENANT, f"{actor}@test.local"))
    db.execute("INSERT INTO core.partners (id, tenant_id, name, kind, status) VALUES (%s, %s, 'Moulins du Sahel', 'supplier', 'active')",
               (supplier, TENANT))
    db.execute("INSERT INTO core.uoms (id, tenant_id, code, name, category) VALUES (%s, %s, 'pc', 'Piece', 'count')", (uom, TENANT))
    for pid, sku in ((film, "FILM"), (pasta, "PASTA")):
        db.execute("INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, %s, %s, %s)", (pid, TENANT, sku, sku, uom))
    db.execute("INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, 'MV-MAIN', 'Main')", (main, TENANT))
    return {"actor": actor, "supplier": supplier, "film": film, "pasta": pasta, "main": main}


def _receive(db, env, quantity):
    vouchers = VoucherService(db)
    draft = vouchers.create_draft(tenant_id=TENANT, actor_id=env["actor"], type="receipt", dest_location_id=env["main"],
                                  lines=[{"product_id": env["film"], "quantity": quantity, "unit_cost": 100}])
    assert isinstance(vouchers.post(tenant_id=TENANT, actor_id=env["actor"], voucher_id=draft.value["id"], correlation_id="c"), Ok)


def _invoice(db, env, number, quantity, validate=True):
    invoices = PurchaseInvoiceService(db)
    draft = invoices.create_draft(tenant_id=TENANT, actor_id=env["actor"], partner_id=env["supplier"], supplier_invoice_number=number,
                                  invoice_date=DAY, lines=[{"product_id": env["film"], "description": "Film", "quantity": quantity,
                                                            "unit_price": 100, "vat_rate": 0},
                                                           {"description": "Transport", "quantity": 1, "unit_price": 500, "vat_rate": 0}])
    assert isinstance(draft, Ok), draft
    if validate:
        assert isinstance(invoices.validate(tenant_id=TENANT, actor_id=env["actor"], invoice_id=draft.value["id"], correlation_id="c"), Ok)
    return draft.value["id"], invoices.list_lines(tenant_id=TENANT, invoice_id=draft.value["id"])


def _credit(db, env, invoice_id, line_id, quantity):
    notes = PurchaseCreditNoteService(db)
    note = notes.create_draft(tenant_id=TENANT, actor_id=env["actor"], invoice_id=invoice_id, note_date=DAY + datetime.timedelta(days=2),
                              reason="Retour", lines=[{"invoice_line_id": line_id, "quantity": quantity}])
    assert isinstance(note, Ok), note
    return notes.validate(tenant_id=TENANT, actor_id=env["actor"], note_id=note.value["id"], correlation_id="c").value


def _on_hand(db, env):
    return db.execute("SELECT quantity_on_hand FROM warehouse.stock_items WHERE tenant_id = %s AND product_id = %s",
                      (TENANT, env["film"])).fetchone()[0]


def test_validated_invoices_and_credit_notes_are_listed_as_information(db, env):
    _receive(db, env, 30)
    on_hand = _on_hand(db, env)
    invoice_id, lines = _invoice(db, env, "F-100", 10)
    _invoice(db, env, "F-DRAFT", 7, validate=False)
    note = _credit(db, env, invoice_id, lines[0]["id"], 2)

    rows = MovementsReportService(db).movements_report(tenant_id=TENANT, product_id=env["film"])
    documents = [(r["move_type"], r["quantity"], r["partner"], r["informational"]) for r in rows if r["informational"]]
    invoice_number = PurchaseInvoiceService(db).get_invoice(tenant_id=TENANT, invoice_id=invoice_id).value["number"]
    assert sorted(documents) == [("purchase_credit_note", D(2), "Moulins du Sahel", True),
                                 ("purchase_invoice", D(10), "Moulins du Sahel", True)]
    assert {r["voucher_number"] for r in rows if r["informational"]} == {invoice_number, note["number"]}
    # The draft and the line without a product are not stock documents for this product.
    assert all(r["quantity"] != D(7) for r in rows) and all(r["sku"] == "FILM" for r in rows)
    # A real move is not information, and listing the documents changed no stock.
    assert [r["informational"] for r in rows if r["move_type"] == "receipt"] == [False]
    assert _on_hand(db, env) == on_hand


def test_the_type_location_and_date_filters_apply_to_documents(db, env):
    _receive(db, env, 30)
    invoice_id, lines = _invoice(db, env, "F-200", 5)
    _credit(db, env, invoice_id, lines[0]["id"], 1)
    report = MovementsReportService(db)

    only_invoices = report.movements_report(tenant_id=TENANT, move_type="purchase_invoice")
    assert [r["move_type"] for r in only_invoices] == ["purchase_invoice"]
    assert [r["move_type"] for r in report.movements_report(tenant_id=TENANT, move_type="receipt")] == ["receipt"]
    # Invoices belong to no depot.
    assert not any(r["informational"] for r in report.movements_report(tenant_id=TENANT, location_id=env["main"]))
    # The invoice is dated DAY, the credit note two days later.
    window = report.movements_report(tenant_id=TENANT, date_from=DAY + datetime.timedelta(days=1), date_to=DAY + datetime.timedelta(days=5))
    assert [r["move_type"] for r in window if r["informational"]] == ["purchase_credit_note"]


def test_a_failing_document_read_leaves_the_rest_of_the_report(db, env, monkeypatch):
    _receive(db, env, 30)
    _invoice(db, env, "F-300", 4)

    def broken(connection, **_kwargs):
        connection.execute("SELECT * FROM finance.no_such_table")

    from modules.procurement.api import report_queries

    readers = {"sales_invoice": broken, "purchase_invoice": report_queries.list_invoice_lines_for_report}
    monkeypatch.setattr(MovementsReportService, "_document_readers", staticmethod(lambda: readers))
    rows = MovementsReportService(db).movements_report(tenant_id=TENANT, product_id=env["film"])
    assert sorted(r["move_type"] for r in rows) == ["purchase_invoice", "receipt"]
    assert db.execute("SELECT 1").fetchone() == (1,)  # the savepoint kept the connection usable


# ---- over HTTP -------------------------------------------------------------------------------------------

class _SharedConnection:
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
    @contextmanager
    def shared():
        yield _SharedConnection(db)

    import core.tenancy
    import modules.warehouse.api.stock_documents_router

    for module in (core.tenancy, modules.warehouse.api.stock_documents_router):
        monkeypatch.setattr(module, "get_connection", shared)
    from app.main import app

    user, token = str(ULID()), str(ULID())
    db.execute("INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')", (user, TENANT, f"{user}@test.local"))
    db.execute("INSERT INTO core.sessions (token, user_id, tenant_id, expires_at) VALUES (%s, %s, %s, NOW() + interval '1 hour')",
               (token, user, TENANT))
    db.execute("INSERT INTO core.user_permissions (user_id, permission) VALUES (%s, 'warehouse.view_moves')", (user,))
    client = TestClient(app)
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client


def test_the_report_and_its_export_carry_the_documents_over_http(api, db, env):
    _receive(db, env, 30)
    invoice_id, lines = _invoice(db, env, "F-400", 6)
    _credit(db, env, invoice_id, lines[0]["id"], 1)

    response = api.get("/warehouse/reports/movements", params={"product_id": env["film"]})
    assert response.status_code == 200, response.text
    body = response.json()
    assert sorted((r["move_type"], r["informational"]) for r in body) == [
        ("purchase_credit_note", True), ("purchase_invoice", True), ("receipt", False)]

    exported = api.get("/warehouse/reports/movements", params={"product_id": env["film"], "format": "csv"})
    assert exported.status_code == 200, exported.text
    table = list(csv.DictReader(io.StringIO(exported.content.decode("utf-8-sig"))))
    assert {(r["type"], r["informational"], r["partner"]) for r in table} == {
        ("purchase_invoice", "yes", "Moulins du Sahel"), ("purchase_credit_note", "yes", "Moulins du Sahel"), ("receipt", "no", "")}
