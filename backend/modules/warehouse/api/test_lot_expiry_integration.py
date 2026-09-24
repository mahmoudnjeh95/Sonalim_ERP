"""Integration tests for setting a lot's DLC afterwards, against a real database.

Production registers a finished-goods lot with its number only; quality enters the DLC
once it has one. The lot is the single place the DLC lives, so the change is audited and
a value already there can be corrected without losing what it was.
"""
from __future__ import annotations

import datetime

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from modules.warehouse.api.lot_service import LotService

TENANT = "integration-test-lot-expiry"
OTHER_TENANT = "integration-test-lot-expiry-other"
D = datetime.date
PRODUCED = datetime.datetime(2026, 7, 5)
FINISHED_GOODS = "production.conditionnement_report"


@pytest.fixture
def env(db):
    actor, uom, product = (str(ULID()) for _ in range(3))
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (actor, TENANT, f"{actor}@test.local"),
    )
    db.execute("INSERT INTO core.uoms (id, tenant_id, code, name, category) VALUES (%s, %s, 'kg', 'Kilogram', 'weight')", (uom, TENANT))
    db.execute("INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, 'LE-P', 'Pasta', %s)", (product, TENANT, uom))
    return {"actor": actor, "product": product}


def _register(db, env, number, *, produced=PRODUCED, expiry=None, source_type=FINISHED_GOODS):
    lot = LotService(db).register_lot(
        tenant_id=TENANT, product_id=env["product"], lot_number=number, actor_id=env["actor"],
        expiry_date=expiry, produced_at=produced, source_type=source_type, source_id=str(ULID()),
    )
    assert isinstance(lot, Ok), getattr(lot, "message", "")
    return lot.value


def _set(db, env, lot, expiry):
    return LotService(db).set_expiry(tenant_id=TENANT, actor_id=env["actor"], lot_id=lot.id, expiry_date=expiry)


def test_a_lot_registered_without_a_dlc_can_be_given_one_later(db, env):
    lot = _register(db, env, "4187SNL")
    assert lot.expiry_date is None

    result = _set(db, env, lot, D(2029, 7, 5))
    assert isinstance(result, Ok) and result.value.expiry_date == "2029-07-05"
    stored = db.execute("SELECT expiry_date FROM warehouse.lots WHERE id = %s", (lot.id,)).fetchone()[0]
    assert stored == D(2029, 7, 5)


def test_setting_the_dlc_is_audited_with_the_lot_who_and_the_dates(db, env):
    lot = _register(db, env, "4187SNL")
    _set(db, env, lot, D(2029, 7, 5))

    row = db.execute(
        "SELECT actor_id, payload FROM core.audit_log WHERE tenant_id = %s AND entity_id = %s AND action = 'lot.expiry_set'",
        (TENANT, lot.id),
    ).fetchone()
    assert row[0] == env["actor"]
    assert row[1] == {"lot_number": "4187SNL", "from": None, "to": "2029-07-05"}


def test_a_dlc_can_be_corrected_and_the_trail_keeps_what_it_was(db, env):
    lot = _register(db, env, "4187SNL", expiry=D(2029, 7, 5))
    result = _set(db, env, lot, D(2029, 7, 1))
    assert isinstance(result, Ok) and result.value.expiry_date == "2029-07-01"

    payloads = [
        row[0]
        for row in db.execute(
            "SELECT payload FROM core.audit_log WHERE tenant_id = %s AND entity_id = %s AND action = 'lot.expiry_set'",
            (TENANT, lot.id),
        ).fetchall()
    ]
    assert payloads == [{"lot_number": "4187SNL", "from": "2029-07-05", "to": "2029-07-01"}]


def test_a_dlc_before_the_day_the_lot_was_made_is_refused_and_changes_nothing(db, env):
    lot = _register(db, env, "4187SNL")
    result = _set(db, env, lot, D(2026, 7, 4))
    assert isinstance(result, Err) and result.code == "INVALID_EXPIRY"
    assert db.execute("SELECT expiry_date FROM warehouse.lots WHERE id = %s", (lot.id,)).fetchone()[0] is None
    assert db.execute("SELECT count(*) FROM core.audit_log WHERE entity_id = %s AND action = 'lot.expiry_set'", (lot.id,)).fetchone()[0] == 0


def test_a_dlc_on_the_day_the_lot_was_made_is_allowed(db, env):
    lot = _register(db, env, "4187SNL")
    assert isinstance(_set(db, env, lot, D(2026, 7, 5)), Ok)


def test_a_lot_with_no_production_day_takes_any_dlc(db, env):
    lot = _register(db, env, "SUP-1", produced=None, source_type="procurement_receipt")
    assert isinstance(_set(db, env, lot, D(2020, 1, 1)), Ok)


def test_a_lot_that_does_not_exist_is_not_found_and_neither_is_another_tenants(db, env):
    lot = _register(db, env, "4187SNL")
    missing = LotService(db).set_expiry(tenant_id=TENANT, actor_id=env["actor"], lot_id=str(ULID()), expiry_date=D(2029, 1, 1))
    assert isinstance(missing, Err) and missing.code == "NOT_FOUND"
    foreign = LotService(db).set_expiry(tenant_id=OTHER_TENANT, actor_id=env["actor"], lot_id=lot.id, expiry_date=D(2029, 1, 1))
    assert isinstance(foreign, Err) and foreign.code == "NOT_FOUND"
    assert db.execute("SELECT expiry_date FROM warehouse.lots WHERE id = %s", (lot.id,)).fetchone()[0] is None


def test_the_lots_waiting_for_a_dlc_can_be_listed_apart_from_the_rest(db, env):
    waiting = _register(db, env, "4187SNL")
    _register(db, env, "4186SNL", expiry=D(2029, 7, 4))
    _register(db, env, "SUP-1", produced=None, source_type="procurement_receipt")

    service = LotService(db)
    only_waiting = service.list_lots(tenant_id=TENANT, source_type=FINISHED_GOODS, without_expiry=True)
    assert [lot.id for lot in only_waiting] == [waiting.id]
    assert {lot.lot_number for lot in service.list_lots(tenant_id=TENANT, without_expiry=True)} == {"4187SNL", "SUP-1"}
    assert {lot.lot_number for lot in service.list_lots(tenant_id=TENANT, source_type=FINISHED_GOODS)} == {"4187SNL", "4186SNL"}
    assert len(service.list_lots(tenant_id=TENANT)) == 3

    # Once quality enters the DLC the lot leaves the queue.
    _set(db, env, waiting, D(2029, 7, 5))
    assert service.list_lots(tenant_id=TENANT, source_type=FINISHED_GOODS, without_expiry=True) == []
