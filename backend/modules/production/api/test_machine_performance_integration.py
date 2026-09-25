"""Integration tests for machine-performance aggregation, against a real database.

A work center like Line_1_PL can carry more than one machine running at once
(maintenance.equipment), so productivity has to be checkable per machine, not
just per line -- this pins that a run's equipment_id is what makes that
possible, and that only validated shifts count, same as every other
aggregate in this module.
"""
from __future__ import annotations

import datetime

import pytest
from ulid import ULID

from core.domain.result import Ok
from modules.production.api.machine_performance_service import MachinePerformanceService
from modules.production.api.service import WorkOrderService
from modules.production.api.shift_report_service import ShiftReportService
from modules.production.api.shift_validation_service import ShiftValidationService
from modules.production.domain.shift_report import SECTION_KEYS
from modules.warehouse.api.service import StockService

TENANT = "integration-test-machine-performance"


@pytest.fixture
def env(db):
    actor = str(ULID())
    uom, product, location, work_center = (str(ULID()) for _ in range(4))
    machine_a, machine_b = str(ULID()), str(ULID())
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (actor, TENANT, f"{actor}@test.local"),
    )
    db.execute(
        "INSERT INTO core.uoms (id, tenant_id, code, name, category) VALUES (%s, %s, 'kg', 'Kilogram', 'weight')",
        (uom, TENANT),
    )
    db.execute(
        "INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, 'MP-PASTA', 'Test pasta', %s)",
        (product, TENANT, uom),
    )
    db.execute(
        "INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, 'MP-LOC', 'Test location')",
        (location, TENANT),
    )
    db.execute(
        "INSERT INTO production.work_centers (id, tenant_id, code, name) VALUES (%s, %s, 'MP-WC', 'Line_1_PL')",
        (work_center, TENANT),
    )
    # The case this whole feature exists for: two machines running on the same line.
    db.execute(
        "INSERT INTO maintenance.equipment (id, tenant_id, work_center_id, code, name) VALUES (%s, %s, %s, 'MP-A', 'Press A')",
        (machine_a, TENANT, work_center),
    )
    db.execute(
        "INSERT INTO maintenance.equipment (id, tenant_id, work_center_id, code, name) VALUES (%s, %s, %s, 'MP-B', 'Press B')",
        (machine_b, TENANT, work_center),
    )
    StockService(db).receive_stock(
        tenant_id=TENANT, product_id=product, location_id=location, quantity=100_000,
        correlation_id=str(ULID()), reference="test-seed", actor_id=actor,
    )
    return {
        "actor": actor,
        "product": product,
        "location": location,
        "work_center": work_center,
        "machine_a": machine_a,
        "machine_b": machine_b,
    }


def _ok(result):
    assert isinstance(result, Ok), getattr(result, "message", result)
    return result.value


def _of(db, env, report_date):
    orders = WorkOrderService(db)
    created = _ok(orders.create_work_order(
        tenant_id=TENANT, actor_id=env["actor"], product_id=env["product"],
        planned_quantity=1000, work_center_id=env["work_center"], start_date=report_date,
    ))
    _ok(orders.start_work_order(tenant_id=TENANT, actor_id=env["actor"], work_order_id=created.id))
    return created.id


def _validated_shift(db, env, *, equipment_id, report_date, semolina_quantity, production_minutes, shift="morning") -> str:
    of_id = _of(db, env, report_date)
    service = ShiftReportService(db)
    shift_id = _ok(service.open_shift(
        tenant_id=TENANT, actor_id=env["actor"], work_center_id=env["work_center"], report_date=report_date, shift=shift,
    ))["id"]
    run = {
        "of_id": of_id, "equipment_id": equipment_id, "start_time": "07:00", "end_time": "14:00",
        "production_minutes": production_minutes, "finished_product_quantity": 900,
        "raw_material_location_id": env["location"],
        "semolina_lines": [{"product_id": env["product"], "quantity": semolina_quantity, "location_id": env["location"]}],
    }
    _ok(service.save_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key="runs", payload={"runs": [run], "versements": run.pop("semolina_lines", [])}))
    for key in SECTION_KEYS:
        if key == "runs":
            _ok(service.submit_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key))
        else:
            _ok(service.declare_nothing(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key))
    _ok(ShiftValidationService(db).validate_shift(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id))
    return shift_id


def test_two_machines_on_the_same_line_are_kept_apart(db, env):
    """The whole point: Line_1_PL running two presses must not blend into one figure."""
    _validated_shift(
        db, env, equipment_id=env["machine_a"], report_date=datetime.date(2026, 9, 1),
        semolina_quantity=500, production_minutes=400,
    )
    _validated_shift(
        db, env, equipment_id=env["machine_b"], report_date=datetime.date(2026, 9, 1),
        semolina_quantity=300, production_minutes=350, shift="afternoon",
    )

    rows = MachinePerformanceService(db).list_machine_performance(tenant_id=TENANT, grain="week")
    by_machine = {r["equipment_id"]: r for r in rows}
    assert by_machine[env["machine_a"]]["material_input_quantity"] == 500
    assert by_machine[env["machine_a"]]["production_minutes"] == 400
    assert by_machine[env["machine_b"]]["material_input_quantity"] == 300
    assert by_machine[env["machine_b"]]["production_minutes"] == 350


def test_draft_reports_are_excluded(db, env):
    of_id = _of(db, env, datetime.date(2026, 9, 15))
    service = ShiftReportService(db)
    shift_id = _ok(service.open_shift(
        tenant_id=TENANT, actor_id=env["actor"], work_center_id=env["work_center"], report_date=datetime.date(2026, 9, 15), shift="morning",
    ))["id"]
    run = {
        "of_id": of_id, "equipment_id": env["machine_a"], "start_time": "07:00", "end_time": "14:00",
        "production_minutes": 100, "finished_product_quantity": 900, "raw_material_location_id": env["location"],
        "semolina_lines": [{"product_id": env["product"], "quantity": 999, "location_id": env["location"]}],
    }
    _ok(service.save_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key="runs", payload={"runs": [run], "versements": run.pop("semolina_lines", [])}))

    rows = MachinePerformanceService(db).list_machine_performance(tenant_id=TENANT, grain="week")
    assert not any(r["equipment_id"] == env["machine_a"] for r in rows)


def test_reports_with_no_machine_named_are_excluded(db, env):
    """A run with no equipment_id must not show up as a phantom machine with no id."""
    _validated_shift(
        db, env, equipment_id=env["machine_a"], report_date=datetime.date(2026, 9, 1),
        semolina_quantity=500, production_minutes=100,
    )
    db.execute("UPDATE production.shift_runs SET equipment_id = NULL WHERE tenant_id = %s", (TENANT,))

    rows = MachinePerformanceService(db).list_machine_performance(tenant_id=TENANT, grain="week")
    assert rows == []


def test_invalid_grain_is_rejected(db):
    with pytest.raises(ValueError):
        MachinePerformanceService(db).list_machine_performance(tenant_id=TENANT, grain="fortnight")
