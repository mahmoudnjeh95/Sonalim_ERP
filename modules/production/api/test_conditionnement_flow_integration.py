"""Integration tests for the conditionnement report (Phase 3).

The point of this phase is that the packing report reuses the daily report's
header, status machine and revision snapshots rather than growing a parallel one —
so most of what is asserted here is that the *shared* machinery still behaves when
the detail is a different shape. Plus the one thing that is genuinely new: a
validated DLC becomes a real warehouse lot, written through the warehouse service.
"""
from __future__ import annotations

import datetime

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from modules.production.api.conditionnement_service import ConditionnementReportService
from modules.production.api.production_report_service import ProductionReportService
from modules.production.api.service import WorkOrderService
from modules.warehouse.api.service import StockService
from modules.production.domain.production_report import ConditionnementReportDetail

TENANT = "integration-test-cond"


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
        "INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, 'TEST-PACK', 'Test packet', %s)",
        (product, TENANT, uom),
    )
    db.execute(
        "INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, 'TEST-LOC', 'Test location')",
        (location, TENANT),
    )
    db.execute(
        "INSERT INTO production.work_centers (id, tenant_id, code, name) VALUES (%s, %s, 'TEST-WC', 'Test line')",
        (work_center, TENANT),
    )

    film, carton, tape = (str(ULID()) for _ in range(3))
    packaging_location = str(ULID())
    db.execute(
        "INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, 'PACK', 'Packaging store')",
        (packaging_location, TENANT),
    )
    stock = StockService(db)
    for product_id, sku in ((film, "TEST-FILM"), (carton, "TEST-CARTON"), (tape, "TEST-TAPE")):
        db.execute(
            "INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, %s, %s, %s)",
            (product_id, TENANT, sku, sku, uom),
        )
        stock.receive_stock(
            tenant_id=TENANT,
            product_id=product_id,
            location_id=packaging_location,
            quantity=10_000,
            correlation_id=str(ULID()),
            reference="test-seed",
            actor_id=actor,
        )

    return {
        "actor": actor,
        "product": product,
        "location": location,
        "work_center": work_center,
        "film": film,
        "carton": carton,
        "tape": tape,
        "packaging_location": packaging_location,
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
    )
    assert isinstance(created, Ok), getattr(created, "message", "")
    service.start_work_order(tenant_id=TENANT, actor_id=env["actor"], work_order_id=created.value.id)
    return created.value


def _report(db, env, of, **detail_kwargs):
    # A packing report that moves stock must name the products and stores involved.
    detail_kwargs.setdefault("film_product_id", env["film"])
    detail_kwargs.setdefault("carton_product_id", env["carton"])
    detail_kwargs.setdefault("tape_product_id", env["tape"])
    detail_kwargs.setdefault("packaging_location_id", env["packaging_location"])
    detail_kwargs.setdefault("finished_goods_location_id", env["location"])
    result = ConditionnementReportService(db).create_report(
        tenant_id=TENANT,
        actor_id=env["actor"],
        of_id=of.id,
        report_date=datetime.date(2026, 9, 1),
        team="B",
        shift="afternoon",
        detail=ConditionnementReportDetail(**detail_kwargs),
    )
    assert isinstance(result, Ok), getattr(result, "message", "")
    return result.value["report"]


def test_create_defaults_the_work_center_from_the_of(db, env, of):
    report = _report(db, env, of, finished_product_quantity=800, film_quantity=40)
    assert report.report_type == "conditionnement"
    assert report.status == "draft"
    assert report.revision == 1
    assert report.work_center_id == env["work_center"]


def test_a_dlc_needs_both_a_lot_number_and_a_date(db, env, of):
    service = ConditionnementReportService(db)
    half = service.create_report(
        tenant_id=TENANT,
        actor_id=env["actor"],
        of_id=of.id,
        report_date=datetime.date(2026, 9, 1),
        detail=ConditionnementReportDetail(lot_number="L-1"),
    )
    assert isinstance(half, Err)
    assert half.code == "INCOMPLETE_DLC"

    other_half = service.create_report(
        tenant_id=TENANT,
        actor_id=env["actor"],
        of_id=of.id,
        report_date=datetime.date(2026, 9, 1),
        detail=ConditionnementReportDetail(dlc_date=datetime.date(2027, 9, 1)),
    )
    assert isinstance(other_half, Err)
    assert other_half.code == "INCOMPLETE_DLC"


def test_the_shared_submit_and_revision_machinery_works_for_packing(db, env, of):
    """Phase 2's submit no longer assumes a daily detail — this is that fix, asserted."""
    reports = ProductionReportService(db)
    report = _report(db, env, of, finished_product_quantity=800, film_quantity=40, carton_quantity=20)

    submitted = reports.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)
    assert isinstance(submitted, Ok), getattr(submitted, "message", "")

    revisions = reports.list_revisions(tenant_id=TENANT, report_id=report.id)
    assert [r["revision"] for r in revisions] == [1]
    assert revisions[0]["detail"]["finished_product_quantity"] == 800
    assert revisions[0]["detail"]["film_quantity"] == 40


def test_a_correction_appends_without_overwriting(db, env, of):
    reports = ProductionReportService(db)
    service = ConditionnementReportService(db)
    report = _report(db, env, of, finished_product_quantity=800, carton_quantity=20)
    reports.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)

    corrected = service.correct_report(
        tenant_id=TENANT,
        actor_id=env["actor"],
        report_id=report.id,
        detail=ConditionnementReportDetail(
            finished_product_quantity=780,
            carton_quantity=20,
            carton_product_id=env["carton"],
            packaging_location_id=env["packaging_location"],
            finished_goods_location_id=env["location"],
        ),
        reason="pallet miscount at the end of the shift",
    )
    assert isinstance(corrected, Ok), getattr(corrected, "message", "")

    revisions = reports.list_revisions(tenant_id=TENANT, report_id=report.id)
    assert [r["revision"] for r in revisions] == [1, 2]
    assert revisions[0]["detail"]["finished_product_quantity"] == 800, "the team's original must survive"
    assert revisions[1]["detail"]["finished_product_quantity"] == 780
    assert revisions[1]["reason"] == "pallet miscount at the end of the shift"


def test_validating_registers_the_dlc_as_a_real_lot(db, env, of):
    reports = ProductionReportService(db)
    report = _report(
        db, env, of,
        finished_product_quantity=800,
        film_quantity=40,
        lot_number="LOT-2026-244",
        dlc_date=datetime.date(2027, 9, 1),
    )
    reports.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)

    lots_before = db.execute("SELECT count(*) FROM warehouse.lots WHERE tenant_id = %s", (TENANT,)).fetchone()[0]
    assert lots_before == 0

    validated = reports.validate_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)
    assert isinstance(validated, Ok), getattr(validated, "message", "")

    lot_number, expiry, source_type, source_id, product_id = db.execute(
        "SELECT lot_number, expiry_date, source_type, source_id, product_id FROM warehouse.lots WHERE tenant_id = %s",
        (TENANT,),
    ).fetchone()
    assert lot_number == "LOT-2026-244"
    assert expiry == datetime.date(2027, 9, 1)
    assert source_type == "production.conditionnement_report"
    assert source_id == report.id
    assert product_id == env["product"], "the lot belongs to the OF's product"


def _on_hand(db, tenant, product_id, location_id) -> float:
    row = db.execute(
        "SELECT quantity_on_hand FROM warehouse.stock_items WHERE tenant_id = %s AND product_id = %s AND location_id = %s",
        (tenant, product_id, location_id),
    ).fetchone()
    return float(row[0]) if row else 0.0


def test_validating_brings_the_finished_product_in_and_packaging_out(db, env, of):
    """The conditionnement report owns the finished tonnage — this is where it
    becomes sellable stock, and the only place packaging is ever deducted.

    What enters stock is `packets_counted`, the tally (Phase 9, decision 18), not
    the tonnage beside it."""
    reports = ProductionReportService(db)
    report = _report(
        db, env, of,
        finished_product_quantity=0.4,
        packets_counted=800,
        film_quantity=40,
        carton_quantity=20,
        tape_quantity=5,
    )
    reports.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)

    finished_before = _on_hand(db, TENANT, env["product"], env["location"])
    film_before = _on_hand(db, TENANT, env["film"], env["packaging_location"])

    validated = reports.validate_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)
    assert isinstance(validated, Ok), getattr(validated, "message", "")

    assert _on_hand(db, TENANT, env["product"], env["location"]) == finished_before + 800
    assert _on_hand(db, TENANT, env["film"], env["packaging_location"]) == film_before - 40
    assert _on_hand(db, TENANT, env["carton"], env["packaging_location"]) == 10_000 - 20
    assert _on_hand(db, TENANT, env["tape"], env["packaging_location"]) == 10_000 - 5


def test_a_cartoned_product_posts_the_carton_count_not_the_machine_tally(db, env, of):
    """Phase 9, decision 24. For a product with a carton tier, the floor's own
    carton count decides what enters stock -- not the packaging machine's HMI
    tally, which can drift from what was actually boxed."""
    db.execute(
        "UPDATE core.products SET net_weight_grams = 500, packets_per_carton = 20 WHERE id = %s AND tenant_id = %s",
        (env["product"], TENANT),
    )
    reports = ProductionReportService(db)
    report = _report(
        db, env, of,
        finished_product_quantity=1,
        packets_counted=2000,  # the machine's tally
        carton_quantity=95,  # the floor's count: 95 * 20 = 1900, not 2000
    )
    reports.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)

    before = _on_hand(db, TENANT, env["product"], env["location"])
    validated = reports.validate_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)
    assert isinstance(validated, Ok), getattr(validated, "message", "")

    assert _on_hand(db, TENANT, env["product"], env["location"]) == before + 1900


def test_a_cartoned_product_with_no_cartons_yet_falls_back_to_the_machine_tally(db, env, of):
    """A cartoned product that has not been boxed yet still gets its finished
    product recorded -- a loose packet is not nothing, it is just not what the
    carton count can speak to."""
    db.execute(
        "UPDATE core.products SET net_weight_grams = 500, packets_per_carton = 20 WHERE id = %s AND tenant_id = %s",
        (env["product"], TENANT),
    )
    reports = ProductionReportService(db)
    report = _report(db, env, of, finished_product_quantity=1, packets_counted=2000, carton_quantity=0)
    reports.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)

    before = _on_hand(db, TENANT, env["product"], env["location"])
    validated = reports.validate_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)
    assert isinstance(validated, Ok), getattr(validated, "message", "")

    assert _on_hand(db, TENANT, env["product"], env["location"]) == before + 2000


def test_the_tonnage_moves_nothing_on_its_own(db, env, of):
    """Phase 9, decision 18. A report that weighed product but counted no packets
    posts no finished product at all.

    This is the boundary the whole ecart rests on: if the tonnage posted, stock
    would be the estimate and the ecart could never show up in it."""
    reports = ProductionReportService(db)
    report = _report(db, env, of, finished_product_quantity=12.5, packets_counted=0)
    reports.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)

    before = _on_hand(db, TENANT, env["product"], env["location"])
    validated = reports.validate_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)
    assert isinstance(validated, Ok), getattr(validated, "message", "")

    assert _on_hand(db, TENANT, env["product"], env["location"]) == before


def test_the_finished_product_is_the_ofs_product(db, env, of):
    """The report does not restate it, so it cannot contradict the order."""
    reports = ProductionReportService(db)
    report = _report(db, env, of, finished_product_quantity=0.4, packets_counted=800)
    reports.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)
    reports.validate_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)

    product_id = db.execute(
        "SELECT product_id FROM warehouse.stock_moves WHERE source_id = %s AND move_type = 'production'",
        (report.id,),
    ).fetchone()[0]
    assert product_id == env["product"]


def test_the_lot_gets_its_stock_when_the_report_is_validated(db, env, of):
    reports = ProductionReportService(db)
    report = _report(
        db, env, of,
        finished_product_quantity=800,
        lot_number="LOT-2026-245",
        dlc_date=datetime.date(2027, 9, 1),
    )
    reports.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)
    reports.validate_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)

    lot_number, expiry = db.execute(
        "SELECT lot_number, expiry_date FROM warehouse.lots WHERE tenant_id = %s", (TENANT,)
    ).fetchone()
    assert lot_number == "LOT-2026-245"
    assert expiry == datetime.date(2027, 9, 1)


def test_validating_without_a_dlc_registers_no_lot(db, env, of):
    reports = ProductionReportService(db)
    report = _report(db, env, of, finished_product_quantity=800)
    reports.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)
    reports.validate_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)

    lots = db.execute("SELECT count(*) FROM warehouse.lots WHERE tenant_id = %s", (TENANT,)).fetchone()[0]
    assert lots == 0


def test_validating_twice_is_still_refused(db, env, of):
    reports = ProductionReportService(db)
    report = _report(
        db, env, of, finished_product_quantity=800, lot_number="LOT-A", dlc_date=datetime.date(2027, 1, 1)
    )
    reports.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)
    assert isinstance(reports.validate_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id), Ok)

    second = reports.validate_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)
    assert isinstance(second, Err)
    assert second.code == "INVALID_TRANSITION"

    lots = db.execute("SELECT count(*) FROM warehouse.lots WHERE tenant_id = %s", (TENANT,)).fetchone()[0]
    assert lots == 1, "a refused second validate must not register a second lot"


def test_a_daily_service_will_not_edit_a_packing_report(db, env, of):
    report = _report(db, env, of, finished_product_quantity=800)
    from modules.production.domain.production_report import DailyReportDetail

    result = ProductionReportService(db).update_daily_draft(
        tenant_id=TENANT, actor_id=env["actor"], report_id=report.id, detail=DailyReportDetail()
    )
    assert isinstance(result, Err)
    assert result.code == "WRONG_REPORT_TYPE"


def test_get_report_returns_the_packing_detail(db, env, of):
    report = _report(db, env, of, finished_product_quantity=800, tape_quantity=5, machine_speed=42.5)
    fetched = ProductionReportService(db).get_report(tenant_id=TENANT, report_id=report.id)
    assert fetched is not None
    assert isinstance(fetched["detail"], ConditionnementReportDetail)
    assert fetched["detail"].tape_quantity == 5
    assert fetched["detail"].machine_speed == 42.5
