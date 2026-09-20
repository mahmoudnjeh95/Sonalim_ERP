"""Integration tests for the packaging ecart (Phase 9, decisions 17-22).

The arithmetic itself is pinned by `domain/test_packaging_estimate.py`. What is
tested here is everything the database is involved in: that a validated report
freezes the packaging it was judged against, that quality's subtraction crosses
the module boundary through qc's service rather than a join, and that the two
ecarts differ only by that subtraction.
"""
from __future__ import annotations

import datetime

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from modules.production.api.conditionnement_service import ConditionnementReportService
from modules.production.api.packaging_variance_service import (
    PackagingTolerancePolicyService,
    PackagingVarianceService,
)
from modules.production.api.production_report_service import ProductionReportService
from modules.production.api.service import WorkOrderService
from modules.production.domain.production_report import ConditionnementReportDetail, DailyReportDetail
from modules.qc.api.non_conformity_service import NonConformityService
from modules.qc.domain.non_conformity import DispositionLine
from modules.warehouse.api.service import StockService

TENANT = "integration-test-variance"


@pytest.fixture
def env(db):
    actor = str(ULID())
    uom, product, location, quarantine, work_center, equipment = (str(ULID()) for _ in range(6))
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (actor, TENANT, f"{actor}@test.local"),
    )
    db.execute(
        "INSERT INTO core.uoms (id, tenant_id, code, name, category) VALUES (%s, %s, 'ea', 'Piece', 'unit')",
        (uom, TENANT),
    )
    # The real catalogue's shape: a 500 g packet, 20 to a carton.
    db.execute(
        """
        INSERT INTO core.products (id, tenant_id, sku, name, uom_id, net_weight_grams, packets_per_carton)
        VALUES (%s, %s, 'VAR-PL-500', 'Doman PL 500gr', %s, 500, 20)
        """,
        (product, TENANT, uom),
    )
    db.execute(
        "INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, 'VAR-FG', 'Finished goods')",
        (location, TENANT),
    )
    db.execute(
        """
        INSERT INTO warehouse.locations (id, tenant_id, code, name, is_blocked, blocked_reason)
        VALUES (%s, %s, 'VAR-QUAR', 'Quarantine', TRUE, 'non-conformity')
        """,
        (quarantine, TENANT),
    )
    db.execute(
        "INSERT INTO production.work_centers (id, tenant_id, code, name) VALUES (%s, %s, 'VAR-WC', 'Line')",
        (work_center, TENANT),
    )
    db.execute(
        "INSERT INTO maintenance.equipment (id, tenant_id, work_center_id, code, name) VALUES (%s, %s, %s, 'VAR-EQ', 'Test machine')",
        (equipment, TENANT, work_center),
    )

    # Cartons are a real stock consumption, so the carton figure has to name a
    # product and a store before a report will submit.
    carton, packaging_location = str(ULID()), str(ULID())
    db.execute(
        "INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, 'VAR-PACK', 'Packaging store')",
        (packaging_location, TENANT),
    )
    db.execute(
        "INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, 'VAR-CARTON', 'Carton', %s)",
        (carton, TENANT, uom),
    )
    StockService(db).receive_stock(
        tenant_id=TENANT,
        product_id=carton,
        location_id=packaging_location,
        quantity=100_000,
        correlation_id=str(ULID()),
        reference="test-seed",
        actor_id=actor,
    )

    return {
        "actor": actor,
        "uom": uom,
        "product": product,
        "location": location,
        "quarantine": quarantine,
        "work_center": work_center,
        "equipment": equipment,
        "carton": carton,
        "packaging_location": packaging_location,
    }


@pytest.fixture
def of(db, env):
    service = WorkOrderService(db)
    created = service.create_work_order(
        tenant_id=TENANT,
        actor_id=env["actor"],
        product_id=env["product"],
        planned_quantity=25,  # tonnes, per decision 19
        work_center_id=env["work_center"],
    )
    assert isinstance(created, Ok), getattr(created, "message", "")
    service.start_work_order(tenant_id=TENANT, actor_id=env["actor"], work_order_id=created.value.id)
    return created.value


def _validated_daily_report(db, env, of, *, tonnage, date, shift):
    """Decision 25: tonnage now comes from the daily report, not the packing
    report -- so every packing report a test validates needs a matching daily
    report behind it, exactly as the real workflow would produce one."""
    reports = ProductionReportService(db)
    created = reports.create_daily_report(
        tenant_id=TENANT,
        actor_id=env["actor"],
        of_id=of.id,
        report_date=date,
        shift=shift,
        equipment_id=env["equipment"],
        detail=DailyReportDetail(finished_product_quantity=tonnage),
    )
    assert isinstance(created, Ok), getattr(created, "message", "")
    report = created.value["report"]
    submitted = reports.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)
    assert isinstance(submitted, Ok), getattr(submitted, "message", "")
    validated = reports.validate_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)
    assert isinstance(validated, Ok), getattr(validated, "message", "")


def _validated_report(db, env, of, *, tonnage, packets, cartons, date, shift="morning"):
    _validated_daily_report(db, env, of, tonnage=tonnage, date=date, shift=shift)

    created = ConditionnementReportService(db).create_report(
        tenant_id=TENANT,
        actor_id=env["actor"],
        of_id=of.id,
        report_date=date,
        shift=shift,
        equipment_id=env["equipment"],
        detail=ConditionnementReportDetail(
            packets_counted=packets,
            carton_quantity=cartons,
            carton_product_id=env["carton"],
            packaging_location_id=env["packaging_location"],
            finished_goods_location_id=env["location"],
        ),
    )
    assert isinstance(created, Ok), getattr(created, "message", "")
    report = created.value["report"]
    reports = ProductionReportService(db)
    submitted = reports.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)
    assert isinstance(submitted, Ok), getattr(submitted, "message", "")
    validated = reports.validate_report(
        tenant_id=TENANT,
        actor_id=env["actor"],
        report_id=report.id,
    )
    assert isinstance(validated, Ok), getattr(validated, "message", "")
    return report


# ---- the report-level ecart ---------------------------------------------


def test_a_report_has_no_tonnage_based_ecart_any_more(db, env, of):
    """Decision 25: a single packing report has no tonnage to compare itself
    against — that only exists at OF scope now, from the daily reports. What
    survives at report scope is machine_carton_variance, which needs none."""
    # 25 000 packets at 20 to a carton is exactly 1250 cartons: machine and
    # floor agree.
    report = _validated_report(
        db, env, of, tonnage=12.5, packets=25_000, cartons=1250, date=datetime.date(2026, 9, 1)
    )
    result = PackagingVarianceService(db).for_report(tenant_id=TENANT, report_id=report.id)
    assert isinstance(result, Ok), getattr(result, "message", "")
    variance = result.value
    assert variance["tonnage"] is None
    assert variance["expected_packets"] is None
    assert variance["expected_cartons"] is None
    assert variance["packet_variance"] is None
    assert variance["within_tolerance"] is None
    assert variance["machine_carton_variance"] == 0


def test_a_report_shows_a_machine_carton_mismatch_independent_of_tonnage(db, env, of):
    # The machine tallied 24 000 packets, but only 1150 cartons were counted --
    # 23 000 packets' worth. 1000 packets are unaccounted for on the floor,
    # regardless of what any scale said.
    report = _validated_report(
        db, env, of, tonnage=12.5, packets=24_000, cartons=1150, date=datetime.date(2026, 9, 1)
    )
    result = PackagingVarianceService(db).for_report(tenant_id=TENANT, report_id=report.id)
    variance = result.value
    assert variance["machine_carton_variance"] == 1000


def test_the_report_ecart_ignores_quality_entirely(db, env, of):
    """Decision 22: at the validation desk there usually is no NC yet, so the
    ecart shown there is deliberately the gross one. Still true for the
    machine/carton figure, which never took a quality subtraction to begin with."""
    report = _validated_report(
        db, env, of, tonnage=12.5, packets=25_000, cartons=1250, date=datetime.date(2026, 9, 1)
    )
    _raise_nc(db, env, of, quantity=500)

    variance = PackagingVarianceService(db).for_report(tenant_id=TENANT, report_id=report.id).value
    assert variance["rejected_packets"] == 0
    assert variance["machine_carton_variance"] == 0


def test_a_draft_report_can_still_be_checked(db, env, of):
    """A team that sees the ecart while typing can fix a transposed digit before
    it ever reaches the validation desk."""
    created = ConditionnementReportService(db).create_report(
        tenant_id=TENANT,
        actor_id=env["actor"],
        of_id=of.id,
        report_date=datetime.date(2026, 9, 4),
        detail=ConditionnementReportDetail(
            packets_counted=1500,
            carton_quantity=70,
            carton_product_id=env["carton"],
            packaging_location_id=env["packaging_location"],
            finished_goods_location_id=env["location"],
        ),
    )
    report = created.value["report"]
    variance = PackagingVarianceService(db).for_report(tenant_id=TENANT, report_id=report.id).value
    assert variance["report_status"] == "draft"
    # 70 cartons of 20 is 1400 packets' worth against a machine tally of 1500.
    assert variance["machine_carton_variance"] == 100
    # Nothing was frozen, so this number moves if the product is edited.
    assert variance["parameters_frozen"] is False


def test_an_unknown_report_is_a_not_found(db, env):
    result = PackagingVarianceService(db).for_report(tenant_id=TENANT, report_id=str(ULID()))
    assert isinstance(result, Err)
    assert result.code == "NOT_FOUND"


# ---- the snapshot --------------------------------------------------------


def test_validating_freezes_the_packaging_it_was_judged_against(db, env, of):
    report = _validated_report(
        db, env, of, tonnage=12.5, packets=25_000, cartons=1250, date=datetime.date(2026, 9, 1)
    )
    row = db.execute(
        """
        SELECT snapshot_net_weight_grams, snapshot_packets_per_carton
        FROM production.conditionnement_reports WHERE report_id = %s
        """,
        (report.id,),
    ).fetchone()
    assert float(row[0]) == 500
    assert float(row[1]) == 20


def test_editing_the_product_afterwards_does_not_rewrite_a_validated_ecart(db, env, of):
    """Decision 20, and the whole reason the snapshot exists: an ecart that
    changes after it was signed off is evidence of nothing. Net weight no longer
    drives anything at report scope (decision 25), but packets-per-carton still
    feeds machine_carton_variance, so editing it is still the meaningful probe."""
    report = _validated_report(
        db, env, of, tonnage=12.5, packets=25_000, cartons=1250, date=datetime.date(2026, 9, 1)
    )
    before = PackagingVarianceService(db).for_report(tenant_id=TENANT, report_id=report.id).value
    assert before["machine_carton_variance"] == 0

    db.execute(
        "UPDATE core.products SET packets_per_carton = 10 WHERE id = %s AND tenant_id = %s",
        (env["product"], TENANT),
    )

    after = PackagingVarianceService(db).for_report(tenant_id=TENANT, report_id=report.id).value
    assert after["packets_per_carton"] == 20
    assert after["machine_carton_variance"] == 0
    assert after["parameters_frozen"] is True


# ---- the OF-level ecart net ---------------------------------------------


def _raise_nc(db, env, of, *, quantity, disposition=None):
    service = NonConformityService(db)
    raised = service.raise_non_conformity(
        tenant_id=TENANT,
        actor_id=env["actor"],
        of_id=of.id,
        product_id=env["product"],
        quantity=quantity,
        source_location_id=env["location"],
        quarantine_location_id=env["quarantine"],
        defect_type="broken",
        correlation_id=str(ULID()),
    )
    assert isinstance(raised, Ok), getattr(raised, "message", "")
    nc = raised.value
    nc_id = nc["id"] if isinstance(nc, dict) else nc.id
    if disposition is not None:
        done = service.disposition(
            tenant_id=TENANT,
            actor_id=env["actor"],
            non_conformity_id=nc_id,
            lines=(DispositionLine(component="product", disposition=disposition, quantity=quantity),),
            correlation_id=str(ULID()),
        )
        assert isinstance(done, Ok), getattr(done, "message", "")
    return nc_id


def test_the_of_ecart_sums_every_validated_shift(db, env, of):
    _validated_report(db, env, of, tonnage=12.5, packets=25_000, cartons=1250, date=datetime.date(2026, 9, 1))
    _validated_report(
        db, env, of, tonnage=10, packets=20_000, cartons=1000, date=datetime.date(2026, 9, 1), shift="evening"
    )
    variance = PackagingVarianceService(db).for_of(tenant_id=TENANT, of_id=of.id).value
    assert variance["report_count"] == 2
    assert variance["tonnage"] == 22.5
    assert variance["counted_packets"] == 45_000
    assert variance["expected_packets"] == 45_000
    assert variance["packet_variance"] == 0


def test_an_open_non_conformity_subtracts_and_is_reported_as_undecided(db, env, of):
    """Decision 21: through quarantine the product is genuinely not sellable, so
    it subtracts — but it is shown separately so it does not read as a loss."""
    _validated_report(db, env, of, tonnage=12.5, packets=25_000, cartons=1250, date=datetime.date(2026, 9, 1))
    _raise_nc(db, env, of, quantity=500)

    variance = PackagingVarianceService(db).for_of(tenant_id=TENANT, of_id=of.id).value
    assert variance["rejected_packets"] == 500
    assert variance["undecided_packets"] == 500
    assert variance["good_packets"] == 24_500
    assert variance["packet_variance"] == -500


def test_product_sent_to_dechet_stays_subtracted_once_dispositioned(db, env, of):
    _validated_report(db, env, of, tonnage=12.5, packets=25_000, cartons=1250, date=datetime.date(2026, 9, 1))
    _raise_nc(db, env, of, quantity=500, disposition="dechet")

    variance = PackagingVarianceService(db).for_of(tenant_id=TENANT, of_id=of.id).value
    assert variance["rejected_packets"] == 500
    # Settled, so no longer awaiting a decision.
    assert variance["undecided_packets"] == 0
    assert variance["packet_variance"] == -500


def test_product_returned_to_stock_does_not_subtract(db, env, of):
    """The half of decision 21 that "dispositioned only" would have got wrong in
    the other direction: what came back is not a loss."""
    _validated_report(db, env, of, tonnage=12.5, packets=25_000, cartons=1250, date=datetime.date(2026, 9, 1))
    _raise_nc(db, env, of, quantity=500, disposition="return_to_stock")

    variance = PackagingVarianceService(db).for_of(tenant_id=TENANT, of_id=of.id).value
    assert variance["rejected_packets"] == 0
    assert variance["packet_variance"] == 0


def test_cartons_are_not_reduced_by_a_rejection(db, env, of):
    """Quality pulls packets out of cartons; it does not un-build the carton."""
    _validated_report(db, env, of, tonnage=12.5, packets=25_000, cartons=1250, date=datetime.date(2026, 9, 1))
    _raise_nc(db, env, of, quantity=500)

    variance = PackagingVarianceService(db).for_of(tenant_id=TENANT, of_id=of.id).value
    assert variance["carton_variance"] == 0


def test_a_draft_report_is_not_in_the_of_ecart(db, env, of):
    _validated_report(db, env, of, tonnage=12.5, packets=25_000, cartons=1250, date=datetime.date(2026, 9, 1))
    ConditionnementReportService(db).create_report(
        tenant_id=TENANT,
        actor_id=env["actor"],
        of_id=of.id,
        report_date=datetime.date(2026, 9, 2),
        detail=ConditionnementReportDetail(
            finished_product_quantity=99, packets_counted=99, finished_goods_location_id=env["location"]
        ),
    )
    variance = PackagingVarianceService(db).for_of(tenant_id=TENANT, of_id=of.id).value
    assert variance["report_count"] == 1
    assert variance["tonnage"] == 12.5


def test_an_of_with_nothing_packed_yet_reports_zeroes_not_an_error(db, env, of):
    result = PackagingVarianceService(db).for_of(tenant_id=TENANT, of_id=of.id)
    assert isinstance(result, Ok)
    assert result.value["report_count"] == 0
    assert result.value["counted_packets"] == 0
    assert result.value["packet_variance_ratio"] is None


def test_an_unknown_of_is_a_not_found(db, env):
    result = PackagingVarianceService(db).for_of(tenant_id=TENANT, of_id=str(ULID()))
    assert isinstance(result, Err)
    assert result.code == "NOT_FOUND"


# ---- the boundary --------------------------------------------------------


def test_nothing_here_reads_qcs_tables_directly(db):
    """Decision 13 and the module contract: production calls qc's service."""
    import inspect

    from modules.production.api import packaging_variance_service

    source = inspect.getsource(packaging_variance_service)
    assert "qc.non_conformities" not in source
    assert "qc.nc_dispositions" not in source
    assert "NonConformityService" in source


def test_the_ecart_never_refuses_a_validation(db, env, of):
    """Decision 22. A wildly wrong ecart still validates — it is a figure, not a
    gate. The tonnage-based figure now only exists at OF scope (decision 25)."""
    report = _validated_report(
        db, env, of, tonnage=12.5, packets=1, cartons=1, date=datetime.date(2026, 9, 1)
    )
    status = db.execute(
        "SELECT status FROM production.production_reports WHERE id = %s", (report.id,)
    ).fetchone()[0]
    assert status == "validated"
    PackagingTolerancePolicyService(db).set_policy(tenant_id=TENANT, actor_id=env["actor"], tolerance_percent=2)
    variance = PackagingVarianceService(db).for_of(tenant_id=TENANT, of_id=of.id).value
    assert variance["packet_variance"] == -24_999
    assert variance["within_tolerance"] is False


# ---- the tolerance -------------------------------------------------------


def test_with_no_tolerance_configured_there_is_none_to_resolve(db, env):
    resolved = PackagingTolerancePolicyService(db).resolve_tolerance_percent(
        tenant_id=TENANT, product_id=env["product"]
    )
    assert resolved is None


def test_an_unconfigured_tolerance_leaves_the_ecart_unjudged(db, env, of):
    _validated_report(db, env, of, tonnage=12.5, packets=24_750, cartons=1240, date=datetime.date(2026, 9, 1))
    variance = PackagingVarianceService(db).for_of(tenant_id=TENANT, of_id=of.id).value
    assert variance["packet_variance"] == -250
    assert variance["tolerance_percent"] is None
    assert variance["within_tolerance"] is None


def test_a_product_override_beats_the_tenant_default(db, env):
    policies = PackagingTolerancePolicyService(db)
    policies.set_policy(tenant_id=TENANT, actor_id=env["actor"], tolerance_percent=5)
    policies.set_policy(
        tenant_id=TENANT, actor_id=env["actor"], tolerance_percent=1, product_id=env["product"]
    )
    assert policies.resolve_tolerance_percent(tenant_id=TENANT, product_id=env["product"]) == 1
    assert policies.resolve_tolerance_percent(tenant_id=TENANT, product_id=str(ULID())) == 5


def test_the_tolerance_changes_the_colour_not_the_figures(db, env, of):
    """Tolerance is judged against the packet variance, which now only exists at
    OF scope (decision 25)."""
    _validated_report(db, env, of, tonnage=12.5, packets=24_750, cartons=1240, date=datetime.date(2026, 9, 1))
    service = PackagingVarianceService(db)
    PackagingTolerancePolicyService(db).set_policy(tenant_id=TENANT, actor_id=env["actor"], tolerance_percent=2)
    strict = service.for_of(tenant_id=TENANT, of_id=of.id).value
    assert strict["packet_variance"] == -250
    assert strict["within_tolerance"] is True  # -1% against the 2% the plant configured

    PackagingTolerancePolicyService(db).set_policy(
        tenant_id=TENANT, actor_id=env["actor"], tolerance_percent=0.5, product_id=env["product"]
    )
    tightened = service.for_of(tenant_id=TENANT, of_id=of.id).value
    assert tightened["packet_variance"] == -250
    assert tightened["within_tolerance"] is False


# ---- the warehouse view --------------------------------------------------


def test_by_product_groups_the_period_and_lists_its_reports(db, env, of):
    _validated_report(db, env, of, tonnage=12.5, packets=25_000, cartons=1250, date=datetime.date(2026, 9, 1))
    _validated_report(
        db, env, of, tonnage=10, packets=19_500, cartons=975, date=datetime.date(2026, 9, 2)
    )

    rows = PackagingVarianceService(db).by_product(tenant_id=TENANT)
    row = next(r for r in rows if r["product_id"] == env["product"])
    assert row["report_count"] == 2
    assert row["tonnage"] == 22.5
    assert row["counted_packets"] == 44_500
    assert row["packet_variance"] == -500
    assert [r["report_date"] for r in row["reports"]] == ["2026-09-01", "2026-09-02"]
    # The per-report rows are gross: quality attaches to an OF, not to a date.
    assert all(r["rejected_packets"] == 0 for r in row["reports"])


def test_by_product_respects_the_period(db, env, of):
    _validated_report(db, env, of, tonnage=12.5, packets=25_000, cartons=1250, date=datetime.date(2026, 9, 1))
    _validated_report(db, env, of, tonnage=10, packets=20_000, cartons=1000, date=datetime.date(2026, 9, 20))

    rows = PackagingVarianceService(db).by_product(
        tenant_id=TENANT, date_from="2026-09-15", date_to="2026-09-30"
    )
    row = next(r for r in rows if r["product_id"] == env["product"])
    assert row["report_count"] == 1
    assert row["tonnage"] == 10
