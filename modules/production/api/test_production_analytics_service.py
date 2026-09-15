"""Tests for the always-on Production recap dashboard's data (see
production_analytics_service.py): the trailing-trend window arithmetic (pure
functions, no DB) and the payload itself against real report/purchase data
(reusing the same fixture shape as test_daily_recap_export_integration.py)."""
from __future__ import annotations

import datetime

import pytest
from ulid import ULID

from core.domain.result import Ok
from modules.procurement.api.service import PurchaseOrderService
from modules.production.api.conditionnement_service import ConditionnementReportService
from modules.production.api.production_analytics_service import _trend_windows, build_analytics_payload
from modules.production.api.production_report_service import ProductionReportService
from modules.production.api.service import WorkOrderService
from modules.production.domain.production_report import ConditionnementReportDetail, DailyReportDetail, SemolinaLine
from modules.warehouse.api.service import StockService

TENANT = "integration-test-production-analytics"


def test_day_trend_is_30_consecutive_days_ending_on_the_anchor():
    windows = _trend_windows("day", "2026-09-10", 30)
    assert len(windows) == 30
    assert windows[-1] == ("2026-09-10", "2026-09-10")
    assert windows[0] == ("2026-08-12", "2026-08-12")
    # Consecutive, no gaps or overlaps.
    for (_, prev_to), (next_from, _) in zip(windows, windows[1:]):
        assert datetime.date.fromisoformat(next_from) == datetime.date.fromisoformat(prev_to) + datetime.timedelta(days=1)


def test_week_trend_is_12_consecutive_iso_weeks_ending_on_the_anchors_week():
    windows = _trend_windows("week", "2026-09-10", 12)
    assert len(windows) == 12
    assert windows[-1] == ("2026-09-07", "2026-09-13")
    for date_from, date_to in windows:
        assert (datetime.date.fromisoformat(date_to) - datetime.date.fromisoformat(date_from)).days == 6


def test_month_trend_is_12_consecutive_calendar_months_crossing_a_year_boundary():
    windows = _trend_windows("month", "2026-02-15", 12)
    assert len(windows) == 12
    assert windows[-1] == ("2026-02-01", "2026-02-28")
    assert windows[0] == ("2025-03-01", "2025-03-31")


@pytest.fixture
def env(db):
    actor = str(ULID())
    uom_ton, location, work_center, equipment, supplier = (str(ULID()) for _ in range(5))
    finished_product, semoule = (str(ULID()) for _ in range(2))

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
    StockService(db).receive_stock(
        tenant_id=TENANT, product_id=semoule, location_id=location,
        quantity=1000, correlation_id=str(ULID()), reference="test-seed", actor_id=actor,
    )

    return {
        "actor": actor, "uom_ton": uom_ton, "location": location, "work_center": work_center,
        "equipment": equipment, "supplier": supplier, "finished_product": finished_product, "semoule": semoule,
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


def _confirm_a_receipt(db, env, *, quantity: float, base_cost: float, invoice_date: datetime.date) -> None:
    procurement = PurchaseOrderService(db)
    po = procurement.create_purchase_order(
        tenant_id=TENANT, actor_id=env["actor"], supplier_id=env["supplier"],
        order_date=invoice_date, currency_code="XOF",
        lines=[{"product_id": env["semoule"], "uom_id": env["uom_ton"], "quantity_ordered": quantity, "unit_price": 0, "unit_price_currency": "XOF"}],
    ).value
    for method in ("validate_order", "approve_order", "place_order"):
        result = getattr(procurement, method)(tenant_id=TENANT, actor_id=env["actor"], order_id=po.id)
        assert isinstance(result, Ok), getattr(result, "message", "")

    line = procurement.list_lines(tenant_id=TENANT, purchase_order_id=po.id)[0]
    receipt = procurement.create_receipt(
        tenant_id=TENANT, actor_id=env["actor"], purchase_order_id=po.id, location_id=env["location"],
        currency_code="XOF", invoice_date=invoice_date,
        lines=[{"purchase_order_line_id": line.id, "quantity": quantity}],
        base_cost=base_cost,
    ).value
    confirmed = procurement.confirm_receipt(tenant_id=TENANT, actor_id=env["actor"], receipt_id=receipt.id, correlation_id=str(ULID()))
    assert isinstance(confirmed, Ok), getattr(confirmed, "message", "")


def _validate_a_day(db, env, of, *, report_date: datetime.date, semoule_qty: float, packets: int) -> None:
    daily = ProductionReportService(db).create_daily_report(
        tenant_id=TENANT, actor_id=env["actor"], of_id=of.id, report_date=report_date,
        equipment_id=env["equipment"], shift="morning",
        detail=DailyReportDetail(
            semolina_lines=(SemolinaLine(product_id=env["semoule"], quantity=semoule_qty, location_id=env["location"]),),
        ),
    ).value["report"]
    ProductionReportService(db).submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=daily.id)
    validated = ProductionReportService(db).validate_report(tenant_id=TENANT, actor_id=env["actor"], report_id=daily.id)
    assert isinstance(validated, Ok), getattr(validated, "message", "")

    cond = ConditionnementReportService(db).create_report(
        tenant_id=TENANT, actor_id=env["actor"], of_id=of.id, report_date=report_date,
        shift="morning", equipment_id=env["equipment"],
        detail=ConditionnementReportDetail(
            packets_counted=packets, packaging_location_id=env["location"], finished_goods_location_id=env["location"],
        ),
    ).value["report"]
    ProductionReportService(db).submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=cond.id)
    validated_cond = ProductionReportService(db).validate_report(tenant_id=TENANT, actor_id=env["actor"], report_id=cond.id)
    assert isinstance(validated_cond, Ok), getattr(validated_cond, "message", "")


def test_analytics_payload_current_period_matches_totals_and_never_includes_fixed_charges(db, env, of):
    _confirm_a_receipt(db, env, quantity=100, base_cost=55_000_000, invoice_date=datetime.date(2026, 8, 1))
    # Landed cost/tonne = 550,000 CFA/tonne.
    _validate_a_day(db, env, of, report_date=datetime.date(2026, 9, 10), semoule_qty=4, packets=7600)
    # 7600 * 500g (env's net_weight_grams) = 3.8 tonnes.

    payload = build_analytics_payload(db, tenant_id=TENANT, period="day", date="2026-09-10")

    assert payload["period_phrase"] == "la journée du 10 septembre 2026"
    assert "charge" not in payload  # fixed charges are export-only, see module docstring
    current = payload["current"]
    assert current["mp_cost"] == pytest.approx(4 * 550_000)
    assert current["packaging_cost"] in (None, 0)
    assert current["tonnage"] == pytest.approx(3.8)
    assert current["packets"] == 7600
    assert current["variable_cost"] == pytest.approx(4 * 550_000)
    assert current["cost_per_tonne"] == pytest.approx((4 * 550_000) / 3.8)
    assert {"category": "MP", "cost": pytest.approx(4 * 550_000)} in current["cost_breakdown"]

    # A day-mode request trends the trailing 30 days, always ending on the requested date.
    assert len(payload["trend"]) == 30
    assert payload["trend"][-1]["date_from"] == "2026-09-10"


def test_analytics_payload_variable_cost_is_none_not_zero_when_mp_is_unpriced(db, env, of):
    # No receipt ever confirmed for the semoule -- MaterialConsumptionService has no
    # landed cost to price the consumption against, so the MP row stays unpriced.
    _validate_a_day(db, env, of, report_date=datetime.date(2026, 9, 10), semoule_qty=4, packets=7600)

    current = build_analytics_payload(db, tenant_id=TENANT, period="day", date="2026-09-10")["current"]

    assert current["mp_cost"] is None
    # variable_cost/cost_per_tonne must stay unknown too, not silently fall back to
    # packaging's 0 and understate the real (unpriced) cost -- see _period_point.
    assert current["variable_cost"] is None
    assert current["cost_per_tonne"] is None
    assert current["tonnage"] == pytest.approx(3.8)


def test_analytics_payload_flags_cost_anomalies_from_purchase_history(db, env, of):
    _confirm_a_receipt(db, env, quantity=100, base_cost=55_000_000, invoice_date=datetime.date(2026, 7, 1))  # 550,000/t baseline
    _confirm_a_receipt(db, env, quantity=10, base_cost=50_000_000, invoice_date=datetime.date(2026, 8, 1))  # 5,000,000/t -- an outlier

    payload = build_analytics_payload(db, tenant_id=TENANT, period="month", date="2026-08-15")

    assert len(payload["anomalies"]) == 1
    anomaly = payload["anomalies"][0]
    assert anomaly["product_id"] == env["semoule"]
    assert anomaly["cost_per_unit_base"] == pytest.approx(5_000_000)
    assert anomaly["is_cost_anomaly"] is True
