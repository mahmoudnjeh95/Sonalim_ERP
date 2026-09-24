"""Semoule consumption for a period, costed from procurement's landed-cost history."""
from __future__ import annotations

import datetime

import pytest
from ulid import ULID

from core.domain.result import Ok
from modules.production.api.mp_consumption_service import MaterialConsumptionService
from modules.production.api.service import WorkOrderService
from modules.production.api.shift_report_service import ShiftReportService
from modules.production.api.shift_validation_service import ShiftValidationService
from modules.production.domain.shift_report import SECTION_KEYS
from modules.warehouse.api.service import StockService

TENANT = "mp-consumption-test"
D = datetime.date


@pytest.fixture
def env(db):
    actor, uom, product, semolina, location, work_center, equipment = (str(ULID()) for _ in range(7))
    db.execute("INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')", (actor, TENANT, f"{actor}@test.local"))
    db.execute("INSERT INTO core.uoms (id, tenant_id, code, name, category) VALUES (%s, %s, 'kg', 'Kilogram', 'weight')", (uom, TENANT))
    db.execute("INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, 'MP-LOC', 'Silo')", (location, TENANT))
    for product_id, sku in ((product, "MP-PASTA"), (semolina, "MP-SEMO")):
        db.execute("INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, %s, %s, %s)", (product_id, TENANT, sku, sku, uom))
    db.execute("INSERT INTO production.work_centers (id, tenant_id, code, name) VALUES (%s, %s, 'MP-WC', 'Line')", (work_center, TENANT))
    db.execute("INSERT INTO maintenance.equipment (id, tenant_id, work_center_id, code, name) VALUES (%s, %s, %s, 'MP-EQ', 'Press')", (equipment, TENANT, work_center))
    StockService(db).receive_stock(tenant_id=TENANT, product_id=semolina, location_id=location, quantity=100_000, correlation_id=str(ULID()), reference="seed", actor_id=actor)
    return {"actor": actor, "product": product, "semolina": semolina, "location": location, "work_center": work_center, "equipment": equipment}


def _ok(result):
    assert isinstance(result, Ok), getattr(result, "message", result)
    return result.value


def _validated_run_shift(db, env, day, *, quantity=1000) -> str:
    of_id = _ok(WorkOrderService(db).create_work_order(
        tenant_id=TENANT, actor_id=env["actor"], product_id=env["product"], planned_quantity=100_000,
        work_center_id=env["work_center"], start_date=day,
    )).id
    _ok(WorkOrderService(db).start_work_order(tenant_id=TENANT, actor_id=env["actor"], work_order_id=of_id))
    service = ShiftReportService(db)
    shift_id = _ok(service.open_shift(tenant_id=TENANT, actor_id=env["actor"], work_center_id=env["work_center"], report_date=day, shift="morning"))["id"]
    run = {
        "of_id": of_id, "equipment_id": env["equipment"], "start_time": "07:00", "end_time": "14:00",
        "production_minutes": 420, "finished_product_quantity": 900, "raw_material_location_id": env["location"],
        "semolina_lines": [{"product_id": env["semolina"], "quantity": quantity, "location_id": env["location"]}],
    }
    _ok(service.save_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key="runs", payload={"runs": [run]}))
    for key in SECTION_KEYS:
        if key == "runs":
            _ok(service.submit_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key))
        else:
            _ok(service.declare_nothing(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key))
    _ok(ShiftValidationService(db).validate_shift(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id))
    return shift_id


def test_a_validated_shifts_semoule_is_summed_by_product(db, env):
    _validated_run_shift(db, env, D(2030, 6, 5), quantity=1000)

    rows = MaterialConsumptionService(db).list_consumption(tenant_id=TENANT, date_from="2030-06-01", date_to="2030-06-30", receipt_lines=[])

    assert len(rows) == 1
    assert rows[0]["product_id"] == env["semolina"]
    assert rows[0]["quantity"] == 1000
    assert rows[0]["priced"] is False


def test_an_unvalidated_shift_is_not_counted(db, env):
    of_id = _ok(WorkOrderService(db).create_work_order(
        tenant_id=TENANT, actor_id=env["actor"], product_id=env["product"], planned_quantity=100_000,
        work_center_id=env["work_center"], start_date=D(2030, 6, 5),
    )).id
    _ok(WorkOrderService(db).start_work_order(tenant_id=TENANT, actor_id=env["actor"], work_order_id=of_id))
    service = ShiftReportService(db)
    shift_id = _ok(service.open_shift(tenant_id=TENANT, actor_id=env["actor"], work_center_id=env["work_center"], report_date=D(2030, 6, 5), shift="morning"))["id"]
    run = {
        "of_id": of_id, "equipment_id": env["equipment"], "start_time": "07:00", "end_time": "14:00",
        "production_minutes": 420, "finished_product_quantity": 900, "raw_material_location_id": env["location"],
        "semolina_lines": [{"product_id": env["semolina"], "quantity": 500, "location_id": env["location"]}],
    }
    _ok(service.save_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key="runs", payload={"runs": [run]}))

    rows = MaterialConsumptionService(db).list_consumption(tenant_id=TENANT, date_from="2030-06-01", date_to="2030-06-30", receipt_lines=[])

    assert rows == []
