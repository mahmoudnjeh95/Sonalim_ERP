"""Price lists, discounts and quotes against the database, and over HTTP."""
from __future__ import annotations

import base64
import datetime
from decimal import Decimal

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from modules.sales.api.pricing_service import PricingService
from modules.sales.api.quote_service import QuoteService
from modules.sales.api.service import SalesOrderService
from modules.sales.domain.entities import OrderLine

TENANT = "integration-test-sales-pricing"
D = Decimal
DAY = datetime.date(2026, 6, 1)
# Quotes are dated today: one dated in the past would already be expired.
TODAY = datetime.date.today()


@pytest.fixture
def env(db):
    actor, uom, pasta, flour, customer, other, location = (str(ULID()) for _ in range(7))
    db.execute("INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')", (actor, TENANT, f"{actor}@test.local"))
    db.execute("INSERT INTO core.uoms (id, tenant_id, code, name, category) VALUES (%s, %s, 'pc', 'Piece', 'count')", (uom, TENANT))
    for pid, sku, price in ((pasta, "SP-PASTA", 1100), (flour, "SP-FLOUR", 500)):
        db.execute("INSERT INTO core.products (id, tenant_id, sku, name, uom_id, selling_price) VALUES (%s, %s, %s, %s, %s, %s)",
                   (pid, TENANT, sku, sku, uom, price))
    for pid, name in ((customer, "Grossiste Bamako"), (other, "Boutique Kati")):
        db.execute("INSERT INTO core.partners (id, tenant_id, name, kind) VALUES (%s, %s, %s, 'customer')", (pid, TENANT, name))
    db.execute("INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, %s, 'FG')", (location, TENANT, str(ULID())))
    return {"actor": actor, "pasta": pasta, "flour": flour, "customer": customer, "other": other, "location": location}


def _list(db, env, name, items, *, default=False, valid_from=None, valid_to=None):
    pricing = PricingService(db)
    created = pricing.save_price_list(tenant_id=TENANT, actor_id=env["actor"], name=name, is_default=default,
                                      valid_from=valid_from, valid_to=valid_to)
    assert isinstance(created, Ok), created
    replaced = pricing.replace_items(tenant_id=TENANT, actor_id=env["actor"], price_list_id=created.value["id"], items=items)
    assert isinstance(replaced, Ok), replaced
    return created.value["id"]


# ---- pricing ----------------------------------------------------------------------------------------

def test_prices_come_from_the_customers_list_with_breaks_else_the_default_else_the_catalog(db, env):
    pricing = PricingService(db)
    public = _list(db, env, "Tarif public 2026", [{"product_id": env["pasta"], "unit_price": 1000}], default=True)
    wholesale = _list(db, env, "Tarif grossistes 2026", [
        {"product_id": env["pasta"], "min_quantity": 1, "unit_price": 950},
        {"product_id": env["pasta"], "min_quantity": 100, "unit_price": 900},
    ], valid_from=datetime.date(2026, 1, 1), valid_to=datetime.date(2026, 12, 31))
    assert isinstance(pricing.set_customer_pricing(tenant_id=TENANT, actor_id=env["actor"], partner_id=env["customer"],
                                                   price_list_id=wholesale, discount_rate=D(2)), Ok)

    def price(partner, product, quantity, on=DAY):
        return pricing.resolve_price(tenant_id=TENANT, partner_id=partner, product_id=product, quantity=D(quantity), on=on).value

    assert (price(env["customer"], env["pasta"], 10)["unit_price"], price(env["customer"], env["pasta"], 10)["discount_rate"]) == (D(950), D(2))
    assert price(env["customer"], env["pasta"], 150)["unit_price"] == D(900)
    assert price(env["customer"], env["pasta"], 10, datetime.date(2027, 1, 2))["price_list_id"] == public  # wholesale list ended
    assert price(env["other"], env["pasta"], 10)["unit_price"] == D(1000)  # no list of its own: the default
    flour = price(env["customer"], env["flour"], 10)
    assert (flour["unit_price"], flour["source"]) == (D(500), "catalog")  # on no list


def test_one_default_list_and_unique_names(db, env):
    pricing = PricingService(db)
    first = _list(db, env, "A", [], default=True)
    second = _list(db, env, "B", [], default=True)
    lists = {l["id"]: l["is_default"] for l in pricing.list_price_lists(tenant_id=TENANT)}
    assert lists == {first: False, second: True}
    clash = pricing.save_price_list(tenant_id=TENANT, actor_id=env["actor"], name="a")
    assert isinstance(clash, Err) and clash.code == "PRICE_LIST_EXISTS"
    dup = pricing.replace_items(tenant_id=TENANT, actor_id=env["actor"], price_list_id=first, items=[
        {"product_id": env["pasta"], "min_quantity": 1, "unit_price": 1}, {"product_id": env["pasta"], "min_quantity": 1, "unit_price": 2}])
    assert isinstance(dup, Err) and dup.code == "DUPLICATE_PRICE"


def test_import_previews_then_replaces_and_export_matches(db, env):
    pricing = PricingService(db)
    list_id = _list(db, env, "Import", [])
    good = "sku;min_quantity;unit_price\nSP-PASTA;1;1 000\nSP-PASTA;50;950,5\nSP-FLOUR;;480\n"
    preview = pricing.import_items(tenant_id=TENANT, actor_id=env["actor"], price_list_id=list_id, filename="tarif.csv",
                                   content_base64=base64.b64encode(good.encode()).decode(), commit=False)
    assert isinstance(preview, Ok) and len(preview.value["items"]) == 3 and preview.value["errors"] == []
    assert pricing.get_price_list(tenant_id=TENANT, price_list_id=list_id).value["item_count"] == 0  # a preview writes nothing
    done = pricing.import_items(tenant_id=TENANT, actor_id=env["actor"], price_list_id=list_id, filename="tarif.csv",
                                content_base64=base64.b64encode(good.encode()).decode(), commit=True)
    assert isinstance(done, Ok)
    assert sorted((r[0], r[2], r[3]) for r in pricing.export_rows(tenant_id=TENANT, price_list_id=list_id)) == [
        ("SP-FLOUR", D(1), D(480)), ("SP-PASTA", D(1), D(1000)), ("SP-PASTA", D(50), D("950.5"))]
    bad = "sku;min_quantity;unit_price\nNOPE;1;10\n"
    refused = pricing.import_items(tenant_id=TENANT, actor_id=env["actor"], price_list_id=list_id, filename="tarif.csv",
                                   content_base64=base64.b64encode(bad.encode()).decode(), commit=True)
    assert isinstance(refused, Err) and refused.code == "IMPORT_HAS_ERRORS"


def test_orders_refuse_a_discount_above_the_limit_unless_allowed(db, env):
    sales = SalesOrderService(db)
    lines = [OrderLine(product_id=env["pasta"], quantity=10, unit_price=1000, discount_rate=8, vat_rate=18)]
    assert isinstance(sales.check_pricing(tenant_id=TENANT, lines=lines, discount_rate=0, may_exceed_discount=False), Ok)
    refused = sales.check_pricing(tenant_id=TENANT, lines=lines, discount_rate=5, may_exceed_discount=False)
    assert isinstance(refused, Err) and refused.code == "DISCOUNT_ABOVE_LIMIT"
    assert isinstance(sales.check_pricing(tenant_id=TENANT, lines=lines, discount_rate=5, may_exceed_discount=True), Ok)
    PricingService(db).update_settings(tenant_id=TENANT, actor_id=env["actor"], max_discount_rate=D(15))
    assert isinstance(sales.check_pricing(tenant_id=TENANT, lines=lines, discount_rate=5, may_exceed_discount=False), Ok)


def test_an_order_keeps_its_discounts_and_vat(db, env):
    sales = SalesOrderService(db)
    order = sales.create_order(tenant_id=TENANT, actor_id=env["actor"], partner_id=env["customer"], location_id=env["location"],
                               discount_rate=5, lines=[OrderLine(product_id=env["pasta"], quantity=10, unit_price=1000,
                                                                 discount_rate=10, vat_rate=18)])
    stored = sales.get_order(tenant_id=TENANT, order_id=order.id).value
    assert (stored.discount_rate, stored.lines[0].discount_rate, stored.lines[0].vat_rate) == (5.0, 10.0, 18.0)
    assert stored.total_amount == 10089.0


# ---- quotes -----------------------------------------------------------------------------------------

def _quote(db, env, **kwargs):
    params = {"tenant_id": TENANT, "actor_id": env["actor"], "partner_id": env["customer"], "quote_date": TODAY,
              "lines": [{"product_id": env["pasta"], "quantity": 120}], "location_id": env["location"]}
    params.update(kwargs)
    created = QuoteService(db).create_quote(**params)
    assert isinstance(created, Ok), created
    return created.value


def test_a_quote_is_priced_numbered_and_totalled(db, env):
    wholesale = _list(db, env, "Grossistes", [{"product_id": env["pasta"], "unit_price": 950},
                                              {"product_id": env["pasta"], "min_quantity": 100, "unit_price": 900}])
    PricingService(db).set_customer_pricing(tenant_id=TENANT, actor_id=env["actor"], partner_id=env["customer"],
                                            price_list_id=wholesale, discount_rate=D(2))
    quote = _quote(db, env)
    assert quote["number"].startswith(f"DV-{TODAY.year}-") and quote["revision"] == 1 and quote["status"] == "draft"
    assert quote["valid_until"] == TODAY + datetime.timedelta(days=30)
    [line] = quote["lines"]
    assert (line["unit_price"], line["vat_rate"], line["price_list_id"]) == (D(900), D(18), wholesale)
    assert quote["discount_rate"] == D(2)  # the customer's standing discount
    # 120 x 900 = 108 000; -2 % = 105 840 excl.; VAT 19 051 (19 051.2); 124 891 incl.
    assert {k: quote["totals"][k] for k in ("gross", "excl_tax", "vat", "incl_tax")} == {
        "gross": D(108000), "excl_tax": D(105840), "vat": D(19051), "incl_tax": D(124891)}
    second = _quote(db, env)
    assert int(second["number"][-6:]) == int(quote["number"][-6:]) + 1


def test_a_quote_moves_through_its_life_and_becomes_an_order_once(db, env):
    quotes = QuoteService(db)
    quote = _quote(db, env, lines=[{"product_id": env["pasta"], "quantity": 10, "unit_price": 1000, "discount_rate": 5}])
    edited = quotes.update_quote(tenant_id=TENANT, actor_id=env["actor"], quote_id=quote["id"], note="Livraison franco Bamako")
    assert isinstance(edited, Ok) and edited.value["note"] == "Livraison franco Bamako"
    early = quotes.convert_to_order(tenant_id=TENANT, actor_id=env["actor"], quote_id=quote["id"])
    assert isinstance(early, Err) and early.code == "QUOTE_NOT_ACCEPTED"
    assert quotes.send(tenant_id=TENANT, actor_id=env["actor"], quote_id=quote["id"]).value["status"] == "sent"
    frozen = quotes.update_quote(tenant_id=TENANT, actor_id=env["actor"], quote_id=quote["id"], note="x")
    assert isinstance(frozen, Err) and frozen.code == "QUOTE_NOT_DRAFT"
    assert quotes.accept(tenant_id=TENANT, actor_id=env["actor"], quote_id=quote["id"]).value["status"] == "accepted"
    converted = quotes.convert_to_order(tenant_id=TENANT, actor_id=env["actor"], quote_id=quote["id"])
    assert isinstance(converted, Ok), converted
    order = SalesOrderService(db).get_order(tenant_id=TENANT, order_id=converted.value["order_id"]).value
    assert (order.quote_id, order.partner_id, order.location_id, order.status) == (quote["id"], env["customer"], env["location"], "draft")
    assert [(l.quantity, l.unit_price, l.discount_rate, l.vat_rate) for l in order.lines] == [(10.0, 1000.0, 5.0, 18.0)]
    assert order.total_amount == float(converted.value["quote"]["totals"]["incl_tax"])  # prices frozen as quoted
    again = quotes.convert_to_order(tenant_id=TENANT, actor_id=env["actor"], quote_id=quote["id"])
    assert isinstance(again, Err) and again.code == "QUOTE_ALREADY_ORDERED"


def test_quotes_expire_by_date_and_revisions_keep_the_number(db, env):
    quotes = QuoteService(db)
    old = _quote(db, env, quote_date=TODAY - datetime.timedelta(days=60), valid_until=TODAY - datetime.timedelta(days=30))
    quotes.send(tenant_id=TENANT, actor_id=env["actor"], quote_id=old["id"])  # may already be expired: either way it ends expired
    assert quotes.get_quote(tenant_id=TENANT, quote_id=old["id"]).value["status"] == "expired"
    late = quotes.accept(tenant_id=TENANT, actor_id=env["actor"], quote_id=old["id"])
    assert isinstance(late, Err) and late.code == "QUOTE_EXPIRED"
    revised = quotes.revise(tenant_id=TENANT, actor_id=env["actor"], quote_id=old["id"])
    assert isinstance(revised, Ok), revised
    assert (revised.value["number"], revised.value["revision"], revised.value["status"]) == (old["number"], 2, "draft")
    assert revised.value["display_number"] == f"{old['number']}-2"
    assert len(revised.value["lines"]) == 1 and revised.value["valid_until"] >= datetime.date.today()
    third = quotes.revise(tenant_id=TENANT, actor_id=env["actor"], quote_id=revised.value["id"])
    assert third.value["revision"] == 3
    assert quotes.get_quote(tenant_id=TENANT, quote_id=revised.value["id"]).value["status"] == "superseded"
    stale = quotes.revise(tenant_id=TENANT, actor_id=env["actor"], quote_id=old["id"])
    assert isinstance(stale, Err) and stale.code == "QUOTE_NOT_REVISABLE"


def test_quote_discount_limit_and_stats(db, env):
    quotes = QuoteService(db)
    refused = quotes.create_quote(tenant_id=TENANT, actor_id=env["actor"], partner_id=env["customer"], quote_date=TODAY,
                                  lines=[{"product_id": env["pasta"], "quantity": 1, "discount_rate": 25}])
    assert isinstance(refused, Err) and refused.code == "DISCOUNT_ABOVE_LIMIT"
    a = _quote(db, env)
    b = _quote(db, env)
    for quote_id, action in ((a["id"], quotes.accept), (b["id"], quotes.refuse)):
        action(tenant_id=TENANT, actor_id=env["actor"], quote_id=quote_id)
    _quote(db, env)  # still a draft
    stats = quotes.stats(tenant_id=TENANT)
    assert stats["counts"] == {"accepted": 1, "refused": 1, "draft": 1}
    assert stats["conversion_rate"] == D("50.0")
    filtered = quotes.list_quotes(tenant_id=TENANT, status="accepted")
    assert [q["id"] for q in filtered] == [a["id"]]


# ---- HTTP -------------------------------------------------------------------------------------------

class _SharedConnection:
    """The router's connection, made the test's rolled-back one with commit and rollback as no-ops."""

    def __init__(self, connection) -> None:
        self._connection = connection

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass

    def __getattr__(self, name):
        return getattr(self._connection, name)


def _client(db, monkeypatch, permissions):
    from contextlib import contextmanager

    from fastapi.testclient import TestClient

    import core.tenancy
    import modules.sales.api.quote_router
    import modules.sales.api.router

    @contextmanager
    def shared():
        yield _SharedConnection(db)

    for module in (core.tenancy, modules.sales.api.quote_router, modules.sales.api.router):
        monkeypatch.setattr(module, "get_connection", shared)
    from app.main import app

    user, token = str(ULID()), str(ULID())
    db.execute("INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')", (user, TENANT, f"{user}@test.local"))
    db.execute("INSERT INTO core.sessions (token, user_id, tenant_id, expires_at) VALUES (%s, %s, %s, NOW() + interval '1 hour')",
               (token, user, TENANT))
    for permission in permissions:
        db.execute("INSERT INTO core.user_permissions (user_id, permission) VALUES (%s, %s)", (user, permission))
    client = TestClient(app)
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client


def test_quotes_and_price_lists_over_http(db, env, monkeypatch):
    client = _client(db, monkeypatch, ["sales.view_orders", "sales.manage_orders", "sales.view_quotes", "sales.manage_quotes",
                                       "sales.manage_price_lists"])

    created = client.post("/sales/price-lists", json={"name": "HTTP list", "is_default": True})
    assert created.status_code == 201, created.text
    list_id = created.json()["id"]
    put = client.put(f"/sales/price-lists/{list_id}/items", json={"items": [{"product_id": env["pasta"], "unit_price": 990}]})
    assert put.status_code == 200 and put.json()["item_count"] == 1
    resolved = client.post("/sales/prices/resolve", json={"partner_id": env["other"], "items": [{"product_id": env["pasta"], "quantity": 3}]})
    assert float(resolved.json()[0]["unit_price"]) == 990
    exported = client.get(f"/sales/price-lists/{list_id}/export?format=csv")
    assert exported.status_code == 200 and "SP-PASTA" in exported.text

    quote = client.post("/sales/quotes", json={"partner_id": env["other"], "location_id": env["location"],
                                               "lines": [{"product_id": env["pasta"], "quantity": 2}]})
    assert quote.status_code == 201, quote.text
    quote_id = quote.json()["id"]
    over = client.post("/sales/quotes", json={"partner_id": env["other"], "lines": [{"product_id": env["pasta"], "quantity": 2,
                                                                                     "discount_rate": 40}]})
    assert over.status_code == 403 and over.json()["detail"]["code"] == "DISCOUNT_ABOVE_LIMIT"
    assert "dépasse" in over.json()["detail"]["message_fr"]
    assert client.post(f"/sales/quotes/{quote_id}/accept").json()["status"] == "accepted"
    converted = client.post(f"/sales/quotes/{quote_id}/convert", json={})
    assert converted.status_code == 201, converted.text
    conflict = client.post(f"/sales/quotes/{quote_id}/convert", json={})
    assert conflict.status_code == 409
    orders = client.get("/sales/orders").json()
    order = next(o for o in orders if o["id"] == converted.json()["order_id"])
    assert order["quote_id"] == quote_id and order["lines"][0]["vat_rate"] == 18.0
    assert order["totals"]["incl_tax"] == float(converted.json()["quote"]["totals"]["incl_tax"])
    assert client.get("/sales/quotes/stats").json()["counts"]["accepted"] == 1
    forbidden_settings = client.put("/sales/settings", json={"max_discount_rate": 50})
    assert forbidden_settings.status_code == 403
    assert client.get("/sales/settings").json()["may_exceed_discount"] is False
