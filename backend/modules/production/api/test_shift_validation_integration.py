"""Validating, rejecting and reversing a whole shift, against real stock.

A shift is filled through ShiftReportService exactly as a team would, then a
validator approves it. Every test runs in the rolled-back `db` transaction.
"""
from __future__ import annotations

import datetime

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from modules.production.api.dashboard_settings_service import DashboardSettingsService
from modules.production.api.regrind_service import RegrindDefaultsService, RegrindService
from modules.production.api.service import WorkOrderService
from modules.production.api.shift_report_service import ShiftReportService
from modules.production.api.shift_validation_service import ShiftValidationService
from modules.production.domain.shift_report import SECTION_KEYS
from modules.warehouse.api.service import StockService

TENANT = "shift-validation-test"
DAY = datetime.date(2030, 6, 7)


@pytest.fixture
def env(db):
    actor = str(ULID())
    uom, product, semolina, location, fg_location, packaging_location, work_center, equipment = (str(ULID()) for _ in range(8))
    film, carton, scotch, ruban = (str(ULID()) for _ in range(4))
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (actor, TENANT, f"{actor}@test.local"),
    )
    db.execute(
        "INSERT INTO core.uoms (id, tenant_id, code, name, category) VALUES (%s, %s, 'kg', 'Kilogram', 'weight')",
        (uom, TENANT),
    )
    for product_id, sku in ((product, "SV-PASTA"), (semolina, "SV-SEMO"), (film, "SV-FILM"), (carton, "SV-CARTON"), (scotch, "SV-SCOTCH"), (ruban, "SV-RUBAN")):
        db.execute(
            "INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, %s, %s, %s)",
            (product_id, TENANT, sku, sku, uom),
        )
    db.execute("INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, 'SV-LOC', 'Silo')", (location, TENANT))
    db.execute("INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, 'SV-PACK', 'Packaging')", (packaging_location, TENANT))
    db.execute("INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, 'SV-FG', 'Finished goods')", (fg_location, TENANT))
    db.execute("INSERT INTO production.work_centers (id, tenant_id, code, name) VALUES (%s, %s, 'SV-WC', 'Line')", (work_center, TENANT))
    db.execute(
        "INSERT INTO maintenance.equipment (id, tenant_id, work_center_id, code, name) VALUES (%s, %s, %s, 'SV-EQ', 'Press')",
        (equipment, TENANT, work_center),
    )
    stock = StockService(db)
    stock.receive_stock(tenant_id=TENANT, product_id=semolina, location_id=location, quantity=100_000,
                        correlation_id=str(ULID()), reference="seed", actor_id=actor)
    for product_id in (film, carton, scotch, ruban):
        stock.receive_stock(tenant_id=TENANT, product_id=product_id, location_id=packaging_location, quantity=10_000,
                            correlation_id=str(ULID()), reference="seed", actor_id=actor)
    return {
        "actor": actor, "product": product, "semolina": semolina, "location": location, "fg_location": fg_location,
        "packaging_location": packaging_location,
        "work_center": work_center, "equipment": equipment, "film": film, "carton": carton, "scotch": scotch,
        "ruban": ruban,
    }


def _of(db, env) -> str:
    service = WorkOrderService(db)
    created = service.create_work_order(
        tenant_id=TENANT, actor_id=env["actor"], product_id=env["product"], planned_quantity=100_000,
        work_center_id=env["work_center"], start_date=DAY,
    )
    assert isinstance(created, Ok), getattr(created, "message", "")
    assert isinstance(service.start_work_order(tenant_id=TENANT, actor_id=env["actor"], work_order_id=created.value.id), Ok)
    return created.value.id


def _ok(result):
    assert isinstance(result, Ok), getattr(result, "message", result)
    return result.value


def _run(env, of_id, *, minutes=420, semolina=1000, **fields):
    return {
        "of_id": of_id, "equipment_id": env["equipment"], "start_time": "07:00", "end_time": "14:00",
        "production_minutes": minutes, "finished_product_quantity": 900,
        "raw_material_location_id": env["location"],
        "semolina_lines": [{"product_id": env["semolina"], "quantity": semolina, "location_id": env["location"]}],
        **fields,
    }


def _poured(runs: list[dict]) -> dict:
    """The runs, with the semoule they list poured through the shift's versement instead."""
    totals: dict[tuple, float] = {}
    for run in runs:
        for line in run.pop("semolina_lines", []):
            key = (line["product_id"], line["location_id"])
            totals[key] = totals.get(key, 0) + line["quantity"]
    versements = [{"product_id": p, "location_id": l, "quantity": q} for (p, l), q in totals.items()]
    return {"runs": runs, "versements": versements}


def _packing_row(env, of_id, *, run_id=None, **fields):
    return {
        "of_id": of_id, "run_id": run_id, "equipment_id": env["equipment"], "finished_product_quantity": 800,
        "packets_counted": 1600, "film_quantity": 40, "carton_quantity": 100, "scotch_quantity": 2, "ruban_quantity": 1,
        "film_product_id": env["film"], "carton_product_id": env["carton"], "scotch_product_id": env["scotch"],
        "ruban_product_id": env["ruban"], "packaging_location_id": env["packaging_location"],
        "finished_goods_location_id": env["fg_location"], "lot_number": "B6261SNL", **fields,
    }


def _submitted_shift(db, env, *, runs=None, packing=True, energy=None, extra=None, shift="morning") -> str:
    """A shift with every section in: filled where given, 'nothing to report' elsewhere.

    `extra` maps a section key to its payload, or to a function of the saved run ids
    (for rows that point at a run).
    """
    service = ShiftReportService(db)
    shift_id = _ok(service.open_shift(tenant_id=TENANT, actor_id=env["actor"], work_center_id=env["work_center"],
                                      report_date=DAY, shift=shift))["id"]
    of_id = _of(db, env)
    _ok(service.save_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key="runs",
                             payload=_poured(runs if runs is not None else [_run(env, of_id)])))
    run_ids = [r["id"] for r in _shift(db, shift_id)["sections"][0]["payload"]["runs"]]

    filled: dict = {"runs": None} if run_ids else {}  # already saved above; only submitted below
    if packing:
        filled["packing"] = {"rows": [_packing_row(env, of_id, run_id=run_ids[0])]}
    if energy is not None:
        filled["energy"] = {"energy": energy}
    for key, payload in (extra or {}).items():
        filled[key] = payload(run_ids) if callable(payload) else payload

    for key in SECTION_KEYS:
        if key in filled:
            if filled[key] is not None:
                _ok(service.save_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key, payload=filled[key]))
            _ok(service.submit_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key))
        else:
            _ok(service.declare_nothing(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key))
    assert _shift(db, shift_id)["status"] == "submitted"
    return shift_id


def _validate(db, env, shift_id, **kwargs):
    return ShiftValidationService(db).validate_shift(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, **kwargs)


def _shift(db, shift_id) -> dict:
    return _ok(ShiftReportService(db).get_shift(tenant_id=TENANT, shift_report_id=shift_id))


def _on_hand(db, env, product_key="product", location_key="location") -> float:
    row = db.execute(
        "SELECT quantity_on_hand FROM warehouse.stock_items WHERE tenant_id = %s AND product_id = %s AND location_id = %s",
        (TENANT, env[product_key], env[location_key]),
    ).fetchone()
    return float(row[0]) if row else 0.0


# ---- validating -------------------------------------------------------------


def test_validating_posts_the_shifts_stock_once_and_freezes_the_shift(db, env):
    shift_id = _submitted_shift(db, env)
    semolina_before, film_before = _on_hand(db, env, "semolina"), _on_hand(db, env, "film", "packaging_location")

    validated = _ok(_validate(db, env, shift_id))

    assert validated["status"] == "validated" and validated["validated_by"] == env["actor"]
    assert _on_hand(db, env, "semolina") == semolina_before - 1000  # the run's semoule went out
    assert _on_hand(db, env, "product", "fg_location") > 0  # and the packed pasta came in
    assert _on_hand(db, env, "film", "packaging_location") == film_before - 40
    statuses = {s["status"] for s in validated["sections"]}
    assert statuses <= {"submitted", "nothing_to_report"}
    assert all(s["revised_after_submit"] is False for s in validated["sections"])


def test_validation_uses_the_row_ids_as_the_stock_move_source(db, env):
    shift_id = _submitted_shift(db, env)
    shift = _shift(db, shift_id)
    run_id = shift["sections"][0]["payload"]["runs"][0]["id"]
    packing_id = next(s for s in shift["sections"] if s["key"] == "packing")["payload"]["rows"][0]["id"]
    _ok(_validate(db, env, shift_id))
    source_types = dict(db.execute(
        "SELECT source_id, source_type FROM warehouse.stock_moves WHERE source_id = ANY(%s)", ([run_id, packing_id],)
    ).fetchall())
    assert source_types == {run_id: "production.shift_run", packing_id: "production.shift_packing_row"}
    moved = {r[0] for r in db.execute("SELECT DISTINCT source_id FROM warehouse.stock_moves WHERE source_id = ANY(%s)", ([run_id, packing_id],)).fetchall()}
    assert moved == {run_id, packing_id}


def test_a_validated_shift_appears_in_production_reports_as_validated_and_reversal_removes_it(db, env):
    """~18 reader services still query production_reports/daily_reports/conditionnement_reports
    directly. Until each is ported to the shift tables, validation writes a read-only copy
    there (no stock posted from it -- ShiftStockService already posted the real stock) so
    those readers keep working; reversal deletes the copy."""
    shift_id = _submitted_shift(db, env)
    shift = _shift(db, shift_id)
    run_id = shift["sections"][0]["payload"]["runs"][0]["id"]
    packing_id = next(s for s in shift["sections"] if s["key"] == "packing")["payload"]["rows"][0]["id"]
    moves_before = db.execute("SELECT count(*) FROM warehouse.stock_moves WHERE tenant_id = %s", (TENANT,)).fetchone()[0]

    _ok(_validate(db, env, shift_id))

    rows = dict(db.execute(
        "SELECT id, status FROM production.production_reports WHERE tenant_id = %s AND id = ANY(%s)",
        (TENANT, [run_id, packing_id]),
    ).fetchall())
    assert rows == {run_id: "validated", packing_id: "validated"}
    assert db.execute("SELECT count(*) FROM production.daily_reports WHERE report_id = %s", (run_id,)).fetchone()[0] == 1
    assert db.execute("SELECT count(*) FROM production.conditionnement_reports WHERE report_id = %s", (packing_id,)).fetchone()[0] == 1
    # The copy posts no stock of its own: everything moved came from ShiftStockService.
    assert db.execute("SELECT count(*) FROM warehouse.stock_moves WHERE tenant_id = %s", (TENANT,)).fetchone()[0] > moves_before

    _ok(ShiftValidationService(db).reverse_shift(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, reason="test"))

    left = db.execute(
        "SELECT count(*) FROM production.production_reports WHERE tenant_id = %s AND id = ANY(%s)",
        (TENANT, [run_id, packing_id]),
    ).fetchone()[0]
    assert left == 0


def test_a_shift_must_be_submitted_and_can_only_be_validated_once(db, env):
    service = ShiftReportService(db)
    open_id = _ok(service.open_shift(tenant_id=TENANT, actor_id=env["actor"], work_center_id=env["work_center"], report_date=DAY, shift="night"))["id"]
    early = _validate(db, env, open_id)
    assert isinstance(early, Err) and early.code == "INVALID_TRANSITION"
    shift_id = _submitted_shift(db, env)
    _ok(_validate(db, env, shift_id))
    again = _validate(db, env, shift_id)
    assert isinstance(again, Err) and again.code == "INVALID_TRANSITION"


def test_a_stale_view_is_refused(db, env):
    shift_id = _submitted_shift(db, env)
    seen = {s["key"]: s["revision"] for s in _shift(db, shift_id)["sections"]}
    # The team edits the packing table after the validator opened the shift.
    packing = next(s for s in _shift(db, shift_id)["sections"] if s["key"] == "packing")["payload"]
    packing["rows"][0]["carton_quantity"] = 120
    _ok(ShiftReportService(db).save_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key="packing", payload=packing))
    result = _validate(db, env, shift_id, seen_revisions=seen)
    assert isinstance(result, Err) and result.code == "CHANGED_SINCE_OPENED"
    assert "packing" in result.message
    # Seeing the current revisions validates.
    fresh = {s["key"]: s["revision"] for s in _shift(db, shift_id)["sections"]}
    assert isinstance(_validate(db, env, shift_id, seen_revisions=fresh), Ok)


def test_an_ongoing_stop_blocks_validation(db, env):
    stops = {"stops": [{"started_at": "2030-06-07T09:00:00+00:00", "motif": "extruder_failure"}]}
    shift_id = _submitted_shift(db, env, extra={"stops": stops})
    result = _validate(db, env, shift_id)
    assert isinstance(result, Err) and result.code == "OPEN_STOP"


def test_a_shift_with_no_run_and_no_packing_has_nothing_to_validate(db, env):
    shift_id = _submitted_shift(db, env, runs=[], packing=False)
    result = _validate(db, env, shift_id)
    assert isinstance(result, Err) and result.code == "NOTHING_TO_VALIDATE"


def test_a_failing_row_leaves_the_whole_shift_untouched(db, env):
    """The run posts fine, then the packing row needs a shortfall comment: nothing may stick."""
    service = ShiftReportService(db)
    shift_id = _ok(service.open_shift(tenant_id=TENANT, actor_id=env["actor"], work_center_id=env["work_center"], report_date=DAY, shift="night"))["id"]
    of_id = _of(db, env)
    _ok(service.save_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key="runs", payload=_poured([_run(env, of_id)])))
    run_id = _shift(db, shift_id)["sections"][0]["payload"]["runs"][0]["id"]
    # 20,000 of film against a store holding 10,000: complete on paper, short in stock.
    _ok(service.save_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key="packing",
                             payload={"rows": [_packing_row(env, of_id, run_id=run_id, film_quantity=20_000)]}))
    for key in SECTION_KEYS:
        if key in ("runs", "packing"):
            _ok(service.submit_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key))
        else:
            _ok(service.declare_nothing(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key))
    semolina_before = _on_hand(db, env, "semolina")
    moves_before = db.execute("SELECT count(*) FROM warehouse.stock_moves WHERE tenant_id = %s", (TENANT,)).fetchone()[0]

    result = _validate(db, env, shift_id)

    assert isinstance(result, Err) and result.code == "SHORTFALL_COMMENT_REQUIRED"
    assert _on_hand(db, env, "semolina") == semolina_before, "the run's semoule must not have been taken"
    assert db.execute("SELECT count(*) FROM warehouse.stock_moves WHERE tenant_id = %s", (TENANT,)).fetchone()[0] == moves_before
    assert db.execute("SELECT count(*) FROM warehouse.stock_moves WHERE source_id = %s", (run_id,)).fetchone()[0] == 0
    assert _shift(db, shift_id)["status"] == "submitted"

    # Explained, the same shift now validates: the refusal left nothing behind to trip over.
    assert isinstance(_validate(db, env, shift_id, shortfall_comment="film counted late"), Ok)
    assert _on_hand(db, env, "semolina") == semolina_before - 1000


# ---- multi-run shifts --------------------------------------------------------


def test_a_shift_with_two_runs_validates_and_posts_each_runs_own_stock(db, env):
    """A PC-style mold-change shift: two runs, two products, each posts its own
    consumption. (This used to also assert an energy split across runs -- that
    was legacy_report_ledger's own presentation-time computation for the old
    daily_reports reader and is not part of ShiftStockService; energy stays a
    single whole-shift figure on shift_energy. See Task 6/6b.)"""
    service = ShiftReportService(db)
    shift_id = _ok(service.open_shift(tenant_id=TENANT, actor_id=env["actor"], work_center_id=env["work_center"], report_date=DAY, shift="afternoon"))["id"]
    first, second = _of(db, env), _of(db, env)
    semolina_before = _on_hand(db, env, "semolina")
    _ok(service.save_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key="runs",
                             payload=_poured([_run(env, first, minutes=240, semolina=400), _run(env, second, minutes=180, semolina=300)])))
    for key in SECTION_KEYS:
        if key == "runs":
            _ok(service.submit_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key))
        else:
            _ok(service.declare_nothing(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key))
    _ok(_validate(db, env, shift_id))

    run_ids = [row[0] for row in db.execute(
        "SELECT id FROM production.shift_runs WHERE shift_report_id = %s ORDER BY line_order", (shift_id,)
    ).fetchall()]
    assert len(run_ids) == 2
    moved = {r[0]: r[1] for r in db.execute(
        "SELECT source_id, quantity FROM warehouse.stock_moves WHERE source_id = ANY(%s) AND move_type = 'production_consumption'",
        (run_ids,),
    ).fetchall()}
    assert float(moved[run_ids[0]]) == 400
    assert float(moved[run_ids[1]]) == 300
    assert _on_hand(db, env, "semolina") == semolina_before - 700


def test_stops_and_waste_stay_on_the_shift_and_post_no_stock(db, env):
    """Stops and waste are records, not stock: validation posts nothing for them and leaves
    them exactly as the team entered them. (The old ledger copied them onto per-run
    report_downtime_lines/report_waste_lines, attaching unassigned waste to the first run;
    the shift tables are now the only copy, and readers attribute them -- see Task 4.)"""
    stops = {"stops": [
        {"started_at": "2030-06-07T08:55:00+00:00", "ended_at": "2030-06-07T09:06:00+00:00", "motif": "extruder_failure",
         "corrective_action": "Nettoyage"},
    ]}
    waste = lambda run_ids: {  # noqa: E731
        "waste_lines": [{"category": "press", "quantity": 6.4, "run_id": run_ids[0], "product_id": env["semolina"]},
                          {"category": "kneading", "quantity": 1.5, "product_id": env["semolina"]}]
    }
    shift_id = _submitted_shift(db, env, extra={"stops": stops, "waste_production": waste})
    semolina_before = _on_hand(db, env, "semolina")
    _ok(_validate(db, env, shift_id))
    run_id = _shift(db, shift_id)["sections"][0]["payload"]["runs"][0]["id"]

    started, ended, motif, action = db.execute(
        "SELECT started_at, ended_at, motif, corrective_action FROM production.machine_stops WHERE shift_report_id = %s",
        (shift_id,),
    ).fetchone()
    assert (ended - started).total_seconds() == 11 * 60
    assert (motif, action) == ("extruder_failure", "Nettoyage")
    lines = {row[0]: (row[1], float(row[2])) for row in db.execute(
        "SELECT category, run_id, quantity FROM production.shift_waste_lines WHERE shift_report_id = %s", (shift_id,)
    ).fetchall()}
    assert lines == {"press": (run_id, 6.4), "kneading": (None, 1.5)}
    # Only the run's semoule left the silo; the 7.9 kg of waste moved nothing.
    assert _on_hand(db, env, "semolina") == semolina_before - 1000


# ---- rejecting ----------------------------------------------------------------


def test_rejecting_returns_only_the_named_sections(db, env):
    shift_id = _submitted_shift(db, env)
    result = _ok(ShiftValidationService(db).reject_sections(
        tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_keys=["packing"], reason="carton count is wrong"))
    by_key = {s["key"]: s for s in result["sections"]}
    assert result["status"] == "returned"
    assert (by_key["packing"]["status"], by_key["packing"]["return_reason"]) == ("returned", "carton count is wrong")
    assert by_key["runs"]["status"] == "submitted"

    # The team fixes it and resubmits; the shift goes back to the validator.
    service = ShiftReportService(db)
    payload = by_key["packing"]["payload"]
    payload["rows"][0]["carton_quantity"] = 90
    _ok(service.save_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key="packing", payload=payload))
    _ok(service.submit_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key="packing"))
    assert _shift(db, shift_id)["status"] == "submitted"
    assert isinstance(_validate(db, env, shift_id), Ok)


def test_rejecting_needs_a_reason_a_section_and_a_submitted_shift(db, env):
    shift_id = _submitted_shift(db, env)
    reject = ShiftValidationService(db).reject_sections
    no_reason = reject(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_keys=["packing"], reason="  ")
    no_section = reject(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_keys=[], reason="x")
    unknown = reject(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_keys=["reels"], reason="x")
    assert [type(r) for r in (no_reason, no_section, unknown)] == [Err, Err, Err]
    assert [r.code for r in (no_reason, no_section, unknown)] == ["MISSING_REASON", "INVALID_VALUE", "INVALID_SECTION"]
    _ok(_validate(db, env, shift_id))
    late = reject(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_keys=["packing"], reason="x")
    assert isinstance(late, Err) and late.code == "INVALID_TRANSITION"


# ---- reversing ----------------------------------------------------------------


def test_reversing_puts_the_stock_back_and_reopens_the_shift(db, env):
    shift_id = _submitted_shift(db, env)
    semolina_before = _on_hand(db, env, "semolina")
    film_before = _on_hand(db, env, "film", "packaging_location")
    _ok(_validate(db, env, shift_id))
    run_id = _shift(db, shift_id)["sections"][0]["payload"]["runs"][0]["id"]

    reversed_ = _ok(ShiftValidationService(db).reverse_shift(
        tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, reason="wrong shift entered"))

    assert _on_hand(db, env, "semolina") == semolina_before
    assert _on_hand(db, env, "film", "packaging_location") == film_before
    assert _on_hand(db, env, "product", "fg_location") == 0
    assert reversed_["status"] == "returned"
    by_key = {s["key"]: s for s in reversed_["sections"]}
    assert by_key["runs"]["status"] == "returned" and "wrong shift entered" in by_key["runs"]["return_reason"]
    assert by_key["silo"]["status"] == "nothing_to_report"
    assert db.execute("SELECT count(*) FROM production.production_reports WHERE id = %s", (run_id,)).fetchone()[0] == 0
    # The rows the team typed survive; only the ledger copy is gone.
    assert len(by_key["runs"]["payload"]["runs"]) == 1


def test_only_a_validated_shift_can_be_reversed_and_it_needs_a_reason(db, env):
    shift_id = _submitted_shift(db, env)
    reverse = ShiftValidationService(db).reverse_shift
    early = reverse(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, reason="x")
    assert isinstance(early, Err) and early.code == "INVALID_TRANSITION"
    _ok(_validate(db, env, shift_id))
    blank = reverse(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, reason=" ")
    assert isinstance(blank, Err) and blank.code == "MISSING_REASON"


def test_a_reversed_shift_can_be_fixed_and_validated_again(db, env):
    shift_id = _submitted_shift(db, env)
    before = _on_hand(db, env, "semolina")
    _ok(_validate(db, env, shift_id))
    _ok(ShiftValidationService(db).reverse_shift(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, reason="fix"))
    service = ShiftReportService(db)
    for key in ("runs", "packing"):
        _ok(service.submit_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key))
    assert _shift(db, shift_id)["status"] == "submitted"
    _ok(_validate(db, env, shift_id))
    assert _on_hand(db, env, "semolina") == before - 1000


def test_the_shift_shows_the_packaging_frozen_and_tonnage_settled_at_validation(db, env):
    # Give the finished product the packaging validation freezes: 500 g packets, 20 to a carton.
    db.execute("UPDATE core.products SET net_weight_grams = 500, packets_per_carton = 20 WHERE id = %s", (env["product"],))
    shift_id = _submitted_shift(db, env)
    _ok(_validate(db, env, shift_id))
    packing_id = next(s for s in _shift(db, shift_id)["sections"] if s["key"] == "packing")["payload"]["rows"][0]["id"]
    net, per_carton, tonnage = db.execute(
        "SELECT snapshot_net_weight_grams, snapshot_packets_per_carton, finished_product_quantity "
        "FROM production.shift_packing_rows WHERE id = %s", (packing_id,)
    ).fetchone()
    ledger = db.execute(
        "SELECT snapshot_net_weight_grams, snapshot_packets_per_carton, finished_product_quantity "
        "FROM production.conditionnement_reports WHERE report_id = %s", (packing_id,)
    ).fetchone()
    assert (float(net), float(per_carton)) == (500.0, 20.0)
    # 100 cartons of 20 packets of 500 g: what the count settles to, not the 800 the team typed.
    assert float(tonnage) == pytest.approx(1.0)


def test_reversing_a_carton_product_takes_back_exactly_what_validation_packed(db, env):
    db.execute("UPDATE core.products SET net_weight_grams = 500, packets_per_carton = 20 WHERE id = %s", (env["product"],))
    shift_id = _submitted_shift(db, env)
    _ok(_validate(db, env, shift_id))
    assert _on_hand(db, env, location_key="fg_location") == pytest.approx(2000)  # 100 cartons of 20
    # The reversal reads the frozen snapshot back from the database, not from the product.
    _ok(ShiftValidationService(db).reverse_shift(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, reason="test"))
    assert _on_hand(db, env, location_key="fg_location") == pytest.approx(0)


# test_rerunning_the_legacy_conversion... removed: Task 3 rewrite eliminates the materialize_shift bridge
# so this test's premise (old-shaped rows written by validation) no longer applies. The convert_legacy_reports()
# SQL function still exists for the one-time migration, but validation no longer feeds it. Task 8 will handle cleanup.


# ---- reversing: two runs, and a rebroyat batch already ground ------------------


def test_reversing_a_two_run_shift_puts_back_each_runs_semoule(db, env):
    """A mold change splits the shift into two runs; reversal must undo both, not just the first."""
    service = ShiftReportService(db)
    shift_id = _ok(service.open_shift(tenant_id=TENANT, actor_id=env["actor"], work_center_id=env["work_center"], report_date=DAY, shift="night"))["id"]
    first, second = _of(db, env), _of(db, env)
    semolina_before = _on_hand(db, env, "semolina")
    _ok(service.save_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key="runs",
                             payload=_poured([_run(env, first, minutes=240, semolina=400), _run(env, second, minutes=180, semolina=300)])))
    for key in SECTION_KEYS:
        if key == "runs":
            _ok(service.submit_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key))
        else:
            _ok(service.declare_nothing(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key))
    _ok(_validate(db, env, shift_id))
    assert _on_hand(db, env, "semolina") == semolina_before - 700

    _ok(ShiftValidationService(db).reverse_shift(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, reason="mold change entered twice"))

    assert _on_hand(db, env, "semolina") == semolina_before


def _rebroyat(db, env) -> str:
    """Rebroyat cannot open its own OF without knowing what the regrind yields."""
    rebroyat = str(ULID())
    uom = db.execute("SELECT uom_id FROM core.products WHERE id = %s", (env["product"],)).fetchone()[0]
    db.execute("INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, 'SV-REBROYAT', 'Rebroyat', %s)",
               (rebroyat, TENANT, uom))
    _ok(RegrindDefaultsService(db).set_default(tenant_id=TENANT, actor_id=env["actor"], output_product_id=rebroyat))
    return rebroyat


def _close_the_regrind_batch(db, env, actual_output_quantity=38) -> str:
    batch_of_id = db.execute(
        "SELECT work_order_id FROM production.regrind_batches WHERE tenant_id = %s AND actual_output_quantity IS NULL", (TENANT,)
    ).fetchone()[0]
    _ok(RegrindService(db).assign_batch(tenant_id=TENANT, actor_id=env["actor"], work_order_id=batch_of_id, team="Équipe A"))
    _ok(RegrindService(db).complete_batch(
        tenant_id=TENANT, actor_id=env["actor"], work_order_id=batch_of_id, correlation_id=str(ULID()),
        location_id=env["location"], actual_output_quantity=actual_output_quantity,
    ))
    return batch_of_id


def test_a_ground_rebroyat_batch_blocks_reversing_the_shift_and_leaves_it_validated(db, env):
    """Its output is physically in stock; reversing the shift underneath it would leave stock nobody can explain."""
    _rebroyat(db, env)
    shift_id = _submitted_shift(db, env, runs=None, packing=False)
    run_id = _shift(db, shift_id)["sections"][0]["payload"]["runs"][0]["id"]
    db.execute("UPDATE production.shift_runs SET regrind_quantity = 40 WHERE id = %s", (run_id,))
    _ok(_validate(db, env, shift_id))
    _close_the_regrind_batch(db, env)
    semolina_after_validation = _on_hand(db, env, "semolina")

    result = ShiftValidationService(db).reverse_shift(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, reason="too late")

    assert isinstance(result, Err) and result.code == "REGRIND_ALREADY_COMPLETED"
    assert _shift(db, shift_id)["status"] == "validated"
    assert _on_hand(db, env, "semolina") == semolina_after_validation, "the refusal must not leave half a reversal behind"


def test_force_reversing_hands_back_the_ground_rebroyat_and_removes_its_order(db, env):
    rebroyat = _rebroyat(db, env)
    shift_id = _submitted_shift(db, env, runs=None, packing=False)
    run_id = _shift(db, shift_id)["sections"][0]["payload"]["runs"][0]["id"]
    db.execute("UPDATE production.shift_runs SET regrind_quantity = 40 WHERE id = %s", (run_id,))
    semolina_before = _on_hand(db, env, "semolina")
    _ok(_validate(db, env, shift_id))
    batch_of_id = _close_the_regrind_batch(db, env, actual_output_quantity=38)
    env["rebroyat"] = rebroyat
    assert _on_hand(db, env, "rebroyat") == 38

    _ok(ShiftValidationService(db).reverse_shift(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, reason="wrong line", force=True))

    assert _on_hand(db, env, "rebroyat") == 0
    assert _on_hand(db, env, "semolina") == semolina_before
    assert db.execute("SELECT count(*) FROM production.work_orders WHERE id = %s", (batch_of_id,)).fetchone()[0] == 0
    assert db.execute("SELECT count(*) FROM production.scrap_records WHERE tenant_id = %s", (TENANT,)).fetchone()[0] == 0


# ---- a validator's own correction, mid-review ----------------------------------


def _runs_with_semolina(db, shift_id, quantity) -> dict:
    """The shift's saved runs payload, with the semoule poured changed -- run ids kept,
    so the packing row that points at the run still points at it."""
    payload = _shift(db, shift_id)["sections"][0]["payload"]
    payload["versements"][0]["quantity"] = quantity
    return {"runs": payload["runs"], "versements": payload["versements"]}


def _validator_edit(db, env, shift_id, *, section_key="runs", payload=None, reason="corrected the semoule quantity"):
    return ShiftValidationService(db).edit_section_as_validator(
        tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=section_key,
        payload=payload if payload is not None else _runs_with_semolina(db, shift_id, 1200), reason=reason,
    )


def test_validator_can_edit_a_submitted_section_with_a_reason(db, env):
    shift_id = _submitted_shift(db, env)

    edited = _ok(_validator_edit(db, env, shift_id))

    assert edited["status"] == "submitted"  # stays submitted, not draft
    assert edited["shift_status"] == "submitted"
    stored = _shift(db, shift_id)["sections"][0]["payload"]["runs"][0]
    assert float(stored["semolina_lines"][0]["quantity"]) == 1200
    history = _ok(ShiftReportService(db).list_revisions(tenant_id=TENANT, shift_report_id=shift_id, section_key="runs"))
    assert history[0]["reason"] == "corrected the semoule quantity"
    assert history[0]["edited_by_validator"] is True
    audit = db.execute(
        "SELECT payload FROM core.audit_log WHERE entity_id = %s AND action = 'shift_report.section_edited_by_validator'",
        (shift_id,),
    ).fetchone()
    assert audit is not None and audit[0]["reason"] == "corrected the semoule quantity"


def test_validator_edit_requires_a_reason(db, env):
    shift_id = _submitted_shift(db, env)
    for reason in ("", "   "):
        result = _validator_edit(db, env, shift_id, reason=reason)
        assert isinstance(result, Err) and result.code == "MISSING_REASON"


def test_validator_edit_refused_when_shift_is_not_submitted(db, env):
    shift_id = _submitted_shift(db, env)
    payload = _runs_with_semolina(db, shift_id, 1200)
    _ok(_validate(db, env, shift_id))  # now 'validated'
    result = _validator_edit(db, env, shift_id, payload=payload, reason="too late")
    assert isinstance(result, Err) and result.code == "INVALID_TRANSITION"


def test_validator_edit_refused_on_a_shift_still_being_filled(db, env):
    shift_id = _ok(ShiftReportService(db).open_shift(tenant_id=TENANT, actor_id=env["actor"], work_center_id=env["work_center"],
                                                     report_date=DAY, shift="evening"))["id"]
    result = _validator_edit(db, env, shift_id, payload={"runs": [_run(env, _of(db, env))]}, reason="not in review yet")
    assert isinstance(result, Err) and result.code == "INVALID_TRANSITION"


def test_validator_edit_rejects_unknown_section(db, env):
    shift_id = _submitted_shift(db, env)
    result = _validator_edit(db, env, shift_id, section_key="not_a_section", payload={}, reason="typo")
    assert isinstance(result, Err) and result.code == "INVALID_SECTION"


def test_validator_edit_does_not_trip_changed_since_opened_on_own_edit(db, env):
    shift_id = _submitted_shift(db, env)
    seen = {s["key"]: s["revision"] for s in _shift(db, shift_id)["sections"]}

    _ok(_validator_edit(db, env, shift_id, payload=_runs_with_semolina(db, shift_id, 1100), reason="fix"))

    # The baseline from before the edit still fails -- the guard is real. The frontend
    # refreshes seen_revisions after its own edit before the next Approve.
    stale = _validate(db, env, shift_id, seen_revisions=seen)
    assert isinstance(stale, Err) and stale.code == "CHANGED_SINCE_OPENED"
    refreshed = {s["key"]: s["revision"] for s in _shift(db, shift_id)["sections"]}
    _ok(_validate(db, env, shift_id, seen_revisions=refreshed))


def test_validator_edit_by_someone_else_still_trips_changed_since_opened(db, env):
    """A concurrent edit after the reviewer opened the shift must still refuse their Approve."""
    shift_id = _submitted_shift(db, env)
    seen = {s["key"]: s["revision"] for s in _shift(db, shift_id)["sections"]}
    _ok(_validator_edit(db, env, shift_id, payload=_runs_with_semolina(db, shift_id, 1300), reason="someone else's fix"))

    result = _validate(db, env, shift_id, seen_revisions=seen)
    assert isinstance(result, Err) and result.code == "CHANGED_SINCE_OPENED"


def test_validator_edit_flag_stays_on_its_own_revision(db, env):
    """A later team revision does not inherit the flag, and the edited one keeps it."""
    shift_id = _submitted_shift(db, env)
    _ok(_validator_edit(db, env, shift_id))
    _ok(ShiftValidationService(db).reject_sections(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id,
                                                   section_keys=["runs"], reason="recount"))
    _ok(ShiftReportService(db).save_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id,
                                            section_key="runs", payload=_runs_with_semolina(db, shift_id, 1250), reason="team recount"))
    _ok(ShiftReportService(db).submit_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key="runs"))

    history = _ok(ShiftReportService(db).list_revisions(tenant_id=TENANT, shift_report_id=shift_id, section_key="runs"))
    flagged = [h["revision"] for h in history if h["edited_by_validator"]]
    assert len(flagged) == 1
    assert history[0]["edited_by_validator"] is False
    assert next(h for h in history if h["edited_by_validator"])["reason"] == "corrected the semoule quantity"


# ---- an admin's correction, after validation -------------------------------------


def _unlocked_edit(db, env, shift_id, *, section_key="runs", payload=None, reason="fixing a typo after the fact"):
    return ShiftValidationService(db).edit_section_after_validation(
        tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=section_key,
        payload=payload if payload is not None else _runs_with_semolina(db, shift_id, 1400), reason=reason,
    )


def test_admin_can_edit_a_validated_section_and_it_stays_validated(db, env):
    shift_id = _submitted_shift(db, env)
    _ok(_validate(db, env, shift_id))

    edited = _ok(_unlocked_edit(db, env, shift_id))

    assert edited["status"] == "submitted"  # the section's own status is untouched
    assert edited["shift_status"] == "validated"  # and so is the shift's
    stored = _shift(db, shift_id)["sections"][0]["payload"]["runs"][0]
    assert float(stored["semolina_lines"][0]["quantity"]) == 1400
    history = _ok(ShiftReportService(db).list_revisions(tenant_id=TENANT, shift_report_id=shift_id, section_key="runs"))
    assert history[0]["reason"] == "fixing a typo after the fact"
    assert history[0]["edited_after_validation"] is True
    assert history[0]["edited_by_validator"] is False
    audit = db.execute(
        "SELECT payload FROM core.audit_log WHERE entity_id = %s AND action = 'shift_report.section_edited_after_validation'",
        (shift_id,),
    ).fetchone()
    assert audit is not None and audit[0]["reason"] == "fixing a typo after the fact"


def test_admin_edit_after_validation_does_not_require_a_reason(db, env):
    shift_id = _submitted_shift(db, env)
    _ok(_validate(db, env, shift_id))

    edited = _ok(_unlocked_edit(db, env, shift_id, reason=""))

    assert edited["shift_status"] == "validated"
    history = _ok(ShiftReportService(db).list_revisions(tenant_id=TENANT, shift_report_id=shift_id, section_key="runs"))
    assert history[0]["reason"] is None
    assert history[0]["edited_after_validation"] is True


def test_admin_edit_after_validation_refused_when_shift_is_not_validated(db, env):
    shift_id = _submitted_shift(db, env)  # still 'submitted', not validated
    result = _unlocked_edit(db, env, shift_id)
    assert isinstance(result, Err) and result.code == "INVALID_TRANSITION"


def test_admin_edit_after_validation_rejects_unknown_section(db, env):
    shift_id = _submitted_shift(db, env)
    _ok(_validate(db, env, shift_id))
    result = _unlocked_edit(db, env, shift_id, section_key="not_a_section", payload={})
    assert isinstance(result, Err) and result.code == "INVALID_SECTION"


def test_admin_edit_after_validation_flag_stays_on_its_own_revision(db, env):
    """A normal team edit elsewhere in the section's history does not inherit the flag."""
    shift_id = _submitted_shift(db, env)
    _ok(_validate(db, env, shift_id))
    _ok(_unlocked_edit(db, env, shift_id))
    _ok(_unlocked_edit(db, env, shift_id, payload=_runs_with_semolina(db, shift_id, 1500), reason="one more fix"))

    history = _ok(ShiftReportService(db).list_revisions(tenant_id=TENANT, shift_report_id=shift_id, section_key="runs"))
    flagged = [h["revision"] for h in history if h["edited_after_validation"]]
    assert len(flagged) == 2
    assert all(not h["edited_by_validator"] for h in history)


# ---- where packed goods land ----------------------------------------------------


def test_packed_goods_wait_in_the_line_store_and_the_shift_records_it(db, env):
    """A row that carries the product's own store (what the screen pre-fills) means "not chosen":
    with a line store configured, the goods wait there until released, and the shift shows it."""
    line = str(ULID())
    db.execute("INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, 'SV-LINE', 'Stock ligne')", (line, TENANT))
    db.execute("UPDATE core.products SET default_location_id = %s WHERE id = %s", (env["fg_location"], env["product"]))
    _ok(DashboardSettingsService(db).replace_store_roles(
        tenant_id=TENANT, actor_id=env["actor"], entries=[{"location_id": line, "role": "line"}]
    ))
    shift_id = _submitted_shift(db, env)

    _ok(_validate(db, env, shift_id))

    env["line"] = line
    assert _on_hand(db, env, "product", "line") > 0
    assert _on_hand(db, env, "product", "fg_location") == 0
    packing_id = next(s for s in _shift(db, shift_id)["sections"] if s["key"] == "packing")["payload"]["rows"][0]["id"]
    stored = db.execute("SELECT finished_goods_location_id FROM production.shift_packing_rows WHERE id = %s", (packing_id,)).fetchone()[0]
    assert stored == line


def test_validation_is_refused_while_a_full_inventory_freezes_a_location_it_would_post_to(db, env):
    from modules.warehouse.api.inventory_service import InventoryService

    shift_id = _submitted_shift(db, env)
    inventory = InventoryService(db).open(tenant_id=TENANT, actor_id=env["actor"], location_id=env["location"], type="full")
    assert isinstance(inventory, Ok)
    semolina_before = _on_hand(db, env, "semolina")
    moves_before = db.execute("SELECT count(*) FROM warehouse.stock_moves WHERE tenant_id = %s", (TENANT,)).fetchone()[0]

    refused = _validate(db, env, shift_id)

    assert isinstance(refused, Err) and refused.code == "LOCATION_FROZEN"
    assert _on_hand(db, env, "semolina") == semolina_before
    assert db.execute("SELECT count(*) FROM warehouse.stock_moves WHERE tenant_id = %s", (TENANT,)).fetchone()[0] == moves_before
    assert _shift(db, shift_id)["status"] == "submitted"

    # Counting done and the inventory closed (no variance), the same shift validates.
    opened = InventoryService(db).get(tenant_id=TENANT, inventory_id=inventory.value["id"]).value
    for line in opened["lines"]:
        for which in (1, 2):
            InventoryService(db).record_count(tenant_id=TENANT, actor_id=env["actor"], inventory_id=opened["id"], line_id=line["id"],
                                              which=which, quantity=line["theoretical_qty"])
    assert isinstance(InventoryService(db).close(tenant_id=TENANT, actor_id=env["actor"], inventory_id=opened["id"], correlation_id="c"), Ok)
    assert isinstance(_validate(db, env, shift_id), Ok)
