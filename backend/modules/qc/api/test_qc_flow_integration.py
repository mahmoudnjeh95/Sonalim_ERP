"""Integration tests for the qc module.

qc carries of_id/product_id as opaque columns via its conformity lines and
never touches production's tables directly -- these tests build a shift
report through production's own ShiftReportService and validate it, then
work with nothing but the resulting shift_report_id and packing row ids.
"""
from __future__ import annotations

import datetime

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from modules.production.api.service import WorkOrderService
from modules.production.api.shift_report_service import ShiftReportService
from modules.production.api.shift_validation_service import ShiftValidationService
from modules.production.domain.shift_report import SECTION_KEYS
from modules.qc.api.non_conformity_service import NonConformityService
from modules.qc.api.quality_service import FollowUpPolicyService, FollowUpService, QualityReportService
from modules.qc.domain.non_conformity import DispositionLine
from modules.warehouse.api.service import StockService

TENANT = "integration-test-qc"


def _ok(result):
    assert isinstance(result, Ok), getattr(result, "message", result)
    return result.value


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
        "INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, 'FG', 'Finished goods')",
        (location, TENANT),
    )
    # A default location, because validating the shift posts the packed pasta there.
    db.execute(
        "INSERT INTO core.products (id, tenant_id, sku, name, uom_id, default_location_id) "
        "VALUES (%s, %s, 'TEST-QC', 'Test pasta', %s, %s)",
        (product, TENANT, uom, location),
    )
    db.execute(
        "INSERT INTO warehouse.locations (id, tenant_id, code, name, is_blocked, blocked_reason) "
        "VALUES (%s, %s, 'QUAR', 'Quarantine', TRUE, 'awaiting QC disposition')",
        (quarantine, TENANT),
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
        tenant_id=TENANT, product_id=product, location_id=location, quantity=1_000,
        correlation_id=str(ULID()), reference="test-seed", actor_id=actor,
    )
    return {
        "actor": actor, "product": product, "location": location, "quarantine": quarantine,
        "work_center": work_center, "equipment": equipment,
    }


@pytest.fixture
def of(db, env):
    created = WorkOrderService(db).create_work_order(
        tenant_id=TENANT, actor_id=env["actor"], product_id=env["product"],
        planned_quantity=1000, work_center_id=env["work_center"],
    )
    assert isinstance(created, Ok), getattr(created, "message", "")
    return created.value


def _validated_shift(db, env, of, report_date=datetime.date(2026, 9, 1), shift="morning", packets_counted=200) -> str:
    """A validated shift with one packing row, ready for QC to inspect."""
    service = ShiftReportService(db)
    shift_id = _ok(service.open_shift(
        tenant_id=TENANT, actor_id=env["actor"], work_center_id=env["work_center"],
        report_date=report_date, shift=shift,
    ))["id"]
    _ok(service.save_section(
        tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key="packing",
        payload={"rows": [{
            "of_id": of.id, "product_id": env["product"], "equipment_id": env["equipment"],
            "finished_product_quantity": 900, "packets_counted": packets_counted,
        }]},
    ))
    for key in SECTION_KEYS:
        if key == "packing":
            _ok(service.submit_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key))
        else:
            _ok(service.declare_nothing(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key))
    _ok(ShiftValidationService(db).validate_shift(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id))
    return shift_id


def _validated_shift_with_rows(db, env, rows, report_date=datetime.date(2026, 9, 1), shift="morning") -> str:
    """A validated shift with one packing row per (of_id, product_id) in `rows`, in order."""
    service = ShiftReportService(db)
    shift_id = _ok(service.open_shift(
        tenant_id=TENANT, actor_id=env["actor"], work_center_id=env["work_center"],
        report_date=report_date, shift=shift,
    ))["id"]
    _ok(service.save_section(
        tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key="packing",
        payload={"rows": [
            {
                "of_id": of_id, "product_id": product_id, "equipment_id": env["equipment"],
                "finished_product_quantity": 100, "packets_counted": 20,
            }
            for of_id, product_id in rows
        ]},
    ))
    for key in SECTION_KEYS:
        if key == "packing":
            _ok(service.submit_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key))
        else:
            _ok(service.declare_nothing(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key))
    _ok(ShiftValidationService(db).validate_shift(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id))
    return shift_id


def _second_product(db, env, sku="TEST-QC-2") -> str:
    product = str(ULID())
    db.execute(
        "INSERT INTO core.products (id, tenant_id, sku, name, uom_id, default_location_id) "
        "SELECT %s, %s, %s, 'Second pasta', uom_id, default_location_id FROM core.products WHERE id = %s",
        (product, TENANT, sku, env["product"]),
    )
    StockService(db).receive_stock(
        tenant_id=TENANT, product_id=product, location_id=env["location"], quantity=1_000,
        correlation_id=str(ULID()), reference="test-seed", actor_id=env["actor"],
    )
    return product


def _quality_report(db, env, of, report_date=datetime.date(2026, 9, 1), shift="morning"):
    shift_id = _validated_shift(db, env, of, report_date=report_date, shift=shift)
    result = QualityReportService(db).create_report(
        tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id,
    )
    assert isinstance(result, Ok), getattr(result, "message", "")
    return result.value["report"]


def _record_line(db, env, report, **line_fields):
    """Fill in the report's single conformity line (one packing row per test shift)."""
    service = QualityReportService(db)
    line = service._load_lines(tenant_id=TENANT, report_id=report.id)[0]
    return _ok(service.update_draft(
        tenant_id=TENANT, actor_id=env["actor"], report_id=report.id,
        lines=[{"shift_packing_row_id": line.shift_packing_row_id, **line_fields}],
    ))


# --- one quality report per shift, many per OF ------------------------------


def test_an_of_carries_one_quality_report_per_shift(db, env, of):
    """Each shift gets its own quality report, so an OF spanning several shifts
    legitimately has several of them."""
    service = QualityReportService(db)
    _quality_report(db, env, of, report_date=datetime.date(2026, 9, 1), shift="morning")
    _quality_report(db, env, of, report_date=datetime.date(2026, 9, 1), shift="afternoon")
    _quality_report(db, env, of, report_date=datetime.date(2026, 9, 2), shift="morning")

    reports = service.list_reports(tenant_id=TENANT)
    assert len(reports) == 3
    of_lines = [
        line
        for report in reports
        for line in service._load_lines(tenant_id=TENANT, report_id=report.id)
        if line.of_id == of.id
    ]
    assert len(of_lines) == 3


def test_the_same_shift_report_cannot_be_inspected_twice(db, env, of):
    report = _quality_report(db, env, of, report_date=datetime.date(2026, 9, 1), shift="morning")
    duplicate = QualityReportService(db).create_report(
        tenant_id=TENANT,
        actor_id=env["actor"],
        shift_report_id=report.shift_report_id,
    )
    assert isinstance(duplicate, Err)
    assert duplicate.code == "DUPLICATE_REPORT"


def test_a_report_starts_as_a_draft_with_one_line_per_packing_row(db, env, of):
    report = _quality_report(db, env, of)
    assert report.status == "draft"

    full = QualityReportService(db).get_report(tenant_id=TENANT, report_id=report.id)
    assert len(full["lines"]) == 1
    assert full["lines"][0].of_id == of.id
    assert full["lines"][0].product_id == env["product"]
    assert full["lines"][0].conforming_cartons == 0
    assert full["lines"][0].non_conforming_cartons == 0


def test_only_validated_shift_reports_without_a_qc_report_are_inspectable(db, env, of):
    service = QualityReportService(db)
    shift_id = _validated_shift(db, env, of)
    inspectable = {row["shift_report_id"] for row in service.list_inspectable_shift_reports(tenant_id=TENANT)}
    assert shift_id in inspectable

    _ok(service.create_report(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id))
    inspectable = {row["shift_report_id"] for row in service.list_inspectable_shift_reports(tenant_id=TENANT)}
    assert shift_id not in inspectable


def test_an_unknown_shift_report_is_refused(db, env):
    result = QualityReportService(db).create_report(
        tenant_id=TENANT, actor_id=env["actor"], shift_report_id=str(ULID())
    )
    assert isinstance(result, Err)
    assert result.code == "NOT_FOUND"


def test_a_shift_not_yet_validated_cannot_be_inspected(db, env, of):
    """An open shift can still change what it packed, so QC has nothing on record to judge."""
    shift_id = _ok(ShiftReportService(db).open_shift(
        tenant_id=TENANT, actor_id=env["actor"], work_center_id=env["work_center"],
        report_date=datetime.date(2026, 9, 3), shift="morning",
    ))["id"]
    result = QualityReportService(db).create_report(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id)
    assert isinstance(result, Err)
    assert result.code == "SHIFT_NOT_VALIDATED"


# --- conformity lines -------------------------------------------------------


def test_update_draft_records_a_lines_counts(db, env, of):
    report = _quality_report(db, env, of)
    updated = _record_line(db, env, report, conforming_cartons=17, non_conforming_cartons=3, defect_details="film mal soude")
    line = updated["lines"][0]
    assert line.conforming_cartons == 17
    assert line.non_conforming_cartons == 3
    assert line.defect_details == "film mal soude"


def test_update_draft_refuses_non_conforming_cartons_without_defect_details(db, env, of):
    report = _quality_report(db, env, of)
    service = QualityReportService(db)
    line = service._load_lines(tenant_id=TENANT, report_id=report.id)[0]
    result = service.update_draft(
        tenant_id=TENANT, actor_id=env["actor"], report_id=report.id,
        lines=[{"shift_packing_row_id": line.shift_packing_row_id, "conforming_cartons": 17, "non_conforming_cartons": 3}],
    )
    assert isinstance(result, Err)
    assert result.code == "MISSING_DEFECT_DETAILS"


def test_update_draft_refuses_a_packing_row_not_on_the_report(db, env, of):
    report = _quality_report(db, env, of)
    result = QualityReportService(db).update_draft(
        tenant_id=TENANT, actor_id=env["actor"], report_id=report.id,
        lines=[{"shift_packing_row_id": str(ULID()), "conforming_cartons": 1}],
    )
    assert isinstance(result, Err)
    assert result.code == "LINE_NOT_FOUND"


def test_submit_refuses_a_line_with_a_defect_but_no_details(db, env, of):
    """update_draft already refuses this; the direct write stands in for a line
    that got into that state some other way, which submit must still catch."""
    report = _quality_report(db, env, of)
    db.execute(
        "UPDATE qc.quality_conformity_lines SET non_conforming_cartons = 3 WHERE report_id = %s",
        (report.id,),
    )
    result = QualityReportService(db).submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)
    assert isinstance(result, Err)
    assert result.code == "MISSING_DEFECT_DETAILS"


def test_a_submitted_report_is_no_longer_a_draft_to_edit(db, env, of):
    service = QualityReportService(db)
    report = _quality_report(db, env, of)
    _ok(service.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id))
    line = service._load_lines(tenant_id=TENANT, report_id=report.id)[0]
    result = service.update_draft(
        tenant_id=TENANT, actor_id=env["actor"], report_id=report.id,
        lines=[{"shift_packing_row_id": line.shift_packing_row_id, "conforming_cartons": 5}],
    )
    assert isinstance(result, Err)
    assert result.code == "NOT_EDITABLE"


# --- the report lifecycle ---------------------------------------------------


def test_the_quality_report_walks_draft_to_validated(db, env, of):
    service = QualityReportService(db)
    report = _quality_report(db, env, of)

    assert isinstance(service.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id), Ok)
    validated = service.validate_report(
        tenant_id=TENANT, actor_id=env["actor"], report_id=report.id, correlation_id=str(ULID())
    )
    assert isinstance(validated, Ok), getattr(validated, "message", "")
    assert validated.value["report"].validated_by == env["actor"]


def test_a_draft_quality_report_cannot_be_validated(db, env, of):
    report = _quality_report(db, env, of)
    result = QualityReportService(db).validate_report(
        tenant_id=TENANT, actor_id=env["actor"], report_id=report.id, correlation_id=str(ULID())
    )
    assert isinstance(result, Err)
    assert result.code == "INVALID_TRANSITION"


def test_validating_twice_is_refused(db, env, of):
    service = QualityReportService(db)
    report = _quality_report(db, env, of)
    service.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)
    assert isinstance(
        service.validate_report(
            tenant_id=TENANT, actor_id=env["actor"], report_id=report.id, correlation_id=str(ULID())
        ),
        Ok,
    )
    second = service.validate_report(
        tenant_id=TENANT, actor_id=env["actor"], report_id=report.id, correlation_id=str(ULID())
    )
    assert isinstance(second, Err)

    windows = db.execute(
        "SELECT count(*) FROM qc.quality_follow_ups WHERE tenant_id = %s AND quality_report_id = %s",
        (TENANT, report.id),
    ).fetchone()[0]
    assert windows == 1, "a refused second validate must not open a second window"


def test_quality_validation_posts_no_stock(db, env, of):
    service = QualityReportService(db)
    report = _quality_report(db, env, of)
    service.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)

    before = db.execute("SELECT count(*) FROM warehouse.stock_moves").fetchone()[0]
    service.validate_report(
        tenant_id=TENANT, actor_id=env["actor"], report_id=report.id, correlation_id=str(ULID())
    )
    assert db.execute("SELECT count(*) FROM warehouse.stock_moves").fetchone()[0] == before


def test_validation_publishes_its_event(db, env, of):
    service = QualityReportService(db)
    report = _quality_report(db, env, of)
    service.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)
    service.validate_report(
        tenant_id=TENANT, actor_id=env["actor"], report_id=report.id, correlation_id=str(ULID())
    )

    published = db.execute(
        "SELECT count(*) FROM events.outbox WHERE event_type = 'qc.quality_report.validated'"
    ).fetchone()[0]
    assert published >= 1


# --- the follow-up window ---------------------------------------------------


def test_validation_opens_a_forty_day_window_by_default(db, env, of):
    service = QualityReportService(db)
    report = _quality_report(db, env, of, report_date=datetime.date(2026, 9, 1))
    service.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)
    validated = service.validate_report(
        tenant_id=TENANT, actor_id=env["actor"], report_id=report.id, correlation_id=str(ULID())
    )
    follow_ups = validated.value["follow_ups"]
    assert len(follow_ups) == 1, "one window per conformity line"
    assert follow_ups[0]["window_ends_on"] == datetime.date(2026, 10, 11)
    assert follow_ups[0]["of_id"] == of.id


def test_a_per_product_policy_overrides_the_default(db, env, of):
    policies = FollowUpPolicyService(db)
    assert isinstance(
        policies.set_policy(tenant_id=TENANT, actor_id=env["actor"], window_days=10, product_id=env["product"]), Ok
    )

    service = QualityReportService(db)
    report = _quality_report(db, env, of, report_date=datetime.date(2026, 9, 1))
    service.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)
    validated = service.validate_report(
        tenant_id=TENANT, actor_id=env["actor"], report_id=report.id, correlation_id=str(ULID())
    )
    assert validated.value["follow_ups"][0]["window_ends_on"] == datetime.date(2026, 9, 11)


def test_a_tenant_default_applies_when_the_product_has_no_override(db, env):
    policies = FollowUpPolicyService(db)
    policies.set_policy(tenant_id=TENANT, actor_id=env["actor"], window_days=25)
    assert policies.resolve_window_days(tenant_id=TENANT, product_id=env["product"]) == 25

    policies.set_policy(tenant_id=TENANT, actor_id=env["actor"], window_days=7, product_id=env["product"])
    assert policies.resolve_window_days(tenant_id=TENANT, product_id=env["product"]) == 7
    assert policies.resolve_window_days(tenant_id=TENANT, product_id=None) == 25


def test_an_observation_outside_the_window_is_refused(db, env, of):
    service = QualityReportService(db)
    report = _quality_report(db, env, of, report_date=datetime.date(2026, 9, 1))
    service.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)
    service.validate_report(
        tenant_id=TENANT, actor_id=env["actor"], report_id=report.id, correlation_id=str(ULID())
    )

    follow_ups = FollowUpService(db)
    inside = follow_ups.record_observation(
        tenant_id=TENANT,
        actor_id=env["actor"],
        quality_report_id=report.id,
        observed_on=datetime.date(2026, 9, 20),
        observation="no change",
    )
    assert isinstance(inside, Ok), getattr(inside, "message", "")

    outside = follow_ups.record_observation(
        tenant_id=TENANT,
        actor_id=env["actor"],
        quality_report_id=report.id,
        observed_on=datetime.date(2026, 12, 1),
        observation="too late",
    )
    assert isinstance(outside, Err)
    assert outside.code == "OUTSIDE_WINDOW"


def test_follow_up_survives_of_closure(db, env, of):
    """Quality outlives production — that is why it is not keyed to an open OF."""
    service = QualityReportService(db)
    report = _quality_report(db, env, of, report_date=datetime.date(2026, 9, 1))
    service.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)
    service.validate_report(
        tenant_id=TENANT, actor_id=env["actor"], report_id=report.id, correlation_id=str(ULID())
    )

    # The shift the quality report inspects is already validated, so the OF has
    # nothing outstanding on the production side and can close.
    work_orders = WorkOrderService(db)
    work_orders.start_work_order(tenant_id=TENANT, actor_id=env["actor"], work_order_id=of.id)
    assert isinstance(
        work_orders.close_work_order(
            tenant_id=TENANT, actor_id=env["actor"], work_order_id=of.id, correlation_id=str(ULID())
        ),
        Ok,
    )

    recorded = FollowUpService(db).record_observation(
        tenant_id=TENANT,
        actor_id=env["actor"],
        quality_report_id=report.id,
        observed_on=datetime.date(2026, 9, 25),
        observation="checked after closure",
    )
    assert isinstance(recorded, Ok), getattr(recorded, "message", "")


# --- deleting a quality report ---------------------------------------------


def test_deleting_a_report_needs_a_reason(db, env, of):
    report = _quality_report(db, env, of)
    result = QualityReportService(db).delete_report(
        tenant_id=TENANT, actor_id=env["actor"], report_id=report.id, reason="   "
    )
    assert isinstance(result, Err)
    assert result.code == "MISSING_REASON"


def test_deleting_a_draft_takes_its_detail_and_lines_with_it(db, env, of):
    service = QualityReportService(db)
    report = _quality_report(db, env, of)

    assert isinstance(
        service.delete_report(
            tenant_id=TENANT, actor_id=env["actor"], report_id=report.id, reason="filed against the wrong OF"
        ),
        Ok,
    )
    assert service.get_report(tenant_id=TENANT, report_id=report.id) is None
    orphans = db.execute(
        "SELECT COUNT(*) FROM qc.quality_report_details WHERE report_id = %s", (report.id,)
    ).fetchone()
    assert orphans[0] == 0
    orphan_lines = db.execute(
        "SELECT COUNT(*) FROM qc.quality_conformity_lines WHERE report_id = %s", (report.id,)
    ).fetchone()
    assert orphan_lines[0] == 0


def test_deleting_a_validated_report_closes_its_follow_up_window(db, env, of):
    """Validation is what opens the 40-day window, so removing the report that
    opened it must take the window away too — otherwise QC keeps chasing an
    observation for a report that no longer exists."""
    service = QualityReportService(db)
    report = _quality_report(db, env, of)
    service.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)
    service.validate_report(
        tenant_id=TENANT, actor_id=env["actor"], report_id=report.id, correlation_id=str(ULID())
    )
    assert FollowUpService(db).count_open_for_of(tenant_id=TENANT, of_id=of.id) == 1

    assert isinstance(
        service.delete_report(
            tenant_id=TENANT, actor_id=env["actor"], report_id=report.id, reason="duplicate of the morning report"
        ),
        Ok,
    )
    assert FollowUpService(db).count_open_for_of(tenant_id=TENANT, of_id=of.id) == 0


def test_a_report_with_a_non_conformity_cannot_be_deleted(db, env, of):
    """The NC has already moved product into quarantine. Deleting the report it
    came from would leave that stock stranded with nothing explaining it."""
    report = _quality_report(db, env, of)
    _record_line(db, env, report, non_conforming_cartons=10, defect_details="bad film seal")
    NonConformityService(db).raise_non_conformity(
        tenant_id=TENANT,
        actor_id=env["actor"],
        of_id=of.id,
        product_id=env["product"],
        quantity=10.0,
        source_location_id=env["location"],
        quarantine_location_id=env["quarantine"],
        defect_type="bad film seal",
        correlation_id=str(ULID()),
        quality_report_id=report.id,
    )

    result = QualityReportService(db).delete_report(
        tenant_id=TENANT, actor_id=env["actor"], report_id=report.id, reason="entered by mistake"
    )
    assert isinstance(result, Err)
    assert result.code == "NON_CONFORMITY_ATTACHED"


def test_the_deletion_is_recorded_in_the_audit_trail(db, env, of):
    report = _quality_report(db, env, of)
    QualityReportService(db).delete_report(
        tenant_id=TENANT, actor_id=env["actor"], report_id=report.id, reason="wrong shift"
    )
    row = db.execute(
        "SELECT payload FROM core.audit_log WHERE entity_id = %s AND action = 'quality_report.deleted'",
        (report.id,),
    ).fetchone()
    assert row is not None
    assert row[0]["reason"] == "wrong shift"
    assert row[0]["status_when_deleted"] == "draft"


# --- non-conformity ---------------------------------------------------------


def _raise_nc(db, env, of, quantity=10.0):
    result = NonConformityService(db).raise_non_conformity(
        tenant_id=TENANT,
        actor_id=env["actor"],
        of_id=of.id,
        product_id=env["product"],
        quantity=quantity,
        source_location_id=env["location"],
        quarantine_location_id=env["quarantine"],
        defect_type="bad film seal",
        severity="major",
        correlation_id=str(ULID()),
    )
    assert isinstance(result, Ok), getattr(result, "message", "")
    return result.value


def _on_hand(db, product_id, location_id) -> float:
    row = db.execute(
        "SELECT quantity_on_hand FROM warehouse.stock_items WHERE tenant_id = %s AND product_id = %s AND location_id = %s",
        (TENANT, product_id, location_id),
    ).fetchone()
    return float(row[0]) if row else 0.0


def test_raising_a_non_conformity_numbers_it(db, env, of):
    non_conformity = _raise_nc(db, env, of)
    assert non_conformity.reference.startswith("NC-")
    assert non_conformity.status == "quarantined", "segregated the moment it is pulled"


def test_a_non_conformity_can_be_raised_against_a_closed_of(db, env, of):
    """The 40-day follow-up outlives production, so NC must work after closure."""
    work_orders = WorkOrderService(db)
    work_orders.start_work_order(tenant_id=TENANT, actor_id=env["actor"], work_order_id=of.id)
    work_orders.close_work_order(
        tenant_id=TENANT, actor_id=env["actor"], work_order_id=of.id, correlation_id=str(ULID())
    )
    non_conformity = _raise_nc(db, env, of)
    assert non_conformity.status == "quarantined"


def test_the_worked_example_ten_packets_fail(db, env, of):
    """Pasta to rebroyat, film and carton and tape to déchet."""
    service = NonConformityService(db)
    non_conformity = _raise_nc(db, env, of)
    assert non_conformity.quarantine_location_id == env["quarantine"]

    dispositioned = service.disposition(
        tenant_id=TENANT,
        actor_id=env["actor"],
        non_conformity_id=non_conformity.id,
        correlation_id=str(ULID()),
        lines=(
            DispositionLine(component="product", disposition="regrind", quantity=8),
            DispositionLine(component="film", disposition="dechet", quantity=0.4),
            DispositionLine(component="carton", disposition="dechet", quantity=1),
            DispositionLine(component="tape", disposition="dechet", quantity=0.1),
        ),
    )
    assert isinstance(dispositioned, Ok), getattr(dispositioned, "message", "")
    assert len(dispositioned.value["dispositions"]) == 4

    closed = service.close(
        tenant_id=TENANT,
        actor_id=env["actor"],
        non_conformity_id=non_conformity.id,
        corrective_action="sealing head recalibrated",
    )
    assert isinstance(closed, Ok)
    assert closed.value.status == "closed"
    assert closed.value.closed_at is not None


def test_raising_moves_the_product_into_quarantine(db, env, of):
    """The movement that makes segregation real rather than a label."""
    before_shelf = _on_hand(db, env["product"], env["location"])

    non_conformity = _raise_nc(db, env, of, quantity=10)

    assert _on_hand(db, env["product"], env["location"]) == before_shelf - 10
    assert _on_hand(db, env["product"], env["quarantine"]) == 10
    assert non_conformity.status == "quarantined"


def test_quarantined_stock_cannot_be_promised(db, env, of):
    """Excluded from available quantity, so no other module can sell it."""
    _raise_nc(db, env, of, quantity=10)
    stock = StockService(db)

    assert _on_hand(db, env["product"], env["quarantine"]) == 10, "it is on the books"
    assert stock.get_available_quantity(TENANT, env["product"], env["quarantine"]) == 0.0


def test_quarantine_must_be_a_blocked_location(db, env, of):
    open_shelf = str(ULID())
    db.execute(
        "INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, 'OPEN', 'Open shelf')",
        (open_shelf, TENANT),
    )
    result = NonConformityService(db).raise_non_conformity(
        tenant_id=TENANT,
        actor_id=env["actor"],
        of_id=of.id,
        product_id=env["product"],
        quantity=10,
        source_location_id=env["location"],
        quarantine_location_id=open_shelf,
        defect_type="bad seal",
        correlation_id=str(ULID()),
    )
    assert isinstance(result, Err)
    assert result.code == "LOCATION_NOT_BLOCKED"


def test_disposition_takes_the_product_back_out_of_quarantine(db, env, of):
    service = NonConformityService(db)
    non_conformity = _raise_nc(db, env, of, quantity=10)
    assert _on_hand(db, env["product"], env["quarantine"]) == 10

    service.disposition(
        tenant_id=TENANT,
        actor_id=env["actor"],
        non_conformity_id=non_conformity.id,
        correlation_id=str(ULID()),
        lines=(
            DispositionLine(component="product", disposition="regrind", quantity=8),
            DispositionLine(component="film", disposition="dechet", quantity=0.4),
        ),
    )
    assert _on_hand(db, env["product"], env["quarantine"]) == 0, "never a straight write-off"


def test_rejecting_a_report_returns_its_quarantined_stock_to_source(db, env, of):
    """A rejected report never made its hold official -- the product must land
    back where it was pulled from, not just be issued off the books with
    nothing downstream telling anyone where it went."""
    report = _quality_report(db, env, of)
    _record_line(db, env, report, non_conforming_cartons=10, defect_details="bad film seal")
    before_shelf = _on_hand(db, env["product"], env["location"])

    raised = NonConformityService(db).raise_non_conformity(
        tenant_id=TENANT,
        actor_id=env["actor"],
        of_id=of.id,
        product_id=env["product"],
        quantity=10.0,
        source_location_id=env["location"],
        quarantine_location_id=env["quarantine"],
        defect_type="bad film seal",
        correlation_id=str(ULID()),
        quality_report_id=report.id,
    )
    assert isinstance(raised, Ok), getattr(raised, "message", "")
    non_conformity_id = raised.value.id
    assert _on_hand(db, env["product"], env["quarantine"]) == 10
    assert _on_hand(db, env["product"], env["location"]) == before_shelf - 10

    submitted = QualityReportService(db).submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)
    assert isinstance(submitted, Ok), getattr(submitted, "message", "")

    rejected = QualityReportService(db).reject_report(
        tenant_id=TENANT, actor_id=env["actor"], report_id=report.id, reason="wrong shift recorded"
    )
    assert isinstance(rejected, Ok), getattr(rejected, "message", "")
    assert rejected.value.status == "rejected"

    nc_row = db.execute(
        "SELECT id FROM qc.non_conformities WHERE tenant_id = %s AND id = %s", (TENANT, non_conformity_id)
    ).fetchone()
    assert nc_row is None, "the hold never should have happened once the report describing it is rejected"
    assert _on_hand(db, env["product"], env["quarantine"]) == 0
    assert _on_hand(db, env["product"], env["location"]) == before_shelf, "stock must return, not vanish"


def test_a_quality_report_backed_nc_converts_cartons_to_the_products_own_unit(db, env, of):
    """A rapport declares its rejection in cartons; the product here is stocked
    in pieces (a carton tier of 20). The caller passing a raw carton count as
    `quantity` -- exactly the bug this closes -- must not reach stock or the
    ticket unconverted: 1 carton non-conforme has to move and record 20."""
    db.execute(
        "UPDATE core.products SET packets_per_carton = 20 WHERE id = %s AND tenant_id = %s",
        (env["product"], TENANT),
    )
    report = _quality_report(db, env, of)
    _record_line(db, env, report, non_conforming_cartons=1, defect_details="pieces endommagees")
    before_shelf = _on_hand(db, env["product"], env["location"])

    raised = NonConformityService(db).raise_non_conformity(
        tenant_id=TENANT,
        actor_id=env["actor"],
        of_id=of.id,
        product_id=env["product"],
        quantity=1.0,  # what an unconverted caller would send -- must be ignored
        source_location_id=env["location"],
        quarantine_location_id=env["quarantine"],
        defect_type="pieces endommagees",
        correlation_id=str(ULID()),
        quality_report_id=report.id,
    )
    assert isinstance(raised, Ok), getattr(raised, "message", "")
    assert raised.value.quantity == 20
    assert _on_hand(db, env["product"], env["quarantine"]) == 20
    assert _on_hand(db, env["product"], env["location"]) == before_shelf - 20


def test_raising_an_nc_from_a_quality_report_derives_quantity_from_its_line(db, env, of):
    qc = QualityReportService(db)
    report = _quality_report(db, env, of)
    line = qc._load_lines(tenant_id=TENANT, report_id=report.id)[0]
    qc.update_draft(
        tenant_id=TENANT, actor_id=env["actor"], report_id=report.id,
        lines=[{"shift_packing_row_id": line.shift_packing_row_id, "conforming_cartons": 10, "non_conforming_cartons": 4, "defect_details": "soudure"}],
    )
    _ok(qc.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id))
    _ok(qc.validate_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id, correlation_id=str(ULID())))

    nc = NonConformityService(db).raise_non_conformity(
        tenant_id=TENANT, actor_id=env["actor"], of_id=of.id, product_id=env["product"],
        quantity=0,  # ignored -- derived from the quality report
        source_location_id=env["location"], defect_type="soudure défectueuse",
        correlation_id=str(ULID()), quarantine_location_id=env["quarantine"],
        quality_report_id=report.id,
    )
    assert isinstance(nc, Ok), getattr(nc, "message", "")
    assert nc.value.quantity == 4  # no packets_per_carton on this test product, so cartons == pieces


def test_one_nc_covers_every_line_of_the_same_of_and_product(db, env, of):
    """Two packing rows, same OF and product: the NC unit is (report, OF, product), so one NC
    carries the sum of both lines' non-conforming cartons, converted to pieces."""
    db.execute(
        "UPDATE core.products SET packets_per_carton = 20 WHERE id = %s AND tenant_id = %s",
        (env["product"], TENANT),
    )
    qc = QualityReportService(db)
    shift_id = _validated_shift_with_rows(db, env, [(of.id, env["product"]), (of.id, env["product"])])
    report = _ok(qc.create_report(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id))["report"]
    lines = qc._load_lines(tenant_id=TENANT, report_id=report.id)
    assert len(lines) == 2
    _ok(qc.update_draft(
        tenant_id=TENANT, actor_id=env["actor"], report_id=report.id,
        lines=[
            {"shift_packing_row_id": lines[0].shift_packing_row_id, "non_conforming_cartons": 3, "defect_details": "soudure"},
            {"shift_packing_row_id": lines[1].shift_packing_row_id, "non_conforming_cartons": 5, "defect_details": "soudure"},
        ],
    ))

    nc = _ok(NonConformityService(db).raise_non_conformity(
        tenant_id=TENANT, actor_id=env["actor"], of_id=of.id, product_id=env["product"], quantity=0,
        source_location_id=env["location"], quarantine_location_id=env["quarantine"],
        defect_type="soudure", correlation_id=str(ULID()), quality_report_id=report.id,
    ))
    assert nc.quantity == 8 * 20


def test_a_manually_raised_nc_keeps_the_quantity_it_is_given(db, env, of):
    """No quality report attached -- there is no rapport carton count to derive
    from, so the quantity the caller supplies (already in the product's own
    unit, per the manual raise form) is trusted as-is."""
    db.execute(
        "UPDATE core.products SET packets_per_carton = 20 WHERE id = %s AND tenant_id = %s",
        (env["product"], TENANT),
    )
    non_conformity = _raise_nc(db, env, of, quantity=7)
    assert non_conformity.quantity == 7


def test_packaging_is_never_deducted_a_second_time(db, env, of):
    """Locked decision 8. The film and carton in a rejected packet already left
    stock when the conditionnement report was validated; deducting them again would
    understate packaging every time quality does its job."""
    film = str(ULID())
    db.execute(
        "INSERT INTO core.products (id, tenant_id, sku, name, uom_id) "
        "SELECT %s, %s, 'NC-FILM', 'Film', id FROM core.uoms WHERE tenant_id = %s LIMIT 1",
        (film, TENANT, TENANT),
    )
    StockService(db).receive_stock(
        tenant_id=TENANT, product_id=film, location_id=env["location"], quantity=500,
        correlation_id=str(ULID()), reference="test-seed", actor_id=env["actor"],
    )
    film_before = _on_hand(db, film, env["location"])

    service = NonConformityService(db)
    non_conformity = _raise_nc(db, env, of, quantity=10)
    service.disposition(
        tenant_id=TENANT,
        actor_id=env["actor"],
        non_conformity_id=non_conformity.id,
        correlation_id=str(ULID()),
        lines=(
            DispositionLine(component="product", disposition="regrind", quantity=8),
            DispositionLine(component="film", disposition="dechet", quantity=0.4),
            DispositionLine(component="carton", disposition="dechet", quantity=1),
        ),
    )
    assert _on_hand(db, film, env["location"]) == film_before, "déchet is reported, not deducted"


def test_the_disposition_publishes_the_event_production_will_consume(db, env, of):
    service = NonConformityService(db)
    non_conformity = _raise_nc(db, env, of)
    service.disposition(
        tenant_id=TENANT,
        actor_id=env["actor"],
        non_conformity_id=non_conformity.id,
        correlation_id=str(ULID()),
        lines=(DispositionLine(component="product", disposition="regrind", quantity=8),),
    )

    published = db.execute(
        "SELECT count(*) FROM events.outbox WHERE event_type = 'qc.non_conformity.dispositioned'"
    ).fetchone()[0]
    assert published >= 1


def test_nothing_in_qc_writes_into_productions_schema(db, env, of):
    """The module boundary, asserted: raising and dispositioning an NC leaves
    production's scrap ledger untouched. Production writes it in Phase 5, by
    consuming the event above."""
    service = NonConformityService(db)
    before = db.execute(
        "SELECT count(*) FROM production.scrap_records WHERE tenant_id = %s", (TENANT,)
    ).fetchone()[0]

    non_conformity = _raise_nc(db, env, of)
    service.disposition(
        tenant_id=TENANT,
        actor_id=env["actor"],
        non_conformity_id=non_conformity.id,
        correlation_id=str(ULID()),
        lines=(DispositionLine(component="product", disposition="regrind", quantity=8),),
    )

    after = db.execute(
        "SELECT count(*) FROM production.scrap_records WHERE tenant_id = %s", (TENANT,)
    ).fetchone()[0]
    assert after == before


def test_closing_requires_a_corrective_action(db, env, of):
    service = NonConformityService(db)
    non_conformity = _raise_nc(db, env, of)
    service.disposition(
        tenant_id=TENANT,
        actor_id=env["actor"],
        non_conformity_id=non_conformity.id,
        correlation_id=str(ULID()),
        lines=(DispositionLine(component="product", disposition="regrind", quantity=8),),
    )

    result = service.close(
        tenant_id=TENANT, actor_id=env["actor"], non_conformity_id=non_conformity.id, corrective_action="  "
    )
    assert isinstance(result, Err)
    assert result.code == "MISSING_CORRECTIVE_ACTION"


# --- admin re-link to another shift ------------------------------------------


def _relink(db, env, report, shift_id):
    return QualityReportService(db).admin_update_report(
        tenant_id=TENANT, actor_id=env["actor"], report_id=report.id, shift_report_id=shift_id, reason="wrong shift",
    )


def test_relinking_a_draft_replaces_its_lines_and_date(db, env, of):
    service = QualityReportService(db)
    report = _quality_report(db, env, of, report_date=datetime.date(2026, 9, 1))
    old_line = service._load_lines(tenant_id=TENANT, report_id=report.id)[0]
    new_shift = _validated_shift(db, env, of, report_date=datetime.date(2026, 9, 2))

    relinked = _ok(_relink(db, env, report, new_shift))

    assert relinked["report"].shift_report_id == new_shift
    assert relinked["report"].report_date == datetime.date(2026, 9, 2)
    assert len(relinked["lines"]) == 1, "the old shift's line is replaced, not kept alongside"
    assert relinked["lines"][0].shift_packing_row_id != old_line.shift_packing_row_id


def test_relinking_a_validated_report_is_refused(db, env, of):
    service = QualityReportService(db)
    report = _quality_report(db, env, of, report_date=datetime.date(2026, 9, 1))
    _ok(service.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id))
    _ok(service.validate_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id, correlation_id=str(ULID())))
    new_shift = _validated_shift(db, env, of, report_date=datetime.date(2026, 9, 2))

    result = _relink(db, env, report, new_shift)
    assert isinstance(result, Err)
    assert result.code == "NOT_EDITABLE"


def test_relinking_a_report_with_a_non_conformity_is_refused(db, env, of):
    report = _quality_report(db, env, of, report_date=datetime.date(2026, 9, 1))
    _record_line(db, env, report, non_conforming_cartons=2, defect_details="bad film seal")
    _ok(NonConformityService(db).raise_non_conformity(
        tenant_id=TENANT, actor_id=env["actor"], of_id=of.id, product_id=env["product"], quantity=0,
        source_location_id=env["location"], quarantine_location_id=env["quarantine"],
        defect_type="bad film seal", correlation_id=str(ULID()), quality_report_id=report.id,
    ))
    new_shift = _validated_shift(db, env, of, report_date=datetime.date(2026, 9, 2))

    result = _relink(db, env, report, new_shift)
    assert isinstance(result, Err)
    assert result.code == "NON_CONFORMITY_ATTACHED"


def test_relinking_onto_an_unvalidated_shift_is_refused(db, env, of):
    report = _quality_report(db, env, of, report_date=datetime.date(2026, 9, 1))
    open_shift = _ok(ShiftReportService(db).open_shift(
        tenant_id=TENANT, actor_id=env["actor"], work_center_id=env["work_center"],
        report_date=datetime.date(2026, 9, 2), shift="morning",
    ))["id"]
    result = _relink(db, env, report, open_shift)
    assert isinstance(result, Err)
    assert result.code == "SHIFT_NOT_VALIDATED"


def test_after_a_relink_the_old_shift_can_get_a_new_report(db, env, of):
    """The old lines went with the re-link, so the one-line-per-packing-row index no longer blocks the old shift."""
    report = _quality_report(db, env, of, report_date=datetime.date(2026, 9, 1))
    old_shift = report.shift_report_id
    new_shift = _validated_shift(db, env, of, report_date=datetime.date(2026, 9, 2))
    _ok(_relink(db, env, report, new_shift))

    fresh = _ok(QualityReportService(db).create_report(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=old_shift))
    assert fresh["report"].shift_report_id == old_shift
    assert len(fresh["lines"]) == 1


def test_edit_in_place_is_allowed_at_any_status(db, env, of):
    service = NonConformityService(db)
    non_conformity = _raise_nc(db, env, of)
    updated = service.admin_update_non_conformity(
        tenant_id=TENANT,
        actor_id=env["actor"],
        non_conformity_id=non_conformity.id,
        quantity=12,
        severity="critical",
    )
    assert isinstance(updated, Ok), getattr(updated, "message", "")
    assert updated.value.quantity == 12
    assert updated.value.severity == "critical"
