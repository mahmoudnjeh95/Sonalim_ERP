"""A validated shift's end-of-shift silo reading says whether each side of the line is running.

The report is the newest word from the floor, so once a shift is validated the machines of
the side it names are moved through Maintenance's own status change (audited there). It
applies only when no later shift on the same line has already been validated: validating an
old shift late must not undo what a newer one said. A machine in maintenance is left alone,
and a change Maintenance refuses is skipped, not an error.
"""
from __future__ import annotations

import psycopg

from modules.maintenance.api.equipment_service import EquipmentService
from modules.production.domain.line_machines import silo_machine_changes


def _later_shift_validated(
    connection: psycopg.Connection, *, tenant_id: str, work_center_id: str, report_date, shift: str, shift_report_id: str
) -> bool:
    """A validated shift on this line that starts after this one (date first, then the shift's clock start)."""
    row = connection.execute(
        """
        SELECT 1
        FROM production.shift_reports s
        LEFT JOIN production.shift_windows w ON w.tenant_id = s.tenant_id AND w.shift = s.shift
        LEFT JOIN production.shift_windows mine ON mine.tenant_id = %s AND mine.shift = %s
        WHERE s.tenant_id = %s AND s.work_center_id = %s AND s.status = 'validated' AND s.id <> %s
          AND (s.report_date > %s
               OR (s.report_date = %s AND COALESCE(w.start_time, TIME '00:00') > COALESCE(mine.start_time, TIME '00:00')))
        LIMIT 1
        """,
        (tenant_id, shift, tenant_id, work_center_id, shift_report_id, report_date, report_date),
    ).fetchone()
    return row is not None


def apply_silo_machine_status(
    connection: psycopg.Connection, *, tenant_id: str, actor_id: str, shift_report_id: str
) -> None:
    work_center_id, report_date, shift = connection.execute(
        "SELECT work_center_id, report_date, shift FROM production.shift_reports WHERE id = %s AND tenant_id = %s",
        (shift_report_id, tenant_id),
    ).fetchone()
    if _later_shift_validated(
        connection,
        tenant_id=tenant_id,
        work_center_id=work_center_id,
        report_date=report_date,
        shift=shift,
        shift_report_id=shift_report_id,
    ):
        return
    readings = connection.execute(
        "SELECT side, line_state FROM production.shift_silo_states "
        "WHERE shift_report_id = %s AND tenant_id = %s AND phase = 'end' AND line_state IS NOT NULL",
        (shift_report_id, tenant_id),
    ).fetchall()
    equipment = EquipmentService(connection)
    for side, line_state in readings:
        machines = [
            (machine.id, machine.production_stage, machine.status)
            for machine in equipment.list_equipment(tenant_id=tenant_id, work_center_id=work_center_id)
        ]
        for machine_id, new_status in silo_machine_changes(side=side, line_state=line_state, machines=machines):
            equipment.transition_status(
                tenant_id=tenant_id, actor_id=actor_id, equipment_id=machine_id, new_status=new_status
            )


def reapply_latest_silo_status(
    connection: psycopg.Connection, *, tenant_id: str, actor_id: str, reversed_shift_report_id: str
) -> None:
    """After a shift's validation is undone, the line's newest word is the latest shift still validated.

    When the reversed shift was the newest word, the latest one still validated has its silo
    reading applied again, so the reversed reading does not keep the machines where it put
    them. A later shift already validated had the last word anyway, and with nothing
    validated left on the line the machines stay as they are.
    """
    work_center_id, report_date, shift = connection.execute(
        "SELECT work_center_id, report_date, shift FROM production.shift_reports WHERE id = %s AND tenant_id = %s",
        (reversed_shift_report_id, tenant_id),
    ).fetchone()
    if _later_shift_validated(
        connection, tenant_id=tenant_id, work_center_id=work_center_id, report_date=report_date, shift=shift,
        shift_report_id=reversed_shift_report_id,
    ):
        return
    latest = connection.execute(
        """
        SELECT s.id
        FROM production.shift_reports s
        LEFT JOIN production.shift_windows w ON w.tenant_id = s.tenant_id AND w.shift = s.shift
        WHERE s.tenant_id = %s AND s.work_center_id = %s AND s.status = 'validated'
        ORDER BY s.report_date DESC, COALESCE(w.start_time, TIME '00:00') DESC, s.id DESC
        LIMIT 1
        """,
        (tenant_id, work_center_id),
    ).fetchone()
    if latest is not None:
        apply_silo_machine_status(connection, tenant_id=tenant_id, actor_id=actor_id, shift_report_id=latest[0])
