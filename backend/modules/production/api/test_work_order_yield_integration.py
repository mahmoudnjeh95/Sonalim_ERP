"""Rendement (yield) = finished product / material poured in, from validated shifts."""
from __future__ import annotations

import datetime

import pytest
from ulid import ULID

from core.domain.result import Ok
from modules.production.api.service import WorkOrderService
from modules.production.api.shift_report_service import ShiftReportService
from modules.production.api.shift_validation_service import ShiftValidationService
from modules.production.api.work_order_yield_service import WorkOrderYieldService
from modules.production.domain.shift_report import SECTION_KEYS
from modules.warehouse.api.service import StockService

TENANT = "work-order-yield-test"
D = datetime.date


@pytest.fixture
def env(db):
    actor, uom, product, semolina, location, work_center, equipment = (str(ULID()) for _ in range(7))
    db.execute("INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')", (actor, TENANT, f"{actor}@test.local"))
    db.execute("INSERT INTO core.uoms (id, tenant_id, code, name, category) VALUES (%s, %s, 'kg', 'Kilogram', 'weight')", (uom, TENANT))
    db.execute("INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, 'WY-LOC', 'Silo')", (location, TENANT))
    for product_id, sku in ((product, "WY-PASTA"), (semolina, "WY-SEMO")):
        db.execute("INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, %s, %s, %s)", (product_id, TENANT, sku, sku, uom))
    db.execute("INSERT INTO production.work_centers (id, tenant_id, code, name) VALUES (%s, %s, 'WY-WC', 'Line')", (work_center, TENANT))
    db.execute("INSERT INTO maintenance.equipment (id, tenant_id, work_center_id, code, name) VALUES (%s, %s, %s, 'WY-EQ', 'Press')", (equipment, TENANT, work_center))
    StockService(db).receive_stock(tenant_id=TENANT, product_id=semolina, location_id=location, quantity=100_000, correlation_id=str(ULID()), reference="seed", actor_id=actor)
    return {"actor": actor, "product": product, "semolina": semolina, "location": location, "work_center": work_center, "equipment": equipment}


def _ok(result):
    assert isinstance(result, Ok), getattr(result, "message", result)
    return result.value


def _of(db, env):
    created = _ok(WorkOrderService(db).create_work_order(
        tenant_id=TENANT, actor_id=env["actor"], product_id=env["product"], planned_quantity=100_000,
        work_center_id=env["work_center"], start_date=D(2030, 6, 1),
    ))
    _ok(WorkOrderService(db).start_work_order(tenant_id=TENANT, actor_id=env["actor"], work_order_id=created.id))
    return created.id


def _validated_shift(db, env, of_id, day, *, semolina_quantity=1000, finished_product_quantity=900,
                      water_percentage=0, shift="morning") -> str:
    service = ShiftReportService(db)
    shift_id = _ok(service.open_shift(tenant_id=TENANT, actor_id=env["actor"], work_center_id=env["work_center"], report_date=day, shift=shift))["id"]
    run = {
        "of_id": of_id, "equipment_id": env["equipment"], "start_time": "07:00", "end_time": "14:00",
        "production_minutes": 420, "finished_product_quantity": finished_product_quantity,
        "raw_material_location_id": env["location"],
        "semolina_lines": [{"product_id": env["semolina"], "quantity": semolina_quantity, "location_id": env["location"]}],
        "water_percentage": water_percentage,
    }
    _ok(service.save_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key="runs", payload={"runs": [run], "versements": run.pop("semolina_lines", [])}))
    for key in SECTION_KEYS:
        if key == "runs":
            _ok(service.submit_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key))
        else:
            _ok(service.declare_nothing(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key))
    _ok(ShiftValidationService(db).validate_shift(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id))
    return shift_id


def test_yield_is_produced_over_semoule_poured(db, env):
    of_id = _of(db, env)
    _validated_shift(db, env, of_id, D(2030, 6, 5), semolina_quantity=1000, finished_product_quantity=900)

    result = WorkOrderYieldService(db).get_work_order_yield(tenant_id=TENANT, work_order_id=of_id)

    assert result is not None
    assert result["semoule_quantity_total"] == 1000
    assert result["produced_quantity"] == 900
    assert result["yield_ratio"] == pytest.approx(0.9)


def test_shifts_accumulate_into_one_yield(db, env):
    of_id = _of(db, env)
    _validated_shift(db, env, of_id, D(2030, 6, 5), semolina_quantity=500, finished_product_quantity=450, shift="morning")
    _validated_shift(db, env, of_id, D(2030, 6, 5), semolina_quantity=500, finished_product_quantity=450, shift="afternoon")

    result = WorkOrderYieldService(db).get_work_order_yield(tenant_id=TENANT, work_order_id=of_id)

    assert result["semoule_quantity_total"] == 1000
    assert result["produced_quantity"] == 900


def test_an_of_with_no_validated_shift_has_no_yield(db, env):
    of_id = _of(db, env)

    assert WorkOrderYieldService(db).get_work_order_yield(tenant_id=TENANT, work_order_id=of_id) is None


def test_list_work_order_yields_returns_every_of_with_a_defined_yield(db, env):
    of_id = _of(db, env)
    _validated_shift(db, env, of_id, D(2030, 6, 5))

    rows = WorkOrderYieldService(db).list_work_order_yields(tenant_id=TENANT)

    assert any(r["work_order_id"] == of_id for r in rows)


def test_recipe_correlation_pairs_a_shifts_water_dosage_with_its_ofs_yield(db, env):
    of_id = _of(db, env)
    # The débit is no longer typed: it is the shift's versements over the hours it ran.
    # An 8 h morning with nothing stopped pours 1000 t, so 125 t/h.
    db.execute(
        "INSERT INTO production.shift_windows (tenant_id, shift, start_time, end_time) VALUES (%s, 'morning', '07:00', '15:00') "
        "ON CONFLICT (tenant_id, shift) DO NOTHING",
        (TENANT,),
    )
    shift_id = _validated_shift(db, env, of_id, D(2030, 6, 5), water_percentage=32.5)

    rows = WorkOrderYieldService(db).list_recipe_correlation(tenant_id=TENANT)

    row = next(r for r in rows if r["of_id"] == of_id)
    assert row["water_percentage"] == pytest.approx(32.5)
    assert row["semolina_flow_rate"] == pytest.approx(125.0)
    assert row["yield_ratio"] == pytest.approx(0.9)


def test_recipe_correlation_excludes_shifts_with_nothing_dosed(db, env):
    of_id = _of(db, env)
    _validated_shift(db, env, of_id, D(2030, 6, 5), water_percentage=0)

    rows = WorkOrderYieldService(db).list_recipe_correlation(tenant_id=TENANT)

    assert not any(r["of_id"] == of_id for r in rows)
