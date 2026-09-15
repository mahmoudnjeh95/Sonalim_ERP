"""Integration test for the day-level recap export.

Exercises the pieces daily_recap_export.py adds on top of the existing
monthly consumption report: semoule consumption priced from procurement's
landed-cost purchase history (MaterialConsumptionService), finished goods by
product (FinishedGoodsService), and the workbook itself building without
error and wiring the "Coût de production" sheet's formula to the right
cross-sheet cell.
"""
from __future__ import annotations

import datetime

import pytest
from ulid import ULID

from core.domain.result import Ok
from modules.procurement.api.service import PurchaseOrderService
from modules.production.api.conditionnement_service import ConditionnementReportService
from modules.production.api.daily_recap_export import build_daily_recap_workbook, day_phrase
from modules.production.api.finished_goods_service import FinishedGoodsService
from modules.production.api.mp_consumption_service import MaterialConsumptionService
from modules.production.api.consumption_report_service import ConsumptionReportService
from modules.production.api.production_report_service import ProductionReportService
from modules.production.api.service import WorkOrderService
from modules.production.domain.production_report import (
    ConditionnementReportDetail,
    DailyReportDetail,
    SemolinaLine,
)
from modules.warehouse.api.service import StockService

TENANT = "integration-test-daily-recap"


@pytest.fixture
def env(db):
    actor = str(ULID())
    uom_ton, location, work_center, equipment, supplier = (str(ULID()) for _ in range(5))
    finished_product, semoule, carton = (str(ULID()) for _ in range(3))

    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (actor, TENANT, f"{actor}@test.local"),
    )
    db.execute(
        "INSERT INTO core.uoms (id, tenant_id, code, name, category) VALUES (%s, %s, 'ton', 'Tonne', 'weight')",
        (uom_ton, TENANT),
    )
    db.execute(
        "INSERT INTO core.products (id, tenant_id, sku, name, uom_id, net_weight_grams) VALUES (%s, %s, %s, %s, %s, %s)",
        (finished_product, TENANT, "TEST-FINISHED", "TEST-FINISHED", uom_ton, 500),
    )
    db.execute(
        "INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, %s, %s, %s)",
        (semoule, TENANT, "TEST-SEMOULE", "TEST-SEMOULE", uom_ton),
    )
    db.execute(
        "INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, %s, %s, %s)",
        (carton, TENANT, "TEST-CARTON", "TEST-CARTON", uom_ton),
    )
    db.execute(
        "INSERT INTO core.partners (id, tenant_id, name, kind, status) VALUES (%s, %s, 'Test MP Supplier', 'supplier', 'active')",
        (supplier, TENANT),
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
    # Semoule must already be in stock for the daily report's semolina line to
    # validate (validation posts a stock move consuming it), same as the
    # packaging products in test_consumption_report_integration.py.
    StockService(db).receive_stock(
        tenant_id=TENANT, product_id=semoule, location_id=location,
        quantity=1000, correlation_id=str(ULID()), reference="test-seed", actor_id=actor,
    )
    StockService(db).receive_stock(
        tenant_id=TENANT, product_id=carton, location_id=location,
        quantity=10_000, correlation_id=str(ULID()), reference="test-seed", actor_id=actor,
    )

    return {
        "actor": actor, "uom_ton": uom_ton, "location": location, "work_center": work_center,
        "equipment": equipment, "supplier": supplier, "finished_product": finished_product, "semoule": semoule,
        "carton": carton,
    }


@pytest.fixture
def of(db, env):
    service = WorkOrderService(db)
    created = service.create_work_order(
        tenant_id=TENANT, actor_id=env["actor"], work_center_id=env["work_center"],
        product_id=env["finished_product"], planned_quantity=50, product_type="PL",
    )
    assert isinstance(created, Ok), getattr(created, "message", "")
    service.start_work_order(tenant_id=TENANT, actor_id=env["actor"], work_order_id=created.value.id)
    return created.value


def _confirm_a_receipt(db, env, *, quantity: float, base_cost: float, transport_fee: float = 0) -> None:
    """A minimal ordered -> received -> confirmed purchase order for the
    semoule product, so MaterialConsumptionService has a landed cost to price
    consumption against."""
    procurement = PurchaseOrderService(db)
    po = procurement.create_purchase_order(
        tenant_id=TENANT, actor_id=env["actor"], supplier_id=env["supplier"],
        order_date=datetime.date(2026, 8, 1), currency_code="XOF",
        lines=[{"product_id": env["semoule"], "uom_id": env["uom_ton"], "quantity_ordered": quantity, "unit_price": 0, "unit_price_currency": "XOF"}],
    ).value
    for method in ("validate_order", "approve_order", "place_order"):
        result = getattr(procurement, method)(tenant_id=TENANT, actor_id=env["actor"], order_id=po.id)
        assert isinstance(result, Ok), getattr(result, "message", "")

    line = procurement.list_lines(tenant_id=TENANT, purchase_order_id=po.id)[0]
    receipt = procurement.create_receipt(
        tenant_id=TENANT, actor_id=env["actor"], purchase_order_id=po.id, location_id=env["location"],
        currency_code="XOF", invoice_date=datetime.date(2026, 8, 5),
        lines=[{"purchase_order_line_id": line.id, "quantity": quantity}],
        base_cost=base_cost, transport_fee=transport_fee,
    ).value
    confirmed = procurement.confirm_receipt(tenant_id=TENANT, actor_id=env["actor"], receipt_id=receipt.id, correlation_id=str(ULID()))
    assert isinstance(confirmed, Ok), getattr(confirmed, "message", "")


def test_mp_consumption_is_priced_from_landed_cost(db, env, of):
    _confirm_a_receipt(db, env, quantity=100, base_cost=50_000_000, transport_fee=5_000_000)
    # Landed cost/tonne = (50M + 5M) / 100 = 550,000 CFA/tonne.

    report_date = datetime.date(2026, 9, 10)
    daily = ProductionReportService(db).create_daily_report(
        tenant_id=TENANT, actor_id=env["actor"], of_id=of.id, report_date=report_date,
        equipment_id=env["equipment"], shift="morning",
        detail=DailyReportDetail(
            semolina_lines=(SemolinaLine(product_id=env["semoule"], quantity=5, location_id=env["location"]),),
        ),
    ).value["report"]
    ProductionReportService(db).submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=daily.id)
    validated = ProductionReportService(db).validate_report(tenant_id=TENANT, actor_id=env["actor"], report_id=daily.id)
    assert isinstance(validated, Ok), getattr(validated, "message", "")

    rows = MaterialConsumptionService(db).list_consumption(tenant_id=TENANT, date_from="2026-09-10", date_to="2026-09-10")
    assert len(rows) == 1
    row = rows[0]
    assert row["product_id"] == env["semoule"]
    assert row["quantity"] == 5
    assert row["priced"] is True
    assert row["unit_cost"] == pytest.approx(550_000)
    assert row["cost"] == pytest.approx(5 * 550_000)


def test_consumption_outside_the_date_range_is_excluded(db, env, of):
    report_date = datetime.date(2026, 9, 10)
    daily = ProductionReportService(db).create_daily_report(
        tenant_id=TENANT, actor_id=env["actor"], of_id=of.id, report_date=report_date,
        equipment_id=env["equipment"], shift="morning",
        detail=DailyReportDetail(
            semolina_lines=(SemolinaLine(product_id=env["semoule"], quantity=3, location_id=env["location"]),),
        ),
    ).value["report"]
    ProductionReportService(db).submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=daily.id)
    ProductionReportService(db).validate_report(tenant_id=TENANT, actor_id=env["actor"], report_id=daily.id)

    rows = MaterialConsumptionService(db).list_consumption(tenant_id=TENANT, date_from="2026-09-11", date_to="2026-09-11")
    assert rows == []


def test_finished_goods_grouped_by_product_and_pc_pl(db, env, of):
    report_date = datetime.date(2026, 9, 10)
    cond = ConditionnementReportService(db).create_report(
        tenant_id=TENANT, actor_id=env["actor"], of_id=of.id, report_date=report_date,
        shift="morning", equipment_id=env["equipment"],
        detail=ConditionnementReportDetail(
            packets_counted=5000,  # 5000 * 500g (see env's net_weight_grams) = 2.5 tonnes, derived on validation
            packaging_location_id=env["location"], finished_goods_location_id=env["location"],
        ),
    ).value["report"]
    ProductionReportService(db).submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=cond.id)
    validated = ProductionReportService(db).validate_report(tenant_id=TENANT, actor_id=env["actor"], report_id=cond.id)
    assert isinstance(validated, Ok), getattr(validated, "message", "")

    rows = FinishedGoodsService(db).list_finished_goods(tenant_id=TENANT, date_from="2026-09-10", date_to="2026-09-10")
    assert len(rows) == 1
    assert rows[0]["product_id"] == env["finished_product"]
    assert rows[0]["pc_pl"] == "PL"
    assert rows[0]["quantity"] == pytest.approx(2.5)
    assert rows[0]["packets_counted"] == 5000


def test_daily_recap_workbook_builds_and_wires_the_charge_formula(db, env, of):
    """End-to-end: real data through every service, into the workbook, with
    the 'Coût de production' sheet's formula referencing the 'Charge
    production' subtotal cell rather than a hardcoded number -- that's the
    whole point of keeping charges manually editable in the exported file."""
    _confirm_a_receipt(db, env, quantity=100, base_cost=55_000_000)
    report_date = datetime.date(2026, 9, 10)

    daily = ProductionReportService(db).create_daily_report(
        tenant_id=TENANT, actor_id=env["actor"], of_id=of.id, report_date=report_date,
        equipment_id=env["equipment"], shift="morning",
        detail=DailyReportDetail(
            semolina_lines=(SemolinaLine(product_id=env["semoule"], quantity=4, location_id=env["location"]),),
        ),
    ).value["report"]
    ProductionReportService(db).submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=daily.id)
    validated_daily = ProductionReportService(db).validate_report(tenant_id=TENANT, actor_id=env["actor"], report_id=daily.id)
    assert isinstance(validated_daily, Ok), getattr(validated_daily, "message", "")

    cond = ConditionnementReportService(db).create_report(
        tenant_id=TENANT, actor_id=env["actor"], of_id=of.id, report_date=report_date,
        shift="morning", equipment_id=env["equipment"],
        detail=ConditionnementReportDetail(
            packets_counted=7600,  # 7600 * 500g (see env's net_weight_grams) = 3.8 tonnes, derived on validation
            carton_quantity=760, carton_product_id=env["carton"],
            packaging_location_id=env["location"], finished_goods_location_id=env["location"],
        ),
    ).value["report"]
    ProductionReportService(db).submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=cond.id)
    validated_cond = ProductionReportService(db).validate_report(tenant_id=TENANT, actor_id=env["actor"], report_id=cond.id)
    assert isinstance(validated_cond, Ok), getattr(validated_cond, "message", "")

    mp_rows = MaterialConsumptionService(db).list_consumption(tenant_id=TENANT, date_from="2026-09-10", date_to="2026-09-10")
    packaging_rows = ConsumptionReportService(db).list_monthly_consumption_by_supplier(
        tenant_id=TENANT, date_from="2026-09-10", date_to="2026-09-10"
    )
    finished_goods_rows = FinishedGoodsService(db).list_finished_goods(tenant_id=TENANT, date_from="2026-09-10", date_to="2026-09-10")
    receipt_lines = PurchaseOrderService(db).list_confirmed_receipt_line_details(tenant_id=TENANT)

    content = build_daily_recap_workbook(
        period_phrase=day_phrase("2026-09-10"), period_days=1,
        mp_rows=mp_rows, packaging_rows=packaging_rows, finished_goods_rows=finished_goods_rows,
        receipt_lines=receipt_lines, mp_product_ids={env["semoule"]}, film_product_ids=set(), carton_product_ids=set(),
        product_names={env["semoule"]: "Semoule Test", env["finished_product"]: "Produit Test"},
        supplier_names={env["supplier"]: "Test MP Supplier"},
    )
    assert len(content) > 0

    import io

    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(content))
    assert {
        "Produit fini", "Consommation MP", "Film", "Carton", "Rub&Scotch", "Gasoil", "Fuel",
        "Coût unitaire", "Achats MP", "Achats Film", "Achats Carton", "Charge production", "Coût de production",
    } <= set(wb.sheetnames)

    cost_sheet = wb["Coût de production"]
    assert cost_sheet["B3"].value == pytest.approx(4 * 550_000)  # coût MP: (55M/100)*4
    assert cost_sheet["B5"].value == "='Charge production'!C17"
    assert cost_sheet["B6"].value == pytest.approx(3.8)  # tonnage
    assert cost_sheet["B7"].value == pytest.approx(760)  # cartons
    assert cost_sheet["B8"].value == pytest.approx(7600)  # paquets
    assert cost_sheet["B10"].value == '=IFERROR((B3+B4+B5)/B6,"—")'  # coût / tonne
    assert cost_sheet["B11"].value == '=IFERROR((B3+B4+B5)/B7,"—")'  # coût / carton
    assert cost_sheet["B12"].value == '=IFERROR((B3+B4+B5)/B8,"—")'  # coût / paquet

    finished_sheet = wb["Produit fini"]
    assert finished_sheet["A4"].value == "Produit Test"
    assert finished_sheet["D4"].value == 3.8
