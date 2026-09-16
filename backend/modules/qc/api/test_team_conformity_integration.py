"""Integration tests for team-conformity aggregation, against a real database.

Same validated-only rule as `get_conformity_summary`, just grouped by team and
a calendar bucket instead of filtered to one OF.
"""
from __future__ import annotations

import datetime

import pytest
from ulid import ULID

from core.domain.result import Ok
from modules.production.api.conditionnement_service import ConditionnementReportService
from modules.production.api.service import WorkOrderService
from modules.production.domain.production_report import ConditionnementReportDetail
from modules.qc.api.quality_service import QualityReportService
from modules.qc.domain.quality import QualityReportDetail

TENANT = "integration-test-team-conformity"


@pytest.fixture
def env(db):
    actor = str(ULID())
    uom, product, work_center = (str(ULID()) for _ in range(3))
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (actor, TENANT, f"{actor}@test.local"),
    )
    db.execute(
        "INSERT INTO core.uoms (id, tenant_id, code, name, category) VALUES (%s, %s, 'kg', 'Kilogram', 'weight')",
        (uom, TENANT),
    )
    db.execute(
        "INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, 'TC-PASTA', 'Test pasta', %s)",
        (product, TENANT, uom),
    )
    db.execute(
        "INSERT INTO production.work_centers (id, tenant_id, code, name) VALUES (%s, %s, 'TC-WC', 'Test line')",
        (work_center, TENANT),
    )
    return {"actor": actor, "product": product, "work_center": work_center}


@pytest.fixture
def of(db, env):
    created = WorkOrderService(db).create_work_order(
        tenant_id=TENANT, actor_id=env["actor"], product_id=env["product"],
        planned_quantity=1000, work_center_id=env["work_center"],
    )
    assert isinstance(created, Ok), getattr(created, "message", "")
    return created.value


def _validated_quality_report(db, env, of, *, team, report_date, conforming, non_conforming):
    """`team` is set on the conditionnement report, exactly as a real packaging
    run would carry it -- the quality report only ever derives its team from
    the run it inspects, it never accepts one directly."""
    packing = ConditionnementReportService(db).create_report(
        tenant_id=TENANT, actor_id=env["actor"], of_id=of.id, report_date=report_date,
        team=team, shift="morning",
        detail=ConditionnementReportDetail(),
    )
    assert isinstance(packing, Ok), getattr(packing, "message", "")

    service = QualityReportService(db)
    created = service.create_report(
        tenant_id=TENANT, actor_id=env["actor"], conditionnement_report_id=packing.value["report"].id,
        detail=QualityReportDetail(
            conforming_cartons=conforming,
            non_conforming_cartons=non_conforming,
            defect_details="test defect" if non_conforming else None,
        ),
    )
    assert isinstance(created, Ok), getattr(created, "message", "")
    report_id = created.value["report"].id
    assert isinstance(service.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report_id), Ok)
    validated = service.validate_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report_id, correlation_id=str(ULID()))
    assert isinstance(validated, Ok), getattr(validated, "message", "")


def test_conformity_is_bucketed_by_team_and_period(db, env, of):
    _validated_quality_report(db, env, of, team="A", report_date=datetime.date(2026, 9, 1), conforming=90, non_conforming=10)
    _validated_quality_report(db, env, of, team="B", report_date=datetime.date(2026, 9, 2), conforming=50, non_conforming=50)
    _validated_quality_report(db, env, of, team="A", report_date=datetime.date(2026, 9, 10), conforming=100, non_conforming=0)

    rows = QualityReportService(db).team_conformity(tenant_id=TENANT, grain="week")

    week1_a = next(r for r in rows if r["team"] == "A" and r["conforming_cartons"] == 90)
    assert week1_a["non_conforming_cartons"] == 10
    assert week1_a["report_count"] == 1

    week1_b = next(r for r in rows if r["team"] == "B")
    assert week1_b["conforming_cartons"] == 50 and week1_b["non_conforming_cartons"] == 50

    week2_a = next(r for r in rows if r["team"] == "A" and r["conforming_cartons"] == 100)
    assert week1_a["period"] != week2_a["period"]


def test_draft_quality_reports_are_excluded(db, env, of):
    packing = ConditionnementReportService(db).create_report(
        tenant_id=TENANT, actor_id=env["actor"], of_id=of.id, report_date=datetime.date(2026, 9, 15),
        team="Z", shift="morning",
        detail=ConditionnementReportDetail(),
    )
    assert isinstance(packing, Ok), getattr(packing, "message", "")
    QualityReportService(db).create_report(
        tenant_id=TENANT, actor_id=env["actor"], conditionnement_report_id=packing.value["report"].id,
        detail=QualityReportDetail(conforming_cartons=5, non_conforming_cartons=5),
    )
    rows = QualityReportService(db).team_conformity(tenant_id=TENANT, grain="week")
    assert not any(r["team"] == "Z" for r in rows)


def test_invalid_grain_is_rejected(db):
    with pytest.raises(ValueError):
        QualityReportService(db).team_conformity(tenant_id=TENANT, grain="fortnight")


def _validated_quality_report_with_indices(
    db, env, of, *, report_date, pre_dryer_index=None, humidity_percentage=None,
    cooling_index=None, pf_index=None, sumo_index=None,
):
    packing = ConditionnementReportService(db).create_report(
        tenant_id=TENANT, actor_id=env["actor"], of_id=of.id, report_date=report_date,
        team="A", shift="morning",
        detail=ConditionnementReportDetail(),
    )
    assert isinstance(packing, Ok), getattr(packing, "message", "")

    service = QualityReportService(db)
    created = service.create_report(
        tenant_id=TENANT, actor_id=env["actor"], conditionnement_report_id=packing.value["report"].id,
        detail=QualityReportDetail(
            pre_dryer_index=pre_dryer_index, humidity_percentage=humidity_percentage,
            cooling_index=cooling_index, pf_index=pf_index, sumo_index=sumo_index,
            conforming_cartons=1, non_conforming_cartons=0,
        ),
    )
    assert isinstance(created, Ok), getattr(created, "message", "")
    report_id = created.value["report"].id
    assert isinstance(service.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report_id), Ok)
    validated = service.validate_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report_id, correlation_id=str(ULID()))
    assert isinstance(validated, Ok), getattr(validated, "message", "")


def test_index_trend_averages_within_a_period_and_ignores_nulls(db, env, of):
    _validated_quality_report_with_indices(
        db, env, of, report_date=datetime.date(2026, 9, 1),
        pre_dryer_index=10, humidity_percentage=12.5, cooling_index=None, pf_index=None, sumo_index=None,
    )
    _validated_quality_report_with_indices(
        db, env, of, report_date=datetime.date(2026, 9, 2),
        pre_dryer_index=20, humidity_percentage=None, cooling_index=5, pf_index=None, sumo_index=None,
    )
    # A different week -- must land in its own bucket.
    _validated_quality_report_with_indices(
        db, env, of, report_date=datetime.date(2026, 9, 20),
        pre_dryer_index=100, humidity_percentage=None, cooling_index=None, pf_index=None, sumo_index=None,
    )

    rows = QualityReportService(db).index_trend(tenant_id=TENANT, grain="week")

    week1 = next(r for r in rows if r["report_count"] == 2)
    assert week1["pre_dryer_index"] == 15, "average of 10 and 20"
    assert week1["humidity_percentage"] == 12.5, "the single non-null value, not dragged toward zero by the other report's null"
    assert week1["cooling_index"] == 5
    assert week1["pf_index"] is None, "no report in the period recorded it"

    week2 = next(r for r in rows if r["report_count"] == 1)
    assert week2["pre_dryer_index"] == 100


def test_index_trend_invalid_grain_is_rejected(db):
    with pytest.raises(ValueError):
        QualityReportService(db).index_trend(tenant_id=TENANT, grain="fortnight")
