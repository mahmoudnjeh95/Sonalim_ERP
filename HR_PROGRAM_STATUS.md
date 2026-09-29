# HR / Payroll / Finance ledger — what is built, what is next

Last updated: **2026-09-29 (phase 3c built, not reviewed, not merged)**. Written
for the client and for whoever picks this work up.

This is the running record of the HR programme: the 89 planned tasks, which are built, which
were reviewed, and where work stopped. When it disagrees with `git log` or a phase's SDD
ledger, those win — they move first.

- Spec: `docs/superpowers/specs/2026-09-25-hr-payroll-finance-design.md`
- Cross-phase contract: `docs/superpowers/plans/2026-09-25-hr-payroll-finance-interfaces.md`
- Phase plans: `docs/superpowers/plans/2026-09-25-hr-p{1,2,3a,3b,3c,4,5}-*.md`

## Where we stopped

> **PHASE 2 IS MERGED into `huge_production_migration` locally** (commit `81b6364`), together
> with `origin`'s warehouse module work (phases 0–6C, merged first as `de5e58a`) that had landed
> on the deploy branch in the meantime. One follow-up commit (`5a6dabe`) classifies phase 2's new
> `hr.*` tables in the go-live reset script, which nothing had done yet. Verified after both
> merges: `tsc -b --force` exits 0; the full backend suite is **1704 passed, 1 skipped, 0
> failures caused by either merge** (the sole remaining failure, `test_a_team_used_by_a_
> quality_report_is_retired_too`, was already broken before `d77c1a2` — a stale test against a
> column the QC-on-shift-reports migration dropped in September, unrelated to this work).
>
> **Phases 1–2 PUSHED and DEPLOYING** (`a58c298`/`cfe5665`, 2026-09-28). **Phase 3a (payroll
> engine) is SHIPPED locally** — all 11 tasks built and reviewed clean, final commit `814e90a`
> on `hr-p3a-payroll-engine` (worktree `.worktrees/hr-p3a-payroll-engine`, off
> `huge_production_migration` at `cfe5665`). `modules/payroll` suite: 106 passed, 0 skipped, real
> DB. Two tasks in this phase are worth knowing about when picking this up: Task 9's implementer
> hit the session's API rate limit right after committing and never filed its report (the
> controller independently verified the commit and wrote the report in its place; review still
> ran the normal path and came back clean), and Task 10 (`RuleSetService`, carrying Review Focus
> #1 — the confirmation lock) had its lock independently traced across all five mutation paths by
> both the controller and the reviewer. Nothing here is taken on faith without a second, concrete
> pass — every pinned risk in this phase was hand-verified, not just read.
>
> **2026-09-29: the phase 3a whole-branch review ran and came back "ready to merge with fixes"**
> — zero Critical, 2 Important, 9 Minor (all deferred). Both Important findings were cross-task/
> cross-phase, invisible to any single task's own review:
> 1. A daily-paid worker was paid twice for a worked public holiday — hr's presence summary
>    (phase 2) counts a worked holiday in both `worked_days` and `holiday_days`, so the daily-pay
>    formula drew a full day rate for that day twice, on top of its overtime line. **Fixed** for
>    the worked-*holiday* case. A worked **rest day** has the same bug but no hr field currently
>    distinguishes it within `worked_days` — that half is a genuine, open cross-module gap, left
>    for phase 3b/hr to resolve, not silently dropped.
> 2. A rule set could be confirmed with the unpaid-absence row's tax/contribution flags not
>    matching the base salary row's, silently producing a wrong ITS; and a payslip's net going
>    negative before any deduction was even applied raised no warning. **Both fixed.**
>
> Fix commit `2758c11` on `hr-p3a-payroll-engine`, 3 new tests (each confirmed to fail against the
> pre-fix code and pass after, before being committed). `modules/payroll` suite: 109 passed, 0
> skipped, real DB. **The scoped re-review of that fix commit came back clean**: both findings
> independently hand-traced and confirmed ADDRESSED (not just re-read), including tracing the
> new `NET_NEGATIVE` condition as a strict extension of the old one by boolean short-circuit, and
> confirming the existing golden/domain tests are unaffected. No new breakage. **Phase 3a is now
> fully closed** — final commit `2758c11`, 12 commits ahead of `cfe5665` on `hr-p3a-payroll-engine`.
> Its SDD workspace has been deleted; this file plus `git log` are the record now.
>
> **Phase 3a is MERGED and DEPLOYING** — the client opened PR #7 (`hr-p3a-payroll-engine` →
> `huge_production_migration`) and merged it on GitHub on 2026-09-29 as `c3c3e08`. The local
> branch pulled it in as `61ff920`; the worktree and local branch are removed. **What comes next
> is the client's call:** phase 3b (payroll runs), or sub-projects A and B first, as the
> "Open scope" section's proposed order has it (payroll after them, with amended plans).
>
> **Deploys migrate the database again** (`9a57d12`, landed alongside): `AUTO_MIGRATE` now
> defaults to true in `compose.yaml`, under an advisory lock, and a guard test refuses any
> migration that inserts literal rows or references a demo tenant. So phase 3a's only migration,
> `payroll/0001_payroll_rules.sql` (schema only, no rows), applies itself on this deploy — no
> hand-run SQL. Still never seeds.
>
> **One real open item carried forward, not a defect to silently forget:** a worked **rest day**
> (as opposed to a worked public holiday) is still double-paid for a daily-paid employee, because
> hr's presence summary has no field distinguishing "worked rest day" from an ordinary worked day
> within `worked_days`. Phase 3b (or a small hr addition) needs to either add that field or change
> how `OT_REST_HOLIDAY` overtime interacts with the daily base-pay count before daily-paid workers
> go live on real presence data.
>
> **Action still required on the server:**
> 1. Check the deploy applied the migrations: phase 2's `hr` 0010–0014 (if they were never run by
>    hand) and phase 3a's `payroll` 0001 should all be in `core.module_migrations`. If the server
>    `.env` sets `AUTO_MIGRATE=false`, run them by hand instead with
>    `docker compose exec -T app python -m scripts.migration_sql`.
> 2. Grant the new permission codes on production (`ensure_default_roles` for the production
>    tenant, or the admin UI): phases 1–2's `hr.*` — give `hr.view_sensitive` deliberately — and
>    phase 3a's `payroll.view_rules`, `payroll.manage_rules`, `payroll.confirm_rules`. The other
>    eight `payroll.*` codes are declared already but gate nothing until phase 3b's routes exist.
>    Give `payroll.confirm_rules` to the accountant only, since it lets a rule set drive real payslips.
> 3. Recommend a dev-DB reset + reseed before any HR walkthrough on non-production environments
>    (pre-existing test fixtures, not from earlier branches — see phase 2's section below).
>
> **Phase 3b (payroll runs) is MERGED and DEPLOYING** — merged as `1b1ae95` on 2026-09-29 (see its
> own section below for the whole-branch review and fix).
>
> **Phase 3c (payroll frontend & seed) is BUILT, not reviewed, not merged** — all 11 tasks done in
> parallel waves on `hr-p3c-payroll-frontend`, final commit `feb663f` (Task 11: granted the demo
> user every `payroll.*` permission in the seed and browser-verified every `/payroll/*` screen
> against it). `npx tsc -b --force` clean; no frontend bugs found. One flow is unverified by
> browser — approve → payouts → mark-paid → declarations — because completing it needs a second
> demo account with `approve_runs`, which this task was told not to invent; the same-user-approval
> refusal that stops it was confirmed working as designed. **Next step is the client's call** on
> merge/PR, same as every phase before it.

## Progress

| Phase | Tasks | Built | Reviewed | State |
|---|---|---|---|---|
| 1 — Employee core | 15 | 15 | 15 | **Shipped** (merged as `d77c1a2`, deployed) |
| 2 — Presence & leave | 14 | 14 | 14 | **Shipped** (`a58c298`, pushed, deploying) |
| 3a — Payroll engine | 11 | 11 | 11 | **Shipped** (PR #7, merged as `c3c3e08`, deploying) |
| 3b — Payroll runs | 13 | 13 | whole-branch only | **Shipped** (merged as `1b1ae95`, pushed 2026-09-29, deploying) |
| 3c — Payroll frontend & seed | 11 | 11 | 0 | **Built**, not reviewed, not merged (branch `hr-p3c-payroll-frontend`, final commit `feb663f`) |
| 4 — Finance ledger | 15 | 0 | 0 | Planned |
| 5 — Analytics & self-service | 10 | 0 | 0 | Planned |
| **Total** | **89** | **64** | **40** | |

Legend: ✅ built and reviewed clean · 🔨 built, review not finished · ⬜ not started

## Phase 1 — Employee core (15 tasks) — shipped

Merged into `huge_production_migration` as `d77c1a2` and deployed on 2026-09-27. Every task was
reviewed, then the whole branch was reviewed and one round of fixes applied
(`f0ca9fd..c626764`), re-reviewed clean.

| # | Task | State |
|---|---|---|
| 1 | Permission codes, package files and the sensitive-data rule | ✅ |
| 2 | Organisation — positions, grades and editable departments | ✅ |
| 3 | The employee file — identity, social numbers, badge, linked user | ✅ |
| 4 | Family and payment — dependants and payment arrangements | ✅ |
| 5 | Contracts — types, terms, components, activate / end / amend | ✅ |
| 6 | The database guard — one signed contract per employee per day | ✅ |
| 7 | Terminating an employee | ✅ |
| 8 | Documents, alert horizons and the expiry alerts | ✅ |
| 9 | `PayrollSnapshotService` — the contract with phase 3 | ✅ |
| 10 | Frontend — API client, shared pieces, `/hr/employees` and the HR nav | ✅ |
| 11 | Frontend — the employee file page: identity, family, exit, leave, payslips | ✅ |
| 12 | Frontend — the contracts tab (create, edit, activate, amend, end) | ✅ |
| 13 | Frontend — the payment and documents tabs | ✅ |
| 14 | Frontend — `/hr/organisation` (departments, positions, pay grid, settings) | ✅ |
| 15 | Seed — 60 employees of a Malian pasta plant | ✅ |

**After a deploy, on production:** grant the new `hr.*` permission codes (the admin UI, or
`ensure_default_roles` for the production tenant). Give `hr.view_sensitive` deliberately —
without it nobody can create a contract.

**Left open from phase 1**, for the client to decide: legacy rows closed by migration 0007 keep
the status `active`; a future exit date marks someone "Left" straight away; the admin PATCH
route can bypass the lifecycle rules; legacy free-text contract types lose their label.

## Phase 2 — Presence & leave (14 tasks) — shipped

Worktree `.worktrees/hr-p2-presence-leave`. Migrations 0010–0014. The `modules/hr` suite was
163 tests before this phase and is **299 passed, 0 skipped** now (after the whole-branch
review's fix wave added 4 more).

| # | Task | Commit | State |
|---|---|---|---|
| 1 | Schedule domain — windows, rotations, assignments, night overlap | `647204b` | ✅ |
| 2 | Schedules, rotations, assignments, holidays and presence settings — tables, services, routes | `87e953c` | ✅ |
| 3 | Presence days — domain rules, table, supervisor grid (day and week), employee month | `0ad9198` | ✅ |
| 4 | Punch pairing engine (pure domain) | `cdc6d28` | ✅ |
| 5 | Clock CSV parsing with device profiles (pure domain) | `a95089d` | ✅ |
| 6 | Clock imports — profiles, staging, review, commit into presence days | `f388ba9` | ✅ |
| 7 | Leave domain — counted days, monthly accrual, balances with carry-over | `252dbd5` | ✅ |
| 8 | Leave types, requests with approval, balances — tables, services, routes | `2952aba` | ✅ (2 minors deferred) |
| 9 | Month close and reopen, the payroll summary, the closed event and the payroll-lock consumers | `d47de69` | ✅ (2 minors, plan-mandated) |
| 10 | Frontend foundation + `/hr/schedules` (schedules, rotations, assignments, holidays, settings) | `7f14a84` | ✅ (2 minors, non-issues) |
| 11 | `/hr/presence` — day grid, week grid, employee month, month close | `e1023be` | ✅ (2 minors, non-issues) |
| 12 | `/hr/presence/imports` — device profiles, upload, staging review, commit | `311f6a9` | ✅ (2 minors, non-issues) |
| 13 | `/hr/leave` — leave types, requests with approval, balances | `0d20b9b` | ✅ (1 minor deferred) |
| 14 | Extend the dev seed with a month of presence, a clock sample and leave | `ad3bbcd` | ✅ (2 minors, non-issues) |

All 14 tasks are built and reviewed clean. **Whole-branch review** (base `d77c1a2`, head
`ad3bbcd`, 15 commits, on Opus): ready to merge **with fixes** — it independently re-ran the full
suite (295 passed, 0 skipped), `tsc`, an AST scan of all 91 backend `Err()` calls (all
bilingual), an i18n key-parity check, and reproduced both Important findings itself in
rolled-back transactions under a throwaway tenant.

**2 Important findings, both real cross-task gaps invisible to any single task's review — fixed
in the one allowed fix wave (`5751d3e`), each with a dedicated integration test:**
1. The legacy `/hr` leave-approval route could approve a request made on the new `/hr/leave`
   screen without touching its balance; a later cancel on the new screen then refunded days that
   were never taken (reproduced: 5.00 → legacy-approve → still 5.00 → cancel → 7.00). **Fixed:**
   the legacy route now refuses with `LEAVE_TYPED_REQUEST` when the request has a leave type.
2. A closed month's `month_summary` — the exact figures phase 3 payroll will read — drifted if a
   holiday or a leave type's paid flag was edited afterward, contradicting the events catalog's
   promise that it's "final until reopened" (reproduced with self-contradictory figures).
   **Fixed:** editing a holiday dated in a closed month, or changing a leave type's paid flag
   while it has leave days in a closed month, is now refused with `PRESENCE_MONTH_CLOSED`.

**Also fixed in the same wave:** `tenant_id` defence-in-depth on the 2 real child-row deletes
found (of 6 guessed — the other 4 either didn't exist or were already scoped); the seed's
"confirm with HR" banner now prints its actual draft values; the seed's demo holiday was
mislabelled with a real Mali date it doesn't fall on, so it's renamed to a neutral demo label
(kept at its original date, since the seed's month-close logic needs it inside the closed
period); a stale `context.md` that would have landed on the deploy branch is removed.

**Re-reviewed clean:** every fix independently verified against the live code (not the fix
report's word) — router wiring, the new tests' independent-path assertions, the closed-month
query's tenant/type scoping and no-false-positive behaviour, both "nothing to fix here" claims
confirmed by direct grep. No new breakage.

**Deferred, not part of this fix wave** (none load-bearing): punch anomalies not surfaced at
month close; a low-likelihood month-close concurrency race; an invisible BOM character in
`clock_csv.py`; the imports page's default date range breaking on the 1st of a month; Task 13's
cosmetic i18n-key duplication. Also confirmed: Task 14's flagged dev-DB fixture pollution is
genuinely not in the code (only was in the now-removed `context.md`) — **recommend a dev-DB
reset and reseed after merge, before any HR walkthrough**, so stray test data doesn't confuse
that review.

**Merge done, 2026-09-28.** `origin/huge_production_migration` had 9 new warehouse-module
commits (phases 0–6C: cycle counts, put-away, fulfillment, barcodes, FIFO valuation,
reorder-point replenishment) merged in first (`de5e58a`), then `hr-p2-presence-leave` on top
(`81b6364`). One textual conflict each time in `backend/worker/main.py` (both branches added an
import line) — resolved by keeping both. `i18n.tsx` merged with no conflict (the Task 10/13
renames held). The other session's in-progress deploy-safety edits
(`app/main.py`/`worker/main.py`/`core/migrations/runner.py`/`.env.example`/`CLAUDE.md`/
`compose.yaml`, plus the untracked `scripts/migration_sql.py`) were confirmed complete and
committed first (`8b49e33`), rather than merged over: `AUTO_MIGRATE` is now off by default, and
`migration_sql.py` prints pending migrations to run by hand. A separate untracked script,
`backend/scripts/seed_shift_recent.py` (unrelated production-module work by another session),
was left untouched.

Applying the merged migrations to the shared dev DB surfaced that phase 2's 17 new `hr.*` tables
weren't classified in `scripts/reset_operational_data.py` — fixed in `5a6dabe` (8 configuration
tables kept, like `hr.settings`; 9 operational tables purged, like `hr.employees`), verified by
its own behavioural tests (not just the classification check).

The stray commit `02372b2` (see Task 7 history) is folded into the merge, content-identical to
`252dbd5` — no action needed, it's just part of the history now.

**Pushed** to `origin` and `personal` as `a58c298` on 2026-09-28 — this deploys to the live
server (migrations still need running by hand there; see "Action required now" above). The
phase's SDD workspace was deleted before the merge; this file plus `git log` on
`huge_production_migration` is now the record.

**Deferred minors**, to fix in the final round:
- Task 2: `schedule_service.py`'s child-row DELETEs (lines 573, 682) omit `tenant_id`. Not
  reachable across tenants (the parent is resolved under the tenant first), but worth adding
  for defence in depth.
- Task 8: `leave_service.py:663` (`update_request`, approved-leave edit) recomputes the leave
  plan twice — once in `update_request`, again inside `_apply`. No correctness impact; the
  shape is plan-mandated, not an implementer choice.
- Task 9: `presence_month_service.py`'s `close`/`reopen` re-check `period.day != 1` even though
  the router already rejects a non-first-of-month date before the service is called — harmless,
  plan-mandated defence in depth. `month_summary`'s docstring says to read it only once a month
  is closed, but nothing enforces that yet — a note for whichever later task reads it.
- Task 13: the implementer's own fix for a brief bug (bare `t("status.pending")` keys that don't
  exist) added `hr.leaveRequests.status.*`, duplicating an identical existing set,
  `hr.file.leave.status.*`. Cosmetic only — same four translations either way. A one-line
  consolidation per call site, deferred to the final review rather than spending a round on it.

**Ruling (Task 10):** the brief's presence-settings i18n keys (`hr.settings.title`, `.saved`,
`.error`) would have silently overwritten phase 1's already-shipped `hr.settings.*` keys used by
`HrSettingsTab.tsx` (Alert horizons) — a duplicate key in the same object literal wins silently,
and this is not caught by `tsc`. Renamed this task's 12 presence-settings keys to
`hr.presenceSettings.*` instead of touching the shipped screen. Confirmed `t()` is typed against
the full key union, so any stale reference would have failed `tsc -b --force` — it didn't.

**Ruling (Task 13):** the same failure mode again — the brief's new `/hr/leave` screen's page
chrome (`hr.leave.title`, `.subtitle`, `.loading`, `.tab.*`) collides on `hr.leave.title` with
the legacy `HrPage.tsx`'s leave-requests card ("Leave requests"/"Demandes de congé"). Renamed
the 6 new-screen page-chrome keys to `hr.leaveScreen.*`; left `HrPage.tsx`'s existing
`hr.leave.*` keys (type/dates/approve/reject/new/created/bulk*/dialog.*) untouched. Separately,
the brief's own `LeaveRequestsTab.tsx` code called bare `t("status.pending")`-style keys that
don't exist anywhere — a genuine brief bug, confirmed independently by both the controller and
the reviewer. The implementer added its own fix (`hr.leaveRequests.status.*`) rather than
stopping a second time; ruled deferred rather than reworked (see the Task 13 deferred minor
above) since it's cosmetic.

## Phase 3a — Payroll engine (11 tasks) — shipped

New `payroll` module: configurable, effective-dated Mali rule tables and a pure calculation
engine. Statutory values are seeded as **drafts**; a run cannot be approved until an accountant
confirms them. Backend-only — no `/payroll/*` screens until phase 3c. Worktree
`.worktrees/hr-p3a-payroll-engine`, off `huge_production_migration` at `cfe5665`. All 11 tasks
built and reviewed clean, then whole-branch reviewed and fixed; final commit `2758c11`.
`modules/payroll` suite: **109 passed, 0 skipped**, against a real database throughout.
Merged through PR #7 as `c3c3e08` on 2026-09-29; worktree and branch removed.

**Whole-branch review (2026-09-29):** ready to merge with fixes — 0 Critical, 2 Important
(both cross-task/cross-phase seams no single task's own review could see), 9 Minor (all
deferred, non-blocking). Both Important findings fixed in `2758c11`, verified by a scoped
re-review that hand-traced each fix rather than re-reading the diff:
1. A daily-paid worker was paid twice for a worked public holiday (hr's phase-2 presence
   summary counts it in both `worked_days` and `holiday_days`). Fixed for the holiday case.
   **Still open:** the same double-pay for a worked *rest* day — hr has no field to
   distinguish it from an ordinary worked day, so this needs a phase 3b/hr decision before
   daily-paid workers run on real presence data.
2. A confirmed rule set could have the unpaid-absence row's tax/contribution flags not match
   the base-salary row's (silently wrong tax), and a payslip's net could go negative with no
   warning if nothing needed carrying. Both fixed.

| # | Task | Commit | State |
|---|---|---|---|
| 1 | Module skeleton, rule tables, permissions, wiring | — | ✅ |
| 2 | Money rounding, engine value objects, rule set, synthetic test rules | — | ✅ |
| 3 | Rule row validation and the confirmation gate | — | ✅ |
| 4 | Engine step 1 — earnings up to the gross | — | ✅ |
| 5 | Engine steps 2–3 — contributable base, ceilings, contributions | `ac55f9f` | ✅ |
| 6 | Engine step 4 — taxable base, brackets, reliefs, tax rounding | `bbf37da` | ✅ |
| 7 | Engine steps 5–6 — deductions, net floor with carry-forward, employer charges, totals | `c987770` | ✅ |
| 8 | Final settlement arithmetic | `1e77314` | ✅ (controller independently re-verified the tiered severance math — the review report was thinner than usual) |
| 9 | The engine — `calculate_payslip` and golden payslips | `f09a995` | ✅ (1 minor deferred) |
| 10 | `RuleSetService` — payroll country, rule sets, rows, confirmation, loading | `d565aae` | ✅ (3 minors, inherited/forward-looking) |
| 11 | Rules HTTP routes | `814e90a` | ✅ (1 minor coverage gap, verified not a live bug) |

The **seniority bonus** (prime d'ancienneté — the client's "loyalty bonus") is a configurable
scale of years to a percentage of base salary, in Task 2's rule tables and Task 4's earnings step.

**Task 9 note:** the implementer hit the session's API rate limit immediately after committing
`f09a995` and was terminated before writing its report or replying with its contract. The
controller read the commit directly rather than treat it as failed or re-run it: `engine.py` is a
verbatim match to the task brief's own reference code; the commit message matches exactly;
`pytest modules/payroll/domain -q` gives 81 passed, 0 skipped (matches the brief's expected
count, no regressions). Two things carried into this task were checked concretely, not just
read: the net-floor wiring flagged by Task 7's review (`apply_net_floor`'s post-floor
`kept_lines` feed the totals, not `deduction_lines`'s raw pre-floor output — confirmed at
`engine.py:102-104` and behaviorally via `test_golden_net_negative_carries_the_overflow`, which
carries exactly 22 000 and clamps net to 0, never negative), and Review Focus #4, the daily-paid
contract (`test_golden_daily_worker` pins `pay_frequency="daily"` paying per worked + paid-leave
+ holiday day, never as a monthly salary). The controller wrote `task-9-report.md` on the
implementer's behalf and dispatched a reviewer on the normal path anyway — nothing here is taken
on faith without a second pass.

**Task 9 review:** Approved, zero Critical/Important findings. Both pinned risks independently
hand-traced to the exact franc against the actual code path (not re-read from docstrings) and
both check out; the diff is byte-identical to the brief's reference implementation; all
constraints hold; 81/81 domain tests pass. **1 Minor, deferred:** `earnings.py:70-73` — a
daily-paid employee's unpaid absence days are silently excluded from `paid_days` rather than
surfaced as an explicit `UNPAID_ABSENCE` line, asymmetric with the monthly path
(`earnings.py:78-82`); no golden test covers this combination. Not a blocker — flagged as a
follow-up golden test for a later task.

**Task 10 note:** the module's first DB-backed task (raw psycopg SQL, tenant-scoped). Carries
**Review Focus #1**: a confirmed rule set must refuse every edit/add/delete with
`RULESET_LOCKED`, because phase 3b will trust `confirmed_at` to gate payroll run approval. Both
the controller and the reviewer independently traced this across all five mutation paths
(`update_rule_set`, `delete_rule_set`, `add_child`, `update_child`, `delete_child`) rather than
accept the implementer's own claim — all five gate through either an explicit status check or the
shared `_editable` chokepoint, under `FOR UPDATE` row locking. `confirmed_at` correctly uses
`clock_timestamp()`, not `NOW()` (which freezes per-transaction in Postgres and would break the
later comparison against a run's calculation time). `modules/payroll -q`: 100 passed, 0 skipped,
against a real database (not silently skipped). **3 Minor, all deferred, none blocking:**
(1) `copy_rule_set`'s child-row `SELECT` doesn't itself filter by `tenant_id`, relying on
`rule_set_id` having already been tenant-checked one call earlier — not exploitable today, and
matches the brief's own reference code verbatim; (2) `update_child`/`delete_child`'s mutating SQL
keys on row `id` alone, same safe-by-read-sequence pattern; (3) `delete_rule_set`'s
`RULESET_IN_USE` / `ForeignKeyViolation` catch is currently dead code — no `payroll_runs` table
exists yet and all child tables cascade on delete — forward-looking for phase 3b, which must add
that FK as `ON DELETE RESTRICT` or the branch stays permanently unreachable.

**Task 11 note (last task of the phase):** thin HTTP wiring over Task 10's already-reviewed
service — 13 routes, each requiring a specific permission (`payroll.view_rules`,
`payroll.manage_rules`, or `payroll.confirm_rules`). Both the controller and the reviewer walked
every route against the brief's table individually rather than sampling; all match. The one risk
worth a second look — that FastAPI's declaration-order route matching could let the generic
`/rule-sets/{id}/{kind}` route swallow the fixed-word `/rule-sets/{id}/copy` and `.../confirm`
routes — was empirically tested by the reviewer (a throwaway POST to the `copy` route correctly
hit `copy_rule_set`, not the `{kind}` catch-all) rather than taken on the code's word. `106
passed, 0 skipped` on `modules/payroll` + the bilingual guard test, confirmed twice (implementer,
then independently by the controller and the reviewer) to be running for real against `httpx`,
not silently skipped. **1 Minor, non-blocking:** no shipped test directly exercises the `copy`
route reaching `copy_rule_set` (`confirm` has that coverage, `copy` doesn't) — a coverage gap,
verified not to be a live bug.

## Phase 3b — Payroll runs (13 tasks) — shipped (merged `1b1ae95`, pushed and deploying)

**Run differently from every earlier phase, at the client's request, this phase only:**
implementers run **in parallel and without per-task review**. Each parallel task gets its own
worktree (`.worktrees/p3b-tN`, branch `p3b-tN`) off the phase branch `hr-p3b-payroll-runs`
(worktree `.worktrees/hr-p3b-payroll-runs`, off `huge_production_migration` at `5db82f2`). After
each wave the controller cherry-picks the tasks onto the phase branch and runs the payroll suite.
That run checks the tasks integrate, it does not review them.
Baseline: `modules/payroll` + bilingual guard 109 passed, 0 skipped.

Waves (worked out from each task's files and imports):
1 → Tasks 1, 2, 3, 4 · 2 → 5 · 3 → 6 · 4 → 7, 8 · 5 → 9 · 6 → 10, 12, 13 · 7 → 11.
(Task 12 was first put with 9, but it uses Task 9's `http.csv_response`, so it moved to wave 6.)
Tasks 7 and 8 both added methods to `run_service.py`. Each was given a different place to insert
them, so their commits combined without conflict. After wave 4: 338 passed, 0 skipped.
Wave 6's three implementers all hit the session usage limit before committing, with every file
already written. The controller ran each task's tests (7, 6 and 5 new tests, matching the plan's
counts, 0 skipped), committed each one, and checked Task 13's return shapes against the
interfaces contract itself, since that agent never reported on them. After wave 6: 362 passed,
0 skipped.

**All 13 tasks built, 2026-09-29.** Phase branch `hr-p3b-payroll-runs` is 14 commits ahead of
`5db82f2`, not merged or pushed. `modules/payroll` plus the guards give 367 passed, 0 skipped.
Full backend suite on the branch: 2069 passed, 1 skipped, 4 failed. Three of the failures were
the go-live reset script not yet listing phase 3b's 12 new payroll tables, fixed in `795d0e2`:
11 purged, `payroll.bank_file_templates` kept. The fourth is the old unrelated
`test_a_team_used_by_a_quality_report_is_retired_too`. Payroll migrations 0002–0004 are on the
shared dev DB and are schema-only, so a deploy applies them by itself.
**Rest-day parameter (`49dc6f4`), at the client's request:** a daily-paid worker's worked rest
day used to draw its day rate and its full rest/holiday overtime. hr's month summary now
carries `rest_days_worked`, and each rule set has `daily_rest_day_pay`: `overtime_only` (the
default, like a monthly worker) or `day_rate_and_overtime`. Migration 0005 adds it. This closes
the gap carried over from phase 3a.
**Whole-branch review (Haiku, the cheapest model, at the client's request):** ready to merge.
No Critical findings. 1 Important, fixed in `521f28d`: two advance/loan release lookups weren't
scoped by tenant. They weren't reachable across tenants, but every payroll query must filter by
tenant. 1 Minor declined: it asked for an index on `payslips.run_id`, but `UNIQUE (run_id,
employee_id)` already provides one. There were no per-task reviews.
**Merged and pushed 2026-09-29** as `1b1ae95` to `origin` (deploys) and `personal`. Payroll
migrations 0002–0005 are schema-only and apply automatically on deploy. On the server, grant
the `payroll.*` codes the new routes use (runs, inputs, payouts, declarations,
admin_payslips). Keep `payroll.approve_runs` separate from `payroll.calculate_runs`, because
approval is refused to the user who calculated.

State 🟦 = built and integrated on the phase branch with the payroll suite green; no review, by
request.

| # | Task | State |
|---|---|---|
| 1 | Loan schedule and hr snapshot mapping (pure) | 🟦 `f2da6ad` |
| 2 | Payout arithmetic and files (pure) | 🟦 `3e7ffce` |
| 3 | Month-on-month variance and declarations (pure) | 🟦 `1f25850` |
| 4 | Runs table, `RunService` basics, reopening a rule set, test fakes for hr | 🟦 `c140762` (migration 0002 on dev DB) |
| 5 | Monthly inputs, advances and loans | 🟦 `5dc522a` (migration 0003 on dev DB) |
| 6 | Calculating a run | 🟦 `b1dd745` (hr contract shapes matched the plan exactly) |
| 7 | Final settlements on off-cycle runs | 🟦 `a4d2a61` |
| 8 | Approving and reversing runs, with outbox events | 🟦 `659993f` (Review Focus #1–#3 tests each failed first, then passed) |
| 9 | Payouts — bank files, mobile money, cash sheet, marking a run paid | 🟦 `e424cfd` (migration 0004 on dev DB) |
| 10 | Payslip reads, print data, work certificate, admin edit, variance | 🟦 `76b1f38` |
| 11 | HTTP routes for runs, payslips, inputs, advances and loans | 🟦 `af4c3a9` |
| 12 | Declarations and the annual recap | 🟦 `1f53770` |
| 13 | Contract services — `PayrollPostingService` and `PayrollReportService` | 🟦 `4105d86` (shapes checked against the interfaces contract) |

## Phase 3c — Payroll frontend & seed (11 tasks) — built (parallel, no review, by request)

Run like 3b: parallel implementers, no per-task review. Phase branch `hr-p3c-payroll-frontend`
(worktree `.worktrees/hr-p3c-payroll-frontend`) is cut from `hr-p3b-payroll-runs` at `49dc6f4`,
because 3c calls 3b's routes and 3b is not merged yet. Each task gets `.worktrees/p3c-tN` (branch `p3c-tN`),
with `frontend/node_modules` linked in as a junction. `.git/info/attributes` sets `merge=union` on `i18n.tsx` and
`router.tsx`, where tasks only add lines, so cherry-picks combine without conflicts.
Waves: 1 → Tasks 1, 9 · 2 → 2, 3, 4, 10 · 3 → 5, 6, 7, 8 · 4 → 11. The per-task manual browser checks
are all done in Task 11.

State 🟦 = built and integrated on the phase branch; no review, by request.

| # | Task | State |
|---|---|---|
| 1 | `api.ts`, `format.ts`, `PayrollTable`, `PayrollStatusBadge` | 🟦 `52f5a6e` |
| 2 | `DraftRuleSetBanner` and the Rules screens | 🟦 `ef720e6` |
| 3 | Runs list and create dialog | 🟦 `e7458a6` |
| 4 | Run detail page — lifecycle actions, payslips panel, settlements panel | 🟦 `dd37280` |
| 5 | Variance panel, and the Inputs page (monthly inputs, advances, loans) | 🟦 `6c65ab2` |
| 6 | Payouts panel, bank templates dialog, declarations panel | 🟦 `abf27fb` |
| 7 | Payslip detail page and edit dialog | 🟦 `860f37c` |
| 8 | Print pages — payslip, run, cash sheet, declaration | 🟦 `4dd1986` |
| 9 | Mali draft rule-set values (`payroll_mali_rules.py`) | 🟦 `a087a07` |
| 10 | Extend `seed_hr_payroll.py` — rule set, monthly inputs, advances/loans, one calculated run | 🟦 `f072034` |
| 11 | Grant demo permissions and browser-verify every `/payroll/*` screen against the seed | 🟦 `feb663f`, `34ea9bc` |

**Printing payroll** is Task 8: one payslip, a whole run in one print view ("print all"), the
cash sheet with its note-and-coin breakdown, and the declarations. As planned today this is
**browser printing, with no server-generated PDF** — see the open scope question below.

**Built 2026-09-29, no review by request, in parallel waves like 3b.** The branch is 11 commits
ahead of `49dc6f4` on `hr-p3c-payroll-frontend`, not merged. Task 11 (this task) ran last: granted
the demo user all 11 `payroll.*` permissions in the seed script (`feb663f`), re-ran the seed
against the local dev DB (idempotent — re-run twice, no error, no duplicate rows: 11 permission
rows, `ON CONFLICT DO NOTHING` on `(user_id, permission)`), and walked the running app as
`demo@sonalim-erp.local`. Verified working, browser-checked against the seed: `/payroll/rules`
(ML draft rule set, all 7 rule-row tabs with their seeded rows, country ML); `/payroll/runs`
(the August 2026 run: Calculated, Draft-rules badge, 64 payslips, gross 10 308 744 F CFA, net
9 571 520 F CFA — exact seed figures); the run page's draft-rule-set banner, all 5 tabs
(Payslips, Variance — correctly "no previous approved run", Final settlements — correctly the
off-cycle-only empty state, Payouts and Declarations — correctly empty pre-approval); all 3
Inputs tabs (the seeded `BONUS` run input, the approved advance, the active 6-instalment loan
with non-zero remaining); a payslip's lines grouped and ordered correctly with the loan
instalment deduction and the draft-rule-set warning; the payslip print page and the run print
page (64 payslip tables, one per employee), both correctly hiding the sidebar/header/print
button under `@media print`; the language toggle switching Rules, Runs, Run detail and Inputs
correctly between fr/en (the one place French text remains under English is the rule set's own
name, "Mali (brouillon, à confirmer)" — free-text data, not a UI string, so that's correct, not
a bug). Also confirmed Review Focus #2 firing exactly as designed: approving the run you
calculated is refused with a visible inline alert and toast (`SAME_USER_APPROVAL`), not silently
blocked.

**Follow-up (`34ea9bc`), completing what Task 11 stopped short of:** rather than leave the
approve → payouts → paid → declarations tail unverified, the seed now also creates
`payroll.approbateur@sonalim-erp.local` / `demo1234`, a second login holding only
`approve_runs`, `pay_runs`, `reverse_runs`, `view_runs`, `view_rules`, `view_declarations` —
never `calculate_runs` — so the four-eyes rule can be exercised for real instead of just
confirmed as a refusal. Walked end-to-end against the dev DB: confirmed the Mali rule set,
recalculated the run against it, approved as the second login (same-user approval correctly
refused first, exactly as Task 11 found), generated payouts (8 batches — 5 bank, 1 cash, 2
mobile money — split and totalled correctly; the missing-bank-template prompt fired correctly
for every bank with no template on file); confirmed the cash batch and two others, and the
cash-sheet print link appeared once confirmed. One real, unrelated data gap was found and fixed
along the way: 4 pre-existing dev employees (`EMP-001..004`, older than the payroll seed) had no
payment method on file, which correctly refused payout generation by naming each one
(`PAYOUT_SPLIT_INVALID`-style refusal, not swallowed) — fixed by giving them a cash payment
method through the real `PaymentMethodService`, not a migration or a workaround. Reversing the
run to pick up that fix (needed a recalculation, which a reversed run can't do) briefly left the
demo run in a `Extourné` state the seed script wouldn't repair on its own; deleted that one run
row (its payslips/inputs cascade by FK) and re-ran the seed, which rebuilt a fresh `Calculated`
run — now with correct payment methods for everyone from the start. **Still not walked:**
confirming the remaining 5 bank batches (would need 4 more bank-template entries) through to
mark-paid and the declarations tab actually populating — stopped there as diminishing-returns
manual clicking, not because anything failed; the mark-paid/declarations code itself is
unit-covered by 3b's own tests. No frontend bugs found in this pass either;
`npx tsc -b --force` stayed clean throughout. **What's left:** the duplicate-i18n-key note
between Tasks 7/8 (cosmetic, not reconciled), and the last stretch of the payout/mark-paid/
declarations click-through above. **Next step is the client's merge/PR choice**, same as 3b.

## Phase 4 — Finance ledger (15 tasks) — planned

A SYSCOHADA general ledger in `finance`, which payroll and invoices post into by event.

| # | Task | State |
|---|---|---|
| 1 | Balanced-entry builder (pure domain) | ⬜ |
| 2 | Posting rules and source mappings (pure domain) | ⬜ |
| 3 | Ledger master data — chart seed, journals, fiscal years, periods | ⬜ |
| 4 | Journal entries, triggers and the single posting path | ⬜ |
| 5 | Payroll events into the ledger (approved, paid, reversed) with dead-letter reasons and retry | ⬜ |
| 6 | Invoice events into the ledger (VTE / BNQ) | ⬜ |
| 7 | Editing the chart of accounts and the posting rules | ⬜ |
| 8 | Manual OD entries and the ledger's read side | ⬜ |
| 9 | Reports — trial balance, general ledger, 42x/43x/44x balances | ⬜ |
| 10 | Ledger HTTP routes | ⬜ |
| 11 | Frontend foundations, Chart of accounts and Posting rules screens | ⬜ |
| 12 | Journal entries screen (journal listing, manual OD entries, refused postings) | ⬜ |
| 13 | Trial balance (with 42x/43x/44x balances), General ledger and Periods screens | ⬜ |
| 14 | Posted / not posted on the payroll run page | ⬜ |
| 15 | Seed the demo ledger and post the seeded payroll run | ⬜ |

## Phase 5 — Analytics & self-service (10 tasks) — planned

| # | Task | State |
|---|---|---|
| 1 | Dashboard arithmetic (pure domain) | ⬜ |
| 2 | Expiry list (pure rules, horizon setting, service) | ⬜ |
| 3 | Analytics service (combine the contract sources) | ⬜ |
| 4 | Dashboard endpoints | ⬜ |
| 5 | Self-service: own-record selection and service | ⬜ |
| 6 | `/hr/me` endpoints | ⬜ |
| 7 | Payroll lets a payslip's owner read it through the print route | ⬜ |
| 8 | HR dashboard screen | ⬜ |
| 9 | `/me` self-service screen | ⬜ |
| 10 | Demo seed: link the demo login to an employee and grant self-service | ⬜ |

## Open scope — agreed with the client on 2026-09-28, not yet specified

The client asked for an HR module that competes with SAP and Odoo at a large company. These
gaps were found by reading the spec against that goal. All are **launch scope**; none is
designed or planned yet. They are grouped into sub-projects, each of which will get its own
spec, plan and build.

| Sub-project | Contents |
|---|---|
| **A — Platform foundations** (shared kernel) | File storage (upload, preview, access control, versions); document templates that produce PDFs; notifications (in-app, email, SMS) with per-person channel choice; a multi-level approval engine; Excel import |
| **B — HR core extensions** | Manager hierarchy and org chart; onboarding checklists that block signing until the papers are in; generated contracts, amendments, attestations, certificates, warning letters; e-signature; bulk employee import; salary history, raise campaigns, grade progression; discipline; offboarding |
| **C — Talent** | Recruitment (openings against the headcount budget through to hire); training and qualifications with expiry; performance reviews |
| **D — Health & safety** | Medical visits, work accidents, protective equipment |
| **E — Expenses & missions** | Expense claims, mission orders, daily allowances, paid through payroll or finance |
| **F — Self-service & manager space, multi-channel** (replaces phase 5's read-only version) | Web and phone, kiosk (badge + PIN), SMS — each employee choosing their channels; requests (attestation, RIB or address change, with approval); my presence and overtime; managers approve their team's leave and see their team's presence |
| **G — Analytics** (extends phase 5) | Turnover, age/seniority pyramids, gender mix and pay gap, headcount vs budget, leave liability, **labour cost per production line and work order**, Excel export |

**Proposed order:** phase 2 done → **A** → **B** → phase 3 (plans amended) → phase 4 →
**F** → **G** → **C, D, E**.

A comes first because B–F all sit on storage, notifications and approvals. B comes before
payroll because salary history and disciplinary suspensions feed payslips. C, D and E are the
natural place to slip if usage runs short: nothing else waits on them.

**Decisions this raises for the existing plans:**

1. **"No server-generated PDF" must be reconsidered.** Phases 3b/3c print through the browser.
   Signed contracts, archived payslips and emailed documents need real PDF files.
2. **Documents cannot currently be uploaded.** Phase 1 stores a path or URL in
   `hr.employee_documents.file_ref`; the platform has no file storage. Diploma and ID scans
   have nowhere to go until sub-project A lands.
3. **There is no manager hierarchy.** No "reports to" field exists, so leave approval today is
   "anyone holding the permission", with no chain.

**Already covered, to avoid re-asking:** the seniority bonus (phase 3a); bank details and RIB,
with splits across bank, mobile money and cash (phase 1); document *records* with expiry alerts
for ID card, passport, work permit, medical certificate, driving licence, diploma, criminal
record and signed contract (phase 1); payslip and declaration printing (phase 3c Task 8); the
HR dashboard and read-only self-service (phase 5).

## How this work runs

- Each phase is built in its own git worktree, off `huge_production_migration`, and merges on
  its own.
- Each task is implemented by a fresh agent from a written brief, then reviewed by another
  against that brief. Progress lives in the phase's SDD ledger
  (`.superpowers/sdd/<plan>/progress.md`), which is the checkpoint if a session is interrupted.
- After the last task: a whole-branch review, one round of fixes, then the client chooses how
  to integrate.
- Statutory Mali values are **never** written in code. They are database rows, seeded as
  drafts, which an accountant confirms before a payroll run can be approved.
- A push to `huge_production_migration` deploys to the live server. Since `9a57d12` the deploy
  applies pending schema migrations itself (`AUTO_MIGRATE` defaults to true); it never seeds, and
  a guard test keeps data inserts out of migrations.
