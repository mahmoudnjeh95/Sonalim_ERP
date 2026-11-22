"""Tax codes: the per-tenant catalog, product and partner assignments, and line resolution against the database."""
from __future__ import annotations

from decimal import Decimal

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from core.tax_codes import TaxCodeService, resolve_lines

TENANT = "integration-test-tax-codes"
D = Decimal


@pytest.fixture
def env(db):
    actor, uom, product, partner = (str(ULID()) for _ in range(4))
    db.execute("INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')", (actor, TENANT, f"{actor}@test.local"))
    db.execute("INSERT INTO core.uoms (id, tenant_id, code, name, category) VALUES (%s, %s, 'pc', 'Piece', 'count')", (uom, TENANT))
    db.execute("INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, 'TAX-P', 'Taxed', %s)", (product, TENANT, uom))
    db.execute("INSERT INTO core.partners (id, tenant_id, name, kind) VALUES (%s, %s, 'Export SA', 'customer')", (partner, TENANT))
    return {"db": db, "actor": actor, "product": product, "partner": partner, "service": TaxCodeService(db)}


def _by_code(service: TaxCodeService) -> dict[str, dict]:
    return {c["code"]: c for c in service.list_codes(tenant_id=TENANT, include_inactive=True)}


def test_the_catalog_starts_with_the_defaults_once(env):
    service = env["service"]
    codes = _by_code(service)
    assert set(codes) == {"TVA18", "EXO"}
    assert (codes["TVA18"]["rate"], codes["EXO"]["rate"], codes["EXO"]["exempt"]) == (D(18), D(0), True)
    service.list_codes(tenant_id=TENANT)
    assert len(service.list_codes(tenant_id=TENANT)) == 2


def test_create_update_and_refusals(env):
    service, actor = env["service"], env["actor"]
    created = service.create_code(tenant_id=TENANT, actor_id=actor, code="tva5", name_fr="TVA 5 %", name_en=None, rate=D(5), scope="sales")
    assert isinstance(created, Ok) and created.value["code"] == "TVA5" and created.value["name_en"] == "TVA 5 %"
    assert service.create_code(tenant_id=TENANT, actor_id=actor, code="TVA5", name_fr="x", name_en=None, rate=5).code == "TAX_CODE_EXISTS"
    assert service.create_code(tenant_id=TENANT, actor_id=actor, code="E2", name_fr="x", name_en=None, rate=5, exempt=True).code == "INVALID_TAX_CODE"
    updated = service.update_code(tenant_id=TENANT, actor_id=actor, tax_code_id=created.value["id"], rate=D("5.5"), active=False)
    assert isinstance(updated, Ok) and (updated.value["rate"], updated.value["active"]) == (D("5.5"), False)
    assert "TVA5" not in {c["code"] for c in service.list_codes(tenant_id=TENANT)}


def test_assignments_check_the_code_and_its_scope(env):
    service, actor = env["service"], env["actor"]
    codes = _by_code(service)
    sales_only = service.create_code(tenant_id=TENANT, actor_id=actor, code="TVA5", name_fr="TVA 5", name_en=None, rate=5, scope="sales").value
    done = service.set_product_codes(tenant_id=TENANT, actor_id=actor, product_id=env["product"],
                                     values={"sales": sales_only["id"], "purchases": codes["TVA18"]["id"]})
    assert done == Ok({"sales_tax_code_id": sales_only["id"], "purchases_tax_code_id": codes["TVA18"]["id"]})
    wrong = service.set_product_codes(tenant_id=TENANT, actor_id=actor, product_id=env["product"], values={"purchases": sales_only["id"]})
    assert isinstance(wrong, Err) and wrong.code == "TAX_CODE_WRONG_SCOPE"
    assert service.set_partner_codes(tenant_id=TENANT, actor_id=actor, partner_id="nope", values={"sales": None}).code == "NOT_FOUND"


def test_lines_resolve_partner_then_product_then_default(env):
    db, service, actor = env["db"], env["service"], env["actor"]
    codes = _by_code(service)
    tva5 = service.create_code(tenant_id=TENANT, actor_id=actor, code="TVA5", name_fr="TVA 5", name_en=None, rate=5).value
    service.set_product_codes(tenant_id=TENANT, actor_id=actor, product_id=env["product"], values={"sales": tva5["id"]})
    lines = [{"product_id": env["product"]}, {"product_id": None}, {"product_id": env["product"], "vat_rate": 18},
             {"product_id": env["product"], "tax_code": "TVA18"}]
    resolved = resolve_lines(db, tenant_id=TENANT, side="sales", partner_id=env["partner"], default_rate=D(18), lines=lines).value
    assert [(r.tax_code, r.rate) for r in resolved] == [("TVA5", D(5)), ("TVA18", D(18)), ("TVA18", D(18)), ("TVA18", D(18))]

    service.set_partner_codes(tenant_id=TENANT, actor_id=actor, partner_id=env["partner"], values={"sales": codes["EXO"]["id"]})
    resolved = resolve_lines(db, tenant_id=TENANT, side="sales", partner_id=env["partner"], default_rate=D(18), lines=lines[:2]).value
    assert [(r.tax_code, r.rate) for r in resolved] == [("EXO", D(0)), ("EXO", D(0))]
    # the purchase side ignores the customer exemption
    resolved = resolve_lines(db, tenant_id=TENANT, side="purchases", partner_id=env["partner"], default_rate=D(18), lines=lines[:1]).value
    assert [(r.tax_code, r.rate) for r in resolved] == [("TVA18", D(18))]

    refused = resolve_lines(db, tenant_id=TENANT, side="sales", partner_id=None, default_rate=D(18),
                            lines=[{"product_id": None}, {"product_id": None, "tax_code": "TVA18", "vat_rate": 5}])
    assert isinstance(refused, Err) and refused.code == "TAX_RATE_MISMATCH" and refused.message.startswith("line 2:")
