"""Integration tests for ShiftStockService, against a real database.

Ported from the old ReportStockService/ProductionReportService test coverage
(test_report_flow_integration.py) onto the shift tables directly: a
shift_runs row plays the role a daily_reports row played there.

Every test runs inside the `db` fixture's transaction and is rolled back.
"""
from __future__ import annotations

import datetime

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from modules.production.api.shift_report_service import ShiftReportService
from modules.production.api.shift_stock_service import ShiftStockService
from modules.production.api.service import WorkOrderService
from modules.warehouse.api.service import StockService

TENANT = "integration-test"


@pytest.fixture
def env(db):
    """Reference rows this module's foreign keys require, created in-transaction."""
    actor = str(ULID())
    uom, product, semolina, location, work_center, equipment = (str(ULID()) for _ in range(6))

    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (actor, TENANT, f"{actor}@test.local"),
    )
    db.execute(
        "INSERT INTO core.uoms (id, tenant_id, code, name, category) VALUES (%s, %s, 'kg', 'Kilogram', 'weight')",
        (uom, TENANT),
    )
    db.execute(
        "INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, 'TEST-PASTA', 'Test pasta', %s)",
        (product, TENANT, uom),
    )
    db.execute(
        "INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, 'TEST-SEMOLINA', 'Test semolina', %s)",
        (semolina, TENANT, uom),
    )
    db.execute(
        "INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, 'TEST-LOC', 'Test location')",
        (location, TENANT),
    )
    db.execute(
        "INSERT INTO production.work_centers (id, tenant_id, code, name) VALUES (%s, %s, 'TEST-WC', 'Test line')",
        (work_center, TENANT),
    )
    db.execute(
        "INSERT INTO maintenance.equipment (id, tenant_id, work_center_id, code, name) VALUES (%s, %s, %s, 'TEST-EQ', 'Test machine')",
        (equipment, TENANT, work_center),
    )
    return {
        "actor": actor,
        "product": product,
        "semolina": semolina,
        "location": location,
        "work_center": work_center,
        "equipment": equipment,
    }


def _open_of(db, env, status: str = "ongoing"):
    service = WorkOrderService(db)
    created = service.create_work_order(
        tenant_id=TENANT,
        actor_id=env["actor"],
        product_id=env["product"],
        planned_quantity=1000,
        work_center_id=env["work_center"],
        start_date=datetime.date(2026, 9, 1),
    )
    assert isinstance(created, Ok), getattr(created, "message", "")
    order = created.value
    if status != "planned":
        assert isinstance(service.start_work_order(tenant_id=TENANT, actor_id=env["actor"], work_order_id=order.id), Ok)
    return order


def _open_shift_with_run(db, env, of_id, **run_overrides):
    """Open a shift, save one run in it, and return the run as a plain dict
    with its semolina_lines joined in -- the shape ShiftStockService expects."""
    shifts = ShiftReportService(db)
    header = shifts.open_shift(
        tenant_id=TENANT, actor_id=env["actor"], work_center_id=env["work_center"],
        report_date=datetime.date(2026, 9, 1), shift="morning", team="Équipe A",
    )
    assert isinstance(header, Ok), getattr(header, "message", "")
    shift_id = header.value["id"]

    run_payload = {
        "of_id": of_id, "equipment_id": env["equipment"], "start_time": "07:00", "end_time": "09:00",
        "production_minutes": 120, "dough_quantity": 100, "finished_product_quantity": 100,
        "regrind_quantity": 0, "raw_material_location_id": env["location"],
        "semolina_lines": [],
    }
    run_payload.update(run_overrides)

    saved = shifts.save_section(
        tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key="runs",
        payload={"runs": [run_payload]},
    )
    assert isinstance(saved, Ok), getattr(saved, "message", "")

    cursor = db.execute("SELECT * FROM production.shift_runs WHERE shift_report_id = %s", (shift_id,))
    names = [d.name for d in cursor.description]
    run = dict(zip(names, cursor.fetchone()))

    semolina_cursor = db.execute(
        "SELECT * FROM production.shift_run_semolina_lines WHERE run_id = %s", (run["id"],)
    )
    sem_names = [d.name for d in semolina_cursor.description]
    run["semolina_lines"] = [dict(zip(sem_names, row)) for row in semolina_cursor.fetchall()]
    return run


def test_post_run_deducts_raw_material_and_not_finished_product(db, env):
    of_id = _open_of(db, env).id
    run = _open_shift_with_run(
        db, env, of_id,
        semolina_lines=[{"product_id": env["semolina"], "location_id": env["location"], "quantity": 50}],
    )
    StockService(db).receive_stock(
        tenant_id=TENANT, product_id=env["semolina"], location_id=env["location"], quantity=1000,
        correlation_id=str(ULID()), reference="test-seed", actor_id=env["actor"],
    )

    service = ShiftStockService(db)
    result = service.post_run(tenant_id=TENANT, actor_id=env["actor"], run=run, correlation_id=str(ULID()))

    assert isinstance(result, Ok), getattr(result, "message", "")
    movements = result.value["movements"]
    assert len(movements) == 1
    assert movements[0]["direction"] == "out"
    assert movements[0]["product_id"] == env["semolina"]
    assert movements[0]["quantity"] == 50

    balance = StockService(db).get_available_quantity(TENANT, env["semolina"], env["location"])
    assert balance == 950  # 1000 received - 50 consumed; finished_product posts nothing


def test_record_regrind_opens_batch_when_regrind_quantity_positive(db, env):
    regrind_output = str(ULID())
    uom_row = db.execute("SELECT uom_id FROM core.products WHERE id = %s", (env["product"],)).fetchone()
    db.execute(
        "INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, 'TEST-REBROYAT', 'Test rebroyat', %s)",
        (regrind_output, TENANT, uom_row[0]),
    )
    of_id = _open_of(db, env).id

    db.execute(
        "INSERT INTO production.regrind_defaults (id, tenant_id, input_product_id, output_product_id) "
        "VALUES (%s, %s, NULL, %s)",
        (str(ULID()), TENANT, regrind_output),
    )

    run = {"id": str(ULID()), "of_id": of_id, "work_center_id": env["work_center"], "regrind_quantity": 12.5, "semolina_lines": []}

    service = ShiftStockService(db)
    result = service.record_regrind(tenant_id=TENANT, actor_id=env["actor"], run=run, regrind_work_center_id=None)

    assert isinstance(result, Ok), getattr(result, "message", "")
    assert result.value["scrap_record_id"] is not None
    assert result.value["regrind_work_order_id"] is not None

    scrap = db.execute(
        "SELECT quantity, product_id, scrap_type FROM production.scrap_records WHERE id = %s",
        (result.value["scrap_record_id"],),
    ).fetchone()
    assert float(scrap[0]) == 12.5
    assert scrap[1] == regrind_output
    assert scrap[2] == "shift_run"


def test_record_regrind_noop_when_quantity_zero(db, env):
    of_id = _open_of(db, env).id
    run = {"id": str(ULID()), "of_id": of_id, "work_center_id": env["work_center"], "regrind_quantity": 0, "semolina_lines": []}
    result = ShiftStockService(db).record_regrind(tenant_id=TENANT, actor_id=env["actor"], run=run, regrind_work_center_id=None)
    assert isinstance(result, Ok), getattr(result, "message", "")
    assert result.value == {"scrap_record_id": None, "regrind_work_order_id": None}


def test_post_packing_receives_finished_and_issues_packaging_and_registers_lot(db, env):
    uom_row = db.execute("SELECT uom_id FROM core.products WHERE id = %s", (env["product"],)).fetchone()
    finished = str(ULID())
    film = str(ULID())
    db.execute(
        "INSERT INTO core.products (id, tenant_id, sku, name, uom_id, net_weight_grams, packets_per_carton) "
        "VALUES (%s, %s, 'TEST-FINISHED', 'Test finished', %s, 500, 20)",
        (finished, TENANT, uom_row[0]),
    )
    db.execute(
        "INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, 'TEST-FILM', 'Test film', %s)",
        (film, TENANT, uom_row[0]),
    )
    fg_store, pack_store = str(ULID()), str(ULID())
    db.execute(
        "INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, 'TEST-FG', 'Test FG store')",
        (fg_store, TENANT),
    )
    db.execute(
        "INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, 'TEST-PACK', 'Test pack store')",
        (pack_store, TENANT),
    )
    of_id = _open_of(db, env).id

    StockService(db).receive_stock(
        tenant_id=TENANT, product_id=film, location_id=pack_store, quantity=1000,
        correlation_id=str(ULID()), reference="test-seed", actor_id=env["actor"],
    )

    packing_row = {
        "id": str(ULID()), "of_id": of_id, "carton_quantity": 10, "packets_counted": 200,
        "waste_carton_quantity": 0, "film_quantity": 5, "carton_product_id": None,
        "film_product_id": film, "scotch_product_id": None, "ruban_product_id": None,
        "scotch_quantity": 0, "ruban_quantity": 0,
        "packaging_location_id": pack_store, "finished_goods_location_id": fg_store,
        "lot_number": "LOT-TEST-1", "dlc_date": None,
    }

    service = ShiftStockService(db)
    snapshot = service.freeze_packing_snapshot(tenant_id=TENANT, packing_row=packing_row, finished_product_id=finished)
    packing_row["snapshot_net_weight_grams"] = snapshot["net_weight_grams"]
    packing_row["snapshot_packets_per_carton"] = snapshot["packets_per_carton"]

    result = service.post_packing(
        tenant_id=TENANT, actor_id=env["actor"], packing_row=packing_row,
        finished_product_id=finished, correlation_id=str(ULID()),
    )
    assert isinstance(result, Ok), getattr(result, "message", "")
    movements = {m["product_id"]: m for m in result.value["movements"]}
    # carton tier present (packets_per_carton=20) -> carton_quantity(10)*20 = 200 packets = 100kg = 0.1t
    assert movements[finished]["direction"] == "in"
    assert movements[film]["direction"] == "out"
    assert movements[film]["quantity"] == 5

    lot = service.register_lot(
        tenant_id=TENANT, actor_id=env["actor"], packing_row=packing_row,
        finished_product_id=finished, report_date=datetime.date(2026, 9, 1),
    )
    assert isinstance(lot, Ok), getattr(lot, "message", "")
    assert lot.value is not None


def test_reverse_run_undoes_stock_and_removes_open_regrind_batch(db, env):
    regrind_output = str(ULID())
    uom_row = db.execute("SELECT uom_id FROM core.products WHERE id = %s", (env["product"],)).fetchone()
    db.execute(
        "INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, 'TEST-REBROYAT-2', 'Test rebroyat 2', %s)",
        (regrind_output, TENANT, uom_row[0]),
    )
    of_id = _open_of(db, env).id
    db.execute(
        "INSERT INTO production.regrind_defaults (id, tenant_id, input_product_id, output_product_id) "
        "VALUES (%s, %s, NULL, %s)",
        (str(ULID()), TENANT, regrind_output),
    )

    run = {
        "id": str(ULID()), "of_id": of_id, "work_center_id": env["work_center"], "regrind_quantity": 8.0,
        "semolina_lines": [], "raw_material_location_id": None,
    }
    service = ShiftStockService(db)
    posted = service.post_run(tenant_id=TENANT, actor_id=env["actor"], run=run, correlation_id=str(ULID()))
    assert isinstance(posted, Ok), getattr(posted, "message", "")
    regrind = service.record_regrind(tenant_id=TENANT, actor_id=env["actor"], run=run, regrind_work_center_id=None)
    assert isinstance(regrind, Ok), getattr(regrind, "message", "")
    assert regrind.value["regrind_work_order_id"] is not None

    reversed_result = service.reverse_run(tenant_id=TENANT, actor_id=env["actor"], run=run, correlation_id=str(ULID()))
    assert isinstance(reversed_result, Ok), getattr(reversed_result, "message", "")
    assert reversed_result.value["removed_scrap_records"] == 1

    remaining_order = db.execute(
        "SELECT 1 FROM production.work_orders WHERE id = %s", (regrind.value["regrind_work_order_id"],)
    ).fetchone()
    assert remaining_order is None
