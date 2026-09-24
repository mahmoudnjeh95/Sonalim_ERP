"""Which dates had at least one validated shift, for the recap export's per-day sheets."""
from __future__ import annotations

import datetime

import pytest
from ulid import ULID

from core.domain.result import Ok
from modules.production.api.report_period_service import list_validated_report_dates
from modules.production.api.service import WorkOrderService
from modules.production.api.shift_report_service import ShiftReportService
from modules.production.api.shift_validation_service import ShiftValidationService
from modules.production.domain.shift_report import SECTION_KEYS
from modules.warehouse.api.service import StockService

TENANT = "report-period-test"


@pytest.fixture
def env(db):
    actor = str(ULID())
    uom, product, semolina, location, work_center, equipment = (str(ULID()) for _ in range(6))
    db.execute("INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')", (actor, TENANT, f"{actor}@test.local"))
    db.execute("INSERT INTO core.uoms (id, tenant_id, code, name, category) VALUES (%s, %s, 'kg', 'Kilogram', 'weight')", (uom, TENANT))
    for product_id, sku in ((product, "RP-PASTA"), (semolina, "RP-SEMO")):
        db.execute("INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, %s, %s, %s)", (product_id, TENANT, sku, sku, uom))
    db.execute("INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, 'RP-LOC', 'Silo')", (location, TENANT))
    db.execute("INSERT INTO production.work_centers (id, tenant_id, code, name) VALUES (%s, %s, 'RP-WC', 'Line')", (work_center, TENANT))
    db.execute("INSERT INTO maintenance.equipment (id, tenant_id, work_center_id, code, name) VALUES (%s, %s, %s, 'RP-EQ', 'Press')", (equipment, TENANT, work_center))
    StockService(db).receive_stock(tenant_id=TENANT, product_id=semolina, location_id=location, quantity=100_000, correlation_id=str(ULID()), reference="seed", actor_id=actor)
    return {"actor": actor, "product": product, "semolina": semolina, "location": location, "work_center": work_center, "equipment": equipment}


def _ok(result):
    assert isinstance(result, Ok), getattr(result, "message", result)
    return result.value


def _validated_shift(db, env, report_date) -> str:
    service = ShiftReportService(db)
    shift_id = _ok(service.open_shift(tenant_id=TENANT, actor_id=env["actor"], work_center_id=env["work_center"], report_date=report_date, shift="morning"))["id"]
    of_id = _ok(WorkOrderService(db).create_work_order(tenant_id=TENANT, actor_id=env["actor"], product_id=env["product"], planned_quantity=100_000, work_center_id=env["work_center"], start_date=report_date)).id
    _ok(WorkOrderService(db).start_work_order(tenant_id=TENANT, actor_id=env["actor"], work_order_id=of_id))
    run = {
        "of_id": of_id, "equipment_id": env["equipment"], "start_time": "07:00", "end_time": "14:00",
        "production_minutes": 420, "finished_product_quantity": 900, "raw_material_location_id": env["location"],
        "semolina_lines": [{"product_id": env["semolina"], "quantity": 1000, "location_id": env["location"]}],
    }
    _ok(service.save_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key="runs", payload={"runs": [run]}))
    for key in SECTION_KEYS:
        if key == "runs":
            _ok(service.submit_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key))
        else:
            _ok(service.declare_nothing(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key))
    _ok(ShiftValidationService(db).validate_shift(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id))
    return shift_id


def test_only_dates_with_a_validated_shift_are_listed(db, env):
    _validated_shift(db, env, datetime.date(2030, 6, 5))
    _validated_shift(db, env, datetime.date(2030, 6, 7))

    dates = list_validated_report_dates(db, tenant_id=TENANT, date_from="2030-06-01", date_to="2030-06-30")

    assert dates == ["2030-06-05", "2030-06-07"]


def test_an_unvalidated_shift_does_not_count(db, env):
    service = ShiftReportService(db)
    service.open_shift(tenant_id=TENANT, actor_id=env["actor"], work_center_id=env["work_center"], report_date=datetime.date(2030, 6, 10), shift="morning")

    dates = list_validated_report_dates(db, tenant_id=TENANT, date_from="2030-06-01", date_to="2030-06-30")

    assert dates == []
