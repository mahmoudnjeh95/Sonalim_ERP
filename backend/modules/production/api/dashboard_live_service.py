"""The shift running on each line right now, before anyone has validated it.

The board's history is validated reports only. This is the other half: what the team on
shift has entered so far, or handed in and not yet had approved. It is never mixed into
the day's totals, the trend or the rankings; the screen shows it apart, marked as not
validated.

A shift that is still being typed or is waiting for its validator has no report rows yet,
so it is laid out through the same conversion validation uses (`materialize_shift`) inside a
savepoint that is always rolled back, then read with the same figures as the day's totals.
Nothing is written. A returned shift is on its way back to its team and shows no figures.
"""
from __future__ import annotations

import datetime

import psycopg

from modules.production.api.dashboard_day_service import DashboardDayService
from modules.production.api.dashboard_settings_service import DashboardSettingsService
from modules.production.api.legacy_report_ledger import materialize_shift
from modules.production.domain.dashboard import current_shift


def _hhmm(value: datetime.time) -> str:
    return value.strftime("%H:%M")


class DashboardLiveService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def get_live(self, *, tenant_id: str, date: datetime.date, at: datetime.time) -> dict:
        windows = DashboardSettingsService(self._connection).list_shift_windows(tenant_id=tenant_id)
        running = current_shift(windows, at)
        if running is None:
            return {"at": _hhmm(at), "shift": None, "unit": None, "lines": []}

        # A night shift that runs through midnight belongs to the day it started.
        report_date = date - datetime.timedelta(days=1) if running.start > running.end and at < running.end else date
        shift = {
            "shift": running.shift,
            "start_time": _hhmm(running.start),
            "end_time": _hhmm(running.end),
            "report_date": report_date.isoformat(),
        }

        reports = self._connection.execute(
            "SELECT id, work_center_id, team, status, created_by FROM production.shift_reports "
            "WHERE tenant_id = %s AND report_date = %s AND lower(shift) = lower(%s) ORDER BY work_center_id",
            (tenant_id, report_date, running.shift),
        ).fetchall()
        if not reports:
            return {"at": _hhmm(at), "shift": shift, "unit": None, "lines": []}

        showing = [r for r in reports if r[3] != "returned"]
        with self._connection.transaction(force_rollback=True):
            for shift_id, _wc, _team, status, created_by in showing:
                if status in ("open", "submitted"):
                    # A shift with nothing in it yet has nothing to show; that is not an error here.
                    materialize_shift(
                        self._connection,
                        tenant_id=tenant_id,
                        shift_report_id=shift_id,
                        actor_id=created_by or "",
                        provisional=True,
                    )
            figures, unit = DashboardDayService(self._connection, statuses=("validated", "submitted")).shift_figures(
                tenant_id=tenant_id, date=report_date, shift=running.shift, work_center_ids=[r[1] for r in showing]
            )

        ongoing: dict[str, list[dict]] = {}
        for shift_id, work_center_id, _team, status, _by in showing:
            if status not in ("open", "submitted"):
                continue
            for equipment_id, started_at, motif in self._connection.execute(
                "SELECT equipment_id, started_at, motif FROM production.machine_stops "
                "WHERE shift_report_id = %s AND tenant_id = %s AND ended_at IS NULL ORDER BY started_at",
                (shift_id, tenant_id),
            ).fetchall():
                ongoing.setdefault(work_center_id, []).append(
                    {"equipment_id": equipment_id, "since": started_at.isoformat(), "motif": motif}
                )

        return {
            "at": _hhmm(at),
            "shift": shift,
            "unit": unit,
            "lines": [
                {
                    "work_center_id": work_center_id,
                    "report": {"id": shift_id, "status": status, "team": team},
                    "ofs": figures.get(work_center_id, []) if status != "returned" else [],
                    "ongoing_stops": ongoing.get(work_center_id, []),
                }
                for shift_id, work_center_id, team, status, _by in reports
            ],
        }
