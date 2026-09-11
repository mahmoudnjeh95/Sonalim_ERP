"""Integration tests for machine-performance aggregation, against a real database.

A work center like Line_1_PL can carry more than one machine running at once
(maintenance.equipment), so productivity has to be checkable per machine, not
just per line -- this pins that a report's equipment_id is what makes that
possible, and that only validated reports count, same as every other
aggregate in this module.
"""
from __future__ import annotations

import datetime

import pytest
from ulid import ULID

from core.domain.result import Ok
from modules.production.api.machine_performance_service import MachinePerformanceService
from modules.production.api.production_report_service import ProductionReportService
from modules.production.api.service import WorkOrderService
from modules.production.domain.production_report import DailyReportDetail, SemolinaLine
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


def _validated_report(db, env, *, equipment_id, report_date, semolina_quantity, production_minutes, downtime_minutes):
    orders = WorkOrderService(db)
    created = orders.create_work_order(
        tenant_id=TENANT, actor_id=env["actor"], product_id=env["product"],
        planned_quantity=1000, work_center_id=env["work_center"], start_date=report_date,
    )
    assert isinstance(created, Ok), getattr(created, "message", "")
    order = created.value
    assert isinstance(orders.start_work_order(tenant_id=TENANT, actor_id=env["actor"], work_order_id=order.id), Ok)

    reports = ProductionReportService(db)
    detail = DailyReportDetail(
        semolina_lines=(SemolinaLine(product_id=env["product"], quantity=semolina_quantity, location_id=env["location"]),),
        raw_material_location_id=env["location"],
        production_minutes=production_minutes,
    )
    created_report = reports.create_daily_report(
        tenant_id=TENANT, actor_id=env["actor"], of_id=order.id, report_date=report_date,
        equipment_id=equipment_id, detail=detail,
    )
    assert isinstance(created_report, Ok), getattr(created_report, "message", "")
    report_id = created_report.value["report"].id
    assert isinstance(reports.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report_id), Ok)
    validated = reports.validate_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report_id)
    assert isinstance(validated, Ok), getattr(validated, "message", "")
    return order.id


def test_two_machines_on_the_same_line_are_kept_apart(db, env):
    """The whole point: Line_1_PL running two presses must not blend into one figure."""
    _validated_report(
        db, env, equipment_id=env["machine_a"], report_date=datetime.date(2026, 9, 1),
        semolina_quantity=500, production_minutes=400, downtime_minutes=0,
    )
    _validated_report(
        db, env, equipment_id=env["machine_b"], report_date=datetime.date(2026, 9, 1),
        semolina_quantity=300, production_minutes=350, downtime_minutes=0,
    )

    rows = MachinePerformanceService(db).list_machine_performance(tenant_id=TENANT, grain="week")
    by_machine = {r["equipment_id"]: r for r in rows}
    assert by_machine[env["machine_a"]]["material_input_quantity"] == 500
    assert by_machine[env["machine_a"]]["production_minutes"] == 400
    assert by_machine[env["machine_b"]]["material_input_quantity"] == 300
    assert by_machine[env["machine_b"]]["production_minutes"] == 350


def test_draft_reports_are_excluded(db, env):
    orders = WorkOrderService(db)
    created = orders.create_work_order(
        tenant_id=TENANT, actor_id=env["actor"], product_id=env["product"],
        planned_quantity=1000, work_center_id=env["work_center"], start_date=datetime.date(2026, 9, 15),
    )
    order = created.value
    assert isinstance(orders.start_work_order(tenant_id=TENANT, actor_id=env["actor"], work_order_id=order.id), Ok)
    ProductionReportService(db).create_daily_report(
        tenant_id=TENANT, actor_id=env["actor"], of_id=order.id, report_date=datetime.date(2026, 9, 15),
        equipment_id=env["machine_a"],
        detail=DailyReportDetail(
            semolina_lines=(SemolinaLine(product_id=env["product"], quantity=999, location_id=env["location"]),),
            raw_material_location_id=env["location"],
        ),
    )

    rows = MachinePerformanceService(db).list_machine_performance(tenant_id=TENANT, grain="week")
    assert not any(r["equipment_id"] == env["machine_a"] for r in rows)


def test_reports_with_no_machine_named_are_excluded(db, env):
    """A report submitted before this feature existed (or, now, one that was
    never allowed to submit without a machine) must not show up as a phantom
    machine with no id."""
    orders = WorkOrderService(db)
    created = orders.create_work_order(
        tenant_id=TENANT, actor_id=env["actor"], product_id=env["product"],
        planned_quantity=1000, work_center_id=env["work_center"], start_date=datetime.date(2026, 9, 1),
    )
    order = created.value
    assert isinstance(orders.start_work_order(tenant_id=TENANT, actor_id=env["actor"], work_order_id=order.id), Ok)
    # Backfill the way a pre-migration row would look: validated, no equipment_id.
    reports = ProductionReportService(db)
    created_report = reports.create_daily_report(
        tenant_id=TENANT, actor_id=env["actor"], of_id=order.id, report_date=datetime.date(2026, 9, 1),
        equipment_id=env["machine_a"],
        detail=DailyReportDetail(
            semolina_lines=(SemolinaLine(product_id=env["product"], quantity=500, location_id=env["location"]),),
            raw_material_location_id=env["location"],
        ),
    )
    report_id = created_report.value["report"].id
    assert isinstance(reports.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report_id), Ok)
    assert isinstance(reports.validate_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report_id), Ok)
    db.execute("UPDATE production.production_reports SET equipment_id = NULL WHERE id = %s", (report_id,))

    rows = MachinePerformanceService(db).list_machine_performance(tenant_id=TENANT, grain="week")
    assert rows == []


def test_invalid_grain_is_rejected(db):
    with pytest.raises(ValueError):
        MachinePerformanceService(db).list_machine_performance(tenant_id=TENANT, grain="fortnight")
