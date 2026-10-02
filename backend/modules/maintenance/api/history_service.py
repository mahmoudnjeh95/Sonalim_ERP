"""Read side of a machine's history (spec 2026-10-02-maintenance-history-design.md): the
indicators per machine, the journal, one machine's logbook, one checkpoint's history.

Read-only. Assembled at read time from maintenance's own tables, the status changes in
core.audit_log (shared kernel), production's readings and warehouse's part costs
(`history_sources`). The rules live in domain/history.py.
"""
from __future__ import annotations

import datetime
from collections import defaultdict

import psycopg

from core.domain.result import Err, Ok, Result
from modules.maintenance.api.history_sources import ProductionReadings, job_parts_costs
from modules.maintenance.api.people import employee_names, user_names
from modules.maintenance.domain.history import (
    StatusChange,
    chain_in_order,
    immobilisation,
    maintenance_block,
    outcome_counts,
    period_bounds,
    production_block,
    validate_journal_filters,
    validate_period,
)

UTC = datetime.timezone.utc


def _iso(value: datetime.datetime | datetime.date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _equipment_not_found(equipment_id: str) -> Err:
    return Err("NOT_FOUND", f"equipment {equipment_id} not found", f"équipement {equipment_id} introuvable")


def _has_activity(row: dict) -> bool:
    production, maintenance = row["production"], row["maintenance"]
    return bool(
        (production and production["stops"])
        or maintenance["breakdowns"]
        or maintenance["preventive"]["due"]
        or maintenance["technician_seconds"]
        or maintenance["parts"]["issued_lines"]
        or maintenance["parts"]["purchase_lines"]
        or maintenance["status_changes"]
        or maintenance["immobilised_minutes"]
    )


class HistoryService:
    def __init__(
        self,
        connection: psycopg.Connection,
        *,
        production: ProductionReadings | None,
        now: datetime.datetime | None = None,
    ) -> None:
        self._connection = connection
        self._production = production
        self._now = now or datetime.datetime.now(UTC)

    # ---- indicators --------------------------------------------------------

    def indicators(
        self,
        *,
        tenant_id: str,
        date_from: datetime.date,
        date_to: datetime.date,
        costs_visible: bool,
        equipment_id: str | None = None,
    ) -> Result[dict]:
        """Both blocks for every active machine, plus archived machines with activity in the
        period; with `equipment_id`, that one machine whatever its state."""
        invalid = validate_period(date_from, date_to)
        if invalid is not None:
            return invalid
        machines = self._machines(tenant_id, equipment_id)
        if equipment_id is not None and not machines:
            return _equipment_not_found(equipment_id)
        start, end = period_bounds(date_from, date_to, self._now)
        maintenance = self._maintenance_blocks(tenant_id, machines, date_from, date_to, start, end, costs_visible)
        production, unattributed = self._production_blocks(tenant_id, date_from, date_to, equipment_id)

        rows = []
        for machine in machines:
            machine_id = machine["equipment_id"]
            row = {
                **machine,
                "production": None if production is None else production.get(machine_id) or production_block([], 0),
                "maintenance": maintenance[machine_id],
            }
            if equipment_id is None and machine["archived_at"] is not None and not _has_activity(row):
                continue
            rows.append(row)
        return Ok(
            {
                "from": date_from.isoformat(),
                "to": date_to.isoformat(),
                "costs_visible": costs_visible,
                "production_available": self._production is not None,
                "machines": rows,
                "unattributed_stops": unattributed if equipment_id is None else None,
            }
        )

    def _machines(self, tenant_id: str, equipment_id: str | None = None) -> list[dict]:
        clauses, params = ["e.tenant_id = %s"], [tenant_id]
        if equipment_id is not None:
            clauses.append("e.id = %s")
            params.append(equipment_id)
        rows = self._connection.execute(
            f"""
            SELECT e.id, e.code, e.name, e.work_center_id, e.production_stage, e.status, e.archived_at,
                   photo.id, photo.updated_at
            FROM maintenance.equipment e
            LEFT JOIN LATERAL (
                SELECT v.id, v.updated_at FROM maintenance.equipment_views v
                WHERE v.equipment_id = e.id AND v.image IS NOT NULL
                ORDER BY v.sort_order, v.id
                LIMIT 1
            ) photo ON true
            WHERE {' AND '.join(clauses)}
            ORDER BY e.name, e.code
            """,
            params,
        ).fetchall()
        return [
            {
                "equipment_id": row[0], "code": row[1], "name": row[2], "work_center_id": row[3],
                "production_stage": row[4], "status": row[5], "archived_at": _iso(row[6]),
                "photo_view_id": row[7], "photo_version": _iso(row[8]),
            }
            for row in rows
        ]

    def _status_changes(self, tenant_id: str, equipment_ids: list[str]) -> dict[str, list[StatusChange]]:
        """Every status change of these machines, oldest first -- the ones before the
        period too: they decide the status the period starts in."""
        rows = self._connection.execute(
            """
            SELECT entity_id, occurred_at, payload->>'from_status', payload->>'to_status'
            FROM core.audit_log
            WHERE tenant_id = %s AND entity_type = 'equipment' AND action = 'equipment.status_changed'
              AND entity_id = ANY(%s)
            ORDER BY entity_id, occurred_at, id
            """,
            (tenant_id, equipment_ids),
        ).fetchall()
        changes: dict[str, list[StatusChange]] = defaultdict(list)
        for equipment_id, at, from_status, to_status in rows:
            changes[equipment_id].append(StatusChange(at=at, from_status=from_status, to_status=to_status))
        return {equipment_id: chain_in_order(machine_changes) for equipment_id, machine_changes in changes.items()}

    def _maintenance_blocks(
        self,
        tenant_id: str,
        machines: list[dict],
        date_from: datetime.date,
        date_to: datetime.date,
        start: datetime.datetime,
        end: datetime.datetime,
        costs_visible: bool,
    ) -> dict[str, dict]:
        ids = [machine["equipment_id"] for machine in machines]
        counts = {
            row[0]: row[1:]
            for row in self._connection.execute(
                """
                SELECT equipment_id,
                       count(*) FILTER (WHERE kind = 'corrective' AND status <> 'cancelled'
                                        AND created_at >= %(start)s AND created_at < %(end)s),
                       count(*) FILTER (WHERE kind = 'preventive' AND status <> 'cancelled'
                                        AND due_date BETWEEN %(date_from)s AND %(date_to)s),
                       count(*) FILTER (WHERE kind = 'preventive' AND status = 'closed'
                                        AND due_date BETWEEN %(date_from)s AND %(date_to)s),
                       count(*) FILTER (WHERE kind = 'preventive' AND status = 'closed'
                                        AND due_date BETWEEN %(date_from)s AND %(date_to)s
                                        AND (closed_at AT TIME ZONE 'UTC')::date <= due_date),
                       count(*) FILTER (WHERE kind = 'preventive' AND status NOT IN ('closed', 'cancelled')
                                        AND due_date BETWEEN %(date_from)s AND %(date_to)s AND due_date < %(today)s)
                FROM maintenance.jobs
                WHERE tenant_id = %(tenant)s AND equipment_id = ANY(%(ids)s)
                GROUP BY equipment_id
                """,
                {"start": start, "end": end, "date_from": date_from, "date_to": date_to,
                 "today": self._now.date(), "tenant": tenant_id, "ids": ids},
            ).fetchall()
        }
        # Same rule as the job list: the latest entry of each (check, attempt) counts.
        technician = dict(
            self._connection.execute(
                """
                SELECT j.equipment_id, COALESCE(sum(latest.duration_seconds), 0)
                FROM (
                    SELECT DISTINCT ON (en.check_id, en.attempt) en.check_id, en.duration_seconds, en.finished_at
                    FROM maintenance.check_entries en
                    WHERE en.tenant_id = %s
                    ORDER BY en.check_id, en.attempt, en.created_at DESC, en.id DESC
                ) latest
                JOIN maintenance.job_checks c ON c.id = latest.check_id
                JOIN maintenance.jobs j ON j.id = c.job_id
                WHERE latest.finished_at >= %s AND latest.finished_at < %s AND j.equipment_id = ANY(%s)
                GROUP BY j.equipment_id
                """,
                (tenant_id, start, end, ids),
            ).fetchall()
        )
        parts_rows = self._connection.execute(
            """
            SELECT j.equipment_id, j.number,
                   count(*) FILTER (WHERE COALESCE(l.issued_quantity, 0) > 0),
                   count(*) FILTER (WHERE COALESCE(l.purchase_quantity, 0) > 0)
            FROM maintenance.part_requests r
            JOIN maintenance.jobs j ON j.id = r.job_id
            JOIN maintenance.part_request_lines l ON l.request_id = r.id
            WHERE r.tenant_id = %s AND r.status = 'approved' AND r.decided_at >= %s AND r.decided_at < %s
              AND j.equipment_id = ANY(%s)
            GROUP BY j.equipment_id, j.number
            """,
            (tenant_id, start, end, ids),
        ).fetchall()
        costs = (
            job_parts_costs(self._connection, tenant_id, [row[1] for row in parts_rows if row[2] > 0])
            if costs_visible
            else None
        )
        changes = self._status_changes(tenant_id, ids)
        calendar_minutes = (end - start).total_seconds() / 60

        blocks: dict[str, dict] = {}
        for machine in machines:
            machine_id = machine["equipment_id"]
            corrective, due, closed, on_time, overdue = counts.get(machine_id, (0, 0, 0, 0, 0))
            machine_changes = changes.get(machine_id, [])
            machine_parts = [row for row in parts_rows if row[0] == machine_id]
            cost = unvalued = None
            if costs is not None:
                cost = sum(costs.get(row[1], (0.0, 0.0))[0] for row in machine_parts)
                unvalued = sum(costs.get(row[1], (0.0, 0.0))[1] for row in machine_parts)
            blocks[machine_id] = maintenance_block(
                breakdowns=corrective,
                due=due,
                closed=closed,
                closed_on_time=on_time,
                overdue=overdue,
                stopped=immobilisation(machine_changes, start, end, machine["status"]),
                calendar_minutes=calendar_minutes,
                technician_seconds=int(technician.get(machine_id, 0)),
                issued_lines=sum(row[2] for row in machine_parts),
                purchase_lines=sum(row[3] for row in machine_parts),
                parts_cost=cost,
                parts_unvalued_quantity=unvalued,
                status_changes=sum(1 for c in machine_changes if start <= c.at < end),
            )
        return blocks

    def _production_blocks(
        self, tenant_id: str, date_from: datetime.date, date_to: datetime.date, equipment_id: str | None
    ) -> tuple[dict[str, dict] | None, dict | None]:
        if self._production is None:
            return None, None
        stops = self._production.stops(tenant_id=tenant_id, date_from=date_from, date_to=date_to, equipment_id=equipment_id)
        running = self._production.running_minutes(tenant_id=tenant_id, date_from=date_from, date_to=date_to)
        by_machine: dict[str, list[dict]] = defaultdict(list)
        unattributed: list[dict] = []
        for stop in stops:
            if stop["equipment_id"]:
                by_machine[stop["equipment_id"]].append(stop)
            else:
                unattributed.append(stop)
        blocks = {machine_id: production_block(machine_stops, running.get(machine_id, 0)) for machine_id, machine_stops in by_machine.items()}
        for machine_id, minutes in running.items():
            blocks.setdefault(machine_id, production_block([], minutes))
        return blocks, {"count": len(unattributed), "minutes": sum(stop["minutes"] for stop in unattributed)}

    # ---- journal -------------------------------------------------------------

    def journal(
        self,
        *,
        tenant_id: str,
        date_from: datetime.date,
        date_to: datetime.date,
        costs_visible: bool,
        equipment_id: str | None = None,
        kind: str | None = None,
        status: str = "closed",
    ) -> Result[dict]:
        """Jobs closed (or cancelled) in the period, latest first; a row's date is its
        close (or cancel) date."""
        invalid = validate_period(date_from, date_to) or validate_journal_filters(kind, status)
        if invalid is not None:
            return invalid
        start, end = period_bounds(date_from, date_to, self._now)
        # Fixed column names chosen from a validated status -- never user text in the SQL.
        ended = {"closed": ("closed",), "cancelled": ("cancelled",), "all": ("closed", "cancelled")}[status]
        clauses = ["(" + " OR ".join(
            f"(j.status = '{name}' AND j.{name}_at >= %(start)s AND j.{name}_at < %(end)s)" for name in ended
        ) + ")"]
        params: dict[str, object] = {"start": start, "end": end}
        if equipment_id is not None:
            clauses.append("j.equipment_id = %(equipment)s")
            params["equipment"] = equipment_id
        if kind is not None:
            clauses.append("j.kind = %(kind)s")
            params["kind"] = kind
        rows = self._job_rows(tenant_id, " AND ".join(clauses), params, costs_visible)
        rows.sort(key=lambda row: (row["date"] or "", row["number"]), reverse=True)
        return Ok({"from": date_from.isoformat(), "to": date_to.isoformat(), "costs_visible": costs_visible, "rows": rows})

    def _job_rows(self, tenant_id: str, where: str, params: dict, costs_visible: bool) -> list[dict]:
        """One journal row per job matching `where` (SQL over alias `j`, named params)."""
        jobs = self._connection.execute(
            f"""
            SELECT j.id, j.number, j.equipment_id, e.code, e.name, j.kind, j.priority, j.title, j.status,
                   j.due_date, j.created_at, j.started_at, j.closed_at, j.cancelled_at, j.cancel_reason, j.chef_user_id,
                   (SELECT count(*) FROM maintenance.job_checks c WHERE c.job_id = j.id),
                   (SELECT count(*) FROM maintenance.job_checks c WHERE c.job_id = j.id AND c.state IN ('done', 'accepted'))
            FROM maintenance.jobs j
            JOIN maintenance.equipment e ON e.id = j.equipment_id
            WHERE j.tenant_id = %(tenant)s AND {where}
            """,
            {**params, "tenant": tenant_id},
        ).fetchall()
        ids = [row[0] for row in jobs]
        if not ids:
            return []

        latest = self._connection.execute(
            """
            SELECT DISTINCT ON (en.check_id, en.attempt)
                   c.job_id, en.check_id, en.attempt, en.duration_seconds, en.outcome, en.performer_employee_id
            FROM maintenance.check_entries en
            JOIN maintenance.job_checks c ON c.id = en.check_id
            WHERE c.job_id = ANY(%s)
            ORDER BY en.check_id, en.attempt, en.created_at DESC, en.id DESC
            """,
            (ids,),
        ).fetchall()
        seconds: dict[str, int] = defaultdict(int)
        performers: dict[str, set[str]] = defaultdict(set)
        last_attempt: dict[str, tuple[str, int, str]] = {}
        for job_id, check_id, attempt, duration, outcome, performer in latest:
            seconds[job_id] += duration
            performers[job_id].add(performer)
            if check_id not in last_attempt or attempt > last_attempt[check_id][1]:
                last_attempt[check_id] = (job_id, attempt, outcome)
        outcomes: dict[str, list[str]] = defaultdict(list)
        for job_id, _attempt, outcome in last_attempt.values():
            outcomes[job_id].append(outcome)

        parts = {
            row[0]: (row[1], row[2])
            for row in self._connection.execute(
                """
                SELECT r.job_id,
                       count(*) FILTER (WHERE COALESCE(l.issued_quantity, 0) > 0),
                       count(*) FILTER (WHERE COALESCE(l.purchase_quantity, 0) > 0)
                FROM maintenance.part_requests r
                JOIN maintenance.part_request_lines l ON l.request_id = r.id
                WHERE r.job_id = ANY(%s) AND r.status = 'approved'
                GROUP BY r.job_id
                """,
                (ids,),
            ).fetchall()
        }
        machine = {
            row[0]: (bool(row[1]), bool(row[2]))
            for row in self._connection.execute(
                """
                SELECT job_id,
                       bool_or(kind = 'started' AND COALESCE((payload->>'equipment_stopped')::boolean, false)),
                       bool_or(kind IN ('closed', 'cancelled') AND COALESCE((payload->>'equipment_restarted')::boolean, false))
                FROM maintenance.job_events
                WHERE job_id = ANY(%s)
                GROUP BY job_id
                """,
                (ids,),
            ).fetchall()
        }
        costs = (
            job_parts_costs(self._connection, tenant_id, [row[1] for row in jobs if parts.get(row[0], (0, 0))[0] > 0])
            if costs_visible
            else None
        )
        chefs = user_names(self._connection, tenant_id, [row[15] for row in jobs])
        names = employee_names(self._connection, tenant_id, [p for people in performers.values() for p in people])

        rows = []
        for (
            job_id, number, equipment_id, code, name, kind, priority, title, status, due_date, created_at,
            started_at, closed_at, cancelled_at, cancel_reason, chef_id, checks_total, checks_done,
        ) in jobs:
            issued, purchase = parts.get(job_id, (0, 0))
            ended_at = closed_at if status == "closed" else cancelled_at if status == "cancelled" else None
            rows.append(
                {
                    "job_id": job_id,
                    "number": number,
                    "equipment_id": equipment_id,
                    "equipment_code": code,
                    "equipment_name": name,
                    "kind": kind,
                    "priority": priority,
                    "title": title,
                    "status": status,
                    "date": _iso(ended_at),
                    "due_date": due_date.isoformat(),
                    "created_at": created_at.isoformat(),
                    "started_at": _iso(started_at),
                    "closed_on_time": closed_at.astimezone(UTC).date() <= due_date if closed_at is not None else None,
                    "cancel_reason": cancel_reason,
                    "chef_name": chefs.get(chef_id) if chef_id is not None else None,
                    "performers": sorted(
                        ({"employee_id": p, "name": names.get(p, p)} for p in performers[job_id]), key=lambda person: person["name"]
                    ),
                    "technician_seconds": seconds[job_id],
                    "checks_total": checks_total,
                    "checks_done": checks_done,
                    "outcomes": outcome_counts(outcomes[job_id], checks_total),
                    "parts": {"issued_lines": issued, "purchase_lines": purchase},
                    "parts_cost": None if costs is None else costs.get(number, (0.0, 0.0))[0],
                    "machine_stopped": machine.get(job_id, (False, False))[0],
                    "machine_restarted": machine.get(job_id, (False, False))[1],
                }
            )
        return rows
