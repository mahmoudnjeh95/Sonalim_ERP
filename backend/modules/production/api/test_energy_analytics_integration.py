"""Energy analytics reads production.shift_energy for validated shifts only, with the shift's produced tonnage."""
from __future__ import annotations

import datetime

import pytest
from ulid import ULID

from core.domain.result import Ok
from modules.production.api.energy_analytics_service import EnergyAnalyticsService
from modules.production.api.service import WorkOrderService
from modules.production.api.shift_report_service import ShiftReportService
from modules.production.api.shift_validation_service import ShiftValidationService
from modules.production.domain.shift_report import SECTION_KEYS
from modules.warehouse.api.service import StockService

TENANT = "energy-analytics-test"
DAY = datetime.date(2030, 7, 1)


@pytest.fixture
def env(db):
    actor = str(ULID())
    uom, product, semolina, location, fg_location, packaging_location, work_center, equipment = (str(ULID()) for _ in range(8))
    film, carton, scotch, ruban = (str(ULID()) for _ in range(4))
    db.execute("INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')", (actor, TENANT, f"{actor}@test.local"))
    db.execute("INSERT INTO core.uoms (id, tenant_id, code, name, category) VALUES (%s, %s, 'kg', 'Kilogram', 'weight')", (uom, TENANT))
    for product_id, sku in ((product, "EA-PASTA"), (semolina, "EA-SEMO"), (film, "EA-FILM"), (carton, "EA-CARTON"), (scotch, "EA-SCOTCH"), (ruban, "EA-RUBAN")):
        db.execute("INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, %s, %s, %s)", (product_id, TENANT, sku, sku, uom))
    db.execute("INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, 'EA-LOC', 'Silo')", (location, TENANT))
    db.execute("INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, 'EA-PACK', 'Packaging')", (packaging_location, TENANT))
    db.execute("INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, 'EA-FG', 'Finished goods')", (fg_location, TENANT))
    db.execute("INSERT INTO production.work_centers (id, tenant_id, code, name) VALUES (%s, %s, 'EA-WC', 'Line')", (work_center, TENANT))
    db.execute("INSERT INTO maintenance.equipment (id, tenant_id, work_center_id, code, name) VALUES (%s, %s, %s, 'EA-EQ', 'Press')", (equipment, TENANT, work_center))
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


def _shift_with_energy(db, env, *, fuel=0, gasoil=0, generator_hours=0, electricity=0, validate=True) -> str:
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
    run_ids = [r["id"] for r in _shift(db, shift_id)["sections"][0]["payload"]["runs"]]
    packing = {"of_id": of_id, "run_id": run_ids[0], "equipment_id": env["equipment"], "finished_product_quantity": 800,
               "packets_counted": 1600, "film_quantity": 40, "carton_quantity": 100, "scotch_quantity": 2, "ruban_quantity": 1,
               "film_product_id": env["film"], "carton_product_id": env["carton"], "scotch_product_id": env["scotch"],
               "ruban_product_id": env["ruban"], "packaging_location_id": env["packaging_location"],
               "finished_goods_location_id": env["fg_location"], "lot_number": "B7021SNL"}
    energy = {"fuel_quantity": fuel, "gasoil_quantity": gasoil, "generator_hours": generator_hours, "electricity_quantity": electricity}

    filled = {"runs": None, "packing": {"rows": [packing]}, "energy": {"energy": energy}}
    for key in SECTION_KEYS:
        if key in filled:
            if filled[key] is not None:
                _ok(service.save_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key, payload=filled[key]))
            _ok(service.submit_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key))
        else:
            _ok(service.declare_nothing(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key))
    if validate:
        _ok(ShiftValidationService(db).validate_shift(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id))
    return shift_id


def _energy(db, **filters):
    return EnergyAnalyticsService(db).list_energy(tenant_id=TENANT, **{"date_from": "2030-07-01", "date_to": "2030-07-01", **filters})


def test_lists_energy_of_validated_shifts_including_zero_values(db, env):
    _shift_with_energy(db, env, fuel=0, gasoil=120.5, generator_hours=3, electricity=450)

    rows = _energy(db)

    assert len(rows) == 1
    row = rows[0]
    assert row["fuel_quantity"] == 0.0  # recorded zero, not a missing value
    assert row["gasoil_quantity"] == 120.5
    assert row["generator_hours"] == 3.0
    assert row["electricity_quantity"] == 450.0
    assert row["produced_quantity"] == 900.0  # the run's finished_product_quantity
    assert row["work_center_id"] == env["work_center"]


def test_energy_of_a_shift_not_yet_validated_is_excluded(db, env):
    _shift_with_energy(db, env, fuel=10, validate=False)
    assert _energy(db) == []


def test_energy_filtered_by_work_center(db, env):
    _shift_with_energy(db, env, fuel=10)
    assert _energy(db, work_center_id="not-this-line") == []
    assert len(_energy(db, work_center_id=env["work_center"])) == 1


def test_energy_outside_date_range_excluded(db, env):
    _shift_with_energy(db, env, fuel=10)
    assert _energy(db, date_from="2030-01-01", date_to="2030-01-31") == []
