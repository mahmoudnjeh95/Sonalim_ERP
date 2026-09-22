from __future__ import annotations

import datetime

import psycopg

from modules.maintenance.api.equipment_service import PRODUCTION_STAGES, EquipmentService
from modules.production.api.dashboard_settings_service import DashboardSettingsService
from modules.production.domain.dashboard import current_shift, line_state, team_rotation_schedule

# An OF that still has work to do on its line. `planned` has not started and
# `closed`/`cancelled` are over, so none of them is "on the line" right now.
OPEN_OF_STATUSES = ("ongoing", "suspended")


def _hhmm(value: datetime.time | None) -> str | None:
    return value.strftime("%H:%M") if value is not None else None


_STAGE_RANK = {stage: rank for rank, stage in enumerate(PRODUCTION_STAGES)}


class DashboardLinesService:
    """The live board: every line, the OFs open on it, its machines, and the
    4-team rotation for the day being shown, each team's slot coloured by
    whatever shift report exists for it.

    Nothing about a machine is entered on the dashboard. Which machines a line
    has, what each one is called, what state it is in and which stage it works
    at are all read from maintenance's equipment registry (through its public
    service, the same in-process call `/production/machines` makes), so a
    machine added or edited there shows up here with no further setup. Status
    is read, never inferred: the OF's own status and each machine's own
    status. Which shift is current comes from the clock times the plant
    configured; with none configured nothing is current.
    """

    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def get_lines(self, *, tenant_id: str, at: datetime.time, date: datetime.date, today: datetime.date) -> dict:
        settings = DashboardSettingsService(self._connection)
        windows = settings.list_shift_windows(tenant_id=tenant_id)
        sorted_windows = sorted(windows, key=lambda w: (w.start, w.shift))
        sorted_shifts = [w.shift for w in sorted_windows]
        running = current_shift(windows, at)
        is_today = date == today

        rotation_rows = self._connection.execute(
            "SELECT team, anchor_date, anchor_stop FROM production.team_rotation WHERE tenant_id = %s ORDER BY team",
            (tenant_id,),
        ).fetchall()
        schedule = sorted(
            team_rotation_schedule(shifts=sorted_shifts, rotation=rotation_rows, date=date),
            key=lambda e: e["team"].lower(),
        )

        report_status_by_line: dict[str, dict[str, str]] = {}
        for work_center_id, shift, report_status in self._connection.execute(
            "SELECT work_center_id, shift, status FROM production.shift_reports WHERE tenant_id = %s AND report_date = %s",
            (tenant_id, date),
        ).fetchall():
            report_status_by_line.setdefault(work_center_id, {})[shift.lower()] = report_status

        def team_status_for(line_id: str) -> list[dict]:
            statuses = report_status_by_line.get(line_id, {})
            return [
                {
                    "team": entry["team"],
                    "shift": entry["shift"],
                    "status": statuses.get(entry["shift"].lower()) if entry["shift"] else None,
                    "is_current": bool(
                        is_today and running is not None and entry["shift"] is not None
                        and entry["shift"].lower() == running.shift.lower()
                    ),
                }
                for entry in schedule
            ]

        equipment_by_line: dict[str, list] = {}
        for machine in EquipmentService(self._connection).list_equipment(tenant_id=tenant_id):
            equipment_by_line.setdefault(machine.work_center_id, []).append(machine)

        ofs_by_line: dict[str, list[dict]] = {}
        for of_id, reference, of_status, work_center_id, product_type, product_name, start_date in self._connection.execute(
            """
            SELECT w.id, w.reference, w.status, w.work_center_id, w.product_type, p.name, w.start_date
            FROM production.work_orders w
            LEFT JOIN core.products p ON p.id = w.product_id AND p.tenant_id = w.tenant_id
            WHERE w.tenant_id = %s AND w.status = ANY(%s)
            ORDER BY w.start_date NULLS LAST, w.reference
            """,
            (tenant_id, list(OPEN_OF_STATUSES)),
        ).fetchall():
            ofs_by_line.setdefault(work_center_id, []).append(
                {
                    "of_id": of_id,
                    "reference": reference,
                    "status": of_status,
                    "product_type": product_type,
                    "product_name": product_name,
                    "start_date": start_date.isoformat() if start_date else None,
                }
            )

        lines = []
        for line_id, code, name, is_blocked, blocked_reason in self._connection.execute(
            "SELECT id, code, name, is_blocked, blocked_reason FROM production.work_centers WHERE tenant_id = %s ORDER BY code",
            (tenant_id,),
        ).fetchall():
            machines = equipment_by_line.get(line_id, [])
            machine_statuses = [m.status for m in machines]
            # Along the line in stage order; the ones with no stage yet come last.
            listed = sorted(
                (
                    {"id": m.id, "code": m.code, "name": m.name, "status": m.status, "stage": m.production_stage}
                    for m in machines
                ),
                key=lambda m: (_STAGE_RANK.get(m["stage"], len(PRODUCTION_STAGES)), m["code"]),
            )
            lines.append(
                {
                    "work_center_id": line_id,
                    "code": code,
                    "name": name,
                    "is_blocked": is_blocked,
                    "blocked_reason": blocked_reason,
                    "ofs": [
                        {**of, "state": line_state(of_status=of["status"], machine_statuses=machine_statuses)}
                        for of in ofs_by_line.get(line_id, [])
                    ],
                    "machines": listed,
                    "team_status": team_status_for(line_id),
                }
            )

        return {
            "at": _hhmm(at),
            "current_shift": (
                {"shift": running.shift, "start_time": _hhmm(running.start), "end_time": _hhmm(running.end)}
                if running is not None
                else None
            ),
            "shift_windows": [
                {"shift": w.shift, "start_time": _hhmm(w.start), "end_time": _hhmm(w.end)} for w in sorted_windows
            ],
            "lines": lines,
        }
