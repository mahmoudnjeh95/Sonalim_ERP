"""The semoule flow the fiche works out for itself.

The team used to type a débit into every production row. It is not a judgement: it is
everything poured into the line -- semoule and rebroyat both -- over the hours the line
actually ran, which is the shift's configured length less the stops recorded on the
same fiche. The server derives it so a report reads the same figure the day it is typed
and a year later, and so the run-level analyses downstream never see a stale number.
"""
from __future__ import annotations

import datetime

import pytest
from ulid import ULID

from modules.production.api.service import WorkOrderService
from modules.production.api.shift_report_service import ShiftReportService
from modules.production.api.test_shift_machine_integration import (  # noqa: F401  (env is a fixture)
    DAY,
    TENANT,
    _ok,
    env,
)


def _window(db, shift: str, start: str, end: str) -> None:
    db.execute(
        "INSERT INTO production.shift_windows (tenant_id, shift, start_time, end_time) VALUES (%s, %s, %s, %s) "
        "ON CONFLICT (tenant_id, shift) DO UPDATE SET start_time = EXCLUDED.start_time, end_time = EXCLUDED.end_time",
        (TENANT, shift, start, end),
    )


def _shift_with(db, env, *, versements, rebroyat=None, runs=None, stops=None, shift="morning"):
    service = ShiftReportService(db)
    shift_id = _ok(
        service.open_shift(
            tenant_id=TENANT, actor_id=env["actor"], work_center_id=env["work_center"], report_date=DAY, shift=shift
        )
    )["id"]
    orders = WorkOrderService(db)
    of_id = _ok(
        orders.create_work_order(
            tenant_id=TENANT, actor_id=env["actor"], product_id=env["pasta"], planned_quantity=1000,
            work_center_id=env["work_center"], start_date=DAY,
        )
    ).id
    _ok(orders.start_work_order(tenant_id=TENANT, actor_id=env["actor"], work_order_id=of_id))
    payload = {
        "runs": runs if runs is not None else [{"of_id": of_id, "production_minutes": 420, "finished_product_quantity": 900}],
        "versements": [{"product_id": env["semolina"], "quantity": q, "location_id": env["silo"]} for q in versements],
    }
    if rebroyat:
        payload["rebroyat_versements"] = rebroyat
    for row in payload["runs"]:
        row.setdefault("of_id", of_id)
    _ok(service.save_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key="runs", payload=payload))
    if stops:
        _ok(service.save_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key="stops", payload={"stops": stops}))
    return shift_id, service


def _flows(db, shift_id) -> list[float]:
    return [
        float(row[0])
        for row in db.execute(
            "SELECT semolina_flow_rate FROM production.shift_runs WHERE shift_report_id = %s ORDER BY line_order, id",
            (shift_id,),
        ).fetchall()
    ]


def _stop(start: str, end: str | None, *, ends_next_day: bool = False) -> dict:
    day = DAY.isoformat()
    next_day = (DAY + datetime.timedelta(days=1)).isoformat()
    return {
        "started_at": f"{day}T{start}:00+00:00",
        "ended_at": f"{next_day if ends_next_day else day}T{end}:00+00:00" if end else None,
    }


def test_flow_is_all_the_mp_over_the_hours_the_stops_left(db, env):
    _window(db, "morning", "07:00", "15:00")
    # 40 t semoule + 2 t rebroyat over 8 h less 60 min stopped = 42 / 7 = 6 t/h
    shift_id, _ = _shift_with(
        db, env,
        versements=[25, 15],
        rebroyat=[{"product_id": env["semolina"], "quantity": 2}],
        stops=[_stop("08:00", "08:40"), _stop("09:00", "09:20")],
    )
    assert _flows(db, shift_id) == [6.0]


def test_every_run_shows_the_same_shift_wide_figure(db, env):
    _window(db, "morning", "07:00", "15:00")
    shift_id, _ = _shift_with(
        db, env,
        versements=[42],
        runs=[{"production_minutes": 300, "finished_product_quantity": 500}, {"production_minutes": 120, "finished_product_quantity": 400}],
        stops=[_stop("08:00", "09:00")],
    )
    assert _flows(db, shift_id) == [6.0, 6.0]


def test_a_stop_still_open_does_not_shorten_the_shift(db, env):
    _window(db, "morning", "07:00", "15:00")
    # Only the closed stop counts: 42 / ((480 - 60) / 60) = 6
    shift_id, _ = _shift_with(db, env, versements=[42], stops=[_stop("08:00", "09:00"), _stop("10:00", None)])
    assert _flows(db, shift_id) == [6.0]


def test_the_flow_follows_the_stops_being_edited(db, env):
    _window(db, "morning", "07:00", "15:00")
    shift_id, service = _shift_with(db, env, versements=[42], stops=[_stop("08:00", "09:00")])
    assert _flows(db, shift_id) == [6.0]
    # The team corrects the stop to half an hour: 42 / 7.5 = 5.6
    _ok(service.save_section(
        tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key="stops",
        payload={"stops": [_stop("08:00", "08:30")]},
    ))
    assert _flows(db, shift_id) == [5.6]


def test_no_flow_when_the_shift_hours_are_not_configured(db, env):
    # No window row for this shift: nothing to divide by, so nothing is claimed.
    shift_id, _ = _shift_with(db, env, versements=[42], shift="unconfigured-shift")
    assert _flows(db, shift_id) == [0.0]


def test_no_flow_when_the_stops_leave_no_running_time(db, env):
    _window(db, "morning", "07:00", "15:00")
    shift_id, _ = _shift_with(db, env, versements=[42], stops=[_stop("07:00", "15:00")])
    assert _flows(db, shift_id) == [0.0]


def test_no_flow_before_anything_is_poured_in(db, env):
    _window(db, "morning", "07:00", "15:00")
    shift_id, _ = _shift_with(db, env, versements=[], stops=[_stop("08:00", "09:00")])
    assert _flows(db, shift_id) == [0.0]


def test_a_figure_the_team_types_is_ignored(db, env):
    """The column is derived: a value in the payload never reaches the row."""
    _window(db, "morning", "07:00", "15:00")
    shift_id, _ = _shift_with(
        db, env, versements=[42],
        runs=[{"production_minutes": 420, "semolina_flow_rate": 999}],
        stops=[_stop("08:00", "09:00")],
    )
    assert _flows(db, shift_id) == [6.0]


def test_a_night_shift_crossing_midnight_uses_its_full_length(db, env):
    _window(db, "night", "23:00", "07:00")
    shift_id, _ = _shift_with(db, env, versements=[42], stops=[_stop("23:30", "00:30", ends_next_day=True)], shift="night")
    assert _flows(db, shift_id) == [6.0]
