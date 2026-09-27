# HR / payroll / ledger program — working context

Snapshot: 2026-09-27. For whoever resumes this work, a person or a new session. The SDD ledgers named
below are the live record of progress: `git log` and the ledger outrank this file once they move past it.

## Current task

**HR phase 2 — Time & presence + leave**, branch `hr-p2-presence-leave` (worktree
`.worktrees/hr-p2-presence-leave`, branched from `huge_production_migration` at `d77c1a2`).

- Tasks 1–3 are done and reviewed.
- Next up: Task 4, the punch-pairing engine (pure domain).

## Done

### Phase 1 — Employee core (shipped)

- 15 tasks, each reviewed; then a whole-branch review on Opus and one fix wave (`f0ca9fd..c626764`),
  re-reviewed clean.
- It adds:
  - the employee file (identity, masked NINA/INPS/AMO, unique badge, linked user);
  - dependants, and dated payment arrangements (bank / mobile money / cash, validated splits);
  - typed XOF contracts with amendments and a one-signed-contract-per-day constraint, and termination;
  - documents with expiry alerts;
  - positions, grades and departments;
  - `PayrollSnapshotService` for phase 3;
  - `/hr/employees`, `/hr/employees/:id` and `/hr/organisation`;
  - the 60-employee Mali seed.
- Merged into `huge_production_migration` as `d77c1a2`, together with `personal`'s PR #14 (packing items
  post from their own store, production migration 0068). Pushed to `origin` (which deploys) and to
  `personal` on 2026-09-27.

### Phase 2 — Presence + leave (in progress, 14 tasks)

| # | Task | Commit | State |
|---|---|---|---|
| 1 | Schedule domain — windows, rotations, assignments, night overlap | `647204b` | ✅ reviewed |
| 2 | Schedules, rotations, assignments, holidays, presence settings — migrations 0010–0011, services, first routes, test kit | `87e953c` | ✅ reviewed (Sonnet) |
| 3 | Presence days — domain, migration 0012, day/week grid, employee month | `0ad9198` | ✅ reviewed |

Baseline before Task 1: `modules/hr` 163 passed. After Task 3: 226 passed, 0 skipped.

## Next

1. Run Tasks 4–14 in order:
   - 4 — punch pairing engine
   - 5 — clock CSV parsing with device profiles
   - 6 — clock imports (migration 0013)
   - 7 — leave domain
   - 8 — leave types, requests and balances (migration 0014)
   - 9 — month close/reopen, `PresenceService.month_summary`, the `hr.presence_month.closed` event and the payroll-lock consumers
   - 10 — frontend foundation and `/hr/schedules`
   - 11 — `/hr/presence`
   - 12 — `/hr/presence/imports`
   - 13 — `/hr/leave`
   - 14 — dev seed: a month of presence, a clock sample, leave
2. Whole-branch review on Opus, one fix wave, then finish the branch. Merge and push only when the user says so.
3. Later phases, whose plans are already committed: 3a payroll engine (11 tasks), 3b payroll runs (13),
   3c payroll frontend + seed (11), 4 SYSCOHADA finance ledger (15), 5 HR analytics + self-service (10).

## Key decisions

### Program (client, 2026-09-25)

- The plant is in **Mali**. Payroll rules are configurable per country and effective-dated.
- Statutory rates are seeded as **drafts**: a payroll run can't be approved until an accountant
  confirms them.
- **No invented thresholds.** Every statutory or plant value is a database row. Code refuses with
  `PRESENCE_SETTINGS_MISSING` (and similar) rather than assume a value.
- Presence comes from supervisors' bulk entry and a clock CSV import.
- Payouts go by bank file, mobile money or cash.
- Payroll posts to a new SYSCOHADA ledger in `finance`.

### Phase 1 rulings (spec over plan where they differed)

- Masking is decided at the HTTP layer.
- A payment set that holds numbers the caller can't see can't be replaced or removed without
  `hr.view_sensitive` (403).
- Relinking an employee's `user_id` needs `hr.view_sensitive`, because phase 5's `/me` resolves "me"
  through it.
- A CDD that ends without renewal stays in the alerts as *expired*; it no longer silently disappears.
- Alert horizons have no arbitrary cap. Number bounds come from the column types, and values are
  refused, never rounded.
- **Legacy USD contracts and payslip lines are relabelled XOF, never converted** (client decision
  2026-09-27: the old screen had a hidden USD default for amounts typed in F CFA). This lives in migration
  0006, commit `0fda742`. Amending a contract in any other non-XOF currency is refused.
- The legacy payroll run skips employees who have left.
- Parked, for the user to decide:
  - 0007-closed legacy rows keep status `active`;
  - a future exit date marks the person "Left" immediately (phase 2 gates presence on the dates, so it
    isn't affected);
  - admin PATCH can bypass lifecycle rules (API only);
  - legacy free-text contract types lose their label.

### Process (the user's choices)

- Subagent-driven development:
  - Sonnet implementers; Haiku for pure-domain tasks whose plan holds the full code;
  - reviews on Haiku, Sonnet for high-risk diffs;
  - a whole-branch review on Opus, then one fix wave.
- Relaunch stalled helpers fresh instead of resuming them, because a resume replays the whole transcript.
- Browser checks run on private ports: backend 8100 (`--reload`), Vite 5273, headless Chrome on CDP
  9334. The controller starts and stops these servers; helpers never manage processes, and every command
  they run has a timeout.
- Commit and push without running the full suite first.
- "Both repos" means `origin` (SmartToolsAgro/Erpsonalim) and `personal` (mahmoudnjeh95/Sonalim_ERP).
  **A push to `huge_production_migration` deploys to the live server.**
- Commit trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Deploy / operations notes

- Dev data never reaches production. The deploy builds images from source and restarts
  `app`/`worker`/`web`; the production database stays in its own volume on the server. HR migrations
  insert no rows, and no seed runs automatically.
- **After a deploy**, grant the new `hr.*` permission codes on production (the admin UI, or
  `ensure_default_roles` for the production tenant). Give `hr.view_sensitive` deliberately: without it
  nobody can create a contract.
- **Merge watch-out:** another session has uncommitted edits to `backend/app/main.py`,
  `backend/worker/main.py` and `backend/core/migrations/runner.py` in the main checkout. Phase 2's
  Tasks 2 and 9 also modify `app/main.py` and `worker/main.py`.
- The shared dev database (`postgresql://erp:erp@localhost:5432/erp`) has hr migrations 0001–0012
  applied. It also holds test data:
  - EMP-T11/T12/T13-TEST;
  - the login `t13-nonsensitive@sonalim-erp.local` (HR admin rights, no `view_sensitive`);
  - T14-DEPT/POS/G1;
  - the seed's HRP-001..060 and `employe.demo@sonalim-erp.local`.

  The user doesn't mind dev contract data.

## Relevant paths

| What | Path |
|---|---|
| Spec (whole program) | `docs/superpowers/specs/2026-09-25-hr-payroll-finance-design.md` |
| Cross-phase contract | `docs/superpowers/plans/2026-09-25-hr-payroll-finance-interfaces.md` |
| Phase plans | `docs/superpowers/plans/2026-09-25-hr-p{1,2,3a,3b,3c,4,5}-*.md` |
| Phase 2 SDD workspace (git-ignored) | `.worktrees/hr-p2-presence-leave/.superpowers/sdd/2026-09-25-hr-p2-presence-leave/` |
| — contents | `progress.md` (ledger, pre-flight table, rulings); `task-N-brief.md` / `task-N-report.md`; `constraints.md`; `reviewer-instructions.md`; `implementer-instructions.md`; `review-*.diff` |
| Phase 1 SDD workspace (kept for parked items) | `.worktrees/hr-p1-employee-core/.superpowers/sdd/2026-09-25-hr-p1-employee-core/` (`progress.md`, `final-review-report.md`, `final-fix-report.md`) |
| HR backend | `backend/modules/hr/{domain,api,migrations,module.json}` |
| Phase 2 files so far | `domain/schedule.py`, `domain/presence.py`, `api/schedule_service.py`, `api/presence_service.py`, `api/presence_router.py`, `api/presence_testkit.py`, `migrations/0010`–`0012` |
| HR frontend | `frontend/src/features/hr/` (phase 2 adds `presence/`, `schedules/`, `leave/`, `presenceApi.ts`, `HrListTable.tsx`, `HrTabsPage.tsx`) |
| Seed | `backend/scripts/seed_hr_payroll.py` |

## Commands (from the worktree)

- Tests (from `backend/`): `.venv/Scripts/python -m pytest modules/hr -q`. Integration tests skip, not
  fail, when no DB is reachable, so check the summary shows "passed".
- Apply migrations (from `backend/`):
  `DATABASE_URL=postgresql://erp:erp@localhost:5432/erp .venv/Scripts/python.exe -c "from core.migrations.runner import apply_all_migrations; apply_all_migrations()"`
- Frontend check (from `frontend/`): `npx tsc -b --force`
