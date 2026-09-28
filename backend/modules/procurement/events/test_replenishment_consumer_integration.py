"""Procurement's half of replenishment: an approved warehouse proposal becomes
a draft purchase order, once."""
from __future__ import annotations

import pytest
from ulid import ULID

from modules.procurement.events.consumers import _handle_replenishment_approved, replenishment_note

TENANT = "integration-test-replenishment-po"


@pytest.fixture
def env(db):
    uom, product, supplier = (str(ULID()) for _ in range(3))
    db.execute("INSERT INTO core.uoms (id, tenant_id, code, name, category) VALUES (%s, %s, 'kg', 'Kilogram', 'weight')", (uom, TENANT))
    db.execute("INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, 'RPO-SEMO', 'Semolina', %s)", (product, TENANT, uom))
    db.execute("INSERT INTO core.partners (id, tenant_id, name, kind) VALUES (%s, %s, 'Mill', 'supplier')", (supplier, TENANT))
    return {"uom": uom, "product": product, "supplier": supplier}


def _envelope(env, proposal_id):
    return {
        "event_id": str(ULID()),
        "event_type": "warehouse.replenishment.approved",
        "tenant_id": TENANT,
        "correlation_id": str(ULID()),
        "payload": {
            "proposal_id": proposal_id, "product_id": env["product"], "uom_id": env["uom"], "quantity": 250,
            "supplier_id": env["supplier"], "site_id": None,
        },
    }


def _orders(db, proposal_id):
    return db.execute(
        "SELECT id, supplier_id, status FROM procurement.purchase_orders WHERE tenant_id = %s AND notes = %s",
        (TENANT, replenishment_note(proposal_id)),
    ).fetchall()


def test_an_approved_proposal_drafts_a_purchase_order(db, env):
    proposal_id = str(ULID())
    _handle_replenishment_approved(db, _envelope(env, proposal_id))
    [(order_id, supplier_id, status)] = _orders(db, proposal_id)
    assert (supplier_id, status) == (env["supplier"], "draft")
    line = db.execute(
        "SELECT product_id, quantity_ordered FROM procurement.purchase_order_lines WHERE purchase_order_id = %s", (order_id,)
    ).fetchone()
    assert (line[0], float(line[1])) == (env["product"], 250)


def test_a_redelivered_approval_drafts_nothing_more(db, env):
    proposal_id = str(ULID())
    _handle_replenishment_approved(db, _envelope(env, proposal_id))
    _handle_replenishment_approved(db, _envelope(env, proposal_id))
    assert len(_orders(db, proposal_id)) == 1
