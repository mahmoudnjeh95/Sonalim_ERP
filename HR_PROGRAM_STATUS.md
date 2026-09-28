# HR / Payroll / Finance ledger — what is built, what is next

Last updated: **2026-09-28**. Written for the client and for whoever picks this work up.

This is the running record of the HR programme: the 89 planned tasks, which are built, which
were reviewed, and where work stopped. When it disagrees with `git log` or a phase's SDD
ledger, those win — they move first.

- Spec: `docs/superpowers/specs/2026-09-25-hr-payroll-finance-design.md`
- Cross-phase contract: `docs/superpowers/plans/2026-09-25-hr-payroll-finance-interfaces.md`
- Phase plans: `docs/superpowers/plans/2026-09-25-hr-p{1,2,3a,3b,3c,4,5}-*.md`

## Where we stopped

> **IN PROGRESS: phase 2, Task 13 — building `/hr/leave` (last screen; only the seed, Task 14,
> follows).**
>
> Next action: review Task 13 once committed, then run Task 14.

Branch `hr-p2-presence-leave` in the worktree `.worktrees/hr-p2-presence-leave`, off
`huge_production_migration` at `d77c1a2`. Nothing of phase 2 is merged or pushed.

**One decision waiting on the client:** commit `02372b2` sits on `huge_production_migration`
in the main checkout by mistake — a helper committed there instead of in the worktree. It holds
only the two leave-domain files, which are also on the HR branch as `252dbd5`. It is local, on
no remote. It would deploy with the next push of that branch. To drop it, run
`git reset --keep d77c1a2` in the main checkout.

## Progress

| Phase | Tasks | Built | Reviewed | State |
|---|---|---|---|---|
| 1 — Employee core | 15 | 15 | 15 | **Shipped** (merged as `d77c1a2`, deployed) |
| 2 — Presence & leave | 14 | 12 | 12 | **In progress** — Task 13 building |
| 3a — Payroll engine | 11 | 0 | 0 | Planned |
| 3b — Payroll runs | 13 | 0 | 0 | Planned |
| 3c — Payroll frontend & seed | 11 | 0 | 0 | Planned |
| 4 — Finance ledger | 15 | 0 | 0 | Planned |
| 5 — Analytics & self-service | 10 | 0 | 0 | Planned |
| **Total** | **89** | **27** | **26** | |

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

## Phase 2 — Presence & leave (14 tasks) — in progress

Worktree `.worktrees/hr-p2-presence-leave`. Migrations 0010–0014. The `modules/hr` suite was
163 tests before this phase and is **295 passed, 0 skipped** now.

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
| 13 | `/hr/leave` — leave types, requests with approval, balances | — | 🔨 building |
| 14 | Extend the dev seed with a month of presence, a clock sample and leave | — | ⬜ |

After Task 14: a whole-branch review, one round of fixes, then the client chooses how to
integrate (merge locally, a PR, or keep the branch).

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
`hr.leave.*` keys (type/dates/approve/reject/new/created/bulk*/dialog.*) untouched.

## Phase 3a — Payroll engine (11 tasks) — planned

New `payroll` module: configurable, effective-dated Mali rule tables and a pure calculation
engine. Statutory values are seeded as **drafts**; a run cannot be approved until an accountant
confirms them.

| # | Task | State |
|---|---|---|
| 1 | Module skeleton, rule tables, permissions, wiring | ⬜ |
| 2 | Money rounding, engine value objects, rule set, synthetic test rules | ⬜ |
| 3 | Rule row validation and the confirmation gate | ⬜ |
| 4 | Engine step 1 — earnings up to the gross | ⬜ |
| 5 | Engine steps 2–3 — contributable base, ceilings, contributions | ⬜ |
| 6 | Engine step 4 — taxable base, brackets, reliefs, tax rounding | ⬜ |
| 7 | Engine steps 5–6 — deductions, net floor with carry-forward, employer charges, totals | ⬜ |
| 8 | Final settlement arithmetic | ⬜ |
| 9 | The engine — `calculate_payslip` and golden payslips | ⬜ |
| 10 | `RuleSetService` — payroll country, rule sets, rows, confirmation, loading | ⬜ |
| 11 | Rules HTTP routes | ⬜ |

The **seniority bonus** (prime d'ancienneté — the client's "loyalty bonus") is a configurable
scale of years to a percentage of base salary, in Task 2's rule tables and Task 4's earnings step.

## Phase 3b — Payroll runs (13 tasks) — planned

| # | Task | State |
|---|---|---|
| 1 | Loan schedule and hr snapshot mapping (pure) | ⬜ |
| 2 | Payout arithmetic and files (pure) | ⬜ |
| 3 | Month-on-month variance and declarations (pure) | ⬜ |
| 4 | Runs table, `RunService` basics, reopening a rule set, test fakes for hr | ⬜ |
| 5 | Monthly inputs, advances and loans | ⬜ |
| 6 | Calculating a run | ⬜ |
| 7 | Final settlements on off-cycle runs | ⬜ |
| 8 | Approving and reversing runs, with outbox events | ⬜ |
| 9 | Payouts — bank files, mobile money, cash sheet, marking a run paid | ⬜ |
| 10 | Payslip reads, print data, work certificate, admin edit, variance | ⬜ |
| 11 | HTTP routes for runs, payslips, inputs, advances and loans | ⬜ |
| 12 | Declarations and the annual recap | ⬜ |
| 13 | Contract services — `PayrollPostingService` and `PayrollReportService` | ⬜ |

## Phase 3c — Payroll frontend & seed (11 tasks) — planned

| # | Task | State |
|---|---|---|
| 1 | `api.ts`, `format.ts`, `PayrollTable`, `PayrollStatusBadge` | ⬜ |
| 2 | `DraftRuleSetBanner` and the Rules screens | ⬜ |
| 3 | Runs list and create dialog | ⬜ |
| 4 | Run detail page — lifecycle actions, payslips panel, settlements panel | ⬜ |
| 5 | Variance panel, and the Inputs page (monthly inputs, advances, loans) | ⬜ |
| 6 | Payouts panel, bank templates dialog, declarations panel | ⬜ |
| 7 | Payslip detail page and edit dialog | ⬜ |
| 8 | Print pages — payslip, run, cash sheet, declaration | ⬜ |
| 9 | Mali draft rule-set values (`payroll_mali_rules.py`) | ⬜ |
| 10 | Extend `seed_hr_payroll.py` — rule set, monthly inputs, advances/loans, one calculated run | ⬜ |
| 11 | Grant demo permissions and browser-verify every `/payroll/*` screen against the seed | ⬜ |

**Printing payroll** is Task 8: one payslip, a whole run in one print view ("print all"), the
cash sheet with its note-and-coin breakdown, and the declarations. As planned today this is
**browser printing, with no server-generated PDF** — see the open scope question below.

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

**Proposed order:** finish phase 2 → **A** → **B** → phase 3 (plans amended) → phase 4 →
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
- A push to `huge_production_migration` deploys to the live server, and never runs migrations
  or seeds there. Migrations are handed over as SQL to run by hand.
