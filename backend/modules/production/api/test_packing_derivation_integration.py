"""A packing row takes its OF, type, packets and stores from data the system already holds."""
from __future__ import annotations

import datetime

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from modules.production.api.product_classification_service import ProductClassificationService
from modules.production.api.service import WorkOrderService
from modules.production.api.shift_report_service import ShiftReportService

TENANT = "packing-derivation-test"
DAY = datetime.date(2030, 7, 8)


def _ok(result):
    assert isinstance(result, Ok), getattr(result, "message", result)
    return result.value


@pytest.fixture
def env(db):
    actor, uom, pasta, film, carton, fg, pack, other, work_center = (str(ULID()) for _ in range(9))
    db.execute("INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')", (actor, TENANT, f"{actor}@test.local"))
    db.execute("INSERT INTO core.uoms (id, tenant_id, code, name, category) VALUES (%s, %s, 'kg', 'Kilogram', 'weight')", (uom, TENANT))
    for product_id, sku in ((pasta, "PD-PASTA"), (film, "PD-FILM"), (carton, "PD-CARTON")):
        db.execute("INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, %s, %s, %s)", (product_id, TENANT, sku, sku, uom))
    for location_id, code in ((fg, "PD-FG"), (pack, "PD-PACK"), (other, "PD-OTHER")):
        db.execute("INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, %s, %s)", (location_id, TENANT, code, code))
    db.execute("UPDATE core.products SET net_weight_grams = 500, packets_per_carton = 12, default_location_id = %s WHERE id = %s", (fg, pasta))
    db.execute("UPDATE core.products SET default_location_id = %s WHERE id = ANY(%s)", (pack, [film, carton]))
    db.execute("INSERT INTO production.work_centers (id, tenant_id, code, name) VALUES (%s, %s, 'PD-WC', 'Line')", (work_center, TENANT))
    ProductClassificationService(db).set_classification(
        tenant_id=TENANT, actor_id=actor, product_id=pasta, category="finished_good", packaging_format="packet"
    )
    return {"actor": actor, "pasta": pasta, "film": film, "carton": carton, "fg": fg, "pack": pack, "other": other, "work_center": work_center}


def _shift_with_run(db, env):
    service = ShiftReportService(db)
    shift_id = _ok(service.open_shift(tenant_id=TENANT, actor_id=env["actor"], work_center_id=env["work_center"], report_date=DAY, shift="morning"))["id"]
    orders = WorkOrderService(db)
    of_id = _ok(orders.create_work_order(tenant_id=TENANT, actor_id=env["actor"], product_id=env["pasta"], planned_quantity=1000, work_center_id=env["work_center"], start_date=DAY)).id
    _ok(orders.start_work_order(tenant_id=TENANT, actor_id=env["actor"], work_order_id=of_id))
    _ok(service.save_section(
        tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key="runs",
        payload={"runs": [{"of_id": of_id, "start_time": "07:00", "end_time": "14:00", "production_minutes": 420, "finished_product_quantity": 900}]},
    ))
    run_id = _ok(service.get_shift(tenant_id=TENANT, shift_report_id=shift_id))["sections"][0]["payload"]["runs"][0]["id"]
    return service, shift_id, of_id, run_id


def _save_packing(service, env, shift_id, rows):
    return service.save_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key="packing", payload={"rows": rows})


def _saved_row(service, shift_id):
    sections = _ok(service.get_shift(tenant_id=TENANT, shift_report_id=shift_id))["sections"]
    return next(s for s in sections if s["key"] == "packing")["payload"]["rows"][0]


def test_the_row_takes_its_of_type_packets_and_stores_from_the_run(db, env):
    service, shift_id, of_id, run_id = _shift_with_run(db, env)
    _ok(_save_packing(service, env, shift_id, [{
        "run_id": run_id, "carton_quantity": 10, "waste_carton_quantity": 1, "carton_product_id": env["carton"],
        "film_product_id": env["film"], "film_quantity": 5,
    }]))
    row = _saved_row(service, shift_id)
    assert row["of_id"] == of_id
    assert row["packing_type"] == "Sachet 500 g"
    assert row["packets_counted"] == 108  # (10 - 1) cartons x 12 packets
    assert row["finished_goods_location_id"] == env["fg"]
    assert row["packaging_location_id"] == env["pack"]


def test_what_the_team_typed_is_kept(db, env):
    service, shift_id, _, run_id = _shift_with_run(db, env)
    _ok(_save_packing(service, env, shift_id, [{
        "run_id": run_id, "packets_counted": 50, "finished_goods_location_id": env["other"], "packaging_location_id": env["other"],
        "film_product_id": env["film"], "film_quantity": 1,
    }]))
    row = _saved_row(service, shift_id)
    assert (row["packets_counted"], row["finished_goods_location_id"], row["packaging_location_id"]) == (50, env["other"], env["other"])


def test_a_row_with_no_production_on_the_shift_is_refused_on_save(db, env):
    service = ShiftReportService(db)
    shift_id = _ok(service.open_shift(tenant_id=TENANT, actor_id=env["actor"], work_center_id=env["work_center"], report_date=DAY, shift="night"))["id"]
    refused = _save_packing(service, env, shift_id, [{"carton_quantity": 3}])
    assert isinstance(refused, Err) and refused.code == "PRODUCTION_FIRST"


def test_packaging_kept_in_different_stores_is_refused(db, env):
    service, shift_id, _, run_id = _shift_with_run(db, env)
    db.execute("UPDATE core.products SET default_location_id = %s WHERE id = %s", (env["other"], env["carton"]))
    refused = _save_packing(service, env, shift_id, [{
        "run_id": run_id, "film_product_id": env["film"], "carton_product_id": env["carton"], "film_quantity": 1, "carton_quantity": 1,
    }])
    assert isinstance(refused, Err) and refused.code == "PACKAGING_STORES_DIFFER"


def test_submitting_needs_a_product(db, env):
    service, shift_id, of_id, _ = _shift_with_run(db, env)
    db.execute("UPDATE production.work_orders SET product_id = NULL WHERE id = %s", (of_id,))
    _ok(_save_packing(service, env, shift_id, [{"of_id": of_id, "packets_counted": 10, "finished_goods_location_id": env["fg"]}]))
    refused = service.submit_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key="packing")
    assert isinstance(refused, Err) and refused.code == "PRODUCT_REQUIRED"


def test_submitting_names_a_product_without_a_default_store(db, env):
    service, shift_id, _, run_id = _shift_with_run(db, env)
    db.execute("UPDATE core.products SET default_location_id = NULL WHERE id = %s", (env["pasta"],))
    _ok(_save_packing(service, env, shift_id, [{"run_id": run_id, "carton_quantity": 10}]))  # a draft may be saved
    refused = service.submit_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key="packing")
    assert isinstance(refused, Err) and refused.code == "NO_DEFAULT_LOCATION"
    assert "default storage location" in refused.message


def test_derived_figures_follow_the_row_when_the_screen_does_not_send_them_back(db, env):
    service, shift_id, _, run_id = _shift_with_run(db, env)
    _ok(_save_packing(service, env, shift_id, [{"run_id": run_id, "carton_quantity": 10}]))
    assert _saved_row(service, shift_id)["packets_counted"] == 120
    # The screen re-saves the row without the fields the server derived (see `serverDerived` in the section config).
    saved = _saved_row(service, shift_id)
    _ok(_save_packing(service, env, shift_id, [{"id": saved["id"], "run_id": run_id, "carton_quantity": 20}]))
    assert _saved_row(service, shift_id)["packets_counted"] == 240
