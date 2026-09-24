"""Integration tests for conformity aggregation, against a real database.

`get_conformity_summary` sums one OF's conformity lines over its validated
quality reports; `team_conformity` applies the same validated-only rule,
grouped by team and a calendar bucket instead of filtered to one OF.
"""
from __future__ import annotations

import datetime

import pytest
from ulid import ULID

from core.domain.result import Ok
from modules.production.api.service import WorkOrderService
from modules.production.api.shift_report_service import ShiftReportService
from modules.production.api.shift_validation_service import ShiftValidationService
from modules.production.domain.shift_report import SECTION_KEYS
from modules.qc.api.quality_service import QualityReportService

TENANT = "integration-test-team-conformity"


def _ok(result):
    assert isinstance(result, Ok), getattr(result, "message", result)
    return result.value


@pytest.fixture
def env(db):
    actor = str(ULID())
    uom, product, location, work_center, equipment = (str(ULID()) for _ in range(5))
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (actor, TENANT, f"{actor}@test.local"),
    )
    db.execute(
        "INSERT INTO core.uoms (id, tenant_id, code, name, category) VALUES (%s, %s, 'kg', 'Kilogram', 'weight')",
        (uom, TENANT),
    )
    db.execute(
        "INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, 'TC-FG', 'Finished goods')",
        (location, TENANT),
    )
    # A default location, because validating the shift posts the packed pasta there.
    db.execute(
        "INSERT INTO core.products (id, tenant_id, sku, name, uom_id, default_location_id) "
        "VALUES (%s, %s, 'TC-PASTA', 'Test pasta', %s, %s)",
        (product, TENANT, uom, location),
    )
    db.execute(
        "INSERT INTO production.work_centers (id, tenant_id, code, name) VALUES (%s, %s, 'TC-WC', 'Test line')",
        (work_center, TENANT),
    )
    db.execute(
        "INSERT INTO maintenance.equipment (id, tenant_id, work_center_id, code, name) "
        "VALUES (%s, %s, %s, 'TC-EQ', 'Test machine')",
        (equipment, TENANT, work_center),
    )
    return {"actor": actor, "product": product, "work_center": work_center, "equipment": equipment}


@pytest.fixture
def of(db, env):
    created = WorkOrderService(db).create_work_order(
        tenant_id=TENANT, actor_id=env["actor"], product_id=env["product"],
        planned_quantity=1000, work_center_id=env["work_center"],
    )
    assert isinstance(created, Ok), getattr(created, "message", "")
    return created.value


def _validated_shift(db, env, packing_rows, *, report_date, team=None) -> str:
    """A validated shift whose packing section holds `packing_rows`.

    `team` is set on the shift report, exactly as a real shift would carry it --
    the quality report only ever derives its team from the shift it inspects.
    """
    service = ShiftReportService(db)
    shift_id = _ok(service.open_shift(
        tenant_id=TENANT, actor_id=env["actor"], work_center_id=env["work_center"],
        report_date=report_date, shift="morning", team=team,
    ))["id"]
    _ok(service.save_section(
        tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key="packing",
        payload={"rows": packing_rows},
    ))
    for key in SECTION_KEYS:
        if key == "packing":
            _ok(service.submit_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key))
        else:
            _ok(service.declare_nothing(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key))
    _ok(ShiftValidationService(db).validate_shift(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id))
    return shift_id


def _packing_row(env, of_id, finished=500, packets=100):
    return {
        "of_id": of_id, "product_id": env["product"], "equipment_id": env["equipment"],
        "finished_product_quantity": finished, "packets_counted": packets,
    }


def _quality_report(db, env, of, *, team, report_date, conforming, non_conforming, validate=True) -> str:
    shift_id = _validated_shift(db, env, [_packing_row(env, of.id)], report_date=report_date, team=team)
    service = QualityReportService(db)
    created = _ok(service.create_report(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id))
    report_id = created["report"].id
    _ok(service.update_draft(
        tenant_id=TENANT, actor_id=env["actor"], report_id=report_id,
        lines=[{
            "shift_packing_row_id": created["lines"][0].shift_packing_row_id,
            "conforming_cartons": conforming,
            "non_conforming_cartons": non_conforming,
            "defect_details": "test defect" if non_conforming else None,
        }],
    ))
    if validate:
        _ok(service.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report_id))
        _ok(service.validate_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report_id, correlation_id=str(ULID())))
    return report_id


# --- per-OF conformity summary ------------------------------------------------


def test_conformity_summary_sums_across_every_line_of_every_of(db, env, of):
    """A shift can pack two OFs; get_conformity_summary(of_id) only counts that OF's lines."""
    other_of = _ok(WorkOrderService(db).create_work_order(
        tenant_id=TENANT, actor_id=env["actor"], product_id=env["product"], planned_quantity=500,
        work_center_id=env["work_center"],
    ))
    shift_id = _validated_shift(
        db, env,
        [_packing_row(env, of.id, finished=500, packets=100), _packing_row(env, other_of.id, finished=300, packets=60)],
        report_date=datetime.date(2026, 9, 2),
    )

    qc = QualityReportService(db)
    report = _ok(qc.create_report(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id))["report"]
    lines = qc._load_lines(tenant_id=TENANT, report_id=report.id)
    of_line = next(l for l in lines if l.of_id == of.id)
    other_line = next(l for l in lines if l.of_id == other_of.id)
    _ok(qc.update_draft(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id, lines=[
        {"shift_packing_row_id": of_line.shift_packing_row_id, "conforming_cartons": 8, "non_conforming_cartons": 0},
        {"shift_packing_row_id": other_line.shift_packing_row_id, "conforming_cartons": 5, "non_conforming_cartons": 0},
    ]))
    _ok(qc.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id))
    _ok(qc.validate_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id, correlation_id=str(ULID())))

    summary = qc.get_conformity_summary(tenant_id=TENANT, of_id=of.id)
    assert summary["conforming_cartons"] == 8
    assert summary["validated_report_count"] == 1

    other_summary = qc.get_conformity_summary(tenant_id=TENANT, of_id=other_of.id)
    assert other_summary["conforming_cartons"] == 5


def test_conformity_summary_sums_several_validated_reports_and_skips_drafts(db, env, of):
    _quality_report(db, env, of, team="A", report_date=datetime.date(2026, 9, 1), conforming=90, non_conforming=10)
    _quality_report(db, env, of, team="A", report_date=datetime.date(2026, 9, 3), conforming=40, non_conforming=0)
    _quality_report(
        db, env, of, team="A", report_date=datetime.date(2026, 9, 4), conforming=7, non_conforming=7, validate=False
    )

    summary = QualityReportService(db).get_conformity_summary(tenant_id=TENANT, of_id=of.id)
    assert summary["validated_report_count"] == 2
    assert summary["conforming_cartons"] == 130
    assert summary["non_conforming_cartons"] == 10
    assert summary["conformity_rate"] == 130 / 140
    assert [p["report_date"] for p in summary["pending_nc_reports"]] == ["2026-09-01"]
    assert summary["pending_nc_reports"][0]["non_conforming_cartons"] == 10.0


def test_conformity_summary_of_an_uninspected_of_is_empty(db, env, of):
    summary = QualityReportService(db).get_conformity_summary(tenant_id=TENANT, of_id=of.id)
    assert summary == {
        "validated_report_count": 0,
        "conforming_cartons": 0.0,
        "non_conforming_cartons": 0.0,
        "conformity_rate": None,
        "pending_nc_reports": [],
    }


# --- team conformity ------------------------------------------------------------


def test_conformity_is_bucketed_by_team_and_period(db, env, of):
    _quality_report(db, env, of, team="A", report_date=datetime.date(2026, 9, 1), conforming=90, non_conforming=10)
    _quality_report(db, env, of, team="B", report_date=datetime.date(2026, 9, 2), conforming=50, non_conforming=50)
    _quality_report(db, env, of, team="A", report_date=datetime.date(2026, 9, 10), conforming=100, non_conforming=0)

    rows = QualityReportService(db).team_conformity(tenant_id=TENANT, grain="week")

    week1_a = next(r for r in rows if r["team"] == "A" and r["conforming_cartons"] == 90)
    assert week1_a["non_conforming_cartons"] == 10
    assert week1_a["report_count"] == 1

    week1_b = next(r for r in rows if r["team"] == "B")
    assert week1_b["conforming_cartons"] == 50 and week1_b["non_conforming_cartons"] == 50

    week2_a = next(r for r in rows if r["team"] == "A" and r["conforming_cartons"] == 100)
    assert week1_a["period"] != week2_a["period"]


def test_a_report_with_several_lines_counts_once_per_bucket(db, env, of):
    other_of = _ok(WorkOrderService(db).create_work_order(
        tenant_id=TENANT, actor_id=env["actor"], product_id=env["product"], planned_quantity=500,
        work_center_id=env["work_center"],
    ))
    shift_id = _validated_shift(
        db, env, [_packing_row(env, of.id), _packing_row(env, other_of.id, finished=300, packets=60)],
        report_date=datetime.date(2026, 9, 2), team="C",
    )
    qc = QualityReportService(db)
    created = _ok(qc.create_report(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id))
    report_id = created["report"].id
    _ok(qc.update_draft(tenant_id=TENANT, actor_id=env["actor"], report_id=report_id, lines=[
        {"shift_packing_row_id": line.shift_packing_row_id, "conforming_cartons": 10, "non_conforming_cartons": 0}
        for line in created["lines"]
    ]))
    _ok(qc.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report_id))
    _ok(qc.validate_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report_id, correlation_id=str(ULID())))

    rows = [r for r in qc.team_conformity(tenant_id=TENANT, grain="month") if r["team"] == "C"]
    assert len(rows) == 1
    assert rows[0]["report_count"] == 1
    assert rows[0]["conforming_cartons"] == 20


def test_draft_quality_reports_are_excluded(db, env, of):
    _quality_report(
        db, env, of, team="Z", report_date=datetime.date(2026, 9, 15), conforming=5, non_conforming=5, validate=False
    )
    rows = QualityReportService(db).team_conformity(tenant_id=TENANT, grain="week")
    assert not any(r["team"] == "Z" for r in rows)


def test_invalid_grain_is_rejected(db):
    with pytest.raises(ValueError):
        QualityReportService(db).team_conformity(tenant_id=TENANT, grain="fortnight")


def test_index_trend_is_gone(db):
    """The five process indices were dropped; there is nothing left to trend."""
    assert not hasattr(QualityReportService(db), "index_trend")
