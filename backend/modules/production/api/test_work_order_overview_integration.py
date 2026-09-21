"""One row per OF for the list: official figures from validated shifts, pending ones beside them."""
from __future__ import annotations

import datetime

import pytest

from modules.production.api.service import WorkOrderService
from modules.production.api.shift_report_service import ShiftReportService
from modules.production.api.shift_validation_service import ShiftValidationService
from modules.production.api.test_packing_product_validation_integration import (  # noqa: F401  (env is a fixture)
    DAY,
    TENANT,
    _ok,
    _two_product_shift,
    env,
)
from modules.production.api.work_order_overview_service import WorkOrderOverviewService

MORNING = datetime.time(9, 0)


def _row(db, of_id, at=MORNING):
    rows = WorkOrderOverviewService(db).overview(tenant_id=TENANT, date=DAY, at=at)
    return next(r for r in rows if r["of_id"] == of_id)


def _bare_order(db, env):
    orders = WorkOrderService(db)
    return _ok(orders.create_work_order(tenant_id=TENANT, actor_id=env["actor"], planned_quantity=1000, work_center_id=env["work_center"], start_date=DAY)).id


def test_an_order_with_no_shift_has_nothing_to_show(db, env):
    row = _row(db, _bare_order(db, env))
    assert row["products"] == [] and row["produced_quantity"] == 0
    assert row["completion_ratio"] == 0
    assert row["yield_ratio"] is None and row["last_shift_date"] is None
    assert row["shifts"] == {"validated": 0, "submitted": 0, "in_progress": 0, "returned": 0}
    assert row["pending_quantity"] == 0 and row["live"] is False


def test_a_handed_in_shift_is_pending_and_never_official(db, env):
    _, of_id = _two_product_shift(db, env)
    row = _row(db, of_id)
    assert row["shifts"]["submitted"] == 1 and row["shifts"]["validated"] == 0
    assert row["produced_quantity"] == 0 and row["products"] == [] and row["yield_ratio"] is None
    assert row["pending_quantity"] == pytest.approx(0.108)  # 120 x 500 g + 240 x 200 g


def test_a_validated_shift_counts_officially(db, env):
    shift_id, of_id = _two_product_shift(db, env)
    _ok(ShiftValidationService(db).validate_shift(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id))
    row = _row(db, of_id)
    assert row["shifts"]["validated"] == 1 and row["pending_quantity"] == 0
    assert row["products"] == [env["big"], env["small"]]
    assert row["produced_quantity"] == pytest.approx(0.108)
    assert row["completion_ratio"] == pytest.approx(0.108 / 1000)
    assert row["yield_ratio"] == pytest.approx(0.9)
    assert row["last_shift_date"] == DAY.isoformat()


def test_an_order_is_live_while_its_shift_is_running(db, env):
    db.execute("INSERT INTO production.shift_windows (tenant_id, shift, start_time, end_time) VALUES (%s, 'morning', '07:00', '15:00')", (TENANT,))
    _, of_id = _two_product_shift(db, env)
    assert _row(db, of_id, at=MORNING)["live"] is True
    assert _row(db, of_id, at=datetime.time(16, 0))["live"] is False


def test_regrind_orders_are_not_listed(db, env):
    of_id = _bare_order(db, env)
    db.execute("INSERT INTO production.regrind_batches (work_order_id, tenant_id) VALUES (%s, %s)", (of_id, TENANT))
    assert of_id not in {r["of_id"] for r in WorkOrderOverviewService(db).overview(tenant_id=TENANT, date=DAY, at=MORNING)}


def test_another_tenants_orders_are_not_listed(db, env):
    _bare_order(db, env)
    assert WorkOrderOverviewService(db).overview(tenant_id="somebody-else", date=DAY, at=MORNING) == []


def test_shifts_can_be_listed_for_one_order(db, env):
    shift_id, of_id = _two_product_shift(db, env)
    service = ShiftReportService(db)
    assert [s["id"] for s in service.list_shifts(tenant_id=TENANT, of_id=of_id)] == [shift_id]
    assert service.list_shifts(tenant_id=TENANT, of_id=_bare_order(db, env)) == []
