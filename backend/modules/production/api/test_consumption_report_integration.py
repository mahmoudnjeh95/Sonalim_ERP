"""Integration test for the monthly consumption-by-supplier report.

Exercises the whole point of the feature: film/carton/scotch/ruban from a
validated shift's packing row and gasoil/fuel from its energy section land in
one grouped-by-category/month/supplier list, and a packaging row with
matching procurement order history gets costed from it while gasoil/fuel --
which carry no product reference at all -- do not.
"""
from __future__ import annotations

import datetime

import pytest
from ulid import ULID

from core.domain.result import Ok
from modules.procurement.api.service import PurchaseOrderService
from modules.production.api.consumption_report_service import ConsumptionReportService
from modules.production.api.service import WorkOrderService
from modules.production.api.shift_report_service import ShiftReportService
from modules.production.api.shift_validation_service import ShiftValidationService
from modules.production.domain.shift_report import SECTION_KEYS
from modules.warehouse.api.service import StockService

TENANT = "integration-test-consumption"


@pytest.fixture
def env(db):
    actor = str(ULID())
    uom, location, work_center, equipment, supplier = (str(ULID()) for _ in range(5))
    product, film, carton, scotch, ruban = (str(ULID()) for _ in range(5))

    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (actor, TENANT, f"{actor}@test.local"),
    )
    db.execute(
        "INSERT INTO core.uoms (id, tenant_id, code, name, category) VALUES (%s, %s, 'kg', 'Kilogram', 'weight')",
        (uom, TENANT),
    )
    for product_id, sku in (
        (product, "TEST-FINISHED"), (film, "TEST-FILM"), (carton, "TEST-CARTON"), (scotch, "TEST-SCOTCH"), (ruban, "TEST-RUBAN"),
    ):
        db.execute(
            "INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, %s, %s, %s)",
            (product_id, TENANT, sku, sku, uom),
        )
    db.execute(
        "INSERT INTO core.partners (id, tenant_id, name, kind, status) VALUES (%s, %s, 'Test Supplier', 'supplier', 'active')",
        (supplier, TENANT),
    )
    # EUR->XOF, effective before any test's PO order_date -- proves costing
    # converts to CFA rather than reporting the supplier's own EUR price.
    db.execute(
        "INSERT INTO core.exchange_rates (id, tenant_id, currency_code, rate_to_base, effective_date, source) "
        "VALUES (%s, %s, 'EUR', 655.957, '2026-01-01', 'test')",
        (str(ULID()), TENANT),
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
    stock = StockService(db)
    for packaging_product_id in (film, carton, scotch, ruban):
        stock.receive_stock(
            tenant_id=TENANT, product_id=packaging_product_id, location_id=location,
            quantity=10_000, correlation_id=str(ULID()), reference="test-seed", actor_id=actor,
        )

    return {
        "actor": actor, "uom": uom, "location": location, "work_center": work_center, "equipment": equipment,
        "supplier": supplier, "product": product, "film": film, "carton": carton, "scotch": scotch, "ruban": ruban,
    }


def _ok(result):
    assert isinstance(result, Ok), getattr(result, "message", result)
    return result.value


@pytest.fixture
def of(db, env):
    service = WorkOrderService(db)
    created = _ok(service.create_work_order(
        tenant_id=TENANT, actor_id=env["actor"], work_center_id=env["work_center"],
        product_id=env["product"], planned_quantity=1000, product_type="PC",
    ))
    service.start_work_order(tenant_id=TENANT, actor_id=env["actor"], work_order_id=created.id)
    return created


def _validated_shift(db, env, of_id, report_date, *, packing=None, energy=None) -> str:
    service = ShiftReportService(db)
    shift_id = _ok(service.open_shift(
        tenant_id=TENANT, actor_id=env["actor"], work_center_id=env["work_center"], report_date=report_date, shift="morning",
    ))["id"]
    filled: dict = {}
    if packing is not None:
        filled["packing"] = {"rows": [{"of_id": of_id, "equipment_id": env["equipment"], "finished_product_quantity": 100, "packets_counted": 100, **packing}]}
    if energy is not None:
        filled["energy"] = {"energy": energy}
    for key in SECTION_KEYS:
        if key in filled:
            _ok(service.save_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key, payload=filled[key]))
            _ok(service.submit_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key))
        else:
            _ok(service.declare_nothing(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key))
    _ok(ShiftValidationService(db).validate_shift(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id))
    return shift_id


def test_groups_by_category_month_and_supplier_and_costs_what_it_can(db, env, of):
    report_date = datetime.date(2026, 4, 15)

    _validated_shift(
        db, env, of.id, report_date,
        packing={
            "film_quantity": 40, "film_product_id": env["film"], "film_supplier_id": env["supplier"],
            "carton_quantity": 20, "carton_product_id": env["carton"], "carton_supplier_id": env["supplier"],
            "scotch_quantity": 5, "scotch_product_id": env["scotch"], "scotch_supplier_id": env["supplier"],
            "ruban_quantity": 3, "ruban_product_id": env["ruban"], "ruban_supplier_id": env["supplier"],
            "packaging_location_id": env["location"], "finished_goods_location_id": env["location"],
        },
        energy={"gasoil_quantity": 100, "gasoil_supplier_id": env["supplier"], "fuel_quantity": 50, "fuel_supplier_id": env["supplier"]},
    )

    # Procurement order history exists for film only -- carton/scotch/ruban and
    # gasoil/fuel should still show up, just unpriced.
    po = PurchaseOrderService(db).create_purchase_order(
        tenant_id=TENANT, actor_id=env["actor"], supplier_id=env["supplier"],
        order_date=datetime.date(2026, 4, 1), currency_code="EUR",
        lines=[{"product_id": env["film"], "uom_id": env["uom"], "quantity_ordered": 100, "unit_price": 12.5, "unit_price_currency": "EUR"}],
    )
    assert isinstance(po, Ok), getattr(po, "message", "")

    rows = ConsumptionReportService(db).list_monthly_consumption_by_supplier(
        tenant_id=TENANT, date_from="2026-04-01", date_to="2026-04-30",
    )
    by_category = {row["category"]: row for row in rows}

    assert set(by_category) == {"film", "carton", "scotch", "ruban", "gasoil", "fuel"}

    film_row = by_category["film"]
    assert film_row["quantity"] == 40
    assert film_row["pc_pl"] == "PC"
    assert film_row["supplier_id"] == env["supplier"]
    assert film_row["priced"] is True
    # 12.5 EUR converted to CFA at the rate in effect on the PO's own order
    # date (2026-04-01) -- never the supplier's raw EUR price mislabeled as CFA.
    assert film_row["unit_price"] == pytest.approx(12.5 * 655.957)
    assert film_row["unit_price_currency"] == "XOF"
    assert film_row["cost"] == pytest.approx(40 * 12.5 * 655.957)

    carton_row = by_category["carton"]
    assert carton_row["quantity"] == 20
    assert carton_row["pc_pl"] == "PC"
    assert carton_row["priced"] is False
    assert carton_row["cost"] is None

    gasoil_row = by_category["gasoil"]
    assert gasoil_row["quantity"] == 100
    assert gasoil_row["product_id"] is None
    assert gasoil_row["pc_pl"] is None
    assert gasoil_row["priced"] is False

    fuel_row = by_category["fuel"]
    assert fuel_row["quantity"] == 50
    assert fuel_row["priced"] is False


def test_a_price_with_no_exchange_rate_stays_unpriced(db, env, of):
    # A currency with order history but no rate on file (unlike EUR, seeded in
    # `env`) must not be shown under the wrong currency -- left unpriced instead.
    report_date = datetime.date(2026, 6, 12)
    _validated_shift(
        db, env, of.id, report_date,
        packing={
            "film_quantity": 10, "film_product_id": env["film"], "film_supplier_id": env["supplier"],
            "packaging_location_id": env["location"], "finished_goods_location_id": env["location"],
        },
    )

    po = PurchaseOrderService(db).create_purchase_order(
        tenant_id=TENANT, actor_id=env["actor"], supplier_id=env["supplier"],
        order_date=datetime.date(2026, 6, 1), currency_code="USD",
        lines=[{"product_id": env["film"], "uom_id": env["uom"], "quantity_ordered": 50, "unit_price": 9, "unit_price_currency": "USD"}],
    )
    assert isinstance(po, Ok), getattr(po, "message", "")

    rows = ConsumptionReportService(db).list_monthly_consumption_by_supplier(
        tenant_id=TENANT, date_from="2026-06-01", date_to="2026-06-30", category="film",
    )
    assert len(rows) == 1
    assert rows[0]["priced"] is False
    assert rows[0]["cost"] is None
    assert rows[0]["unit_price"] is None


def test_category_filter_narrows_the_result(db, env, of):
    report_date = datetime.date(2026, 5, 10)
    _validated_shift(
        db, env, of.id, report_date,
        packing={
            "film_quantity": 10, "film_product_id": env["film"], "film_supplier_id": env["supplier"],
            "scotch_quantity": 2, "scotch_product_id": env["scotch"], "scotch_supplier_id": env["supplier"],
            "packaging_location_id": env["location"], "finished_goods_location_id": env["location"],
        },
    )

    rows = ConsumptionReportService(db).list_monthly_consumption_by_supplier(
        tenant_id=TENANT, date_from="2026-05-01", date_to="2026-05-31", category="film",
    )
    assert [row["category"] for row in rows] == ["film"]


def test_invalid_category_raises(db):
    with pytest.raises(ValueError):
        ConsumptionReportService(db).list_monthly_consumption_by_supplier(tenant_id=TENANT, category="not-a-category")
