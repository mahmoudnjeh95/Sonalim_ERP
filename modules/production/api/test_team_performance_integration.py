"""Integration tests for team-performance aggregation, against a real database.

The property under test: totals are bucketed by team and by calendar period, and
only validated reports count — the same validated-only rule every other
aggregate in this module follows.
"""
from __future__ import annotations

import datetime

import pytest
from ulid import ULID

from core.domain.result import Ok
from modules.production.api.production_report_service import ProductionReportService
from modules.production.api.service import WorkOrderService
from modules.production.api.team_performance_service import TeamPerformanceService
from modules.production.api.work_order_yield_service import WorkOrderYieldService
from modules.production.domain.production_report import DailyReportDetail, SemolinaLine
from modules.warehouse.api.service import StockService

TENANT = "integration-test-team-performance"


@pytest.fixture
def env(db):
    actor = str(ULID())
    uom, product, location, work_center = (str(ULID()) for _ in range(4))
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (actor, TENANT, f"{actor}@test.local"),
    )
    db.execute(
        "INSERT INTO core.uoms (id, tenant_id, code, name, category) VALUES (%s, %s, 'kg', 'Kilogram', 'weight')",
        (uom, TENANT),
    )
    db.execute(
        "INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, 'TP-PASTA', 'Test pasta', %s)",
        (product, TENANT, uom),
    )
    db.execute(
        "INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, 'TP-LOC', 'Test location')",
        (location, TENANT),
    )
    db.execute(
        "INSERT INTO production.work_centers (id, tenant_id, code, name) VALUES (%s, %s, 'TP-WC', 'Test line')",
        (work_center, TENANT),
    )
    StockService(db).receive_stock(
        tenant_id=TENANT, product_id=product, location_id=location, quantity=100_000,
        correlation_id=str(ULID()), reference="test-seed", actor_id=actor,
    )
    return {"actor": actor, "product": product, "location": location, "work_center": work_center}


def _validated_report(
    db, env, *, team, report_date, semolina_quantity, production_minutes, downtime_minutes,
    downtime_reason=None, water_percentage=0, semolina_flow_rate=0,
):
    orders = WorkOrderService(db)
    created = orders.create_work_order(
        tenant_id=TENANT, actor_id=env["actor"], product_id=env["product"],
        planned_quantity=1000, work_center_id=env["work_center"], start_date=report_date,
    )
    assert isinstance(created, Ok), getattr(created, "message", "")
    order = created.value
    assert isinstance(orders.start_work_order(tenant_id=TENANT, actor_id=env["actor"], work_order_id=order.id), Ok)

    reports = ProductionReportService(db)
    detail = DailyReportDetail(
        semolina_lines=(SemolinaLine(product_id=env["product"], quantity=semolina_quantity, location_id=env["location"]),),
        raw_material_location_id=env["location"],
        production_minutes=production_minutes,
        downtime_minutes=downtime_minutes,
        downtime_reason=downtime_reason or ("test downtime" if downtime_minutes else None),
        water_percentage=water_percentage,
        semolina_flow_rate=semolina_flow_rate,
    )
    created_report = reports.create_daily_report(
        tenant_id=TENANT, actor_id=env["actor"], of_id=order.id, report_date=report_date,
        team=team, shift="morning", detail=detail,
    )
    assert isinstance(created_report, Ok), getattr(created_report, "message", "")
    report_id = created_report.value["report"].id
    assert isinstance(reports.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report_id), Ok)
    validated = reports.validate_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report_id, correlation_id=str(ULID()))
    assert isinstance(validated, Ok), getattr(validated, "message", "")
    return order.id


def test_totals_are_bucketed_by_team_and_period(db, env):
    # Same week, two teams: their totals must not bleed into each other.
    _validated_report(
        db, env, team="A", report_date=datetime.date(2026, 9, 1),
        semolina_quantity=500, production_minutes=400, downtime_minutes=20,
    )
    _validated_report(
        db, env, team="B", report_date=datetime.date(2026, 9, 2),
        semolina_quantity=300, production_minutes=350, downtime_minutes=50,
    )
    # A later week for team A, to prove periods don't collapse into one bucket.
    _validated_report(
        db, env, team="A", report_date=datetime.date(2026, 9, 10),
        semolina_quantity=200, production_minutes=200, downtime_minutes=10,
    )

    rows = TeamPerformanceService(db).list_team_performance(tenant_id=TENANT, grain="week")
    by_key = {(r["team"], r["period"]): r for r in rows}

    week1_a = next(r for (team, _), r in by_key.items() if team == "A" and r["semolina_quantity"] == 500)
    assert week1_a["production_minutes"] == 400
    assert week1_a["downtime_minutes"] == 20
    assert week1_a["report_count"] == 1

    week1_b = next(r for (team, _), r in by_key.items() if team == "B")
    assert week1_b["semolina_quantity"] == 300

    week2_a = next(r for (team, _), r in by_key.items() if team == "A" and r["semolina_quantity"] == 200)
    assert week1_a["period"] != week2_a["period"]


def test_draft_reports_are_excluded(db, env):
    orders = WorkOrderService(db)
    created = orders.create_work_order(
        tenant_id=TENANT, actor_id=env["actor"], product_id=env["product"],
        planned_quantity=1000, work_center_id=env["work_center"], start_date=datetime.date(2026, 9, 15),
    )
    order = created.value
    assert isinstance(orders.start_work_order(tenant_id=TENANT, actor_id=env["actor"], work_order_id=order.id), Ok)
    ProductionReportService(db).create_daily_report(
        tenant_id=TENANT, actor_id=env["actor"], of_id=order.id, report_date=datetime.date(2026, 9, 15),
        team="C", shift="morning",
        detail=DailyReportDetail(
            semolina_lines=(SemolinaLine(product_id=env["product"], quantity=999, location_id=env["location"]),),
            raw_material_location_id=env["location"],
        ),
    )

    rows = TeamPerformanceService(db).list_team_performance(tenant_id=TENANT, grain="week")
    assert not any(r["team"] == "C" for r in rows)


def test_invalid_grain_is_rejected(db):
    with pytest.raises(ValueError):
        TeamPerformanceService(db).list_team_performance(tenant_id=TENANT, grain="fortnight")


def test_downtime_reasons_are_summed_across_reports(db, env):
    _validated_report(
        db, env, team="A", report_date=datetime.date(2026, 9, 1),
        semolina_quantity=100, production_minutes=400, downtime_minutes=20, downtime_reason="mixer jam",
    )
    _validated_report(
        db, env, team="B", report_date=datetime.date(2026, 9, 2),
        semolina_quantity=100, production_minutes=400, downtime_minutes=15, downtime_reason="mixer jam",
    )
    _validated_report(
        db, env, team="A", report_date=datetime.date(2026, 9, 3),
        semolina_quantity=100, production_minutes=400, downtime_minutes=5, downtime_reason="power cut",
    )
    # No downtime at all: must not show up as a reason of its own.
    _validated_report(
        db, env, team="A", report_date=datetime.date(2026, 9, 4),
        semolina_quantity=100, production_minutes=400, downtime_minutes=0,
    )

    rows = {r["reason"]: r for r in TeamPerformanceService(db).list_downtime_reasons(tenant_id=TENANT)}
    assert rows["mixer jam"]["minutes"] == 35
    assert rows["mixer jam"]["report_count"] == 2
    assert rows["power cut"]["minutes"] == 5
    # Worst offender first.
    ordered = TeamPerformanceService(db).list_downtime_reasons(tenant_id=TENANT)
    assert ordered[0]["reason"] == "mixer jam"


def test_recipe_correlation_pairs_shift_inputs_with_the_ofs_yield(db, env):
    of_id = _validated_report(
        db, env, team="A", report_date=datetime.date(2026, 9, 1),
        semolina_quantity=1000, production_minutes=400, downtime_minutes=0,
        water_percentage=32, semolina_flow_rate=4.5,
    )

    rows = WorkOrderYieldService(db).list_recipe_correlation(tenant_id=TENANT)
    assert len(rows) == 1
    row = rows[0]
    assert row["of_id"] == of_id
    assert row["water_percentage"] == 32
    assert row["semolina_flow_rate"] == 4.5
    assert row["yield_ratio"] is not None


def test_recipe_correlation_skips_shifts_with_no_dosage_recorded(db, env):
    _validated_report(
        db, env, team="A", report_date=datetime.date(2026, 9, 1),
        semolina_quantity=1000, production_minutes=400, downtime_minutes=0,
    )
    rows = WorkOrderYieldService(db).list_recipe_correlation(tenant_id=TENANT)
    assert rows == []
