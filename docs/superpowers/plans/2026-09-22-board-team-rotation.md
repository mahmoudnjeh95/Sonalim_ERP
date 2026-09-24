# Board team rotation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the production board's static per-shift roster pill with a computed 4-team rotation, shown as one status circle per team on every OF card (grey/blue/green/red), blinking on the team currently on shift only when the board shows today.

**Architecture:** A new plant-wide `production.team_rotation` table stores one anchor point per team (its stop in a repeating Morning→Afternoon→Night→Rest cycle on one reference date). A pure domain function projects that anchor forward or backward to any date. `DashboardLinesService.get_lines` gains a `date` parameter, computes each team's slot for that date, and looks up that slot's shift report status per line. The old `production.line_team_roster` table and its settings UI are removed, replaced by a rotation settings form. Team *names* are unchanged — they still come from `core.report_options` (kind `team`).

**Tech Stack:** Python/FastAPI/psycopg backend (`backend/modules/production`), React/TypeScript frontend (`frontend/src/features/production`), Postgres migrations.

**Spec:** `docs/superpowers/specs/2026-09-22-board-team-rotation-design.md`

## Global Constraints

- Rotation is one shared schedule for the whole plant (not per line) — spec decision 1.
- Cycle order is the plant's shifts sorted by start time, then Rest — spec decision 2.
- Circle colours: grey = no report, blue = submitted, green = validated, red = returned — spec decision 5.
- Blink only on the team whose slot is the shift running now, and only when the board shows today — spec decision 6.
- `production.line_team_roster` and its settings UI are removed, not kept alongside the new one — spec decision 7.
- Every new/changed UI string goes through `t()` with both an English and a French entry — spec decision 8.
- No invented defaults: settings start empty; a tenant that hasn't configured shifts/rotation sees "not set", never a guess.

---

## Task 1: Rotation formula and validation (domain)

**Files:**
- Modify: `backend/modules/production/domain/dashboard.py`
- Test: `backend/modules/production/domain/test_dashboard.py`

**Interfaces:**
- Produces: `team_rotation_schedule(*, shifts: list[str], rotation: list[tuple[str, datetime.date, int]], date: datetime.date) -> list[dict]` — each dict is `{"team": str, "shift": str | None}` (`None` = resting that day).
- Produces: `validate_team_rotation(entries: list[dict], *, num_shifts: int) -> Result[None]` — `entries` are `{"team": str, "anchor_date": datetime.date, "anchor_stop": int}`. Error codes: `WRONG_TEAM_COUNT`, `INVALID_ENTRY`, `DUPLICATE_ENTRY`.

- [ ] **Step 1: Write the failing tests**

Add to `backend/modules/production/domain/test_dashboard.py` (append at the end of the file, and add `team_rotation_schedule` and `validate_team_rotation` to the existing `from modules.production.domain.dashboard import (...)` block at the top):

```python
def _rotation():
    # The owner's own anchor: on 2026-09-19, B was on the first shift, C on the
    # second, D on the third, A resting.
    return [
        ("B", datetime.date(2026, 9, 19), 0),
        ("C", datetime.date(2026, 9, 19), 1),
        ("D", datetime.date(2026, 9, 19), 2),
        ("A", datetime.date(2026, 9, 19), 3),
    ]


def test_team_rotation_schedule_on_the_anchor_date():
    shifts = ["Shift 1", "Shift 2", "Shift 3"]
    schedule = team_rotation_schedule(shifts=shifts, rotation=_rotation(), date=datetime.date(2026, 9, 19))
    assert {(e["team"], e["shift"]) for e in schedule} == {
        ("B", "Shift 1"), ("C", "Shift 2"), ("D", "Shift 3"), ("A", None),
    }


def test_team_rotation_schedule_advances_one_stop_per_day():
    shifts = ["Shift 1", "Shift 2", "Shift 3"]
    schedule = team_rotation_schedule(shifts=shifts, rotation=_rotation(), date=datetime.date(2026, 9, 22))
    assert {(e["team"], e["shift"]) for e in schedule} == {
        ("C", "Shift 1"), ("D", "Shift 2"), ("A", "Shift 3"), ("B", None),
    }


def test_team_rotation_schedule_wraps_after_a_full_cycle_and_works_before_the_anchor():
    shifts = ["Shift 1", "Shift 2", "Shift 3"]
    # The cycle is 4 days long (3 shifts + rest), so 4 days later matches the anchor exactly.
    after = team_rotation_schedule(shifts=shifts, rotation=_rotation(), date=datetime.date(2026, 9, 23))
    assert {(e["team"], e["shift"]) for e in after} == {
        ("B", "Shift 1"), ("C", "Shift 2"), ("D", "Shift 3"), ("A", None),
    }
    before = team_rotation_schedule(shifts=shifts, rotation=_rotation(), date=datetime.date(2026, 9, 18))
    assert {(e["team"], e["shift"]) for e in before} == {
        ("C", "Shift 1"), ("D", "Shift 2"), ("A", "Shift 3"), ("B", None),
    }


def test_team_rotation_needs_exactly_shifts_plus_one_teams():
    entries = [
        {"team": "A", "anchor_date": datetime.date(2026, 9, 19), "anchor_stop": 0},
        {"team": "B", "anchor_date": datetime.date(2026, 9, 19), "anchor_stop": 1},
    ]
    result = validate_team_rotation(entries, num_shifts=3)
    assert isinstance(result, Err) and result.code == "WRONG_TEAM_COUNT"


def test_team_rotation_rejects_two_teams_on_the_same_stop():
    entries = [
        {"team": "A", "anchor_date": datetime.date(2026, 9, 19), "anchor_stop": 0},
        {"team": "B", "anchor_date": datetime.date(2026, 9, 19), "anchor_stop": 0},
        {"team": "C", "anchor_date": datetime.date(2026, 9, 19), "anchor_stop": 2},
        {"team": "D", "anchor_date": datetime.date(2026, 9, 19), "anchor_stop": 3},
    ]
    result = validate_team_rotation(entries, num_shifts=3)
    assert isinstance(result, Err) and result.code == "DUPLICATE_ENTRY"


def test_team_rotation_rejects_two_teams_with_the_same_name():
    entries = [
        {"team": "A", "anchor_date": datetime.date(2026, 9, 19), "anchor_stop": 0},
        {"team": "a", "anchor_date": datetime.date(2026, 9, 19), "anchor_stop": 1},
        {"team": "C", "anchor_date": datetime.date(2026, 9, 19), "anchor_stop": 2},
        {"team": "D", "anchor_date": datetime.date(2026, 9, 19), "anchor_stop": 3},
    ]
    result = validate_team_rotation(entries, num_shifts=3)
    assert isinstance(result, Err) and result.code == "DUPLICATE_ENTRY"


def test_team_rotation_rejects_mismatched_anchor_dates():
    entries = [
        {"team": "A", "anchor_date": datetime.date(2026, 9, 19), "anchor_stop": 0},
        {"team": "B", "anchor_date": datetime.date(2026, 9, 20), "anchor_stop": 1},
        {"team": "C", "anchor_date": datetime.date(2026, 9, 19), "anchor_stop": 2},
        {"team": "D", "anchor_date": datetime.date(2026, 9, 19), "anchor_stop": 3},
    ]
    result = validate_team_rotation(entries, num_shifts=3)
    assert isinstance(result, Err) and result.code == "INVALID_ENTRY"


def test_team_rotation_accepts_a_complete_valid_set():
    result = validate_team_rotation(
        [{"team": t, "anchor_date": d, "anchor_stop": s} for t, d, s in _rotation()], num_shifts=3
    )
    assert isinstance(result, Ok)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/Scripts/python.exe -m pytest modules/production/domain/test_dashboard.py -q`
Expected: `ImportError` (or collection failure) — `team_rotation_schedule` and `validate_team_rotation` don't exist yet.

- [ ] **Step 3: Implement the domain functions**

Append to `backend/modules/production/domain/dashboard.py` (after `direction`, at the end of the file):

```python
def team_rotation_schedule(
    *, shifts: list[str], rotation: list[tuple[str, datetime.date, int]], date: datetime.date
) -> list[dict]:
    """Where each team in the 4-team rotation stands on `date`: which of
    `shifts` it is on, or `None` when it is that team's turn to rest.

    `shifts` are the plant's configured shifts, in cycle order (stop 0 is the
    first shift of the day, `len(shifts)` is Rest) -- callers pass them sorted
    by start time, the same order the rest of the board already sorts shifts
    in. `rotation` is one `(team, anchor_date, anchor_stop)` per team:
    `anchor_stop` is where that team stood in the cycle on `anchor_date`. Every
    team advances one stop for every day that passes (or goes back one for
    every day before `anchor_date`); the whole calendar is built from that one
    recorded anchor, nothing else is guessed.
    """
    stops = len(shifts) + 1
    schedule = []
    for team, anchor_date, anchor_stop in rotation:
        stop = (anchor_stop + (date - anchor_date).days) % stops
        schedule.append({"team": team, "shift": shifts[stop] if stop < len(shifts) else None})
    return schedule


def validate_team_rotation(entries: list[dict], *, num_shifts: int) -> Result[None]:
    """A plant-wide team rotation needs exactly one team per stop in the cycle:
    one for each configured shift, plus one resting. Every team shares the same
    anchor date; nothing here guesses at a team name or a stop left out."""
    stops = num_shifts + 1
    if len(entries) != stops:
        return Err("WRONG_TEAM_COUNT", f"the rotation needs exactly {stops} teams (one per shift, plus rest)")
    anchor_dates = {entry["anchor_date"] for entry in entries}
    if len(anchor_dates) != 1:
        return Err("INVALID_ENTRY", "every team must share the same anchor date")
    seen_teams: set[str] = set()
    seen_stops: set[int] = set()
    for entry in entries:
        team = entry["team"].strip()
        stop = entry["anchor_stop"]
        if not team:
            return Err("INVALID_ENTRY", "a rotation entry needs a team")
        if not (0 <= stop < stops):
            return Err("INVALID_ENTRY", f"anchor_stop must be between 0 and {stops - 1}")
        key = team.lower()
        if key in seen_teams:
            return Err("DUPLICATE_ENTRY", f"team {team!r} appears twice")
        seen_teams.add(key)
        if stop in seen_stops:
            return Err("DUPLICATE_ENTRY", f"two teams share stop {stop}")
        seen_stops.add(stop)
    return Ok(None)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && .venv/Scripts/python.exe -m pytest modules/production/domain/test_dashboard.py -q`
Expected: PASS (all tests in the file, old and new).

- [ ] **Step 5: Commit**

```bash
git add backend/modules/production/domain/dashboard.py backend/modules/production/domain/test_dashboard.py
git commit -m "Add the 4-team rotation formula and its validation"
```

---

## Task 2: Migration — team_rotation table replaces line_team_roster

**Files:**
- Create: `backend/modules/production/migrations/0057_production_team_rotation.sql`
- Modify: `backend/scripts/reset_operational_data.py:137,148`

**Interfaces:**
- Produces: table `production.team_rotation (tenant_id, team, anchor_date, anchor_stop)`, `PRIMARY KEY (tenant_id, team)`.
- Consumes: nothing (schema-only task).

- [ ] **Step 1: Write the migration**

Create `backend/modules/production/migrations/0057_production_team_rotation.sql`:

```sql
-- Replaces line_team_roster: that table could only ever hold one team per
-- shift (one row per work_center_id + shift), which cannot express a 4-team
-- rotation with a resting team. This table anchors the whole plant's rotation
-- instead: on `anchor_date`, each team sits at `anchor_stop` in the cycle
-- [shift_0, shift_1, ..., shift_(n-1), rest] (n = the plant's configured shift
-- count, sorted by start time; `anchor_stop = n` means resting). A team's stop
-- on any other date is (anchor_stop + (date - anchor_date).days) mod (n + 1) --
-- see modules/production/domain/dashboard.py:team_rotation_schedule. All rows
-- for a tenant share the same anchor_date (enforced in the service, not here,
-- same as every other replace-the-whole-list setting on this dashboard).
CREATE TABLE production.team_rotation (
    tenant_id TEXT NOT NULL,
    team TEXT NOT NULL,
    anchor_date DATE NOT NULL,
    anchor_stop INTEGER NOT NULL CHECK (anchor_stop >= 0),
    PRIMARY KEY (tenant_id, team)
);

DROP TABLE production.line_team_roster;
```

- [ ] **Step 2: Update the go-live reset script's table list**

In `backend/scripts/reset_operational_data.py`, remove line 137 (`"production.line_team_roster",`) and add `"production.team_rotation",` between the existing `"production.store_roles",` (line 148) and `"production.waste_types",` (line 149) entries, so the config-table group reads:

```python
    "production.shift_windows",
    "production.store_roles",
    "production.team_rotation",
    "production.waste_types",
    "production.work_centers",
```

- [ ] **Step 3: Apply the migration against the dev/test database and verify**

Migrations run automatically from `core.migrations.runner.apply_all_migrations()`, called at app/worker startup (`app/main.py`, `worker/main.py`) — there is no standalone migration CLI in this repo. Apply it directly:

Run: `cd backend && DATABASE_URL=postgresql://erp:erp@localhost:5432/erp PYTHONPATH=. .venv/Scripts/python.exe -c "from core.migrations.runner import apply_all_migrations; apply_all_migrations()"`
Expected: no error. Then confirm with `psql postgresql://erp:erp@localhost:5432/erp -c '\d production.team_rotation'` (shows the new table) and `-c '\d production.line_team_roster'` (reports it no longer exists).

- [ ] **Step 4: Commit**

```bash
git add backend/modules/production/migrations/0057_production_team_rotation.sql backend/scripts/reset_operational_data.py
git commit -m "Replace line_team_roster with the team_rotation table"
```

---

## Task 3: Settings service and endpoint for the rotation

**Files:**
- Modify: `backend/modules/production/api/dashboard_settings_service.py`
- Modify: `backend/modules/production/api/router.py:2612-2670` (roster request models and endpoint)
- Test: `backend/modules/production/api/test_dashboard_settings_integration.py`

**Interfaces:**
- Consumes: `validate_team_rotation` from `modules.production.domain.dashboard` (Task 1).
- Produces: `DashboardSettingsService.replace_team_rotation(*, tenant_id: str, actor_id: str, entries: list[dict]) -> Result[list[dict]]`, where each output dict is `{"team": str, "anchor_date": str (ISO), "anchor_stop": int}`. `get_settings(...)["team_rotation"]` returns the same shape. Error codes: `NO_SHIFTS_CONFIGURED` (in addition to the domain's own codes).
- Produces: `PUT /production/dashboard/settings/team-rotation` (replaces `PUT /production/dashboard/settings/roster`, which is removed).

- [ ] **Step 1: Write the failing tests**

In `backend/modules/production/api/test_dashboard_settings_integration.py`:

Replace this line:
```python
    assert DashboardSettingsService(db).get_settings(tenant_id=TENANT) == {
        "shift_windows": [],
        "roster": [],
        "store_roles": [],
    }
```
with:
```python
    assert DashboardSettingsService(db).get_settings(tenant_id=TENANT) == {
        "shift_windows": [],
        "team_rotation": [],
        "store_roles": [],
    }
```

Delete `test_roster_round_trip_and_one_team_per_line_and_shift` and `test_roster_entry_needs_line_shift_and_team` entirely (they test the API being removed).

Add these tests after `test_shift_windows_reject_a_zero_length_shift_and_a_repeated_name`:

```python
def test_team_rotation_needs_shifts_configured_first(db, actor):
    result = DashboardSettingsService(db).replace_team_rotation(
        tenant_id=TENANT, actor_id=actor, entries=[{"team": "A", "anchor_date": "2026-09-19", "anchor_stop": 0}]
    )
    assert isinstance(result, Err) and result.code == "NO_SHIFTS_CONFIGURED"


def test_team_rotation_round_trip(db, actor):
    service = DashboardSettingsService(db)
    service.replace_shift_windows(
        tenant_id=TENANT, actor_id=actor,
        windows=[ShiftWindow(shift="Shift 1", start=T(7, 0), end=T(15, 0)), ShiftWindow(shift="Shift 2", start=T(15, 0), end=T(23, 0))],
    )
    entries = [
        {"team": "B", "anchor_date": "2026-09-19", "anchor_stop": 0},
        {"team": "C", "anchor_date": "2026-09-19", "anchor_stop": 1},
        {"team": "A", "anchor_date": "2026-09-19", "anchor_stop": 2},
    ]
    assert isinstance(service.replace_team_rotation(tenant_id=TENANT, actor_id=actor, entries=entries), Ok)
    stored = service.get_settings(tenant_id=TENANT)["team_rotation"]
    assert {(r["team"], r["anchor_date"], r["anchor_stop"]) for r in stored} == {
        ("B", "2026-09-19", 0), ("C", "2026-09-19", 1), ("A", "2026-09-19", 2),
    }


def test_team_rotation_rejects_the_wrong_number_of_teams(db, actor):
    service = DashboardSettingsService(db)
    service.replace_shift_windows(
        tenant_id=TENANT, actor_id=actor,
        windows=[ShiftWindow(shift="Shift 1", start=T(7, 0), end=T(15, 0)), ShiftWindow(shift="Shift 2", start=T(15, 0), end=T(23, 0))],
    )
    result = service.replace_team_rotation(
        tenant_id=TENANT, actor_id=actor, entries=[{"team": "A", "anchor_date": "2026-09-19", "anchor_stop": 0}]
    )
    assert isinstance(result, Err) and result.code == "WRONG_TEAM_COUNT"


def test_replacing_team_rotation_drops_what_it_leaves_out(db, actor):
    service = DashboardSettingsService(db)
    service.replace_shift_windows(tenant_id=TENANT, actor_id=actor, windows=[ShiftWindow(shift="Shift 1", start=T(7, 0), end=T(15, 0))])
    service.replace_team_rotation(
        tenant_id=TENANT, actor_id=actor,
        entries=[{"team": "A", "anchor_date": "2026-09-19", "anchor_stop": 0}, {"team": "B", "anchor_date": "2026-09-19", "anchor_stop": 1}],
    )
    service.replace_team_rotation(
        tenant_id=TENANT, actor_id=actor,
        entries=[{"team": "C", "anchor_date": "2026-09-20", "anchor_stop": 0}, {"team": "D", "anchor_date": "2026-09-20", "anchor_stop": 1}],
    )
    assert {r["team"] for r in service.get_settings(tenant_id=TENANT)["team_rotation"]} == {"C", "D"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && DATABASE_URL=postgresql://erp:erp@localhost:5432/erp PYTHONPATH=. .venv/Scripts/python.exe -m pytest modules/production/api/test_dashboard_settings_integration.py -q`
Expected: FAIL — `AttributeError: 'DashboardSettingsService' object has no attribute 'replace_team_rotation'`, and the `get_settings` equality test fails because it still returns `"roster"`.

- [ ] **Step 3: Implement the service and router changes**

In `backend/modules/production/api/dashboard_settings_service.py`, add `import datetime` at the top and change the import line to also pull in the new domain helpers:

```python
from modules.production.domain.dashboard import (
    STORE_ROLES,
    ShiftWindow,
    shift_length_minutes,
    validate_shift_window,
    validate_team_rotation,
)
```

Replace the `roster` block inside `get_settings` (the query and the dict key) with:

```python
        rotation = self._connection.execute(
            "SELECT team, anchor_date, anchor_stop FROM production.team_rotation WHERE tenant_id = %s ORDER BY anchor_stop",
            (tenant_id,),
        ).fetchall()
```
and in the returned dict, replace `"roster": [{"work_center_id": w, "shift": s, "team": t} for w, s, t in roster],` with:
```python
            "team_rotation": [{"team": t, "anchor_date": d.isoformat(), "anchor_stop": s} for t, d, s in rotation],
```

Replace the entire `replace_roster` method with:

```python
    def replace_team_rotation(self, *, tenant_id: str, actor_id: str, entries: list[dict]) -> Result[list[dict]]:
        num_shifts = len(self.list_shift_windows(tenant_id=tenant_id))
        if num_shifts == 0:
            return Err("NO_SHIFTS_CONFIGURED", "configure the plant's shifts before the team rotation")

        cleaned = []
        for entry in entries:
            team = (entry.get("team") or "").strip()
            raw_date = entry.get("anchor_date")
            try:
                anchor_date = raw_date if isinstance(raw_date, datetime.date) else datetime.date.fromisoformat(str(raw_date))
            except (TypeError, ValueError):
                return Err("INVALID_ENTRY", "a rotation entry needs a valid anchor date")
            anchor_stop = entry.get("anchor_stop")
            if not team or not isinstance(anchor_stop, int):
                return Err("INVALID_ENTRY", "a rotation entry needs a team and its stop in the cycle")
            cleaned.append({"team": team, "anchor_date": anchor_date, "anchor_stop": anchor_stop})

        check = validate_team_rotation(cleaned, num_shifts=num_shifts)
        if isinstance(check, Err):
            return check

        self._connection.execute("DELETE FROM production.team_rotation WHERE tenant_id = %s", (tenant_id,))
        for row in cleaned:
            self._connection.execute(
                "INSERT INTO production.team_rotation (tenant_id, team, anchor_date, anchor_stop) VALUES (%s, %s, %s, %s)",
                (tenant_id, row["team"], row["anchor_date"], row["anchor_stop"]),
            )
        result = [{"team": r["team"], "anchor_date": r["anchor_date"].isoformat(), "anchor_stop": r["anchor_stop"]} for r in cleaned]
        self._audit(tenant_id, actor_id, "team_rotation", result)
        return Ok(result)
```

In `backend/modules/production/api/router.py`, replace the `RosterEntryRequest`/`ReplaceRosterRequest` classes (lines 2612-2619) with:

```python
class TeamRotationEntryRequest(BaseModel):
    team: str
    anchor_date: datetime.date
    anchor_stop: int


class ReplaceTeamRotationRequest(BaseModel):
    items: list[TeamRotationEntryRequest]
```

Replace the `replace_line_roster` endpoint (lines 2661-2670) with:

```python
@router.put("/dashboard/settings/team-rotation")
def replace_team_rotation(
    body: ReplaceTeamRotationRequest,
    tenant: TenantContext = Depends(require_permission("production.manage_dashboard_settings")),
) -> list[dict]:
    with get_connection() as connection:
        result = DashboardSettingsService(connection).replace_team_rotation(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            entries=[{"team": i.team, "anchor_date": i.anchor_date.isoformat(), "anchor_stop": i.anchor_stop} for i in body.items],
        )
        return _settings_result(connection, result)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && DATABASE_URL=postgresql://erp:erp@localhost:5432/erp PYTHONPATH=. .venv/Scripts/python.exe -m pytest modules/production/api/test_dashboard_settings_integration.py -q`
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add backend/modules/production/api/dashboard_settings_service.py backend/modules/production/api/router.py backend/modules/production/api/test_dashboard_settings_integration.py
git commit -m "Replace the roster settings endpoint with the team rotation"
```

---

## Task 4: Board endpoint — date-scoped team status per line

**Files:**
- Modify: `backend/modules/production/api/dashboard_lines_service.py`
- Modify: `backend/modules/production/api/router.py:2685-2696`
- Test: `backend/modules/production/api/test_dashboard_lines_integration.py`

**Interfaces:**
- Consumes: `team_rotation_schedule` from `modules.production.domain.dashboard` (Task 1); `production.team_rotation` and `production.shift_reports` tables.
- Produces: `DashboardLinesService.get_lines(*, tenant_id: str, at: datetime.time, date: datetime.date, today: datetime.date) -> dict`, where each entry in `lines[i]` now has `team_status: list[{"team": str, "shift": str | None, "status": str | None, "is_current": bool}]` instead of `roster`. `status` is one of `"open" | "submitted" | "returned" | "validated" | None` (`None` = no report for that slot).
- Produces: `GET /production/dashboard/lines` gains a `date` query parameter (optional, defaults to the server's today).

- [ ] **Step 1: Write the failing tests**

In `backend/modules/production/api/test_dashboard_lines_integration.py`, replace the `_lines` helper:

```python
def _lines(db, at=T(8, 4), date=datetime.date(2026, 9, 19), today=datetime.date(2026, 9, 19)):
    return DashboardLinesService(db).get_lines(tenant_id=TENANT, at=at, date=date, today=today)
```

Delete `test_roster_lists_every_shift_and_flags_the_current_one` and `test_nothing_is_current_when_no_shift_windows_are_configured` (they exercise the removed roster API), and add these in their place:

```python
def test_team_status_is_empty_when_no_rotation_is_configured(db, env):
    _line(db, "L1")
    payload = _lines(db)
    assert payload["current_shift"] is None
    assert _by_code(payload)["L1"]["team_status"] == []


def test_team_status_lists_every_team_with_the_shift_it_is_on_and_flags_the_current_one(db, env):
    line_id = _line(db, "L1")
    settings = DashboardSettingsService(db)
    settings.replace_shift_windows(
        tenant_id=TENANT, actor_id=env["actor"],
        windows=[
            ShiftWindow(shift="Shift 1", start=T(7, 0), end=T(15, 0)),
            ShiftWindow(shift="Shift 2", start=T(15, 0), end=T(23, 0)),
            ShiftWindow(shift="Shift 3", start=T(23, 0), end=T(7, 0)),
        ],
    )
    settings.replace_team_rotation(
        tenant_id=TENANT, actor_id=env["actor"],
        entries=[
            {"team": "B", "anchor_date": "2026-09-19", "anchor_stop": 0},
            {"team": "C", "anchor_date": "2026-09-19", "anchor_stop": 1},
            {"team": "D", "anchor_date": "2026-09-19", "anchor_stop": 2},
            {"team": "A", "anchor_date": "2026-09-19", "anchor_stop": 3},
        ],
    )
    payload = _lines(db, at=T(8, 4), date=datetime.date(2026, 9, 19), today=datetime.date(2026, 9, 19))
    assert payload["current_shift"]["shift"] == "Shift 1"
    team_status = _by_code(payload)["L1"]["team_status"]
    assert {(e["team"], e["shift"], e["is_current"]) for e in team_status} == {
        ("B", "Shift 1", True), ("C", "Shift 2", False), ("D", "Shift 3", False), ("A", None, False),
    }
    # The rotation moves forward: three days later a different team is on Shift 1.
    later = _by_code(_lines(db, at=T(8, 4), date=datetime.date(2026, 9, 22), today=datetime.date(2026, 9, 22)))["L1"]["team_status"]
    assert {(e["team"], e["shift"]) for e in later} == {
        ("C", "Shift 1"), ("D", "Shift 2"), ("A", "Shift 3"), ("B", None),
    }


def test_team_status_colour_follows_the_shift_report_for_that_slot(db, env):
    line_id = _line(db, "L1")
    settings = DashboardSettingsService(db)
    settings.replace_shift_windows(
        tenant_id=TENANT, actor_id=env["actor"],
        windows=[ShiftWindow(shift="Shift 1", start=T(7, 0), end=T(15, 0)), ShiftWindow(shift="Shift 2", start=T(15, 0), end=T(23, 0))],
    )
    settings.replace_team_rotation(
        tenant_id=TENANT, actor_id=env["actor"],
        entries=[
            {"team": "B", "anchor_date": "2026-09-19", "anchor_stop": 0},
            {"team": "C", "anchor_date": "2026-09-19", "anchor_stop": 1},
            {"team": "A", "anchor_date": "2026-09-19", "anchor_stop": 2},
        ],
    )
    for shift, report_status in (("Shift 1", "validated"), ("Shift 2", "returned")):
        db.execute(
            "INSERT INTO production.shift_reports (id, tenant_id, work_center_id, report_date, shift, status) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (str(ULID()), TENANT, line_id, datetime.date(2026, 9, 19), shift, report_status),
        )
    # Viewed as a past day (today is the 20th): the colours reflect the reports, nothing blinks.
    team_status = _by_code(_lines(db, date=datetime.date(2026, 9, 19), today=datetime.date(2026, 9, 20)))["L1"]["team_status"]
    assert {(e["team"], e["status"]) for e in team_status} == {("B", "validated"), ("C", "returned"), ("A", None)}
    assert all(not e["is_current"] for e in team_status)
```

No new imports are needed for these tests: `DashboardSettingsService` and `ULID` are both already imported at the top of this file.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && DATABASE_URL=postgresql://erp:erp@localhost:5432/erp PYTHONPATH=. .venv/Scripts/python.exe -m pytest modules/production/api/test_dashboard_lines_integration.py -q`
Expected: FAIL — `TypeError: get_lines() got an unexpected keyword argument 'date'`.

- [ ] **Step 3: Implement the service and router changes**

Replace the full contents of `backend/modules/production/api/dashboard_lines_service.py` with:

```python
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
```

In `backend/modules/production/api/router.py`, replace the `get_dashboard_lines` endpoint (lines 2685-2696) with:

```python
@router.get("/dashboard/lines")
def get_dashboard_lines(
    at: datetime.time | None = Query(default=None, description="Plant-local clock time, HH:MM. Defaults to the server's."),
    date: datetime.date | None = Query(default=None, description="Which day's board to show. Defaults to the server's today."),
    tenant: TenantContext = Depends(require_permission("production.view_work_orders")),
) -> dict:
    """The live board: each line with the OFs open on it, every machine declared
    on it (with its stage once the plant has set one), and the 4-team rotation
    for `date`, each team's slot coloured by that line's shift report."""
    with get_connection() as connection:
        today = datetime.date.today()
        return DashboardLinesService(connection).get_lines(
            tenant_id=tenant.tenant_id,
            at=at or datetime.datetime.now().time().replace(second=0, microsecond=0),
            date=date or today,
            today=today,
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && DATABASE_URL=postgresql://erp:erp@localhost:5432/erp PYTHONPATH=. .venv/Scripts/python.exe -m pytest modules/production/api/test_dashboard_lines_integration.py -q`
Expected: PASS (all tests, old and new).

- [ ] **Step 5: Run the full production suite to catch anything else touching `roster`/`get_lines`**

Run: `cd backend && DATABASE_URL=postgresql://erp:erp@localhost:5432/erp PYTHONPATH=. .venv/Scripts/python.exe -m pytest modules/production -q`
Expected: PASS. If anything else references `line_team_roster`, `replace_roster`, or `DashboardLine.roster`, fix it here before moving on (a grep for `line_team_roster` and `"roster"` across `backend/` should now come back empty outside of git history).

- [ ] **Step 6: Commit**

```bash
git add backend/modules/production/api/dashboard_lines_service.py backend/modules/production/api/router.py backend/modules/production/api/test_dashboard_lines_integration.py
git commit -m "Compute the board's team status from the rotation and shift reports"
```

---

## Task 5: Frontend API types and calls

**Files:**
- Modify: `frontend/src/features/production/board/api.ts`

**Interfaces:**
- Consumes: nothing new (matches Task 3 and Task 4's response shapes exactly).
- Produces: `TeamStatusEntry`, `BoardLine.team_status`, `getBoardLines(token, at, date)`, `DashboardSettings.team_rotation`, `replaceTeamRotation`.

- [ ] **Step 1: Update the types and functions**

In `frontend/src/features/production/board/api.ts`, delete the `RosterEntry` interface (lines 21-28) and replace it with:

```ts
export interface TeamStatusEntry {
  team: string;
  /** null for the team resting that day. */
  shift: string | null;
  /** null when no report exists yet for that slot. */
  status: LiveStatus | null;
  is_current: boolean;
}
```

In `BoardLine`, replace `roster: RosterEntry[];` with `team_status: TeamStatusEntry[];`.

Replace:
```ts
export function getBoardLines(token: string, at: string) {
  return apiFetch<BoardLines>(`/production/dashboard/lines?at=${encodeURIComponent(at)}`, { token });
}
```
with:
```ts
export function getBoardLines(token: string, at: string, date: string) {
  return apiFetch<BoardLines>(
    `/production/dashboard/lines?at=${encodeURIComponent(at)}&date=${encodeURIComponent(date)}`,
    { token },
  );
}
```

In `DashboardSettings`, replace `roster: { work_center_id: string; shift: string; team: string }[];` with `team_rotation: { team: string; anchor_date: string; anchor_stop: number }[];`.

Replace:
```ts
export const replaceRoster = (token: string, items: DashboardSettings["roster"]) => replaceSection(token, "roster", items);
```
with:
```ts
export const replaceTeamRotation = (token: string, items: DashboardSettings["team_rotation"]) =>
  replaceSection(token, "team-rotation", items);
```

- [ ] **Step 2: Typecheck**

Run: `cd frontend && npx tsc -b --force`
Expected: errors in `LinesBoard.tsx` and `DashboardSettingsCard.tsx` (they still reference `RosterEntry`, `line.roster`, `replaceRoster`) — that's expected, fixed in Tasks 6 and 7. Confirm the errors are only in those two files and mention exactly the removed names.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/production/board/api.ts
git commit -m "Replace the roster API types with team status and team rotation"
```

---

## Task 6: Board UI — team status circles per OF card

**Files:**
- Modify: `frontend/src/features/production/board/LinesBoard.tsx`
- Modify: `frontend/src/features/production/board/ProductionBoard.tsx`

**Interfaces:**
- Consumes: `TeamStatusEntry`, `BoardLine.team_status`, `getBoardLines(token, at, date)` (Task 5).
- Produces: `TeamStatusPills` component (replaces `RosterPills`), rendered from `OfCard`.

- [ ] **Step 1: Replace `RosterPills` in `LinesBoard.tsx`**

Change the type import: replace `RosterEntry,` with `TeamStatusEntry,` in the `import type { ... } from "./api";` block.

Replace the whole `RosterPills` function (lines 117-134) with:

```tsx
const TEAM_STATUS_TONE: Record<"none" | LiveStatus, string> = {
  none: "bg-muted text-muted-foreground",
  open: "bg-muted text-muted-foreground",
  submitted: "bg-primary/10 text-primary",
  validated: "bg-success/10 text-success",
  returned: "bg-destructive-soft text-destructive",
};

function TeamStatusPills({ teamStatus }: { teamStatus: TeamStatusEntry[] }) {
  return (
    <div className="flex items-start gap-1">
      {teamStatus.map((entry) => (
        <div
          key={entry.team}
          className={cn("flex w-[52px] flex-col items-center text-[10.5px] text-muted-foreground", entry.is_current && "board-team-now")}
          title={entry.shift ?? undefined}
        >
          <span className={cn("board-avatar h-[26px] w-[26px] rounded-full", TEAM_STATUS_TONE[entry.status ?? "none"])} aria-hidden="true" />
          <b className="max-w-full truncate text-[11.5px] text-foreground">{entry.team}</b>
        </div>
      ))}
    </div>
  );
}
```

This drops the `UserRound` icon and the shift start/end times (the circle itself is now the whole point — colour and blink — and the team's own time slot is no longer fixed, since it changes with the rotation). `UserRound` is now unused in this file (its only other appearance was this component) — remove it from the `import { ChevronRight, UserRound } from "lucide-react";` line, leaving `import { ChevronRight } from "lucide-react";`. `shiftColor` stays imported: it is still used at line 317 (the shift-output bar chart), unrelated to this change.

In `OfCard`, replace:
```tsx
        {line.roster.length ? (
          <RosterPills roster={line.roster} />
        ) : (
          <p className="max-w-[12rem] text-xs text-muted-foreground">{t("production.board.roster.notSet.title")}</p>
        )}
```
with:
```tsx
        {line.team_status.length ? (
          <TeamStatusPills teamStatus={line.team_status} />
        ) : (
          <p className="max-w-[12rem] text-xs text-muted-foreground">{t("production.board.roster.notSet.title")}</p>
        )}
```

- [ ] **Step 2: Pass the selected day through to the lines query in `ProductionBoard.tsx`**

Replace:
```tsx
  const lines = useQuery({
    queryKey: ["production", "board", "lines"],
    queryFn: () => getBoardLines(token, clockTime(new Date())),
    refetchInterval: 60_000,
  });
```
with:
```tsx
  const lines = useQuery({
    queryKey: ["production", "board", "lines", date],
    queryFn: () => getBoardLines(token, clockTime(new Date()), date),
    refetchInterval: 60_000,
  });
```

- [ ] **Step 3: Typecheck**

Run: `cd frontend && npx tsc -b --force`
Expected: errors remaining only in `DashboardSettingsCard.tsx` (fixed in Task 7).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/production/board/LinesBoard.tsx frontend/src/features/production/board/ProductionBoard.tsx
git commit -m "Show the 4-team rotation as status circles on each OF card"
```

---

## Task 7: Settings UI — team rotation form replaces the roster grid

**Files:**
- Modify: `frontend/src/features/production/DashboardSettingsCard.tsx`

**Interfaces:**
- Consumes: `DashboardSettings["team_rotation"]`, `replaceTeamRotation` (Task 5).
- Produces: `TeamRotationForm` component (replaces `RosterForm`), rendered from `DashboardSettingsCard`.

- [ ] **Step 1: Replace the imports**

Replace:
```ts
import { listWorkCenters } from "./api";
import {
  DASHBOARD_SETTINGS_QUERY_KEY,
  MANAGE_DASHBOARD_SETTINGS_PERMISSION,
  getDashboardSettings,
  replaceRoster,
  replaceShiftWindows,
  replaceStoreRoles,
  type DashboardSettings,
  type StoreRole,
} from "./board/api";
```
with:
```ts
import {
  DASHBOARD_SETTINGS_QUERY_KEY,
  MANAGE_DASHBOARD_SETTINGS_PERMISSION,
  getDashboardSettings,
  replaceShiftWindows,
  replaceStoreRoles,
  replaceTeamRotation,
  type DashboardSettings,
  type StoreRole,
} from "./board/api";
```

(`listWorkCenters` and the `lines` query it backed were only used by the per-line roster grid; the rotation is plant-wide, so they go too.)

- [ ] **Step 2: Replace `RosterForm` with `TeamRotationForm`**

Delete the whole `RosterForm` function (lines 112-167) and replace it with:

```tsx
// --- Team rotation -----------------------------------------------------------

/**
 * The 4-team rotation: on a reference date, which team is on which shift.
 * The team left over from that date's picks is resting, computed, not chosen.
 */
function TeamRotationForm({ shifts, teams, initial, canEdit }: { shifts: string[]; teams: string[]; initial: DashboardSettings["team_rotation"]; canEdit: boolean }) {
  const { t } = useI18n();
  const [referenceDate, setReferenceDate] = useState(() => initial[0]?.anchor_date ?? new Date().toISOString().slice(0, 10));
  const [draft, setDraft] = useState<Record<string, string>>(() => {
    const teamByStop = Object.fromEntries(initial.map((r) => [r.anchor_stop, r.team]));
    return Object.fromEntries(shifts.map((shift, index) => [shift, teamByStop[index] ?? ""]));
  });
  const save = useSaveSection(replaceTeamRotation);

  const chosen = shifts.map((shift) => draft[shift]).filter(Boolean);
  const resting = teams.find((team) => !chosen.includes(team));
  const canSave = teams.length === shifts.length + 1 && chosen.length === shifts.length && new Set(chosen).size === chosen.length && resting !== undefined;

  return (
    <Section
      title={t("production.board.settings.teamRotation")}
      hint={t("production.board.settings.teamRotation.hint")}
      canEdit={canEdit && canSave}
      saving={save.isPending}
      onSave={() =>
        save.mutate([
          ...shifts.map((shift, index) => ({ team: draft[shift], anchor_date: referenceDate, anchor_stop: index })),
          { team: resting as string, anchor_date: referenceDate, anchor_stop: shifts.length },
        ])
      }
    >
      {shifts.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("production.board.settings.noShifts")}</p>
      ) : teams.length !== shifts.length + 1 ? (
        <p className="text-sm text-muted-foreground">
          {t("production.board.settings.teamRotation.wrongCount")} ({shifts.length + 1})
        </p>
      ) : (
        <div className="space-y-3">
          <label className="block text-xs text-muted-foreground">
            {t("production.board.settings.teamRotation.referenceDate")}
            <Input type="date" disabled={!canEdit} value={referenceDate} onChange={(e) => setReferenceDate(e.target.value)} className="mt-1 w-40" />
          </label>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {shifts.map((shift) => (
              <div key={shift} className="rounded-lg border border-border p-3">
                <p className="mb-2 text-sm font-medium">{shift}</p>
                <Select disabled={!canEdit} value={draft[shift] ?? ""} onChange={(e) => setDraft({ ...draft, [shift]: e.target.value })}>
                  <option value="">{t("production.board.settings.noTeam")}</option>
                  {teams.map((team) => (
                    <option key={team} value={team}>{team}</option>
                  ))}
                </Select>
              </div>
            ))}
          </div>
          <p className="text-xs text-muted-foreground">
            {resting
              ? `${t("production.board.settings.teamRotation.resting")}: ${resting}`
              : t("production.board.settings.teamRotation.incomplete")}
          </p>
        </div>
      )}
    </Section>
  );
}
```

- [ ] **Step 3: Wire it into the card**

In the `DashboardSettingsCard` component, remove the `lines` query:
```ts
  const lines = useQuery({ queryKey: ["production", "work-centers"], queryFn: () => listWorkCenters(token) });
```
and remove `lines.data` from the `ready` check, so it reads:
```ts
  const ready = settings.data && options.data && locations.data;
```

Replace:
```tsx
            <RosterForm key={`r-${JSON.stringify(settings.data!.roster)}`} lines={lines.data!.map((l) => ({ id: l.id, name: l.name }))} shifts={activeOf("shift")} teams={activeOf("team")} initial={settings.data!.roster} canEdit={canEdit} />
```
with:
```tsx
            <TeamRotationForm
              key={`tr-${JSON.stringify(settings.data!.team_rotation)}`}
              shifts={[...settings.data!.shift_windows].sort((a, b) => a.start_time.localeCompare(b.start_time)).map((w) => w.shift)}
              teams={activeOf("team")}
              initial={settings.data!.team_rotation}
              canEdit={canEdit}
            />
```

Note the `shifts` list here is deliberately sorted by `start_time` from `shift_windows` (the plant's actual configured clock times), not `activeOf("shift")`'s order — this is what fixes the cycle order (Morning → Afternoon → Night) and must match the same sort the backend uses in `DashboardLinesService.get_lines`.

- [ ] **Step 4: Typecheck**

Run: `cd frontend && npx tsc -b --force`
Expected: no errors anywhere in the frontend.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/production/DashboardSettingsCard.tsx
git commit -m "Replace the per-line roster grid with the team rotation form"
```

---

## Task 8: Translation strings

**Files:**
- Modify: `frontend/src/lib/i18n.tsx`

**Interfaces:**
- Consumes: nothing (string tables only).
- Produces: every `TranslationKey` referenced by Tasks 6-7 that doesn't already exist.

- [ ] **Step 1: Add the English entries**

In the `en` object (before line 3082, near the existing `"production.board.settings.roster"` and `"production.board.settings.noTeam"` entries), replace:
```ts
  "production.board.settings.roster": "Team per line and shift",
  "production.board.settings.noTeam": "No team",
```
with:
```ts
  "production.board.settings.teamRotation": "Team rotation",
  "production.board.settings.teamRotation.hint": "On a reference date, which team is on which shift. The team left out is resting; the rest of the calendar is computed from this one date.",
  "production.board.settings.teamRotation.referenceDate": "Reference date",
  "production.board.settings.teamRotation.resting": "Resting on the reference date",
  "production.board.settings.teamRotation.incomplete": "Pick a different team for each shift to see who rests.",
  "production.board.settings.teamRotation.wrongCount": "Configure exactly one more active team (in Report Options) than there are shifts",
  "production.board.settings.noTeam": "No team",
```

- [ ] **Step 2: Add the matching French entries**

In the `fr` object (after line 3084, near the existing `"production.board.settings.roster"` and `"production.board.settings.noTeam"` entries at what are currently lines 3215-3216), replace:
```ts
  "production.board.settings.roster": "Équipe par ligne et par poste",
  "production.board.settings.noTeam": "Aucune équipe",
```
with:
```ts
  "production.board.settings.teamRotation": "Roulement des équipes",
  "production.board.settings.teamRotation.hint": "À une date de référence, l'équipe affectée à chaque poste. L'équipe restante se repose ; le reste du calendrier est calculé à partir de cette seule date.",
  "production.board.settings.teamRotation.referenceDate": "Date de référence",
  "production.board.settings.teamRotation.resting": "Au repos à la date de référence",
  "production.board.settings.teamRotation.incomplete": "Choisissez une équipe différente pour chaque poste pour voir qui se repose.",
  "production.board.settings.teamRotation.wrongCount": "Configurez exactement une équipe active de plus (dans Options de rapport) qu'il n'y a de postes",
  "production.board.settings.noTeam": "Aucune équipe",
```

- [ ] **Step 3: Typecheck**

Run: `cd frontend && npx tsc -b --force`
Expected: no errors. (`TranslationKey = keyof typeof en`, and `fr` is typed `Record<TranslationKey, string>`, so a missing French key would already have failed Task 7's typecheck — this step re-confirms after the string additions.)

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/i18n.tsx
git commit -m "Add French and English strings for the team rotation settings"
```

---

## Task 9: Full verification

**Files:** none (verification only).

- [ ] **Step 1: Run the full backend suite**

Run: `cd backend && DATABASE_URL=postgresql://erp:erp@localhost:5432/erp PYTHONPATH=. .venv/Scripts/python.exe -m pytest -q`
Expected: PASS, no regressions anywhere (not just `modules/production`).

- [ ] **Step 2: Full frontend typecheck**

Run: `cd frontend && npx tsc -b --force`
Expected: PASS, zero errors.

- [ ] **Step 3: Configure a real rotation in the dev database and verify in the browser**

Using the demo login (see the frontend-verification memory for the login/session recipe): open Production → Settings → Dashboard, enter the shift windows if not already set, then use the new "Team rotation" section to enter the owner's real anchor (2026-09-19: Shift 1 = B, Shift 2 = C, Shift 3 = D, so A rests), with reference date `2026-09-19`. Save.

Open the production board on today (2026-09-22): confirm every OF card shows 4 circles labelled with the active team names, the team on the currently-running shift is blinking, and the others are steady. Confirm the colours match whatever shift reports exist for today. Step the board back to a past day (e.g. 2026-09-19): confirm the same 4 circles are shown with the correct historical colours and **no blinking at all**.

- [ ] **Step 4: Clean up any throwaway data created for the walkthrough**

If step 3 created any shift reports purely to exercise a colour (e.g. a throwaway `validated`/`returned` row), remove them the same way other test-data walkthroughs in this repo have (delete only rows provably created for this check, per the shift-report program's test-data etiquette). Leave the entered team rotation and shift windows in place — that's real configuration, not test data.
