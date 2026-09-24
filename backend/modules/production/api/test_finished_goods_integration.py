"""Finished pasta actually packed in a period, by product -- the "Produit Fini" sheet."""
from __future__ import annotations

import datetime

import pytest
from ulid import ULID

from core.domain.result import Ok
from modules.production.api.finished_goods_service import FinishedGoodsService
from modules.production.api.service import WorkOrderService
from modules.production.api.shift_report_service import ShiftReportService
from modules.production.api.shift_validation_service import ShiftValidationService
from modules.production.domain.shift_report import SECTION_KEYS
from modules.warehouse.api.service import StockService

TENANT = "finished-goods-test"
D = datetime.date


@pytest.fixture
def env(db):
    actor, uom, product, semolina, location, work_center, equipment = (str(ULID()) for _ in range(7))
    db.execute("INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')", (actor, TENANT, f"{actor}@test.local"))
    db.execute("INSERT INTO core.uoms (id, tenant_id, code, name, category) VALUES (%s, %s, 'kg', 'Kilogram', 'weight')", (uom, TENANT))
    db.execute("INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, 'FG-LOC', 'Silo')", (location, TENANT))
    db.execute(
        "INSERT INTO core.products (id, tenant_id, sku, name, uom_id, default_location_id, net_weight_grams) VALUES (%s, %s, 'FG-PASTA', 'FG-PASTA', %s, %s, 500)",
        (product, TENANT, uom, location),
    )
    db.execute(
        "INSERT INTO core.products (id, tenant_id, sku, name, uom_id, default_location_id) VALUES (%s, %s, 'FG-SEMO', 'FG-SEMO', %s, %s)",
        (semolina, TENANT, uom, location),
    )
    db.execute("INSERT INTO production.work_centers (id, tenant_id, code, name) VALUES (%s, %s, 'FG-WC', 'Line')", (work_center, TENANT))
    db.execute("INSERT INTO maintenance.equipment (id, tenant_id, work_center_id, code, name) VALUES (%s, %s, %s, 'FG-EQ', 'Packer')", (equipment, TENANT, work_center))
    StockService(db).receive_stock(tenant_id=TENANT, product_id=semolina, location_id=location, quantity=100_000, correlation_id=str(ULID()), reference="seed", actor_id=actor)
    return {"actor": actor, "product": product, "semolina": semolina, "location": location, "work_center": work_center, "equipment": equipment}


def _ok(result):
    assert isinstance(result, Ok), getattr(result, "message", result)
    return result.value


def _validated_packing_shift(db, env, day, *, packets_counted=200) -> str:
    of_id = _ok(WorkOrderService(db).create_work_order(
        tenant_id=TENANT, actor_id=env["actor"], product_id=env["product"], planned_quantity=100_000,
        work_center_id=env["work_center"], start_date=day,
    )).id
    _ok(WorkOrderService(db).start_work_order(tenant_id=TENANT, actor_id=env["actor"], work_order_id=of_id))
    service = ShiftReportService(db)
    shift_id = _ok(service.open_shift(tenant_id=TENANT, actor_id=env["actor"], work_center_id=env["work_center"], report_date=day, shift="morning"))["id"]
    _ok(service.save_section(
        tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key="packing",
        payload={"rows": [{
            "of_id": of_id, "equipment_id": env["equipment"], "finished_product_quantity": 900,
            "packets_counted": packets_counted,
        }]},
    ))
    for key in SECTION_KEYS:
        if key == "packing":
            _ok(service.submit_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key))
        else:
            _ok(service.declare_nothing(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key))
    _ok(ShiftValidationService(db).validate_shift(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id))
    return shift_id


def test_a_validated_shifts_packing_is_summed_by_product(db, env):
    _validated_packing_shift(db, env, D(2030, 6, 5))

    rows = FinishedGoodsService(db).list_finished_goods(tenant_id=TENANT, date_from="2030-06-01", date_to="2030-06-30")

    assert len(rows) == 1
    assert rows[0]["product_id"] == env["product"]
    assert rows[0]["quantity"] == pytest.approx(0.1)
    assert rows[0]["packets_counted"] == 200


def test_an_unvalidated_shifts_packing_is_not_counted(db, env):
    of_id = _ok(WorkOrderService(db).create_work_order(
        tenant_id=TENANT, actor_id=env["actor"], product_id=env["product"], planned_quantity=100_000,
        work_center_id=env["work_center"], start_date=D(2030, 6, 5),
    )).id
    _ok(WorkOrderService(db).start_work_order(tenant_id=TENANT, actor_id=env["actor"], work_order_id=of_id))
    service = ShiftReportService(db)
    shift_id = _ok(service.open_shift(tenant_id=TENANT, actor_id=env["actor"], work_center_id=env["work_center"], report_date=D(2030, 6, 5), shift="morning"))["id"]
    _ok(service.save_section(
        tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key="packing",
        payload={"rows": [{"of_id": of_id, "equipment_id": env["equipment"], "finished_product_quantity": 900, "packets_counted": 200}]},
    ))

    rows = FinishedGoodsService(db).list_finished_goods(tenant_id=TENANT, date_from="2030-06-01", date_to="2030-06-30")

    assert rows == []


def test_out_of_range_dates_are_excluded(db, env):
    _validated_packing_shift(db, env, D(2030, 5, 1))

    rows = FinishedGoodsService(db).list_finished_goods(tenant_id=TENANT, date_from="2030-06-01", date_to="2030-06-30")

    assert rows == []
