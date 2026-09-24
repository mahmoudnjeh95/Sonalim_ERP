"""The board's live view: the shift running on each line right now, read before it is validated."""
from __future__ import annotations

import datetime

import pytest

from modules.production.api.dashboard_live_service import DashboardLiveService
from modules.production.api.shift_report_service import ShiftReportService
from modules.production.api.shift_validation_service import ShiftValidationService
from modules.production.api.test_shift_machine_integration import (  # noqa: F401  (env is a fixture)
    DAY,
    TENANT,
    _ok,
    _submitted_shift,
    _validate,
    env,
)
from modules.production.api.test_shift_wiring_integration import _draft_shift


@pytest.fixture
def windows(db):
    for shift, start, end in (("morning", "07:00", "14:00"), ("afternoon", "14:00", "22:00"), ("night", "22:00", "07:00")):
        db.execute("INSERT INTO production.shift_windows (tenant_id, shift, start_time, end_time) VALUES (%s, %s, %s, %s)", (TENANT, shift, start, end))


def _live(db, at="09:00", date=DAY):
    return DashboardLiveService(db).get_live(tenant_id=TENANT, date=date, at=datetime.time.fromisoformat(at))


def _line(live, env):
    return next((l for l in live["lines"] if l["work_center_id"] == env["work_center"]), None)


def test_without_configured_shifts_nothing_is_current(db, env):
    live = _live(db)
    assert live["shift"] is None and live["lines"] == []


def test_a_line_with_no_report_for_the_current_shift_is_not_listed(db, env, windows):
    live = _live(db, "09:00")
    assert live["shift"]["shift"] == "morning"
    assert _line(live, env) is None  # the board says "no report opened yet" for it


def test_a_handed_in_shift_shows_its_figures_marked_by_status(db, env, windows):
    shift_id = _submitted_shift(db, env, shift="morning")
    line = _line(_live(db, "09:00"), env)
    assert line["report"] == {"id": shift_id, "status": "submitted", "team": None}
    of = line["ofs"][0]
    assert (of["semolina_poured"], of["finished_product"], of["production_minutes"], of["packets_counted"]) == (1000, 900, 420, 120)
    assert of["yield_pct"] == pytest.approx(90.0)


def test_a_draft_shows_the_run_so_far(db, env, windows):
    shift_id = _draft_shift(db, env, shift="morning")
    line = _line(_live(db, "09:00"), env)
    assert line["report"]["status"] == "open" and line["report"]["id"] == shift_id
    assert line["ofs"][0]["finished_product"] == 100


def test_a_validated_shift_is_shown_too(db, env, windows):
    _validate(db, env, _submitted_shift(db, env, shift="morning"))
    line = _line(_live(db, "09:00"), env)
    assert line["report"]["status"] == "validated"
    assert line["ofs"][0]["finished_product"] == 900


def test_a_night_shift_after_midnight_belongs_to_the_day_it_started(db, env, windows):
    _submitted_shift(db, env, shift="night")
    after_midnight = _live(db, "02:00", date=DAY + datetime.timedelta(days=1))
    assert after_midnight["shift"]["shift"] == "night"
    assert after_midnight["shift"]["report_date"] == DAY.isoformat()
    assert _line(after_midnight, env)["report"]["status"] == "submitted"
    before_midnight = _live(db, "23:00", date=DAY)
    assert before_midnight["shift"]["report_date"] == DAY.isoformat()


def test_a_returned_shift_is_named_but_shows_no_figures(db, env, windows):
    shift_id = _submitted_shift(db, env, shift="morning")
    _ok(ShiftValidationService(db).reject_sections(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_keys=["packing"], reason="no"))
    line = _line(_live(db, "09:00"), env)
    assert line["report"]["status"] == "returned"
    assert line["ofs"] == []


def test_a_machine_whose_stop_is_still_ongoing_is_listed(db, env, windows):
    shift_id = _draft_shift(db, env, shift="morning")
    _ok(ShiftReportService(db).save_section(
        tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key="stops",
        payload={"stops": [{"equipment_id": env["machines"]["extrusion"], "started_at": "2030-08-05T08:30:00+00:00", "motif": "die_jam"}]},
    ))
    line = _line(_live(db, "09:00"), env)
    stop = line["ongoing_stops"][0]
    assert stop["equipment_id"] == env["machines"]["extrusion"] and stop["motif"] == "die_jam"
    assert datetime.datetime.fromisoformat(stop["since"]) == datetime.datetime.fromisoformat("2030-08-05T08:30:00+00:00")


def test_reading_the_live_view_leaves_nothing_behind(db, env, windows):
    shift_id = _submitted_shift(db, env, shift="morning")
    _live(db, "09:00")
    left = db.execute(
        "SELECT count(*) FROM production.production_reports WHERE tenant_id = %s AND id IN "
        "(SELECT id FROM production.shift_runs WHERE shift_report_id = %s)", (TENANT, shift_id),
    ).fetchone()[0]
    assert left == 0
