"""Validating a shift with two products posts each under its own product and stamps the order."""
from __future__ import annotations

import datetime

import pytest
from ulid import ULID

from core.domain.result import Ok
from modules.production.api.of_consolidation_service import OfConsolidationService
from modules.production.api.packaging_variance_service import PackagingVarianceService
from modules.production.api.product_classification_service import ProductClassificationService
from modules.production.api.service import WorkOrderService
from modules.production.api.shift_report_service import ShiftReportService
from modules.production.api.shift_validation_service import ShiftValidationService
from modules.production.domain.shift_report import SECTION_KEYS
from modules.warehouse.api.service import StockService

TENANT = "packing-product-validation-test"
DAY = datetime.date(2030, 9, 12)


def _ok(result):
    assert isinstance(result, Ok), getattr(result, "message", result)
    return result.value


@pytest.fixture
def env(db):
    actor, uom, small, big, semolina, silo, fg_small, fg_big, work_center = (str(ULID()) for _ in range(9))
    db.execute("INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')", (actor, TENANT, f"{actor}@test.local"))
    db.execute("INSERT INTO core.uoms (id, tenant_id, code, name, category) VALUES (%s, %s, 'kg', 'Kilogram', 'weight')", (uom, TENANT))
    for product_id, sku in ((small, "PV-200"), (big, "PV-500"), (semolina, "PV-SEMO")):
        db.execute("INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, %s, %s, %s)", (product_id, TENANT, sku, sku, uom))
    for location_id, code in ((silo, "PV-SILO"), (fg_small, "PV-FG-200"), (fg_big, "PV-FG-500")):
        db.execute("INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, %s, %s)", (location_id, TENANT, code, code))
    db.execute("UPDATE core.products SET net_weight_grams = 200, packets_per_carton = 24, default_location_id = %s WHERE id = %s", (fg_small, small))
    db.execute("UPDATE core.products SET net_weight_grams = 500, packets_per_carton = 12, default_location_id = %s WHERE id = %s", (fg_big, big))
    db.execute("INSERT INTO production.work_centers (id, tenant_id, code, name) VALUES (%s, %s, 'PV-WC', 'Line')", (work_center, TENANT))
    for stage in ("versement", "extrusion", "conditionnement"):
        db.execute(
            "INSERT INTO maintenance.equipment (id, tenant_id, work_center_id, code, name, production_stage) VALUES (%s, %s, %s, %s, %s, %s)",
            (str(ULID()), TENANT, work_center, f"PV-{stage}", stage, stage),
        )
    for product_id in (small, big):
        ProductClassificationService(db).set_classification(tenant_id=TENANT, actor_id=actor, product_id=product_id, category="finished_good", packaging_format="packet")
    StockService(db).receive_stock(tenant_id=TENANT, product_id=semolina, location_id=silo, quantity=100_000, correlation_id=str(ULID()), reference="seed", actor_id=actor)
    return {"actor": actor, "small": small, "big": big, "semolina": semolina, "silo": silo, "fg_small": fg_small, "fg_big": fg_big, "work_center": work_center}


def _on_hand(db, product_id, location_id) -> float:
    row = db.execute(
        "SELECT quantity_on_hand FROM warehouse.stock_items WHERE tenant_id = %s AND product_id = %s AND location_id = %s",
        (TENANT, product_id, location_id),
    ).fetchone()
    return float(row[0]) if row else 0.0


def _two_product_shift(db, env):
    """One OF with no product, one run, and a packing row for each of two products."""
    service = ShiftReportService(db)
    shift_id = _ok(service.open_shift(tenant_id=TENANT, actor_id=env["actor"], work_center_id=env["work_center"], report_date=DAY, shift="morning"))["id"]
    orders = WorkOrderService(db)
    of_id = _ok(orders.create_work_order(tenant_id=TENANT, actor_id=env["actor"], planned_quantity=1000, work_center_id=env["work_center"], start_date=DAY)).id
    _ok(orders.start_work_order(tenant_id=TENANT, actor_id=env["actor"], work_order_id=of_id))
    _ok(service.save_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key="runs", payload={"runs": [{
        "of_id": of_id, "start_time": "07:00", "end_time": "14:00", "production_minutes": 420, "finished_product_quantity": 900,
        "raw_material_location_id": env["silo"],
        "semolina_lines": [{"product_id": env["semolina"], "quantity": 1000, "location_id": env["silo"]}],
    }]}))
    filled = {"packing": {"rows": [
        {"product_id": env["big"], "packets_counted": 120, "lot_number": "PV-L1"},
        {"product_id": env["small"], "packets_counted": 240, "lot_number": "PV-L2"},
    ]}}
    for key in SECTION_KEYS:
        if key == "runs":
            _ok(service.submit_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key))
        elif key in filled:
            _ok(service.save_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key, payload=filled[key]))
            _ok(service.submit_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key))
        else:
            _ok(service.declare_nothing(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key))
    return shift_id, of_id


def test_each_product_is_posted_under_its_own_product(db, env):
    shift_id, _ = _two_product_shift(db, env)
    _ok(ShiftValidationService(db).validate_shift(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id))
    assert _on_hand(db, env["big"], env["fg_big"]) == 120
    assert _on_hand(db, env["small"], env["fg_small"]) == 240


def test_reversing_takes_each_product_back_out(db, env):
    shift_id, _ = _two_product_shift(db, env)
    _ok(ShiftValidationService(db).validate_shift(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id))
    _ok(ShiftValidationService(db).reverse_shift(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, reason="test"))
    assert _on_hand(db, env["big"], env["fg_big"]) == 0
    assert _on_hand(db, env["small"], env["fg_small"]) == 0


def test_the_first_validation_stamps_an_order_that_has_no_product(db, env):
    shift_id, of_id = _two_product_shift(db, env)
    assert db.execute("SELECT product_id FROM production.work_orders WHERE id = %s", (of_id,)).fetchone()[0] is None
    _ok(ShiftValidationService(db).validate_shift(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id))
    assert db.execute("SELECT product_id FROM production.work_orders WHERE id = %s", (of_id,)).fetchone()[0] == env["big"]  # its first row


def _validated(db, env):
    shift_id, of_id = _two_product_shift(db, env)
    _ok(ShiftValidationService(db).validate_shift(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id))
    return of_id


def test_the_product_view_groups_by_the_rows_product(db, env):
    _validated(db, env)
    by_product = {p["product_id"]: p for p in PackagingVarianceService(db).by_product(tenant_id=TENANT)}
    assert set(by_product) == {env["big"], env["small"]}
    assert by_product[env["big"]]["counted_packets"] == 120 and by_product[env["small"]]["counted_packets"] == 240
    assert by_product[env["big"]]["net_weight_grams"] == 500 and by_product[env["small"]]["net_weight_grams"] == 200


def test_a_two_product_order_returns_one_breakdown_per_product(db, env):
    of_id = _validated(db, env)
    result = _ok(PackagingVarianceService(db).for_of(tenant_id=TENANT, of_id=of_id))
    assert result["multi_product"] is True
    assert {p["product_id"] for p in result["products"]} == {env["big"], env["small"]}
    assert all(p["tonnage"] is None for p in result["products"])  # an order's tonnage cannot be split by product


def test_a_one_product_order_keeps_its_old_shape(db, env):
    shift_id, of_id = _two_product_shift(db, env)
    db.execute("UPDATE production.shift_packing_rows SET product_id = %s WHERE shift_report_id = %s", (env["big"], shift_id))
    _ok(ShiftValidationService(db).validate_shift(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id))
    result = _ok(PackagingVarianceService(db).for_of(tenant_id=TENANT, of_id=of_id))
    assert "multi_product" not in result and result["product_id"] == env["big"]


def test_consolidation_lists_every_product_of_the_order(db, env):
    of_id = _validated(db, env)
    consolidation = _ok(OfConsolidationService(db).consolidate(tenant_id=TENANT, of_id=of_id))
    assert consolidation["product_ids"] == [env["big"], env["small"]]


def test_a_product_already_on_the_order_is_never_overwritten(db, env):
    shift_id, of_id = _two_product_shift(db, env)
    db.execute("UPDATE production.work_orders SET product_id = %s WHERE id = %s", (env["small"], of_id))
    _ok(ShiftValidationService(db).validate_shift(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id))
    assert db.execute("SELECT product_id FROM production.work_orders WHERE id = %s", (of_id,)).fetchone()[0] == env["small"]
    assert _on_hand(db, env["big"], env["fg_big"]) == 120  # the row still posts under its own product
