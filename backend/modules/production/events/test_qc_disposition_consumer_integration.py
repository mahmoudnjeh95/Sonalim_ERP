"""The cross-module loop: qc decides, production reacts.

`scrap_records` belongs to production and qc may not write into it, so the pasta
pulled out of a rejected packet reaches rebroyat by event rather than by a foreign
key.

The handler is exercised directly rather than through `core.events.consumers._process`,
because that function commits after each handler — which would defeat the rollback
fixture and leave residue in a development database. Idempotency is a property of
the registry, not of this handler, so it is asserted through the skip path, which
does not commit.
"""
from __future__ import annotations

import pytest
from ulid import ULID

from core.domain.result import Ok
from core.events.consumers import _process
from modules.production.api.service import WorkOrderService
from modules.production.events.consumers import CONSUMER_NAME, _handle_non_conformity_dispositioned

TENANT = "integration-test-consumer"


@pytest.fixture
def env(db):
    actor = str(ULID())
    uom, product, work_center = (str(ULID()) for _ in range(3))
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (actor, TENANT, f"{actor}@test.local"),
    )
    db.execute(
        "INSERT INTO core.uoms (id, tenant_id, code, name, category) VALUES (%s, %s, 'kg', 'Kilogram', 'weight')",
        (uom, TENANT),
    )
    db.execute(
        "INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, 'CONS-P', 'Pasta', %s)",
        (product, TENANT, uom),
    )
    db.execute(
        "INSERT INTO production.work_centers (id, tenant_id, code, name) VALUES (%s, %s, 'CONS-WC', 'Line')",
        (work_center, TENANT),
    )
    created = WorkOrderService(db).create_work_order(
        tenant_id=TENANT,
        actor_id=actor,
        product_id=product,
        planned_quantity=1000,
        work_center_id=work_center,
    )
    assert isinstance(created, Ok), getattr(created, "message", "")
    return {"actor": actor, "product": product, "of": created.value}


def _envelope(env, *, event_id: str, lines: list[dict]) -> dict:
    return {
        "event_id": event_id,
        "event_type": "qc.non_conformity.dispositioned",
        "tenant_id": TENANT,
        "correlation_id": str(ULID()),
        "payload": {
            "non_conformity_id": "NC-TEST",
            "of_id": env["of"].id,
            "product_id": env["product"],
            "lines": lines,
        },
    }


def _scrap_count(db) -> int:
    return db.execute(
        "SELECT count(*) FROM production.scrap_records WHERE tenant_id = %s", (TENANT,)
    ).fetchone()[0]


def test_a_regrind_disposition_becomes_a_scrap_record(db, env):
    _handle_non_conformity_dispositioned(
        db,
        _envelope(env, event_id=str(ULID()), lines=[{"component": "product", "disposition": "regrind", "quantity": 8}]),
    )

    scrap_type, quantity, work_order_id, source_note = db.execute(
        "SELECT scrap_type, quantity, work_order_id, source_note FROM production.scrap_records WHERE tenant_id = %s",
        (TENANT,),
    ).fetchone()
    assert scrap_type == "non_conformity"
    assert float(quantity) == 8
    assert work_order_id == env["of"].id
    assert "NC-TEST" in source_note


def test_dechet_lines_do_not_become_scrap(db, env):
    """Film, carton and tape are reported as déchet on the ticket, not reground.

    Locked decision 8: their stock already left at conditionnement, so turning them
    into scrap here would double-count the loss.
    """
    _handle_non_conformity_dispositioned(
        db,
        _envelope(
            env,
            event_id=str(ULID()),
            lines=[
                {"component": "film", "disposition": "dechet", "quantity": 0.4},
                {"component": "carton", "disposition": "dechet", "quantity": 1},
                {"component": "tape", "disposition": "dechet", "quantity": 0.1},
            ],
        ),
    )
    assert _scrap_count(db) == 0


def test_only_the_regrind_lines_are_taken_from_a_mixed_disposition(db, env):
    _handle_non_conformity_dispositioned(
        db,
        _envelope(
            env,
            event_id=str(ULID()),
            lines=[
                {"component": "product", "disposition": "regrind", "quantity": 8},
                {"component": "film", "disposition": "dechet", "quantity": 0.4},
                {"component": "carton", "disposition": "dechet", "quantity": 1},
            ],
        ),
    )
    assert _scrap_count(db) == 1


def test_an_already_processed_event_is_skipped(db, env):
    """At-least-once delivery, made harmless by the registry's processed-events log.

    The skip path is asserted rather than a full redelivery because `_process`
    commits on the success path.
    """
    event_id = str(ULID())
    db.execute(
        "INSERT INTO events.processed_events (event_id, consumer) VALUES (%s, %s)",
        (event_id, CONSUMER_NAME),
    )

    handled = _process(
        db,
        _envelope(env, event_id=event_id, lines=[{"component": "product", "disposition": "regrind", "quantity": 8}]),
    )
    assert handled
    assert _scrap_count(db) == 0, "a redelivered event must not write a second scrap record"


def test_the_scrap_it_writes_is_available_to_the_regrind_workflow(db, env):
    """The point of the loop: rebroyat from quality reaches the same workflow as
    rebroyat from a daily report."""
    _handle_non_conformity_dispositioned(
        db,
        _envelope(env, event_id=str(ULID()), lines=[{"component": "product", "disposition": "regrind", "quantity": 8}]),
    )
    available = db.execute(
        "SELECT count(*) FROM production.scrap_records WHERE tenant_id = %s AND NOT is_reground", (TENANT,)
    ).fetchone()[0]
    assert available == 1


def test_the_handler_works_against_a_closed_of(db, env):
    """Quality outlives production, so a disposition often lands after closure."""
    service = WorkOrderService(db)
    service.start_work_order(tenant_id=TENANT, actor_id=env["actor"], work_order_id=env["of"].id)
    service.close_work_order(
        tenant_id=TENANT, actor_id=env["actor"], work_order_id=env["of"].id, correlation_id=str(ULID())
    )

    _handle_non_conformity_dispositioned(
        db,
        _envelope(env, event_id=str(ULID()), lines=[{"component": "product", "disposition": "regrind", "quantity": 8}]),
    )
    assert _scrap_count(db) == 1
