"""Arrêts as a list of stoppages, against a real database.

Downtime used to be one `downtime_minutes`/`downtime_reason` pair, which meant a
shift that stopped twice for two different reasons had to pick one to report and
fold the other's minutes into it. These tests pin the replacement: a report can
carry several stoppages, each with its own motif, and the list survives every
path a report takes — draft, correction after validation, deletion — the same
way `report_waste_lines` and `report_semolina_lines` already do.
"""
from __future__ import annotations

import datetime

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from modules.production.api.production_report_service import ProductionReportService
from modules.production.api.regrind_service import RegrindDefaultsService
from modules.production.api.service import WorkOrderService
from modules.production.domain.production_report import (
    DailyReportDetail,
    DowntimeLine,
    SemolinaLine,
    downtime_total_minutes,
)
from modules.warehouse.api.service import StockService

TENANT = "integration-test-downtime-lines"


@pytest.fixture
def env(db):
    actor = str(ULID())
    uom, product, location, work_center, equipment = (str(ULID()) for _ in range(5))

    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (actor, TENANT, f"{actor}@test.local"),
    )
    db.execute(
        "INSERT INTO core.uoms (id, tenant_id, code, name, category) VALUES (%s, %s, 'kg', 'Kilogramme', 'weight')",
        (uom, TENANT),
    )
    db.execute(
        "INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, 'DT-PASTA', 'Test pasta', %s)",
        (product, TENANT, uom),
    )
    db.execute(
        "INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, 'DT-LOC', 'Test location')",
        (location, TENANT),
    )
    db.execute(
        "INSERT INTO production.work_centers (id, tenant_id, code, name) VALUES (%s, %s, 'DT-WC', 'Line')",
        (work_center, TENANT),
    )
    db.execute(
        "INSERT INTO maintenance.equipment (id, tenant_id, work_center_id, code, name) VALUES (%s, %s, %s, 'DT-EQ', 'Test machine')",
        (equipment, TENANT, work_center),
    )
    StockService(db).receive_stock(
        tenant_id=TENANT, product_id=product, location_id=location, quantity=100_000,
        correlation_id=str(ULID()), reference="seed", actor_id=actor,
    )
    RegrindDefaultsService(db).set_default(tenant_id=TENANT, actor_id=actor, output_product_id=product)
    return {"actor": actor, "product": product, "location": location, "work_center": work_center, "equipment": equipment}


@pytest.fixture
def of(db, env):
    service = WorkOrderService(db)
    created = service.create_work_order(
        tenant_id=TENANT, actor_id=env["actor"], product_id=env["product"],
        planned_quantity=1000, work_center_id=env["work_center"],
    )
    assert isinstance(created, Ok), getattr(created, "message", "")
    assert isinstance(
        service.start_work_order(tenant_id=TENANT, actor_id=env["actor"], work_order_id=created.value.id), Ok
    )
    return created.value


def _draft(db, env, of, **detail):
    semolina_lines = detail.pop("semolina_lines", None)
    if semolina_lines is None:
        semolina_lines = (
            SemolinaLine(product_id=env["product"], quantity=detail.pop("semolina_quantity", 500), location_id=env["location"]),
        )
    detail["semolina_lines"] = semolina_lines
    detail.setdefault("raw_material_location_id", env["location"])
    created = ProductionReportService(db).create_daily_report(
        tenant_id=TENANT, actor_id=env["actor"], of_id=of.id,
        report_date=datetime.date(2026, 9, 1), shift="morning",
        equipment_id=env["equipment"],
        detail=DailyReportDetail(**detail),
    )
    assert isinstance(created, Ok), getattr(created, "message", "")
    return created.value["report"]


def _validate(db, env, report_id):
    service = ProductionReportService(db)
    assert isinstance(service.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report_id), Ok)
    result = service.validate_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report_id)
    assert isinstance(result, Ok), getattr(result, "message", "")
    return result


def _read(db, report_id):
    return ProductionReportService(db).get_report(tenant_id=TENANT, report_id=report_id)


# --- round trip -------------------------------------------------------------


def test_a_downtime_line_is_stored_and_read_back_whole(db, env, of):
    report = _draft(
        db, env, of,
        downtime_lines=(DowntimeLine(motif="die_jam", minutes=20, note="filière 3"),),
    )
    detail = _read(db, report.id)["detail"]
    assert len(detail.downtime_lines) == 1
    line = detail.downtime_lines[0]
    assert (line.motif, line.minutes, line.note) == ("die_jam", 20, "filière 3")


def test_several_motifs_on_the_same_report_are_all_kept(db, env, of):
    """The whole point: a shift stopped for two different reasons records both,
    rather than folding one into the other or picking one to report."""
    report = _draft(
        db, env, of,
        downtime_lines=(
            DowntimeLine(motif="extruder_failure", minutes=20),
            DowntimeLine(motif="electrical_failure", minutes=15),
        ),
    )
    detail = _read(db, report.id)["detail"]
    assert {(line.motif, line.minutes) for line in detail.downtime_lines} == {
        ("extruder_failure", 20),
        ("electrical_failure", 15),
    }
    assert downtime_total_minutes(detail.downtime_lines) == 35


def test_the_order_the_shift_entered_them_in_is_kept(db, env, of):
    report = _draft(
        db, env, of,
        downtime_lines=(
            DowntimeLine(motif="extruder_failure", minutes=5),
            DowntimeLine(motif="electrical_failure", minutes=10),
            DowntimeLine(motif="team_break", minutes=15),
        ),
    )
    detail = _read(db, report.id)["detail"]
    assert [line.motif for line in detail.downtime_lines] == ["extruder_failure", "electrical_failure", "team_break"]


def test_editing_a_draft_replaces_the_whole_list(db, env, of):
    """A form that removed a row must not leave the row behind in the database."""
    report = _draft(
        db, env, of,
        downtime_lines=(
            DowntimeLine(motif="extruder_failure", minutes=20),
            DowntimeLine(motif="electrical_failure", minutes=15),
        ),
    )
    updated = ProductionReportService(db).update_daily_draft(
        tenant_id=TENANT, actor_id=env["actor"], report_id=report.id,
        detail=DailyReportDetail(
            semolina_lines=(SemolinaLine(product_id=env["product"], quantity=500, location_id=env["location"]),),
            raw_material_location_id=env["location"],
            downtime_lines=(DowntimeLine(motif="die_jam", minutes=9),),
        ),
    )
    assert isinstance(updated, Ok), getattr(updated, "message", "")
    detail = _read(db, report.id)["detail"]
    assert [(line.motif, line.minutes) for line in detail.downtime_lines] == [("die_jam", 9)]


def test_blank_rows_are_not_stored(db, env, of):
    """A form with an untouched row recorded no stoppage. Storing it as zero
    minutes with no motif would put an arrêt with no cause into the report."""
    report = _draft(
        db, env, of,
        downtime_lines=(
            DowntimeLine(motif="extruder_failure", minutes=20),
            DowntimeLine(minutes=0),
        ),
    )
    detail = _read(db, report.id)["detail"]
    assert len(detail.downtime_lines) == 1


def test_a_zero_minute_line_carrying_a_note_is_kept(db, env, of):
    """"No stoppage today" is a fact a shift chose to record."""
    report = _draft(db, env, of, downtime_lines=(DowntimeLine(minutes=0, note="ran clean all shift"),))
    detail = _read(db, report.id)["detail"]
    assert len(detail.downtime_lines) == 1
    assert detail.downtime_lines[0].note == "ran clean all shift"


# --- what the list is allowed to say ----------------------------------------


def test_a_line_with_minutes_but_no_motif_is_refused_even_as_a_draft(db, env, of):
    """Unlike a waste line's item (deferred to submit-time), a downtime line's
    motif is required as soon as it records minutes -- the same strictness the
    single downtime_reason field used to have."""
    result = ProductionReportService(db).create_daily_report(
        tenant_id=TENANT, actor_id=env["actor"], of_id=of.id,
        report_date=datetime.date(2026, 9, 1),
        detail=DailyReportDetail(downtime_lines=(DowntimeLine(minutes=20),)),
    )
    assert isinstance(result, Err)
    assert result.code == "MISSING_DOWNTIME_REASON"


def test_a_negative_duration_is_refused_at_creation(db, env, of):
    result = ProductionReportService(db).create_daily_report(
        tenant_id=TENANT, actor_id=env["actor"], of_id=of.id,
        report_date=datetime.date(2026, 9, 2),
        detail=DailyReportDetail(downtime_lines=(DowntimeLine(motif="x", minutes=-5),)),
    )
    assert isinstance(result, Err)
    assert result.code == "INVALID_DURATION"


# --- corrections and deletion -----------------------------------------------


def test_correcting_a_validated_report_rewrites_its_downtime_list(db, env, of):
    report = _draft(db, env, of, downtime_lines=(DowntimeLine(motif="extruder_failure", minutes=20),))
    _validate(db, env, report.id)

    corrected = ProductionReportService(db).correct_validated_report(
        tenant_id=TENANT, actor_id=env["actor"], report_id=report.id,
        detail=DailyReportDetail(
            semolina_lines=(SemolinaLine(product_id=env["product"], quantity=500, location_id=env["location"]),),
            raw_material_location_id=env["location"],
            downtime_lines=(
                DowntimeLine(motif="extruder_failure", minutes=25),
                DowntimeLine(motif="electrical_failure", minutes=10),
            ),
        ),
        reason="the stoppage log was re-checked",
    )
    assert isinstance(corrected, Ok), getattr(corrected, "message", "")
    detail = _read(db, report.id)["detail"]
    assert sorted(line.minutes for line in detail.downtime_lines) == [10, 25]


def test_deleting_a_report_takes_its_downtime_list_with_it(db, env, of):
    report = _draft(db, env, of, downtime_lines=(DowntimeLine(motif="extruder_failure", minutes=20),))
    result = ProductionReportService(db).delete_report(
        tenant_id=TENANT, actor_id=env["actor"], report_id=report.id, reason="entered against the wrong OF"
    )
    assert isinstance(result, Ok), getattr(result, "message", "")
    remaining = db.execute(
        "SELECT count(*) FROM production.report_downtime_lines WHERE report_id = %s", (report.id,)
    ).fetchone()[0]
    assert remaining == 0


def test_the_deletion_audit_records_the_downtime_that_was_there(db, env, of):
    """The rows are gone afterwards, so the audit entry is the only account of
    what the report said — including its arrêts."""
    report = _draft(db, env, of, downtime_lines=(DowntimeLine(motif="extruder_failure", minutes=20),))
    ProductionReportService(db).delete_report(
        tenant_id=TENANT, actor_id=env["actor"], report_id=report.id, reason="duplicate"
    )
    payload = db.execute(
        """
        SELECT payload FROM core.audit_log
        WHERE entity_id = %s AND action = 'production_report.deleted'
        """,
        (report.id,),
    ).fetchone()[0]
    assert payload["detail"]["downtime_lines"] == [
        {"motif": "extruder_failure", "minutes": 20, "note": None, "line_order": 0}
    ]
