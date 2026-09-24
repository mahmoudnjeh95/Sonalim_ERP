# Board team rotation — design

Date: 2026-09-22. Status: approved in conversation.

## 1. Goal

Each OF card on the production board (`frontend/src/features/production/board/LinesBoard.tsx`) shows the plant's
4-team rotation for that line's shift: which team (A/B/C/D) is on which shift, or resting, on the day currently
shown on the board — with a status circle per team, and a blink on whichever team is on shift **right now** (only
when the board is showing today).

This replaces the current `RosterPills` (one pill per **configured shift**, showing a single static team read from
`production.line_team_roster`), which cannot express a 4-team rotation (it only ever holds one team per shift, so
at most 3 teams total) and is not date-aware (it shows the same "current" team regardless of which day the board is
browsing).

## 2. Decisions taken with the owner

| # | Decision |
|---|---|
| 1 | The rotation is **one shared schedule for the whole plant** (not per line). Every line's OF card reads the same team-for-the-day. |
| 2 | Teams follow a **fixed 4-stop cycle**: Morning → Afternoon → Night → Rest → Morning …, each team just offset from the others in time. Stop order is the plant's shifts sorted by start time, then Rest. |
| 3 | Anchor point given by the owner: on **2026-09-19**, team B was on Morning (07:00–14:00), C on Afternoon, D on Night, A resting. This is the one data point the whole calendar is computed from — nothing else is guessed. |
| 4 | Team **names** are not new: reuse the existing `core.report_options` list of kind `team` (Production Settings already manages this list; shift reports already file under these names). The rotation only adds *positions in the cycle*, not the names themselves. |
| 5 | Circle colours, per team, per date: **grey** = no shift report for that team's slot that day; **blue** = report submitted, not yet validated; **green** = validated; **red** = report was returned (needs rework). Resting team is always grey (no separate "resting" look). |
| 6 | **Blink** only applies to the team on the shift running right now, and only when the board is showing **today**. Past days show the same 4 circles with no blink. |
| 7 | The old per-line "Roster" grid in Production Settings → Dashboard is **removed**, along with `production.line_team_roster`. It's superseded, not kept alongside the new screen. |
| 8 | All new/changed UI strings go through the existing `t()` i18n system with both French and English entries — this app is bilingual and the board is normally viewed in French. |

Open choice, not yet exercised: the initial anchor (decision 3) is entered once through the new settings screen after
it's built, the same way every other dashboard setting starts empty and is filled in by hand — it is not pre-seeded
by a migration.

## 3. Data model

New migration `production/migrations/0057_production_team_rotation.sql`:

```sql
-- Where the 4-team rotation is anchored: on `anchor_date`, each team sits at
-- `anchor_stop` in the cycle [shift_0, shift_1, ..., shift_(n-1), rest], stops
-- numbered by the plant's shifts sorted by start time, with `n` (= number of
-- configured shifts) as the "resting" stop. A team's stop on any other date is
-- (anchor_stop + (date - anchor_date).days) mod (n + 1).
CREATE TABLE production.team_rotation (
    tenant_id TEXT NOT NULL,
    team TEXT NOT NULL,
    anchor_date DATE NOT NULL,
    anchor_stop INTEGER NOT NULL CHECK (anchor_stop >= 0),
    PRIMARY KEY (tenant_id, team)
);
```

Same replace-the-whole-list pattern as `shift_windows`/`store_roles`: one `anchor_date` shared by every row for a
tenant (validated at save time, like `replace_roster`'s duplicate-shift check today). Saving requires exactly
`(number of configured shifts) + 1` distinct teams, each given a distinct `anchor_stop` in `[0, n]` — this is
enforced the same way `replace_shift_windows`/`replace_roster` validate today (`Err` results, no silent guessing).

`production.line_team_roster` and its column set are dropped in the same migration. `backend/scripts/reset_operational_data.py`'s
table list (`production.line_team_roster`) is updated to `production.team_rotation`.

## 4. Backend

**Domain** (`modules/production/domain/dashboard.py`): a pure function, given the tenant's shift windows (sorted by
start time — the existing sort used everywhere else) and the rotation rows, returns for a given `date` a list of
`(team, stop_index)`, where `stop_index in [0, n-1]` is a real shift and `stop_index == n` is Rest. No I/O, easily
unit tested against the 2026-09-19 anchor from decision 3.

**`DashboardSettingsService`**: `replace_roster`/roster read in `get_settings` are replaced by
`replace_team_rotation`/a `team_rotation` entry in `get_settings` (list of `{team, anchor_date, anchor_stop}`, plus
the resolved per-shift-name breakdown for the settings screen to render).

**`DashboardLinesService.get_lines`**: gains an optional `date: datetime.date` query param (default: today, same
default the rest of the board already uses). For each line, `roster` is replaced by `team_status`: for every team in
the rotation, `{team, shift: <shift name> | null, status: LiveStatus | null, is_current: bool}` — `shift` is `null`
for the resting team; `status` is looked up from `production.shift_reports` by `(work_center_id, report_date=date,
shift)` (the table's existing `UNIQUE (tenant_id, work_center_id, report_date, shift)` makes this a single lookup),
`null` when no report row exists; `is_current` is `true` only when `date == today` and `shift` matches the shift
returned by the existing `current_shift(...)` helper. Endpoint `GET /production/dashboard/lines` gains `date` the
same way `at` already works; `ProductionBoard.tsx` passes its existing `date` state through.

## 5. Frontend

- `api.ts`: `RosterEntry` → `TeamStatusEntry { team: string; shift: string | null; status: LiveStatus | null;
  is_current: boolean }` (reuses the existing `LiveStatus` union: `open | submitted | returned | validated`, `null`
  meaning no report at all — both render grey). `BoardLine.roster` → `BoardLine.team_status`. `getBoardLines(token,
  at, date)`.
- `LinesBoard.tsx`: `RosterPills` → `TeamStatusPills`, one circle per team (A/B/C/D-style label from the team name),
  coloured per decision 5, blinking (reusing the existing `board-team-now` blink styling already used for the
  current roster pill) only when `entry.is_current` — which the backend already gates on `date === today`, so the
  component doesn't need to know which day is showing.
- `DashboardSettingsCard.tsx`: `RosterForm` → `TeamRotationForm`: a reference date picker plus one dropdown per
  configured shift (choices = active `team` report options), the leftover team shown as resting; saves as
  `anchor_date` + computed `anchor_stop` per team. Disabled with a explanatory message when the active team-option
  count isn't exactly shifts+1 (mirrors the existing "configure shifts first" empty states on this card).
- i18n: new keys under `production.board.*` / `production.board.settings.*` for the rotation settings labels and any
  new status wording, added to both the French and English tables (existing `TranslationKey`/`useI18n` pattern).

## 6. Testing

- Domain: unit tests for the stop-cycle formula against the 2026-09-19 anchor (decision 3), including wrap-around
  and a shift-windows configuration with a different number of shifts.
- Backend integration: `DashboardSettingsService.replace_team_rotation` validation (wrong team count, duplicate
  stops, missing shift config); `DashboardLinesService.get_lines(date=...)` returns correct `team_status` for a
  known date against seeded shift reports in each of the four states (none/open, submitted, validated, returned).
- Frontend: `tsc -b --force` clean; browser walkthrough — today's board blinks the right team, a past day shows the
  four circles with no blink, and the new settings screen saves and reloads correctly.

## 7. Out of scope

- Per-line rotations (decision 1 rules this out).
- A distinct visual state for "resting" vs. "no report yet" (decision 5).
- Anything about which specific people are on a team (team names stay exactly what Report Options already holds).
