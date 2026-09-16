"""Integration tests for the OF-centred rebuild, against a real database.

These cover what the domain unit tests cannot: that the SQL actually runs, that the
row-level guards hold, and — above all — that the OF lifecycle posts no stock while
report validation and regrind do. Phase 5 makes validation move inventory, so the
"posted nothing" assertions here are the regression net for that work.

Every test runs inside the `db` fixture's transaction and is rolled back, so they
are safe against a development database. They skip when none is reachable.
"""
from __future__ import annotations

import datetime

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from modules.production.api.production_report_service import ProductionReportService
from modules.production.api.regrind_service import RegrindDefaultsService, RegrindService
from modules.warehouse.api.service import StockService
from modules.production.api.service import WorkOrderService
from modules.production.domain.production_report import DailyReportDetail, SemolinaLine

TENANT = "integration-test"


@pytest.fixture
def env(db):
    """Reference rows this module's foreign keys require, created in-transaction.

    Built here rather than read from whatever the database happens to hold, so the
    tests pass on any migrated database — seeded or empty.
    """
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
        "INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, 'TEST-PASTA', 'Test pasta', %s)",
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
    db.execute(
        "INSERT INTO maintenance.equipment (id, tenant_id, work_center_id, code, name) VALUES (%s, %s, %s, 'TEST-EQ', 'Test machine')",
        (equipment, TENANT, work_center),
    )

    # Stock for the line to consume. Without this every validated report would be a
    # shortfall, which is a real case but not the ordinary one.
    StockService(db).receive_stock(
        tenant_id=TENANT,
        product_id=product,
        location_id=location,
        quantity=100_000,
        correlation_id=str(ULID()),
        reference="test-seed",
        actor_id=actor,
    )
    return {
        "actor": actor,
        "product": product,
        "location": location,
        "work_center": work_center,
        "equipment": equipment,
    }


def _configure_regrind(db, env):
    """Rebroyat cannot open its own OF without knowing what the regrind yields."""
    result = RegrindDefaultsService(db).set_default(
        tenant_id=TENANT, actor_id=env["actor"], output_product_id=env["product"]
    )
    assert isinstance(result, Ok), getattr(result, "message", "")


def _open_of(db, env, status: str = "ongoing"):
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
    order = created.value
    if status != "planned":
        assert isinstance(service.start_work_order(tenant_id=TENANT, actor_id=env["actor"], work_order_id=order.id), Ok)
    return order


def _stock_move_count(db) -> int:
    return db.execute("SELECT count(*) FROM warehouse.stock_moves").fetchone()[0]


def _detail(env, **kwargs):
    # A single-line convenience over the real (list-shaped) semolina_lines field:
    # most tests only care about one quality, so semolina_quantity/product_id
    # still work as a shorthand and are translated into one line here.
    semolina_lines = kwargs.pop("semolina_lines", None)
    semolina_quantity = kwargs.pop("semolina_quantity", 0)
    semolina_product_id = kwargs.pop("semolina_product_id", env["product"])
    semolina_location_id = kwargs.pop("semolina_location_id", env["location"])
    if semolina_lines is None:
        semolina_lines = (
            SemolinaLine(product_id=semolina_product_id, quantity=semolina_quantity, location_id=semolina_location_id),
        )
    kwargs.setdefault("raw_material_location_id", env["location"])
    return DailyReportDetail(semolina_lines=semolina_lines, **kwargs)


def _draft_report(db, env, of_id, report_date=datetime.date(2026, 9, 1), shift="morning", **detail_kwargs):
    # A report that moves stock must name what it moves and from where, so the
    # helper supplies those targets unless a test overrides them.
    result = ProductionReportService(db).create_daily_report(
        tenant_id=TENANT,
        actor_id=env["actor"],
        of_id=of_id,
        report_date=report_date,
        team="A",
        shift=shift,
        equipment_id=env["equipment"],
        detail=_detail(env, **detail_kwargs),
    )
    assert isinstance(result, Ok), getattr(result, "message", "")
    return result.value["report"]


# --- the OF moves nothing ---------------------------------------------------


def test_the_whole_of_lifecycle_posts_no_stock(db, env):
    """The pivot, asserted: create, start, suspend, resume and close move nothing."""
    service = WorkOrderService(db)
    before = _stock_move_count(db)

    order = _open_of(db, env, status="planned")
    assert order.status == "planned"
    assert isinstance(service.start_work_order(tenant_id=TENANT, actor_id=env["actor"], work_order_id=order.id), Ok)
    assert isinstance(
        service.suspend_work_order(tenant_id=TENANT, actor_id=env["actor"], work_order_id=order.id, reason="press jam"),
        Ok,
    )
    assert isinstance(service.resume_work_order(tenant_id=TENANT, actor_id=env["actor"], work_order_id=order.id), Ok)
    closed = service.close_work_order(
        tenant_id=TENANT, actor_id=env["actor"], work_order_id=order.id, correlation_id=str(ULID())
    )
    assert isinstance(closed, Ok)
    assert closed.value.closed_at is not None
    assert closed.value.closed_by == env["actor"]

    assert _stock_move_count(db) == before


def test_a_running_of_cannot_be_cancelled_without_suspending_first(db, env):
    order = _open_of(db, env)
    result = WorkOrderService(db).cancel_work_order(
        tenant_id=TENANT, actor_id=env["actor"], work_order_id=order.id
    )
    assert isinstance(result, Err)
    assert result.code == "INVALID_TRANSITION"


def test_the_status_column_rejects_the_old_vocabulary(db, env):
    """The database itself refuses draft/in_progress/completed after the rebuild."""
    import psycopg

    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(
            "INSERT INTO production.work_orders "
            "(id, tenant_id, reference, product_id, planned_quantity, status, work_center_id) "
            "VALUES (%s, %s, 'OF-X', %s, 1, 'in_progress', %s)",
            (str(ULID()), TENANT, env["product"], env["work_center"]),
        )


def test_an_of_must_name_its_work_center(db, env):
    """Locked decision 3, enforced by the schema as well as the service."""
    import psycopg

    result = WorkOrderService(db).create_work_order(
        tenant_id=TENANT, actor_id=env["actor"], product_id=env["product"], planned_quantity=100, work_center_id="  "
    )
    assert isinstance(result, Err)
    assert result.code == "MISSING_WORK_CENTER"

    with pytest.raises(psycopg.errors.NotNullViolation):
        db.execute(
            "INSERT INTO production.work_orders (id, tenant_id, reference, product_id, planned_quantity, status) "
            "VALUES (%s, %s, 'OF-Y', %s, 1, 'planned')",
            (str(ULID()), TENANT, env["product"]),
        )


# --- supervisor --------------------------------------------------------------


def test_an_of_can_be_created_and_later_given_a_supervisor(db, env):
    """Unlike work_center_id, supervisor_id is never required -- it can be left
    unset at creation and named later through the edit form."""
    service = WorkOrderService(db)
    created = service.create_work_order(
        tenant_id=TENANT, actor_id=env["actor"], product_id=env["product"],
        planned_quantity=100, work_center_id=env["work_center"],
    )
    assert isinstance(created, Ok), getattr(created, "message", "")
    assert created.value.supervisor_id is None

    updated = service.admin_update_work_order(
        tenant_id=TENANT, actor_id=env["actor"], work_order_id=created.value.id, supervisor_id=env["actor"],
    )
    assert isinstance(updated, Ok), getattr(updated, "message", "")
    assert updated.value.supervisor_id == env["actor"]

    reloaded = service.get_work_order(tenant_id=TENANT, work_order_id=created.value.id)
    assert reloaded.supervisor_id == env["actor"]


def test_an_of_can_name_its_supervisor_at_creation(db, env):
    service = WorkOrderService(db)
    created = service.create_work_order(
        tenant_id=TENANT, actor_id=env["actor"], product_id=env["product"],
        planned_quantity=100, work_center_id=env["work_center"], supervisor_id=env["actor"],
    )
    assert isinstance(created, Ok), getattr(created, "message", "")
    assert created.value.supervisor_id == env["actor"]


def test_supervisor_options_are_scoped_to_the_production_role(db, env):
    """Finance/CRM/etc. accounts must never show up in the OF supervisor picker."""
    role_production, role_finance = str(ULID()), str(ULID())
    production_user, finance_user = str(ULID()), str(ULID())
    db.execute(
        "INSERT INTO core.roles (id, tenant_id, code, name) VALUES (%s, %s, 'production', 'Production')",
        (role_production, TENANT),
    )
    db.execute(
        "INSERT INTO core.roles (id, tenant_id, code, name) VALUES (%s, %s, 'finance', 'Finance')",
        (role_finance, TENANT),
    )
    for user_id, email in ((production_user, "floor-lead@test.local"), (finance_user, "accountant@test.local")):
        db.execute(
            "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
            (user_id, TENANT, email),
        )
    db.execute(
        "INSERT INTO core.user_roles (user_id, role_id) VALUES (%s, %s)", (production_user, role_production)
    )
    db.execute(
        "INSERT INTO core.user_roles (user_id, role_id) VALUES (%s, %s)", (finance_user, role_finance)
    )

    options = WorkOrderService(db).list_supervisor_options(tenant_id=TENANT)
    emails = {o["email"] for o in options}
    assert "floor-lead@test.local" in emails
    assert "accountant@test.local" not in emails


# --- revision snapshots -----------------------------------------------------


def test_submitting_freezes_the_teams_figures(db, env):
    service = ProductionReportService(db)
    order = _open_of(db, env)
    report = _draft_report(db, env, order.id, semolina_quantity=1000, regrind_quantity=50)

    assert isinstance(service.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id), Ok)
    revisions = service.list_revisions(tenant_id=TENANT, report_id=report.id)
    assert [r["revision"] for r in revisions] == [1]
    assert revisions[0]["detail"]["regrind_quantity"] == 50
    assert revisions[0]["reason"] is None


def test_a_correction_never_overwrites_what_the_team_submitted(db, env):
    """The whole control: without this, a good yield cannot be told from a typed one."""
    service = ProductionReportService(db)
    order = _open_of(db, env)
    report = _draft_report(db, env, order.id, semolina_quantity=1000, regrind_quantity=50)
    service.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)

    corrected = service.correct_daily_report(
        tenant_id=TENANT,
        actor_id=env["actor"],
        report_id=report.id,
        detail=_detail(env, semolina_quantity=1000, regrind_quantity=65),
        reason="meter misread on the rebroyat line",
    )
    assert isinstance(corrected, Ok), getattr(corrected, "message", "")

    revisions = service.list_revisions(tenant_id=TENANT, report_id=report.id)
    assert [r["revision"] for r in revisions] == [1, 2]
    assert revisions[0]["detail"]["regrind_quantity"] == 50, "the team's original must survive"
    assert revisions[1]["detail"]["regrind_quantity"] == 65
    assert revisions[1]["reason"] == "meter misread on the rebroyat line"


def test_a_correction_must_say_why(db, env):
    service = ProductionReportService(db)
    order = _open_of(db, env)
    report = _draft_report(db, env, order.id, semolina_quantity=1000)
    service.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)

    result = service.correct_daily_report(
        tenant_id=TENANT, actor_id=env["actor"], report_id=report.id, detail=DailyReportDetail(), reason="   "
    )
    assert isinstance(result, Err)
    assert result.code == "MISSING_REASON"


def test_a_validated_report_cannot_be_corrected(db, env):
    """Its figures have posted stock from Phase 5 on; changing them needs a reversal."""
    service = ProductionReportService(db)
    order = _open_of(db, env)
    report = _draft_report(db, env, order.id, semolina_quantity=1000)
    service.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)
    service.validate_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)

    result = service.correct_daily_report(
        tenant_id=TENANT, actor_id=env["actor"], report_id=report.id, detail=DailyReportDetail(), reason="late fix"
    )
    assert isinstance(result, Err)
    assert result.code == "NOT_CORRECTABLE"


# --- gasoil, start time, and the audit trail behind History -----------------


def test_gasoil_and_start_time_round_trip(db, env):
    """Gasoil is a separate fuel from fuel_quantity (fioul), and start_time is
    a plain clock reading — neither had anywhere to be exercised before."""
    service = ProductionReportService(db)
    order = _open_of(db, env)
    report = _draft_report(
        db, env, order.id, semolina_quantity=1000,
        fuel_quantity=12.5, gasoil_quantity=7.0, start_time=datetime.time(6, 30),
    )
    detail = service.get_report(tenant_id=TENANT, report_id=report.id)["detail"]
    assert detail.fuel_quantity == 12.5
    assert detail.gasoil_quantity == 7.0
    assert detail.start_time == datetime.time(6, 30)


def test_gasoil_cannot_be_negative(db, env):
    order = _open_of(db, env)
    result = ProductionReportService(db).create_daily_report(
        tenant_id=TENANT, actor_id=env["actor"], of_id=order.id,
        report_date=datetime.date(2026, 9, 5),
        detail=DailyReportDetail(gasoil_quantity=-1),
    )
    assert isinstance(result, Err)
    assert result.code == "INVALID_QUANTITY"


def test_every_draft_save_is_recorded_in_the_audit_log(db, env):
    """The mechanism the report's History panel reads: every draft edit writes
    a full snapshot to core.audit_log, not only submit/correct/validate."""
    service = ProductionReportService(db)
    order = _open_of(db, env)
    report = _draft_report(db, env, order.id, semolina_quantity=1000)

    service.update_daily_draft(
        tenant_id=TENANT, actor_id=env["actor"], report_id=report.id,
        detail=_detail(env, semolina_quantity=1200),
    )

    entries = db.execute(
        """
        SELECT action, actor_id, payload FROM core.audit_log
        WHERE entity_id = %s ORDER BY occurred_at
        """,
        (report.id,),
    ).fetchall()
    actions = [row[0] for row in entries]
    assert actions == ["production_report.created", "production_report.draft_updated"]
    assert entries[1][1] == env["actor"]
    assert entries[1][2]["semolina_lines"][0]["quantity"] == 1200


# --- validation -------------------------------------------------------------


def test_a_draft_cannot_be_validated(db, env):
    service = ProductionReportService(db)
    order = _open_of(db, env)
    report = _draft_report(db, env, order.id, semolina_quantity=1000)

    result = service.validate_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)
    assert isinstance(result, Err)
    assert result.code == "INVALID_TRANSITION"


def test_validating_twice_is_refused(db, env):
    """The guard that stops a retried call double-posting stock once Phase 5 lands."""
    service = ProductionReportService(db)
    _configure_regrind(db, env)
    order = _open_of(db, env)
    report = _draft_report(db, env, order.id, semolina_quantity=1000, regrind_quantity=40)
    service.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)

    first = service.validate_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)
    assert isinstance(first, Ok)
    assert first.value.validated_by == env["actor"]

    second = service.validate_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)
    assert isinstance(second, Err)
    assert second.code == "INVALID_TRANSITION"

    scrap_records = db.execute(
        "SELECT count(*) FROM production.scrap_records WHERE tenant_id = %s", (TENANT,)
    ).fetchone()[0]
    assert scrap_records == 1, "a refused second validate must not write a second scrap record"


def test_validation_writes_the_corrected_rebroyat_as_scrap(db, env):
    """scrap_records becomes a derived ledger, and regrind keeps its inputs."""
    service = ProductionReportService(db)
    _configure_regrind(db, env)
    order = _open_of(db, env)
    report = _draft_report(db, env, order.id, semolina_quantity=1000, regrind_quantity=50)
    service.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)
    service.correct_daily_report(
        tenant_id=TENANT,
        actor_id=env["actor"],
        report_id=report.id,
        detail=_detail(env, semolina_quantity=1000, regrind_quantity=65),
        reason="meter misread",
    )
    service.validate_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)

    scrap_type, quantity, work_order_id = db.execute(
        "SELECT scrap_type, quantity, work_order_id FROM production.scrap_records WHERE tenant_id = %s",
        (TENANT,),
    ).fetchone()
    assert float(quantity) == 65.0, "the official figure is the corrected one, not the submitted one"
    assert scrap_type == "daily_report"
    assert work_order_id == order.id


def test_validation_without_rebroyat_writes_no_scrap(db, env):
    service = ProductionReportService(db)
    order = _open_of(db, env)
    report = _draft_report(db, env, order.id, semolina_quantity=1000, regrind_quantity=0)
    service.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)
    service.validate_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)

    scrap_records = db.execute(
        "SELECT count(*) FROM production.scrap_records WHERE tenant_id = %s", (TENANT,)
    ).fetchone()[0]
    assert scrap_records == 0


def _on_hand(db, env) -> float:
    row = db.execute(
        "SELECT quantity_on_hand FROM warehouse.stock_items WHERE tenant_id = %s AND product_id = %s AND location_id = %s",
        (TENANT, env["product"], env["location"]),
    ).fetchone()
    return float(row[0]) if row else 0.0


def test_validating_a_daily_report_deducts_raw_material(db, env):
    """The pivot completed: validation is what moves stock."""
    service = ProductionReportService(db)
    _configure_regrind(db, env)
    order = _open_of(db, env)
    report = _draft_report(db, env, order.id, semolina_quantity=1000, regrind_quantity=40)
    service.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)

    before = _on_hand(db, env)
    validated = service.validate_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)
    assert isinstance(validated, Ok), getattr(validated, "message", "")
    assert _on_hand(db, env) == before - 1000


def test_the_daily_reports_finished_product_figure_posts_nothing(db, env):
    """Locked decision 7: the conditionnement report owns that tonnage.

    Counting it here too would double the same pasta, so the only movement a daily
    report makes is the raw material going out.
    """
    service = ProductionReportService(db)
    order = _open_of(db, env)
    report = _draft_report(db, env, order.id, semolina_quantity=1000, finished_product_quantity=900)
    service.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)
    service.validate_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)

    moves = db.execute(
        "SELECT direction FROM (SELECT move_type AS direction FROM warehouse.stock_moves WHERE source_id = %s) m",
        (report.id,),
    ).fetchall()
    assert len(moves) == 1, "one movement only — the raw material"
    assert moves[0][0] == "production_consumption"


def test_a_movement_names_the_report_and_of_that_caused_it(db, env):
    service = ProductionReportService(db)
    order = _open_of(db, env)
    report = _draft_report(db, env, order.id, semolina_quantity=1000)
    service.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)
    service.validate_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)

    source_type, source_id, of_id = db.execute(
        "SELECT source_type, source_id, of_id FROM warehouse.stock_moves WHERE source_id = %s",
        (report.id,),
    ).fetchone()
    assert source_type == "production.daily_report"
    assert source_id == report.id
    assert of_id == order.id


def test_a_draft_or_rejected_report_never_posts(db, env):
    """Enforced by the status guard, not by convention."""
    service = ProductionReportService(db)
    order = _open_of(db, env)
    report = _draft_report(db, env, order.id, semolina_quantity=1000)

    before = _stock_move_count(db)
    assert isinstance(service.validate_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id), Err)

    service.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)
    service.reject_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id, reason="wrong figures")
    assert isinstance(service.validate_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id), Err)

    assert _stock_move_count(db) == before


def test_a_shortfall_needs_a_comment_but_then_posts_anyway(db, env):
    """Locked decision 10. Semoule is always available: the report records what
    physically happened, and a balance that goes negative means the stock figure is
    wrong, not the shift. The validator has to account for it, not override it."""
    service = ProductionReportService(db)
    order = _open_of(db, env)
    # More than the 100,000 the fixture seeded.
    report = _draft_report(db, env, order.id, semolina_quantity=150_000)
    service.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)

    refused = service.validate_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)
    assert isinstance(refused, Err)
    assert refused.code == "SHORTFALL_COMMENT_REQUIRED"

    accepted = service.validate_report(
        tenant_id=TENANT,
        actor_id=env["actor"],
        report_id=report.id,
        shortfall_comment="silo reading was stale; stocktake booked",
    )
    assert isinstance(accepted, Ok), getattr(accepted, "message", "")
    assert _on_hand(db, env) == -50_000, "the movement posts even though it goes negative"

    comment = db.execute(
        "SELECT shortfall_comment FROM production.production_reports WHERE id = %s", (report.id,)
    ).fetchone()[0]
    assert comment == "silo reading was stale; stocktake booked"


def test_a_reservation_still_refuses_a_shortfall(db, env):
    """The exception is only for recording production that already happened."""
    result = StockService(db).reserve_stock(
        tenant_id=TENANT,
        product_id=env["product"],
        location_id=env["location"],
        quantity=1_000_000,
        correlation_id=str(ULID()),
        reference="test",
        actor_id=env["actor"],
    )
    assert isinstance(result, Err)
    assert result.code == "INSUFFICIENT_STOCK"


def test_rebroyat_above_zero_opens_its_own_regrind_order(db, env):
    """Decision 11: nobody has to remember to raise it."""
    service = ProductionReportService(db)
    _configure_regrind(db, env)
    order = _open_of(db, env)
    report = _draft_report(db, env, order.id, semolina_quantity=1000, regrind_quantity=45)
    service.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)
    service.validate_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)

    batches = db.execute(
        """
        SELECT wo.id, wo.planned_quantity FROM production.regrind_batches rb
        JOIN production.work_orders wo ON wo.id = rb.work_order_id
        WHERE rb.tenant_id = %s
        """,
        (TENANT,),
    ).fetchall()
    assert len(batches) == 1
    assert float(batches[0][1]) == 45


def test_the_regrind_order_can_be_opened_on_a_different_work_center(db, env):
    """A validator may name the rebroyeur machine explicitly rather than always
    inheriting the reporting line's own work center (decision 15's default)."""
    rebroyeur = str(ULID())
    db.execute(
        "INSERT INTO production.work_centers (id, tenant_id, code, name) VALUES (%s, %s, 'TEST-REBROYEUR', 'Test rebroyeur')",
        (rebroyeur, TENANT),
    )
    service = ProductionReportService(db)
    _configure_regrind(db, env)
    order = _open_of(db, env)
    report = _draft_report(db, env, order.id, semolina_quantity=1000, regrind_quantity=45)
    service.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)
    result = service.validate_report(
        tenant_id=TENANT, actor_id=env["actor"], report_id=report.id, regrind_work_center_id=rebroyeur
    )
    assert isinstance(result, Ok), getattr(result, "message", "")

    batch_work_center = db.execute(
        """
        SELECT wo.work_center_id FROM production.regrind_batches rb
        JOIN production.work_orders wo ON wo.id = rb.work_order_id
        WHERE rb.tenant_id = %s
        """,
        (TENANT,),
    ).fetchone()
    assert batch_work_center[0] == rebroyeur
    assert batch_work_center[0] != env["work_center"]


def test_validation_is_blocked_when_no_regrind_default_is_configured(db, env):
    """Blocked rather than silently skipped — skipping would lose the rebroyat."""
    service = ProductionReportService(db)
    order = _open_of(db, env)
    report = _draft_report(db, env, order.id, semolina_quantity=1000, regrind_quantity=45)
    service.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)

    result = service.validate_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)
    assert isinstance(result, Err)
    assert result.code == "REGRIND_DEFAULT_MISSING"


def test_a_report_without_rebroyat_needs_no_regrind_default(db, env):
    service = ProductionReportService(db)
    order = _open_of(db, env)
    report = _draft_report(db, env, order.id, semolina_quantity=1000, regrind_quantity=0)
    service.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)
    assert isinstance(
        service.validate_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id), Ok
    )


def test_a_report_must_name_what_it_moves_before_it_can_be_submitted(db, env):
    """A draft may be half-finished; a report handed to the desk may not."""
    result = ProductionReportService(db).create_daily_report(
        tenant_id=TENANT,
        actor_id=env["actor"],
        of_id=_open_of(db, env).id,
        report_date=datetime.date(2026, 9, 4),
        equipment_id=env["equipment"],
        detail=DailyReportDetail(semolina_lines=(SemolinaLine(quantity=1000),)),
    )
    assert isinstance(result, Ok), getattr(result, "message", "")

    submitted = ProductionReportService(db).submit_report(
        tenant_id=TENANT, actor_id=env["actor"], report_id=result.value["report"].id
    )
    assert isinstance(submitted, Err)
    assert submitted.code == "MISSING_STOCK_TARGET"


def test_a_report_without_a_machine_cannot_be_submitted(db, env):
    """A line like Line_1_PL can carry more than one machine at once, so a report
    that never names which one it ran on can never be attributed to a machine
    again once it leaves the draft stage."""
    result = ProductionReportService(db).create_daily_report(
        tenant_id=TENANT,
        actor_id=env["actor"],
        of_id=_open_of(db, env).id,
        report_date=datetime.date(2026, 9, 5),
        detail=_detail(env, semolina_quantity=500),
    )
    assert isinstance(result, Ok), getattr(result, "message", "")
    assert result.value["report"].equipment_id is None

    submitted = ProductionReportService(db).submit_report(
        tenant_id=TENANT, actor_id=env["actor"], report_id=result.value["report"].id
    )
    assert isinstance(submitted, Err)
    assert submitted.code == "MISSING_MACHINE"


# --- reject and revise ------------------------------------------------------


def test_reject_then_revise_keeps_the_rejected_original(db, env):
    service = ProductionReportService(db)
    order = _open_of(db, env)
    report = _draft_report(db, env, order.id, semolina_quantity=500)
    service.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)

    rejected = service.reject_report(
        tenant_id=TENANT, actor_id=env["actor"], report_id=report.id, reason="does not match the silo reading"
    )
    assert isinstance(rejected, Ok)
    assert rejected.value.status == "rejected"

    reopened = service.revise_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)
    assert isinstance(reopened, Ok)
    assert reopened.value.status == "draft"
    assert reopened.value.revision == 2
    assert reopened.value.rejection_reason is None

    service.update_daily_draft(
        tenant_id=TENANT, actor_id=env["actor"], report_id=report.id,
        detail=_detail(env, semolina_quantity=520),
    )
    service.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)

    revisions = service.list_revisions(tenant_id=TENANT, report_id=report.id)
    assert [r["revision"] for r in revisions] == [1, 2]
    assert revisions[0]["detail"]["semolina_lines"][0]["quantity"] == 500, "the rejected figures stay readable"
    assert revisions[1]["detail"]["semolina_lines"][0]["quantity"] == 520


def test_a_rejection_must_say_what_is_wrong(db, env):
    service = ProductionReportService(db)
    order = _open_of(db, env)
    report = _draft_report(db, env, order.id, semolina_quantity=500)
    service.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)

    result = service.reject_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id, reason=" ")
    assert isinstance(result, Err)
    assert result.code == "MISSING_REASON"


def test_a_submitted_report_is_no_longer_a_draft(db, env):
    service = ProductionReportService(db)
    order = _open_of(db, env)
    report = _draft_report(db, env, order.id, semolina_quantity=500)
    service.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)

    result = service.update_daily_draft(
        tenant_id=TENANT, actor_id=env["actor"], report_id=report.id, detail=DailyReportDetail()
    )
    assert isinstance(result, Err)
    assert result.code == "NOT_EDITABLE"


# --- one report per shift ---------------------------------------------------


def test_a_shift_cannot_report_twice(db, env):
    """Double entry would double-count tonnage and rebroyat once validated."""
    order = _open_of(db, env)
    _draft_report(db, env, order.id, semolina_quantity=1000)

    duplicate = ProductionReportService(db).create_daily_report(
        tenant_id=TENANT,
        actor_id=env["actor"],
        of_id=order.id,
        report_date=datetime.date(2026, 9, 1),
        team="B",
        shift="morning",
        detail=_detail(env, semolina_quantity=900),
    )
    assert isinstance(duplicate, Err)
    assert duplicate.code == "DUPLICATE_REPORT"


def test_a_different_shift_on_the_same_day_is_fine(db, env):
    service = ProductionReportService(db)
    order = _open_of(db, env)
    _draft_report(db, env, order.id, semolina_quantity=1000)

    afternoon = service.create_daily_report(
        tenant_id=TENANT,
        actor_id=env["actor"],
        of_id=order.id,
        report_date=datetime.date(2026, 9, 1),
        shift="afternoon",
        detail=_detail(env, semolina_quantity=900),
    )
    assert isinstance(afternoon, Ok), getattr(afternoon, "message", "")


def test_shiftless_reports_are_deduplicated_too(db, env):
    """The NULLS NOT DISTINCT case — the one a default unique index would miss."""
    service = ProductionReportService(db)
    order = _open_of(db, env)

    first = service.create_daily_report(
        tenant_id=TENANT, actor_id=env["actor"], of_id=order.id, report_date=datetime.date(2026, 9, 1)
    )
    assert isinstance(first, Ok)

    second = service.create_daily_report(
        tenant_id=TENANT, actor_id=env["actor"], of_id=order.id, report_date=datetime.date(2026, 9, 1)
    )
    assert isinstance(second, Err)
    assert second.code == "DUPLICATE_REPORT"


def test_the_database_refuses_a_duplicate_even_without_the_service_check(db, env):
    import psycopg

    order = _open_of(db, env)
    report = _draft_report(db, env, order.id, semolina_quantity=1000)
    header = db.execute(
        "SELECT of_id, report_date, shift FROM production.production_reports WHERE id = %s", (report.id,)
    ).fetchone()

    with pytest.raises(psycopg.errors.UniqueViolation):
        db.execute(
            "INSERT INTO production.production_reports "
            "(id, tenant_id, of_id, report_type, report_date, status, revision, shift) "
            "VALUES (%s, %s, %s, 'daily', %s, 'draft', 1, %s)",
            (str(ULID()), TENANT, header[0], header[1], header[2]),
        )


# --- regrind, the one path that still posts stock ---------------------------


def test_completing_the_auto_created_regrind_batch_receives_stock(db, env):
    """Rebroyat is still the one production output received on its own OF: it has
    no report behind it, only the scrap it was built from."""
    service = ProductionReportService(db)
    _configure_regrind(db, env)
    order = _open_of(db, env)
    report = _draft_report(db, env, order.id, semolina_quantity=1000, regrind_quantity=60)
    service.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)
    service.validate_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)

    batch_of_id = db.execute(
        "SELECT work_order_id FROM production.regrind_batches WHERE tenant_id = %s", (TENANT,)
    ).fetchone()[0]

    assigned = RegrindService(db).assign_batch(
        tenant_id=TENANT, actor_id=env["actor"], work_order_id=batch_of_id, team="Équipe A",
    )
    assert isinstance(assigned, Ok), getattr(assigned, "message", "")

    before = _stock_move_count(db)
    completed = RegrindService(db).complete_batch(
        tenant_id=TENANT,
        actor_id=env["actor"],
        work_order_id=batch_of_id,
        correlation_id=str(ULID()),
        location_id=env["location"],
        actual_output_quantity=58,
    )
    assert isinstance(completed, Ok), getattr(completed, "message", "")
    assert completed.value["work_order"].status == "closed"
    assert _stock_move_count(db) > before


def test_finishing_a_regrind_batch_without_assigning_it_is_rejected(db, env):
    """A regrind run should never be closed without a responsable having handed
    it to a team first — that handoff is what starts the OF."""
    service = ProductionReportService(db)
    _configure_regrind(db, env)
    order = _open_of(db, env)
    report = _draft_report(db, env, order.id, semolina_quantity=1000, regrind_quantity=60)
    service.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)
    service.validate_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)

    batch_of_id = db.execute(
        "SELECT work_order_id FROM production.regrind_batches WHERE tenant_id = %s", (TENANT,)
    ).fetchone()[0]

    completed = RegrindService(db).complete_batch(
        tenant_id=TENANT,
        actor_id=env["actor"],
        work_order_id=batch_of_id,
        correlation_id=str(ULID()),
        location_id=env["location"],
        actual_output_quantity=58,
    )
    assert isinstance(completed, Err)
    assert completed.code == "NOT_ASSIGNED"


def test_assigning_a_regrind_batch_starts_it_and_records_the_team(db, env):
    service = ProductionReportService(db)
    _configure_regrind(db, env)
    order = _open_of(db, env)
    report = _draft_report(db, env, order.id, semolina_quantity=1000, regrind_quantity=60)
    service.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)
    service.validate_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)

    batch_of_id = db.execute(
        "SELECT work_order_id FROM production.regrind_batches WHERE tenant_id = %s", (TENANT,)
    ).fetchone()[0]

    before = RegrindService(db).get_regrind_batch(tenant_id=TENANT, work_order_id=batch_of_id)
    assert before["stage"] == "new"
    assert before["loss_quantity"] is None

    assigned = RegrindService(db).assign_batch(
        tenant_id=TENANT, actor_id=env["actor"], work_order_id=batch_of_id, team="Équipe A",
    )
    assert isinstance(assigned, Ok), getattr(assigned, "message", "")
    assert assigned.value["work_order"].status == "ongoing"
    assert assigned.value["stage"] == "assigned"
    assert assigned.value["assigned_team"] == "Équipe A"

    # Assigning twice is refused rather than silently reassigning the team.
    reassigned = RegrindService(db).assign_batch(
        tenant_id=TENANT, actor_id=env["actor"], work_order_id=batch_of_id, team="Équipe B",
    )
    assert isinstance(reassigned, Err)
    assert reassigned.code == "ALREADY_ASSIGNED"


def test_finishing_a_regrind_batch_reports_the_real_variance(db, env):
    """Once the team weighs the real output, the écart is input minus that real
    weight — never the estimate the batch was opened with."""
    service = ProductionReportService(db)
    _configure_regrind(db, env)
    order = _open_of(db, env)
    report = _draft_report(db, env, order.id, semolina_quantity=1000, regrind_quantity=60)
    service.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)
    service.validate_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)

    batch_of_id = db.execute(
        "SELECT work_order_id FROM production.regrind_batches WHERE tenant_id = %s", (TENANT,)
    ).fetchone()[0]

    RegrindService(db).assign_batch(
        tenant_id=TENANT, actor_id=env["actor"], work_order_id=batch_of_id, team="Équipe A",
    )
    completed = RegrindService(db).complete_batch(
        tenant_id=TENANT,
        actor_id=env["actor"],
        work_order_id=batch_of_id,
        correlation_id=str(ULID()),
        location_id=env["location"],
        actual_output_quantity=55,
    )
    assert isinstance(completed, Ok), getattr(completed, "message", "")

    batch = RegrindService(db).get_regrind_batch(tenant_id=TENANT, work_order_id=batch_of_id)
    assert batch["stage"] == "finished"
    assert batch["actual_output_quantity"] == 55
    assert batch["loss_quantity"] == batch["input_quantity_total"] - 55


# --- closure ----------------------------------------------------------------


def test_closing_an_of_deletes_nothing_but_refuses_new_reports(db, env):
    service = ProductionReportService(db)
    order = _open_of(db, env)
    report = _draft_report(db, env, order.id, semolina_quantity=1000)
    service.submit_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)
    service.validate_report(tenant_id=TENANT, actor_id=env["actor"], report_id=report.id)

    closed = WorkOrderService(db).close_work_order(
        tenant_id=TENANT, actor_id=env["actor"], work_order_id=order.id, correlation_id=str(ULID())
    )
    assert isinstance(closed, Ok)

    surviving = db.execute(
        "SELECT count(*) FROM production.production_reports WHERE of_id = %s", (order.id,)
    ).fetchone()[0]
    assert surviving == 1, "closure is archival — reports stay readable"

    refused = service.create_daily_report(
        tenant_id=TENANT, actor_id=env["actor"], of_id=order.id, report_date=datetime.date(2026, 9, 3)
    )
    assert isinstance(refused, Err)
    assert refused.code == "OF_NOT_OPEN"
