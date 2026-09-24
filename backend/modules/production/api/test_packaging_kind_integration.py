"""A packaging component can be given the kind of packaging it is."""
from __future__ import annotations

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from modules.production.api.product_classification_service import ProductClassificationService

TENANT = "packaging-kind-test"


@pytest.fixture
def env(db):
    actor, uom, product = (str(ULID()) for _ in range(3))
    db.execute("INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')", (actor, TENANT, f"{actor}@test.local"))
    db.execute("INSERT INTO core.uoms (id, tenant_id, code, name, category) VALUES (%s, %s, 'kg', 'Kilogram', 'weight')", (uom, TENANT))
    db.execute("INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, 'PK-FILM', 'Film', %s)", (product, TENANT, uom))
    return {"actor": actor, "product": product}


def test_the_kind_is_stored_and_listed(db, env):
    service = ProductClassificationService(db)
    saved = service.set_classification(
        tenant_id=TENANT, actor_id=env["actor"], product_id=env["product"], category="packaging_component", packaging_kind="film"
    )
    assert isinstance(saved, Ok) and saved.value.packaging_kind == "film"
    assert service.get_classification(TENANT, env["product"]).packaging_kind == "film"
    listed = service.list_classifications(TENANT, category="packaging_component")
    assert [c.packaging_kind for c in listed] == ["film"]


def test_the_kind_is_refused_on_other_categories(db, env):
    result = ProductClassificationService(db).set_classification(
        tenant_id=TENANT, actor_id=env["actor"], product_id=env["product"], category="raw_material", packaging_kind="film"
    )
    assert isinstance(result, Err) and result.code == "PACKAGING_KIND_INVALID"


def test_reclassifying_drops_the_kind(db, env):
    service = ProductClassificationService(db)
    service.set_classification(tenant_id=TENANT, actor_id=env["actor"], product_id=env["product"], category="packaging_component", packaging_kind="carton")
    service.set_classification(tenant_id=TENANT, actor_id=env["actor"], product_id=env["product"], category="raw_material")
    assert service.get_classification(TENANT, env["product"]).packaging_kind is None
