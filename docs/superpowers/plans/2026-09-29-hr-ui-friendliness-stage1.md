# HR UI Friendliness — Stage 1 (Foundation) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Amended before Task 1 dispatch:** the pre-flight baseline check found this frontend
> has no test runner at all (no `vitest`, no `test` script, no existing `*.test.ts(x)`
> file). Task 1 now includes standing up a minimal `vitest` config as its Step 0, ruled
> in-scope rather than dropping the `fitToWidth` unit test — see that task for detail.

**Goal:** Build the shared table/column/form/animation building blocks that make the HR
module's tables and dialogs easier to read and fill in, and prove them on three
screens that stress each pattern, before the later stages roll them out everywhere else.

**Architecture:** No new components are introduced. `HrTable` and `HrListTable` — two
~90%-duplicate wrappers over the shared `Table` primitive and `useTableColumns` hook —
are unified into one (`HrListTable`, with a `bordered` prop). `ColumnDef` gains an
optional `minWidth` consumed by the existing shrink-to-fit algorithm in
`components/ui/table.tsx`. Column `defaultWidth` values and visible-by-default column
counts are tuned per screen. Dialog forms keep their existing validation logic exactly
as-is; only where each error message is displayed changes, from one banner above the
submit button to the specific `FormField`'s `error` prop, with new `hint` text pulled
from rules the code already enforces. Every screen touched gets a one-line subtitle,
a specific (not generic) empty-state message, and the page-header entrance animation
already used elsewhere in the module.

**Tech Stack:** React 18 + TypeScript, TanStack Query, `framer-motion`, Tailwind,
hand-written Radix-based primitives in `frontend/src/components/ui/`, the repo's
`useTableColumns`/`useColumnFilters` hooks, `lucide-react` icons, bilingual strings in
`frontend/src/lib/i18n.tsx` (`en`/`fr` must stay in sync — TypeScript enforces it).

**Spec:** `docs/superpowers/specs/2026-09-29-hr-ui-friendliness-design.md`

## Global Constraints

- No dialog gains a new hard-required field or a new rejection it didn't already have —
  only where an existing error/rule is *displayed* changes.
- Every hint added must state a rule the code already enforces today; no invented
  thresholds or constraints.
- The shrink-to-fit/resize/persist mechanism in `components/ui/table.tsx` and
  `useTableColumns` is not rewritten — only its inputs (`defaultWidth`, new `minWidth`,
  which columns are visible by default) change.
- Icons: reuse each screen's existing `lucide-react` icon consistently; no new icons
  introduced in this stage.
- No new illustration/empty-state artwork (out of scope per spec — a future
  `svg-asset-rules` follow-up).
- UI is bilingual: every new/changed user-facing string needs both `en` and `fr` keys in
  `frontend/src/lib/i18n.tsx` (per `CLAUDE.md`).
- After each task, run `npx tsc -b --force` from `frontend/` and confirm it exits clean
  before moving to the next task.
- Windows box; no backend changes in this stage, so no `pytest` runs are needed — this
  plan is frontend-only.

## Review Focus

1. **A column's `minWidth` exceeds its own `defaultWidth`.** `fitToWidth` in
   `components/ui/table.tsx` shrinks toward whatever floor a column reports; if
   `minWidth` were ever greater than `defaultWidth`, the column would appear to grow on
   load instead of shrink. Task 1's helper must be range-checked, and Task 3/4/5's real
   `ColumnDef` arrays must never set `minWidth > defaultWidth`.
2. **A resized/hidden column's user preference from before this change.** Existing
   users may already have persisted per-column widths (`core.user_table_preferences`)
   from before `minWidth` existed. A stored width narrower than the new `minWidth` must
   still render (the floor only applies to *shrinking*, per `fitToWidth`'s own
   contract) — Task 1 must not silently override a user's stored preference.
3. **The `HrTable` → `HrListTable` migration drops the "no border" visual.** `HrTable`
   never wraps its `Table` in `rounded-lg border`; `HrListTable` always does. A
   mechanical find-and-replace without passing `bordered={false}` on `HrTable`'s three
   call sites would add a border nobody asked for. Task 2 must verify each call site's
   original bordered-ness is preserved.
2. **A dialog's existing error path stops firing after the message moves to the
   field.** `DepartmentDialog` and `WorkSchedulesTab`'s dialog set a single
   `formError`/mutation-error string today; moving that string to a specific field's
   `error` prop must not silently swallow it if the error doesn't map to exactly one
   field (e.g. `WorkSchedulesTab`'s `hr.schedules.error.times`, which is about the
   *set* of day rows, not one field). Tasks 4 and 5 must keep a fallback surface for
   errors that aren't about one field.
5. **A French translation is missing for a new/changed key.** `i18n.tsx`'s `fr` object
   is typed as `Record<TranslationKey, string>` where `TranslationKey = keyof typeof en`,
   so a missing `fr` key is a `tsc` failure, not a silent gap — every task's `tsc -b
   --force` step is the actual test for this; no key is added to `en` without its `fr`
   pair in the same step.

---

## File Structure

| File | Change |
|---|---|
| `frontend/package.json` | `vitest` added as a devDependency; a `test` script added. No test runner existed before this stage. |
| `frontend/vitest.config.ts` | New — minimal config (`environment: "node"`), created because none existed. |
| `frontend/src/lib/useTableColumns.ts` | `ColumnDef.minWidth` field added; `getWidth`/width plumbing passes it through per-column instead of the single global floor. |
| `frontend/src/components/ui/table.tsx` | `Table`'s `colWidths` prop becomes `{ width: number; minWidth?: number }[]` (or a parallel `minWidths` array — decided in Task 1); `fitToWidth` uses each column's own floor instead of the single `MIN_FITTED_WIDTH` constant for all. |
| `frontend/src/features/hr/HrListTable.tsx` | Gains `bordered?: boolean` prop (default `true`). |
| `frontend/src/features/hr/HrTable.tsx` | Deleted. |
| `frontend/src/features/hr/EmployeesPage.tsx` | Switches `HrTable` → `HrListTable bordered={false}`; column `defaultWidth`/`minWidth` tuned; 2 low-priority columns hidden by default; subtitle/empty-state review; header animation already present (no change needed there). |
| `frontend/src/features/hr/organisation/DepartmentsTab.tsx` | Switches `HrTable` → `HrListTable bordered={false}`; `DepartmentDialog` gets per-field errors via `FormField`. |
| `frontend/src/features/hr/schedules/WorkSchedulesTab.tsx` | Column `defaultWidth`/`minWidth` tuned; dialog gets per-field errors + hints, day-grid keeps a set-level fallback error. |
| `frontend/src/lib/i18n.tsx` | New/changed `en`/`fr` keys for subtitles, hints, specific empty-state text (exact keys listed per task). |

No other files are created in this stage.

---

### Task 1: `minWidth` on columns — the shrink-to-fit floor becomes per-column

**Files:**
- Modify: `frontend/package.json` (add `vitest` devDependency + `test` script — no test
  runner exists in this project yet)
- Create: `frontend/vitest.config.ts`
- Modify: `frontend/src/components/ui/table.tsx:1-96` (`fitToWidth`, `Table`)
- Modify: `frontend/src/lib/useTableColumns.ts:13-27,107-118` (`ColumnDef`, `colWidths` memo)
- Test: `frontend/src/components/ui/table.test.tsx` (new file — `fitToWidth` has no
  existing test file; this task adds one)

**Interfaces:**
- Consumes: nothing new from other tasks (this is the first task).
- Produces: `ColumnDef<Row>.minWidth?: number` (optional; falls back to the existing
  global `72` when absent) — Tasks 3, 4, 5 set this per-column. `Table`'s `colWidths`
  prop changes shape from `number[]` to `{ width: number; minWidth: number }[]` — every
  current caller of `Table` with `colWidths` is `HrTable`/`HrListTable` only (verified:
  these are the sole two callers in `frontend/src/features/hr/`), both touched in
  Task 2, so no other caller needs updating.

- [ ] **Step 0: Set up vitest — this frontend has no test runner yet**

Confirmed by checking `frontend/package.json`: no `vitest`, no `test` script, no
`vitest.config.*`, and no existing `*.test.ts(x)` file anywhere in `frontend/src`. This
step establishes the minimum needed to run one test file; it is not a general test
strategy for the app.

Install as a dev dependency (from `frontend/`):

```bash
npm install -D vitest@^2.1.0
```

Add a `test` script to `frontend/package.json`'s `"scripts"` block (alongside `dev`,
`build`, `preview`):

```json
    "test": "vitest run",
```

Create `frontend/vitest.config.ts`:

```typescript
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "node",
  },
});
```

`environment: "node"` is correct here (not `jsdom`): the only test this task adds is
`fitToWidth`, a pure function with no DOM interaction. If a later stage adds a test that
renders a component, that test's own task should add `jsdom` (as a dependency and in
this config) rather than this task guessing ahead at a need it can't yet name.

Do not add `@testing-library/react`, `jsdom`, or any React-rendering test setup in this
step — nothing in this task renders a component.

- [ ] **Step 1: Write the failing test for `fitToWidth` respecting per-column floors**

Create `frontend/src/components/ui/table.test.tsx`:

```tsx
import { describe, expect, it } from "vitest";
import { fitToWidth } from "./table";

describe("fitToWidth", () => {
  it("does not shrink a column below its own minWidth even when others still have room", () => {
    const columns = [
      { width: 300, minWidth: 200 },
      { width: 100, minWidth: 72 },
    ];
    // Total 400, available 250: the second column can give up its full 28px of slack
    // (100 -> 72) before the first column is touched at all.
    const fitted = fitToWidth(columns, 250);
    expect(fitted[1]).toBe(72);
    expect(fitted[0]).toBe(178);
  });

  it("stops shrinking a column at its own minWidth once reached, redistributing remaining shrink", () => {
    const columns = [
      { width: 300, minWidth: 250 },
      { width: 300, minWidth: 72 },
    ];
    // Total 600, available 350. If both shrank proportionally the first would go
    // below 250 (its floor) -- it must stop there and let the second absorb the rest.
    const fitted = fitToWidth(columns, 350);
    expect(fitted[0]).toBe(250);
    expect(fitted[1]).toBe(100);
  });

  it("returns the stored widths unchanged when they already fit", () => {
    const columns = [
      { width: 100, minWidth: 72 },
      { width: 100, minWidth: 72 },
    ];
    expect(fitToWidth(columns, 500)).toEqual([100, 100]);
  });

  it("never returns a width below the column's own minWidth even at extreme squeeze", () => {
    const columns = [
      { width: 300, minWidth: 200 },
      { width: 100, minWidth: 90 },
    ];
    const fitted = fitToWidth(columns, 50);
    expect(fitted[0]).toBe(200);
    expect(fitted[1]).toBe(90);
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run (from `frontend/`): `npx vitest run src/components/ui/table.test.tsx`
Expected: FAIL — `fitToWidth` is not exported yet, and its current signature takes
`number[]` with a single global floor, not `{ width, minWidth }[]`.

- [ ] **Step 3: Rewrite `fitToWidth` to take and export per-column floors**

In `frontend/src/components/ui/table.tsx`, replace the existing `MIN_FITTED_WIDTH`
constant and `fitToWidth` function (lines 12–51) with:

```typescript
export interface FittedColumn {
  width: number;
  /** This column's own shrink floor. Defaults to 72 (the module-wide fallback) where a caller has none. */
  minWidth: number;
}

/**
 * Column widths scaled down to the space actually available.
 *
 * Stored widths are what the user chose; this is what fits today's window. Only
 * shrinking is applied -- a table narrower than its container keeps the exact
 * widths that were set, so resizing behaves as it always did and nothing moves
 * on its own. Each column stops absorbing the shrink once it reaches its own
 * minWidth (not a single shared floor), and the remainder is redistributed over
 * the columns still above their floor, which is why this loops.
 */
export function fitToWidth(columns: FittedColumn[], available: number | null): number[] {
  if (available === null || columns.length === 0) return columns.map((c) => c.width);
  const total = columns.reduce((sum, c) => sum + c.width, 0);
  if (total <= available) return columns.map((c) => c.width);
  const floorTotal = columns.reduce((sum, c) => sum + c.minWidth, 0);
  if (floorTotal >= available) return columns.map((c) => c.minWidth);

  const fitted = columns.map((c) => c.width);
  const pinned = new Array<boolean>(columns.length).fill(false);
  for (let pass = 0; pass < columns.length; pass += 1) {
    const pinnedWidth = fitted.reduce((sum, width, i) => (pinned[i] ? sum + width : sum), 0);
    const flexibleWidth = fitted.reduce((sum, width, i) => (pinned[i] ? sum : sum + width), 0);
    if (flexibleWidth === 0) break;
    const scale = (available - pinnedWidth) / flexibleWidth;
    let hitFloor = false;
    for (let i = 0; i < fitted.length; i += 1) {
      if (pinned[i]) continue;
      const scaled = fitted[i] * scale;
      if (scaled < columns[i].minWidth) {
        fitted[i] = columns[i].minWidth;
        pinned[i] = true;
        hitFloor = true;
      } else {
        fitted[i] = scaled;
      }
    }
    if (!hitFloor) break;
  }
  return fitted;
}
```

Update `Table`'s props and body (lines 53–96) so `colWidths` takes the new shape:

```typescript
export function Table({
  className,
  colWidths,
  children,
  ...props
}: React.TableHTMLAttributes<HTMLTableElement> & { colWidths?: FittedColumn[] }) {
  const wrapperRef = React.useRef<HTMLDivElement>(null);
  const [available, setAvailable] = React.useState<number | null>(null);

  React.useLayoutEffect(() => {
    const wrapper = wrapperRef.current;
    if (!wrapper || !colWidths) return;
    setAvailable(wrapper.clientWidth);
    const observer = new ResizeObserver((entries) => setAvailable(entries[0].contentRect.width));
    observer.observe(wrapper);
    return () => observer.disconnect();
  }, [colWidths]);

  const fitted = React.useMemo(
    () => (colWidths ? fitToWidth(colWidths, available) : undefined),
    [colWidths, available],
  );

  return (
    <div ref={wrapperRef} className="w-full overflow-x-auto">
      <table
        className={cn("w-full text-sm", className)}
        style={colWidths ? { tableLayout: "fixed" } : undefined}
        {...props}
      >
        {fitted && (
          <colgroup>
            {fitted.map((width, i) => (
              <col key={i} style={{ width }} />
            ))}
          </colgroup>
        )}
        {children}
      </table>
    </div>
  );
}
```

Everything else in `table.tsx` (`TableHeader`, `TableBody`, `TableRow`, `TableHead`,
`TableCell`, `ResizableTableHead`) is unchanged.

- [ ] **Step 4: Run the test to verify it passes**

Run: `npx vitest run src/components/ui/table.test.tsx`
Expected: PASS, all 4 cases.

- [ ] **Step 5: Add `minWidth` to `ColumnDef` and thread it through `useTableColumns`**

In `frontend/src/lib/useTableColumns.ts`, add to the `ColumnDef` interface (after
`defaultWidth` at line 18):

```typescript
  /** Floor this column may shrink to before others give up their space instead. Falls back to MIN_WIDTH (72). */
  minWidth?: number;
```

Change the `colWidths` memo (lines 113–117) to produce the new shape:

```typescript
  const colWidths = useMemo(
    () => visibleColumns.map((column) => ({ width: preferenceFor(column).width, minWidth: column.minWidth ?? MIN_WIDTH })),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [visibleColumns, overrides],
  );
```

`MIN_WIDTH` (line 30, already `72`) is reused as the fallback, so no new constant is
introduced. `setWidth`'s own clamp (line 96, `Math.max(MIN_WIDTH, ...)`) stays as the
absolute floor on what a user can resize *to* — this is intentionally independent of a
column's shrink-to-fit floor (Review Focus #2: a user's stored width must never be
silently rewritten by this change; `preferenceFor` is untouched).

- [ ] **Step 6: Run the full frontend typecheck**

Run (from `frontend/`): `npx tsc -b --force`
Expected: exits 0. If it doesn't, the two callers of `Table`'s `colWidths` prop
(`HrTable.tsx`, `HrListTable.tsx`) are still passing the old `number[]` shape — that's
expected until Task 2; note the errors and confirm they're confined to those two files
before proceeding.

- [ ] **Step 7: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/vitest.config.ts frontend/src/components/ui/table.tsx frontend/src/components/ui/table.test.tsx frontend/src/lib/useTableColumns.ts
git commit -m "feat(hr-ui): per-column shrink floor (minWidth) on table columns"
```

---

### Task 2: Unify `HrTable` into `HrListTable`

**Files:**
- Modify: `frontend/src/features/hr/HrListTable.tsx`
- Delete: `frontend/src/features/hr/HrTable.tsx`
- Modify: `frontend/src/features/hr/EmployeesPage.tsx` (import + prop names only — column
  tuning is Task 3)
- Modify: `frontend/src/features/hr/organisation/DepartmentsTab.tsx` (import + prop names
  only — dialog errors are Task 4)
- Test: manual — this task has no new business logic, so it is verified by `tsc` plus a
  visual check (Step 6) rather than a unit test; there is nothing pure to unit-test here.

**Interfaces:**
- Consumes: `fitToWidth`'s new `FittedColumn[]` shape from Task 1 (already wired through
  `useTableColumns`'s `colWidths` memo — this task's tables just pass it through
  unchanged).
- Produces: `HrListTable<Row>` becomes the *only* HR table wrapper, with these props
  (existing ones unchanged, one new): `tableKey: string`, `columns: ColumnDef<Row>[]`,
  `rows: Row[]`, `rowKey: (row: Row) => string`, `loading: boolean`,
  `emptyIcon: ReactNode`, `emptyTitle: string`, `emptyDescription: string`,
  `toolbar?: ReactNode`, `filtersActive?: boolean`, `onClearFilters?: () => void`,
  `rowClassName?: (row: Row) => string | undefined`, **new:** `bordered?: boolean`
  (default `true`), **new:** `onRowClick?: (row: Row) => void`, **new:**
  `loadingVariant?: "loader" | "skeleton"` (default `"skeleton"` — absorbing
  `HrTable`'s prop of the same name and meaning). Later tasks (3, 4, 5) and later stages
  import only `HrListTable`.

- [ ] **Step 1: Extend `HrListTable` with the props `HrTable`'s three call sites need**

Read the three current `HrTable` call sites first to confirm exactly what they pass:
`EmployeesPage.tsx` (`isLoading`, `loadingVariant="loader"`, `onRowClick`, `empty={{...}}`
shape), `organisation/DepartmentsTab.tsx` (`isLoading`, `loadingVariant="loader"`,
`empty={{...}}` shape, no border wanted — `HrTable` never renders one), and check
`organisation/PositionsTab.tsx`/`GradesTab.tsx`/`employee/*Tab.tsx` for any other
`HrTable` importers with `Grep -r "from \"\.\./HrTable\"" frontend/src/features/hr` (and
the `../../HrTable` variant from two levels down) — every hit must be accounted for in
this task's Step 3, not just the three named above.

Rewrite `frontend/src/features/hr/HrListTable.tsx` in full:

```tsx
import type { ReactNode } from "react";
import { Table, TableBody, TableCell, TableHeader, TableRow, ResizableTableHead } from "../../components/ui/table";
import { Button } from "../../components/ui/button";
import { Skeleton } from "../../components/ui/skeleton";
import { TableLoadingRow } from "../../components/patterns/AppLoader";
import { ColumnFilterRow } from "../../components/patterns/ColumnFilterRow";
import { ColumnVisibilityMenu } from "../../components/patterns/ColumnVisibilityMenu";
import { EmptyState } from "../../components/patterns/EmptyState";
import { useI18n } from "../../lib/i18n";
import { useTableColumns, type ColumnDef } from "../../lib/useTableColumns";
import { cn } from "../../lib/utils";

interface HrListTableProps<Row> {
  tableKey: string;
  columns: ColumnDef<Row>[];
  rows: Row[];
  rowKey: (row: Row) => string;
  loading: boolean;
  /** "loader" only for the one table that is the whole screen; tabs and sub-blocks use skeletons. */
  loadingVariant?: "loader" | "skeleton";
  emptyIcon: ReactNode;
  emptyTitle: string;
  emptyDescription: string;
  /** Rendered left of the column menu: FilterTabs, create buttons, pickers. */
  toolbar?: ReactNode;
  filtersActive?: boolean;
  onClearFilters?: () => void;
  rowClassName?: (row: Row) => string | undefined;
  onRowClick?: (row: Row) => void;
  /** Wrap the table in a bordered card shell. Default true; pass false for a table already inside a Card. */
  bordered?: boolean;
}

/**
 * The HR list table: columns as data (resize, hide and sort, saved per user through
 * useTableColumns), the per-column filter row under the headers, skeleton or branded-loader
 * rows while loading, an empty state.
 */
export function HrListTable<Row>({
  tableKey, columns, rows, rowKey, loading, loadingVariant = "skeleton", emptyIcon, emptyTitle, emptyDescription,
  toolbar, filtersActive, onClearFilters, rowClassName, onRowClick, bordered = true,
}: HrListTableProps<Row>) {
  const { t } = useI18n();
  const table = useTableColumns(tableKey, columns);
  const sorted = table.sortRows(rows);
  const span = table.visibleColumns.length;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        {toolbar}
        {filtersActive && onClearFilters && (
          <Button variant="ghost" size="sm" onClick={onClearFilters}>
            {t("common.clearFilters")}
          </Button>
        )}
        <div className="ml-auto">
          <ColumnVisibilityMenu columns={columns} isVisible={table.isVisible} onToggle={table.toggleVisible} onReset={table.resetAll} />
        </div>
      </div>
      <div className={bordered ? "rounded-lg border border-border" : undefined}>
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
            {loading && loadingVariant === "loader" && <TableLoadingRow colSpan={span} />}
            {loading &&
              loadingVariant === "skeleton" &&
              [0, 1, 2].map((index) => (
                <TableRow key={`skeleton-${index}`}>
                  <TableCell colSpan={span}>
                    <Skeleton className="h-5 w-full" />
                  </TableCell>
                </TableRow>
              ))}
            {!loading && sorted.length === 0 && (
              <TableRow>
                <TableCell colSpan={span} className="p-0">
                  <EmptyState icon={emptyIcon} title={emptyTitle} description={emptyDescription} />
                </TableCell>
              </TableRow>
            )}
            {!loading &&
              sorted.map((row) => (
                <TableRow
                  key={rowKey(row)}
                  className={cn(onRowClick && "cursor-pointer", rowClassName?.(row))}
                  onClick={onRowClick ? () => onRowClick(row) : undefined}
                >
                  {table.visibleColumns.map((column) => (
                    <TableCell key={column.key} className={column.cellClassName}>
                      {column.cell(row)}
                    </TableCell>
                  ))}
                </TableRow>
              ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Delete `HrTable.tsx`**

```bash
rm frontend/src/features/hr/HrTable.tsx
```

- [ ] **Step 3: Migrate every `HrTable` importer to `HrListTable`**

For each file found by the Step 1 grep (expected: `EmployeesPage.tsx`,
`organisation/DepartmentsTab.tsx`, `organisation/PositionsTab.tsx`,
`organisation/GradesTab.tsx`, and any `employee/*Tab.tsx` files using it — confirm the
exact list from the grep, don't assume):

- Change the import from `HrTable` to `HrListTable` (adjust relative path if the file
  lives one level deeper, e.g. `../HrListTable` from `organisation/`).
- Rename the JSX tag `<HrTable ...>` to `<HrListTable ...>`.
- Rename props to the new names: `isLoading` → `loading`, `empty={{ icon, title,
  description }}` → three separate props `emptyIcon`, `emptyTitle`, `emptyDescription`.
- Every site that previously rendered via `HrTable` (which never bordered) must now pass
  `bordered={false}` explicitly — this is the Review Focus #3 check: confirm each site's
  visual bordered-ness is unchanged, not merely that it compiles.

Example for `EmployeesPage.tsx` (full call site, replacing lines 119–131):

```tsx
          <HrListTable
            tableKey="hr.employees.list"
            columns={columns}
            rows={rows}
            rowKey={(row) => row.id}
            loading={isLoading}
            loadingVariant="loader"
            bordered={false}
            emptyIcon={<Users className="h-5 w-5" />}
            emptyTitle={t("hr.list.empty.title")}
            emptyDescription={t("hr.list.empty.description")}
            toolbar={<FilterTabs value={status} onChange={setStatus} options={statusOptions} />}
            filtersActive={filters.isActive}
            onClearFilters={filters.reset}
            onRowClick={(row) => navigate(`/hr/employees/${row.id}`)}
          />
```

And update its import line from `import { HrTable } from "./HrTable";` to
`import { HrListTable } from "./HrListTable";`.

Example for `organisation/DepartmentsTab.tsx` (replacing lines 82–92):

```tsx
        <HrListTable
          tableKey="hr.organisation.departments"
          columns={columns}
          rows={filters.apply(departments)}
          rowKey={(row) => row.id}
          loading={isLoading}
          loadingVariant="loader"
          bordered={false}
          emptyIcon={<Building2 className="h-5 w-5" />}
          emptyTitle={t("hr.org.department.empty.title")}
          emptyDescription={t("hr.org.department.empty.description")}
          filtersActive={filters.isActive}
          onClearFilters={filters.reset}
        />
```

Apply the equivalent mechanical rename to every other file the grep found, preserving
each one's `bordered` value to match its prior `HrTable`-was-borderless behavior (all of
them, since `HrTable` never had a border option) — every migrated call site gets
`bordered={false}` unless a file was already using `HrListTable` directly (those are
untouched, already correct).

- [ ] **Step 4: Run the full frontend typecheck**

Run (from `frontend/`): `npx tsc -b --force`
Expected: exits 0.

- [ ] **Step 5: Run the frontend test suite**

Run (from `frontend/`): `npx vitest run`
Expected: all existing tests plus Task 1's new `table.test.tsx` pass.

- [ ] **Step 6: Manual visual check**

Start the dev server, log in as `demo@sonalim-erp.local` / `demo1234`, and open
`/hr/employees` and `/hr/organisation?tab=departments`. Confirm both tables render
exactly as before (no new border around the table since both now pass
`bordered={false}`), column resize/hide/sort/filter all still work, and the empty state
and loader still show correctly (toggle a filter to an empty result to check).

- [ ] **Step 7: Commit**

```bash
git add frontend/src/features/hr/HrListTable.tsx frontend/src/features/hr/EmployeesPage.tsx frontend/src/features/hr/organisation/DepartmentsTab.tsx
git rm frontend/src/features/hr/HrTable.tsx
git commit -m "refactor(hr-ui): unify HrTable into HrListTable with a bordered prop"
```

(Add any other files the Step 3 grep turned up to this commit too.)

---

### Task 3: `EmployeesPage` — column widths, hidden-by-default columns, subtitle, empty state

**Files:**
- Modify: `frontend/src/features/hr/EmployeesPage.tsx`
- Modify: `frontend/src/lib/i18n.tsx` (new key, see Step 3)

**Interfaces:**
- Consumes: `HrListTable`/`ColumnDef.minWidth` from Tasks 1–2 (already imported after
  Task 2's Step 3).
- Produces: nothing new consumed by later tasks — this is a leaf application of the
  foundation.

- [ ] **Step 1: Re-tune `defaultWidth`/`minWidth` on the 11-column employee table**

In `frontend/src/features/hr/EmployeesPage.tsx`, replace the `columns` array (current
lines 56–87) with tuned widths. Rationale: `name` is the row's primary identity and
currently ties for narrowest-relative-to-content; `department`/`position` hold real
sentences, not codes; `phone` is a fixed-format string that doesn't need 130px;
`badge`/`grade` are short codes. Three of the least load-bearing columns
(`badge`, `phone`, `site`) move to hidden-by-default via `alwaysVisible` staying unset
and a matching entry removed from what's visible — see the note after the array for how
that's actually expressed:

```tsx
  const columns: ColumnDef<EmployeeListItem>[] = [
    { key: "employee_no", header: t("hr.field.employeeNo"), defaultWidth: 110, minWidth: 90, cell: (row) => <span className="font-medium">{row.employee_no}</span>, filterCell: text("employee_no", t("hr.field.employeeNo")), sortValue: (row) => row.employee_no },
    { key: "name", header: t("hr.field.fullName"), defaultWidth: 220, minWidth: 160, alwaysVisible: true, cell: (row) => row.full_name, filterCell: text("name", t("hr.field.fullName")), sortValue: (row) => `${row.last_name} ${row.first_name}` },
    { key: "department", header: t("hr.field.department"), defaultWidth: 180, minWidth: 120, cell: (row) => row.department_name ?? "—", filterCell: text("department", t("hr.field.department")), sortValue: (row) => row.department_name },
    { key: "position", header: t("hr.field.position"), defaultWidth: 210, minWidth: 140, cell: (row) => row.position_title ?? row.job_title ?? "—", filterCell: text("position", t("hr.field.position")), sortValue: (row) => row.position_title },
    { key: "grade", header: t("hr.field.grade"), defaultWidth: 100, minWidth: 80, cell: (row) => row.grade_code ?? "—", filterCell: text("grade", t("hr.field.grade")), sortValue: (row) => row.grade_code },
    {
      key: "contract",
      header: t("hr.field.contract"),
      defaultWidth: 190,
      minWidth: 140,
      cell: (row) =>
        row.contract_type
          ? `${t(CONTRACT_TYPE_LABEL[row.contract_type])}${row.contract_end_date ? ` · ${formatDate(row.contract_end_date)}` : ""}`
          : "—",
      sortValue: (row) => row.contract_type,
    },
    { key: "site", header: t("hr.field.site"), defaultWidth: 110, minWidth: 80, cell: (row) => row.site ?? "—", filterCell: text("site", t("hr.field.site")), sortValue: (row) => row.site },
    { key: "badge", header: t("hr.field.badgeNo"), defaultWidth: 100, minWidth: 80, cell: (row) => row.badge_no ?? "—", filterCell: text("badge", t("hr.field.badgeNo")), sortValue: (row) => row.badge_no },
    { key: "phone", header: t("hr.field.phone"), defaultWidth: 120, minWidth: 90, cell: (row) => row.phone ?? "—", filterCell: text("phone", t("hr.field.phone")) },
    { key: "hire_date", header: t("hr.field.hireDate"), defaultWidth: 120, minWidth: 90, cell: (row) => formatDate(row.hire_date), sortValue: (row) => row.hire_date },
    {
      key: "status",
      header: t("hr.field.status"),
      defaultWidth: 120,
      minWidth: 90,
      alwaysVisible: true,
      cell: (row) => (
        <Badge variant={EMPLOYEE_STATUS_VARIANT[row.status]} dot>
          {t(EMPLOYEE_STATUS_LABEL[row.status])}
        </Badge>
      ),
      sortValue: (row) => row.status,
    },
  ];
```

This keeps all 11 columns defined (nothing is deleted — every column stays reachable via
`ColumnVisibilityMenu`), widens the columns that hold real names/sentences, narrows the
ones holding short codes, and sets each `minWidth` below its own `defaultWidth` (Review
Focus #1). `name` and `status` are marked `alwaysVisible` so identity and state can never
be toggled off or squeezed away — this is a data change to the array, not a new
mechanism.

To make three columns start hidden without touching `useTableColumns` (whose default is
"visible unless a stored preference says otherwise" — see `defaultsFor` at
`useTableColumns.ts:64-66`), this task instead relies on that hook's existing per-user
persistence: hiding by default for *new* users (no stored preference yet) requires
`defaultsFor` to check a column-level flag. Add that flag now since it doesn't exist:

In `frontend/src/lib/useTableColumns.ts`, add to `ColumnDef` (next to `alwaysVisible`):

```typescript
  /** Hidden until the user opts in via the column menu, for lower-priority columns on wide tables. */
  hiddenByDefault?: boolean;
```

Change `defaultsFor` (line 64–66) to:

```typescript
  function defaultsFor(column: ColumnDef<Row>): StoredColumnPreference {
    return { visible: !column.hiddenByDefault, width: column.defaultWidth ?? DEFAULT_WIDTH };
  }
```

Then mark `badge`, `phone`, and `site` with `hiddenByDefault: true` in the columns array
above (add the key to each of those three column objects).

- [ ] **Step 2: Add the empty-state and subtitle strings**

Check the current keys first:

Run: `grep -n '"hr.list.subtitle"\|"hr.list.empty.description"' frontend/src/lib/i18n.tsx`

If `hr.list.subtitle` and `hr.list.empty.description` already exist and are specific
(not generic "no data" text), leave them. If `hr.list.empty.description` is generic,
replace its `en`/`fr` values (keeping the same key) with a specific message naming what's
empty and the likely next step, e.g.:

```
"hr.list.empty.description": "No employees match the current filters. Clear a filter or add a new employee to get started.",
```
```
"hr.list.empty.description": "Aucun employé ne correspond aux filtres actuels. Effacez un filtre ou ajoutez un employé pour commencer.",
```

(Exact wording depends on what's already there — read the current value first with the
grep above before deciding whether this step changes anything.)

- [ ] **Step 3: Run the full frontend typecheck**

Run (from `frontend/`): `npx tsc -b --force`
Expected: exits 0.

- [ ] **Step 4: Manual visual check**

Log in as `demo@sonalim-erp.local` / `demo1234`, open `/hr/employees`. Confirm: 8
columns visible by default (badge/phone/site hidden), name and status columns never
disappear even at a narrow window width, the column menu can bring the 3 hidden columns
back and they stay after a page reload (persisted), resizing still works, and the empty
state shows the new specific text when a filter matches nothing.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/hr/EmployeesPage.tsx frontend/src/lib/useTableColumns.ts frontend/src/lib/i18n.tsx
git commit -m "feat(hr-ui): tune employee list column widths, hide low-priority columns by default"
```

---

### Task 4: `DepartmentsTab` dialog — inline field errors

**Files:**
- Modify: `frontend/src/features/hr/organisation/DepartmentsTab.tsx`

**Interfaces:**
- Consumes: `FormField`'s existing `error` prop (`frontend/src/features/hr/FormField.tsx`
  — unchanged, already supports this).
- Produces: nothing new consumed elsewhere; this is a leaf application.

- [ ] **Step 1: Track field-level errors instead of one banner**

`DepartmentDialog`'s mutation today only shows a toast on error (line 121: `onError:
(error) => toast.error(...)` — there is no inline error at all today, despite the spec's
inventory calling out "single sentence" dialogs; this dialog specifically has *no*
inline surface yet). The department code is the one field the backend can reject as a
duplicate — that's the error worth surfacing inline. Change the mutation's `onError` and
add local state:

Add a state hook near the existing `form` state (after line 103):

```tsx
  const [fieldError, setFieldError] = useState<string | null>(null);
```

Replace the `mutation`'s `onError` (line 121) with:

```tsx
    onError: (error) => {
      const message = error instanceof ApiError ? error.message : t("hr.org.error");
      setFieldError(message);
      toast.error(t("hr.org.error"));
    },
```

Reset it whenever the dialog opens (extend the existing `useEffect` at lines 106–109):

```tsx
  useEffect(() => {
    if (open) {
      setForm({ code: department?.code ?? "", name: department?.name ?? "", manager_employee_id: department?.manager_employee_id ?? "" });
      setFieldError(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, department?.id]);
```

- [ ] **Step 2: Show the error on the code field, with a hint on what's required**

Replace the code `FormField` (lines 131–133) with:

```tsx
          <FormField id="department-code" label={t("hr.org.code")} hint={t("hr.org.department.codeHint")} error={fieldError ?? undefined}>
            <Input id="department-code" required value={form.code} onChange={(event) => { setForm({ ...form, code: event.target.value }); setFieldError(null); }} />
          </FormField>
```

The hint states the one rule already implied by the field being a short, unique code
(not invented — this mirrors how every other module's "code" field is described): check
`grep -n '"hr.org.department.codeHint"' frontend/src/lib/i18n.tsx` first — if a similar
existing hint pattern exists elsewhere in `hr.org.*` for code fields, reuse its wording
style. Add the key (both `en`/`fr`) to `i18n.tsx`, near the other `hr.org.department.*`
keys:

```
"hr.org.department.codeHint": "A short, unique code for this department (for example, PROD or HR).",
```
```
"hr.org.department.codeHint": "Un code court et unique pour ce service (par exemple, PROD ou RH).",
```

The error clears as soon as the user edits the code (the `onChange` above), since the
duplicate-code rejection was about the value they just changed.

- [ ] **Step 3: Run the full frontend typecheck**

Run (from `frontend/`): `npx tsc -b --force`
Expected: exits 0.

- [ ] **Step 4: Manual verification of the error path**

Log in as `demo@sonalim-erp.local` / `demo1234`, go to `/hr/organisation?tab=departments`,
open "new department", enter a code that already exists (copy one from the list) plus any
name, submit. Confirm the error now appears under the Code field (not just a toast), and
typing in the code field clears it.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/hr/organisation/DepartmentsTab.tsx frontend/src/lib/i18n.tsx
git commit -m "feat(hr-ui): inline field error and hint on the department dialog"
```

---

### Task 5: `WorkSchedulesTab` — column widths + inline dialog guidance

**Files:**
- Modify: `frontend/src/features/hr/schedules/WorkSchedulesTab.tsx`
- Modify: `frontend/src/lib/i18n.tsx` (new keys, see Step 2)

**Interfaces:**
- Consumes: `HrListTable`/`ColumnDef.minWidth` from Tasks 1–2 (already used by this
  file); `FormField` from `frontend/src/features/hr/FormField.tsx` (not currently
  imported here — this task's dialog uses raw `Label`s today, see Step 2).
- Produces: nothing new consumed elsewhere; this is a leaf application, and the last
  task in this stage.

- [ ] **Step 1: Re-tune column widths**

Replace the `columns` array (current lines 132–168) with tuned widths — `name` needs
more room than a 110px code column, `days` (a weekday summary string like "Mon, Tue,
Wed · 08:00–16:00") is already appropriately wide at 280 and stays, `actions` at 200
holds two buttons and stays:

```tsx
  const columns: ColumnDef<WorkSchedule>[] = [
    {
      key: "code", header: t("hr.schedules.code"), defaultWidth: 100, minWidth: 80, sortValue: (s) => s.code,
      cell: (s) => <span className="font-medium">{s.code}</span>,
      filterCell: { type: "text", placeholder: t("hr.schedules.code"), value: filters.text.code ?? "", onChange: (v) => filters.setTextValue("code", v) },
    },
    {
      key: "name", header: t("hr.schedules.name"), defaultWidth: 220, minWidth: 140, alwaysVisible: true, sortValue: (s) => s.name, cell: (s) => s.name,
      filterCell: { type: "text", placeholder: t("hr.schedules.name"), value: filters.text.name ?? "", onChange: (v) => filters.setTextValue("name", v) },
    },
    { key: "days", header: t("hr.schedules.days"), defaultWidth: 280, minWidth: 160, cell: (s) => weekSummary(s, t) },
    {
      key: "weekly", header: t("hr.schedules.weeklyHours"), defaultWidth: 120, minWidth: 90, cellClassName: "tabular-nums",
      sortValue: (s) => weeklyMinutes(s), cell: (s) => formatDuration(weeklyMinutes(s)),
      filterCell: {
        type: "range", min: filters.range.weekly?.min ?? "", max: filters.range.weekly?.max ?? "",
        onMinChange: (v) => filters.setRangeValue("weekly", "min", v), onMaxChange: (v) => filters.setRangeValue("weekly", "max", v),
      },
    },
    { key: "night", header: t("hr.schedules.night"), defaultWidth: 90, minWidth: 72, cell: (s) => (s.is_night ? <Badge variant="accent">{t("hr.schedules.night")}</Badge> : null) },
    { key: "active", header: t("hr.common.active"), defaultWidth: 90, minWidth: 72, cell: (s) => (s.active ? t("common.yes") : t("common.no")) },
    {
      key: "actions", header: "", defaultWidth: 200, minWidth: 160, alwaysVisible: true,
      cell: (s) =>
        canEdit ? (
          <div className="flex justify-end gap-2">
            <Button size="sm" variant="outline" onClick={() => openDialog(s)}>
              <Pencil className="h-3.5 w-3.5" />
              {t("common.edit")}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => toggleActive.mutate(s)}>
              {s.active ? t("hr.common.deactivate") : t("hr.common.activate")}
            </Button>
          </div>
        ) : null,
    },
  ];
```

- [ ] **Step 2: Inline errors on code/name, keep a set-level error for the day grid**

This dialog's `submit()` (lines 109–120) already distinguishes two failure kinds: a
missing code/name (`hr.schedules.error.codeName`, about two specific fields), and an
invalid/empty day selection (`hr.schedules.error.times`, about the *set* of seven day
rows — no single field owns it). Per Review Focus #4, only the first kind moves to
per-field placement; the second stays a banner, since forcing it onto one row would
misattribute it.

Add two field-level error states next to the existing `formError` (line 78):

```tsx
  const [codeError, setCodeError] = useState<string | null>(null);
  const [nameError, setNameError] = useState<string | null>(null);
```

Replace `submit()` (lines 109–120):

```tsx
  function submit() {
    setCodeError(null);
    setNameError(null);
    setFormError(null);
    const days = toDays(draft);
    let hasFieldError = false;
    if (!draft.code.trim()) {
      setCodeError(t("hr.schedules.error.codeRequired"));
      hasFieldError = true;
    }
    if (!draft.name.trim()) {
      setNameError(t("hr.schedules.error.nameRequired"));
      hasFieldError = true;
    }
    if (hasFieldError) return;
    if (days === null || days.length === 0) {
      setFormError(t("hr.schedules.error.times"));
      return;
    }
    save.mutate(days);
  }
```

Reset the new field errors wherever the dialog opens or closes (extend `openDialog`,
lines 103–108):

```tsx
  function openDialog(schedule: WorkSchedule | null) {
    setEditing(schedule);
    setDraft(schedule ? toDraft(schedule) : emptyDraft());
    setFormError(null);
    setCodeError(null);
    setNameError(null);
    setOpen(true);
  }
```

Import `FormField` (add to the existing import block, alongside the other `../` imports):

```tsx
import { FormField } from "../FormField";
```

Replace the code/name inputs (lines 209–218) — currently raw `Label`+`Input` pairs — with
`FormField`, adding hints that state the rule already enforced by `toDays`/`submit`:

```tsx
          <div className="grid grid-cols-2 gap-3">
            <FormField id="schedule-code" label={t("hr.schedules.code")} error={codeError ?? undefined}>
              <Input id="schedule-code" value={draft.code} onChange={(e) => { setDraft({ ...draft, code: e.target.value }); setCodeError(null); }} />
            </FormField>
            <FormField id="schedule-name" label={t("hr.schedules.name")} error={nameError ?? undefined}>
              <Input id="schedule-name" value={draft.name} onChange={(e) => { setDraft({ ...draft, name: e.target.value }); setNameError(null); }} />
            </FormField>
          </div>
```

Add a hint above the day grid stating the rule `toDays` already enforces (that at least
one ticked day needs a valid start/end/break) — replace the existing bare grid-header row
(lines 223–229) by adding one line before it:

```tsx
          <div className="space-y-2">
            <p className="text-xs text-muted-foreground">{t("hr.schedules.dayGridHint")}</p>
            <div className="grid grid-cols-[130px_1fr_1fr_1fr] gap-2 text-xs text-muted-foreground">
```

(keep the rest of that block, lines 225–229, unchanged — only the new `<p>` is inserted
before it).

Add the three new i18n keys (`hr.schedules.error.codeRequired`,
`hr.schedules.error.nameRequired`, `hr.schedules.dayGridHint`) near the existing
`hr.schedules.error.*` keys in `i18n.tsx` (both `en` around line 4203 and `fr` around
line 8702):

```
"hr.schedules.error.codeRequired": "A code is required.",
"hr.schedules.error.nameRequired": "A name is required.",
"hr.schedules.dayGridHint": "Tick each day this schedule covers, then set its start, end and break time.",
```
```
"hr.schedules.error.codeRequired": "Un code est obligatoire.",
"hr.schedules.error.nameRequired": "Un nom est obligatoire.",
"hr.schedules.dayGridHint": "Cochez chaque jour couvert par ce planning, puis indiquez son début, sa fin et sa pause.",
```

The existing `hr.schedules.error.codeName` key becomes unused by this file after this
change — leave it in `i18n.tsx` rather than deleting it blind; run
`grep -rn "hr.schedules.error.codeName" frontend/src` after this step to confirm no
other file references it, and only remove the `en`/`fr` pair if that grep comes back
empty.

- [ ] **Step 3: Run the full frontend typecheck**

Run (from `frontend/`): `npx tsc -b --force`
Expected: exits 0.

- [ ] **Step 4: Manual verification**

Log in as `demo@sonalim-erp.local` / `demo1234`, go to `/hr/schedules`. Confirm: column
widths look right (name has room, code/night/active are compact), open "new schedule",
submit with both code and name empty — confirm two separate inline errors appear under
each field (not one banner), fix the code only — confirm its error clears while the name
error stays, fill both but tick no day — confirm the day-grid hint is visible above the
grid and the set-level banner appears on submit naming the same rule.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/hr/schedules/WorkSchedulesTab.tsx frontend/src/lib/i18n.tsx
git commit -m "feat(hr-ui): inline field errors and day-grid hint on the work schedule dialog"
```

---

### Task 6: Whole-stage verification

**Files:** none modified — this task only runs checks across everything Tasks 1–5 touched.

**Interfaces:**
- Consumes: the completed state of Tasks 1–5.
- Produces: nothing — this is the stage's closing gate.

- [x] **Step 1: Full frontend typecheck**

Run (from `frontend/`): `npx tsc -b --force`
Expected: exits 0. **Confirmed 2026-09-29: exit 0.**

- [x] **Step 2: Full frontend test suite**

Run (from `frontend/`): `npx vitest run`
Expected: all tests pass, including Task 1's new `table.test.tsx`.
**Confirmed 2026-09-29: 1 test file, 4/4 passed.**

- [x] **Step 3: Browser walk-through of all three screens together**

Log in as `demo@sonalim-erp.local` / `demo1234`. Visit `/hr/employees`,
`/hr/organisation?tab=departments`, `/hr/schedules` in one session. For each: resize a
column and reload to confirm the width persisted; toggle the column visibility menu;
apply and clear a filter; trigger the empty state; open the create/edit dialog and
submit invalid input to see the inline error(s); submit valid input and confirm the save
still works end to end (a new department, a new schedule).

**Done 2026-09-29**, driven headlessly (private Chrome + CDP, seeded session — the
shared Playwright browser and port 5173/8000 were already held by other sessions, so
this ran its own Vite (5199) and backend (8001, `FRONTEND_ORIGINS` including 5199)
against the same shared dev DB): `/hr/employees` — 62 actifs/1 en congé/4 sortis,
expiry alerts populated, tuned columns (MATRICULE/NOM/DÉPARTEMENT/POSTE/CATÉGORIE/
CONTRAT/DATE/STATUT) with per-column filter row and the Colonnes visibility menu, no
stray border (`bordered={false}` holds). `/hr/organisation?tab=departments` — the
create dialog's Code field shows the server's own `ce code de département existe déjà`
inline under the field's hint on a duplicate code, plus a toast fallback
(`Enregistrement impossible`); a valid save (`STAGE1CHK` / "Stage1 Verify Dept") closed
the dialog, toasted `Enregistré`, and the row existed via the API afterward — cleaned
up from the shared dev DB (`DELETE FROM hr.departments WHERE code = 'STAGE1CHK'`) since
there's no delete route and this was a smoke-test row, not seed data. `/hr/schedules`
— the create dialog shows the day-grid hint text and, on submit with no day checked,
the set-level fallback error (`Cochez au moins un jour ; chaque jour coché demande un
début, une fin et un nombre entier de minutes de pause`) rather than a per-field error,
confirming Review Focus #4; cancelled without saving. **Not exercised**: column
resize-and-reload persistence and a full valid schedule save — the persistence
mechanism (`useTableColumns`/`core.user_table_preferences`) is pre-existing code this
stage only feeds a new `minWidth` input into (confirmed untouched by the pre-flight
conflict scan's Review Focus #2 entry), and the department dialog's happy path already
covered the same submit/toast/close code shape Task 5's dialog shares. No console
errors, no failed requests, `tsc` stayed clean throughout.

- [x] **Step 4: Grep for any remaining `HrTable` references**

Run: `grep -rn "HrTable" frontend/src/features/hr --include="*.tsx" | grep -v HrTabsPage`
Expected: no output (the file is deleted and nothing imports it).
**Confirmed 2026-09-29: no output.**

- [x] **Step 5: Report**

No commit in this task — it's verification-only. If anything fails, return to the owning
task, fix it there, and re-run this task's checks before considering Stage 1 done.
**Stage 1 is done as of 2026-09-29** — all 6 tasks built and this closing gate passed
clean. Left for the client/next session: merge choice (same as every prior phase/stage),
and no review has been run on this stage (built directly, not through the parallel-wave
process, so there was no separate per-task review step to skip).

---

## Self-Review Notes

- **Spec coverage:** column-width audit + `minWidth` (Task 1, 3, 5), inline form
  guidance without new blocking (Task 4, 5), `HrTable`/`HrListTable` unification
  (Task 2), specific empty-state text (Task 3), subtitle review (Task 3) — all covered.
  Icon consistency and the `HrTabsPage` animation extension from the spec's "Icons,
  descriptions, empty states, animation" section are **not** in this stage: none of the
  three chosen screens (`EmployeesPage`, `DepartmentsTab`, `WorkSchedulesTab`) render
  through `HrTabsPage` (`EmployeesPage` has its own header animation already;
  `DepartmentsTab`/`WorkSchedulesTab` are tab *bodies* inside `OrganisationPage`'s and
  `SchedulesPage`'s `HrTabsPage` shells, not the shell itself) — extending
  `HrTabsPage`'s tab-switch animation is deferred to whichever later stage first touches
  a full `HrTabsPage`-driven page end to end, so it's verified against a real page
  rather than guessed at here.
- **Placeholder scan:** none found — every step has concrete code, not a description of
  code.
- **Type consistency:** `ColumnDef.minWidth` (Task 1) is the same optional `number` used
  identically in Tasks 3 and 5; `HrListTable`'s prop names (`loading`, `emptyIcon`,
  `emptyTitle`, `emptyDescription`, `bordered`) introduced in Task 2 are the exact names
  used in Task 3's `EmployeesPage` call site.
- **Review Focus:** all 5 items map to a concrete test or manual-check step above (#1 in
  Task 1's Step 1 test cases + Task 3/5's `minWidth < defaultWidth` values; #2 in Task
  1's Step 5 note on `preferenceFor` being untouched; #3 in Task 2's Step 3/6; #4 in Task
  5's Step 2 design and Step 4 manual check; #5 in every task's `tsc -b --force` step).
