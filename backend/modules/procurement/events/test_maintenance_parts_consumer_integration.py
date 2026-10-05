"""Procurement's half of a maintenance parts request: the lines a supervisor could not
issue from stock become one draft purchase order, once."""
from __future__ import annotations

import pytest
from ulid import ULID

from core.events.consumers import _registry
from modules.procurement.events.consumers import (
    MAINTENANCE_PARTS_CONSUMER_NAME,
    _handle_maintenance_parts_purchase_requested,
    maintenance_parts_note,
)

TENANT = "integration-test-maintenance-parts-po"
EVENT = "maintenance.parts.purchase_requested"


@pytest.fixture
def env(db):
    piece, litre, bearing, oil = (str(ULID()) for _ in range(4))
    db.execute(
        "INSERT INTO core.uoms (id, tenant_id, code, name, category, is_integer_only) VALUES (%s, %s, 'pc', 'Pièce', 'unit', TRUE)",
        (piece, TENANT),
    )
    db.execute("INSERT INTO core.uoms (id, tenant_id, code, name, category) VALUES (%s, %s, 'L', 'Litre', 'volume')", (litre, TENANT))
    db.execute(
        "INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, 'MPO-ROUL', 'Roulement 6204', %s)",
        (bearing, TENANT, piece),
    )
    db.execute(
        "INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, 'MPO-HUILE', 'Huile hydraulique', %s)",
        (oil, TENANT, litre),
    )
    return {"piece": piece, "litre": litre, "bearing": bearing, "oil": oil}


def _envelope(env, request_id):
    return {
        "event_id": str(ULID()),
        "event_type": EVENT,
        "tenant_id": TENANT,
        "correlation_id": str(ULID()),
        "payload": {
            "request_id": request_id,
            "job_number": "MT-2026-0007",
            "lines": [
                {"line_id": str(ULID()), "product_id": env["bearing"], "uom_id": env["piece"], "quantity": 6.0},
                {"line_id": str(ULID()), "product_id": env["oil"], "uom_id": env["litre"], "quantity": 2.5},
            ],
        },
    }


def _orders(db, request_id):
    return db.execute(
        "SELECT id, supplier_id, status FROM procurement.purchase_orders WHERE tenant_id = %s AND notes = %s",
        (TENANT, maintenance_parts_note(request_id)),
    ).fetchall()


def test_consumer_drafts_one_po_and_is_idempotent(db, env):
    request_id = str(ULID())
    envelope = _envelope(env, request_id)

    _handle_maintenance_parts_purchase_requested(db, envelope)
    # the same event redelivered, and the same request published again under a new event id
    _handle_maintenance_parts_purchase_requested(db, envelope)
    _handle_maintenance_parts_purchase_requested(db, {**envelope, "event_id": str(ULID())})

    [(order_id, supplier_id, status)] = _orders(db, request_id)
    assert maintenance_parts_note(request_id) == f"maintenance:{request_id}"
    # a draft for a buyer to complete: no supplier, no price yet
    assert (supplier_id, status) == (None, "draft")
    lines = db.execute(
        """
        SELECT product_id, uom_id, quantity_ordered, unit_price, unit_price_currency
        FROM procurement.purchase_order_lines WHERE purchase_order_id = %s
        """,
        (order_id,),
    ).fetchall()
    assert sorted((p, u, float(q), float(price), currency) for p, u, q, price, currency in lines) == sorted(
        [
            (env["bearing"], env["piece"], 6.0, 0.0, "XOF"),
            (env["oil"], env["litre"], 2.5, 0.0, "XOF"),
        ]
    )


def test_two_requests_draft_two_orders(db, env):
    first, second = str(ULID()), str(ULID())
    _handle_maintenance_parts_purchase_requested(db, _envelope(env, first))
    _handle_maintenance_parts_purchase_requested(db, _envelope(env, second))
    assert len(_orders(db, first)) == 1 and len(_orders(db, second)) == 1


def test_a_purchase_order_the_service_refuses_fails_the_delivery(db, env):
    envelope = _envelope(env, str(ULID()))
    envelope["payload"]["lines"][0]["product_id"] = "no-such-product"
    with pytest.raises(RuntimeError):
        _handle_maintenance_parts_purchase_requested(db, envelope)


def test_the_consumer_is_registered_on_the_event():
    assert (MAINTENANCE_PARTS_CONSUMER_NAME, _handle_maintenance_parts_purchase_requested) in _registry[EVENT]
    assert MAINTENANCE_PARTS_CONSUMER_NAME == "procurement.maintenance_parts"
