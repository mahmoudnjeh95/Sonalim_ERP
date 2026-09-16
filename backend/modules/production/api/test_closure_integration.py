"""Integration tests for termination and closure (Phase 7).

The distinction under test: **unfinished production work blocks closure, quality
work never does.** The 40-day follow-up deliberately outlives production, so a
check that held an order open until quality finished would keep every OF open for
weeks and make the closed state meaningless — and a non-conformity is usually
found after the run is over.
"""
from __future__ import annotations

import datetime

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from modules.production.api.conditionnement_service import ConditionnementReportService
from modules.production.api.production_report_service import ProductionReportService
from modules.production.api.service import WorkOrderService
from modules.production.domain.production_report import ConditionnementReportDetail, DailyReportDetail, SemolinaLine
from modules.qc.api.non_conformity_service import NonConformityService
from modules.qc.api.quality_service import QualityReportService
from modules.qc.domain.quality import QualityReportDetail
from modules.warehouse.api.service import StockService

TENANT = "integration-test-closure"


@pytest.fixture
def env(db):
    actor = str(ULID())
    uom, product, location, quarantine, work_center, equipment = (str(ULID()) for _ in range(6))
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (actor, TENANT, f"{actor}@test.local"),
    )
    db.execute(
        "INSERT INTO core.uoms (id, tenant_id, code, name, category) VALUES (%s, %s, 'kg', 'Kilogram', 'weight')",
        (uom, TENANT),
    )
    db.execute(
        "INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, 'CLOSE-P', 'Pasta', %s)",
        (product, TENANT, uom),
    )
    db.execute(
        "INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, 'FG', 'Finished goods')",
        (location, TENANT),
    )
    db.execute(
        "INSERT INTO warehouse.locations (id, tenant_id, code, name, is_blocked) "
        "VALUES (%s, %s, 'QUAR', 'Quarantine', TRUE)",
        (quarantine, TENANT),
    )
    db.execute(
        "INSERT INTO production.work_centers (id, tenant_id, code, name) VALUES (%s, %s, 'CLOSE-WC', 'Line')",
        (work_center, TENANT),
    )
    db.execute(
        "INSERT INTO maintenance.equipment (id, tenant_id, work_center_id, code, name) VALUES (%s, %s, %s, 'CLOSE-EQ', 'Test machine')",
        (equipment, TENANT, work_center),
    )
    StockService(db).receive_stock(
        tenant_id=TENANT, product_id=product, location_id=location, quantity=100_000,
        correlation_id=str(ULID()), reference="seed", actor_id=actor,
    )
    return {
        "actor": actor,
        "product": product,
        "location": location,
        "quarantine": quarantine,
        "work_center": work_center,
        "equipment": equipment,
    }


@pytest.fixture
def of(db, env):
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
    service.start_work_order(tenant_id=TENANT, actor_id=env["actor"], work_order_id=created.value.id)
    return created.value


def _report(db, env, of, *, date, validate=True, submit=True, **detail):
    semolina_lines = detail.pop("semolina_lines", None)
    if semolina_lines is None:
        semolina_lines = (
            SemolinaLine(
                product_id=detail.pop("semolina_product_id", env["product"]),
                quantity=detail.pop("semolina_quantity", 1000),
                location_id=env["location"],
            ),
        )
    detail["semolina_lines"] = semolina_lines
    detail.setdefault("raw_material_location_id", env["location"])
    service = ProductionReportService(db)
    created = service.create_daily_report(
        tenant_id=TENANT, actor_id=env["actor"], of_id=of.id, report_date=date,
        equipment_id=env["equipment"],
        detail=DailyReportDetail(**detail),
    )
    assert isinstance(created, Ok), getattr(created, "message", "")
    report = created.value["report"]
    if submit:
        service.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)
    if validate:
        service.validate_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)
    return report


def _check(db, of) -> dict:
    result = WorkOrderService(db).pre_close_check(tenant_id=TENANT, work_order_id=of.id)
    assert isinstance(result, Ok), getattr(result, "message", "")
    return result.value


def _codes(findings: list[dict]) -> set[str]:
    return {f["code"] for f in findings}


# --- what blocks -------------------------------------------------------------


def test_a_tidy_of_can_close(db, env, of):
    _report(db, env, of, date=datetime.date(2026, 9, 1))
    check = _check(db, of)
    assert check["blockers"] == []
    assert check["can_close"] is True

    closed = WorkOrderService(db).close_work_order(
        tenant_id=TENANT, actor_id=env["actor"], work_order_id=of.id, correlation_id=str(ULID())
    )
    assert isinstance(closed, Ok), getattr(closed, "message", "")


def test_a_draft_report_blocks_closure(db, env, of):
    _report(db, env, of, date=datetime.date(2026, 9, 1))
    _report(db, env, of, date=datetime.date(2026, 9, 2), submit=False, validate=False)

    check = _check(db, of)
    assert "DRAFT_REPORTS" in _codes(check["blockers"])
    assert check["can_close"] is False

    refused = WorkOrderService(db).close_work_order(
        tenant_id=TENANT, actor_id=env["actor"], work_order_id=of.id, correlation_id=str(ULID())
    )
    assert isinstance(refused, Err)
    assert refused.code == "OF_HAS_BLOCKERS"


def test_a_report_waiting_at_the_desk_blocks_closure(db, env, of):
    """Its figures have not posted stock yet — closing over it would strand them."""
    _report(db, env, of, date=datetime.date(2026, 9, 1), validate=False)

    check = _check(db, of)
    assert "UNVALIDATED_REPORTS" in _codes(check["blockers"])


def test_a_rejected_report_blocks_closure(db, env, of):
    service = ProductionReportService(db)
    rejected = _report(db, env, of, date=datetime.date(2026, 9, 1), validate=False)
    service.reject_report(
        tenant_id=TENANT, actor_id=env["actor"], report_id=rejected.id, reason="figures do not add up"
    )

    check = _check(db, of)
    assert "REJECTED_REPORTS" in _codes(check["blockers"])


def test_revising_and_validating_clears_the_blocker(db, env, of):
    service = ProductionReportService(db)
    report = _report(db, env, of, date=datetime.date(2026, 9, 1), validate=False)
    service.reject_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id, reason="wrong")
    service.revise_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)
    service.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)
    service.validate_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)

    assert _check(db, of)["blockers"] == []


# --- what only warns ---------------------------------------------------------


def test_open_quality_follow_up_warns_but_never_blocks(db, env, of):
    """The 40-day window outlives production by design."""
    _report(db, env, of, date=datetime.date(2026, 9, 1))

    packing = ConditionnementReportService(db).create_report(
        tenant_id=TENANT, actor_id=env["actor"], of_id=of.id, report_date=datetime.date(2026, 9, 1),
        equipment_id=env["equipment"],
        detail=ConditionnementReportDetail(),
    )
    assert isinstance(packing, Ok), getattr(packing, "message", "")
    packing_report_id = packing.value["report"].id
    # Submitted and validated immediately -- a draft packing report would itself
    # block closure, and that is not what this test is about.
    reports = ProductionReportService(db)
    assert isinstance(
        reports.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=packing_report_id), Ok
    )
    assert isinstance(
        reports.validate_report(tenant_id=TENANT, actor_id=env["actor"], report_id=packing_report_id), Ok
    )

    quality = QualityReportService(db)
    created = quality.create_report(
        tenant_id=TENANT, actor_id=env["actor"], conditionnement_report_id=packing_report_id,
        detail=QualityReportDetail(conforming_cartons=100),
    )
    report_id = created.value["report"].id
    quality.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report_id)
    quality.validate_report(
        tenant_id=TENANT, actor_id=env["actor"], report_id=report_id, correlation_id=str(ULID())
    )

    check = _check(db, of)
    assert "OPEN_QUALITY_FOLLOW_UPS" in _codes(check["warnings"])
    assert check["blockers"] == []
    assert check["can_close"] is True

    closed = WorkOrderService(db).close_work_order(
        tenant_id=TENANT, actor_id=env["actor"], work_order_id=of.id, correlation_id=str(ULID())
    )
    assert isinstance(closed, Ok), getattr(closed, "message", "")


def test_an_open_non_conformity_warns_but_never_blocks(db, env, of):
    _report(db, env, of, date=datetime.date(2026, 9, 1))
    NonConformityService(db).raise_non_conformity(
        tenant_id=TENANT,
        actor_id=env["actor"],
        of_id=of.id,
        product_id=env["product"],
        quantity=10,
        source_location_id=env["location"],
        quarantine_location_id=env["quarantine"],
        defect_type="bad seal",
        correlation_id=str(ULID()),
    )

    check = _check(db, of)
    assert "OPEN_NON_CONFORMITIES" in _codes(check["warnings"])
    assert check["blockers"] == []


def test_an_of_with_nothing_validated_is_warned_about(db, env, of):
    check = _check(db, of)
    assert "NO_VALIDATED_REPORTS" in _codes(check["warnings"])
    assert check["blockers"] == [], "an empty order is odd, not unfinished"
    assert check["can_close"] is True


def test_a_missing_start_date_is_warned_about(db, env):
    service = WorkOrderService(db)
    created = service.create_work_order(
        tenant_id=TENANT,
        actor_id=env["actor"],
        product_id=env["product"],
        planned_quantity=500,
        work_center_id=env["work_center"],
    )
    service.start_work_order(tenant_id=TENANT, actor_id=env["actor"], work_order_id=created.value.id)

    result = service.pre_close_check(tenant_id=TENANT, work_order_id=created.value.id)
    assert "MISSING_START_DATE" in _codes(result.value["warnings"])


# --- the override ------------------------------------------------------------


def test_closing_over_blockers_needs_a_reason(db, env, of):
    _report(db, env, of, date=datetime.date(2026, 9, 1), submit=False, validate=False)
    service = WorkOrderService(db)

    without = service.close_work_order(
        tenant_id=TENANT, actor_id=env["actor"], work_order_id=of.id, correlation_id=str(ULID()), force=True
    )
    assert isinstance(without, Err)
    assert without.code == "MISSING_REASON"

    forced = service.close_work_order(
        tenant_id=TENANT,
        actor_id=env["actor"],
        work_order_id=of.id,
        correlation_id=str(ULID()),
        force=True,
        force_reason="shift never finished the draft; line decommissioned",
    )
    assert isinstance(forced, Ok), getattr(forced, "message", "")
    assert forced.value.status == "closed"


def test_the_override_is_audited_with_what_it_overrode(db, env, of):
    _report(db, env, of, date=datetime.date(2026, 9, 1), submit=False, validate=False)
    WorkOrderService(db).close_work_order(
        tenant_id=TENANT,
        actor_id=env["actor"],
        work_order_id=of.id,
        correlation_id=str(ULID()),
        force=True,
        force_reason="line decommissioned",
    )

    payload = db.execute(
        """
        SELECT payload FROM core.audit_log
        WHERE tenant_id = %s AND entity_id = %s AND action = 'work_order.closed_over_blockers'
        """,
        (TENANT, of.id),
    ).fetchone()
    assert payload is not None, "closing over blockers must leave a trail"
    assert payload[0]["reason"] == "line decommissioned"
    assert "DRAFT_REPORTS" in {b["code"] for b in payload[0]["blockers"]}


# --- closure stays archival --------------------------------------------------


def test_closure_changes_nothing_but_the_closure_fields(db, env, of):
    _report(db, env, of, date=datetime.date(2026, 9, 1))
    before_reports = db.execute(
        "SELECT count(*) FROM production.production_reports WHERE of_id = %s", (of.id,)
    ).fetchone()[0]
    before_moves = db.execute("SELECT count(*) FROM warehouse.stock_moves").fetchone()[0]

    closed = WorkOrderService(db).close_work_order(
        tenant_id=TENANT, actor_id=env["actor"], work_order_id=of.id, correlation_id=str(ULID())
    )
    assert isinstance(closed, Ok)
    assert closed.value.closed_at is not None
    assert closed.value.closed_by == env["actor"]

    assert db.execute(
        "SELECT count(*) FROM production.production_reports WHERE of_id = %s", (of.id,)
    ).fetchone()[0] == before_reports
    assert db.execute("SELECT count(*) FROM warehouse.stock_moves").fetchone()[0] == before_moves


def test_a_closed_of_still_accepts_quality_work(db, env, of):
    """The failure mode the whole design guards against."""
    _report(db, env, of, date=datetime.date(2026, 9, 1))
    WorkOrderService(db).close_work_order(
        tenant_id=TENANT, actor_id=env["actor"], work_order_id=of.id, correlation_id=str(ULID())
    )

    raised = NonConformityService(db).raise_non_conformity(
        tenant_id=TENANT,
        actor_id=env["actor"],
        of_id=of.id,
        product_id=env["product"],
        quantity=10,
        source_location_id=env["location"],
        quarantine_location_id=env["quarantine"],
        defect_type="found in the warehouse a week later",
        correlation_id=str(ULID()),
    )
    assert isinstance(raised, Ok), getattr(raised, "message", "")


def test_a_closed_of_cannot_be_closed_again(db, env, of):
    _report(db, env, of, date=datetime.date(2026, 9, 1))
    service = WorkOrderService(db)
    service.close_work_order(
        tenant_id=TENANT, actor_id=env["actor"], work_order_id=of.id, correlation_id=str(ULID())
    )

    again = service.close_work_order(
        tenant_id=TENANT, actor_id=env["actor"], work_order_id=of.id, correlation_id=str(ULID())
    )
    assert isinstance(again, Err)
    assert again.code == "INVALID_TRANSITION"
    assert _check(db, of)["can_close"] is False
