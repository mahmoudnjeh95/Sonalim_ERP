# HR module UI friendliness — design

Date: 2026-09-29
Status: approved, staged rollout not yet built

## Goal

Make the shipped HR screens (employee core, organisation, presence, schedules, leave —
phases 1 and 2, all merged on `huge_production_migration`) easier to read and use day to
day: less cramped tables, guidance instead of hard blocking on forms, and a module that
feels designed rather than bare. Out of scope: the payroll frontend (phase 3c, unmerged
branch `hr-p3c-payroll-frontend`) and the legacy `/hr` page (`HrPage.tsx`) — both left
alone, to revisit separately later.

## Inventory (as found, 2026-09-29)

51 files, ~6,900 lines across `frontend/src/features/hr/{employee,organisation,presence,
schedules,leave}`. Full per-screen breakdown was gathered by an Explore pass and is not
repeated here; the load-bearing facts:

- All list/grid screens go through one of two nearly-identical wrappers, `HrTable.tsx`
  (card-embedded, no border) and `HrListTable.tsx` (bordered) — both built on the shared
  `Table` primitive (`components/ui/table.tsx`) and `useTableColumns` (column defs as
  data: `{ key, header, defaultWidth, cell, filterCell?, sortValue?, ... }`).
- `Table` already auto-shrinks fixed column widths to the container via `ResizeObserver`,
  down to a single global 72px floor, and falls back to horizontal scroll. Widths are
  user-resizable and persisted per `tableKey`. This mechanism is sound — the "tiny
  columns" complaint is under-sized `defaultWidth` values and too many visible columns at
  once (some tables run 10–13 columns), not a missing capability.
- `FormField.tsx` already supports a `hint` (muted helper text) and `error`
  (destructive text) slot per field. Exactly one dialog (`EmployeeFormDialog.tsx`) uses
  it with Zod + react-hook-form for real per-field errors. Every other create/edit dialog
  (20+) uses plain `useState` with a single free-text error line above the submit button
  and native HTML `required` — no per-field inline guidance.
- Icons are `lucide-react` only, small, inline next to text — no large/decorative use.
  No illustrations anywhere in `features/hr` (no `.svg` imports). Animation is limited to
  `framer-motion` page-header fade/slide and `AnimatePresence` tab transitions on the
  `EmployeeFilePage`/`OrganisationPage` family; the `HrTabsPage`-driven screens (Presence,
  Schedules, Leave) just toggle `hidden` with no transition.
- Shared `components/patterns/` has more than HR currently uses (e.g. `DateRangeFilter`,
  `HelpTooltip`) — reuse before inventing new components.

## Principles

1. **Widen the mechanism's inputs, don't replace the mechanism.** The resize/persist/
   shrink-to-fit table system stays. Fix the `defaultWidth`/`minWidth` values feeding it,
   and reduce default visible-column count on the worst offenders via the existing
   `ColumnVisibilityMenu` (hide-by-default, not delete).
2. **Guidance, not new blocking.** No dialog gains a new hard-required field or a new
   rejection it didn't already have. Per-field inline errors and hints replace the
   single-sentence error banner; they surface the same validation that exists today,
   closer to the field it's about.
3. **Reuse existing assets before adding new ones.** Icons: reuse each tab's existing
   `lucide-react` icon consistently in the header, don't invent a new icon language.
   Illustrations: none added in this program — large illustration/empty-state artwork is
   its own follow-up under the `svg-asset-rules` skill, not bundled here. Animation:
   extend the existing `framer-motion` page/tab pattern to the screens missing it; no new
   animation language.
4. **One unified table wrapper.** Fold `HrTable` into `HrListTable` behind a `bordered`
   prop; delete the duplicate.
5. **Stage and verify on real screens before rolling out.** Each stage ends with
   `tsc -b --force` clean and a browser walk-through against the demo login, per this
   repo's standing verification practice, before the next stage starts.

## Design details

### Column widths

- Audit every `ColumnDef[]` in the module. Widen `defaultWidth` for text-bearing columns
  (names, multi-word statuses, free text) that are currently set at 90–140px when their
  typical content needs more; narrow icon-only/short/badge-only columns that are
  currently over-wide.
- Add an optional `minWidth` to `ColumnDef` (default falls back to the existing global
  72px floor) so a column central to the row's identity (employee name, status) can
  refuse to shrink below a readable width before secondary columns give up their space.
  This only changes the floor `fitToWidth` shrinks a column *to*; the shrink algorithm
  itself in `table.tsx` is unchanged.
- For tables at 10+ visible columns (`EmployeesPage` list, `ContractsTab`,
  `MonthCloseTab` summary, `LeaveTypesTab`), move 2–3 lower-priority columns to
  hidden-by-default (still togglable via `ColumnVisibilityMenu`, which already persists
  per user) instead of showing all columns cramped.

### Forms — inline guidance

- Every create/edit dialog keeps its current validation rules (nothing new becomes
  required or newly rejected). The single free-text error banner is replaced by passing
  the relevant message to the specific `FormField`'s `error` prop.
- Add a `hint` line under fields whose valid format or constraint isn't obvious from the
  label alone (examples found in the inventory: holiday's 2-letter country code, payment
  method share percentages summing to 100, rotation anchor date must be a Monday,
  schedule's at-least-one-working-day rule). Hints are pulled from validation messages
  that already exist in the code (no invented thresholds — every hint states a rule the
  code already enforces).
- `EmployeeFormDialog` (the one Zod-based form) is the reference pattern for the error
  slot's look; it is not required reading for how other dialogs get their errors — those
  stay on manual `useState` validation, just with per-field placement.

### Icons, descriptions, empty states, animation

- Every tab body and every page header gets a one-line description under its title
  stating what the screen is for, where one isn't already present.
- Keep each screen's existing `lucide-react` icon as its consistent visual identity
  (tab icon in the tab bar, repeated in the page/card header) rather than introducing
  new icons.
- Every `EmptyState` usage gets a specific, situational message (what's empty and, where
  useful, the next action) instead of a generic "no data" string.
- Extend the existing `framer-motion` fade/slide entrance pattern (already on
  `EmployeesPage`, `EmployeeFilePage`, `OrganisationPage`) to the `HrTabsPage`-driven
  screens (Presence, Schedules, Leave) that currently switch tabs with a bare `hidden`
  toggle, using the same easing/duration already established — consistency, not a new
  animation style.

### Table unification

- `HrListTable` gains a `bordered?: boolean` prop (default true, matching its current
  behavior). `HrTable` is deleted; its call sites (employee/organisation tabs) switch to
  `HrListTable` with `bordered={false}` where they currently render without a border.

## Staging

Each stage below is a self-contained unit: build, `tsc -b --force`, browser-verify with
the demo login (`demo@sonalim-erp.local` / `demo1234`), then check in before the next
stage. Later stages may adjust based on what Stage 1 surfaces in practice.

1. **Foundation.** Build the column-width audit tooling/rules, the `minWidth` addition,
   the inline-error/hint convention, the `HrTable`→`HrListTable` unification, and the
   tab-transition animation extension. Apply all of it to three representative screens
   chosen to stress each pattern: `EmployeesPage.tsx` (11-column table, worst-case
   column crowding), `organisation/DepartmentsTab.tsx` (simple table + simple dialog,
   proves the unified wrapper and inline errors on the easy case), and
   `schedules/WorkSchedulesTab.tsx` (weekday-grid dialog, the most complex manual
   validation in the module, proves inline errors hold up under complexity).
2. **Employee core rollout.** Apply the foundation to the remaining `EmployeeFilePage`
   tabs: Contracts, Family, Payment, Documents, Leave (the read-only one), and the file
   page's own tab transitions.
3. **Organisation rollout.** Positions, Grades, Settings tabs.
4. **Presence & schedules rollout.** Day/Week grids (care needed: cells hold live
   `Select`/`Input`/`Checkbox` controls, not static text — column-width changes must not
   break editability), Employee Month calendar tile grid, Month Close, Clock Imports/
   Review/Profiles, and the Schedules tabs (Rotations, Assignments, Holidays, Presence
   Settings).
5. **Leave rollout.** Leave Requests, Balances, Types.

## Explicitly out of scope

- Payroll frontend (`hr-p3c-payroll-frontend` branch, unmerged) — revisit after it's
  reviewed/merged.
- Legacy `/hr` page (`HrPage.tsx`) — left as-is; a separate future decision (redesign vs.
  remove) once its functionality overlap with `/hr/leave` and the employee file is
  resolved.
- New illustration artwork / empty-state graphics — a follow-up under `svg-asset-rules`,
  not bundled here.
- Migrating all dialogs to Zod + react-hook-form — only the error/hint *placement*
  changes; the validation mechanism (manual vs. Zod) is unchanged per dialog.
- Searchable/combobox select primitive — the native `<select>` stays; not part of this
  program.
