# Maintenance History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every machine a read-only history — a logbook page, a per-checkpoint history panel, a global journal with Excel export, a printable PDF sheet, and production-vs-maintenance breakdown indicators side by side.

**Architecture:** A read-only `HistoryService` in the maintenance module assembles everything at read time: maintenance's own tables, status changes from `core.audit_log` (shared kernel), production's stops and running minutes through production's `api/` services (behind a small injectable reader so tests need no validated shifts), and FIFO part costs through warehouse's `ValuationService`. Pure rules (status intervals, formulas) live in `domain/history.py`. The React side adds a "Historique" tab, a logbook route, a side sheet, a print route, seven icons and three illustrations.

**Tech Stack:** FastAPI + psycopg raw SQL, openpyxl, pytest (`db` fixture); React 18 + TS, TanStack Query v5, Tailwind, Radix Dialog, framer-motion, Recharts, vitest.

**Spec:** `docs/superpowers/specs/2026-10-02-maintenance-history-design.md` (read it first; this plan argues from it).

## Global Constraints

- Read-only feature: no new maintenance table, no event, no new permission. The only schema change is the core index (Task 1).
- Every history endpoint requires `maintenance.view_jobs`. Part costs are returned only when the user holds `warehouse.view_valuation` (`costs_visible`); otherwise `parts_cost` / `parts_unvalued_quantity` are `null`.
- Modules never read another module's tables: production through `StopsAnalyticsService` / `MachinePerformanceService`, warehouse through `ValuationService`. `core.audit_log` and `core.users` are shared kernel and may be read directly.
- No invented thresholds: a figure that cannot be computed is `null` and shows "—"; never infinity, never a guess.
- "Panne" = production stop with `downtime_type = 'corrective'` on one side; corrective maintenance job (not cancelled) on the other. Never merged.
- Dates are UTC (Mali time). A period `[from, to]` is `from 00:00Z` to `to + 1 day 00:00Z`, capped at now.
- Router errors: `HTTPException(status, err_detail(Err(code, message, message_fr)))`.
- Currency: XOF via `formatXof` (`frontend/src/lib/currency.ts`); never `Intl` `style: "currency"`, never "F CFA".
- Every UI string in both `frontend/src/lib/i18n.en.ts` and `frontend/src/lib/i18n.fr.ts` (French is the plant language).
- Palette only: Tailwind tokens (`primary` navy, `accent` gold, `success`, `destructive`, `border`), plus the brand navy hexes `#071F43` / `#082B57` / `#1A4A85` for the photo tile's radial gradient (as on the login page) and `#123B6D` / `#F5A900` / `#E5484D` inside the Recharts chart (Recharts takes literal colours). Gold is the one highlight; motion only where it explains a state; `prefers-reduced-motion` respected.
- One branded loader (`AppLoader`) per screen on first load; `Skeleton` afterwards.
- Every screen works at 390 px wide.
- Never `git stash` (shared worktree). Verify the browser with a private headless Chrome, not the shared Playwright session.
- Commands run from `backend/` with `.venv/Scripts/python`; frontend from `frontend/`.

## Review Focus

1. A machine whose status never changed, or whose only change happened after the period started — the start status must come from the rule (last change before; else first change's `from_status`; else current status), never default to "operational". Pinned in Task 4.
2. Zero breakdowns in the period — MTBF/MTTR/calendar MTBF must be `null` ("—"), not a division error or infinity. Pinned in Task 4.
3. A user without `warehouse.view_valuation` — costs must be `null` in JSON and absent from the Excel file, not 0. Pinned in Tasks 6 and 9.
4. A reversed or future period (`from > to`, or `from` after today) — `from > to` is refused with `INVALID_PERIOD` (422); a future period yields zero-length figures, not negative minutes. Pinned in Tasks 4 and 9.
5. A rejected-then-redone point — the journal outcome counts use the latest attempt and the time sums every attempt's latest entry; the point history keeps the rejected attempt with its reason. Pinned in Tasks 6 and 8.

---

### Task 1: Core index on the audit log

**Files:**
- Create: `backend/core/migrations/0029_core_audit_log_entity_index.sql`
- Test: `backend/core/test_audit_log_index_integration.py`

**Interfaces:**
- Produces: index `core_audit_log_entity_idx` on `core.audit_log (tenant_id, entity_type, entity_id, occurred_at)`, used by Task 5's status-change query.

- [ ] **Step 1: Write the failing test**

```python
"""The audit log can be read one entity at a time without scanning it all."""
from __future__ import annotations


def test_audit_log_has_the_per_entity_index(db):
    row = db.execute(
        "SELECT indexdef FROM pg_indexes WHERE schemaname = 'core' AND indexname = 'core_audit_log_entity_idx'"
    ).fetchone()
    assert row is not None
    assert "(tenant_id, entity_type, entity_id, occurred_at)" in row[0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest core/test_audit_log_index_integration.py -q`
Expected: FAIL (`assert None is not None`). If it SKIPS, the DB is unreachable — start Postgres first; a skip is not a pass.

- [ ] **Step 3: Write the migration**

```sql
-- One entity's trail (GET /core/audit-log?entity_type=&entity_id=, and maintenance's
-- machine history rebuilding a machine's status changes) used to scan the whole log.
-- Schema only.
CREATE INDEX IF NOT EXISTS core_audit_log_entity_idx
    ON core.audit_log (tenant_id, entity_type, entity_id, occurred_at);
```

- [ ] **Step 4: Apply and run the tests**

Run: `.venv/Scripts/python -c "from core.migrations.runner import apply_all_migrations; apply_all_migrations()"`
Then: `.venv/Scripts/python -m pytest core/test_audit_log_index_integration.py core/migrations/test_migration_data_guard.py -q`
Expected: PASS (both).

- [ ] **Step 5: Commit**

```bash
git add backend/core/migrations/0029_core_audit_log_entity_index.sql backend/core/test_audit_log_index_integration.py
git commit -m "feat(core): index the audit log by entity for per-machine history reads"
```

---

### Task 2: Production stops — machine filter, note and corrective action

**Files:**
- Modify: `backend/modules/production/api/stops_analytics_service.py`
- Test: `backend/modules/production/api/test_stops_analytics_integration.py` (append)

**Interfaces:**
- Produces: `StopsAnalyticsService(conn).list_stops(*, tenant_id: str, date_from: str | None = None, date_to: str | None = None, equipment_id: str | None = None) -> list[dict]`; each row now also has `shift_report_id: str`, `note: str | None`, `corrective_action: str | None` (all existing keys unchanged). Consumed by Task 5 (`ProductionServices.stops`).

- [ ] **Step 1: Write the failing test** (append to the test file; it already imports `ULID`, `StopsAnalyticsService` and defines `env`, `_shift_with_stop`, `_stops`, `TENANT`)

```python
def test_filters_by_machine_and_returns_the_shift_note_and_corrective_action(db, env):
    shift_id = _shift_with_stop(db, env, equipment_id=env["equipment"], classification="mechanical")
    db.execute(
        "UPDATE production.machine_stops SET note = 'filière démontée', corrective_action = 'nettoyage filière' "
        "WHERE shift_report_id = %s",
        (shift_id,),
    )
    db.execute(
        "INSERT INTO production.machine_stops (id, tenant_id, shift_report_id, equipment_id, started_at, ended_at, downtime_type) "
        "VALUES (%s, %s, %s, %s, '2030-07-01T10:00:00Z', '2030-07-01T10:10:00Z', 'corrective')",
        (str(ULID()), TENANT, shift_id, str(ULID())),
    )

    assert len(_stops(db)) == 2
    [row] = StopsAnalyticsService(db).list_stops(
        tenant_id=TENANT, date_from="2030-07-01", date_to="2030-07-01", equipment_id=env["equipment"]
    )
    assert (row["note"], row["corrective_action"], row["shift_report_id"]) == (
        "filière démontée", "nettoyage filière", shift_id,
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest modules/production/api/test_stops_analytics_integration.py -q`
Expected: the new test FAILS with `TypeError: ... unexpected keyword argument 'equipment_id'`.

- [ ] **Step 3: Implement**

In `list_stops`, add the parameter and filter, and select/return the three new fields:

```python
    def list_stops(
        self,
        *,
        tenant_id: str,
        date_from: str | None = None,
        date_to: str | None = None,
        equipment_id: str | None = None,
    ) -> list[dict]:
        clauses = ["s.tenant_id = %s", "s.status = 'validated'", "ms.ended_at IS NOT NULL"]
        params: list[object] = [tenant_id]
        if date_from is not None:
            clauses.append("s.report_date >= %s")
            params.append(date_from)
        if date_to is not None:
            clauses.append("s.report_date <= %s")
            params.append(date_to)
        # One machine's stops (its maintenance logbook); left out, every stop, attributed or not.
        if equipment_id is not None:
            clauses.append("ms.equipment_id = %s")
            params.append(equipment_id)
        where = " AND ".join(clauses)

        rows = self._connection.execute(
            f"""
            SELECT
                ms.equipment_id, s.work_center_id, s.team, s.report_date,
                ms.started_at, ms.ended_at,
                ROUND(EXTRACT(EPOCH FROM (ms.ended_at - ms.started_at)) / 60) AS minutes,
                ms.downtime_type, ms.classification, ms.motif, ms.source,
                ms.shift_report_id, ms.note, ms.corrective_action
            FROM production.machine_stops ms
            JOIN production.shift_reports s ON s.id = ms.shift_report_id AND s.tenant_id = ms.tenant_id
            WHERE {where}
            ORDER BY ms.started_at
            """,
            params,
        ).fetchall()
        return [
            {
                "equipment_id": equipment_id,
                "work_center_id": work_center_id,
                "team": team,
                "report_date": report_date.isoformat(),
                "started_at": started_at.isoformat(),
                "ended_at": ended_at.isoformat(),
                "minutes": int(minutes),
                "downtime_type": downtime_type,
                "classification": classification,
                "motif": motif,
                "source": source,
                "shift_report_id": shift_report_id,
                "note": note,
                "corrective_action": corrective_action,
            }
            for (
                equipment_id, work_center_id, team, report_date, started_at, ended_at,
                minutes, downtime_type, classification, motif, source,
                shift_report_id, note, corrective_action,
            ) in rows
        ]
```

Note the loop variable `equipment_id` shadows the parameter only inside the comprehension — the filter has already been applied above, so this is safe.

- [ ] **Step 4: Run the tests**

Run: `.venv/Scripts/python -m pytest modules/production/api/test_stops_analytics_integration.py -q`
Expected: PASS (all, including the existing ones).

- [ ] **Step 5: Commit**

```bash
git add backend/modules/production/api/stops_analytics_service.py backend/modules/production/api/test_stops_analytics_integration.py
git commit -m "feat(production): stops analytics filter one machine and carry the note and corrective action"
```

---

### Task 3: Warehouse — cost of several references in one query

**Files:**
- Modify: `backend/modules/warehouse/api/valuation_service.py` (add a method after `cost_of_reference`)
- Test: `backend/modules/warehouse/api/test_valuation_service_integration.py` (append)

**Interfaces:**
- Produces: `ValuationService(conn).costs_of_references(*, tenant_id: str, references: list[str]) -> dict[str, dict]` — every requested reference is a key; value `{"reference", "quantity": float, "cost": float, "unvalued_quantity": float, "currency": "XOF"}`. Consumed by Task 5 (`job_parts_costs`).

- [ ] **Step 1: Write the failing test** (append; the file defines `env`, `_receive`, `TENANT`)

```python
def test_costs_of_references_answers_every_reference_in_one_call(db, env):
    _receive(db, env, 10, unit_cost=100)
    stock = StockService(db)
    for reference, quantity in (("maintenance:MT-1", 3), ("maintenance:MT-2", 2)):
        issued = stock.issue_stock(
            tenant_id=TENANT, product_id=env["product"], location_id=env["a"], quantity=quantity,
            reference=reference, actor_id=env["actor"], move_type="maintenance",
        )
        assert isinstance(issued, Ok)

    costs = ValuationService(db).costs_of_references(
        tenant_id=TENANT, references=["maintenance:MT-1", "maintenance:MT-2", "maintenance:MT-3"]
    )

    assert {ref: (c["quantity"], c["cost"], c["unvalued_quantity"]) for ref, c in costs.items()} == {
        "maintenance:MT-1": (3, 300, 0),
        "maintenance:MT-2": (2, 200, 0),
        "maintenance:MT-3": (0, 0, 0),
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest modules/warehouse/api/test_valuation_service_integration.py -q`
Expected: FAIL with `AttributeError: ... has no attribute 'costs_of_references'`.

- [ ] **Step 3: Implement** (right after `cost_of_reference`)

```python
    def costs_of_references(self, *, tenant_id: str, references: list[str]) -> dict[str, dict]:
        """`cost_of_reference` for several references in one query. Every reference asked
        for is in the result; one nothing left under has quantity and cost 0."""
        rows = self._connection.execute(
            """
            SELECT reference, layer_id, quantity, unit_cost FROM warehouse.cost_layer_consumptions
            WHERE tenant_id = %s AND reference = ANY(%s)
            """,
            (tenant_id, list(references)),
        ).fetchall()
        allocations: dict[str, list[Allocation]] = {reference: [] for reference in references}
        for reference, layer_id, quantity, unit_cost in rows:
            allocations[reference].append(
                Allocation(layer_id=layer_id, quantity=float(quantity), unit_cost=float(unit_cost) if unit_cost is not None else None)
            )
        result: dict[str, dict] = {}
        for reference, items in allocations.items():
            cost, unvalued = allocation_cost(items)
            result[reference] = {
                "reference": reference,
                "quantity": sum(a.quantity for a in items),
                "cost": cost,
                "unvalued_quantity": unvalued,
                "currency": "XOF",
            }
        return result
```

- [ ] **Step 4: Run the tests**

Run: `.venv/Scripts/python -m pytest modules/warehouse/api/test_valuation_service_integration.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/warehouse/api/valuation_service.py backend/modules/warehouse/api/test_valuation_service_integration.py
git commit -m "feat(warehouse): cost of several stock-out references in one query"
```

---

### Task 4: Maintenance history domain rules

**Files:**
- Create: `backend/modules/maintenance/domain/history.py`
- Test: `backend/modules/maintenance/domain/test_history.py`

**Interfaces:**
- Produces (all pure):
  - `StatusChange(at: datetime, from_status: str, to_status: str)` (frozen dataclass)
  - `Immobilisation(minutes: float, episodes: int)` (frozen dataclass)
  - `STOPPED_STATUSES = frozenset({"down", "maintenance"})`, `CORRECTIVE_STOP_TYPE = "corrective"`
  - `JOB_KINDS = ("preventive", "corrective")`, `JOURNAL_STATUSES = ("closed", "cancelled", "all")`
  - `validate_period(date_from: date, date_to: date) -> Err | None` (code `INVALID_PERIOD`)
  - `validate_journal_filters(kind: str | None, status: str) -> Err | None` (code `INVALID_FILTER`)
  - `period_bounds(date_from: date, date_to: date, now: datetime) -> tuple[datetime, datetime]`
  - `status_at_start(changes: list[StatusChange], start: datetime, current_status: str) -> str`
  - `immobilisation(changes: list[StatusChange], start: datetime, end: datetime, current_status: str) -> Immobilisation`
  - `ratio(numerator: float, denominator: int) -> float | None`
  - `production_block(stops: list[dict], running_minutes: int) -> dict`
  - `maintenance_block(*, breakdowns, due, closed, closed_on_time, overdue, stopped: Immobilisation, calendar_minutes: float, technician_seconds: int, issued_lines: int, purchase_lines: int, parts_cost: float | None, parts_unvalued_quantity: float | None, status_changes: int) -> dict`
  - `outcome_counts(latest_outcomes: list[str], checks_total: int) -> dict[str, int]`

- [ ] **Step 1: Write the failing tests**

```python
"""Pure rules of a machine's history: status intervals and the indicator formulas."""
from __future__ import annotations

import datetime

from core.domain.result import Err
from modules.maintenance.domain.history import (
    Immobilisation,
    StatusChange,
    immobilisation,
    maintenance_block,
    outcome_counts,
    period_bounds,
    production_block,
    status_at_start,
    validate_journal_filters,
    validate_period,
)

UTC = datetime.timezone.utc


def at(month: int, day: int, hour: int = 0) -> datetime.datetime:
    return datetime.datetime(2026, month, day, hour, tzinfo=UTC)


START, END = at(9, 1), at(9, 11)  # ten days = 14 400 minutes
DAY = 24 * 60


def change(when, from_status, to_status):
    return StatusChange(at=when, from_status=from_status, to_status=to_status)


def test_the_last_change_before_the_period_decides_the_start_status():
    changes = [change(at(8, 20), "operational", "down")]
    assert status_at_start(changes, START, "operational") == "down"
    assert immobilisation(changes, START, END, "operational") == Immobilisation(minutes=10 * DAY, episodes=1)


def test_without_an_earlier_change_the_first_change_tells_the_start_status():
    changes = [change(at(9, 5), "down", "operational")]
    assert status_at_start(changes, START, "operational") == "down"
    assert immobilisation(changes, START, END, "operational") == Immobilisation(minutes=4 * DAY, episodes=1)


def test_a_machine_that_never_changed_keeps_its_current_status():
    assert immobilisation([], START, END, "operational") == Immobilisation(minutes=0, episodes=0)
    assert immobilisation([], START, END, "maintenance") == Immobilisation(minutes=10 * DAY, episodes=1)


def test_down_then_maintenance_is_one_episode():
    changes = [
        change(at(9, 2), "operational", "down"),
        change(at(9, 3), "down", "maintenance"),
        change(at(9, 4), "maintenance", "operational"),
    ]
    assert immobilisation(changes, START, END, "operational") == Immobilisation(minutes=2 * DAY, episodes=1)


def test_two_stoppages_are_two_episodes_and_an_open_one_runs_to_the_end():
    changes = [
        change(at(9, 2), "operational", "down"),
        change(at(9, 3), "down", "operational"),
        change(at(9, 9), "operational", "maintenance"),
    ]
    assert immobilisation(changes, START, END, "maintenance") == Immobilisation(minutes=3 * DAY, episodes=2)


def test_period_bounds_stop_at_now_and_a_future_period_is_empty():
    now = at(9, 10, 12)
    assert period_bounds(datetime.date(2026, 9, 1), datetime.date(2026, 9, 30), now) == (at(9, 1), now)
    start, end = period_bounds(datetime.date(2026, 10, 1), datetime.date(2026, 10, 31), now)
    assert start == end == at(10, 1)


def test_a_reversed_period_and_unknown_filters_are_refused():
    refused = validate_period(datetime.date(2026, 9, 30), datetime.date(2026, 9, 1))
    assert isinstance(refused, Err) and refused.code == "INVALID_PERIOD" and refused.message_fr
    assert validate_period(datetime.date(2026, 9, 1), datetime.date(2026, 9, 1)) is None
    assert validate_journal_filters("preventive", "closed") is None
    assert validate_journal_filters(None, "all") is None
    assert validate_journal_filters("emergency", "closed").code == "INVALID_FILTER"
    assert validate_journal_filters(None, "open").code == "INVALID_FILTER"


def _stop(minutes, downtime_type, classification=None):
    return {"minutes": minutes, "downtime_type": downtime_type, "classification": classification}


def test_production_block_counts_only_corrective_stops_as_breakdowns():
    block = production_block(
        [_stop(30, "corrective", "mechanical"), _stop(20, "corrective", "electric"), _stop(15, "preventive"), _stop(10, None)],
        running_minutes=600,
    )
    assert (block["stops"], block["stop_minutes"], block["breakdowns"], block["breakdown_minutes"]) == (4, 75, 2, 50)
    assert (block["mtbf_minutes"], block["mttr_minutes"]) == (300, 25)
    assert block["breakdowns_by_system"] == [
        {"classification": "mechanical", "count": 1, "minutes": 30},
        {"classification": "electric", "count": 1, "minutes": 20},
    ]
    assert {"type": None, "count": 1, "minutes": 10} in block["stops_by_type"]


def test_without_a_breakdown_mtbf_and_mttr_are_unknown_not_infinite():
    block = production_block([_stop(15, "preventive")], running_minutes=600)
    assert (block["breakdowns"], block["mtbf_minutes"], block["mttr_minutes"]) == (0, None, None)


def _maintenance(**overrides):
    arguments = dict(
        breakdowns=2, due=4, closed=3, closed_on_time=2, overdue=1,
        stopped=Immobilisation(minutes=400, episodes=2), calendar_minutes=14_400, technician_seconds=3_600,
        issued_lines=1, purchase_lines=1, parts_cost=12_000.0, parts_unvalued_quantity=0.0, status_changes=4,
    )
    arguments.update(overrides)
    return maintenance_block(**arguments)


def test_maintenance_block_formulas():
    block = _maintenance()
    assert block["preventive"] == {"due": 4, "closed": 3, "closed_on_time": 2, "overdue": 1}
    assert (block["immobilised_minutes"], block["immobilisations"], block["mean_immobilisation_minutes"]) == (400, 2, 200)
    assert block["calendar_mtbf_minutes"] == (14_400 - 400) / 2
    assert block["parts"] == {"issued_lines": 1, "purchase_lines": 1}


def test_maintenance_block_without_breakdowns_or_stoppages():
    block = _maintenance(breakdowns=0, stopped=Immobilisation(minutes=0, episodes=0))
    assert (block["calendar_mtbf_minutes"], block["mean_immobilisation_minutes"]) == (None, None)


def test_outcome_counts_count_unrecorded_checks_as_pending():
    assert outcome_counts(["ok", "ok", "issue"], checks_total=5) == {"ok": 2, "issue": 1, "not_done": 0, "pending": 2}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest modules/maintenance/domain/test_history.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'modules.maintenance.domain.history'`.

- [ ] **Step 3: Implement `domain/history.py`**

```python
"""Pure rules behind a machine's history (spec 2026-10-02-maintenance-history-design.md):
status intervals rebuilt from status changes, and every indicator formula.

No database. A figure that cannot be computed is None -- never infinity, never a guess.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass

from core.domain.result import Err

UTC = datetime.timezone.utc

STOPPED_STATUSES = frozenset({"down", "maintenance"})
# The one production stop type that counts as a breakdown (a built-in code; admin-added types never do).
CORRECTIVE_STOP_TYPE = "corrective"
JOB_KINDS = ("preventive", "corrective")
JOURNAL_STATUSES = ("closed", "cancelled", "all")


@dataclass(frozen=True)
class StatusChange:
    at: datetime.datetime
    from_status: str
    to_status: str


@dataclass(frozen=True)
class Immobilisation:
    minutes: float
    episodes: int


def validate_period(date_from: datetime.date, date_to: datetime.date) -> Err | None:
    if date_from > date_to:
        return Err(
            "INVALID_PERIOD",
            f"the period starts ({date_from}) after it ends ({date_to})",
            f"la période commence ({date_from}) après sa fin ({date_to})",
        )
    return None


def validate_journal_filters(kind: str | None, status: str) -> Err | None:
    if kind is not None and kind not in JOB_KINDS:
        return Err("INVALID_FILTER", f"unknown job kind: {kind}", f"type d'intervention inconnu : {kind}")
    if status not in JOURNAL_STATUSES:
        return Err("INVALID_FILTER", f"unknown journal status: {status}", f"statut de journal inconnu : {status}")
    return None


def period_bounds(
    date_from: datetime.date, date_to: datetime.date, now: datetime.datetime
) -> tuple[datetime.datetime, datetime.datetime]:
    """`from 00:00Z` to `to + 1 day 00:00Z`, capped at now; a period still to come is empty."""
    start = datetime.datetime.combine(date_from, datetime.time.min, tzinfo=UTC)
    end = datetime.datetime.combine(date_to + datetime.timedelta(days=1), datetime.time.min, tzinfo=UTC)
    end = min(end, now)
    return start, max(start, end)


def status_at_start(changes: list[StatusChange], start: datetime.datetime, current_status: str) -> str:
    """`changes` oldest first. The last change before the period; else the first change's
    starting status; else the machine never changed and is still in its current status."""
    before = [c for c in changes if c.at < start]
    if before:
        return before[-1].to_status
    if changes:
        return changes[0].from_status
    return current_status


def immobilisation(
    changes: list[StatusChange], start: datetime.datetime, end: datetime.datetime, current_status: str
) -> Immobilisation:
    """Minutes in `down` or `maintenance` within [start, end), and the stretches of it
    (an episode runs from leaving `operational` to coming back; down -> maintenance is one)."""
    stopped_since = start if status_at_start(changes, start, current_status) in STOPPED_STATUSES else None
    episodes = 1 if stopped_since is not None else 0
    minutes = 0.0
    for change in changes:
        if not (start <= change.at < end):
            continue
        now_stopped = change.to_status in STOPPED_STATUSES
        if stopped_since is not None and not now_stopped:
            minutes += (change.at - stopped_since).total_seconds() / 60
            stopped_since = None
        elif stopped_since is None and now_stopped:
            stopped_since = change.at
            episodes += 1
    if stopped_since is not None:
        minutes += (end - stopped_since).total_seconds() / 60
    return Immobilisation(minutes=minutes, episodes=episodes)


def ratio(numerator: float, denominator: int) -> float | None:
    return numerator / denominator if denominator > 0 else None


def _grouped(stops: list[dict], field: str, name: str) -> list[dict]:
    groups: dict[str | None, tuple[int, int]] = {}
    for stop in stops:
        count, minutes = groups.get(stop[field], (0, 0))
        groups[stop[field]] = (count + 1, minutes + stop["minutes"])
    rows = [{name: key, "count": count, "minutes": minutes} for key, (count, minutes) in groups.items()]
    return sorted(rows, key=lambda row: (-row["minutes"], str(row[name])))


def production_block(stops: list[dict], running_minutes: int) -> dict:
    """One machine's production figures from its stops (`minutes`, `downtime_type`,
    `classification`) and its running minutes, both for validated shifts of the period."""
    breakdowns = [stop for stop in stops if stop["downtime_type"] == CORRECTIVE_STOP_TYPE]
    breakdown_minutes = sum(stop["minutes"] for stop in breakdowns)
    return {
        "stops": len(stops),
        "stop_minutes": sum(stop["minutes"] for stop in stops),
        "stops_by_type": _grouped(stops, "downtime_type", "type"),
        "breakdowns": len(breakdowns),
        "breakdown_minutes": breakdown_minutes,
        "breakdowns_by_system": _grouped(breakdowns, "classification", "classification"),
        "running_minutes": running_minutes,
        "mtbf_minutes": ratio(running_minutes, len(breakdowns)),
        "mttr_minutes": ratio(breakdown_minutes, len(breakdowns)),
    }


def maintenance_block(
    *,
    breakdowns: int,
    due: int,
    closed: int,
    closed_on_time: int,
    overdue: int,
    stopped: Immobilisation,
    calendar_minutes: float,
    technician_seconds: int,
    issued_lines: int,
    purchase_lines: int,
    parts_cost: float | None,
    parts_unvalued_quantity: float | None,
    status_changes: int,
) -> dict:
    return {
        "breakdowns": breakdowns,
        "preventive": {"due": due, "closed": closed, "closed_on_time": closed_on_time, "overdue": overdue},
        "immobilised_minutes": stopped.minutes,
        "immobilisations": stopped.episodes,
        "mean_immobilisation_minutes": ratio(stopped.minutes, stopped.episodes),
        "calendar_minutes": calendar_minutes,
        # "calendaire": maintenance records no running time, so the period's clock stands in.
        "calendar_mtbf_minutes": ratio(max(calendar_minutes - stopped.minutes, 0.0), breakdowns),
        "technician_seconds": technician_seconds,
        "parts": {"issued_lines": issued_lines, "purchase_lines": purchase_lines},
        "parts_cost": parts_cost,
        "parts_unvalued_quantity": parts_unvalued_quantity,
        "status_changes": status_changes,
    }


def outcome_counts(latest_outcomes: list[str], checks_total: int) -> dict[str, int]:
    """The latest outcome of each recorded check; a check with no entry yet is pending."""
    return {
        "ok": latest_outcomes.count("ok"),
        "issue": latest_outcomes.count("issue"),
        "not_done": latest_outcomes.count("not_done"),
        "pending": max(checks_total - len(latest_outcomes), 0),
    }
```

- [ ] **Step 4: Run the tests**

Run: `.venv/Scripts/python -m pytest modules/maintenance/domain/test_history.py -q`
Expected: PASS (12 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/modules/maintenance/domain/history.py backend/modules/maintenance/domain/test_history.py
git commit -m "feat(maintenance): history rules -- status intervals and breakdown formulas"
```

---

### Task 5: History sources and the indicators read

**Files:**
- Create: `backend/modules/maintenance/api/history_sources.py`
- Create: `backend/modules/maintenance/api/history_service.py`
- Create: `backend/modules/maintenance/api/test_history_integration.py`
- Modify: `backend/modules/maintenance/module.json` (`optional_depends` gets `"production"`, version `0.3.0`)

**Interfaces:**
- Consumes: Task 2 `list_stops(..., equipment_id=)`, Task 3 `costs_of_references`, Task 4 domain functions.
- Produces:
  - `ProductionReadings` protocol with `stops(*, tenant_id, date_from: date, date_to: date, equipment_id: str | None = None) -> list[dict]` and `running_minutes(*, tenant_id, date_from: date, date_to: date) -> dict[str, int]`
  - `production_readings(connection) -> ProductionReadings | None`
  - `job_parts_costs(connection, tenant_id: str, job_numbers: list[str]) -> dict[str, tuple[float, float]] | None`
  - `HistoryService(connection, *, production: ProductionReadings | None, now: datetime | None = None)` with `indicators(*, tenant_id, date_from: date, date_to: date, costs_visible: bool, equipment_id: str | None = None) -> Result[dict]` (shape in the spec, plus `photo_version` and `maintenance.status_changes`).
  - test helpers in `test_history_integration.py` reused by Tasks 6–8: `T`, `_user`, `_employee`, `_machine`, `_view_with_points`, `ctx`, `_entry`, `_job`, `_set_audit_times`, `FakeProduction`, `NOW`, `PERIOD`.

- [ ] **Step 1: Write the failing tests** (new file)

```python
"""Integration tests for a machine's history, against a real database.

Production's figures come from a fake reader: building validated shifts is production's
own concern (its stops analytics tests cover "validated shifts only"); here we check what
maintenance does with them.
"""
from __future__ import annotations

import datetime
from types import SimpleNamespace

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from modules.hr.api.employee_service import EmployeeService
from modules.hr.domain.employee import EmployeeFile
from modules.maintenance.api.equipment_service import EquipmentService
from modules.maintenance.api.history_service import HistoryService
from modules.maintenance.api.job_service import JobService
from modules.maintenance.api.map_service import MapService

T = "integration-test-history"
UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 10, 2, 12, tzinfo=UTC)
PERIOD = (datetime.date(2026, 9, 1), datetime.date(2026, 9, 30))
SEPT = 30 * 24 * 60
JPEG_BYTES = b"\xff\xd8\xff" + b"0" * 50


def _user(db, full_name, *, permissions=()):
    user_id = str(ULID())
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash, full_name) VALUES (%s, %s, %s, 'x', %s)",
        (user_id, T, f"{user_id}@test.local", full_name),
    )
    for permission in permissions:
        db.execute("INSERT INTO core.user_permissions (user_id, permission) VALUES (%s, %s)", (user_id, permission))
    return user_id


def _employee(db, first_name, last_name):
    created = EmployeeService(db).create_employee(
        tenant_id=T,
        actor_id=str(ULID()),
        employee=EmployeeFile(employee_no=f"E-{ULID()}", first_name=first_name, last_name=last_name, hire_date=datetime.date(2024, 1, 1)),
    )
    assert isinstance(created, Ok), created
    return created.value["id"]


def _machine(db, actor, code="EXT-L1"):
    created = EquipmentService(db).create_equipment(
        tenant_id=T, actor_id=actor, work_center_id="wc-1", code=code, name=f"Machine {code}"
    )
    assert isinstance(created, Ok), created
    return created.value.id


def _view_with_points(db, actor, machine, points):
    maps = MapService(db)
    view = maps.create_view(tenant_id=T, actor_id=actor, equipment_id=machine, label="Face", image=JPEG_BYTES, mime="image/jpeg").value
    ids = []
    for index, (label, action, extra) in enumerate(points):
        point = maps.add_checkpoint(
            tenant_id=T, actor_id=actor, view_id=view["id"], x_pct=10 + index, y_pct=20, label=label, action=action, **extra
        ).value
        maps.update_checkpoint(tenant_id=T, actor_id=actor, checkpoint_id=point["id"], sort_order=index + 1)
        ids.append(point["id"])
    return view["id"], ids


@pytest.fixture
def ctx(db):
    sup = _user(db, "Sara Superviseur", permissions=("maintenance.plan_jobs",))
    chef = _user(db, "Chef Keita", permissions=("maintenance.execute_jobs",))
    machine = _machine(db, sup)
    view, points = _view_with_points(
        db, sup, machine,
        [("Roulement", "lubricate", {}), ("Température palier", "measure", {"measure_unit": "°C"}), ("Courroie", "inspect", {})],
    )
    employees = [_employee(db, "Awa", "Diarra"), _employee(db, "Moussa", "Traoré")]
    return SimpleNamespace(sup=sup, chef=chef, machine=machine, view=view, points=points, employees=employees)


def _job(db, ctx, **overrides) -> str:
    arguments = dict(
        tenant_id=T, actor_id=ctx.sup, equipment_id=ctx.machine, title="Graissage", description=None,
        kind="corrective", priority="normal", due_date=datetime.date(2026, 9, 10), stops_machine=False,
        checkpoint_ids=[ctx.points[0]], tasks=[], chef_user_id=ctx.chef,
    )
    arguments.update(overrides)
    created = JobService(db).create_job(**arguments)
    assert isinstance(created, Ok), created
    return created.value


def _entry(db, ctx, job_id, check_id, **overrides):
    now = datetime.datetime.now(UTC)
    arguments = dict(
        tenant_id=T, actor_id=ctx.chef, job_id=job_id, check_id=check_id, performer_employee_id=ctx.employees[0],
        outcome="ok", note=None, measured_value=None, started_at=now - datetime.timedelta(minutes=5), finished_at=now,
        manual_minutes=None, photo=None, actor_can_plan=False, now=now,
    )
    arguments.update(overrides)
    recorded = JobService(db).record_entry(**arguments)
    assert isinstance(recorded, Ok), recorded


def _checks(db, job_id) -> list[str]:
    return [row[0] for row in db.execute(
        "SELECT id FROM maintenance.job_checks WHERE job_id = %s ORDER BY sort_order, id", (job_id,)
    ).fetchall()]


def _close(db, ctx, job_id, outcomes):
    """Records one entry per check with the given outcomes, submits, accepts all, closes."""
    jobs = JobService(db)
    checks = _checks(db, job_id)
    for check_id, outcome in zip(checks, outcomes):
        _entry(db, ctx, job_id, check_id, outcome=outcome)
    assert isinstance(jobs.submit(tenant_id=T, actor_id=ctx.chef, job_id=job_id, actor_can_plan=False), Ok)
    assert isinstance(jobs.review(tenant_id=T, actor_id=ctx.sup, job_id=job_id, verdicts=[(c, "accepted", None) for c in checks]), Ok)
    assert isinstance(jobs.close(tenant_id=T, actor_id=ctx.sup, job_id=job_id), Ok)


def _set_job_times(db, job_id, **columns):
    """Moves a job's timestamps into the test period: the service writes NOW()."""
    for column, value in columns.items():
        db.execute(f"UPDATE maintenance.jobs SET {column} = %s WHERE id = %s", (value, job_id))


def _set_audit_times(db, machine, times):
    """Every status change in one test transaction has the same NOW(); spread them out in order."""
    rows = db.execute(
        "SELECT id FROM core.audit_log WHERE entity_id = %s AND action = 'equipment.status_changed' ORDER BY occurred_at, id",
        (machine,),
    ).fetchall()
    assert len(rows) == len(times)
    for (audit_id,), when in zip(rows, times):
        db.execute("UPDATE core.audit_log SET occurred_at = %s WHERE id = %s", (when, audit_id))


class FakeProduction:
    def __init__(self, stops=(), running=None):
        self._stops = list(stops)
        self._running = running or {}

    def stops(self, *, tenant_id, date_from, date_to, equipment_id=None):
        return [s for s in self._stops if equipment_id is None or s["equipment_id"] == equipment_id]

    def running_minutes(self, *, tenant_id, date_from, date_to):
        return dict(self._running)


def _stop(equipment_id, minutes, downtime_type="corrective", classification="mechanical", started_at="2026-09-12T08:00:00+00:00"):
    return {
        "equipment_id": equipment_id, "work_center_id": "wc-1", "team": "B", "report_date": started_at[:10],
        "started_at": started_at, "ended_at": started_at, "minutes": minutes, "downtime_type": downtime_type,
        "classification": classification, "motif": "die_jam", "source": "manual", "shift_report_id": "shift-1",
        "note": "filière démontée", "corrective_action": None,
    }


def _service(db, production=None):
    return HistoryService(db, production=production, now=NOW)


def _indicators(db, production=None, **overrides):
    arguments = dict(tenant_id=T, date_from=PERIOD[0], date_to=PERIOD[1], costs_visible=True)
    arguments.update(overrides)
    result = _service(db, production).indicators(**arguments)
    assert isinstance(result, Ok), result
    return result.value


def _row(indicators, machine):
    [row] = [m for m in indicators["machines"] if m["equipment_id"] == machine]
    return row


def test_immobilisation_comes_from_the_status_changes(db, ctx):
    equipment = EquipmentService(db)
    for status in ("down", "maintenance", "operational"):
        assert isinstance(equipment.transition_status(tenant_id=T, actor_id=ctx.sup, equipment_id=ctx.machine, new_status=status), Ok)
    _set_audit_times(db, ctx.machine, [
        datetime.datetime(2026, 9, 2, 8, tzinfo=UTC),
        datetime.datetime(2026, 9, 2, 9, tzinfo=UTC),
        datetime.datetime(2026, 9, 2, 10, tzinfo=UTC),
    ])
    job_id = _job(db, ctx)
    _set_job_times(db, job_id, created_at=datetime.datetime(2026, 9, 2, 8, tzinfo=UTC))

    block = _row(_indicators(db), ctx.machine)["maintenance"]

    assert (block["immobilised_minutes"], block["immobilisations"], block["mean_immobilisation_minutes"]) == (120, 1, 120)
    assert block["breakdowns"] == 1
    assert block["calendar_minutes"] == SEPT
    assert block["calendar_mtbf_minutes"] == SEPT - 120
    assert block["status_changes"] == 3


def test_preventive_due_closed_on_time_and_overdue(db, ctx):
    rows = [
        # (due, status, closed_at)
        (datetime.date(2026, 9, 5), "closed", datetime.datetime(2026, 9, 5, 15, tzinfo=UTC)),   # on time
        (datetime.date(2026, 9, 6), "closed", datetime.datetime(2026, 9, 8, 9, tzinfo=UTC)),    # late
        (datetime.date(2026, 9, 20), "assigned", None),                                          # overdue (now is Oct 2)
        (datetime.date(2026, 9, 21), "cancelled", None),                                         # not counted
        (datetime.date(2026, 10, 20), "assigned", None),                                         # outside the period
    ]
    for due, status, closed_at in rows:
        job_id = _job(db, ctx)
        db.execute(
            "UPDATE maintenance.jobs SET kind = 'preventive', due_date = %s, status = %s, closed_at = %s WHERE id = %s",
            (due, status, closed_at, job_id),
        )

    block = _row(_indicators(db), ctx.machine)["maintenance"]

    assert block["preventive"] == {"due": 3, "closed": 2, "closed_on_time": 1, "overdue": 1}
    assert block["breakdowns"] == 0 and block["calendar_mtbf_minutes"] is None


def test_production_block_comes_from_the_production_reader(db, ctx):
    production = FakeProduction(
        stops=[_stop(ctx.machine, 30), _stop(ctx.machine, 20, classification="electric"),
               _stop(ctx.machine, 15, downtime_type="preventive"), _stop(None, 10)],
        running={ctx.machine: 600},
    )

    indicators = _indicators(db, production)
    block = _row(indicators, ctx.machine)["production"]

    assert (block["breakdowns"], block["breakdown_minutes"], block["mttr_minutes"], block["mtbf_minutes"]) == (2, 50, 25, 300)
    assert block["stops"] == 3
    assert indicators["unattributed_stops"] == {"count": 1, "minutes": 10}
    assert indicators["production_available"] is True


def test_without_production_the_block_is_unavailable(db, ctx):
    indicators = _indicators(db, production=None)
    assert indicators["production_available"] is False
    assert _row(indicators, ctx.machine)["production"] is None
    assert indicators["unattributed_stops"] is None


def test_a_machine_with_no_production_figure_gets_an_empty_block(db, ctx):
    block = _row(_indicators(db, FakeProduction()), ctx.machine)["production"]
    assert (block["stops"], block["breakdowns"], block["mtbf_minutes"]) == (0, 0, None)


def test_an_archived_machine_is_listed_only_with_activity(db, ctx):
    idle = _machine(db, ctx.sup, code="OLD-1")
    busy = _machine(db, ctx.sup, code="OLD-2")
    job_id = JobService(db).create_job(
        tenant_id=T, actor_id=ctx.sup, equipment_id=busy, title="Panne", description=None, kind="corrective",
        priority="urgent", due_date=datetime.date(2026, 9, 3), stops_machine=False, checkpoint_ids=[],
        tasks=[{"label": "Réparer", "action": "replace"}], chef_user_id=ctx.chef,
    ).value
    _set_job_times(db, job_id, created_at=datetime.datetime(2026, 9, 3, tzinfo=UTC))
    for machine in (idle, busy):
        assert isinstance(EquipmentService(db).archive_equipment(tenant_id=T, actor_id=ctx.sup, equipment_id=machine), Ok)

    listed = {m["equipment_id"] for m in _indicators(db)["machines"]}

    assert busy in listed and idle not in listed and ctx.machine in listed


def test_the_photo_is_the_first_view_with_an_image(db, ctx):
    row = _row(_indicators(db), ctx.machine)
    assert row["photo_view_id"] == ctx.view and row["photo_version"] is not None


def test_a_reversed_period_and_an_unknown_machine_are_refused(db, ctx):
    service = _service(db)
    reversed_period = service.indicators(tenant_id=T, date_from=PERIOD[1], date_to=PERIOD[0], costs_visible=True)
    assert isinstance(reversed_period, Err) and reversed_period.code == "INVALID_PERIOD"
    unknown = service.indicators(tenant_id=T, date_from=PERIOD[0], date_to=PERIOD[1], costs_visible=True, equipment_id="nope")
    assert isinstance(unknown, Err) and unknown.code == "NOT_FOUND"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest modules/maintenance/api/test_history_integration.py -q`
Expected: FAIL with `ModuleNotFoundError: ... history_service`.

- [ ] **Step 3: Write `history_sources.py`**

```python
"""What a machine's history reads from other modules -- only through their api/ services.

Production (stops of validated shifts, running minutes) and warehouse (FIFO cost of the
parts issued to a job) are optional dependencies of maintenance: when one is not
installed its reader is None and the history says "non disponible" instead of failing.
The production reader is a protocol so HistoryService can be tested with a fake one.
"""
from __future__ import annotations

import datetime
from typing import Protocol

import psycopg


class ProductionReadings(Protocol):
    def stops(
        self, *, tenant_id: str, date_from: datetime.date, date_to: datetime.date, equipment_id: str | None = None
    ) -> list[dict]: ...

    def running_minutes(self, *, tenant_id: str, date_from: datetime.date, date_to: datetime.date) -> dict[str, int]: ...


class ProductionServices:
    """`ProductionReadings` over production's own services (validated shifts only)."""

    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def stops(
        self, *, tenant_id: str, date_from: datetime.date, date_to: datetime.date, equipment_id: str | None = None
    ) -> list[dict]:
        from modules.production.api.stops_analytics_service import StopsAnalyticsService

        return StopsAnalyticsService(self._connection).list_stops(
            tenant_id=tenant_id, date_from=date_from.isoformat(), date_to=date_to.isoformat(), equipment_id=equipment_id
        )

    def running_minutes(self, *, tenant_id: str, date_from: datetime.date, date_to: datetime.date) -> dict[str, int]:
        from modules.production.api.machine_performance_service import MachinePerformanceService

        rows = MachinePerformanceService(self._connection).list_machine_performance(
            tenant_id=tenant_id, grain="year", date_from=date_from.isoformat(), date_to=date_to.isoformat()
        )
        minutes: dict[str, int] = {}
        for row in rows:
            minutes[row["equipment_id"]] = minutes.get(row["equipment_id"], 0) + int(row["production_minutes"])
        return minutes


def production_readings(connection: psycopg.Connection) -> ProductionReadings | None:
    """Production's readings, or None when the production module is not installed."""
    try:
        import modules.production.api.stops_analytics_service  # noqa: F401
    except ImportError:
        return None
    return ProductionServices(connection)


def job_parts_costs(
    connection: psycopg.Connection, tenant_id: str, job_numbers: list[str]
) -> dict[str, tuple[float, float]] | None:
    """(cost XOF, unvalued quantity) of what left stock for each job (`maintenance:<number>`,
    the reference PartsService.approve issues under); None without the warehouse module."""
    try:
        from modules.warehouse.api.valuation_service import ValuationService
    except ImportError:
        return None
    if not job_numbers:
        return {}
    references = {f"maintenance:{number}": number for number in job_numbers}
    costs = ValuationService(connection).costs_of_references(tenant_id=tenant_id, references=list(references))
    return {references[reference]: (value["cost"], value["unvalued_quantity"]) for reference, value in costs.items()}
```

- [ ] **Step 4: Write `history_service.py` (indicators part)**

```python
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


def _number(value) -> float | None:
    return float(value) if value is not None else None


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
        return changes

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
```

Add `"production"` to `optional_depends` in `backend/modules/maintenance/module.json` and bump `"version"` to `"0.3.0"`:

```json
  "version": "0.3.0",
  "depends": ["core"],
  "optional_depends": ["hr", "warehouse", "production"],
```

- [ ] **Step 5: Run the tests**

Run: `.venv/Scripts/python -m pytest modules/maintenance/api/test_history_integration.py -q`
Expected: PASS (8 tests). If they all SKIP, the DB is unreachable — that is not a pass.

- [ ] **Step 6: Commit**

```bash
git add backend/modules/maintenance/api/history_sources.py backend/modules/maintenance/api/history_service.py backend/modules/maintenance/api/test_history_integration.py backend/modules/maintenance/module.json
git commit -m "feat(maintenance): machine indicators -- production and maintenance breakdowns side by side"
```

---

### Task 6: Journal of interventions

**Files:**
- Modify: `backend/modules/maintenance/api/history_service.py` (add `journal` and the shared `_job_rows`)
- Test: `backend/modules/maintenance/api/test_history_integration.py` (append)

**Interfaces:**
- Consumes: Task 5 `HistoryService`, helpers in the test file.
- Produces:
  - `HistoryService.journal(*, tenant_id, date_from: date, date_to: date, costs_visible: bool, equipment_id: str | None = None, kind: str | None = None, status: str = "closed") -> Result[dict]` → `{"from", "to", "costs_visible", "rows": [JournalRow]}`.
  - `HistoryService._job_rows(tenant_id: str, where: str, params: dict, costs_visible: bool) -> list[dict]` — one JournalRow per job (keys: `job_id, number, equipment_id, equipment_code, equipment_name, kind, priority, title, status, date, due_date, created_at, started_at, closed_on_time, cancel_reason, chef_name, performers[{employee_id,name}], technician_seconds, checks_total, checks_done, outcomes{ok,issue,not_done,pending}, parts{issued_lines,purchase_lines}, parts_cost, machine_stopped, machine_restarted`). Reused by Task 7.

- [ ] **Step 1: Write the failing tests** (append)

```python
from modules.maintenance.api.job_queries import job_detail  # noqa: E402
from modules.maintenance.api.parts_service import PartsService, list_part_requests  # noqa: E402
from modules.warehouse.api.location_service import LocationService  # noqa: E402
from modules.warehouse.api.service import StockService  # noqa: E402


def _journal(db, **overrides):
    arguments = dict(tenant_id=T, date_from=PERIOD[0], date_to=PERIOD[1], costs_visible=True)
    arguments.update(overrides)
    result = _service(db).journal(**arguments)
    assert isinstance(result, Ok), result
    return result.value["rows"]


def test_journal_row_tells_what_was_done_with_rework(db, ctx):
    jobs = JobService(db)
    job_id = _job(db, ctx, checkpoint_ids=ctx.points[:1], tasks=[{"label": "Nettoyer", "action": "clean"}])
    first, second = _checks(db, job_id)
    _entry(db, ctx, job_id, first)
    _entry(db, ctx, job_id, second, performer_employee_id=ctx.employees[1])
    jobs.submit(tenant_id=T, actor_id=ctx.chef, job_id=job_id, actor_can_plan=False)
    jobs.review(tenant_id=T, actor_id=ctx.sup, job_id=job_id, verdicts=[(first, "accepted", None), (second, "rejected", "mal fait")])
    _entry(db, ctx, job_id, second, outcome="issue")
    jobs.submit(tenant_id=T, actor_id=ctx.chef, job_id=job_id, actor_can_plan=False)
    jobs.review(tenant_id=T, actor_id=ctx.sup, job_id=job_id, verdicts=[(second, "accepted", None)])
    assert isinstance(jobs.close(tenant_id=T, actor_id=ctx.sup, job_id=job_id), Ok)
    _set_job_times(db, job_id, closed_at=datetime.datetime(2026, 9, 10, 9, tzinfo=UTC))

    [row] = _journal(db)

    assert row["job_id"] == job_id and row["status"] == "closed"
    assert row["date"].startswith("2026-09-10")
    assert row["outcomes"] == {"ok": 1, "issue": 1, "not_done": 0, "pending": 0}
    assert row["technician_seconds"] == 3 * 300  # three attempts' latest entries, five minutes each
    assert [p["name"] for p in row["performers"]] == ["Awa Diarra", "Moussa Traoré"]
    assert row["closed_on_time"] is True and row["chef_name"] == "Chef Keita"
    assert _journal(db, status="cancelled") == []
    assert _journal(db, kind="preventive") == []


def test_journal_lists_cancelled_jobs_by_their_cancel_date(db, ctx):
    job_id = _job(db, ctx)
    assert isinstance(JobService(db).cancel(tenant_id=T, actor_id=ctx.sup, job_id=job_id, reason="doublon"), Ok)
    _set_job_times(db, job_id, cancelled_at=datetime.datetime(2026, 9, 4, tzinfo=UTC))

    assert _journal(db) == []
    [row] = _journal(db, status="all")
    assert (row["status"], row["cancel_reason"], row["date"][:10]) == ("cancelled", "doublon", "2026-09-04")


def test_journal_parts_cost_needs_the_valuation_right(db, ctx):
    uom = str(ULID())
    db.execute("INSERT INTO core.uoms (id, tenant_id, code, name, category, is_integer_only) VALUES (%s, %s, 'pc', 'Pièce', 'unit', true)", (uom, T))
    bearing = str(ULID())
    db.execute("INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, 'ROUL-6204', 'Roulement 6204', %s)", (bearing, T, uom))
    store = LocationService(db).create_location(tenant_id=T, actor_id=ctx.sup, code="MAG-PDR", name="Magasin pièces").value.id
    assert isinstance(StockService(db).receive_stock(
        tenant_id=T, product_id=bearing, location_id=store, quantity=5, correlation_id=str(ULID()),
        reference="history-test", actor_id=ctx.sup, unit_cost=5000,
    ), Ok)
    job_id = _job(db, ctx)
    parts = PartsService(db)
    request_id = parts.create_request(
        tenant_id=T, actor_id=ctx.chef, job_id=job_id, lines=[{"product_id": bearing, "uom_id": uom, "quantity": 2}],
        note=None, actor_can_plan=False,
    ).value
    [request] = list_part_requests(db, T, job_id=job_id)
    [line] = request["lines"]
    assert isinstance(parts.approve(
        tenant_id=T, actor_id=ctx.sup, request_id=request_id,
        lines=[{"line_id": line["id"], "location_id": store, "issue_quantity": 2}], note=None, correlation_id=str(ULID()),
    ), Ok)
    _close(db, ctx, job_id, ["ok"])
    _set_job_times(db, job_id, closed_at=datetime.datetime(2026, 9, 12, tzinfo=UTC))

    [visible] = _journal(db)
    [hidden] = _journal(db, costs_visible=False)

    assert visible["parts"] == {"issued_lines": 1, "purchase_lines": 0}
    assert visible["parts_cost"] == 10_000
    assert hidden["parts_cost"] is None and hidden["parts"] == {"issued_lines": 1, "purchase_lines": 0}


def test_journal_refuses_unknown_filters(db, ctx):
    refused = _service(db).journal(tenant_id=T, date_from=PERIOD[0], date_to=PERIOD[1], costs_visible=True, status="open")
    assert isinstance(refused, Err) and refused.code == "INVALID_FILTER"
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python -m pytest modules/maintenance/api/test_history_integration.py -q -k journal`
Expected: FAIL with `AttributeError: 'HistoryService' object has no attribute 'journal'`.

- [ ] **Step 3: Implement** (add to `HistoryService`)

```python
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
```

- [ ] **Step 4: Run the tests**

Run: `.venv/Scripts/python -m pytest modules/maintenance/api/test_history_integration.py -q`
Expected: PASS (12 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/modules/maintenance/api/history_service.py backend/modules/maintenance/api/test_history_integration.py
git commit -m "feat(maintenance): journal of closed and cancelled interventions with outcomes, time and parts cost"
```

---

### Task 7: One machine's logbook

**Files:**
- Modify: `backend/modules/maintenance/api/history_service.py` (add `equipment_history`, `_checkpoint_summaries`)
- Test: `backend/modules/maintenance/api/test_history_integration.py` (append)

**Interfaces:**
- Consumes: `indicators(..., equipment_id=)`, `_job_rows`.
- Produces: `HistoryService.equipment_history(*, tenant_id, equipment_id, date_from: date, date_to: date, costs_visible: bool) -> Result[dict]` → `{"equipment": MachineSummary, "indicators": {"production", "maintenance"}, "costs_visible", "production_available", "timeline": [...], "checkpoints": [...]}` (spec shape). Timeline items: `{"kind": "job", "at", "job": JournalRow}`, `{"kind": "production_stop", "at", "stop": {...}}`, `{"kind": "status_change", "at", "from_status", "to_status", "actor_name"}`, newest first.

- [ ] **Step 1: Write the failing tests** (append)

```python
def _history(db, ctx, production=None, **overrides):
    arguments = dict(tenant_id=T, equipment_id=ctx.machine, date_from=PERIOD[0], date_to=PERIOD[1], costs_visible=True)
    arguments.update(overrides)
    result = _service(db, production).equipment_history(**arguments)
    assert isinstance(result, Ok), result
    return result.value


def test_the_logbook_mixes_jobs_stops_and_status_changes_newest_first(db, ctx):
    closed = _job(db, ctx, title="Graissage mensuel")
    _close(db, ctx, closed, ["ok"])
    _set_job_times(db, closed, created_at=datetime.datetime(2026, 9, 3, tzinfo=UTC), closed_at=datetime.datetime(2026, 9, 5, tzinfo=UTC))
    still_open = _job(db, ctx, title="Fuite d'huile")
    _set_job_times(db, still_open, created_at=datetime.datetime(2026, 8, 1, tzinfo=UTC))  # open: listed whatever its age
    old = _job(db, ctx, title="Ancienne")
    _close(db, ctx, old, ["ok"])
    _set_job_times(db, old, created_at=datetime.datetime(2026, 7, 1, tzinfo=UTC), closed_at=datetime.datetime(2026, 7, 2, tzinfo=UTC))
    EquipmentService(db).transition_status(tenant_id=T, actor_id=ctx.sup, equipment_id=ctx.machine, new_status="down")
    _set_audit_times(db, ctx.machine, [datetime.datetime(2026, 9, 20, 14, tzinfo=UTC)])
    production = FakeProduction(stops=[_stop(ctx.machine, 75, started_at="2026-09-12T09:40:00+00:00")], running={ctx.machine: 600})

    history = _history(db, ctx, production)

    assert [(item["kind"], item["at"][:10]) for item in history["timeline"]] == [
        ("status_change", "2026-09-20"),
        ("production_stop", "2026-09-12"),
        ("job", "2026-09-05"),
        ("job", "2026-08-01"),
    ]
    status_change = history["timeline"][0]
    assert (status_change["from_status"], status_change["to_status"], status_change["actor_name"]) == ("operational", "down", "Sara Superviseur")
    stop = history["timeline"][1]["stop"]
    assert (stop["minutes"], stop["classification"], stop["note"]) == (75, "mechanical", "filière démontée")
    assert history["equipment"]["equipment_id"] == ctx.machine
    assert history["indicators"]["production"]["breakdowns"] == 1


def test_the_logbook_summarises_each_checkpoint(db, ctx):
    for value, outcome, closed_on in ((68, "ok", 5), (71, "issue", 15)):
        job_id = _job(db, ctx, checkpoint_ids=[ctx.points[1]])
        [check] = _checks(db, job_id)
        _entry(db, ctx, job_id, check, measured_value=value, outcome=outcome)
        jobs = JobService(db)
        jobs.submit(tenant_id=T, actor_id=ctx.chef, job_id=job_id, actor_can_plan=False)
        jobs.review(tenant_id=T, actor_id=ctx.sup, job_id=job_id, verdicts=[(check, "accepted", None)])
        jobs.close(tenant_id=T, actor_id=ctx.sup, job_id=job_id)
    MapService(db).archive_checkpoint(tenant_id=T, actor_id=ctx.sup, checkpoint_id=ctx.points[2])

    points = {p["checkpoint_id"]: p for p in _history(db, ctx)["checkpoints"]}

    measured = points[ctx.points[1]]
    assert (measured["checks_count"], measured["issues_count"], measured["last_outcome"]) == (2, 1, "issue")
    assert measured["last_measured_value"] == 71
    assert [m["value"] for m in measured["recent_measures"]] == [68, 71]
    assert points[ctx.points[0]]["checks_count"] == 0 and points[ctx.points[0]]["last_checked_at"] is None
    assert ctx.points[2] not in points  # archived and never checked


def test_an_unknown_machine_has_no_logbook(db, ctx):
    missing = _service(db).equipment_history(tenant_id=T, equipment_id="nope", date_from=PERIOD[0], date_to=PERIOD[1], costs_visible=True)
    assert isinstance(missing, Err) and missing.code == "NOT_FOUND"
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python -m pytest modules/maintenance/api/test_history_integration.py -q -k logbook`
Expected: FAIL with `AttributeError: ... 'equipment_history'`.

- [ ] **Step 3: Implement** (add to `HistoryService`)

```python
    # ---- one machine's logbook -------------------------------------------------

    def equipment_history(
        self,
        *,
        tenant_id: str,
        equipment_id: str,
        date_from: datetime.date,
        date_to: datetime.date,
        costs_visible: bool,
    ) -> Result[dict]:
        indicators = self.indicators(
            tenant_id=tenant_id, date_from=date_from, date_to=date_to, costs_visible=costs_visible, equipment_id=equipment_id
        )
        if isinstance(indicators, Err):
            return indicators
        [machine] = indicators.value["machines"]
        start, end = period_bounds(date_from, date_to, self._now)

        timeline: list[dict] = []
        jobs = self._job_rows(
            tenant_id,
            """j.equipment_id = %(equipment)s AND (
                   (j.created_at >= %(start)s AND j.created_at < %(end)s)
                OR (j.closed_at >= %(start)s AND j.closed_at < %(end)s)
                OR (j.cancelled_at >= %(start)s AND j.cancelled_at < %(end)s)
                OR j.status NOT IN ('closed', 'cancelled'))""",
            {"equipment": equipment_id, "start": start, "end": end},
            costs_visible,
        )
        for job in jobs:
            # A closed or cancelled job sits at its end; an open one at its creation.
            timeline.append({"kind": "job", "at": job["date"] or job["created_at"], "job": job})
        if self._production is not None:
            for stop in self._production.stops(tenant_id=tenant_id, date_from=date_from, date_to=date_to, equipment_id=equipment_id):
                timeline.append(
                    {
                        "kind": "production_stop",
                        "at": stop["started_at"],
                        "stop": {
                            key: stop[key]
                            for key in (
                                "started_at", "ended_at", "minutes", "downtime_type", "classification", "motif",
                                "note", "corrective_action", "report_date", "team", "shift_report_id",
                            )
                        },
                    }
                )
        changes = self._connection.execute(
            """
            SELECT occurred_at, payload->>'from_status', payload->>'to_status', actor_id
            FROM core.audit_log
            WHERE tenant_id = %s AND entity_type = 'equipment' AND action = 'equipment.status_changed'
              AND entity_id = %s AND occurred_at >= %s AND occurred_at < %s
            """,
            (tenant_id, equipment_id, start, end),
        ).fetchall()
        actors = user_names(self._connection, tenant_id, [row[3] for row in changes])
        for at, from_status, to_status, actor_id in changes:
            timeline.append(
                {"kind": "status_change", "at": at.isoformat(), "from_status": from_status, "to_status": to_status,
                 "actor_name": actors.get(actor_id)}
            )
        timeline.sort(key=lambda item: datetime.datetime.fromisoformat(item["at"]), reverse=True)

        summary = {key: machine[key] for key in machine if key not in ("production", "maintenance")}
        return Ok(
            {
                "equipment": summary,
                "indicators": {"production": machine["production"], "maintenance": machine["maintenance"]},
                "costs_visible": costs_visible,
                "production_available": self._production is not None,
                "timeline": timeline,
                "checkpoints": self._checkpoint_summaries(tenant_id, equipment_id),
            }
        )

    def _checkpoint_summaries(self, tenant_id: str, equipment_id: str) -> list[dict]:
        """Every point of the machine's map, in map order, with its whole history (not the
        period's): an archived point is kept only if it was ever checked."""
        points = self._connection.execute(
            """
            SELECT cp.id, cp.view_id, v.label, cp.label, cp.action, cp.measure_unit, cp.sort_order, cp.archived_at
            FROM maintenance.checkpoints cp
            JOIN maintenance.equipment_views v ON v.id = cp.view_id
            WHERE v.equipment_id = %s AND cp.tenant_id = %s
            ORDER BY v.sort_order, v.id, cp.sort_order, cp.id
            """,
            (equipment_id, tenant_id),
        ).fetchall()
        entries = self._connection.execute(
            """
            SELECT c.checkpoint_id, c.id, en.finished_at, en.outcome, en.measured_value
            FROM maintenance.check_entries en
            JOIN maintenance.job_checks c ON c.id = en.check_id
            JOIN maintenance.jobs j ON j.id = c.job_id
            WHERE j.equipment_id = %s AND j.tenant_id = %s AND c.checkpoint_id IS NOT NULL
            ORDER BY en.finished_at, en.id
            """,
            (equipment_id, tenant_id),
        ).fetchall()
        by_point: dict[str, list[tuple]] = defaultdict(list)
        for checkpoint_id, *rest in entries:
            by_point[checkpoint_id].append(tuple(rest))

        summaries = []
        for checkpoint_id, view_id, view_label, label, action, unit, sort_order, archived_at in points:
            history = by_point.get(checkpoint_id, [])
            if archived_at is not None and not history:
                continue
            last = history[-1] if history else None
            measures = [(finished_at, value) for _check, finished_at, _outcome, value in history if value is not None]
            summaries.append(
                {
                    "checkpoint_id": checkpoint_id,
                    "view_id": view_id,
                    "view_label": view_label,
                    "label": label,
                    "action": action,
                    "measure_unit": unit,
                    "sort_order": sort_order,
                    "archived": archived_at is not None,
                    "checks_count": len({check_id for check_id, *_ in history}),
                    "issues_count": sum(1 for _check, _at, outcome, _value in history if outcome == "issue"),
                    "last_checked_at": _iso(last[1]) if last else None,
                    "last_outcome": last[2] if last else None,
                    "last_measured_value": _number(measures[-1][1]) if measures else None,
                    "recent_measures": [{"at": at.isoformat(), "value": float(value)} for at, value in measures[-8:]],
                }
            )
        return summaries
```

- [ ] **Step 4: Run the tests**

Run: `.venv/Scripts/python -m pytest modules/maintenance/api/test_history_integration.py -q`
Expected: PASS (15 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/modules/maintenance/api/history_service.py backend/modules/maintenance/api/test_history_integration.py
git commit -m "feat(maintenance): machine logbook -- timeline of jobs, production stops and status changes, checkpoint summary"
```

---

### Task 8: One checkpoint's history

**Files:**
- Modify: `backend/modules/maintenance/api/history_service.py` (add `checkpoint_history`)
- Test: `backend/modules/maintenance/api/test_history_integration.py` (append)

**Interfaces:**
- Produces: `HistoryService.checkpoint_history(*, tenant_id: str, checkpoint_id: str) -> Result[dict]` → `{"checkpoint": {id, label, action, instructions, measure_unit, requires_photo, view_id, view_label, view_version, x_pct, y_pct, equipment_id, equipment_name, archived_at}, "summary": {checks_count, issues_count, last_checked_at}, "measures": [{at, value, outcome, job_number}], "checks": [{job_id, job_number, job_kind, job_status, check_id, attempts: [{attempt, entries: [{entry_id, performer_name, recorded_by_name, started_at, finished_at, duration_seconds, duration_source, outcome, note, measured_value, has_photo}], review: {verdict, reason, reviewer_name, created_at} | null}]}]}`; checks newest job first, attempts oldest first, measures oldest first.

- [ ] **Step 1: Write the failing tests** (append)

```python
def test_a_checkpoint_history_keeps_every_attempt_across_jobs(db, ctx):
    jobs = JobService(db)
    first_job = _job(db, ctx, checkpoint_ids=[ctx.points[1]])
    [first_check] = _checks(db, first_job)
    _entry(db, ctx, first_job, first_check, measured_value=68)
    jobs.submit(tenant_id=T, actor_id=ctx.chef, job_id=first_job, actor_can_plan=False)
    jobs.review(tenant_id=T, actor_id=ctx.sup, job_id=first_job, verdicts=[(first_check, "accepted", None)])
    jobs.close(tenant_id=T, actor_id=ctx.sup, job_id=first_job)
    _set_job_times(db, first_job, created_at=datetime.datetime(2026, 8, 1, tzinfo=UTC))

    second_job = _job(db, ctx, checkpoint_ids=[ctx.points[1]])
    [second_check] = _checks(db, second_job)
    _entry(db, ctx, second_job, second_check, measured_value=78, outcome="issue", note="bruit anormal")
    jobs.submit(tenant_id=T, actor_id=ctx.chef, job_id=second_job, actor_can_plan=False)
    jobs.review(tenant_id=T, actor_id=ctx.sup, job_id=second_job, verdicts=[(second_check, "rejected", "refaire après graissage")])
    _entry(db, ctx, second_job, second_check, measured_value=71, performer_employee_id=ctx.employees[1])

    result = _service(db).checkpoint_history(tenant_id=T, checkpoint_id=ctx.points[1])

    assert isinstance(result, Ok), result
    history = result.value
    assert history["checkpoint"]["label"] == "Température palier" and history["checkpoint"]["measure_unit"] == "°C"
    assert [c["job_id"] for c in history["checks"]] == [second_job, first_job]
    rejected, redone = history["checks"][0]["attempts"]
    assert (rejected["attempt"], rejected["review"]["verdict"], rejected["review"]["reason"]) == (1, "rejected", "refaire après graissage")
    assert rejected["entries"][0]["note"] == "bruit anormal" and rejected["entries"][0]["outcome"] == "issue"
    assert (redone["attempt"], redone["review"], redone["entries"][0]["performer_name"]) == (2, None, "Moussa Traoré")
    assert [m["value"] for m in history["measures"]] == [68, 78, 71]
    assert history["summary"]["checks_count"] == 2 and history["summary"]["issues_count"] == 1


def test_an_unknown_checkpoint_has_no_history(db, ctx):
    missing = _service(db).checkpoint_history(tenant_id=T, checkpoint_id="nope")
    assert isinstance(missing, Err) and missing.code == "NOT_FOUND"
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python -m pytest modules/maintenance/api/test_history_integration.py -q -k checkpoint_history`
Expected: FAIL with `AttributeError: ... 'checkpoint_history'`.

- [ ] **Step 3: Implement** (add to `HistoryService`)

```python
    # ---- one checkpoint ----------------------------------------------------------

    def checkpoint_history(self, *, tenant_id: str, checkpoint_id: str) -> Result[dict]:
        """Every check of one point across every job (the snapshot keeps the point's id),
        newest job first; each attempt with its entries and its review."""
        row = self._connection.execute(
            """
            SELECT cp.id, cp.label, cp.action, cp.instructions, cp.measure_unit, cp.requires_photo, cp.view_id, v.label,
                   v.updated_at, cp.x_pct, cp.y_pct, e.id, e.name, cp.archived_at
            FROM maintenance.checkpoints cp
            JOIN maintenance.equipment_views v ON v.id = cp.view_id
            JOIN maintenance.equipment e ON e.id = v.equipment_id
            WHERE cp.id = %s AND cp.tenant_id = %s
            """,
            (checkpoint_id, tenant_id),
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"checkpoint {checkpoint_id} not found", f"point {checkpoint_id} introuvable")
        (point_id, label, action, instructions, unit, requires_photo, view_id, view_label,
         view_updated_at, x_pct, y_pct, equipment_id, equipment_name, archived_at) = row

        checks = self._connection.execute(
            """
            SELECT c.id, j.id, j.number, j.kind, j.status
            FROM maintenance.job_checks c
            JOIN maintenance.jobs j ON j.id = c.job_id
            WHERE c.checkpoint_id = %s AND c.tenant_id = %s
            ORDER BY j.created_at DESC, j.number DESC
            """,
            (checkpoint_id, tenant_id),
        ).fetchall()
        check_ids = [check[0] for check in checks]
        entries = self._connection.execute(
            """
            SELECT id, check_id, attempt, performer_employee_id, recorded_by, started_at, finished_at, duration_seconds,
                   duration_source, outcome, note, measured_value, photo IS NOT NULL
            FROM maintenance.check_entries
            WHERE check_id = ANY(%s)
            ORDER BY created_at, id
            """,
            (check_ids,),
        ).fetchall()
        reviews = self._connection.execute(
            """
            SELECT check_id, attempt, verdict, reason, reviewer_id, created_at
            FROM maintenance.check_reviews
            WHERE check_id = ANY(%s)
            ORDER BY created_at, id
            """,
            (check_ids,),
        ).fetchall()
        users = user_names(self._connection, tenant_id, [*(e[4] for e in entries), *(r[4] for r in reviews)])
        people = employee_names(self._connection, tenant_id, [e[3] for e in entries])
        number_of = {check[0]: check[2] for check in checks}

        attempts: dict[str, dict[int, dict]] = defaultdict(dict)
        for (entry_id, check_id, attempt, performer, recorded_by, started_at, finished_at, duration, source,
             outcome, note, value, has_photo) in entries:
            slot = attempts[check_id].setdefault(attempt, {"attempt": attempt, "entries": [], "review": None})
            slot["entries"].append(
                {
                    "entry_id": entry_id,
                    "performer_name": people.get(performer, performer),
                    "recorded_by_name": users.get(recorded_by, recorded_by),
                    "started_at": started_at.isoformat(),
                    "finished_at": finished_at.isoformat(),
                    "duration_seconds": duration,
                    "duration_source": source,
                    "outcome": outcome,
                    "note": note,
                    "measured_value": _number(value),
                    "has_photo": has_photo,
                }
            )
        for check_id, attempt, verdict, reason, reviewer_id, created_at in reviews:
            slot = attempts[check_id].setdefault(attempt, {"attempt": attempt, "entries": [], "review": None})
            slot["review"] = {
                "verdict": verdict, "reason": reason, "reviewer_name": users.get(reviewer_id, reviewer_id),
                "created_at": created_at.isoformat(),
            }

        last_checked_at = max((e[6] for e in entries), default=None)
        measures = sorted(
            (
                {"at": e[6].isoformat(), "value": float(e[11]), "outcome": e[9], "job_number": number_of[e[1]]}
                for e in entries
                if e[11] is not None
            ),
            key=lambda measure: measure["at"],
        )
        return Ok(
            {
                "checkpoint": {
                    "id": point_id, "label": label, "action": action, "instructions": instructions, "measure_unit": unit,
                    "requires_photo": requires_photo, "view_id": view_id, "view_label": view_label,
                    "view_version": _iso(view_updated_at), "x_pct": float(x_pct), "y_pct": float(y_pct),
                    "equipment_id": equipment_id, "equipment_name": equipment_name, "archived_at": _iso(archived_at),
                },
                "summary": {
                    "checks_count": sum(1 for check in checks if attempts.get(check[0])),
                    "issues_count": sum(1 for e in entries if e[9] == "issue"),
                    "last_checked_at": _iso(last_checked_at),
                },
                "measures": measures,
                "checks": [
                    {
                        "job_id": job_id, "job_number": number, "job_kind": kind, "job_status": status, "check_id": check_id,
                        "attempts": [attempts[check_id][n] for n in sorted(attempts.get(check_id, {}))],
                    }
                    for check_id, job_id, number, kind, status in checks
                ],
            }
        )
```

- [ ] **Step 4: Run the tests**

Run: `.venv/Scripts/python -m pytest modules/maintenance/api/test_history_integration.py modules/maintenance/domain/test_history.py -q`
Expected: PASS (17 + 12 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/modules/maintenance/api/history_service.py backend/modules/maintenance/api/test_history_integration.py
git commit -m "feat(maintenance): checkpoint history across jobs, every attempt with its review and measures"
```

---

### Task 9: History endpoints and the Excel journal

**Files:**
- Create: `backend/modules/maintenance/api/history_export.py`
- Create: `backend/modules/maintenance/api/history_router.py`
- Modify: `backend/modules/maintenance/api/router.py` (import and include `history_router`)
- Test: `backend/modules/maintenance/api/test_history_router_integration.py`

**Interfaces:**
- Consumes: `HistoryService` (Tasks 5–8), `production_readings`, `user_has_permission`.
- Produces HTTP (all `maintenance.view_jobs`; `from`/`to` default to Jan 1 of this year / today):
  - `GET /maintenance/history/indicators?from&to&equipment_id`
  - `GET /maintenance/history/journal?from&to&equipment_id&kind&status`
  - `GET /maintenance/history/journal/export?<same>&lang=fr|en` → `.xlsx`
  - `GET /maintenance/equipment/{equipment_id}/history?from&to`
  - `GET /maintenance/checkpoints/{checkpoint_id}/history`
  - `journal_workbook(journal: dict, *, lang: str) -> bytes`

- [ ] **Step 1: Write the failing tests**

```python
"""The history endpoints over HTTP: rights, cost visibility, error codes, the Excel journal."""
from __future__ import annotations

import datetime
import io
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from ulid import ULID

pytest.importorskip("httpx", reason="the FastAPI test client needs httpx (requirements-dev.txt)")
from fastapi.testclient import TestClient  # noqa: E402
from openpyxl import load_workbook  # noqa: E402

from core.domain.result import Ok  # noqa: E402
from core.tenancy import TenantContext, require_session  # noqa: E402
from modules.hr.api.employee_service import EmployeeService  # noqa: E402
from modules.hr.domain.employee import EmployeeFile  # noqa: E402
from modules.maintenance.api import history_router  # noqa: E402
from modules.maintenance.api import router as router_module  # noqa: E402
from modules.maintenance.api.equipment_service import EquipmentService  # noqa: E402
from modules.maintenance.api.job_service import JobService  # noqa: E402

TENANT = "integration-test-history-router"
TODAY = datetime.date.today()


class _Connection:
    """The fixture's connection, with the transaction left to the fixture."""

    def __init__(self, connection) -> None:
        self._connection = connection

    def __getattr__(self, name):
        return getattr(self._connection, name)

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> bool:
        return False


def _user(db, full_name, *permissions):
    user_id = str(ULID())
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash, full_name) VALUES (%s, %s, %s, 'x', %s)",
        (user_id, TENANT, f"{user_id}@test.local", full_name),
    )
    for permission in permissions:
        db.execute("INSERT INTO core.user_permissions (user_id, permission) VALUES (%s, %s)", (user_id, permission))
    return user_id


@pytest.fixture
def api(db, monkeypatch):
    sup = _user(db, "Sara Superviseur", "maintenance.view_jobs", "maintenance.plan_jobs", "maintenance.execute_jobs")
    valuer = _user(db, "Valérie Valorisation", "maintenance.view_jobs", "warehouse.view_valuation")
    nobody = _user(db, "Sans Droit")
    machine = EquipmentService(db).create_equipment(
        tenant_id=TENANT, actor_id=sup, work_center_id="wc-1", code="PRESSE-1", name="Presse 1"
    ).value.id
    employee = EmployeeService(db).create_employee(
        tenant_id=TENANT, actor_id=sup,
        employee=EmployeeFile(employee_no=f"E-{ULID()}", first_name="Awa", last_name="Diarra", hire_date=datetime.date(2024, 1, 1)),
    ).value["id"]

    jobs = JobService(db)
    job_id = jobs.create_job(
        tenant_id=TENANT, actor_id=sup, equipment_id=machine, title="Graissage", description=None, kind="corrective",
        priority="normal", due_date=TODAY, stops_machine=False, checkpoint_ids=[],
        tasks=[{"label": "Graisser", "action": "lubricate"}], chef_user_id=sup,
    ).value
    [check_id] = [r[0] for r in db.execute("SELECT id FROM maintenance.job_checks WHERE job_id = %s", (job_id,)).fetchall()]
    now = datetime.datetime.now(datetime.timezone.utc)
    assert isinstance(jobs.record_entry(
        tenant_id=TENANT, actor_id=sup, job_id=job_id, check_id=check_id, performer_employee_id=employee, outcome="ok",
        note=None, measured_value=None, started_at=now - datetime.timedelta(minutes=5), finished_at=now,
        manual_minutes=None, photo=None, actor_can_plan=True, now=now,
    ), Ok)
    jobs.submit(tenant_id=TENANT, actor_id=sup, job_id=job_id, actor_can_plan=True)
    jobs.review(tenant_id=TENANT, actor_id=sup, job_id=job_id, verdicts=[(check_id, "accepted", None)])
    assert isinstance(jobs.close(tenant_id=TENANT, actor_id=sup, job_id=job_id), Ok)

    wrapped = _Connection(db)
    monkeypatch.setattr(history_router, "get_connection", lambda: wrapped)
    monkeypatch.setattr("core.tenancy.get_connection", lambda: wrapped)
    current = {"user": sup}
    app = FastAPI()
    app.include_router(router_module.router)
    app.dependency_overrides[require_session] = lambda: TenantContext(tenant_id=TENANT, user_id=current["user"], session_token="t")

    def acting_as(user_id: str) -> None:
        current["user"] = user_id

    return SimpleNamespace(client=TestClient(app), acting_as=acting_as, sup=sup, valuer=valuer, nobody=nobody, machine=machine, job=job_id)


PERIOD = f"from={TODAY.replace(month=1, day=1).isoformat()}&to={TODAY.isoformat()}"


def test_history_routes_need_view_jobs(api):
    api.acting_as(api.nobody)
    for path in (
        f"/maintenance/history/indicators?{PERIOD}",
        f"/maintenance/history/journal?{PERIOD}",
        f"/maintenance/history/journal/export?{PERIOD}",
        f"/maintenance/equipment/{api.machine}/history?{PERIOD}",
        "/maintenance/checkpoints/whatever/history",
    ):
        assert api.client.get(path).status_code == 403, path


def test_costs_follow_the_valuation_right(api):
    plain = api.client.get(f"/maintenance/history/journal?{PERIOD}").json()
    assert plain["costs_visible"] is False and plain["rows"][0]["parts_cost"] is None
    api.acting_as(api.valuer)
    valued = api.client.get(f"/maintenance/history/journal?{PERIOD}").json()
    assert valued["costs_visible"] is True and valued["rows"][0]["parts_cost"] == 0


def test_indicators_and_logbook_answer(api):
    indicators = api.client.get(f"/maintenance/history/indicators?{PERIOD}")
    assert indicators.status_code == 200
    assert api.machine in {m["equipment_id"] for m in indicators.json()["machines"]}
    logbook = api.client.get(f"/maintenance/equipment/{api.machine}/history?{PERIOD}")
    assert logbook.status_code == 200 and logbook.json()["timeline"][0]["job"]["job_id"] == api.job


def test_error_codes(api):
    reversed_period = api.client.get(f"/maintenance/history/journal?from={TODAY.isoformat()}&to=2000-01-01")
    assert reversed_period.status_code == 422 and reversed_period.json()["detail"]["code"] == "INVALID_PERIOD"
    assert api.client.get(f"/maintenance/history/journal?{PERIOD}&status=open").json()["detail"]["code"] == "INVALID_FILTER"
    unknown = api.client.get(f"/maintenance/equipment/nope/history?{PERIOD}")
    assert unknown.status_code == 404 and unknown.json()["detail"]["message_fr"]
    assert api.client.get("/maintenance/checkpoints/nope/history").status_code == 404


def test_the_excel_journal_holds_the_rows_and_hides_costs_without_the_right(api):
    response = api.client.get(f"/maintenance/history/journal/export?{PERIOD}&lang=fr")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/vnd.openxmlformats")
    sheet = load_workbook(io.BytesIO(response.content)).active
    headers = [cell.value for cell in sheet[2]]
    assert headers[:3] == ["N°", "Clôturée le", "Machine"] and "Coût (XOF)" not in headers
    numbers = [row[0].value for row in sheet.iter_rows(min_row=3) if row[0].value and str(row[0].value).startswith("MT-")]
    assert len(numbers) == 1

    api.acting_as(api.valuer)
    valued = load_workbook(io.BytesIO(api.client.get(f"/maintenance/history/journal/export?{PERIOD}&lang=en").content)).active
    assert "Cost (XOF)" in [cell.value for cell in valued[2]]
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python -m pytest modules/maintenance/api/test_history_router_integration.py -q`
Expected: FAIL with `ImportError: cannot import name 'history_router'`.

- [ ] **Step 3: Write `history_export.py`**

```python
"""The maintenance journal as an Excel workbook, in the house style of the production recaps."""
from __future__ import annotations

import datetime
import io

from openpyxl import Workbook

from modules.production.api.xlsx_report_style import autofit, data_row, header_row, title_row, total_row

_TEXT = {
    "fr": {
        "sheet": "Journal",
        "title": "Journal des interventions de maintenance — {from_} → {to}",
        "headers": ["N°", "Clôturée le", "Machine", "Type", "Intervention", "Techniciens", "Temps (min)",
                    "OK", "Anomalies", "Non faits", "Pièces sorties (lignes)", "Pièces commandées (lignes)"],
        "cost": "Coût (XOF)",
        "kind": {"preventive": "Préventive", "corrective": "Corrective"},
        "total": "Total",
    },
    "en": {
        "sheet": "Journal",
        "title": "Maintenance journal — {from_} → {to}",
        "headers": ["No.", "Closed on", "Machine", "Type", "Intervention", "Technicians", "Time (min)",
                    "OK", "Issues", "Not done", "Parts issued (lines)", "Parts ordered (lines)"],
        "cost": "Cost (XOF)",
        "kind": {"preventive": "Preventive", "corrective": "Corrective"},
        "total": "Total",
    },
}


def journal_workbook(journal: dict, *, lang: str) -> bytes:
    text = _TEXT.get(lang, _TEXT["fr"])
    headers = list(text["headers"]) + ([text["cost"]] if journal["costs_visible"] else [])
    span = len(headers)
    money_cols = {span} if journal["costs_visible"] else set()

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = text["sheet"]
    title_row(sheet, 1, span, text["title"].format(from_=journal["from"], to=journal["to"]))
    header_row(sheet, 2, headers)
    row_number = 3
    total_minutes = 0
    total_cost = 0.0
    for row in journal["rows"]:
        minutes = (row["technician_seconds"] + 30) // 60
        total_minutes += minutes
        values = [
            row["number"],
            datetime.date.fromisoformat(row["date"][:10]) if row["date"] else None,
            f"{row['equipment_code']} — {row['equipment_name']}",
            text["kind"][row["kind"]],
            row["title"],
            ", ".join(person["name"] for person in row["performers"]),
            minutes,
            row["outcomes"]["ok"],
            row["outcomes"]["issue"],
            row["outcomes"]["not_done"],
            row["parts"]["issued_lines"],
            row["parts"]["purchase_lines"],
        ]
        if journal["costs_visible"]:
            values.append(row["parts_cost"] or 0)
            total_cost += row["parts_cost"] or 0
        data_row(sheet, row_number, values, money_cols=money_cols)
        sheet.cell(row=row_number, column=2).number_format = "dd/mm/yyyy"
        row_number += 1
    totals: list = [total_minutes, None, None, None, None, None]
    if journal["costs_visible"]:
        totals.append(total_cost)
    total_row(sheet, row_number, span, text["total"], 6, totals, money_cols=money_cols)
    autofit(sheet, [14, 12, 28, 12, 34, 30, 11, 6, 10, 10, 14, 16, 14][:span])

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
```

- [ ] **Step 4: Write `history_router.py`**

```python
"""The machine history endpoints (spec 2026-10-02-maintenance-history-design.md): indicators,
journal (+ Excel), one machine's logbook, one checkpoint's history. Read-only, view_jobs.
Costs are only returned to a holder of warehouse.view_valuation."""
from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from core.db import get_connection
from core.domain.result import Err, err_detail
from core.tenancy import TenantContext, require_permission, user_has_permission
from modules.maintenance.api.history_export import journal_workbook
from modules.maintenance.api.history_service import HistoryService
from modules.maintenance.api.history_sources import production_readings

# No prefix: included into modules/maintenance/api/router.py, which carries /maintenance.
router = APIRouter(tags=["maintenance.history"])

_VIEW = "maintenance.view_jobs"
_STATUS_BY_CODE = {"NOT_FOUND": status.HTTP_404_NOT_FOUND}
_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _period(date_from: datetime.date | None, date_to: datetime.date | None) -> tuple[datetime.date, datetime.date]:
    today = datetime.date.today()
    return date_from or datetime.date(today.year, 1, 1), date_to or today


def _service(connection) -> HistoryService:
    return HistoryService(connection, production=production_readings(connection))


def _costs_visible(connection, tenant: TenantContext) -> bool:
    return user_has_permission(connection, user_id=tenant.user_id, permission="warehouse.view_valuation")


def _unwrap(result):
    if isinstance(result, Err):
        raise HTTPException(_STATUS_BY_CODE.get(result.code, status.HTTP_422_UNPROCESSABLE_ENTITY), err_detail(result))
    return result.value


@router.get("/history/indicators")
def history_indicators(
    date_from: datetime.date | None = Query(default=None, alias="from"),
    date_to: datetime.date | None = Query(default=None, alias="to"),
    equipment_id: str | None = None,
    tenant: TenantContext = Depends(require_permission(_VIEW)),
) -> dict:
    start, end = _period(date_from, date_to)
    with get_connection() as connection:
        return _unwrap(
            _service(connection).indicators(
                tenant_id=tenant.tenant_id, date_from=start, date_to=end, equipment_id=equipment_id,
                costs_visible=_costs_visible(connection, tenant),
            )
        )


def _journal(connection, tenant, date_from, date_to, equipment_id, kind, journal_status) -> dict:
    start, end = _period(date_from, date_to)
    return _unwrap(
        _service(connection).journal(
            tenant_id=tenant.tenant_id, date_from=start, date_to=end, equipment_id=equipment_id, kind=kind,
            status=journal_status, costs_visible=_costs_visible(connection, tenant),
        )
    )


@router.get("/history/journal")
def history_journal(
    date_from: datetime.date | None = Query(default=None, alias="from"),
    date_to: datetime.date | None = Query(default=None, alias="to"),
    equipment_id: str | None = None,
    kind: str | None = None,
    journal_status: str = Query(default="closed", alias="status"),
    tenant: TenantContext = Depends(require_permission(_VIEW)),
) -> dict:
    with get_connection() as connection:
        return _journal(connection, tenant, date_from, date_to, equipment_id, kind, journal_status)


@router.get("/history/journal/export")
def history_journal_export(
    date_from: datetime.date | None = Query(default=None, alias="from"),
    date_to: datetime.date | None = Query(default=None, alias="to"),
    equipment_id: str | None = None,
    kind: str | None = None,
    journal_status: str = Query(default="closed", alias="status"),
    lang: str = "fr",
    tenant: TenantContext = Depends(require_permission(_VIEW)),
) -> Response:
    with get_connection() as connection:
        journal = _journal(connection, tenant, date_from, date_to, equipment_id, kind, journal_status)
    filename = f"maintenance-journal-{journal['from']}_{journal['to']}.xlsx"
    return Response(
        content=journal_workbook(journal, lang=lang),
        media_type=_XLSX,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/equipment/{equipment_id}/history")
def equipment_history(
    equipment_id: str,
    date_from: datetime.date | None = Query(default=None, alias="from"),
    date_to: datetime.date | None = Query(default=None, alias="to"),
    tenant: TenantContext = Depends(require_permission(_VIEW)),
) -> dict:
    start, end = _period(date_from, date_to)
    with get_connection() as connection:
        return _unwrap(
            _service(connection).equipment_history(
                tenant_id=tenant.tenant_id, equipment_id=equipment_id, date_from=start, date_to=end,
                costs_visible=_costs_visible(connection, tenant),
            )
        )


@router.get("/checkpoints/{checkpoint_id}/history")
def checkpoint_history(checkpoint_id: str, tenant: TenantContext = Depends(require_permission(_VIEW))) -> dict:
    with get_connection() as connection:
        return _unwrap(_service(connection).checkpoint_history(tenant_id=tenant.tenant_id, checkpoint_id=checkpoint_id))
```

In `backend/modules/maintenance/api/router.py`, add `history_router` to the existing import line and include it after the others:

```python
from modules.maintenance.api import history_router, jobs_router, maps_router, parts_router, programs_router, spare_parts_router, teams_router
...
router.include_router(spare_parts_router.router)
router.include_router(history_router.router)
```

- [ ] **Step 5: Run the tests**

Run: `.venv/Scripts/python -m pytest modules/maintenance/api/test_history_router_integration.py modules/maintenance -q`
Expected: PASS (the new 5 router tests and the whole maintenance suite).

- [ ] **Step 6: Commit**

```bash
git add backend/modules/maintenance/api/history_export.py backend/modules/maintenance/api/history_router.py backend/modules/maintenance/api/router.py backend/modules/maintenance/api/test_history_router_integration.py
git commit -m "feat(maintenance): history endpoints and the Excel journal, costs only with the valuation right"
```

---

### Task 10: Dev seed for the history screens

**Files:**
- Create: `backend/scripts/seed_maintenance_history.py`

**Interfaces:**
- Consumes: `JobService`, `EquipmentService`, the demo data from `scripts.seed_maintenance` (team, machines with views and points).
- Produces: dev-only history (never run on the server, never a migration).

- [ ] **Step 1: Write the script**

```python
"""Dev-only history for the maintenance logbook: five months of closed jobs on the demo
machines (monthly preventive rounds with trending measures, a corrective job sent back
once), and their status changes. Run after scripts.seed_maintenance:

    .venv/Scripts/python -m scripts.seed_maintenance_history

Idempotent: does nothing when a job titled "Historique démo" already exists. Only adds
maintenance rows and audit rows written by EquipmentService; backdates their timestamps
(dev data only -- the services always write NOW()).
"""
from __future__ import annotations

import datetime

from core.db import get_connection
from core.domain.result import Err
from modules.maintenance.api.equipment_service import EquipmentService
from modules.maintenance.api.job_service import JobService
from modules.maintenance.api.people import active_employees

TENANT = "demo"
DEMO_EMAIL = "demo@sonalim-erp.local"
MARKER = "Historique démo"
UTC = datetime.timezone.utc
MONTHS = 5


def _check(result, context: str):
    if isinstance(result, Err):
        raise RuntimeError(f"{context}: {result.code} — {result.message}")
    return result.value


def _set(connection, table: str, row_id: str, **columns) -> None:
    for column, value in columns.items():
        connection.execute(f"UPDATE maintenance.{table} SET {column} = %s WHERE id = %s", (value, row_id))


def seed() -> None:
    with get_connection() as connection:
        if connection.execute(
            "SELECT 1 FROM maintenance.jobs WHERE tenant_id = %s AND title LIKE %s", (TENANT, f"{MARKER}%")
        ).fetchone():
            print("already seeded")
            return
        demo = connection.execute("SELECT id FROM core.users WHERE tenant_id = %s AND email = %s", (TENANT, DEMO_EMAIL)).fetchone()
        if demo is None:
            raise RuntimeError("demo user not found — run scripts.seed_dev first")
        actor = demo[0]
        people = active_employees(connection, TENANT)
        if not people:
            raise RuntimeError("no active HR employee — run the HR seed first")
        machines = connection.execute(
            """
            SELECT DISTINCT e.id, e.name FROM maintenance.equipment e
            JOIN maintenance.equipment_views v ON v.equipment_id = e.id
            WHERE e.tenant_id = %s AND e.archived_at IS NULL
            ORDER BY e.name LIMIT 2
            """,
            (TENANT,),
        ).fetchall()
        if not machines:
            raise RuntimeError("no machine with a photo map — run scripts.seed_maintenance first")

        jobs = JobService(connection)
        today = datetime.date.today()
        for machine_index, (machine_id, machine_name) in enumerate(machines):
            points = [row[0] for row in connection.execute(
                """
                SELECT cp.id FROM maintenance.checkpoints cp JOIN maintenance.equipment_views v ON v.id = cp.view_id
                WHERE v.equipment_id = %s AND cp.archived_at IS NULL ORDER BY v.sort_order, cp.sort_order, cp.id
                """,
                (machine_id,),
            ).fetchall()]
            for months_ago in range(MONTHS, 0, -1):
                due = (today.replace(day=1) - datetime.timedelta(days=30 * months_ago)).replace(day=10 + machine_index)
                job_id = _check(jobs.create_job(
                    tenant_id=TENANT, actor_id=actor, equipment_id=machine_id, title=f"{MARKER} — ronde mensuelle",
                    description=None, kind="preventive", priority="normal", due_date=due, stops_machine=False,
                    checkpoint_ids=points, tasks=[], chef_user_id=actor,
                ), "create preventive")
                checks = connection.execute(
                    "SELECT id, action FROM maintenance.job_checks WHERE job_id = %s ORDER BY sort_order, id", (job_id,)
                ).fetchall()
                done_at = datetime.datetime.combine(due, datetime.time(9, 0), tzinfo=UTC)
                for index, (check_id, action) in enumerate(checks):
                    started = done_at + datetime.timedelta(minutes=12 * index)
                    outcome = "issue" if (months_ago == 2 and index == 0) else "ok"
                    _check(jobs.record_entry(
                        tenant_id=TENANT, actor_id=actor, job_id=job_id, check_id=check_id,
                        performer_employee_id=people[index % len(people)]["id"], outcome=outcome,
                        note="bruit anormal" if outcome == "issue" else None,
                        measured_value=(62 + 2 * (MONTHS - months_ago) + machine_index) if action == "measure" else None,
                        started_at=started, finished_at=started + datetime.timedelta(minutes=8 + index),
                        manual_minutes=None, photo=None, actor_can_plan=True, now=started + datetime.timedelta(minutes=8 + index),
                    ), "record entry")
                _check(jobs.submit(tenant_id=TENANT, actor_id=actor, job_id=job_id, actor_can_plan=True), "submit")
                _check(jobs.review(tenant_id=TENANT, actor_id=actor, job_id=job_id, verdicts=[(c[0], "accepted", None) for c in checks]), "review")
                _check(jobs.close(tenant_id=TENANT, actor_id=actor, job_id=job_id), "close")
                closed_at = done_at + datetime.timedelta(hours=6 + 30 * (months_ago == 3))
                _set(connection, "jobs", job_id, created_at=done_at - datetime.timedelta(days=5), started_at=done_at,
                     submitted_at=done_at + datetime.timedelta(hours=2), closed_at=closed_at)
            print(f"{machine_name}: {MONTHS} closed preventive rounds")

            # A breakdown two months ago: down, maintenance while repaired, back to operational.
            # Only from operational: the workflow seed may have left a machine held by an open job.
            current = connection.execute("SELECT status FROM maintenance.equipment WHERE id = %s", (machine_id,)).fetchone()[0]
            if current != "operational":
                print(f"{machine_name}: status is {current}, breakdown story skipped")
                continue
            equipment = EquipmentService(connection)
            broke = datetime.datetime.combine(today - datetime.timedelta(days=58 + machine_index), datetime.time(7, 40), tzinfo=UTC)
            for status in ("down", "maintenance", "operational"):
                _check(equipment.transition_status(tenant_id=TENANT, actor_id=actor, equipment_id=machine_id, new_status=status), status)
            audit_rows = connection.execute(
                "SELECT id FROM core.audit_log WHERE entity_id = %s AND action = 'equipment.status_changed' ORDER BY occurred_at DESC, id DESC LIMIT 3",
                (machine_id,),
            ).fetchall()
            for (audit_id,), offset in zip(reversed(audit_rows), (0, 45, 330)):
                connection.execute(
                    "UPDATE core.audit_log SET occurred_at = %s WHERE id = %s", (broke + datetime.timedelta(minutes=offset), audit_id)
                )
            corrective = _check(jobs.create_job(
                tenant_id=TENANT, actor_id=actor, equipment_id=machine_id, title=f"{MARKER} — panne vis principale",
                description="Bruit puis arrêt de la vis", kind="corrective", priority="urgent", due_date=broke.date(),
                stops_machine=False, checkpoint_ids=points[:1], tasks=[{"label": "Remplacer le roulement", "action": "replace"}],
                chef_user_id=actor,
            ), "create corrective")
            checks = [row[0] for row in connection.execute(
                "SELECT id FROM maintenance.job_checks WHERE job_id = %s ORDER BY sort_order, id", (corrective,)
            ).fetchall()]
            repair = broke + datetime.timedelta(minutes=60)
            for check_id in checks:
                _check(jobs.record_entry(
                    tenant_id=TENANT, actor_id=actor, job_id=corrective, check_id=check_id,
                    performer_employee_id=people[0]["id"], outcome="ok", note=None, measured_value=None,
                    started_at=repair, finished_at=repair + datetime.timedelta(minutes=50), manual_minutes=None, photo=None,
                    actor_can_plan=True, now=repair + datetime.timedelta(minutes=50),
                ), "record corrective")
            _check(jobs.submit(tenant_id=TENANT, actor_id=actor, job_id=corrective, actor_can_plan=True), "submit corrective")
            _check(jobs.review(
                tenant_id=TENANT, actor_id=actor, job_id=corrective,
                verdicts=[(checks[0], "rejected", "serrage à refaire")] + [(c, "accepted", None) for c in checks[1:]],
            ), "review corrective")
            _check(jobs.record_entry(
                tenant_id=TENANT, actor_id=actor, job_id=corrective, check_id=checks[0],
                performer_employee_id=people[-1]["id"], outcome="ok", note="resserré", measured_value=None,
                started_at=repair + datetime.timedelta(hours=2), finished_at=repair + datetime.timedelta(hours=2, minutes=15),
                manual_minutes=None, photo=None, actor_can_plan=True, now=repair + datetime.timedelta(hours=2, minutes=15),
            ), "redo corrective")
            _check(jobs.submit(tenant_id=TENANT, actor_id=actor, job_id=corrective, actor_can_plan=True), "resubmit")
            _check(jobs.review(tenant_id=TENANT, actor_id=actor, job_id=corrective, verdicts=[(checks[0], "accepted", None)]), "accept")
            _check(jobs.close(tenant_id=TENANT, actor_id=actor, job_id=corrective), "close corrective")
            _set(connection, "jobs", corrective, created_at=broke, started_at=repair, closed_at=broke + datetime.timedelta(hours=6))
            print(f"{machine_name}: one breakdown with a sent-back point and its status changes")
        connection.commit()


if __name__ == "__main__":
    seed()
```

If `record_entry` refuses a `started_at` far in the past or a performer the job's team does not hold, read the refusal it raises and adjust the arguments (the refusal codes are in `job_service.py`); keep the backdating in `_set`.

- [ ] **Step 2: Run it on the dev DB**

Run: `.venv/Scripts/python -m scripts.seed_maintenance && .venv/Scripts/python -m scripts.seed_maintenance_history`
Expected: two lines per machine, no traceback. Running it a second time prints `already seeded`.

- [ ] **Step 3: Check the API answers with data**

Run (backend running, demo token in `$TOKEN`): `curl -s -H "Authorization: Bearer $TOKEN" "http://localhost:8000/maintenance/history/indicators" | PYTHONUTF8=1 .venv/Scripts/python -m json.tool | head -60`
Expected: the two demo machines with non-zero `maintenance.immobilised_minutes` and `preventive.due`.

- [ ] **Step 4: Commit**

```bash
git add backend/scripts/seed_maintenance_history.py
git commit -m "chore(maintenance): dev seed for the history screens"
```

---

### Task 11: Icons and illustrations

**Files:**
- Create: `frontend/src/assets/icons/maintenance/{history,status-change,measure,checkpoint,immobilisation,mtbf,mttr}.svg`
- Create: `frontend/src/assets/illustrations/maintenance/{history-empty,checkpoint-never,no-breakdown}.svg`

**Interfaces:**
- Produces: SVGs imported as React components with `?react` (icons through `outlineIcon()` from `components/patterns/outlineIcon.tsx` for stroke weight). Consumed by Tasks 14–19.

Follow `.claude/skills/svg-asset-rules/SKILL.md`: icons 64×64, `stroke="currentColor"`, 3 px round stroke; illustrations 240×200 with the same animation vocabulary as `illustrations/empty-states/empty-all-clear.svg`, each with its own class prefix (inline SVG `<style>` is global) and a `prefers-reduced-motion` block.

- [ ] **Step 1: Write the seven icons**

`history.svg`
```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64"
fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
<path d="M14 10h30a6 6 0 0 1 6 6v38H20a6 6 0 0 1-6-6Z"/><path d="M14 48a6 6 0 0 1 6-6h30"/><circle cx="32" cy="24" r="8"/><path d="M32 20v4l3 2"/>
</svg>
```

`status-change.svg`
```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64"
fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
<path d="M12 22h36l-8-8"/><path d="M52 42H16l8 8"/>
</svg>
```

`measure.svg`
```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64"
fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
<path d="M10 46a22 22 0 0 1 44 0"/><path d="m32 46 11-14"/><circle cx="32" cy="46" r="3"/><path d="M15 46h4M45 46h4M32 24v4M19 33l3 2M45 33l-3 2"/>
</svg>
```

`checkpoint.svg`
```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64"
fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
<path d="M32 58S16 43 16 30a16 16 0 0 1 32 0c0 13-16 28-16 28Z"/><path d="m25 30 5 5 9-10"/>
</svg>
```

`immobilisation.svg`
```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64"
fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
<rect x="10" y="18" width="44" height="34" rx="4"/><path d="M27 28v14M37 28v14"/><path d="M18 18v-8h10v8"/>
</svg>
```

`mtbf.svg`
```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64"
fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
<path d="m16 10-5 12h8l-5 12"/><path d="m50 10-5 12h8l-5 12"/><path d="M14 48h36"/><path d="m19 43-5 5 5 5M45 43l5 5-5 5"/>
</svg>
```

`mttr.svg`
```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64"
fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
<circle cx="32" cy="37" r="19"/><path d="M27 10h10M32 10v8M32 37l8-8M47 20l4-4"/>
</svg>
```

- [ ] **Step 2: Write the three illustrations**

`history-empty.svg` (open logbook: machine on the left page, a timeline with a gold live dot on the right)
```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 240 200" fill="none" stroke-linecap="round" stroke-linejoin="round">
<style>
  .mhe-float{animation:mheFloat 4s ease-in-out infinite}
  .mhe-halo{transform-box:fill-box;transform-origin:center;animation:mheHalo 4s ease-in-out infinite}
  .mhe-ripple{transform-box:fill-box;transform-origin:center;animation:mheRipple 3s ease-out infinite}
  .mhe-star{transform-box:fill-box;transform-origin:center;animation:mheTwinkle 2.6s ease-in-out infinite}
  .mhe-star.b{animation-delay:.9s}
  .mhe-star.c{animation-delay:1.7s}
  @keyframes mheFloat{0%,100%{transform:translateY(0)}50%{transform:translateY(-5px)}}
  @keyframes mheHalo{0%,100%{transform:scale(1);opacity:.06}50%{transform:scale(1.06);opacity:.1}}
  @keyframes mheRipple{0%{transform:scale(1);opacity:.55}80%,100%{transform:scale(2);opacity:0}}
  @keyframes mheTwinkle{0%,100%{transform:scale(.4);opacity:.15}50%{transform:scale(1);opacity:1}}
  @media(prefers-reduced-motion:reduce){
    .mhe-float,.mhe-halo,.mhe-ripple,.mhe-star{animation:none}
    .mhe-ripple{opacity:0}
    .mhe-star{opacity:.7;transform:scale(.8)}
  }
</style>
<circle class="mhe-halo" cx="120" cy="100" r="76" fill="#123B6D" opacity=".06"/>
<ellipse cx="120" cy="172" rx="52" ry="5" fill="#123B6D" opacity=".08"/>
<g class="mhe-float">
  <path d="M120 58c-14-8-34-10-52-6v96c18-4 38-2 52 6Z" fill="#FFFFFF" stroke="#123B6D" stroke-width="4"/>
  <path d="M120 58c14-8 34-10 52-6v96c-18-4-38-2-52 6Z" fill="#FFFFFF" stroke="#123B6D" stroke-width="4"/>
  <rect x="80" y="84" width="28" height="22" rx="3" stroke="#123B6D" stroke-width="3"/>
  <path d="M86 84v-7h7v7M95 92h8M95 98h8" stroke="#123B6D" stroke-width="3"/>
  <path d="M80 118h28M80 128h18" stroke="#C9D6E4" stroke-width="4"/>
  <path d="M140 74v66" stroke="#C9D6E4" stroke-width="3"/>
  <circle cx="140" cy="78" r="6" fill="#F5B51B"/>
  <circle class="mhe-ripple" cx="140" cy="78" r="6" stroke="#F5A900" stroke-width="2"/>
  <path d="M152 78h12" stroke="#123B6D" stroke-width="4"/>
  <circle cx="140" cy="104" r="5" fill="#FFFFFF" stroke="#123B6D" stroke-width="3"/><path d="M152 104h10" stroke="#C9D6E4" stroke-width="4"/>
  <circle cx="140" cy="128" r="5" fill="#FFFFFF" stroke="#123B6D" stroke-width="3"/><path d="M152 128h14" stroke="#C9D6E4" stroke-width="4"/>
</g>
<g transform="translate(48 60)"><path class="mhe-star" d="M0-7 1.8-1.8 7 0 1.8 1.8 0 7-1.8 1.8-7 0-1.8-1.8Z" fill="#F5A900"/></g>
<g transform="translate(194 70)"><path class="mhe-star b" d="M0-6 1.5-1.5 6 0 1.5 1.5 0 6-1.5 1.5-6 0-1.5-1.5Z" fill="#123B6D"/></g>
<g transform="translate(190 152)"><path class="mhe-star c" d="M0-5 1.2-1.2 5 0 1.2 1.2 0 5-1.2 1.2-5 0-1.2-1.2Z" fill="#F5A900"/></g>
</svg>
```

`checkpoint-never.svg` (a photo frame with a gold pin dropping in)
```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 240 200" fill="none" stroke-linecap="round" stroke-linejoin="round">
<style>
  .mcn-float{animation:mcnFloat 4s ease-in-out infinite}
  .mcn-halo{transform-box:fill-box;transform-origin:center;animation:mcnHalo 4s ease-in-out infinite}
  .mcn-ripple{transform-box:fill-box;transform-origin:center;animation:mcnRipple 3s ease-out infinite}
  .mcn-drop{animation:mcnDrop 3.2s cubic-bezier(.22,1,.36,1) infinite}
  .mcn-star{transform-box:fill-box;transform-origin:center;animation:mcnTwinkle 2.6s ease-in-out infinite}
  .mcn-star.b{animation-delay:.9s}
  @keyframes mcnFloat{0%,100%{transform:translateY(0)}50%{transform:translateY(-5px)}}
  @keyframes mcnHalo{0%,100%{transform:scale(1);opacity:.06}50%{transform:scale(1.06);opacity:.1}}
  @keyframes mcnRipple{0%{transform:scale(1);opacity:.55}80%,100%{transform:scale(2);opacity:0}}
  @keyframes mcnDrop{0%{transform:translateY(-14px);opacity:0}30%,100%{transform:translateY(0);opacity:1}}
  @keyframes mcnTwinkle{0%,100%{transform:scale(.4);opacity:.15}50%{transform:scale(1);opacity:1}}
  @media(prefers-reduced-motion:reduce){
    .mcn-float,.mcn-halo,.mcn-ripple,.mcn-drop,.mcn-star{animation:none}
    .mcn-ripple{opacity:0}
    .mcn-star{opacity:.7;transform:scale(.8)}
  }
</style>
<circle class="mcn-halo" cx="120" cy="100" r="76" fill="#123B6D" opacity=".06"/>
<ellipse cx="120" cy="170" rx="44" ry="5" fill="#123B6D" opacity=".08"/>
<g class="mcn-float">
  <rect x="62" y="56" width="116" height="86" rx="10" fill="#FFFFFF" stroke="#123B6D" stroke-width="4"/>
  <path d="M74 128l26-26 18 16 14-12 34 22" stroke="#C9D6E4" stroke-width="4"/>
  <rect x="84" y="74" width="40" height="30" rx="4" stroke="#123B6D" stroke-width="3"/>
  <path d="M92 74v-8h9v8M132 82h18M132 92h12" stroke="#123B6D" stroke-width="3"/>
  <g class="mcn-drop">
    <circle class="mcn-ripple" cx="152" cy="62" r="10" stroke="#F5A900" stroke-width="2"/>
    <path d="M152 78s-12-11-12-20a12 12 0 0 1 24 0c0 9-12 20-12 20Z" fill="#F5B51B" stroke="#071F43" stroke-width="2.5"/>
    <circle cx="152" cy="58" r="4" fill="#071F43"/>
  </g>
</g>
<g transform="translate(46 128)"><path class="mcn-star" d="M0-6 1.5-1.5 6 0 1.5 1.5 0 6-1.5 1.5-6 0-1.5-1.5Z" fill="#F5A900"/></g>
<g transform="translate(196 116)"><path class="mcn-star b" d="M0-5 1.2-1.2 5 0 1.2 1.2 0 5-1.2 1.2-5 0-1.2-1.2Z" fill="#123B6D"/></g>
</svg>
```

`no-breakdown.svg` (a machine with a green check halo)
```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 240 200" fill="none" stroke-linecap="round" stroke-linejoin="round">
<style>
  .mnb-float{animation:mnbFloat 4s ease-in-out infinite}
  .mnb-halo{transform-box:fill-box;transform-origin:center;animation:mnbHalo 4s ease-in-out infinite}
  .mnb-ripple{transform-box:fill-box;transform-origin:center;animation:mnbRipple 3s ease-out infinite}
  .mnb-check{stroke-dasharray:1;animation:mnbCheck 5s ease-in-out infinite}
  .mnb-star{transform-box:fill-box;transform-origin:center;animation:mnbTwinkle 2.6s ease-in-out infinite}
  .mnb-star.b{animation-delay:.9s}
  .mnb-star.c{animation-delay:1.7s}
  @keyframes mnbFloat{0%,100%{transform:translateY(0)}50%{transform:translateY(-5px)}}
  @keyframes mnbHalo{0%,100%{transform:scale(1);opacity:.06}50%{transform:scale(1.06);opacity:.1}}
  @keyframes mnbRipple{0%{transform:scale(1);opacity:.5}80%,100%{transform:scale(1.9);opacity:0}}
  @keyframes mnbCheck{0%{stroke-dashoffset:1}20%,84%{stroke-dashoffset:0}100%{stroke-dashoffset:0}}
  @keyframes mnbTwinkle{0%,100%{transform:scale(.4);opacity:.15}50%{transform:scale(1);opacity:1}}
  @media(prefers-reduced-motion:reduce){
    .mnb-float,.mnb-halo,.mnb-ripple,.mnb-check,.mnb-star{animation:none}
    .mnb-check{stroke-dashoffset:0}
    .mnb-ripple{opacity:0}
    .mnb-star{opacity:.7;transform:scale(.8)}
  }
</style>
<circle class="mnb-halo" cx="120" cy="100" r="76" fill="#20A464" opacity=".06"/>
<ellipse cx="120" cy="170" rx="50" ry="5" fill="#123B6D" opacity=".08"/>
<g class="mnb-float">
  <rect x="64" y="80" width="92" height="68" rx="8" fill="#FFFFFF" stroke="#123B6D" stroke-width="4"/>
  <path d="M80 80V64h20v16M116 100h26M116 116h20M80 100h22v24H80Z" stroke="#123B6D" stroke-width="4"/>
  <circle cx="164" cy="74" r="24" fill="#FFFFFF" stroke="#20A464" stroke-width="4"/>
  <circle class="mnb-ripple" cx="164" cy="74" r="24" stroke="#20A464" stroke-width="2"/>
  <path class="mnb-check" pathLength="1" d="m153 74 8 8 14-15" stroke="#20A464" stroke-width="5"/>
</g>
<g transform="translate(52 66)"><path class="mnb-star" d="M0-7 1.8-1.8 7 0 1.8 1.8 0 7-1.8 1.8-7 0-1.8-1.8Z" fill="#F5A900"/></g>
<g transform="translate(200 128)"><path class="mnb-star b" d="M0-6 1.5-1.5 6 0 1.5 1.5 0 6-1.5 1.5-6 0-1.5-1.5Z" fill="#F5A900"/></g>
<g transform="translate(44 146)"><path class="mnb-star c" d="M0-5 1.2-1.2 5 0 1.2 1.2 0 5-1.2 1.2-5 0-1.2-1.2Z" fill="#123B6D"/></g>
</svg>
```

- [ ] **Step 3: Look at them**

Run from the repo root (Git Bash), one per file:
`"/c/Program Files/Google/Chrome/Application/chrome.exe" --headless=new --disable-gpu --user-data-dir="<scratchpad>/chrome-svg" --window-size=480,400 --screenshot="<scratchpad>/history-empty.png" "file:///D:/mahmoud%20repo/Sonalim_ERP/frontend/src/assets/illustrations/maintenance/history-empty.svg"`
Expected: each illustration draws in navy and gold on white, nothing clipped; icons draw as single-weight outlines.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/assets/icons/maintenance frontend/src/assets/illustrations/maintenance
git commit -m "feat(maintenance-ui): history icons and animated empty-state illustrations"
```

---

### Task 12: History client — types, queries, period and formatting helpers, strings

**Files:**
- Create: `frontend/src/features/maintenance/history/api.ts`
- Create: `frontend/src/features/maintenance/history/historyPeriod.ts`
- Create: `frontend/src/features/maintenance/history/historyFormat.ts`
- Test: `frontend/src/features/maintenance/history/historyPeriod.test.ts`, `frontend/src/features/maintenance/history/historyFormat.test.ts`
- Modify: `frontend/src/lib/i18n.en.ts`, `frontend/src/lib/i18n.fr.ts`

**Interfaces:**
- Produces (consumed by Tasks 14–19):
  - types `Period`, `ProductionBlock`, `MaintenanceBlock`, `MachineSummary`, `MachineIndicators`, `IndicatorsResponse`, `JournalStatus`, `JournalKind`, `JournalRow`, `JournalResponse`, `ProductionStopItem`, `TimelineItem`, `CheckpointSummary`, `EquipmentHistory`, `PointEntry`, `PointAttempt`, `PointCheck`, `CheckpointHistory`
  - hooks `useHistoryIndicators(token, period)`, `useHistoryJournal(token, filters: JournalFilters)`, `useEquipmentHistory(token, equipmentId, period)`, `useCheckpointHistory(token, checkpointId | null)`; `exportJournalWorkbook(token, filters & { lang }) => Promise<Blob>`
  - `PERIOD_PRESETS`, `DEFAULT_PRESET`, `PeriodPreset`, `isoDay`, `presetRange`, `matchingPreset`, `periodFromParams`, `usePeriod()` → `{ period, preset, isDefault, setRange, setPreset, reset }`
  - `fill`, `minutesOrDash`, `monthKey`, `largestIndex`, `sparklinePoints`, `initials`
  - every `maintenance.history.*` translation key used by later tasks

- [ ] **Step 1: Write the failing tests**

`historyPeriod.test.ts`
```ts
import { describe, expect, it } from "vitest";
import { matchingPreset, periodFromParams, presetRange } from "./historyPeriod";

const TODAY = new Date(2026, 9, 2); // 2 Oct 2026, local time

describe("presetRange", () => {
  it("covers the month, last month, three months and the year up to today", () => {
    expect(presetRange("month", TODAY)).toEqual({ from: "2026-10-01", to: "2026-10-02" });
    expect(presetRange("lastMonth", TODAY)).toEqual({ from: "2026-09-01", to: "2026-09-30" });
    expect(presetRange("threeMonths", TODAY)).toEqual({ from: "2026-08-01", to: "2026-10-02" });
    expect(presetRange("year", TODAY)).toEqual({ from: "2026-01-01", to: "2026-10-02" });
  });

  it("crosses the year in January", () => {
    expect(presetRange("lastMonth", new Date(2026, 0, 15))).toEqual({ from: "2025-12-01", to: "2025-12-31" });
  });
});

describe("matchingPreset and periodFromParams", () => {
  it("recognises a preset and treats anything else as custom", () => {
    expect(matchingPreset({ from: "2026-09-01", to: "2026-09-30" }, TODAY)).toBe("lastMonth");
    expect(matchingPreset({ from: "2026-09-03", to: "2026-09-30" }, TODAY)).toBeNull();
  });

  it("falls back to this year for a missing, malformed or reversed period", () => {
    const year = { from: "2026-01-01", to: "2026-10-02" };
    expect(periodFromParams(new URLSearchParams(""), TODAY)).toEqual(year);
    expect(periodFromParams(new URLSearchParams("from=2026-9-1&to=2026-09-30"), TODAY)).toEqual(year);
    expect(periodFromParams(new URLSearchParams("from=2026-09-30&to=2026-09-01"), TODAY)).toEqual(year);
    expect(periodFromParams(new URLSearchParams("from=2026-09-01&to=2026-09-30"), TODAY)).toEqual({ from: "2026-09-01", to: "2026-09-30" });
  });
});
```

`historyFormat.test.ts`
```ts
import { describe, expect, it } from "vitest";
import { fill, initials, largestIndex, minutesOrDash, monthKey, sparklinePoints } from "./historyFormat";

describe("historyFormat", () => {
  it("fills every placeholder and leaves unknown ones", () => {
    expect(fill("{ok} OK · {issue} anomalie(s) · {x}", { ok: 3, issue: 1 })).toBe("3 OK · 1 anomalie(s) · {x}");
  });

  it("shows a dash for a figure that cannot be computed", () => {
    expect(minutesOrDash(null)).toBe("—");
    expect(minutesOrDash(57)).toBe("57 min");
    expect(minutesOrDash(400)).toBe("6 h 40 min");
  });

  it("groups by month and finds the largest bar", () => {
    expect(monthKey("2026-09-28T09:40:00+00:00")).toBe("2026-09");
    expect(largestIndex([290, 80, 290, 30])).toBe(0);
    expect(largestIndex([])).toBe(-1);
  });

  it("draws a sparkline oldest left and a flat series in the middle", () => {
    expect(sparklinePoints([1, 3], 20, 10, 0)).toEqual([{ x: 0, y: 10 }, { x: 20, y: 0 }]);
    expect(sparklinePoints([5, 5], 20, 10, 0).map((p) => p.y)).toEqual([5, 5]);
  });

  it("makes initials from a full name", () => {
    expect(initials("Awa Diarra")).toBe("AD");
    expect(initials("Moussa")).toBe("M");
  });
});
```

- [ ] **Step 2: Run to verify they fail**

Run (in `frontend/`): `npx vitest run src/features/maintenance/history`
Expected: FAIL — `Failed to resolve import "./historyPeriod"`.

- [ ] **Step 3: Write `historyPeriod.ts`**

```ts
import { useSearchParams } from "react-router-dom";

export interface Period {
  from: string;
  to: string;
}

export type PeriodPreset = "month" | "lastMonth" | "threeMonths" | "year";
export const PERIOD_PRESETS: readonly PeriodPreset[] = ["month", "lastMonth", "threeMonths", "year"];
export const DEFAULT_PRESET: PeriodPreset = "year";

/** A calendar day as YYYY-MM-DD, in local time (the plant runs on UTC, so they agree there). */
export function isoDay(date: Date): string {
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}`;
}

export function presetRange(preset: PeriodPreset, today: Date = new Date()): Period {
  const year = today.getFullYear();
  const month = today.getMonth();
  switch (preset) {
    case "month":
      return { from: isoDay(new Date(year, month, 1)), to: isoDay(today) };
    case "lastMonth":
      return { from: isoDay(new Date(year, month - 1, 1)), to: isoDay(new Date(year, month, 0)) };
    case "threeMonths":
      return { from: isoDay(new Date(year, month - 2, 1)), to: isoDay(today) };
    case "year":
      return { from: isoDay(new Date(year, 0, 1)), to: isoDay(today) };
  }
}

export function matchingPreset(period: Period, today: Date = new Date()): PeriodPreset | null {
  return (
    PERIOD_PRESETS.find((preset) => {
      const range = presetRange(preset, today);
      return range.from === period.from && range.to === period.to;
    }) ?? null
  );
}

const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/;

/** `?from=&to=`; missing, malformed or reversed falls back to the default preset. */
export function periodFromParams(params: URLSearchParams, today: Date = new Date()): Period {
  const from = params.get("from");
  const to = params.get("to");
  if (from && to && ISO_DAY.test(from) && ISO_DAY.test(to) && from <= to) return { from, to };
  return presetRange(DEFAULT_PRESET, today);
}

/** The period of a history screen, kept in the URL so a link, a reload or the print sheet opens on the same dates. */
export function usePeriod() {
  const [searchParams, setSearchParams] = useSearchParams();
  const period = periodFromParams(searchParams);
  const preset = matchingPreset(period);

  function setRange(range: Period) {
    setSearchParams(
      (current) => {
        const next = new URLSearchParams(current);
        next.set("from", range.from);
        next.set("to", range.to);
        return next;
      },
      { replace: true },
    );
  }

  function reset() {
    setSearchParams(
      (current) => {
        const next = new URLSearchParams(current);
        next.delete("from");
        next.delete("to");
        return next;
      },
      { replace: true },
    );
  }

  return {
    period,
    preset,
    isDefault: preset === DEFAULT_PRESET,
    setRange,
    setPreset: (next: PeriodPreset) => setRange(presetRange(next)),
    reset,
  };
}
```

- [ ] **Step 4: Write `historyFormat.ts`**

```ts
import { formatDuration } from "../../../lib/units";

/** Replaces every `{name}` of a translated string; an unknown placeholder is left as it is. */
export function fill(text: string, values: Record<string, string | number>): string {
  return text.replace(/\{(\w+)\}/g, (match, name: string) => (name in values ? String(values[name]) : match));
}

/** A duration in minutes, or "—" for a figure that cannot be computed (e.g. MTBF with no breakdown). */
export function minutesOrDash(minutes: number | null | undefined): string {
  return minutes === null || minutes === undefined ? "—" : formatDuration(minutes);
}

/** "2026-09-28T09:40:00+00:00" -> "2026-09": the timeline's month group. */
export function monthKey(iso: string): string {
  return iso.slice(0, 7);
}

/** Index of the largest value (the first on a tie), -1 when empty: the bar that gets the gold highlight. */
export function largestIndex(values: number[]): number {
  let best = -1;
  values.forEach((value, index) => {
    if (best === -1 || value > values[best]) best = index;
  });
  return best;
}

/** Points of a sparkline in a width x height box, oldest on the left; a flat series sits in the middle. */
export function sparklinePoints(values: number[], width: number, height: number, padding = 2): { x: number; y: number }[] {
  if (values.length === 0) return [];
  const min = Math.min(...values);
  const span = Math.max(...values) - min;
  const step = values.length > 1 ? (width - 2 * padding) / (values.length - 1) : 0;
  return values.map((value, index) => ({
    x: padding + index * step,
    y: span === 0 ? height / 2 : padding + (1 - (value - min) / span) * (height - 2 * padding),
  }));
}

export function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .map((part) => part[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
}
```

- [ ] **Step 5: Write `api.ts`**

```ts
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { apiErrorFromResponse, apiFetch, BASE_URL, networkError } from "../../../lib/api";
import type { CheckAction, EquipmentStatus, JobListItem, JobStatus, Outcome, ProductionStage } from "../api";
import type { Period } from "./historyPeriod";

export interface ProductionBlock {
  stops: number;
  stop_minutes: number;
  stops_by_type: { type: string | null; count: number; minutes: number }[];
  breakdowns: number;
  breakdown_minutes: number;
  breakdowns_by_system: { classification: string | null; count: number; minutes: number }[];
  running_minutes: number;
  mtbf_minutes: number | null;
  mttr_minutes: number | null;
}

export interface MaintenanceBlock {
  breakdowns: number;
  preventive: { due: number; closed: number; closed_on_time: number; overdue: number };
  immobilised_minutes: number;
  immobilisations: number;
  mean_immobilisation_minutes: number | null;
  calendar_minutes: number;
  calendar_mtbf_minutes: number | null;
  technician_seconds: number;
  parts: { issued_lines: number; purchase_lines: number };
  /** null when the user may not see costs (warehouse.view_valuation) or the warehouse module is absent. */
  parts_cost: number | null;
  parts_unvalued_quantity: number | null;
  status_changes: number;
}

export interface MachineSummary {
  equipment_id: string;
  code: string;
  name: string;
  work_center_id: string;
  production_stage: ProductionStage | null;
  status: EquipmentStatus;
  archived_at: string | null;
  /** The first view of the machine's plan that has a photo, for its thumbnail. */
  photo_view_id: string | null;
  photo_version: string | null;
}

export interface MachineIndicators extends MachineSummary {
  /** null when production figures are not available. */
  production: ProductionBlock | null;
  maintenance: MaintenanceBlock;
}

export interface IndicatorsResponse {
  from: string;
  to: string;
  costs_visible: boolean;
  production_available: boolean;
  machines: MachineIndicators[];
  unattributed_stops: { count: number; minutes: number } | null;
}

export type JournalStatus = "closed" | "cancelled" | "all";
export type JournalKind = JobListItem["kind"];

export interface JournalRow {
  job_id: string;
  number: string;
  equipment_id: string;
  equipment_code: string;
  equipment_name: string;
  kind: JournalKind;
  priority: JobListItem["priority"];
  title: string;
  status: JobStatus;
  /** Close (or cancel) date; null for a job still open (logbook only). */
  date: string | null;
  due_date: string;
  created_at: string;
  started_at: string | null;
  closed_on_time: boolean | null;
  cancel_reason: string | null;
  chef_name: string | null;
  performers: { employee_id: string; name: string }[];
  technician_seconds: number;
  checks_total: number;
  checks_done: number;
  outcomes: { ok: number; issue: number; not_done: number; pending: number };
  parts: { issued_lines: number; purchase_lines: number };
  parts_cost: number | null;
  machine_stopped: boolean;
  machine_restarted: boolean;
}

export interface JournalResponse {
  from: string;
  to: string;
  costs_visible: boolean;
  rows: JournalRow[];
}

export interface ProductionStopItem {
  started_at: string;
  ended_at: string;
  minutes: number;
  downtime_type: string | null;
  classification: string | null;
  motif: string | null;
  note: string | null;
  corrective_action: string | null;
  report_date: string;
  team: string | null;
  shift_report_id: string;
}

export type TimelineItem =
  | { kind: "job"; at: string; job: JournalRow }
  | { kind: "production_stop"; at: string; stop: ProductionStopItem }
  | { kind: "status_change"; at: string; from_status: EquipmentStatus; to_status: EquipmentStatus; actor_name: string | null };

export interface CheckpointSummary {
  checkpoint_id: string;
  view_id: string;
  view_label: string;
  label: string;
  action: CheckAction;
  measure_unit: string | null;
  sort_order: number;
  archived: boolean;
  checks_count: number;
  issues_count: number;
  last_checked_at: string | null;
  last_outcome: Outcome | null;
  last_measured_value: number | null;
  recent_measures: { at: string; value: number }[];
}

export interface EquipmentHistory {
  equipment: MachineSummary;
  indicators: { production: ProductionBlock | null; maintenance: MaintenanceBlock };
  costs_visible: boolean;
  production_available: boolean;
  timeline: TimelineItem[];
  checkpoints: CheckpointSummary[];
}

export interface PointEntry {
  entry_id: string;
  performer_name: string;
  recorded_by_name: string;
  started_at: string;
  finished_at: string;
  duration_seconds: number;
  duration_source: "timer" | "manual";
  outcome: Outcome;
  note: string | null;
  measured_value: number | null;
  has_photo: boolean;
}

export interface PointAttempt {
  attempt: number;
  entries: PointEntry[];
  review: { verdict: "accepted" | "rejected"; reason: string | null; reviewer_name: string; created_at: string } | null;
}

export interface PointCheck {
  job_id: string;
  job_number: string;
  job_kind: JournalKind;
  job_status: JobStatus;
  check_id: string;
  attempts: PointAttempt[];
}

export interface CheckpointHistory {
  checkpoint: {
    id: string;
    label: string;
    action: CheckAction;
    instructions: string | null;
    measure_unit: string | null;
    requires_photo: boolean;
    view_id: string;
    view_label: string;
    view_version: string | null;
    x_pct: number;
    y_pct: number;
    equipment_id: string;
    equipment_name: string;
    archived_at: string | null;
  };
  summary: { checks_count: number; issues_count: number; last_checked_at: string | null };
  measures: { at: string; value: number; outcome: Outcome; job_number: string }[];
  checks: PointCheck[];
}

export interface JournalFilters extends Period {
  equipment_id?: string;
  kind?: JournalKind;
  status: JournalStatus;
}

function query(params: Record<string, string | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) if (value) search.set(key, value);
  return search.toString();
}

// Every key starts with ["maintenance"], so a maintenance write (which invalidates that prefix) refreshes the history too.
export const historyIndicatorsKey = (period: Period) => ["maintenance", "history", "indicators", period.from, period.to] as const;
export const historyJournalKey = (filters: JournalFilters) => ["maintenance", "history", "journal", filters] as const;
export const equipmentHistoryKey = (equipmentId: string, period: Period) =>
  ["maintenance", "history", "equipment", equipmentId, period.from, period.to] as const;
export const checkpointHistoryKey = (checkpointId: string) => ["maintenance", "history", "checkpoint", checkpointId] as const;

export function useHistoryIndicators(token: string, period: Period) {
  return useQuery({
    queryKey: historyIndicatorsKey(period),
    queryFn: () => apiFetch<IndicatorsResponse>(`/maintenance/history/indicators?${query({ ...period })}`, { token }),
    enabled: !!token,
    placeholderData: keepPreviousData,
  });
}

export function useHistoryJournal(token: string, filters: JournalFilters) {
  return useQuery({
    queryKey: historyJournalKey(filters),
    queryFn: () => apiFetch<JournalResponse>(`/maintenance/history/journal?${query({ ...filters })}`, { token }),
    enabled: !!token,
    placeholderData: keepPreviousData,
  });
}

export function useEquipmentHistory(token: string, equipmentId: string, period: Period) {
  return useQuery({
    queryKey: equipmentHistoryKey(equipmentId, period),
    queryFn: () => apiFetch<EquipmentHistory>(`/maintenance/equipment/${equipmentId}/history?${query({ ...period })}`, { token }),
    enabled: !!token && !!equipmentId,
    placeholderData: keepPreviousData,
  });
}

export function useCheckpointHistory(token: string, checkpointId: string | null) {
  return useQuery({
    queryKey: checkpointHistoryKey(checkpointId ?? ""),
    queryFn: () => apiFetch<CheckpointHistory>(`/maintenance/checkpoints/${checkpointId}/history`, { token }),
    enabled: !!token && !!checkpointId,
  });
}

/** The journal as .xlsx (GET /maintenance/history/journal/export). Bypasses apiFetch, which always parses JSON. */
export async function exportJournalWorkbook(token: string, filters: JournalFilters & { lang: string }): Promise<Blob> {
  let response: Response;
  try {
    response = await fetch(`${BASE_URL}/maintenance/history/journal/export?${query({ ...filters })}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
  } catch {
    throw networkError();
  }
  if (!response.ok) throw await apiErrorFromResponse(response);
  return response.blob();
}
```

- [ ] **Step 5b: Add the strings** — in `i18n.en.ts` right after the `"maintenance.wizard.leave.confirm"` entry, and the French ones at the same place in `i18n.fr.ts` (the French file is typed against the English keys, so a missing key fails `tsc`):

| key | en | fr |
|---|---|---|
| `maintenance.tabs.history` | History | Historique |
| `maintenance.equipment.history` | History | Historique |
| `maintenance.history.view.indicators` | Indicators | Indicateurs |
| `maintenance.history.view.journal` | Journal | Journal |
| `maintenance.history.period.month` | This month | Ce mois |
| `maintenance.history.period.lastMonth` | Last month | Mois dernier |
| `maintenance.history.period.threeMonths` | 3 months | 3 mois |
| `maintenance.history.period.year` | This year | Cette année |
| `maintenance.history.period.custom` | Custom | Personnalisée |
| `maintenance.history.machine.all` | All machines | Toutes les machines |
| `maintenance.history.machine.label` | Machine | Machine |
| `maintenance.history.loadError` | Could not load the history | Impossible de charger l'historique |
| `maintenance.history.production.title` | According to production | Selon la production |
| `maintenance.history.production.caption` | stops of validated shifts | arrêts des postes validés |
| `maintenance.history.production.unavailable` | Production figures are not available. | Les chiffres de production ne sont pas disponibles. |
| `maintenance.history.maintenance.title` | According to maintenance | Selon la maintenance |
| `maintenance.history.maintenance.caption` | interventions and machine status | interventions et états de la machine |
| `maintenance.history.kpi.breakdowns` | Breakdowns | Pannes |
| `maintenance.history.kpi.mtbf` | MTBF | MTBF |
| `maintenance.history.kpi.mtbfHint` | running time ÷ breakdowns | marche ÷ pannes |
| `maintenance.history.kpi.mttr` | MTTR | MTTR |
| `maintenance.history.kpi.mttrHint` | stop time ÷ breakdowns | arrêt ÷ pannes |
| `maintenance.history.kpi.allStops` | All stops | Tous arrêts |
| `maintenance.history.kpi.corrective` | corrective jobs | interventions correctives |
| `maintenance.history.kpi.immobilisation` | Immobilisation | Immobilisation |
| `maintenance.history.kpi.meanImmobilisation` | avg {value} | moy. {value} |
| `maintenance.history.kpi.betweenBreakdowns` | Between breakdowns | Entre pannes |
| `maintenance.history.kpi.calendar` | calendar time | calendaire |
| `maintenance.history.kpi.partsCost` | Parts cost | Coût pièces |
| `maintenance.history.kpi.unvalued` | {value} unvalued | {value} non valorisé |
| `maintenance.history.kpi.technician` | Technician time | Temps technicien |
| `maintenance.history.kpi.noBreakdown` | no breakdown | aucune panne |
| `maintenance.history.bySystem` | Breakdowns by system | Pannes par système |
| `maintenance.history.noBreakdown` | No breakdown in this period | Aucune panne sur la période |
| `maintenance.history.preventive.summary` | Preventive: {due} due · {closed} closed | Préventives : {due} prévues · {closed} clôturées |
| `maintenance.history.preventive.onTime` | {n} on time | {n} à l'heure |
| `maintenance.history.preventive.overdue` | {n} overdue | {n} en retard |
| `maintenance.history.preventive.none` | No preventive job due in this period | Aucune préventive prévue sur la période |
| `maintenance.history.stat.productionBreakdowns` | Breakdowns · production | Pannes · production |
| `maintenance.history.stat.maintenanceBreakdowns` | Breakdowns · maintenance | Pannes · maintenance |
| `maintenance.history.stat.immobilisation` | Immobilisation | Immobilisation |
| `maintenance.history.stat.partsCost` | Parts cost | Coût pièces |
| `maintenance.history.column.machine` | Machine | Machine |
| `maintenance.history.column.stopTime` | Stop time | Arrêt |
| `maintenance.history.column.preventive` | Preventive | Préventives |
| `maintenance.history.column.technician` | Technician | Technicien |
| `maintenance.history.unattributed` | {count} production stops name no machine ({minutes}): not attributed, so outside the per-machine totals. | {count} arrêts production sans machine ({minutes}) : non attribués, donc hors des totaux par machine. |
| `maintenance.history.indicators.empty.title` | No machine | Aucune machine |
| `maintenance.history.indicators.empty.description` | No machine had activity in this period. | Aucune machine n'a eu d'activité sur la période. |
| `maintenance.history.journal.status.closed` | Closed | Clôturées |
| `maintenance.history.journal.status.cancelled` | Cancelled | Annulées |
| `maintenance.history.journal.status.all` | All | Toutes |
| `maintenance.history.journal.kind.all` | All types | Tous types |
| `maintenance.history.journal.kind.preventive` | Preventive | Préventives |
| `maintenance.history.journal.kind.corrective` | Corrective | Correctives |
| `maintenance.history.journal.export` | Export to Excel | Exporter Excel |
| `maintenance.history.journal.exportError` | The export failed | L'export a échoué |
| `maintenance.history.journal.column.number` | No. | N° |
| `maintenance.history.journal.column.date` | Date | Date |
| `maintenance.history.journal.column.kind` | Type | Type |
| `maintenance.history.journal.column.title` | Intervention | Intervention |
| `maintenance.history.journal.column.performers` | Technicians | Techniciens |
| `maintenance.history.journal.column.time` | Time | Temps |
| `maintenance.history.journal.column.result` | Result | Résultat |
| `maintenance.history.journal.column.parts` | Parts | Pièces |
| `maintenance.history.journal.column.cost` | Cost | Coût |
| `maintenance.history.journal.result` | {ok} OK · {issue} issue(s) · {notDone} not done | {ok} OK · {issue} anomalie(s) · {notDone} non fait(s) |
| `maintenance.history.journal.empty.title` | Nothing in this period | Rien sur cette période |
| `maintenance.history.journal.empty.description` | No intervention was closed or cancelled in this period. | Aucune intervention clôturée ou annulée sur la période. |
| `maintenance.history.logbook.eyebrow` | Machine logbook | Carnet machine |
| `maintenance.history.logbook.back` | Back | Retour |
| `maintenance.history.logbook.print` | PDF sheet | Fiche PDF |
| `maintenance.history.logbook.photoCaption` | Plan photo | Photo du plan |
| `maintenance.history.logbook.summary` | {jobs} interventions · {stops} production stops | {jobs} interventions · {stops} arrêts production |
| `maintenance.history.logbook.notFound` | Machine not found | Machine introuvable |
| `maintenance.history.timeline.title` | Timeline | Fil chronologique |
| `maintenance.history.timeline.hint` | latest first | le plus récent en haut |
| `maintenance.history.timeline.filter.all` | All | Tout |
| `maintenance.history.timeline.filter.jobs` | Interventions | Interventions |
| `maintenance.history.timeline.filter.stops` | Production stops | Arrêts production |
| `maintenance.history.timeline.filter.status` | Status changes | Changements d'état |
| `maintenance.history.timeline.filter.issues` | Issues | Anomalies |
| `maintenance.history.timeline.live` | In progress | En cours |
| `maintenance.history.timeline.stop` | Production stop | Arrêt production |
| `maintenance.history.timeline.status` | Status: | État : |
| `maintenance.history.timeline.by` | by {name} | par {name} |
| `maintenance.history.timeline.machineStopped` | machine stopped | machine arrêtée |
| `maintenance.history.timeline.progress` | {done} / {total} points | {done} / {total} points |
| `maintenance.history.timeline.parts` | {n} part line(s) | {n} ligne(s) de pièces |
| `maintenance.history.timeline.shift` | Shift of {date} | Poste du {date} |
| `maintenance.history.timeline.correctiveAction` | Action: {value} | Action : {value} |
| `maintenance.history.timeline.onTime` | on time | à l'heure |
| `maintenance.history.timeline.late` | late | en retard |
| `maintenance.history.timeline.empty.title` | Nothing in this period | Rien sur cette période |
| `maintenance.history.timeline.empty.description` | No intervention, stop or status change for this machine in this period. | Aucune intervention, aucun arrêt ni changement d'état pour cette machine sur la période. |
| `maintenance.history.points.title` | Checkpoints | Points de contrôle |
| `maintenance.history.points.count` | {n} points | {n} points |
| `maintenance.history.points.never` | never checked | jamais contrôlé |
| `maintenance.history.points.issues` | {n} issue(s) | {n} anomalie(s) |
| `maintenance.history.points.show` | Show the checkpoints ({n}) | Voir les points ({n}) |
| `maintenance.history.points.hide` | Hide the checkpoints | Masquer les points |
| `maintenance.history.points.archived` | archived | archivé |
| `maintenance.history.points.none` | This machine has no checkpoint on its plan. | Cette machine n'a aucun point sur son plan. |
| `maintenance.history.point.eyebrow` | Checkpoint | Point de contrôle |
| `maintenance.history.point.checked` | Checked | Contrôlé |
| `maintenance.history.point.times` | {n} time(s) | {n} fois |
| `maintenance.history.point.issues` | Issues | Anomalies |
| `maintenance.history.point.last` | Last | Dernier |
| `maintenance.history.point.measures` | Measures ({unit}) | Mesures ({unit}) |
| `maintenance.history.point.noLimits` | no limit recorded | aucune limite enregistrée |
| `maintenance.history.point.checks` | Every check | Chaque contrôle |
| `maintenance.history.point.attempt` | attempt {n} | tentative {n} |
| `maintenance.history.point.notYet` | not checked yet | pas encore contrôlé |
| `maintenance.history.point.review` | Review: {reason} ({name}) | Revue : {reason} ({name}) |
| `maintenance.history.point.timer` | timer | chrono |
| `maintenance.history.point.manual` | entered by hand | saisie manuelle |
| `maintenance.history.point.empty.title` | This point has never been checked | Ce point n'a encore jamais été contrôlé |
| `maintenance.history.point.empty.description` | Its checks will appear here, attempt by attempt. | Ses contrôles apparaîtront ici, tentative par tentative. |
| `maintenance.history.print.title` | Machine history | Fiche historique machine |
| `maintenance.history.print.period` | Period: {from} → {to} | Période : {from} → {to} |
| `maintenance.history.print.printedOn` | Printed on {date} by {user} | Imprimé le {date} par {user} |
| `maintenance.history.print.jobs` | Interventions | Interventions |
| `maintenance.history.print.stops` | Production stops | Arrêts production |
| `maintenance.history.print.statusChanges` | Status changes | Changements d'état |
| `maintenance.history.print.points` | Checkpoints | Points de contrôle |
| `maintenance.history.print.none` | None in this period | Aucun sur la période |
| `maintenance.history.print.column.from` | From | De |
| `maintenance.history.print.column.to` | To | À |
| `maintenance.history.print.column.by` | By | Par |
| `maintenance.history.print.column.duration` | Duration | Durée |
| `maintenance.history.print.column.system` | System | Système |
| `maintenance.history.print.column.reason` | Reason | Motif |
| `maintenance.history.print.column.note` | Note | Note |
| `maintenance.history.print.column.lastMeasure` | Last measure | Dernière mesure |

Each row becomes one line, e.g. `  "maintenance.history.kpi.mtbfHint": "running time ÷ breakdowns",` in the English file and `  "maintenance.history.kpi.mtbfHint": "marche ÷ pannes",` in the French one.

- [ ] **Step 6: Run the tests and the type check**

Run (in `frontend/`): `npx vitest run src/features/maintenance/history && npx tsc -b --force`
Expected: 9 vitest tests PASS; `tsc` exits 0.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/features/maintenance/history frontend/src/lib/i18n.en.ts frontend/src/lib/i18n.fr.ts
git commit -m "feat(maintenance-ui): history client -- types, queries, period presets, formatting and strings"
```

---

### Task 13: Side sheet primitive and a shared print shell

**Files:**
- Create: `frontend/src/components/ui/sheet.tsx`
- Move: `frontend/src/features/payroll/print/PrintShell.tsx` → `frontend/src/components/patterns/PrintShell.tsx`
- Modify: the six payroll importers (`CashSheetPrintPage.tsx`, `DeclarationPrintPage.tsx`, `PayslipDocument.tsx`, `PayslipPrintPage.tsx`, `RunPrintPage.tsx`, `WorkCertificate.tsx` in `frontend/src/features/payroll/print/`)

**Interfaces:**
- Produces: `Sheet`, `SheetContent` (props of Radix `Dialog.Content` + `closeLabel: string`), `SheetTitle`, `SheetDescription`; `PrintShell` with props `{ title, subtitle?, company: PrintCompany | null, brand?: ReactNode, backTo, children }`, plus the existing `PRINT_TABLE`, `PRINT_TH`, `PRINT_TD`, `formatDay` exports. Consumed by Tasks 18 and 19.

- [ ] **Step 1: Write `sheet.tsx`**

```tsx
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { forwardRef, type ComponentPropsWithoutRef, type ElementRef } from "react";
import { cn } from "../../lib/utils";

/**
 * A panel sliding in from the right, full screen on a phone. Kept apart from dialog.tsx,
 * which rewrites `max-w-*` classes for centred dialogs.
 */
export const Sheet = DialogPrimitive.Root;

export const SheetContent = forwardRef<
  ElementRef<typeof DialogPrimitive.Content>,
  ComponentPropsWithoutRef<typeof DialogPrimitive.Content> & { closeLabel: string }
>(({ className, children, closeLabel, ...props }, ref) => (
  <DialogPrimitive.Portal>
    <DialogPrimitive.Overlay
      className={cn(
        "fixed inset-0 z-50 bg-foreground/30 backdrop-blur-[1px]",
        "data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=closed]:animate-out data-[state=closed]:fade-out-0",
      )}
    />
    <DialogPrimitive.Content
      ref={ref}
      className={cn(
        "fixed inset-y-0 right-0 z-50 flex h-full w-full flex-col overflow-y-auto border-l border-border bg-background shadow-raised sm:max-w-md",
        "data-[state=open]:animate-in data-[state=open]:slide-in-from-right data-[state=closed]:animate-out data-[state=closed]:slide-out-to-right",
        "motion-reduce:animate-none",
        className,
      )}
      {...props}
    >
      {children}
      <DialogPrimitive.Close
        className="absolute right-3 top-3 rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        aria-label={closeLabel}
      >
        <X className="h-4 w-4" />
      </DialogPrimitive.Close>
    </DialogPrimitive.Content>
  </DialogPrimitive.Portal>
));
SheetContent.displayName = "SheetContent";

export const SheetTitle = forwardRef<
  ElementRef<typeof DialogPrimitive.Title>,
  ComponentPropsWithoutRef<typeof DialogPrimitive.Title>
>(({ className, ...props }, ref) => <DialogPrimitive.Title ref={ref} className={cn("text-base font-semibold", className)} {...props} />);
SheetTitle.displayName = "SheetTitle";

export const SheetDescription = forwardRef<
  ElementRef<typeof DialogPrimitive.Description>,
  ComponentPropsWithoutRef<typeof DialogPrimitive.Description>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Description ref={ref} className={cn("text-sm text-muted-foreground", className)} {...props} />
));
SheetDescription.displayName = "SheetDescription";
```

- [ ] **Step 2: Move the print shell and update its importers**

Run (repo root, Git Bash):
```bash
git mv frontend/src/features/payroll/print/PrintShell.tsx frontend/src/components/patterns/PrintShell.tsx
sed -i 's#from "./PrintShell"#from "../../../components/patterns/PrintShell"#' frontend/src/features/payroll/print/{CashSheetPrintPage,DeclarationPrintPage,PayslipDocument,PayslipPrintPage,RunPrintPage,WorkCertificate}.tsx
```

In the moved `PrintShell.tsx`:
1. Fix its imports: `../../../components/ui/button` → `../ui/button`; `../../../lib/i18n` → `../../lib/i18n`; delete `import type { CompanyHeader } from "../api";`.
2. Add, above `PRINT_CSS`:
```tsx
/** The employer block of a printed document (payroll's CompanyHeader has this shape). */
export interface PrintCompany {
  name: string | null;
  address: string | null;
  employer_inps_no: string | null;
  employer_tax_id: string | null;
}
```
3. In the props: change `company: CompanyHeader | null;` to `company: PrintCompany | null;`, and add after it:
```tsx
  /** A brand block shown at the top left (e.g. the logo and wordmark) for documents with no employer block. */
  brand?: ReactNode;
```
and destructure `brand` in the function parameters.
4. In the header's left `<div className="min-w-0">`, render `{brand}` before `{company && (...)}`.

- [ ] **Step 3: Type check**

Run (in `frontend/`): `npx tsc -b --force`
Expected: exit 0 (the payroll print pages still compile against the moved shell).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/ui/sheet.tsx frontend/src/components/patterns/PrintShell.tsx frontend/src/features/payroll/print
git commit -m "refactor(ui): side sheet primitive, and the print shell shared outside payroll with a brand slot"
```

---

### Task 14: Period control, machine photo and the two indicator blocks

**Files:**
- Create: `frontend/src/features/maintenance/history/PeriodControl.tsx`
- Create: `frontend/src/features/maintenance/history/MachinePhoto.tsx`
- Create: `frontend/src/features/maintenance/history/IndicatorBlocks.tsx`

**Interfaces:**
- Consumes: Task 12 (`usePeriod`, `PERIOD_PRESETS`, types, `fill`, `minutesOrDash`, `largestIndex`), Task 11 assets.
- Produces: `<PeriodControl />`; `<MachinePhotoTile machine caption? className? />`, `<MachineThumb machine />`; `<IndicatorBlocks production maintenance costsVisible productionAvailable />`, `<ProductionCard block available />`, `<MaintenanceCard block costsVisible />`; `HISTORY_EASE`.

- [ ] **Step 1: Write `PeriodControl.tsx`**

```tsx
import { useState } from "react";
import { DateRangeFilter } from "../../../components/patterns/DateRangeFilter";
import { FilterTabs } from "../../../components/patterns/FilterTabs";
import { useI18n, type TranslationKey } from "../../../lib/i18n";
import { PERIOD_PRESETS, usePeriod, type PeriodPreset } from "./historyPeriod";

type Choice = PeriodPreset | "custom";

const LABEL: Record<Choice, TranslationKey> = {
  month: "maintenance.history.period.month",
  lastMonth: "maintenance.history.period.lastMonth",
  threeMonths: "maintenance.history.period.threeMonths",
  year: "maintenance.history.period.year",
  custom: "maintenance.history.period.custom",
};

/** Preset periods as chips, plus two dates for a custom one; the period itself lives in the URL. */
export function PeriodControl() {
  const { t } = useI18n();
  const { period, preset, isDefault, setPreset, setRange, reset } = usePeriod();
  const [customOpen, setCustomOpen] = useState(preset === null);
  const value: Choice = customOpen || preset === null ? "custom" : preset;

  return (
    <div className="flex flex-wrap items-center gap-2">
      <FilterTabs<Choice>
        options={[...PERIOD_PRESETS, "custom" as const].map((choice) => ({ value: choice, label: t(LABEL[choice]) }))}
        value={value}
        onChange={(choice) => {
          if (choice === "custom") {
            setCustomOpen(true);
          } else {
            setCustomOpen(false);
            setPreset(choice);
          }
        }}
      />
      {value === "custom" && (
        <DateRangeFilter
          from={period.from}
          to={period.to}
          onChange={setRange}
          onReset={() => {
            setCustomOpen(false);
            reset();
          }}
          isDefault={isDefault}
        />
      )}
    </div>
  );
}
```

- [ ] **Step 2: Write `MachinePhoto.tsx`**

```tsx
import stageConditionnement from "../../../assets/illustrations/production/stage-conditionnement.webp";
import stageExtrusion from "../../../assets/illustrations/production/stage-extrusion.webp";
import stageMelange from "../../../assets/illustrations/production/stage-melange.webp";
import MachineSvg from "../../../assets/icons/maintenance/machine.svg?react";
import { outlineIcon } from "../../../components/patterns/outlineIcon";
import { cn } from "../../../lib/utils";
import { fetchViewImageBlob, type ProductionStage } from "../api";
import { useAuthedImage } from "../useAuthedImage";
import type { MachineSummary } from "./api";

const MachineIcon = outlineIcon(MachineSvg);

const STAGE_ART: Record<ProductionStage, string> = {
  versement: stageMelange,
  extrusion: stageExtrusion,
  conditionnement: stageConditionnement,
};

/** The machine's own photo (the first view of its plan); else its stage's artwork; else the machine icon. */
function useMachinePicture(machine: MachineSummary): { src: string | null; isPhoto: boolean } {
  const { url } = useAuthedImage(fetchViewImageBlob, machine.photo_view_id, machine.photo_version);
  if (url) return { src: url, isPhoto: true };
  if (machine.production_stage) return { src: STAGE_ART[machine.production_stage], isPhoto: false };
  return { src: null, isPhoto: false };
}

const TILE = "relative grid place-items-center overflow-hidden bg-[radial-gradient(circle_at_50%_65%,#1A4A85_0%,#082B57_60%,#071F43_100%)]";

export function MachinePhotoTile({ machine, caption, className }: { machine: MachineSummary; caption?: string; className?: string }) {
  const { src, isPhoto } = useMachinePicture(machine);
  return (
    <div className={cn(TILE, "rounded-xl", className)}>
      {src ? (
        <img
          src={src}
          alt=""
          className={isPhoto ? "h-full w-full object-cover" : "w-[115%] max-w-none drop-shadow-[0_10px_18px_rgba(0,0,0,0.35)]"}
        />
      ) : (
        <MachineIcon aria-hidden className="h-12 w-12 text-white/70" />
      )}
      {caption && isPhoto && (
        <span className="absolute bottom-2 left-2 text-[10px] uppercase tracking-[0.14em] text-white/80">{caption}</span>
      )}
    </div>
  );
}

export function MachineThumb({ machine }: { machine: MachineSummary }) {
  const { src, isPhoto } = useMachinePicture(machine);
  return (
    <span className={cn(TILE, "h-7 w-9 shrink-0 rounded-md")}>
      {src ? (
        <img src={src} alt="" className={isPhoto ? "h-full w-full object-cover" : "w-[125%] max-w-none"} />
      ) : (
        <MachineIcon aria-hidden className="h-4 w-4 text-white/70" />
      )}
    </span>
  );
}
```

- [ ] **Step 3: Write `IndicatorBlocks.tsx`**

```tsx
import type { ReactNode } from "react";
import { motion, useReducedMotion } from "framer-motion";
import DowntimeSvg from "../../../assets/icons/production/downtime.svg?react";
import WrenchSvg from "../../../assets/icons/maintenance/wrench.svg?react";
import NoBreakdownIllustration from "../../../assets/illustrations/maintenance/no-breakdown.svg?react";
import { CountUp } from "../../../components/motion/CountUp";
import { outlineIcon } from "../../../components/patterns/outlineIcon";
import { Card } from "../../../components/ui/card";
import { formatXofWithCode } from "../../../lib/currency";
import { useI18n } from "../../../lib/i18n";
import { formatDuration } from "../../../lib/units";
import { cn } from "../../../lib/utils";
import { downtimeLabel } from "../../production/downtimeOptions";
import type { MaintenanceBlock, ProductionBlock } from "./api";
import { fill, largestIndex, minutesOrDash } from "./historyFormat";

const DowntimeIcon = outlineIcon(DowntimeSvg);
const WrenchIcon = outlineIcon(WrenchSvg);

/** The brand's easing (LoginPage, BrandLoader). */
export const HISTORY_EASE = [0.22, 1, 0.36, 1] as const;

function BlockHeader({ icon, title, caption }: { icon: ReactNode; title: string; caption: string }) {
  return (
    <div className="flex min-w-0 items-center gap-2 border-b border-border px-4 py-2.5">
      <span className="shrink-0 text-primary">{icon}</span>
      <p className="shrink-0 text-sm font-semibold">{title}</p>
      <p className="truncate text-xs text-muted-foreground">· {caption}</p>
    </div>
  );
}

function Tiles({ children }: { children: ReactNode }) {
  return <div className="grid grid-cols-2 gap-px bg-border sm:grid-cols-4">{children}</div>;
}

function Tile({ label, sub, children }: { label: string; sub?: ReactNode; children: ReactNode }) {
  return (
    <div className="min-w-0 bg-card px-4 py-3">
      <p className="truncate text-xs text-muted-foreground">{label}</p>
      <p className="whitespace-nowrap text-lg font-bold tabular-nums tracking-tight sm:text-xl">{children}</p>
      {sub && <p className="truncate text-xs text-muted-foreground">{sub}</p>}
    </div>
  );
}

function SystemBars({ rows }: { rows: ProductionBlock["breakdowns_by_system"] }) {
  const { t } = useI18n();
  const reduce = useReducedMotion();
  if (rows.length === 0) {
    return (
      <div className="flex items-center gap-3 px-4 py-3">
        <NoBreakdownIllustration aria-hidden className="h-16 w-20 shrink-0" />
        <p className="text-sm text-muted-foreground">{t("maintenance.history.noBreakdown")}</p>
      </div>
    );
  }
  const top = largestIndex(rows.map((row) => row.minutes));
  const max = rows[top].minutes || 1;
  return (
    <div className="space-y-1.5 px-4 py-3">
      <p className="text-xs text-muted-foreground">{t("maintenance.history.bySystem")}</p>
      {rows.map((row, index) => (
        <div key={row.classification ?? "none"} className="flex items-center gap-2 text-xs">
          <span className="w-24 shrink-0 truncate text-muted-foreground">
            {row.classification ? downtimeLabel(t, "classification", row.classification) : "—"}
          </span>
          <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
            <motion.div
              className={cn("h-full rounded-full", index === top ? "bg-accent" : "bg-primary/70")}
              initial={reduce ? false : { width: 0 }}
              animate={{ width: `${(row.minutes / max) * 100}%` }}
              transition={{ duration: 0.6, ease: HISTORY_EASE }}
            />
          </div>
          <span className="w-20 shrink-0 text-right tabular-nums text-muted-foreground">{formatDuration(row.minutes)}</span>
        </div>
      ))}
    </div>
  );
}

export function ProductionCard({ block, available }: { block: ProductionBlock | null; available: boolean }) {
  const { t } = useI18n();
  return (
    <Card className="overflow-hidden">
      <BlockHeader
        icon={<DowntimeIcon className="h-4 w-4" />}
        title={t("maintenance.history.production.title")}
        caption={t("maintenance.history.production.caption")}
      />
      {!available || !block ? (
        <p className="px-4 py-6 text-sm text-muted-foreground">{t("maintenance.history.production.unavailable")}</p>
      ) : (
        <>
          <Tiles>
            <Tile label={t("maintenance.history.kpi.breakdowns")} sub={formatDuration(block.breakdown_minutes)}>
              <CountUp value={block.breakdowns} duration={350} />
            </Tile>
            <Tile
              label={t("maintenance.history.kpi.mtbf")}
              sub={t(block.mtbf_minutes === null ? "maintenance.history.kpi.noBreakdown" : "maintenance.history.kpi.mtbfHint")}
            >
              {minutesOrDash(block.mtbf_minutes)}
            </Tile>
            <Tile
              label={t("maintenance.history.kpi.mttr")}
              sub={t(block.mttr_minutes === null ? "maintenance.history.kpi.noBreakdown" : "maintenance.history.kpi.mttrHint")}
            >
              {minutesOrDash(block.mttr_minutes)}
            </Tile>
            <Tile label={t("maintenance.history.kpi.allStops")} sub={formatDuration(block.stop_minutes)}>
              <CountUp value={block.stops} duration={350} />
            </Tile>
          </Tiles>
          <SystemBars rows={block.breakdowns_by_system} />
        </>
      )}
    </Card>
  );
}

function PreventiveRing({ due, closed }: { due: number; closed: number }) {
  const reduce = useReducedMotion();
  const radius = 22;
  const circumference = 2 * Math.PI * radius;
  const share = due > 0 ? Math.min(closed / due, 1) : 0;
  const label = due > 0 ? `${closed}/${due}` : "—";
  return (
    <svg viewBox="0 0 54 54" className="h-14 w-14 shrink-0" role="img" aria-label={label}>
      <circle cx="27" cy="27" r={radius} fill="none" className="stroke-muted" strokeWidth="7" />
      {due > 0 && (
        <motion.circle
          cx="27"
          cy="27"
          r={radius}
          fill="none"
          className="stroke-accent"
          strokeWidth="7"
          strokeLinecap="round"
          transform="rotate(-90 27 27)"
          strokeDasharray={circumference}
          initial={reduce ? false : { strokeDashoffset: circumference }}
          animate={{ strokeDashoffset: circumference * (1 - share) }}
          transition={{ duration: 0.6, ease: HISTORY_EASE }}
        />
      )}
      <text x="27" y="31" textAnchor="middle" className="fill-primary text-[12px] font-bold">
        {label}
      </text>
    </svg>
  );
}

export function MaintenanceCard({ block, costsVisible }: { block: MaintenanceBlock; costsVisible: boolean }) {
  const { t } = useI18n();
  const technician = formatDuration(block.technician_seconds / 60);
  const { due, closed, closed_on_time: onTime, overdue } = block.preventive;
  return (
    <Card className="overflow-hidden">
      <BlockHeader
        icon={<WrenchIcon className="h-4 w-4" />}
        title={t("maintenance.history.maintenance.title")}
        caption={t("maintenance.history.maintenance.caption")}
      />
      <Tiles>
        <Tile label={t("maintenance.history.kpi.breakdowns")} sub={t("maintenance.history.kpi.corrective")}>
          <CountUp value={block.breakdowns} duration={350} />
        </Tile>
        <Tile
          label={t("maintenance.history.kpi.immobilisation")}
          sub={
            block.mean_immobilisation_minutes === null
              ? undefined
              : fill(t("maintenance.history.kpi.meanImmobilisation"), { value: formatDuration(block.mean_immobilisation_minutes) })
          }
        >
          {formatDuration(block.immobilised_minutes)}
        </Tile>
        <Tile
          label={t("maintenance.history.kpi.betweenBreakdowns")}
          sub={t(block.calendar_mtbf_minutes === null ? "maintenance.history.kpi.noBreakdown" : "maintenance.history.kpi.calendar")}
        >
          {minutesOrDash(block.calendar_mtbf_minutes)}
        </Tile>
        {costsVisible ? (
          <Tile
            label={t("maintenance.history.kpi.partsCost")}
            sub={block.parts_unvalued_quantity ? fill(t("maintenance.history.kpi.unvalued"), { value: block.parts_unvalued_quantity }) : undefined}
          >
            {block.parts_cost === null ? "—" : formatXofWithCode(block.parts_cost)}
          </Tile>
        ) : (
          <Tile label={t("maintenance.history.kpi.technician")}>{technician}</Tile>
        )}
      </Tiles>
      <div className="flex items-center gap-4 px-4 py-3">
        <PreventiveRing due={due} closed={closed} />
        <div className="min-w-0 space-y-0.5 text-xs">
          <p className="text-sm font-semibold">
            {due === 0 ? t("maintenance.history.preventive.none") : fill(t("maintenance.history.preventive.summary"), { due, closed })}
          </p>
          {due > 0 && (
            <p className="text-muted-foreground">
              {fill(t("maintenance.history.preventive.onTime"), { n: onTime })} ·{" "}
              <span className={cn(overdue > 0 && "font-semibold text-destructive")}>
                {fill(t("maintenance.history.preventive.overdue"), { n: overdue })}
              </span>
            </p>
          )}
          {costsVisible && (
            <p className="text-muted-foreground">
              {t("maintenance.history.kpi.technician")} {technician}
            </p>
          )}
        </div>
      </div>
    </Card>
  );
}

export function IndicatorBlocks({
  production,
  maintenance,
  costsVisible,
  productionAvailable,
}: {
  production: ProductionBlock | null;
  maintenance: MaintenanceBlock;
  costsVisible: boolean;
  productionAvailable: boolean;
}) {
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <ProductionCard block={production} available={productionAvailable} />
      <MaintenanceCard block={maintenance} costsVisible={costsVisible} />
    </div>
  );
}
```

- [ ] **Step 4: Type check**

Run (in `frontend/`): `npx tsc -b --force`
Expected: exit 0.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/maintenance/history/PeriodControl.tsx frontend/src/features/maintenance/history/MachinePhoto.tsx frontend/src/features/maintenance/history/IndicatorBlocks.tsx
git commit -m "feat(maintenance-ui): period control, machine photo tile and the production/maintenance indicator blocks"
```

---

### Task 15: Indicators view and journal view

**Files:**
- Create: `frontend/src/features/maintenance/history/IndicatorsView.tsx`
- Create: `frontend/src/features/maintenance/history/JournalView.tsx`

**Interfaces:**
- Consumes: Tasks 12 and 14.
- Produces: `<IndicatorsView data isLoading equipmentId onOpen />` and `<JournalView period equipmentId />` (URL params owned by the journal: `jstatus`, `kind`). Consumed by Task 16.

- [ ] **Step 1: Write `IndicatorsView.tsx`**

```tsx
import { useMemo } from "react";
import { Gauge } from "lucide-react";
import DowntimeSvg from "../../../assets/icons/production/downtime.svg?react";
import ImmobilisationSvg from "../../../assets/icons/maintenance/immobilisation.svg?react";
import SparePartsSvg from "../../../assets/icons/maintenance/spare_parts.svg?react";
import WrenchSvg from "../../../assets/icons/maintenance/wrench.svg?react";
import HistoryEmptyIllustration from "../../../assets/illustrations/maintenance/history-empty.svg?react";
import { ColumnFilterRow, type FilterCell } from "../../../components/patterns/ColumnFilterRow";
import { EmptyState } from "../../../components/patterns/EmptyState";
import { MobileCardList } from "../../../components/patterns/MobileCardList";
import { outlineIcon } from "../../../components/patterns/outlineIcon";
import { StatCard } from "../../../components/patterns/StatCard";
import { Badge } from "../../../components/ui/badge";
import { Card, CardContent } from "../../../components/ui/card";
import { Skeleton } from "../../../components/ui/skeleton";
import { ResizableTableHead, Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../../../components/ui/table";
import { CURRENCY_CODE, formatXofWithCode } from "../../../lib/currency";
import { useI18n } from "../../../lib/i18n";
import { formatDuration } from "../../../lib/units";
import { useColumnFilters, type FilterField } from "../../../lib/useColumnFilters";
import { useIsMobile } from "../../../lib/useIsMobile";
import { useTableColumns, type ColumnDef } from "../../../lib/useTableColumns";
import { cn } from "../../../lib/utils";
import type { IndicatorsResponse, MachineIndicators } from "./api";
import { fill, minutesOrDash } from "./historyFormat";
import { MachineThumb } from "./MachinePhoto";

const DowntimeIcon = outlineIcon(DowntimeSvg);
const WrenchIcon = outlineIcon(WrenchSvg);
const ImmobilisationIcon = outlineIcon(ImmobilisationSvg);
const SparePartsIcon = outlineIcon(SparePartsSvg);

type Group = "machine" | "production" | "maintenance";
const GROUP_OF: Record<string, Group> = {
  machine: "machine",
  prod_breakdowns: "production", prod_stop: "production", mtbf: "production", mttr: "production",
  maint_breakdowns: "maintenance", immobilisation: "maintenance", preventive: "maintenance", technician: "maintenance", cost: "maintenance",
};

/** The "Selon la production | Selon la maintenance" row above the headers, spanning whichever columns are visible. */
function GroupRow({ columns }: { columns: ColumnDef<MachineIndicators>[] }) {
  const { t } = useI18n();
  const runs: { group: Group; span: number }[] = [];
  for (const column of columns) {
    const group = GROUP_OF[column.key];
    const last = runs[runs.length - 1];
    if (last && last.group === group) last.span += 1;
    else runs.push({ group, span: 1 });
  }
  return (
    <TableRow className="hover:bg-transparent">
      {runs.map((run, index) => (
        <TableHead
          key={`${run.group}-${index}`}
          colSpan={run.span}
          className={cn("h-7 pb-0 text-[10px] font-semibold uppercase tracking-[0.16em] text-primary", run.group === "maintenance" && "border-l border-border")}
        >
          {run.group === "production" && (
            <span className="inline-flex items-center gap-1.5"><DowntimeIcon className="h-3.5 w-3.5" />{t("maintenance.history.production.title")}</span>
          )}
          {run.group === "maintenance" && (
            <span className="inline-flex items-center gap-1.5"><WrenchIcon className="h-3.5 w-3.5" />{t("maintenance.history.maintenance.title")}</span>
          )}
        </TableHead>
      ))}
    </TableRow>
  );
}

export function IndicatorsView({
  data,
  isLoading,
  equipmentId,
  onOpen,
}: {
  data: IndicatorsResponse | undefined;
  isLoading: boolean;
  equipmentId: string;
  onOpen: (machine: MachineIndicators) => void;
}) {
  const { t } = useI18n();
  const isMobile = useIsMobile();
  const costsVisible = data?.costs_visible ?? false;
  const machines = useMemo(
    () => (data?.machines ?? []).filter((machine) => !equipmentId || machine.equipment_id === equipmentId),
    [data, equipmentId],
  );

  const totals = useMemo(
    () => ({
      production: machines.reduce((sum, m) => sum + (m.production?.breakdowns ?? 0), 0),
      maintenance: machines.reduce((sum, m) => sum + m.maintenance.breakdowns, 0),
      immobilisedHours: machines.reduce((sum, m) => sum + m.maintenance.immobilised_minutes, 0) / 60,
      cost: costsVisible ? machines.reduce((sum, m) => sum + (m.maintenance.parts_cost ?? 0), 0) : null,
    }),
    [machines, costsVisible],
  );

  const filterFields: FilterField<MachineIndicators>[] = [
    { key: "machine", kind: "text", getValue: (m) => `${m.code} ${m.name}` },
    { key: "prod_breakdowns", kind: "range", getValue: (m) => m.production?.breakdowns ?? null },
    { key: "maint_breakdowns", kind: "range", getValue: (m) => m.maintenance.breakdowns },
    { key: "cost", kind: "range", getValue: (m) => m.maintenance.parts_cost },
  ];
  const filters = useColumnFilters(filterFields);
  const rangeCell = (key: string): FilterCell => ({
    type: "range",
    min: filters.range[key]?.min ?? "",
    max: filters.range[key]?.max ?? "",
    onMinChange: (value) => filters.setRangeValue(key, "min", value),
    onMaxChange: (value) => filters.setRangeValue(key, "max", value),
  });

  const columns: ColumnDef<MachineIndicators>[] = [
    {
      key: "machine",
      header: t("maintenance.history.column.machine"),
      defaultWidth: 220,
      alwaysVisible: true,
      mobileRole: "title",
      sortValue: (m) => m.name,
      filterCell: { type: "text", value: filters.text.machine ?? "", onChange: (v) => filters.setTextValue("machine", v), placeholder: t("maintenance.history.column.machine") },
      cell: (m) => (
        <span className="flex min-w-0 items-center gap-2">
          <MachineThumb machine={m} />
          <span className="min-w-0">
            <span className="block truncate font-medium">{m.name}</span>
            <span className="block truncate font-mono text-xs text-muted-foreground">{m.code}</span>
          </span>
        </span>
      ),
    },
    {
      key: "prod_breakdowns",
      header: t("maintenance.history.kpi.breakdowns"),
      defaultWidth: 100,
      sortValue: (m) => m.production?.breakdowns ?? -1,
      filterCell: rangeCell("prod_breakdowns"),
      cell: (m) => <span className="font-semibold tabular-nums">{m.production ? m.production.breakdowns : "—"}</span>,
    },
    { key: "prod_stop", header: t("maintenance.history.column.stopTime"), defaultWidth: 110, sortValue: (m) => m.production?.breakdown_minutes ?? -1,
      cell: (m) => <span className="tabular-nums">{m.production ? formatDuration(m.production.breakdown_minutes) : "—"}</span> },
    { key: "mtbf", header: t("maintenance.history.kpi.mtbf"), defaultWidth: 110, sortValue: (m) => m.production?.mtbf_minutes ?? -1,
      cell: (m) => <span className="tabular-nums">{minutesOrDash(m.production?.mtbf_minutes)}</span> },
    { key: "mttr", header: t("maintenance.history.kpi.mttr"), defaultWidth: 100, sortValue: (m) => m.production?.mttr_minutes ?? -1,
      cell: (m) => <span className="tabular-nums">{minutesOrDash(m.production?.mttr_minutes)}</span> },
    {
      key: "maint_breakdowns",
      header: t("maintenance.history.kpi.breakdowns"),
      defaultWidth: 100,
      headerClassName: "border-l border-border",
      cellClassName: "border-l border-border",
      sortValue: (m) => m.maintenance.breakdowns,
      filterCell: rangeCell("maint_breakdowns"),
      cell: (m) => <span className="font-semibold tabular-nums">{m.maintenance.breakdowns}</span>,
    },
    { key: "immobilisation", header: t("maintenance.history.kpi.immobilisation"), defaultWidth: 130, sortValue: (m) => m.maintenance.immobilised_minutes,
      cell: (m) => <span className="tabular-nums">{formatDuration(m.maintenance.immobilised_minutes)}</span> },
    {
      key: "preventive",
      header: t("maintenance.history.column.preventive"),
      defaultWidth: 150,
      sortValue: (m) => m.maintenance.preventive.overdue,
      cell: (m) => {
        const { due, closed, overdue } = m.maintenance.preventive;
        if (due === 0) return <span className="text-muted-foreground">—</span>;
        return (
          <Badge variant={overdue > 0 ? "warning" : "success"}>
            {closed}/{due}
            {overdue > 0 && ` · ${fill(t("maintenance.history.preventive.overdue"), { n: overdue })}`}
          </Badge>
        );
      },
    },
    { key: "technician", header: t("maintenance.history.column.technician"), defaultWidth: 110, hiddenByDefault: false,
      sortValue: (m) => m.maintenance.technician_seconds,
      cell: (m) => <span className="tabular-nums">{formatDuration(m.maintenance.technician_seconds / 60)}</span> },
    ...(costsVisible
      ? [
          {
            key: "cost",
            header: `${t("maintenance.history.kpi.partsCost")} (${CURRENCY_CODE})`,
            defaultWidth: 140,
            sortValue: (m: MachineIndicators) => m.maintenance.parts_cost ?? 0,
            filterCell: rangeCell("cost"),
            cell: (m: MachineIndicators) => (
              <span className="tabular-nums">{m.maintenance.parts_cost === null ? "—" : formatXofWithCode(m.maintenance.parts_cost)}</span>
            ),
          },
        ]
      : []),
  ];
  const table = useTableColumns("maintenance.history.indicators", columns);
  const rows = table.sortRows(filters.apply(machines));
  const span = table.visibleColumns.length;
  const empty = (
    <EmptyState
      icon={<Gauge className="h-5 w-5" />}
      illustration={<HistoryEmptyIllustration aria-hidden className="h-44 w-52" />}
      title={t("maintenance.history.indicators.empty.title")}
      description={t("maintenance.history.indicators.empty.description")}
    />
  );

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label={t("maintenance.history.stat.productionBreakdowns")} value={data?.production_available ? totals.production : null} icon={<DowntimeIcon className="h-5 w-5" />} />
        <StatCard label={t("maintenance.history.stat.maintenanceBreakdowns")} value={totals.maintenance} icon={<WrenchIcon className="h-5 w-5" />} />
        <StatCard label={t("maintenance.history.stat.immobilisation")} value={totals.immobilisedHours} unit="h" decimals={1} icon={<ImmobilisationIcon className="h-5 w-5" />} accent="warning" />
        {costsVisible && (
          <StatCard label={t("maintenance.history.stat.partsCost")} value={totals.cost} unit={CURRENCY_CODE} icon={<SparePartsIcon className="h-5 w-5" />} accent="accent" />
        )}
      </div>

      {isMobile ? (
        <MobileCardList
          columns={table.visibleColumns}
          rows={rows}
          rowKey={(m) => m.equipment_id}
          loading={isLoading}
          emptyIcon={<Gauge className="h-5 w-5" />}
          emptyTitle={t("maintenance.history.indicators.empty.title")}
          emptyDescription={t("maintenance.history.indicators.empty.description")}
          onRowClick={onOpen}
        />
      ) : (
        <Card>
          <CardContent className="p-0">
            <Table colWidths={table.colWidths}>
              <TableHeader>
                <GroupRow columns={table.visibleColumns} />
                <TableRow>
                  {table.visibleColumns.map((column) => (
                    <ResizableTableHead
                      key={column.key}
                      width={table.getWidth(column.key)}
                      onResize={(width) => table.setWidth(column.key, width)}
                      className={column.headerClassName}
                      sortDirection={table.sortDirectionFor(column.key)}
                      onSort={column.sortValue ? () => table.toggleSort(column.key) : undefined}
                    >
                      {column.header}
                    </ResizableTableHead>
                  ))}
                </TableRow>
                <ColumnFilterRow cells={table.visibleColumns.map((column) => column.filterCell ?? { type: "blank" })} />
              </TableHeader>
              <TableBody>
                {isLoading &&
                  [0, 1, 2].map((index) => (
                    <TableRow key={`skeleton-${index}`}>
                      <TableCell colSpan={span}><Skeleton className="h-5 w-full" /></TableCell>
                    </TableRow>
                  ))}
                {!isLoading && rows.length === 0 && (
                  <TableRow className="hover:bg-transparent">
                    <TableCell colSpan={span} className="p-0">{empty}</TableCell>
                  </TableRow>
                )}
                {!isLoading &&
                  rows.map((machine) => (
                    <TableRow key={machine.equipment_id} onClick={() => onOpen(machine)} className="cursor-pointer">
                      {table.visibleColumns.map((column) => (
                        <TableCell key={column.key} className={column.cellClassName}>{column.cell(machine)}</TableCell>
                      ))}
                    </TableRow>
                  ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      {data?.unattributed_stops && data.unattributed_stops.count > 0 && (
        <p className="rounded-lg border border-border bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
          {fill(t("maintenance.history.unattributed"), {
            count: data.unattributed_stops.count,
            minutes: formatDuration(data.unattributed_stops.minutes),
          })}
        </p>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Write `JournalView.tsx`**

```tsx
import { useMemo, useState } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { ClipboardList, FileSpreadsheet } from "lucide-react";
import { toast } from "sonner";
import HistoryEmptyIllustration from "../../../assets/illustrations/maintenance/history-empty.svg?react";
import { ColumnFilterRow } from "../../../components/patterns/ColumnFilterRow";
import { EmptyState } from "../../../components/patterns/EmptyState";
import { FilterTabs } from "../../../components/patterns/FilterTabs";
import { MobileCardList } from "../../../components/patterns/MobileCardList";
import { Badge } from "../../../components/ui/badge";
import { Button } from "../../../components/ui/button";
import { Card, CardContent } from "../../../components/ui/card";
import { Skeleton } from "../../../components/ui/skeleton";
import { ResizableTableHead, Table, TableBody, TableCell, TableHeader, TableRow } from "../../../components/ui/table";
import { ApiError } from "../../../lib/api";
import { useAuth } from "../../../lib/auth";
import { CURRENCY_CODE, formatXofWithCode } from "../../../lib/currency";
import { useI18n } from "../../../lib/i18n";
import { formatDuration } from "../../../lib/units";
import { useColumnFilters, type FilterField } from "../../../lib/useColumnFilters";
import { useIsMobile } from "../../../lib/useIsMobile";
import { useTableColumns, type ColumnDef } from "../../../lib/useTableColumns";
import { formatDay } from "../jobs/jobFormat";
import { JOB_KIND_LABEL_KEY } from "../labels";
import { exportJournalWorkbook, useHistoryJournal, type JournalFilters, type JournalKind, type JournalRow, type JournalStatus } from "./api";
import { fill, initials } from "./historyFormat";
import type { Period } from "./historyPeriod";

type KindFilter = "all" | JournalKind;
const STATUSES: JournalStatus[] = ["closed", "cancelled", "all"];
const KINDS: KindFilter[] = ["all", "preventive", "corrective"];

function ResultBar({ row }: { row: JournalRow }) {
  const { t } = useI18n();
  const { ok, issue, not_done: notDone } = row.outcomes;
  const total = Math.max(ok + issue + notDone, 1);
  return (
    <span className="flex items-center gap-2">
      <span className="flex h-2 w-20 shrink-0 overflow-hidden rounded-full bg-muted">
        <span className="bg-success" style={{ width: `${(ok / total) * 100}%` }} />
        <span className="bg-destructive" style={{ width: `${(issue / total) * 100}%` }} />
        <span className="bg-muted-foreground/40" style={{ width: `${(notDone / total) * 100}%` }} />
      </span>
      <span className="truncate text-xs text-muted-foreground">{fill(t("maintenance.history.journal.result"), { ok, issue, notDone })}</span>
    </span>
  );
}

export function JournalView({ period, equipmentId }: { period: Period; equipmentId: string }) {
  const { session } = useAuth();
  const token = session!.token;
  const { t, language } = useI18n();
  const navigate = useNavigate();
  const location = useLocation();
  const isMobile = useIsMobile();
  const [searchParams, setSearchParams] = useSearchParams();
  const [exporting, setExporting] = useState(false);

  const statusParam = searchParams.get("jstatus") as JournalStatus | null;
  const status: JournalStatus = statusParam && STATUSES.includes(statusParam) ? statusParam : "closed";
  const kindParam = searchParams.get("kind") as KindFilter | null;
  const kind: KindFilter = kindParam && KINDS.includes(kindParam) ? kindParam : "all";

  const filters = useMemo<JournalFilters>(
    () => ({ ...period, equipment_id: equipmentId || undefined, kind: kind === "all" ? undefined : kind, status }),
    [period, equipmentId, kind, status],
  );
  const journal = useHistoryJournal(token, filters);
  const costsVisible = journal.data?.costs_visible ?? false;

  function update(key: string, value: string | null) {
    setSearchParams(
      (current) => {
        const next = new URLSearchParams(current);
        if (value === null) next.delete(key);
        else next.set(key, value);
        return next;
      },
      { replace: true },
    );
  }

  async function exportExcel() {
    setExporting(true);
    try {
      const blob = await exportJournalWorkbook(token, { ...filters, lang: language });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `maintenance-journal-${period.from}_${period.to}.xlsx`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (error) {
      toast.error(t("maintenance.history.journal.exportError"), { description: error instanceof ApiError ? error.message : undefined });
    } finally {
      setExporting(false);
    }
  }

  const fields: FilterField<JournalRow>[] = [
    { key: "number", kind: "text", getValue: (r) => r.number },
    { key: "machine", kind: "text", getValue: (r) => `${r.equipment_code} ${r.equipment_name}` },
    { key: "title", kind: "text", getValue: (r) => r.title },
    { key: "performers", kind: "text", getValue: (r) => r.performers.map((p) => p.name).join(" ") },
    { key: "time", kind: "range", getValue: (r) => Math.round(r.technician_seconds / 60) },
    { key: "cost", kind: "range", getValue: (r) => r.parts_cost },
  ];
  const columnFilters = useColumnFilters(fields);
  const text = (key: string, placeholder: string) => ({
    type: "text" as const,
    value: columnFilters.text[key] ?? "",
    onChange: (v: string) => columnFilters.setTextValue(key, v),
    placeholder,
  });
  const range = (key: string) => ({
    type: "range" as const,
    min: columnFilters.range[key]?.min ?? "",
    max: columnFilters.range[key]?.max ?? "",
    onMinChange: (v: string) => columnFilters.setRangeValue(key, "min", v),
    onMaxChange: (v: string) => columnFilters.setRangeValue(key, "max", v),
  });

  const columns: ColumnDef<JournalRow>[] = [
    { key: "number", header: t("maintenance.history.journal.column.number"), defaultWidth: 140, alwaysVisible: true, mobileRole: "subtitle",
      sortValue: (r) => r.number, filterCell: text("number", t("maintenance.history.journal.column.number")),
      cell: (r) => <span className="font-mono text-xs font-medium text-primary">{r.number}</span> },
    { key: "date", header: t("maintenance.history.journal.column.date"), defaultWidth: 120, sortValue: (r) => r.date ?? "",
      cell: (r) => <span className="whitespace-nowrap">{formatDay(r.date)}</span> },
    { key: "machine", header: t("maintenance.history.column.machine"), defaultWidth: 180, sortValue: (r) => r.equipment_name,
      filterCell: text("machine", t("maintenance.history.column.machine")),
      cell: (r) => <span className="block truncate" title={`${r.equipment_code} — ${r.equipment_name}`}>{r.equipment_name}</span> },
    { key: "kind", header: t("maintenance.history.journal.column.kind"), defaultWidth: 120, sortValue: (r) => r.kind,
      cell: (r) => <Badge variant={r.kind === "corrective" ? "destructive" : "primary"}>{t(JOB_KIND_LABEL_KEY[r.kind])}</Badge> },
    { key: "title", header: t("maintenance.history.journal.column.title"), defaultWidth: 220, mobileRole: "title", sortValue: (r) => r.title,
      filterCell: text("title", t("maintenance.history.journal.column.title")),
      cell: (r) => <span className="block truncate" title={r.cancel_reason ?? r.title}>{r.title}</span> },
    { key: "performers", header: t("maintenance.history.journal.column.performers"), defaultWidth: 140,
      filterCell: text("performers", t("maintenance.history.journal.column.performers")),
      cell: (r) => (
        <span className="flex items-center" title={r.performers.map((p) => p.name).join(", ")}>
          {r.performers.length === 0 && <span className="text-muted-foreground">—</span>}
          {r.performers.map((p) => (
            <span key={p.employee_id} className="-ml-1.5 grid h-6 w-6 place-items-center rounded-full border-2 border-card bg-primary text-[9px] font-bold text-primary-foreground first:ml-0">
              {initials(p.name)}
            </span>
          ))}
        </span>
      ) },
    { key: "time", header: t("maintenance.history.journal.column.time"), defaultWidth: 110, sortValue: (r) => r.technician_seconds,
      filterCell: range("time"),
      cell: (r) => <span className="whitespace-nowrap tabular-nums">{r.technician_seconds > 0 ? formatDuration(r.technician_seconds / 60) : "—"}</span> },
    { key: "result", header: t("maintenance.history.journal.column.result"), defaultWidth: 230, cell: (r) => <ResultBar row={r} /> },
    { key: "parts", header: t("maintenance.history.journal.column.parts"), defaultWidth: 90, sortValue: (r) => r.parts.issued_lines + r.parts.purchase_lines,
      cell: (r) => <span className="tabular-nums">{r.parts.issued_lines + r.parts.purchase_lines || "—"}</span> },
    ...(costsVisible
      ? [{
          key: "cost",
          header: `${t("maintenance.history.journal.column.cost")} (${CURRENCY_CODE})`,
          defaultWidth: 130,
          sortValue: (r: JournalRow) => r.parts_cost ?? 0,
          filterCell: range("cost"),
          cell: (r: JournalRow) => <span className="whitespace-nowrap tabular-nums">{r.parts_cost ? formatXofWithCode(r.parts_cost) : "—"}</span>,
        }]
      : []),
  ];
  const table = useTableColumns("maintenance.history.journal", columns);
  const rows = table.sortRows(columnFilters.apply(journal.data?.rows ?? []));
  const span = table.visibleColumns.length;
  const loading = journal.isLoading;

  function openJob(row: JournalRow) {
    navigate(`/maintenance/jobs/${row.job_id}`, { state: { from: `${location.pathname}${location.search}` } });
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <FilterTabs<JournalStatus>
            options={STATUSES.map((value) => ({ value, label: t(`maintenance.history.journal.status.${value}` as const) }))}
            value={status}
            onChange={(value) => update("jstatus", value === "closed" ? null : value)}
          />
          <FilterTabs<KindFilter>
            options={KINDS.map((value) => ({ value, label: t(`maintenance.history.journal.kind.${value}` as const) }))}
            value={kind}
            onChange={(value) => update("kind", value === "all" ? null : value)}
          />
          {columnFilters.isActive && (
            <Button variant="ghost" size="sm" onClick={columnFilters.reset}>{t("common.clearFilters")}</Button>
          )}
        </div>
        <Button onClick={exportExcel} disabled={exporting || rows.length === 0} className="w-full sm:w-auto">
          <FileSpreadsheet className="h-4 w-4" />
          {t("maintenance.history.journal.export")}
        </Button>
      </div>

      {isMobile ? (
        <MobileCardList
          columns={table.visibleColumns}
          rows={rows}
          rowKey={(r) => r.job_id}
          loading={loading}
          emptyIcon={<ClipboardList className="h-5 w-5" />}
          emptyTitle={t("maintenance.history.journal.empty.title")}
          emptyDescription={t("maintenance.history.journal.empty.description")}
          onRowClick={openJob}
        />
      ) : (
        <Card>
          <CardContent className="p-0">
            <Table colWidths={table.colWidths}>
              <TableHeader>
                <TableRow>
                  {table.visibleColumns.map((column) => (
                    <ResizableTableHead
                      key={column.key}
                      width={table.getWidth(column.key)}
                      onResize={(width) => table.setWidth(column.key, width)}
                      className={column.headerClassName}
                      sortDirection={table.sortDirectionFor(column.key)}
                      onSort={column.sortValue ? () => table.toggleSort(column.key) : undefined}
                    >
                      {column.header}
                    </ResizableTableHead>
                  ))}
                </TableRow>
                <ColumnFilterRow cells={table.visibleColumns.map((column) => column.filterCell ?? { type: "blank" })} />
              </TableHeader>
              <TableBody>
                {loading &&
                  [0, 1, 2].map((index) => (
                    <TableRow key={`skeleton-${index}`}>
                      <TableCell colSpan={span}><Skeleton className="h-5 w-full" /></TableCell>
                    </TableRow>
                  ))}
                {!loading && rows.length === 0 && (
                  <TableRow className="hover:bg-transparent">
                    <TableCell colSpan={span} className="p-0">
                      <EmptyState
                        icon={<ClipboardList className="h-5 w-5" />}
                        illustration={<HistoryEmptyIllustration aria-hidden className="h-44 w-52" />}
                        title={t("maintenance.history.journal.empty.title")}
                        description={t("maintenance.history.journal.empty.description")}
                      />
                    </TableCell>
                  </TableRow>
                )}
                {!loading &&
                  rows.map((row) => (
                    <TableRow key={row.job_id} onClick={() => openJob(row)} className="cursor-pointer">
                      {table.visibleColumns.map((column) => (
                        <TableCell key={column.key} className={column.cellClassName}>{column.cell(row)}</TableCell>
                      ))}
                    </TableRow>
                  ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
```

The template-literal keys (`` `maintenance.history.journal.status.${value}` as const ``) type-check only if every combination exists in `i18n.en.ts` — Task 12 added all six.

- [ ] **Step 3: Type check**

Run (in `frontend/`): `npx tsc -b --force`
Expected: exit 0.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/maintenance/history/IndicatorsView.tsx frontend/src/features/maintenance/history/JournalView.tsx
git commit -m "feat(maintenance-ui): indicators per machine and the journal with Excel export"
```

---

### Task 16: The "Historique" tab

**Files:**
- Create: `frontend/src/features/maintenance/history/HistoryTab.tsx`
- Modify: `frontend/src/features/maintenance/MaintenancePage.tsx`

**Interfaces:**
- Consumes: Tasks 12, 14, 15.
- Produces: tab `?tab=history` (`&view=journal`, `&equipment=<id>`, `&from=&to=`).

- [ ] **Step 1: Write `HistoryTab.tsx`**

```tsx
import { useRef } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { AlertTriangle } from "lucide-react";
import { AppLoader } from "../../../components/patterns/AppLoader";
import { EmptyState } from "../../../components/patterns/EmptyState";
import { FilterTabs } from "../../../components/patterns/FilterTabs";
import { Select } from "../../../components/ui/select";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { apiErrorMessage } from "../jobs/jobFormat";
import { useHistoryIndicators, type MachineIndicators } from "./api";
import { usePeriod } from "./historyPeriod";
import { IndicatorsView } from "./IndicatorsView";
import { JournalView } from "./JournalView";
import { PeriodControl } from "./PeriodControl";

type HistoryView = "indicators" | "journal";

/**
 * Maintenance → Historique: per-machine indicators (production and maintenance side by side)
 * or the journal of closed interventions. Period, machine and view live in the URL.
 */
export function HistoryTab() {
  const { session } = useAuth();
  const token = session!.token;
  const { t } = useI18n();
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams, setSearchParams] = useSearchParams();
  const { period } = usePeriod();
  const view: HistoryView = searchParams.get("view") === "journal" ? "journal" : "indicators";
  const equipmentId = searchParams.get("equipment") ?? "";

  const indicators = useHistoryIndicators(token, period);
  // The branded loader shows once, on the tab's first load; a period change after that uses skeletons.
  const loadedOnce = useRef(false);
  if (indicators.data) loadedOnce.current = true;
  const firstLoad = indicators.isLoading && !loadedOnce.current;
  const machines = (indicators.data?.machines ?? []).slice().sort((a, b) => a.name.localeCompare(b.name));

  function update(key: string, value: string | null) {
    setSearchParams(
      (current) => {
        const next = new URLSearchParams(current);
        if (value === null) next.delete(key);
        else next.set(key, value);
        return next;
      },
      { replace: true },
    );
  }

  function openMachine(machine: MachineIndicators) {
    navigate(`/maintenance/equipment/${machine.equipment_id}?from=${period.from}&to=${period.to}`, {
      state: { from: `${location.pathname}${location.search}` },
    });
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <FilterTabs<HistoryView>
          options={[
            { value: "indicators", label: t("maintenance.history.view.indicators") },
            { value: "journal", label: t("maintenance.history.view.journal") },
          ]}
          value={view}
          onChange={(value) => update("view", value === "indicators" ? null : value)}
        />
        <div className="w-full sm:w-64">
          <Select aria-label={t("maintenance.history.machine.label")} value={equipmentId} onChange={(event) => update("equipment", event.target.value || null)}>
            <option value="">{t("maintenance.history.machine.all")}</option>
            {machines.map((machine) => (
              <option key={machine.equipment_id} value={machine.equipment_id}>
                {machine.code} — {machine.name}
              </option>
            ))}
          </Select>
        </div>
      </div>
      <PeriodControl />

      {firstLoad ? (
        <AppLoader className="py-16" />
      ) : indicators.isError ? (
        <EmptyState
          icon={<AlertTriangle className="h-5 w-5" />}
          title={t("maintenance.history.loadError")}
          description={apiErrorMessage(indicators.error, t("maintenance.history.loadError"))}
        />
      ) : view === "indicators" ? (
        <IndicatorsView data={indicators.data} isLoading={indicators.isFetching && !indicators.data} equipmentId={equipmentId} onOpen={openMachine} />
      ) : (
        <JournalView period={period} equipmentId={equipmentId} />
      )}
    </div>
  );
}
```

- [ ] **Step 2: Register the tab** in `MaintenancePage.tsx`:

```tsx
import HistorySvg from "../../assets/icons/maintenance/history.svg?react";
import { outlineIcon } from "../../components/patterns/outlineIcon";
import { HistoryTab } from "./history/HistoryTab";

const HistoryIcon = outlineIcon(HistorySvg);
```
and in `ALL_TABS`, right after the `jobs` entry:
```tsx
  { value: "history", labelKey: "maintenance.tabs.history", icon: HistoryIcon, Component: HistoryTab, permission: "maintenance.view_jobs" },
```

- [ ] **Step 3: Type check and look at it**

Run (in `frontend/`): `npx tsc -b --force` → exit 0.
Then with backend (8000) and Vite (5173) running and the Task 10 seed loaded, open `http://localhost:5173/maintenance?tab=history` as the demo user (private headless Chrome, session seeded over CDP — recipe in the user's memory `feedback_verify_frontend_in_repo`), screenshot at 1400 px and 390 px: the four stat cards, the grouped table, the journal view (`&view=journal`), and the Excel button downloading a file.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/maintenance/history/HistoryTab.tsx frontend/src/features/maintenance/MaintenancePage.tsx
git commit -m "feat(maintenance-ui): Historique tab -- indicators and journal over a shared period and machine filter"
```

---

### Task 17: The machine logbook page

**Files:**
- Create: `frontend/src/features/maintenance/history/EquipmentHistoryPage.tsx`
- Create: `frontend/src/features/maintenance/history/HistoryTimeline.tsx`
- Create: `frontend/src/features/maintenance/history/CheckpointList.tsx`
- Modify: `frontend/src/routes/router.tsx` (route), `frontend/src/features/maintenance/EquipmentTab.tsx` (History button), `frontend/src/features/maintenance/jobs/JobPage.tsx` (machine name links to the logbook)

**Interfaces:**
- Consumes: Tasks 11–14.
- Produces: route `/maintenance/equipment/:equipmentId` (`?from&to&point`); `<HistoryTimeline items />`; `<CheckpointList points onOpen />`. Task 18 adds the sheet to this page.

- [ ] **Step 1: Write `HistoryTimeline.tsx`**

```tsx
import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { motion, useReducedMotion } from "framer-motion";
import DowntimeSvg from "../../../assets/icons/production/downtime.svg?react";
import HistorySvg from "../../../assets/icons/maintenance/history.svg?react";
import CorrectiveSvg from "../../../assets/icons/maintenance/corrective.svg?react";
import PreventiveSvg from "../../../assets/icons/maintenance/preventive.svg?react";
import StatusChangeSvg from "../../../assets/icons/maintenance/status-change.svg?react";
import HistoryEmptyIllustration from "../../../assets/illustrations/maintenance/history-empty.svg?react";
import { EmptyState } from "../../../components/patterns/EmptyState";
import { FilterTabs } from "../../../components/patterns/FilterTabs";
import { outlineIcon } from "../../../components/patterns/outlineIcon";
import { Badge } from "../../../components/ui/badge";
import { formatXofWithCode } from "../../../lib/currency";
import { currentLocale, useI18n, type TranslationKey } from "../../../lib/i18n";
import { formatDuration } from "../../../lib/units";
import { cn } from "../../../lib/utils";
import { downtimeLabel } from "../../production/downtimeOptions";
import type { EquipmentStatus, JobStatus } from "../api";
import { formatDateTime, formatDay } from "../jobs/jobFormat";
import { JOB_KIND_LABEL_KEY, JOB_PRIORITY_LABEL_KEY, JOB_STATUS_BADGE_VARIANT, JOB_STATUS_LABEL_KEY } from "../labels";
import type { JournalRow, ProductionStopItem, TimelineItem } from "./api";
import { HISTORY_EASE } from "./IndicatorBlocks";
import { fill, monthKey } from "./historyFormat";

const DowntimeIcon = outlineIcon(DowntimeSvg);
const HistoryIcon = outlineIcon(HistorySvg);
const CorrectiveIcon = outlineIcon(CorrectiveSvg);
const PreventiveIcon = outlineIcon(PreventiveSvg);
const StatusChangeIcon = outlineIcon(StatusChangeSvg);

type TimelineFilter = "all" | "jobs" | "stops" | "status" | "issues";
const FILTERS: TimelineFilter[] = ["all", "jobs", "stops", "status", "issues"];
const LIVE: JobStatus[] = ["in_progress", "rework"];
const STATUS_TEXT: Record<EquipmentStatus, string> = { operational: "text-success", down: "text-destructive", maintenance: "text-warning" };

function matches(item: TimelineItem, filter: TimelineFilter): boolean {
  switch (filter) {
    case "all":
      return true;
    case "jobs":
      return item.kind === "job";
    case "stops":
      return item.kind === "production_stop";
    case "status":
      return item.kind === "status_change";
    case "issues":
      return (item.kind === "job" && item.job.outcomes.issue > 0) || (item.kind === "production_stop" && item.stop.downtime_type === "corrective");
  }
}

function keyOf(item: TimelineItem): string {
  if (item.kind === "job") return `job-${item.job.job_id}`;
  if (item.kind === "production_stop") return `stop-${item.stop.shift_report_id}-${item.stop.started_at}`;
  return `status-${item.at}-${item.to_status}`;
}

type Tone = "default" | "live" | "done" | "issue";

/** The dot on the spine. The live job's one is the view's single gold highlight. */
function Node({ tone, children }: { tone: Tone; children: ReactNode }) {
  return (
    <span
      className={cn(
        "absolute -left-[32px] top-2.5 grid h-6 w-6 place-items-center rounded-full border-2 bg-card",
        tone === "default" && "border-border text-primary",
        tone === "live" && "border-accent text-accent shadow-glow",
        tone === "done" && "border-success text-success",
        tone === "issue" && "border-destructive text-destructive",
      )}
    >
      {tone === "live" && <span aria-hidden className="absolute inset-[-2px] animate-ping rounded-full border-2 border-accent opacity-40 motion-reduce:hidden" />}
      {children}
    </span>
  );
}

function JobEntry({ job }: { job: JournalRow }) {
  const { t } = useI18n();
  const live = LIVE.includes(job.status);
  const open = job.status !== "closed" && job.status !== "cancelled";
  const tone: Tone = live ? "live" : job.status === "closed" ? (job.outcomes.issue > 0 ? "issue" : "done") : "default";
  const Icon = job.kind === "preventive" ? PreventiveIcon : CorrectiveIcon;
  const partLines = job.parts.issued_lines + job.parts.purchase_lines;
  return (
    <Link
      to={`/maintenance/jobs/${job.job_id}`}
      className={cn("relative block rounded-lg border border-border bg-card px-3 py-2.5 transition-colors hover:bg-muted/40", live && "border-accent/60")}
    >
      <Node tone={tone}><Icon className="h-3.5 w-3.5" /></Node>
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <p className="min-w-0 text-sm font-semibold">
          <span className="font-mono text-xs text-muted-foreground">{job.number}</span> · {job.title}
        </p>
        {live ? (
          <span className="inline-flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-[0.12em] text-accent">
            <span className="h-1.5 w-1.5 rounded-full bg-accent" />
            {t("maintenance.history.timeline.live")}
          </span>
        ) : (
          <span className="text-xs text-muted-foreground">{formatDay(job.date ?? job.created_at)}</span>
        )}
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
        <Badge variant={job.kind === "corrective" ? "destructive" : "primary"}>
          {t(JOB_KIND_LABEL_KEY[job.kind])}
          {job.priority === "urgent" ? ` · ${t(JOB_PRIORITY_LABEL_KEY.urgent)}` : ""}
        </Badge>
        {!live && <Badge variant={JOB_STATUS_BADGE_VARIANT[job.status]}>{t(JOB_STATUS_LABEL_KEY[job.status])}</Badge>}
        {job.chef_name && <span>{job.chef_name}</span>}
        {open ? (
          <span>{fill(t("maintenance.history.timeline.progress"), { done: job.checks_done, total: job.checks_total })}</span>
        ) : (
          <span>
            {fill(t("maintenance.history.journal.result"), { ok: job.outcomes.ok, issue: job.outcomes.issue, notDone: job.outcomes.not_done })}
          </span>
        )}
        {job.technician_seconds > 0 && <span className="tabular-nums">{formatDuration(job.technician_seconds / 60)}</span>}
        {partLines > 0 && (
          <span>
            {fill(t("maintenance.history.timeline.parts"), { n: partLines })}
            {job.parts_cost ? ` · ${formatXofWithCode(job.parts_cost)}` : ""}
          </span>
        )}
        {job.machine_stopped && <span>{t("maintenance.history.timeline.machineStopped")}</span>}
        {job.kind === "preventive" && job.closed_on_time !== null && (
          <span className={job.closed_on_time ? "text-success" : "text-destructive"}>
            {t(job.closed_on_time ? "maintenance.history.timeline.onTime" : "maintenance.history.timeline.late")}
          </span>
        )}
      </div>
    </Link>
  );
}

function StopEntry({ stop }: { stop: ProductionStopItem }) {
  const { t } = useI18n();
  const breakdown = stop.downtime_type === "corrective";
  return (
    <div className="relative rounded-lg border border-border bg-card px-3 py-2.5">
      <Node tone={breakdown ? "issue" : "default"}><DowntimeIcon className="h-3.5 w-3.5" /></Node>
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <p className="min-w-0 text-sm font-semibold">
          {t("maintenance.history.timeline.stop")}
          {stop.motif ? ` · ${downtimeLabel(t, "motif", stop.motif)}` : ""}
        </p>
        <span className="text-xs text-muted-foreground">{formatDateTime(stop.started_at)}</span>
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
        {stop.downtime_type && (
          <Badge variant={breakdown ? "destructive" : "default"}>
            {downtimeLabel(t, "type", stop.downtime_type)}
            {stop.classification ? ` · ${downtimeLabel(t, "classification", stop.classification)}` : ""}
          </Badge>
        )}
        <span className="tabular-nums">{formatDuration(stop.minutes)}</span>
        <span>
          {fill(t("maintenance.history.timeline.shift"), { date: formatDay(stop.report_date) })}
          {stop.team ? ` · ${stop.team}` : ""}
        </span>
        {stop.note && <span className="italic">“{stop.note}”</span>}
        {stop.corrective_action && <span>{fill(t("maintenance.history.timeline.correctiveAction"), { value: stop.corrective_action })}</span>}
      </div>
    </div>
  );
}

function StatusWord({ status }: { status: EquipmentStatus }) {
  const { t } = useI18n();
  return <span className={STATUS_TEXT[status]}>{t(`maintenance.equipment.status.${status}` as TranslationKey)}</span>;
}

function StatusEntry({ item }: { item: Extract<TimelineItem, { kind: "status_change" }> }) {
  const { t } = useI18n();
  const tone: Tone = item.to_status === "operational" ? "done" : item.to_status === "down" ? "issue" : "default";
  return (
    <div className="relative rounded-lg border border-border bg-card px-3 py-2.5">
      <Node tone={tone}><StatusChangeIcon className="h-3.5 w-3.5" /></Node>
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <p className="text-sm font-semibold">
          {t("maintenance.history.timeline.status")} <StatusWord status={item.from_status} /> → <StatusWord status={item.to_status} />
        </p>
        <span className="text-xs text-muted-foreground">{formatDateTime(item.at)}</span>
      </div>
      {item.actor_name && <p className="mt-1 text-xs text-muted-foreground">{fill(t("maintenance.history.timeline.by"), { name: item.actor_name })}</p>}
    </div>
  );
}

export function HistoryTimeline({ items }: { items: TimelineItem[] }) {
  const { t } = useI18n();
  const reduce = useReducedMotion();
  const [filter, setFilter] = useState<TimelineFilter>("all");
  const visible = items.filter((item) => matches(item, filter));
  const months: [string, TimelineItem[]][] = [];
  for (const item of visible) {
    const key = monthKey(item.at);
    const last = months[months.length - 1];
    if (last && last[0] === key) last[1].push(item);
    else months.push([key, [item]]);
  }
  const monthLabel = (key: string) =>
    new Intl.DateTimeFormat(currentLocale(), { month: "long", year: "numeric", timeZone: "UTC" }).format(new Date(`${key}-01T00:00:00Z`));

  return (
    <div>
      <div className="flex items-baseline justify-between px-4 pb-2 pt-3">
        <h2 className="text-sm font-semibold">{t("maintenance.history.timeline.title")}</h2>
        <span className="text-xs text-muted-foreground">{t("maintenance.history.timeline.hint")}</span>
      </div>
      <div className="px-4 pb-3">
        <FilterTabs<TimelineFilter>
          options={FILTERS.map((value) => ({ value, label: t(`maintenance.history.timeline.filter.${value}` as const) }))}
          value={filter}
          onChange={setFilter}
        />
      </div>
      {visible.length === 0 ? (
        <EmptyState
          icon={<HistoryIcon className="h-5 w-5" />}
          illustration={<HistoryEmptyIllustration aria-hidden className="h-44 w-52" />}
          title={t("maintenance.history.timeline.empty.title")}
          description={t("maintenance.history.timeline.empty.description")}
        />
      ) : (
        <div className="relative pb-4 pl-12 pr-4">
          <span aria-hidden className="absolute bottom-6 left-[27px] top-2 w-0.5 bg-gradient-to-b from-accent via-border to-border" />
          {months.map(([key, group]) => (
            <section key={key} className="space-y-2">
              <p className="pt-2 text-[10px] font-bold uppercase tracking-[0.18em] text-muted-foreground">{monthLabel(key)}</p>
              {group.map((item, index) => (
                <motion.div
                  key={keyOf(item)}
                  initial={reduce ? false : { opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.45, ease: HISTORY_EASE, delay: Math.min(index, 8) * 0.07 }}
                >
                  {item.kind === "job" ? <JobEntry job={item.job} /> : item.kind === "production_stop" ? <StopEntry stop={item.stop} /> : <StatusEntry item={item} />}
                </motion.div>
              ))}
            </section>
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Write `CheckpointList.tsx`**

```tsx
import { useState } from "react";
import { Badge } from "../../../components/ui/badge";
import { Button } from "../../../components/ui/button";
import { useI18n } from "../../../lib/i18n";
import { useIsMobile } from "../../../lib/useIsMobile";
import { cn } from "../../../lib/utils";
import { formatDay, formatMeasure } from "../jobs/jobFormat";
import { OUTCOME_LABEL_KEY } from "../labels";
import type { CheckpointSummary } from "./api";
import { fill, sparklinePoints } from "./historyFormat";

function Sparkline({ values }: { values: number[] }) {
  const points = sparklinePoints(values, 58, 20);
  const last = points[points.length - 1];
  return (
    <svg viewBox="0 0 58 20" className="h-5 w-14 shrink-0" aria-hidden>
      <polyline points={points.map((p) => `${p.x},${p.y}`).join(" ")} fill="none" className="stroke-primary" strokeWidth="1.6" strokeLinejoin="round" />
      <circle cx={last.x} cy={last.y} r="2.6" className="fill-accent" />
    </svg>
  );
}

/** The machine's checkpoints in map order; each opens its history. On a phone the list sits behind a toggle. */
export function CheckpointList({ points, onOpen }: { points: CheckpointSummary[]; onOpen: (checkpointId: string) => void }) {
  const { t } = useI18n();
  const isMobile = useIsMobile();
  const [open, setOpen] = useState(false);
  const shown = !isMobile || open;
  return (
    <div>
      <div className="flex items-baseline justify-between px-4 pb-2 pt-3">
        <h2 className="text-sm font-semibold">{t("maintenance.history.points.title")}</h2>
        <span className="text-xs text-muted-foreground">{fill(t("maintenance.history.points.count"), { n: points.length })}</span>
      </div>
      {isMobile && (
        <div className="px-4 pb-3">
          <Button variant="outline" size="sm" className="w-full" aria-expanded={open} onClick={() => setOpen((value) => !value)}>
            {open ? t("maintenance.history.points.hide") : fill(t("maintenance.history.points.show"), { n: points.length })}
          </Button>
        </div>
      )}
      {shown &&
        (points.length === 0 ? (
          <p className="px-4 pb-4 text-sm text-muted-foreground">{t("maintenance.history.points.none")}</p>
        ) : (
          <ul className="divide-y divide-border border-t border-border">
            {points.map((point, index) => (
              <li key={point.checkpoint_id}>
                <button
                  type="button"
                  onClick={() => onOpen(point.checkpoint_id)}
                  className="flex w-full items-center gap-3 px-4 py-2.5 text-left transition-colors hover:bg-muted/40"
                >
                  <span
                    className={cn(
                      "grid h-6 w-6 shrink-0 place-items-center rounded-full text-[11px] font-bold",
                      point.checks_count === 0
                        ? "bg-muted text-muted-foreground"
                        : point.last_outcome === "issue"
                          ? "bg-destructive text-destructive-foreground"
                          : "bg-primary text-primary-foreground",
                    )}
                  >
                    {index + 1}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium">
                      {point.label}
                      {point.archived && <span className="ml-1 text-xs text-muted-foreground">({t("maintenance.history.points.archived")})</span>}
                    </span>
                    <span className="block truncate text-xs text-muted-foreground">
                      {point.last_checked_at && point.last_outcome
                        ? `${formatDay(point.last_checked_at)} · ${t(OUTCOME_LABEL_KEY[point.last_outcome])}`
                        : t("maintenance.history.points.never")}
                    </span>
                  </span>
                  {point.recent_measures.length >= 2 && <Sparkline values={point.recent_measures.map((m) => m.value)} />}
                  {point.last_measured_value !== null && (
                    <span className="shrink-0 text-right text-xs tabular-nums text-muted-foreground">{formatMeasure(point.last_measured_value, point.measure_unit)}</span>
                  )}
                  {point.issues_count > 0 && (
                    <Badge variant="destructive">{fill(t("maintenance.history.points.issues"), { n: point.issues_count })}</Badge>
                  )}
                </button>
              </li>
            ))}
          </ul>
        ))}
    </div>
  );
}
```

- [ ] **Step 3: Write `EquipmentHistoryPage.tsx`**

```tsx
import { useRef } from "react";
import { Link, useLocation, useParams, useSearchParams } from "react-router-dom";
import { motion } from "framer-motion";
import { AlertTriangle, ArrowLeft, Printer } from "lucide-react";
import { AppLoader } from "../../../components/patterns/AppLoader";
import { EmptyState } from "../../../components/patterns/EmptyState";
import { Badge, type BadgeProps } from "../../../components/ui/badge";
import { Button } from "../../../components/ui/button";
import { Card } from "../../../components/ui/card";
import { useAuth } from "../../../lib/auth";
import { useI18n, type TranslationKey } from "../../../lib/i18n";
import type { EquipmentStatus } from "../api";
import { apiErrorMessage } from "../jobs/jobFormat";
import { useEquipmentHistory } from "./api";
import { CheckpointList } from "./CheckpointList";
import { fill } from "./historyFormat";
import { usePeriod } from "./historyPeriod";
import { HistoryTimeline } from "./HistoryTimeline";
import { IndicatorBlocks } from "./IndicatorBlocks";
import { MachinePhotoTile } from "./MachinePhoto";
import { PeriodControl } from "./PeriodControl";

const STATUS_VARIANT: Record<EquipmentStatus, BadgeProps["variant"]> = { operational: "success", down: "destructive", maintenance: "warning" };

/** /maintenance/equipment/:equipmentId — one machine's logbook (spec 2026-10-02 maintenance history). */
export function EquipmentHistoryPage() {
  const { equipmentId = "" } = useParams();
  const { session } = useAuth();
  const { t } = useI18n();
  const location = useLocation();
  const [, setSearchParams] = useSearchParams();
  const { period } = usePeriod();
  const history = useEquipmentHistory(session!.token, equipmentId, period);
  const backTo = (location.state as { from?: string } | null)?.from ?? "/maintenance?tab=history";
  const loadedOnce = useRef(false);
  if (history.data) loadedOnce.current = true;

  if (history.isLoading && !loadedOnce.current) return <AppLoader className="py-24" />;
  if (!history.data) {
    return (
      <EmptyState
        icon={<AlertTriangle className="h-5 w-5" />}
        title={t("maintenance.history.logbook.notFound")}
        description={apiErrorMessage(history.error, t("maintenance.history.loadError"))}
        action={
          <Button variant="outline" asChild>
            <Link to={backTo}>{t("maintenance.history.logbook.back")}</Link>
          </Button>
        }
      />
    );
  }

  const data = history.data;
  const machine = data.equipment;
  const jobs = data.timeline.filter((item) => item.kind === "job").length;
  const stops = data.timeline.filter((item) => item.kind === "production_stop").length;

  function openPoint(checkpointId: string | null) {
    setSearchParams(
      (current) => {
        const next = new URLSearchParams(current);
        if (checkpointId) next.set("point", checkpointId);
        else next.delete("point");
        return next;
      },
      { replace: true },
    );
  }

  return (
    <div className="space-y-4">
      <Button variant="ghost" size="sm" asChild>
        <Link to={backTo}>
          <ArrowLeft className="h-4 w-4" />
          {t("maintenance.history.logbook.back")}
        </Link>
      </Button>

      <motion.div initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}>
        <Card className="grid items-center gap-4 p-3 sm:grid-cols-[200px_1fr] lg:grid-cols-[200px_1fr_auto]">
          <MachinePhotoTile machine={machine} caption={t("maintenance.history.logbook.photoCaption")} className="h-40 sm:h-32" />
          <div className="min-w-0 space-y-1.5">
            <p className="text-[10px] font-semibold uppercase tracking-[0.22em] text-muted-foreground">{t("maintenance.history.logbook.eyebrow")}</p>
            <h1 className="break-words text-xl font-bold tracking-tight">{machine.name}</h1>
            <div className="flex flex-wrap gap-1.5">
              <Badge variant="primary">{machine.code}</Badge>
              {machine.production_stage && <Badge>{t(`maintenance.equipment.stage.${machine.production_stage}` as TranslationKey)}</Badge>}
              {machine.archived_at ? (
                <Badge variant="outline" dot>{t("maintenance.equipment.archived.badge")}</Badge>
              ) : (
                <Badge variant={STATUS_VARIANT[machine.status]} dot>{t(`maintenance.equipment.status.${machine.status}` as TranslationKey)}</Badge>
              )}
            </div>
            <p className="text-xs text-muted-foreground">{fill(t("maintenance.history.logbook.summary"), { jobs, stops })}</p>
          </div>
          <div className="flex flex-col gap-2 sm:col-span-2 lg:col-span-1 lg:items-end">
            <PeriodControl />
            <Button asChild className="w-full sm:w-auto">
              <Link to={`/maintenance/equipment/${equipmentId}/print?from=${period.from}&to=${period.to}`}>
                <Printer className="h-4 w-4" />
                {t("maintenance.history.logbook.print")}
              </Link>
            </Button>
          </div>
        </Card>
      </motion.div>

      <IndicatorBlocks
        production={data.indicators.production}
        maintenance={data.indicators.maintenance}
        costsVisible={data.costs_visible}
        productionAvailable={data.production_available}
      />

      <div className="grid gap-4 lg:grid-cols-[1.7fr_1fr]">
        <Card className="min-w-0">
          <HistoryTimeline items={data.timeline} />
        </Card>
        <Card className="min-w-0 self-start">
          <CheckpointList points={data.checkpoints} onOpen={openPoint} />
        </Card>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Route and entry points**

`frontend/src/routes/router.tsx` — import and add the route next to the other maintenance routes (inside the layout's children, before the job route):
```tsx
import { EquipmentHistoryPage } from "../features/maintenance/history/EquipmentHistoryPage";
...
  { path: "/maintenance/equipment/:equipmentId", element: <EquipmentHistoryPage /> },
```

`EquipmentTab.tsx` — add `History` to the lucide import, `const canViewJobs = useHasPermission("maintenance.view_jobs");` next to `canManageCheckpoints`, and in the `action` column render this button first in **both** branches (archived and active), wrapping the archived branch's single button in a fragment:
```tsx
{canViewJobs && (
  <Button size="sm" variant="outline" asChild>
    <Link to={`/maintenance/equipment/${item.id}`}>
      <History className="h-3.5 w-3.5" />
      {t("maintenance.equipment.history")}
    </Link>
  </Button>
)}
```

`jobs/JobPage.tsx` (the header, around line 273) — make the machine line a link (`Link` is already imported there; add it if not):
```tsx
<p className="break-words text-sm text-muted-foreground">
  <Link to={`/maintenance/equipment/${job.equipment_id}`} className="underline-offset-2 hover:text-primary hover:underline">
    {job.equipment_code} — {job.equipment_name}
  </Link>
</p>
```

- [ ] **Step 5: Type check and look at it**

Run (in `frontend/`): `npx tsc -b --force` → exit 0.
Open `http://localhost:5173/maintenance/equipment/<demo machine id>` (private headless Chrome, demo session) at 1400 px and 390 px: header with the machine photo, both blocks, timeline with month headers and coloured nodes, checkpoints with sparklines; on the phone the blocks are 2×2 and the points sit behind the toggle. Click a timeline job → job page; its machine name → back to the logbook.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/maintenance/history/EquipmentHistoryPage.tsx frontend/src/features/maintenance/history/HistoryTimeline.tsx frontend/src/features/maintenance/history/CheckpointList.tsx frontend/src/routes/router.tsx frontend/src/features/maintenance/EquipmentTab.tsx frontend/src/features/maintenance/jobs/JobPage.tsx
git commit -m "feat(maintenance-ui): machine logbook -- photo header, both blocks, timeline and checkpoints"
```

---

### Task 18: The checkpoint history sheet

**Files:**
- Create: `frontend/src/features/maintenance/history/CheckpointHistorySheet.tsx`
- Create: `frontend/src/features/maintenance/history/MeasureTrendChart.tsx`
- Modify: `frontend/src/features/maintenance/history/EquipmentHistoryPage.tsx`

**Interfaces:**
- Consumes: Task 13 `Sheet`, Task 12 `useCheckpointHistory`, `PinnedPhoto` (`map/PinnedPhoto.tsx`), `EntryPhoto` (`jobs/EntryPhoto.tsx`), `useAuthedImage` + `fetchViewImageBlob`.
- Produces: `<CheckpointHistorySheet checkpointId onClose />`, `<MeasureTrendChart measures unit />`.

Read the `dataviz` skill before writing the chart.

- [ ] **Step 1: Write `MeasureTrendChart.tsx`**

```tsx
import type { ReactElement } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { Outcome } from "../api";
import { formatDay, formatMeasure } from "../jobs/jobFormat";
import type { CheckpointHistory } from "./api";

// Recharts takes literal colours: the brand navy, the gold highlight, the error red.
const NAVY = "#123B6D";
const GOLD = "#F5A900";
const RED = "#E5484D";

interface DotArgs {
  cx?: number;
  cy?: number;
  index?: number;
  payload?: { outcome: Outcome };
}

/** Measured values over time. No limit lines: no limits are recorded anywhere. The latest value is gold, an anomaly red. */
export function MeasureTrendChart({ measures, unit }: { measures: CheckpointHistory["measures"]; unit: string | null }) {
  const data = measures.map((measure) => ({ ...measure, label: formatDay(measure.at) }));
  const lastIndex = data.length - 1;
  const renderDot = (raw: unknown): ReactElement => {
    const { cx, cy, index, payload } = raw as DotArgs;
    if (cx === undefined || cy === undefined) return <g key={`dot-${index}`} />;
    const last = index === lastIndex;
    const fill = last ? GOLD : payload?.outcome === "issue" ? RED : NAVY;
    return <circle key={`dot-${index}`} cx={cx} cy={cy} r={last ? 5 : 3} fill={fill} stroke="#FFFFFF" strokeWidth={last ? 2 : 1} />;
  };
  return (
    <div className="h-36 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 12, right: 12, bottom: 0, left: -12 }}>
          <CartesianGrid stroke="hsl(214 20% 92%)" vertical={false} />
          <XAxis dataKey="label" tick={{ fontSize: 10 }} tickLine={false} axisLine={false} minTickGap={24} />
          <YAxis tick={{ fontSize: 10 }} tickLine={false} axisLine={false} width={44} domain={["auto", "auto"]} />
          <Tooltip formatter={(value) => formatMeasure(Number(value), unit)} />
          <Line type="monotone" dataKey="value" stroke={NAVY} strokeWidth={2} dot={renderDot} activeDot={{ r: 5, fill: GOLD }} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
```

- [ ] **Step 2: Write `CheckpointHistorySheet.tsx`**

```tsx
import { Link } from "react-router-dom";
import { MapPin } from "lucide-react";
import CheckpointNeverIllustration from "../../../assets/illustrations/maintenance/checkpoint-never.svg?react";
import { EmptyState } from "../../../components/patterns/EmptyState";
import { Badge } from "../../../components/ui/badge";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "../../../components/ui/sheet";
import { Skeleton } from "../../../components/ui/skeleton";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { formatDuration } from "../../../lib/units";
import { cn } from "../../../lib/utils";
import { fetchViewImageBlob } from "../api";
import { EntryPhoto } from "../jobs/EntryPhoto";
import { formatDay, formatMeasure } from "../jobs/jobFormat";
import { CHECK_ACTION_ICON, CHECK_ACTION_LABEL_KEY, CHECK_STATE_LABEL_KEY, OUTCOME_BADGE_VARIANT, OUTCOME_LABEL_KEY } from "../labels";
import { PinnedPhoto } from "../map/PinnedPhoto";
import { useAuthedImage } from "../useAuthedImage";
import { useCheckpointHistory, type CheckpointHistory, type PointAttempt, type PointCheck } from "./api";
import { fill } from "./historyFormat";
import { MeasureTrendChart } from "./MeasureTrendChart";

function Figure({ label, value, danger = false }: { label: string; value: string; danger?: boolean }) {
  return (
    <div className="px-4 py-2.5">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={cn("text-base font-bold tabular-nums", danger && "text-destructive")}>{value}</p>
    </div>
  );
}

function AttemptCard({ check, attempt, numbered, unit }: { check: PointCheck; attempt: PointAttempt; numbered: boolean; unit: string | null }) {
  const { t } = useI18n();
  const entry = attempt.entries[attempt.entries.length - 1];
  const rejected = attempt.review?.verdict === "rejected";
  return (
    <div className={cn("rounded-lg border border-border px-3 py-2.5", rejected && "border-destructive/40 bg-destructive/5")}>
      <div className="flex items-center justify-between gap-2">
        <Link to={`/maintenance/jobs/${check.job_id}`} className="min-w-0 truncate text-sm font-semibold text-primary hover:underline">
          {check.job_number} · {formatDay(entry?.finished_at)}
          {numbered && ` · ${fill(t("maintenance.history.point.attempt"), { n: attempt.attempt })}`}
        </Link>
        {attempt.review ? (
          <Badge variant={rejected ? "destructive" : "success"}>{t(CHECK_STATE_LABEL_KEY[attempt.review.verdict])}</Badge>
        ) : (
          entry && <Badge variant={OUTCOME_BADGE_VARIANT[entry.outcome]}>{t(OUTCOME_LABEL_KEY[entry.outcome])}</Badge>
        )}
      </div>
      {entry && (
        <p className="mt-1 text-xs text-muted-foreground">
          {entry.performer_name} · {formatDuration(entry.duration_seconds / 60)} (
          {t(entry.duration_source === "manual" ? "maintenance.history.point.manual" : "maintenance.history.point.timer")})
          {entry.measured_value !== null && (
            <>
              {" · "}
              <b className={cn("text-foreground", entry.outcome === "issue" && "text-destructive")}>{formatMeasure(entry.measured_value, unit)}</b>
            </>
          )}
          {" · "}
          {t(OUTCOME_LABEL_KEY[entry.outcome])}
          {entry.note && ` · “${entry.note}”`}
        </p>
      )}
      {attempt.review?.reason && (
        <p className="mt-1 text-xs text-muted-foreground">
          {fill(t("maintenance.history.point.review"), { reason: attempt.review.reason, name: attempt.review.reviewer_name })}
        </p>
      )}
      {entry?.has_photo && <EntryPhoto entryId={entry.entry_id} className="mt-2 h-16 w-20" />}
    </div>
  );
}

function PointHistory({ data, photoUrl }: { data: CheckpointHistory; photoUrl: string | undefined }) {
  const { t } = useI18n();
  const point = data.checkpoint;
  const ActionIcon = CHECK_ACTION_ICON[point.action];
  return (
    <div className="pb-6">
      <header className="space-y-1 border-b border-border px-5 pb-3 pr-12 pt-5">
        <p className="text-[10px] font-semibold uppercase tracking-[0.22em] text-muted-foreground">
          {t("maintenance.history.point.eyebrow")} · {point.equipment_name}
        </p>
        <SheetTitle className="flex items-center gap-2 text-base font-bold">
          <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-accent text-[11px] font-bold text-accent-foreground">1</span>
          {point.label}
        </SheetTitle>
        <SheetDescription className="flex flex-wrap items-center gap-1.5 text-xs">
          <ActionIcon className="h-3.5 w-3.5" />
          {t(CHECK_ACTION_LABEL_KEY[point.action])}
          {point.measure_unit && ` · ${point.measure_unit}`}
          {point.instructions && ` · ${point.instructions}`}
        </SheetDescription>
      </header>
      {photoUrl && (
        <div className="bg-[radial-gradient(circle_at_50%_60%,#1A4A85,#071F43)] p-3">
          <PinnedPhoto src={photoUrl} pins={[{ id: point.id, x: point.x_pct, y: point.y_pct, n: 1, tone: "active" }]} />
          <p className="mt-1 text-[10px] uppercase tracking-[0.14em] text-white/80">{point.view_label}</p>
        </div>
      )}
      <div className="grid grid-cols-3 divide-x divide-border border-b border-border">
        <Figure label={t("maintenance.history.point.checked")} value={fill(t("maintenance.history.point.times"), { n: data.summary.checks_count })} />
        <Figure label={t("maintenance.history.point.issues")} value={String(data.summary.issues_count)} danger={data.summary.issues_count > 0} />
        <Figure label={t("maintenance.history.point.last")} value={formatDay(data.summary.last_checked_at)} />
      </div>
      {data.measures.length > 0 && (
        <div className="px-5 pt-4">
          <div className="flex items-baseline justify-between gap-2">
            <p className="text-sm font-semibold">{fill(t("maintenance.history.point.measures"), { unit: point.measure_unit ?? "" })}</p>
            <p className="text-xs text-muted-foreground">{t("maintenance.history.point.noLimits")}</p>
          </div>
          <MeasureTrendChart measures={data.measures} unit={point.measure_unit} />
        </div>
      )}
      <div className="space-y-2 px-5 pt-4">
        <p className="text-sm font-semibold">{t("maintenance.history.point.checks")}</p>
        {data.summary.checks_count === 0 ? (
          <EmptyState
            icon={<MapPin className="h-5 w-5" />}
            illustration={<CheckpointNeverIllustration aria-hidden className="h-40 w-48" />}
            title={t("maintenance.history.point.empty.title")}
            description={t("maintenance.history.point.empty.description")}
          />
        ) : (
          data.checks.map((check) =>
            check.attempts.length === 0 ? (
              <p key={check.check_id} className="rounded-lg border border-dashed border-border px-3 py-2 text-xs text-muted-foreground">
                {check.job_number} · {t("maintenance.history.point.notYet")}
              </p>
            ) : (
              check.attempts.map((attempt) => (
                <AttemptCard
                  key={`${check.check_id}-${attempt.attempt}`}
                  check={check}
                  attempt={attempt}
                  numbered={check.attempts.length > 1}
                  unit={point.measure_unit}
                />
              ))
            ),
          )
        )}
      </div>
    </div>
  );
}

/** A checkpoint's whole history, in a panel sliding over the logbook (`?point=<id>`). */
export function CheckpointHistorySheet({ checkpointId, onClose }: { checkpointId: string | null; onClose: () => void }) {
  const { session } = useAuth();
  const { t } = useI18n();
  const history = useCheckpointHistory(session!.token, checkpointId);
  const data = history.data && history.data.checkpoint.id === checkpointId ? history.data : undefined;
  const { url } = useAuthedImage(fetchViewImageBlob, data?.checkpoint.view_id, data?.checkpoint.view_version);
  return (
    <Sheet open={checkpointId !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent closeLabel={t("common.close")}>
        {data ? (
          <PointHistory data={data} photoUrl={url} />
        ) : (
          <div className="space-y-3 p-5">
            <SheetTitle className="sr-only">{t("maintenance.history.point.eyebrow")}</SheetTitle>
            <Skeleton className="h-6 w-2/3" />
            <Skeleton className="h-40 w-full" />
            <Skeleton className="h-24 w-full" />
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}
```

- [ ] **Step 3: Mount the sheet on the logbook** — in `EquipmentHistoryPage.tsx`:

```tsx
import { CheckpointHistorySheet } from "./CheckpointHistorySheet";
...
  const [searchParams, setSearchParams] = useSearchParams();   // replaces `const [, setSearchParams] = ...`
  const pointId = searchParams.get("point");
...
      {/* last child of the page's root <div> */}
      <CheckpointHistorySheet checkpointId={pointId} onClose={() => openPoint(null)} />
```

- [ ] **Step 4: Type check and look at it**

Run (in `frontend/`): `npx tsc -b --force` → exit 0.
On the logbook, click a measure point: the sheet slides in with the photo and gold pin, three figures, the chart (latest dot gold, the anomaly red), and the attempts (the rejected one tinted, with its reason). At 390 px the sheet fills the screen. Escape and the close button both clear `?point=`.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/maintenance/history/CheckpointHistorySheet.tsx frontend/src/features/maintenance/history/MeasureTrendChart.tsx frontend/src/features/maintenance/history/EquipmentHistoryPage.tsx
git commit -m "feat(maintenance-ui): checkpoint history sheet with measure trend and every attempt"
```

---

### Task 19: The printable machine sheet

**Files:**
- Create: `frontend/src/features/maintenance/history/EquipmentHistoryPrintPage.tsx`
- Modify: `frontend/src/routes/router.tsx`

**Interfaces:**
- Consumes: Task 13 `PrintShell` (`brand` slot), Task 12 `useEquipmentHistory`, `usePeriod`.
- Produces: route `/maintenance/equipment/:equipmentId/print?from&to`.

- [ ] **Step 1: Write the page**

```tsx
import type { ReactNode } from "react";
import { useParams } from "react-router-dom";
import { AlertTriangle } from "lucide-react";
import LogoMark from "../../../assets/animations/logo-mark.svg?react";
import { AppLoader } from "../../../components/patterns/AppLoader";
import { BrandWordmark } from "../../../components/patterns/BrandLoader";
import { EmptyState } from "../../../components/patterns/EmptyState";
import { PRINT_TABLE, PRINT_TD, PRINT_TH, PrintShell } from "../../../components/patterns/PrintShell";
import { useAuth } from "../../../lib/auth";
import { formatXofWithCode } from "../../../lib/currency";
import { useI18n, type TranslationKey } from "../../../lib/i18n";
import { formatDuration } from "../../../lib/units";
import { downtimeLabel } from "../../production/downtimeOptions";
import { formatDateTime, formatDay, formatMeasure } from "../jobs/jobFormat";
import { JOB_KIND_LABEL_KEY, OUTCOME_LABEL_KEY } from "../labels";
import { useEquipmentHistory, type TimelineItem } from "./api";
import { fill, minutesOrDash } from "./historyFormat";
import { usePeriod } from "./historyPeriod";

type Of<K extends TimelineItem["kind"]> = Extract<TimelineItem, { kind: K }>;

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-2 break-inside-avoid">
      <h2 className="border-b border-[#F5A900] pb-1 text-sm font-semibold uppercase tracking-wide">{title}</h2>
      {children}
    </section>
  );
}

function Pairs({ rows }: { rows: [string, string][] }) {
  return (
    <table className={PRINT_TABLE}>
      <tbody>
        {rows.map(([label, value]) => (
          <tr key={label}>
            <td className={PRINT_TD}>{label}</td>
            <td className={`${PRINT_TD} text-right font-semibold`}>{value}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** /maintenance/equipment/:id/print — the machine's history on paper (browser print → PDF). */
export function EquipmentHistoryPrintPage() {
  const { equipmentId = "" } = useParams();
  const { session } = useAuth();
  const { t } = useI18n();
  const { period } = usePeriod();
  const history = useEquipmentHistory(session!.token, equipmentId, period);

  if (history.isLoading) return <AppLoader className="py-24" />;
  if (!history.data) {
    return <EmptyState icon={<AlertTriangle className="h-5 w-5" />} title={t("maintenance.history.logbook.notFound")} description={t("maintenance.history.loadError")} />;
  }

  const data = history.data;
  const production = data.indicators.production;
  const maintenance = data.indicators.maintenance;
  const jobs = data.timeline.filter((item): item is Of<"job"> => item.kind === "job");
  const stops = data.timeline.filter((item): item is Of<"production_stop"> => item.kind === "production_stop");
  const changes = data.timeline.filter((item): item is Of<"status_change"> => item.kind === "status_change");
  const status = (value: string) => t(`maintenance.equipment.status.${value}` as TranslationKey);
  const none = <p className="text-xs text-neutral-500">{t("maintenance.history.print.none")}</p>;

  return (
    <PrintShell
      title={t("maintenance.history.print.title")}
      subtitle={
        <>
          {data.equipment.code} — {data.equipment.name}
          <br />
          {fill(t("maintenance.history.print.period"), { from: formatDay(period.from), to: formatDay(period.to) })}
        </>
      }
      company={null}
      brand={
        <div className="flex items-center gap-3 text-[#123B6D]">
          <LogoMark aria-hidden className="h-10 w-10" />
          <BrandWordmark tone="light" size={20} />
        </div>
      }
      backTo={`/maintenance/equipment/${equipmentId}?from=${period.from}&to=${period.to}`}
    >
      <div className="grid grid-cols-2 gap-6 print:grid-cols-2">
        <Section title={t("maintenance.history.production.title")}>
          {production ? (
            <Pairs
              rows={[
                [t("maintenance.history.kpi.breakdowns"), `${production.breakdowns} · ${formatDuration(production.breakdown_minutes)}`],
                [t("maintenance.history.kpi.mtbf"), minutesOrDash(production.mtbf_minutes)],
                [t("maintenance.history.kpi.mttr"), minutesOrDash(production.mttr_minutes)],
                [t("maintenance.history.kpi.allStops"), `${production.stops} · ${formatDuration(production.stop_minutes)}`],
              ]}
            />
          ) : (
            <p className="text-xs text-neutral-500">{t("maintenance.history.production.unavailable")}</p>
          )}
        </Section>
        <Section title={t("maintenance.history.maintenance.title")}>
          <Pairs
            rows={[
              [t("maintenance.history.kpi.breakdowns"), String(maintenance.breakdowns)],
              [t("maintenance.history.kpi.immobilisation"), formatDuration(maintenance.immobilised_minutes)],
              [t("maintenance.history.kpi.betweenBreakdowns"), minutesOrDash(maintenance.calendar_mtbf_minutes)],
              [
                t("maintenance.history.column.preventive"),
                maintenance.preventive.due === 0
                  ? "—"
                  : `${maintenance.preventive.closed}/${maintenance.preventive.due} · ${fill(t("maintenance.history.preventive.overdue"), { n: maintenance.preventive.overdue })}`,
              ],
              [t("maintenance.history.kpi.technician"), formatDuration(maintenance.technician_seconds / 60)],
              ...(data.costs_visible && maintenance.parts_cost !== null
                ? ([[t("maintenance.history.kpi.partsCost"), formatXofWithCode(maintenance.parts_cost)]] as [string, string][])
                : []),
            ]}
          />
        </Section>
      </div>

      <Section title={t("maintenance.history.print.jobs")}>
        {jobs.length === 0 ? none : (
          <table className={PRINT_TABLE}>
            <thead>
              <tr>
                <th className={PRINT_TH}>{t("maintenance.history.journal.column.number")}</th>
                <th className={PRINT_TH}>{t("maintenance.history.journal.column.date")}</th>
                <th className={PRINT_TH}>{t("maintenance.history.journal.column.kind")}</th>
                <th className={PRINT_TH}>{t("maintenance.history.journal.column.title")}</th>
                <th className={PRINT_TH}>{t("maintenance.history.journal.column.result")}</th>
                <th className={PRINT_TH}>{t("maintenance.history.journal.column.time")}</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map(({ job }) => (
                <tr key={job.job_id}>
                  <td className={PRINT_TD}>{job.number}</td>
                  <td className={PRINT_TD}>{formatDay(job.date ?? job.created_at)}</td>
                  <td className={PRINT_TD}>{t(JOB_KIND_LABEL_KEY[job.kind])}</td>
                  <td className={PRINT_TD}>{job.title}</td>
                  <td className={PRINT_TD}>
                    {fill(t("maintenance.history.journal.result"), { ok: job.outcomes.ok, issue: job.outcomes.issue, notDone: job.outcomes.not_done })}
                  </td>
                  <td className={PRINT_TD}>{formatDuration(job.technician_seconds / 60)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>

      <Section title={t("maintenance.history.print.stops")}>
        {stops.length === 0 ? none : (
          <table className={PRINT_TABLE}>
            <thead>
              <tr>
                <th className={PRINT_TH}>{t("maintenance.history.journal.column.date")}</th>
                <th className={PRINT_TH}>{t("maintenance.history.print.column.duration")}</th>
                <th className={PRINT_TH}>{t("maintenance.history.journal.column.kind")}</th>
                <th className={PRINT_TH}>{t("maintenance.history.print.column.system")}</th>
                <th className={PRINT_TH}>{t("maintenance.history.print.column.reason")}</th>
                <th className={PRINT_TH}>{t("maintenance.history.print.column.note")}</th>
              </tr>
            </thead>
            <tbody>
              {stops.map(({ stop }) => (
                <tr key={`${stop.shift_report_id}-${stop.started_at}`}>
                  <td className={PRINT_TD}>{formatDateTime(stop.started_at)}</td>
                  <td className={PRINT_TD}>{formatDuration(stop.minutes)}</td>
                  <td className={PRINT_TD}>{stop.downtime_type ? downtimeLabel(t, "type", stop.downtime_type) : "—"}</td>
                  <td className={PRINT_TD}>{stop.classification ? downtimeLabel(t, "classification", stop.classification) : "—"}</td>
                  <td className={PRINT_TD}>{stop.motif ? downtimeLabel(t, "motif", stop.motif) : "—"}</td>
                  <td className={PRINT_TD}>{stop.note ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>

      <Section title={t("maintenance.history.print.statusChanges")}>
        {changes.length === 0 ? none : (
          <table className={PRINT_TABLE}>
            <thead>
              <tr>
                <th className={PRINT_TH}>{t("maintenance.history.journal.column.date")}</th>
                <th className={PRINT_TH}>{t("maintenance.history.print.column.from")}</th>
                <th className={PRINT_TH}>{t("maintenance.history.print.column.to")}</th>
                <th className={PRINT_TH}>{t("maintenance.history.print.column.by")}</th>
              </tr>
            </thead>
            <tbody>
              {changes.map((change) => (
                <tr key={`${change.at}-${change.to_status}`}>
                  <td className={PRINT_TD}>{formatDateTime(change.at)}</td>
                  <td className={PRINT_TD}>{status(change.from_status)}</td>
                  <td className={PRINT_TD}>{status(change.to_status)}</td>
                  <td className={PRINT_TD}>{change.actor_name ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>

      <Section title={t("maintenance.history.print.points")}>
        {data.checkpoints.length === 0 ? none : (
          <table className={PRINT_TABLE}>
            <thead>
              <tr>
                <th className={PRINT_TH}>{t("maintenance.history.points.title")}</th>
                <th className={PRINT_TH}>{t("maintenance.history.point.checked")}</th>
                <th className={PRINT_TH}>{t("maintenance.history.point.issues")}</th>
                <th className={PRINT_TH}>{t("maintenance.history.point.last")}</th>
                <th className={PRINT_TH}>{t("maintenance.history.print.column.lastMeasure")}</th>
              </tr>
            </thead>
            <tbody>
              {data.checkpoints.map((point) => (
                <tr key={point.checkpoint_id}>
                  <td className={PRINT_TD}>{point.label}</td>
                  <td className={PRINT_TD}>{point.checks_count}</td>
                  <td className={PRINT_TD}>{point.issues_count}</td>
                  <td className={PRINT_TD}>
                    {point.last_checked_at && point.last_outcome
                      ? `${formatDay(point.last_checked_at)} · ${t(OUTCOME_LABEL_KEY[point.last_outcome])}`
                      : t("maintenance.history.points.never")}
                  </td>
                  <td className={PRINT_TD}>{point.last_measured_value !== null ? formatMeasure(point.last_measured_value, point.measure_unit) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>

      <p className="text-[10px] text-neutral-500">
        {fill(t("maintenance.history.print.printedOn"), { date: formatDateTime(new Date().toISOString()), user: session!.email })}
      </p>
    </PrintShell>
  );
}
```

- [ ] **Step 2: Route** — in `router.tsx`, next to the logbook route:

```tsx
import { EquipmentHistoryPrintPage } from "../features/maintenance/history/EquipmentHistoryPrintPage";
...
  { path: "/maintenance/equipment/:equipmentId/print", element: <EquipmentHistoryPrintPage /> },
```

- [ ] **Step 3: Type check and print it**

Run (in `frontend/`): `npx tsc -b --force` → exit 0.
Open the logbook → "Fiche PDF": the sheet shows the logo + wordmark, the machine and period, both blocks side by side, the four tables. In headless Chrome, `Page.printToPDF` (or Ctrl+P → Save as PDF) gives a multi-page A4 PDF with no sidebar and nothing clipped.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/maintenance/history/EquipmentHistoryPrintPage.tsx frontend/src/routes/router.tsx
git commit -m "feat(maintenance-ui): printable machine history sheet"
```

---

### Task 20: Whole-feature verification

**Files:** none (verification only; fix in the owning task's files if anything fails).

- [ ] **Step 1: Backend suites**

Run (in `backend/`): `.venv/Scripts/python -m pytest modules/maintenance modules/production/api/test_stops_analytics_integration.py modules/warehouse/api/test_valuation_service_integration.py core/test_audit_log_index_integration.py core/migrations/test_migration_data_guard.py -q`
Expected: all PASS, and the summary shows tests **run**, not skipped.

- [ ] **Step 2: Frontend checks**

Run (in `frontend/`): `npx vitest run && npx tsc -b --force`
Expected: all vitest tests PASS; `tsc` exit 0.

- [ ] **Step 3: Browser pass (private headless Chrome, demo session)**

With the Task 10 seed loaded, capture at 1400 px and at 390 px:
1. `/maintenance?tab=history` — stat cards count up, grouped header, unattributed note when present.
2. `/maintenance?tab=history&view=journal` — filters, column filter row, Excel download opens in Excel/LibreOffice with French headers and a totals row.
3. `/maintenance/equipment/<id>` — photo tile, both blocks (system bars, preventive ring), timeline (gold live node if a job is in progress), checkpoints with sparklines.
4. `?point=<measure point>` — sheet with chart and attempts.
5. `/maintenance/equipment/<id>/print` — print preview.
6. Emulate `prefers-reduced-motion: reduce` (CDP `Emulation.setEmulatedMedia`) on 1 and 3: no count-up, no ring/bar animation, illustrations static.
7. As a user without `warehouse.view_valuation` (revoke on the demo user temporarily via `DELETE /core/users/{id}/permissions/...` or use a second user): no cost column, no cost tile, cost absent from the Excel.

- [ ] **Step 4: Report** — list anything that differs from the spec (`docs/superpowers/specs/2026-10-02-maintenance-history-design.md`) with the screenshot that shows it, instead of claiming completion.
