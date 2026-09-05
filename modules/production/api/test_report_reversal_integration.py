"""Correcting and deleting a validated report (first-review follow-up).

A validated report has already moved stock, so changing or removing it has to
undo those movements — otherwise inventory quietly stops matching the reports
that justify it. The mirror movements are posted rather than the ledger edited,
so the original and its correction both stay visible.
"""
from __future__ import annotations

import datetime

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from modules.production.api.production_report_service import ProductionReportService
from modules.production.api.regrind_service import RegrindDefaultsService, RegrindService
from modules.production.api.service import WorkOrderService
from modules.production.domain.production_report import DailyReportDetail, SemolinaLine
from modules.warehouse.api.service import StockService

TENANT = "integration-test-reversal"


@pytest.fixture
def env(db):
    actor = str(ULID())
    uom, semolina, rebroyat, location, work_center = (str(ULID()) for _ in range(5))
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (actor, TENANT, f"{actor}@test.local"),
    )
    db.execute(
        "INSERT INTO core.uoms (id, tenant_id, code, name, category) VALUES (%s, %s, 'kg', 'Kilogram', 'weight')",
        (uom, TENANT),
    )
    for product_id, sku in ((semolina, "REV-SEM"), (rebroyat, "REV-REB")):
        db.execute(
            "INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, %s, %s, %s)",
            (product_id, TENANT, sku, sku, uom),
        )
    db.execute(
        "INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, 'REV-LOC', 'Store')",
        (location, TENANT),
    )
    db.execute(
        "INSERT INTO production.work_centers (id, tenant_id, code, name) VALUES (%s, %s, 'REV-WC', 'Line')",
        (work_center, TENANT),
    )
    stock = StockService(db)
    for product_id in (semolina, rebroyat):
        stock.receive_stock(
            tenant_id=TENANT, product_id=product_id, location_id=location, quantity=10_000,
            correlation_id=str(ULID()), reference="seed", actor_id=actor,
        )
    RegrindDefaultsService(db).set_default(tenant_id=TENANT, actor_id=actor, output_product_id=rebroyat)
    return {
        "actor": actor,
        "semolina": semolina,
        "rebroyat": rebroyat,
        "location": location,
        "work_center": work_center,
    }


@pytest.fixture
def of(db, env):
    service = WorkOrderService(db)
    created = service.create_work_order(
        tenant_id=TENANT, actor_id=env["actor"], product_id=env["semolina"],
        planned_quantity=1000, work_center_id=env["work_center"],
    )
    service.start_work_order(tenant_id=TENANT, actor_id=env["actor"], work_order_id=created.value.id)
    return created.value


def _on_hand(db, product_id, location_id) -> float:
    row = db.execute(
        "SELECT quantity_on_hand FROM warehouse.stock_items WHERE tenant_id = %s AND product_id = %s AND location_id = %s",
        (TENANT, product_id, location_id),
    ).fetchone()
    return float(row[0]) if row else 0.0


def _detail(env, **kwargs):
    semolina_lines = kwargs.pop("semolina_lines", None)
    if semolina_lines is None:
        semolina_lines = (
            SemolinaLine(
                product_id=kwargs.pop("semolina_product_id", env["semolina"]),
                quantity=kwargs.pop("semolina_quantity", 0),
                location_id=env["location"],
            ),
        )
    kwargs["semolina_lines"] = semolina_lines
    kwargs.setdefault("raw_material_location_id", env["location"])
    return DailyReportDetail(**kwargs)


def _validated_report(db, env, of, **detail_kwargs):
    service = ProductionReportService(db)
    created = service.create_daily_report(
        tenant_id=TENANT, actor_id=env["actor"], of_id=of.id,
        report_date=datetime.date(2026, 9, 1), detail=_detail(env, **detail_kwargs),
    )
    assert isinstance(created, Ok), getattr(created, "message", "")
    report = created.value["report"]
    service.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)
    validated = service.validate_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)
    assert isinstance(validated, Ok), getattr(validated, "message", "")
    return report


# --- rebroyat poured in ------------------------------------------------------


def test_rebroyat_poured_in_is_deducted_like_semolina(db, env, of):
    """The gap this closed: recycled material used to re-enter production untracked."""
    semolina_before = _on_hand(db, env["semolina"], env["location"])
    rebroyat_before = _on_hand(db, env["rebroyat"], env["location"])

    _validated_report(db, env, of, semolina_quantity=800, regrind_input_quantity=120,
                      regrind_input_product_id=env["rebroyat"])

    assert _on_hand(db, env["semolina"], env["location"]) == semolina_before - 800
    assert _on_hand(db, env["rebroyat"], env["location"]) == rebroyat_before - 120


def test_rebroyat_poured_in_must_name_its_product(db, env, of):
    service = ProductionReportService(db)
    created = service.create_daily_report(
        tenant_id=TENANT, actor_id=env["actor"], of_id=of.id, report_date=datetime.date(2026, 9, 2),
        detail=_detail(env, semolina_quantity=100, regrind_input_quantity=50),
    )
    submitted = service.submit_report(
        tenant_id=TENANT, actor_id=env["actor"], report_id=created.value["report"].id
    )
    assert isinstance(submitted, Err)
    assert submitted.code == "MISSING_STOCK_TARGET"


def test_the_transformation_ratio_counts_rebroyat_as_input(db, env, of):
    from modules.production.api.of_consolidation_service import OfConsolidationService

    _validated_report(db, env, of, semolina_quantity=800, regrind_input_quantity=200,
                      regrind_input_product_id=env["rebroyat"])
    result = OfConsolidationService(db).consolidate(tenant_id=TENANT, of_id=of.id)
    assert isinstance(result, Ok)
    assert result.value["material_input_quantity"] == 1000, "semoule + rebroyat poured in"


# --- deleting a validated report --------------------------------------------


def test_deleting_a_validated_report_gives_the_stock_back(db, env, of):
    before = _on_hand(db, env["semolina"], env["location"])
    report = _validated_report(db, env, of, semolina_quantity=800)
    assert _on_hand(db, env["semolina"], env["location"]) == before - 800

    deleted = ProductionReportService(db).delete_report(
        tenant_id=TENANT, actor_id=env["actor"], report_id=report.id, reason="entered against the wrong OF"
    )
    assert isinstance(deleted, Ok), getattr(deleted, "message", "")
    assert _on_hand(db, env["semolina"], env["location"]) == before


def test_deleting_needs_a_reason(db, env, of):
    report = _validated_report(db, env, of, semolina_quantity=100)
    result = ProductionReportService(db).delete_report(
        tenant_id=TENANT, actor_id=env["actor"], report_id=report.id, reason="  "
    )
    assert isinstance(result, Err)
    assert result.code == "MISSING_REASON"


def test_a_deleted_report_leaves_its_figures_in_the_audit_trail(db, env, of):
    """The row is gone, so the audit entry is the only record it existed."""
    report = _validated_report(db, env, of, semolina_quantity=750)
    ProductionReportService(db).delete_report(
        tenant_id=TENANT, actor_id=env["actor"], report_id=report.id, reason="duplicate entry"
    )

    payload = db.execute(
        "SELECT payload FROM core.audit_log WHERE entity_id = %s AND action = 'production_report.deleted'",
        (report.id,),
    ).fetchone()
    assert payload is not None
    assert payload[0]["reason"] == "duplicate entry"
    assert payload[0]["detail"]["semolina_lines"][0]["quantity"] == 750
    assert payload[0]["status_at_deletion"] == "validated"

    assert db.execute(
        "SELECT count(*) FROM production.production_reports WHERE id = %s", (report.id,)
    ).fetchone()[0] == 0


def test_deleting_a_draft_moves_no_stock(db, env, of):
    service = ProductionReportService(db)
    created = service.create_daily_report(
        tenant_id=TENANT, actor_id=env["actor"], of_id=of.id, report_date=datetime.date(2026, 9, 3),
        detail=_detail(env, semolina_quantity=500),
    )
    moves_before = db.execute("SELECT count(*) FROM warehouse.stock_moves").fetchone()[0]

    deleted = service.delete_report(
        tenant_id=TENANT, actor_id=env["actor"], report_id=created.value["report"].id, reason="typo"
    )
    assert isinstance(deleted, Ok)
    assert db.execute("SELECT count(*) FROM warehouse.stock_moves").fetchone()[0] == moves_before


def test_deleting_also_removes_the_rebroyat_order_it_opened(db, env, of):
    report = _validated_report(db, env, of, semolina_quantity=800, regrind_quantity=40)
    assert db.execute("SELECT count(*) FROM production.regrind_batches WHERE tenant_id = %s", (TENANT,)).fetchone()[0] == 1

    ProductionReportService(db).delete_report(
        tenant_id=TENANT, actor_id=env["actor"], report_id=report.id, reason="wrong shift"
    )
    assert db.execute("SELECT count(*) FROM production.regrind_batches WHERE tenant_id = %s", (TENANT,)).fetchone()[0] == 0
    assert db.execute("SELECT count(*) FROM production.scrap_records WHERE tenant_id = %s", (TENANT,)).fetchone()[0] == 0


def test_a_completed_rebroyat_order_blocks_the_delete(db, env, of):
    """Its output is physically in stock — there is no honest way to unwind it."""
    report = _validated_report(db, env, of, semolina_quantity=800, regrind_quantity=40)
    batch_of_id = db.execute(
        "SELECT work_order_id FROM production.regrind_batches WHERE tenant_id = %s", (TENANT,)
    ).fetchone()[0]
    assigned = RegrindService(db).assign_batch(
        tenant_id=TENANT, actor_id=env["actor"], work_order_id=batch_of_id, team="Équipe A",
    )
    assert isinstance(assigned, Ok), getattr(assigned, "message", "")
    completed = RegrindService(db).complete_batch(
        tenant_id=TENANT, actor_id=env["actor"], work_order_id=batch_of_id,
        correlation_id=str(ULID()), location_id=env["location"], actual_output_quantity=38,
    )
    assert isinstance(completed, Ok), getattr(completed, "message", "")

    result = ProductionReportService(db).delete_report(
        tenant_id=TENANT, actor_id=env["actor"], report_id=report.id, reason="too late"
    )
    assert isinstance(result, Err)
    assert result.code == "REGRIND_ALREADY_COMPLETED"


# --- correcting a validated report -------------------------------------------


def test_correcting_a_validated_report_reposts_the_difference(db, env, of):
    before = _on_hand(db, env["semolina"], env["location"])
    report = _validated_report(db, env, of, semolina_quantity=800)
    assert _on_hand(db, env["semolina"], env["location"]) == before - 800

    corrected = ProductionReportService(db).correct_validated_report(
        tenant_id=TENANT, actor_id=env["actor"], report_id=report.id,
        detail=_detail(env, semolina_quantity=650), reason="silo meter over-read",
    )
    assert isinstance(corrected, Ok), getattr(corrected, "message", "")
    assert _on_hand(db, env["semolina"], env["location"]) == before - 650, "inventory follows the corrected figure"


def test_a_post_validation_correction_appends_a_revision(db, env, of):
    service = ProductionReportService(db)
    report = _validated_report(db, env, of, semolina_quantity=800)
    service.correct_validated_report(
        tenant_id=TENANT, actor_id=env["actor"], report_id=report.id,
        detail=_detail(env, semolina_quantity=650), reason="silo meter over-read",
    )

    revisions = service.list_revisions(tenant_id=TENANT, report_id=report.id)
    assert [r["revision"] for r in revisions] == [1, 2]
    assert revisions[0]["detail"]["semolina_lines"][0]["quantity"] == 800, "the team's original survives"
    assert revisions[1]["detail"]["semolina_lines"][0]["quantity"] == 650
    assert revisions[1]["reason"] == "silo meter over-read"


def test_correcting_needs_a_reason(db, env, of):
    report = _validated_report(db, env, of, semolina_quantity=800)
    result = ProductionReportService(db).correct_validated_report(
        tenant_id=TENANT, actor_id=env["actor"], report_id=report.id,
        detail=_detail(env, semolina_quantity=650), reason="",
    )
    assert isinstance(result, Err)
    assert result.code == "MISSING_REASON"


def test_the_reversal_leaves_both_movements_on_the_ledger(db, env, of):
    """History is not edited — the original and its undo both stay visible."""
    report = _validated_report(db, env, of, semolina_quantity=800)
    ProductionReportService(db).correct_validated_report(
        tenant_id=TENANT, actor_id=env["actor"], report_id=report.id,
        detail=_detail(env, semolina_quantity=650), reason="meter over-read",
    )

    moves = db.execute(
        "SELECT quantity FROM warehouse.stock_moves WHERE source_id = %s ORDER BY created_at", (report.id,)
    ).fetchall()
    assert [float(m[0]) for m in moves] == [800, 800, 650], "posted, reversed, re-posted"
