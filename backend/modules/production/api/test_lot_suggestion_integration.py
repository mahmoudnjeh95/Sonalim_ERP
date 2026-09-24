"""Integration tests for the lot number a packing report is offered, against a real database.

The suggestion is read from what the same line already filed -- drafts and submitted
shifts included, since the number is wanted while the day's first report is still
being typed. A returned shift's packing does not count, since its figures were sent
back as wrong.
"""
from __future__ import annotations

import datetime

import pytest
from ulid import ULID

from core.domain.result import Ok
from modules.production.api.lot_suggestion_service import LotSuggestionService
from modules.production.api.service import WorkOrderService
from modules.production.api.shift_report_service import ShiftReportService
from modules.production.api.shift_validation_service import ShiftValidationService
from modules.production.domain.shift_report import SECTION_KEYS

TENANT = "integration-test-lot-suggestion"
D = datetime.date


@pytest.fixture
def env(db):
    actor, uom, product, line, other_line, machine, location = (str(ULID()) for _ in range(7))
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (actor, TENANT, f"{actor}@test.local"),
    )
    db.execute("INSERT INTO core.uoms (id, tenant_id, code, name, category) VALUES (%s, %s, 'kg', 'Kilogram', 'weight')", (uom, TENANT))
    db.execute("INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, 'LS-LOC', 'Finished goods')", (location, TENANT))
    db.execute(
        "INSERT INTO core.products (id, tenant_id, sku, name, uom_id, default_location_id) VALUES (%s, %s, 'LS-P', 'Pasta', %s, %s)",
        (product, TENANT, uom, location),
    )
    for work_center, code in ((line, "LS-L1"), (other_line, "LS-L2")):
        db.execute(
            "INSERT INTO production.work_centers (id, tenant_id, code, name) VALUES (%s, %s, %s, %s)",
            (work_center, TENANT, code, code),
        )
    db.execute(
        "INSERT INTO maintenance.equipment (id, tenant_id, work_center_id, code, name) VALUES (%s, %s, %s, 'LS-EQ', 'Packer')",
        (machine, TENANT, line),
    )
    return {"actor": actor, "product": product, "line": line, "other_line": other_line, "machine": machine}


def _ok(result):
    assert isinstance(result, Ok), getattr(result, "message", result)
    return result.value


def _of(db, env, line=None):
    orders = WorkOrderService(db)
    created = _ok(orders.create_work_order(
        tenant_id=TENANT, actor_id=env["actor"], product_id=env["product"], planned_quantity=1000,
        work_center_id=line or env["line"], start_date=D(2026, 6, 1),
    ))
    orders.start_work_order(tenant_id=TENANT, actor_id=env["actor"], work_order_id=created.id)
    return created.id


def _file(db, env, of_id, day, lot, *, line=None, reject=False):
    """A shift's packing row carrying this lot, submitted (and optionally returned)."""
    service = ShiftReportService(db)
    shift_id = _ok(service.open_shift(
        tenant_id=TENANT, actor_id=env["actor"], work_center_id=line or env["line"], report_date=day, shift="morning",
    ))["id"]
    _ok(service.save_section(
        tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key="packing",
        payload={"rows": [{
            "of_id": of_id, "equipment_id": env["machine"], "finished_product_quantity": 100,
            "packets_counted": 100, "lot_number": lot,
            "dlc_date": (day + datetime.timedelta(days=700)).isoformat() if lot else None,
        }]},
    ))
    for key in SECTION_KEYS:
        if key == "packing":
            _ok(service.submit_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key))
        else:
            _ok(service.declare_nothing(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key))
    if reject:
        _ok(ShiftValidationService(db).reject_sections(
            tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id,
            section_keys=["packing"], reason="wrong lot",
        ))
    return shift_id


def _suggest(db, env, day, line=None):
    return LotSuggestionService(db).suggest(tenant_id=TENANT, work_center_id=line or env["line"], report_date=day)


def test_a_line_that_never_filed_a_lot_has_nothing_to_follow(db, env):
    assert _suggest(db, env, D(2026, 7, 6)) == {"lot_number": None, "based_on": None}


def test_the_next_days_lot_is_the_last_one_counted_on(db, env):
    _file(db, env, _of(db, env), D(2026, 7, 5), "4187SNL")
    assert _suggest(db, env, D(2026, 7, 8)) == {
        "lot_number": "4190SNL",
        "based_on": {"lot_number": "4187SNL", "report_date": "2026-07-05"},
    }


def test_the_same_day_is_offered_the_same_lot_so_every_shift_shares_it(db, env):
    of_id = _of(db, env)
    _file(db, env, of_id, D(2026, 7, 5), "4187SNL")
    assert _suggest(db, env, D(2026, 7, 5))["lot_number"] == "4187SNL"


def test_only_the_lines_own_lots_are_followed(db, env):
    _file(db, env, _of(db, env), D(2026, 7, 5), "4187SNL")
    assert _suggest(db, env, D(2026, 7, 6), line=env["other_line"])["lot_number"] is None


def test_the_latest_lot_on_or_before_the_day_is_the_one_followed(db, env):
    of_id = _of(db, env)
    _file(db, env, of_id, D(2026, 7, 1), "4183SNL")
    _file(db, env, of_id, D(2026, 7, 10), "4192SNL")
    # A report filed for the 5th is counted on from the 1st, not from the 10th.
    assert _suggest(db, env, D(2026, 7, 5))["lot_number"] == "4187SNL"
    assert _suggest(db, env, D(2026, 7, 11))["lot_number"] == "4193SNL"


def test_a_returned_shift_does_not_set_the_counter(db, env):
    of_id = _of(db, env)
    _file(db, env, of_id, D(2026, 7, 5), "4187SNL")
    _file(db, env, of_id, D(2026, 7, 6), "9999SNL", reject=True)
    assert _suggest(db, env, D(2026, 7, 7))["lot_number"] == "4189SNL"


def test_a_free_text_lot_is_skipped_for_the_last_lot_that_is_a_counter(db, env):
    of_id = _of(db, env)
    _file(db, env, of_id, D(2026, 7, 5), "4187SNL")
    _file(db, env, of_id, D(2026, 7, 6), "essai-juillet")
    assert _suggest(db, env, D(2026, 7, 8))["based_on"]["lot_number"] == "4187SNL"


def test_a_report_with_no_lot_is_not_a_lot_to_follow(db, env):
    of_id = _of(db, env)
    _file(db, env, of_id, D(2026, 7, 5), "4187SNL")
    _file(db, env, of_id, D(2026, 7, 6), None)
    assert _suggest(db, env, D(2026, 7, 7))["lot_number"] == "4189SNL"
