"""A packing row names its own finished product; everything else follows from it."""
from __future__ import annotations

import datetime

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from modules.production.api.product_classification_service import ProductClassificationService
from modules.production.api.service import WorkOrderService
from modules.production.api.shift_report_service import ShiftReportService

TENANT = "packing-product-test"
DAY = datetime.date(2030, 9, 9)


def _ok(result):
    assert isinstance(result, Ok), getattr(result, "message", result)
    return result.value


def test_the_product_columns_exist(db):
    columns = {
        (table, column)
        for table, column in db.execute(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema = 'production' AND column_name = 'product_id' "
            "AND table_name IN ('shift_packing_rows', 'conditionnement_reports')"
        ).fetchall()
    }
    assert columns == {("shift_packing_rows", "product_id"), ("conditionnement_reports", "product_id")}


@pytest.fixture
def env(db):
    actor, uom, small, big, film, carton, fg_small, fg_big, pack, work_center = (str(ULID()) for _ in range(10))
    db.execute("INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')", (actor, TENANT, f"{actor}@test.local"))
    db.execute("INSERT INTO core.uoms (id, tenant_id, code, name, category) VALUES (%s, %s, 'kg', 'Kilogram', 'weight')", (uom, TENANT))
    for product_id, sku in ((small, "PP-200"), (big, "PP-500"), (film, "PP-FILM"), (carton, "PP-CARTON")):
        db.execute("INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, %s, %s, %s)", (product_id, TENANT, sku, sku, uom))
    for location_id, code in ((fg_small, "PP-FG-200"), (fg_big, "PP-FG-500"), (pack, "PP-PACK")):
        db.execute("INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, %s, %s)", (location_id, TENANT, code, code))
    db.execute("UPDATE core.products SET net_weight_grams = 200, packets_per_carton = 24, default_location_id = %s WHERE id = %s", (fg_small, small))
    db.execute("UPDATE core.products SET net_weight_grams = 500, packets_per_carton = 12, default_location_id = %s WHERE id = %s", (fg_big, big))
    db.execute("UPDATE core.products SET default_location_id = %s WHERE id = ANY(%s)", (pack, [film, carton]))
    db.execute("INSERT INTO production.work_centers (id, tenant_id, code, name) VALUES (%s, %s, 'PP-WC', 'Line')", (work_center, TENANT))
    for product_id in (small, big):
        ProductClassificationService(db).set_classification(
            tenant_id=TENANT, actor_id=actor, product_id=product_id, category="finished_good", packaging_format="packet"
        )
    return {"actor": actor, "small": small, "big": big, "film": film, "carton": carton, "fg_small": fg_small, "fg_big": fg_big, "pack": pack, "work_center": work_center}


def _open_shift(db, env, shift="morning"):
    service = ShiftReportService(db)
    shift_id = _ok(service.open_shift(tenant_id=TENANT, actor_id=env["actor"], work_center_id=env["work_center"], report_date=DAY, shift=shift))["id"]
    return service, shift_id


def _order(db, env, *, product_id=None):
    orders = WorkOrderService(db)
    of_id = _ok(orders.create_work_order(tenant_id=TENANT, actor_id=env["actor"], product_id=product_id, planned_quantity=1000, work_center_id=env["work_center"], start_date=DAY)).id
    _ok(orders.start_work_order(tenant_id=TENANT, actor_id=env["actor"], work_order_id=of_id))
    return of_id


def _save_runs(service, env, shift_id, of_ids):
    _ok(service.save_section(
        tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key="runs",
        payload={"runs": [{"of_id": of_id, "start_time": "07:00", "end_time": "14:00", "production_minutes": 420, "finished_product_quantity": 900} for of_id in of_ids]},
    ))


def _save_packing(service, env, shift_id, rows):
    return service.save_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key="packing", payload={"rows": rows})


def _packing_rows(service, shift_id):
    sections = _ok(service.get_shift(tenant_id=TENANT, shift_report_id=shift_id))["sections"]
    return next(s for s in sections if s["key"] == "packing")["payload"]["rows"]


def test_a_row_derives_type_packets_and_store_from_its_own_product(db, env):
    service, shift_id = _open_shift(db, env)
    of_id = _order(db, env)  # created with no product, as the screen creates it
    _save_runs(service, env, shift_id, [of_id])
    _ok(_save_packing(service, env, shift_id, [{"product_id": env["small"], "carton_quantity": 10}]))
    [row] = _packing_rows(service, shift_id)
    assert row["of_id"] == of_id
    assert row["product_id"] == env["small"]
    assert row["packing_type"] == "Sachet 200 g"
    assert row["packets_counted"] == 240  # 10 cartons x 24 packets
    assert row["finished_goods_location_id"] == env["fg_small"]
    assert row["run_id"] is not None  # the OF has exactly one run on the shift


def test_a_row_without_a_product_takes_its_orders_product(db, env):
    service, shift_id = _open_shift(db, env)
    of_id = _order(db, env, product_id=env["big"])
    _save_runs(service, env, shift_id, [of_id])
    _ok(_save_packing(service, env, shift_id, [{"carton_quantity": 10}]))
    [row] = _packing_rows(service, shift_id)
    assert row["product_id"] == env["big"] and row["packing_type"] == "Sachet 500 g"


def test_changing_the_product_re_derives_the_row(db, env):
    service, shift_id = _open_shift(db, env)
    _save_runs(service, env, shift_id, [_order(db, env)])
    _ok(_save_packing(service, env, shift_id, [{"product_id": env["small"], "carton_quantity": 10}]))
    [saved] = _packing_rows(service, shift_id)
    # The screen re-sends the row without the fields the server derived and clears the OF on a product change.
    _ok(_save_packing(service, env, shift_id, [{"id": saved["id"], "product_id": env["big"], "carton_quantity": 10}]))
    [row] = _packing_rows(service, shift_id)
    assert (row["packing_type"], row["packets_counted"], row["finished_goods_location_id"]) == ("Sachet 500 g", 120, env["fg_big"])


def test_two_orders_are_told_apart_by_the_rows_product(db, env):
    service, shift_id = _open_shift(db, env)
    small_of = _order(db, env, product_id=env["small"])
    big_of = _order(db, env, product_id=env["big"])
    _save_runs(service, env, shift_id, [small_of, big_of])
    _ok(_save_packing(service, env, shift_id, [{"product_id": env["big"], "carton_quantity": 1}]))
    [row] = _packing_rows(service, shift_id)
    assert row["of_id"] == big_of


def test_two_orders_and_no_product_is_ambiguous(db, env):
    service, shift_id = _open_shift(db, env)
    _save_runs(service, env, shift_id, [_order(db, env, product_id=env["small"]), _order(db, env, product_id=env["big"])])
    refused = _save_packing(service, env, shift_id, [{"carton_quantity": 1}])
    assert isinstance(refused, Err) and refused.code == "OF_AMBIGUOUS"


def test_a_shift_with_no_production_says_to_enter_it_first(db, env):
    service, shift_id = _open_shift(db, env)
    refused = _save_packing(service, env, shift_id, [{"product_id": env["small"], "carton_quantity": 1}])
    assert isinstance(refused, Err) and refused.code == "PRODUCTION_FIRST"


def test_handing_in_needs_a_product(db, env):
    service, shift_id = _open_shift(db, env)
    _save_runs(service, env, shift_id, [_order(db, env)])  # an order with no product either
    _ok(_save_packing(service, env, shift_id, [{"carton_quantity": 3}]))  # a draft may be saved without one
    refused = service.submit_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key="packing")
    assert isinstance(refused, Err) and refused.code == "PRODUCT_REQUIRED"
