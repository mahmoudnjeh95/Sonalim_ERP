"""Validating, rejecting and reversing a whole shift, against real stock.

A shift is filled through ShiftReportService exactly as a team would, then a
validator approves it. Every test runs in the rolled-back `db` transaction.
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
                             payload={"runs": runs if runs is not None else [_run(env, of_id)]}))
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
    _ok(service.save_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key="runs", payload={"runs": [_run(env, of_id)]}))
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
                             payload={"runs": [_run(env, first, minutes=260, semolina=400), _run(env, second, minutes=160, semolina=300)]}))
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
        "SELECT source_id, quantity FROM warehouse.stock_moves WHERE source_id = ANY(%s) AND direction = 'out'",
        (run_ids,),
    ).fetchall()}
    assert float(moved[run_ids[0]]) == 400
    assert float(moved[run_ids[1]]) == 300
    assert _on_hand(db, env, "semolina") == semolina_before - 700


def test_stops_and_waste_reach_the_reports_they_belong_to(db, env):
    stops = {"stops": [
        {"started_at": "2030-06-07T08:55:00+00:00", "ended_at": "2030-06-07T09:06:00+00:00", "motif": "extruder_failure",
         "corrective_action": "Nettoyage"},
    ]}
    waste = lambda run_ids: {  # noqa: E731
        "waste_lines": [{"category": "press", "quantity": 6.4, "run_id": run_ids[0], "product_id": env["semolina"]},
                          {"category": "kneading", "quantity": 1.5, "product_id": env["semolina"]}]
    }
    shift_id = _submitted_shift(db, env, extra={"stops": stops, "waste_production": waste})
    _ok(_validate(db, env, shift_id))
    run_id = _shift(db, shift_id)["sections"][0]["payload"]["runs"][0]["id"]
    minutes, motif, note = db.execute(
        "SELECT minutes, motif, note FROM production.report_downtime_lines WHERE report_id = %s", (run_id,)
    ).fetchone()
    assert (minutes, motif) == (11, "extruder_failure") and "Nettoyage" in note
    kinds = dict(db.execute("SELECT category, quantity FROM production.report_waste_lines WHERE report_id = %s", (run_id,)).fetchall())
    assert {k: float(v) for k, v in kinds.items()} == {"press": 6.4, "kneading": 1.5}  # the unassigned line joined the first run


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
    assert (net, per_carton, tonnage) == ledger, "the shift and the readers must agree"
    # 100 cartons of 20 packets of 500 g: what the count settles to, not the 800 the team typed.
    assert float(tonnage) == pytest.approx(1.0)


def test_rerunning_the_legacy_conversion_does_not_turn_a_validated_shifts_copies_back_into_stops(db, env):
    """Validation writes old-shaped copies of the shift into the legacy tables. The one-time conversion
    of legacy reports must leave them alone, or every stop of a new shift would be counted twice."""
    stops = {"stops": [{"started_at": "2030-06-07T08:55:00+00:00", "ended_at": "2030-06-07T09:06:00+00:00", "motif": "extruder_failure"}]}
    shift_id = _submitted_shift(db, env, extra={"stops": stops})
    _ok(_validate(db, env, shift_id))

    def counts():
        return tuple(
            db.execute(f"SELECT count(*) FROM production.{t} WHERE shift_report_id = %s", (shift_id,)).fetchone()[0]
            for t in ("machine_stops", "shift_runs", "shift_packing_rows", "shift_waste_lines", "shift_energy")
        )

    before = counts()
    db.execute("SELECT production.convert_legacy_reports()")
    assert counts() == before
    assert before[0] == 1
