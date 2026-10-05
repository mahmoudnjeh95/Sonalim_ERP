"""Integration tests for the reservation ledger and TTL expiry."""
from __future__ import annotations

import datetime

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from modules.warehouse.api.reservation_service import ReservationService
from modules.warehouse.api.service import StockService

TENANT = "integration-test-reservations"
UTC = datetime.timezone.utc


@pytest.fixture
def env(db):
    actor, uom, product, location = (str(ULID()) for _ in range(4))
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (actor, TENANT, f"{actor}@test.local"),
    )
    db.execute("INSERT INTO core.uoms (id, tenant_id, code, name, category) VALUES (%s, %s, 'kg', 'Kilogram', 'weight')", (uom, TENANT))
    db.execute("INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, 'RS-P', 'Pasta', %s)", (product, TENANT, uom))
    db.execute(
        "INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, %s, 'Main')", (location, TENANT, str(ULID()))
    )
    StockService(db).receive_stock(
        tenant_id=TENANT, product_id=product, location_id=location, quantity=100, correlation_id=str(ULID()), reference="setup"
    )
    return {"actor": actor, "product": product, "location": location}


def _reserve(db, env, quantity, reference, expires_at=None):
    result = StockService(db).reserve_stock(
        tenant_id=TENANT, product_id=env["product"], location_id=env["location"], quantity=quantity,
        correlation_id=str(ULID()), reference=reference, actor_id=env["actor"], expires_at=expires_at,
    )
    assert isinstance(result, Ok), getattr(result, "message", "")


def _reserved(db, env) -> float:
    return StockService(db).list_stock_items(TENANT, location_id=env["location"])[0].quantity_reserved


def _ledger(db, reference):
    return [r for r in ReservationService(db).list_reservations(tenant_id=TENANT) if r.reference == reference]


def _backdate(db, reference, when):
    """The service refuses a past expiry, so a lapsed hold is made by moving
    an existing one's expiry into the past directly."""
    db.execute(
        "UPDATE warehouse.stock_reservations SET expires_at = %s WHERE tenant_id = %s AND reference = %s", (when, TENANT, reference)
    )


def test_every_reservation_gets_a_ledger_row(db, env):
    _reserve(db, env, 10, "hold:a")
    [row] = _ledger(db, "hold:a")
    assert (row.quantity, row.quantity_open, row.status, row.expires_at) == (10, 10, "active", None)


def test_a_past_expiry_is_refused_at_reservation_time(db, env):
    result = StockService(db).reserve_stock(
        tenant_id=TENANT, product_id=env["product"], location_id=env["location"], quantity=1, correlation_id=str(ULID()),
        reference="hold:past", expires_at=datetime.datetime.now(UTC) - datetime.timedelta(minutes=1),
    )
    assert isinstance(result, Err) and result.code == "INVALID_EXPIRY"
    assert _reserved(db, env) == 0


def test_releasing_by_reference_closes_ledger_rows_oldest_first(db, env):
    _reserve(db, env, 10, "hold:b")
    _reserve(db, env, 5, "hold:b")
    StockService(db).release_stock_reservation(
        tenant_id=TENANT, product_id=env["product"], location_id=env["location"], quantity=12, reference="hold:b"
    )
    rows = sorted(_ledger(db, "hold:b"), key=lambda r: r.quantity, reverse=True)
    assert [(r.quantity_open, r.status) for r in rows] == [(0, "released"), (3, "active")]
    assert _reserved(db, env) == 3


def test_a_lapsed_reservation_is_expired_and_its_stock_given_back(db, env):
    _reserve(db, env, 10, "hold:c", expires_at=datetime.datetime.now(UTC) + datetime.timedelta(hours=1))
    _reserve(db, env, 4, "hold:keep")  # no expiry: never touched by the sweep
    _backdate(db, "hold:c", datetime.datetime.now(UTC) - datetime.timedelta(minutes=5))

    expired = ReservationService(db).expire_due_reservations(now=datetime.datetime.now(UTC), tenant_id=TENANT)
    assert [r.reference for r in expired] == ["hold:c"]
    assert expired[0].status == "expired"
    assert _reserved(db, env) == 4

    move = db.execute(
        "SELECT quantity FROM warehouse.stock_moves WHERE tenant_id = %s AND reference = 'hold:c' AND move_type = 'reservation_expired'",
        (TENANT,),
    ).fetchone()
    assert float(move[0]) == 10
    event = db.execute(
        "SELECT payload FROM events.outbox WHERE tenant_id = %s AND event_type = 'warehouse.reservation.expired'", (TENANT,)
    ).fetchone()[0]
    assert event["payload"]["quantity"] == 10


def test_a_second_sweep_does_nothing(db, env):
    _reserve(db, env, 10, "hold:d", expires_at=datetime.datetime.now(UTC) + datetime.timedelta(hours=1))
    _backdate(db, "hold:d", datetime.datetime.now(UTC) - datetime.timedelta(minutes=5))
    service = ReservationService(db)
    service.expire_due_reservations(now=datetime.datetime.now(UTC), tenant_id=TENANT)
    assert service.expire_due_reservations(now=datetime.datetime.now(UTC), tenant_id=TENANT) == []
    assert _reserved(db, env) == 0


def test_expiry_never_releases_more_than_the_counter_still_holds(db, env):
    _reserve(db, env, 10, "hold:e", expires_at=datetime.datetime.now(UTC) + datetime.timedelta(hours=1))
    # An admin overwrite lowered the counter behind the ledger's back.
    db.execute(
        "UPDATE warehouse.stock_items SET quantity_reserved = 6 WHERE tenant_id = %s AND product_id = %s", (TENANT, env["product"])
    )
    _backdate(db, "hold:e", datetime.datetime.now(UTC) - datetime.timedelta(minutes=5))
    [expired] = ReservationService(db).expire_due_reservations(now=datetime.datetime.now(UTC), tenant_id=TENANT)
    assert expired.status == "expired"
    assert _reserved(db, env) == 0


def test_manual_release_frees_one_specific_reservation(db, env):
    _reserve(db, env, 10, "hold:f")
    [row] = _ledger(db, "hold:f")
    result = ReservationService(db).release_reservation(tenant_id=TENANT, actor_id=env["actor"], reservation_id=row.id)
    assert isinstance(result, Ok) and result.value.status == "released"
    assert _reserved(db, env) == 0
    again = ReservationService(db).release_reservation(tenant_id=TENANT, actor_id=env["actor"], reservation_id=row.id)
    assert isinstance(again, Err) and again.code == "INVALID_STATE"


def test_admin_update_extends_or_clears_the_expiry_and_is_audited(db, env):
    _reserve(db, env, 2, "hold:g", expires_at=datetime.datetime.now(UTC) + datetime.timedelta(hours=1))
    [row] = _ledger(db, "hold:g")
    later = datetime.datetime.now(UTC) + datetime.timedelta(days=2)
    service = ReservationService(db)
    extended = service.update_reservation(tenant_id=TENANT, actor_id=env["actor"], reservation_id=row.id, expires_at=later)
    assert isinstance(extended, Ok) and extended.value.expires_at == later
    cleared = service.update_reservation(tenant_id=TENANT, actor_id=env["actor"], reservation_id=row.id, clear_expiry=True)
    assert isinstance(cleared, Ok) and cleared.value.expires_at is None
    audits = db.execute(
        "SELECT count(*) FROM core.audit_log WHERE tenant_id = %s AND entity_id = %s AND action = 'stock_reservation.updated'",
        (TENANT, row.id),
    ).fetchone()[0]
    assert audits == 2


def test_two_reservations_in_one_transaction_do_not_share_a_timestamp(db, env):
    """Releasing closes reservations oldest first (ORDER BY created_at, id). NOW() is the
    transaction's start time, so two reservations taken together shared it and the order
    fell to the ULID tie-break, which is not ordered inside a millisecond -- the newer
    hold could be closed before the older one."""
    _reserve(db, env, 10, "hold:tie")
    _reserve(db, env, 5, "hold:tie")

    times = [
        row[0]
        for row in db.execute(
            "SELECT created_at FROM warehouse.stock_reservations WHERE tenant_id = %s AND reference = 'hold:tie' "
            "ORDER BY created_at, id",
            (TENANT,),
        ).fetchall()
    ]

    assert len(times) == 2
    assert times[0] < times[1], "both reservations share a timestamp: the release order depends on the id tie-break"
