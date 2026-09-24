"""Humidity analytics reads production.shift_runs.humidity_percentage for validated shifts only."""
from __future__ import annotations

import datetime

import pytest
from ulid import ULID

from core.domain.result import Ok
from modules.production.api.humidity_analytics_service import list_humidity
from modules.production.api.service import WorkOrderService
from modules.production.api.shift_report_service import ShiftReportService
from modules.production.api.shift_validation_service import ShiftValidationService
from modules.production.domain.shift_report import SECTION_KEYS
from modules.warehouse.api.service import StockService

TENANT = "humidity-analytics-test"
DAY = datetime.date(2030, 7, 1)


@pytest.fixture
def env(db):
    actor = str(ULID())
    uom, product, semolina, location, fg_location, packaging_location, work_center, equipment = (str(ULID()) for _ in range(8))
    film, carton, scotch, ruban = (str(ULID()) for _ in range(4))
    db.execute("INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')", (actor, TENANT, f"{actor}@test.local"))
    db.execute("INSERT INTO core.uoms (id, tenant_id, code, name, category) VALUES (%s, %s, 'kg', 'Kilogram', 'weight')", (uom, TENANT))
    for product_id, sku in ((product, "HA-PASTA"), (semolina, "HA-SEMO"), (film, "HA-FILM"), (carton, "HA-CARTON"), (scotch, "HA-SCOTCH"), (ruban, "HA-RUBAN")):
        db.execute("INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, %s, %s, %s)", (product_id, TENANT, sku, sku, uom))
    db.execute("INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, 'HA-LOC', 'Silo')", (location, TENANT))
    db.execute("INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, 'HA-PACK', 'Packaging')", (packaging_location, TENANT))
    db.execute("INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, 'HA-FG', 'Finished goods')", (fg_location, TENANT))
    db.execute("INSERT INTO production.work_centers (id, tenant_id, code, name) VALUES (%s, %s, 'HA-WC', 'Line')", (work_center, TENANT))
    db.execute("INSERT INTO maintenance.equipment (id, tenant_id, work_center_id, code, name) VALUES (%s, %s, %s, 'HA-EQ', 'Press')", (equipment, TENANT, work_center))
    stock = StockService(db)
    stock.receive_stock(tenant_id=TENANT, product_id=semolina, location_id=location, quantity=100_000, correlation_id=str(ULID()), reference="seed", actor_id=actor)
    for product_id in (film, carton, scotch, ruban):
        stock.receive_stock(tenant_id=TENANT, product_id=product_id, location_id=packaging_location, quantity=10_000, correlation_id=str(ULID()), reference="seed", actor_id=actor)
    return {
        "actor": actor, "product": product, "semolina": semolina, "location": location, "fg_location": fg_location,
        "packaging_location": packaging_location, "work_center": work_center, "equipment": equipment,
        "film": film, "carton": carton, "scotch": scotch, "ruban": ruban,
    }


def _of(db, env) -> str:
    service = WorkOrderService(db)
    created = service.create_work_order(tenant_id=TENANT, actor_id=env["actor"], product_id=env["product"], planned_quantity=100_000, work_center_id=env["work_center"], start_date=DAY)
    assert isinstance(created, Ok)
    assert isinstance(service.start_work_order(tenant_id=TENANT, actor_id=env["actor"], work_order_id=created.value.id), Ok)
    return created.value.id


def _ok(result):
    assert isinstance(result, Ok), getattr(result, "message", result)
    return result.value


def _shift(db, shift_id) -> dict:
    return _ok(ShiftReportService(db).get_shift(tenant_id=TENANT, shift_report_id=shift_id))


def _validated_shift_with_humidity(db, env, *, humidity) -> str:
    service = ShiftReportService(db)
    shift_id = _ok(service.open_shift(tenant_id=TENANT, actor_id=env["actor"], work_center_id=env["work_center"], report_date=DAY, shift="morning"))["id"]
    of_id = _of(db, env)
    run = {
        "of_id": of_id, "equipment_id": env["equipment"], "start_time": "07:00", "end_time": "14:00",
        "production_minutes": 420, "finished_product_quantity": 900, "humidity_percentage": humidity,
        "raw_material_location_id": env["location"],
        "semolina_lines": [{"product_id": env["semolina"], "quantity": 1000, "location_id": env["location"]}],
    }
    _ok(service.save_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key="runs", payload={"runs": [run]}))
    run_ids = [r["id"] for r in _shift(db, shift_id)["sections"][0]["payload"]["runs"]]
    packing = {"of_id": of_id, "run_id": run_ids[0], "equipment_id": env["equipment"], "finished_product_quantity": 800,
               "packets_counted": 1600, "film_quantity": 40, "carton_quantity": 100, "scotch_quantity": 2, "ruban_quantity": 1,
               "film_product_id": env["film"], "carton_product_id": env["carton"], "scotch_product_id": env["scotch"],
               "ruban_product_id": env["ruban"], "packaging_location_id": env["packaging_location"],
               "finished_goods_location_id": env["fg_location"], "lot_number": "B7031SNL"}

    filled = {"runs": None, "packing": {"rows": [packing]}}
    for key in SECTION_KEYS:
        if key in filled:
            if filled[key] is not None:
                _ok(service.save_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key, payload=filled[key]))
            _ok(service.submit_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key))
        else:
            _ok(service.declare_nothing(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key))
    _ok(ShiftValidationService(db).validate_shift(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id))
    return shift_id


def test_humidity_endpoint_returns_run_level_readings(db, env):
    _validated_shift_with_humidity(db, env, humidity=14.2)

    rows = list_humidity(db, tenant_id=TENANT, date_from="2030-07-01", date_to="2030-07-01")

    assert len(rows) == 1
    assert rows[0]["humidity_percentage"] == 14.2
    assert rows[0]["work_center_id"] == env["work_center"]


def test_runs_with_no_humidity_are_skipped_not_zeroed(db, env):
    """The humidity_percentage column defaults to NULL when never typed -- the query
    must exclude those runs, not report a null reading as 0%."""
    service = ShiftReportService(db)
    shift_id = _ok(service.open_shift(tenant_id=TENANT, actor_id=env["actor"], work_center_id=env["work_center"], report_date=DAY, shift="morning"))["id"]
    of_id = _of(db, env)
    run = {
        "of_id": of_id, "equipment_id": env["equipment"], "start_time": "07:00", "end_time": "14:00",
        "production_minutes": 420, "finished_product_quantity": 900,
        "raw_material_location_id": env["location"],
        "semolina_lines": [{"product_id": env["semolina"], "quantity": 1000, "location_id": env["location"]}],
    }
    _ok(service.save_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key="runs", payload={"runs": [run]}))

    for key in SECTION_KEYS:
        if key != "runs":
            _ok(service.declare_nothing(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key))
    _ok(service.submit_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key="runs"))
    _ok(ShiftValidationService(db).validate_shift(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id))

    rows = list_humidity(db, tenant_id=TENANT, date_from="2030-07-01", date_to="2030-07-01")
    assert rows == []


def test_humidity_of_a_shift_not_yet_validated_is_excluded(db, env):
    service = ShiftReportService(db)
    shift_id = _ok(service.open_shift(tenant_id=TENANT, actor_id=env["actor"], work_center_id=env["work_center"], report_date=DAY, shift="morning"))["id"]
    of_id = _of(db, env)
    run = {
        "of_id": of_id, "equipment_id": env["equipment"], "start_time": "07:00", "end_time": "14:00",
        "production_minutes": 420, "finished_product_quantity": 900, "humidity_percentage": 13.0,
        "raw_material_location_id": env["location"],
        "semolina_lines": [{"product_id": env["semolina"], "quantity": 1000, "location_id": env["location"]}],
    }
    _ok(service.save_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key="runs", payload={"runs": [run]}))
    assert list_humidity(db, tenant_id=TENANT, date_from="2030-07-01", date_to="2030-07-01") == []


def test_humidity_outside_date_range_excluded(db, env):
    _validated_shift_with_humidity(db, env, humidity=13.5)
    assert list_humidity(db, tenant_id=TENANT, date_from="2030-01-01", date_to="2030-01-31") == []
