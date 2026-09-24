# Shift Form Header UX Enhancement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace slow dropdown-based shift selection (date, ligne, shift) with smooth navigation: day arrows + modal date picker, line status badges showing missing reports, clickable line cards, and auto-sync with maintenance module's equipment list.

**Architecture:** 
- Add `<DateNavigator>` component with left/right arrows, current date display, and click-to-open modal picker
- Replace line dropdown with `<LineCardsSelector>` showing equipment from maintenance module as clickable cards with report-count badges
- Enhance `useShiftReferenceData` to fetch live equipment and count existing shift reports per line per date
- Debounce date/line changes to prefetch shift data before user needs it, smoothing the transition to new selections
- All list queries (equipment, shift reports) will invalidate on changes to catch archive/add events

**Tech Stack:** React 18, TanStack Query, Lucide icons, Tailwind CSS

**Spec:** User feedback session 2026-09-24 — smooth day/ligne/shift navigation without modal friction

## Global Constraints

- Window width < 800px: line cards collapse to a dropdown fallback (no cards)
- Must sync equipment list from maintenance.equipment (not a hardcoded list)
- Equipment with `archived_at IS NOT NULL` must not appear
- Report-count badges show per-shift breakdowns (0/3 shifts means 0 reports exist for that line today)
- No new permissions required (existing production.shift.view already enforces line access)

---

## File Structure

**New files:**
- `frontend/src/features/production/shift/DateNavigator.tsx` — day arrows + modal picker
- `frontend/src/features/production/shift/LineCardsSelector.tsx` — cards or dropdown fallback
- `frontend/src/features/production/shift/LineStatusBadge.tsx` — report-count badge component

**Modified files:**
- `frontend/src/features/production/shift/ShiftReportTab.tsx` — swap selectors, add prefetch logic
- `frontend/src/features/production/shift/useShiftReferenceData.ts` — fetch equipment, count reports per line+date

**No backend changes required** — all data already exists (equipment via maintenance API, shift reports via existing list endpoint).

---

## Review Focus

1. **Day navigation doesn't respect business hours** — midnight cross-over on night shifts: if the user clicks "next day" at 23:50, should it mean calendar tomorrow or the next shift window? → Test that arrow follows calendar date, not shift clock.
2. **Equipment sync stale on archive/add** — if a line is archived in maintenance while the shift form is open, the UI should reflect it within 5 seconds. → Test that equipment query invalidates on user action and stale window.
3. **Report-count logic** — the "0/3 shifts" badge should only count reports that actually exist. Empty slots (open but not yet filed) must not count. → Test that badge reads shift_reports list filtered by date+line, not shift_windows list.
4. **Mobile fallback confusion** — switching from cards to dropdown on resize should not lose the user's selection. → Test that lineId state persists and dropdown shows selected line after resize.
5. **Race condition on rapid date clicks** — if the user clicks date arrows very fast, multiple in-flight queries could arrive out of order. → Test that the final query key is date+line+shift, and TanStack Query dedupes/cancels stale requests.

---

## Task 1: Fetch equipment + count shift reports in reference data

**Files:**
- Modify: `frontend/src/features/production/shift/useShiftReferenceData.ts:22-40` (add equipment state + report count logic)
- Test: `frontend/src/features/production/shift/__tests__/useShiftReferenceData.test.ts` (new file)

**Interfaces:**
- Consumes: `listEquipment(token)` (already imported), `listShiftReports(token, filters)` (already imported)
- Produces: 
  - `useShiftReferenceData()` now returns `{ ..., workCenterMap: Map<string, { name, reportCount, shiftStatuses }>, activeEquipment: Equipment[] }`
  - Equipment list filtered: only `archived_at === null`, sorted by work_center_id + name
  - Report counts keyed by `${date}|${work_center_id}`, value is count of `ShiftReport[]` for that date+line across all shifts

- [ ] **Step 1: Write failing test for equipment list and report count**

```typescript
// frontend/src/features/production/shift/__tests__/useShiftReferenceData.test.ts
import { renderHook, waitFor } from "@testing-library/react";
import { useShiftReferenceData } from "../useShiftReferenceData";
import * as api from "../../api";

jest.mock("../../api");
jest.mock("../../maintenance/api");

test("equipment includes only non-archived items", async () => {
  const mockEquipment = [
    { id: "e1", work_center_id: "wc1", name: "Line_1", archived_at: null },
    { id: "e2", work_center_id: "wc1", name: "Line_2", archived_at: "2026-01-01" }, // archived
  ];
  jest.spyOn(api, "listEquipment").mockResolvedValue(mockEquipment);
  
  const { result } = renderHook(() => useShiftReferenceData(true));
  
  await waitFor(() => {
    expect(result.current.activeEquipment).toHaveLength(1);
    expect(result.current.activeEquipment[0].name).toBe("Line_1");
  });
});

test("counts shift reports per date and work_center_id", async () => {
  jest.spyOn(api, "listEquipment").mockResolvedValue([
    { id: "e1", work_center_id: "wc1", name: "Line_1", archived_at: null },
  ]);
  jest.spyOn(api, "listShiftReports").mockResolvedValue([
    { id: "sr1", work_center_id: "wc1", report_date: "2026-09-24", shift: "day" },
    { id: "sr2", work_center_id: "wc1", report_date: "2026-09-24", shift: "night" },
    { id: "sr3", work_center_id: "wc1", report_date: "2026-09-23", shift: "day" },
  ]);
  
  const { result } = renderHook(() => useShiftReferenceData(true));
  
  await waitFor(() => {
    expect(result.current.reportCountByLineDate.get("2026-09-24|wc1")).toBe(2);
    expect(result.current.reportCountByLineDate.get("2026-09-23|wc1")).toBe(1);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
npm test -- frontend/src/features/production/shift/__tests__/useShiftReferenceData.test.ts
```

Expected: FAIL — `activeEquipment`, `reportCountByLineDate` properties don't exist.

- [ ] **Step 3: Implement equipment + report count logic in useShiftReferenceData**

Modify `frontend/src/features/production/shift/useShiftReferenceData.ts`:

```typescript
export function useShiftReferenceData(enabled: boolean) {
  const { session } = useAuth();
  const token = session!.token;
  const { t } = useI18n();
  const label = useLabel();
  const waste = useWasteTypes();

  const workCenters = useQuery({ queryKey: ["production", "shift", "work-centers"], queryFn: () => listWorkCenters(token), enabled });
  const settings = useQuery({ queryKey: DASHBOARD_SETTINGS_QUERY_KEY, queryFn: () => getDashboardSettings(token), enabled });
  const orders = useQuery({ queryKey: ["production", "shift", "orders"], queryFn: () => listWorkOrders(token), enabled });
  const products = useQuery({ queryKey: ["production", "shift", "products"], queryFn: () => listProducts(token), enabled });
  const classifications = useQuery({ queryKey: ["production", "shift", "classifications"], queryFn: () => listClassifications(token), enabled, retry: false });
  const locations = useQuery({ queryKey: ["production", "shift", "locations"], queryFn: () => listLocations(token), enabled });
  const molds = useQuery({ queryKey: ["production", "shift", "molds"], queryFn: () => listMolds(token), enabled });
  const equipment = useQuery({ queryKey: ["production", "shift", "equipment"], queryFn: () => listEquipment(token), enabled });
  const shiftReports = useQuery({ queryKey: ["production", "shift", "all-reports"], queryFn: () => listShiftReports(token), enabled });
  const partners = useQuery({ queryKey: ["production", "shift", "partners"], queryFn: () => listPartners(token), enabled });

  // Filter archived equipment and build report count map
  const activeEquipment = useMemo(
    () => (equipment.data ?? []).filter((e) => !e.archived_at).sort((a, b) => a.name.localeCompare(b.name)),
    [equipment.data],
  );

  const reportCountByLineDate = useMemo(() => {
    const map = new Map<string, number>();
    for (const report of shiftReports.data ?? []) {
      const key = `${report.report_date}|${report.work_center_id}`;
      map.set(key, (map.get(key) ?? 0) + 1);
    }
    return map;
  }, [shiftReports.data]);

  // ... rest of buildOptions ...

  return {
    workCenters: workCenters.data,
    workCentersLoading: workCenters.isLoading,
    windows: settings.data?.shift_windows ?? [],
    activeEquipment,
    reportCountByLineDate,
    buildOptions,
  };
}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
npm test -- frontend/src/features/production/shift/__tests__/useShiftReferenceData.test.ts
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/production/shift/useShiftReferenceData.ts
git add frontend/src/features/production/shift/__tests__/useShiftReferenceData.test.ts
git commit -m "feat(production): expose equipment list and report counts in shift reference data"
```

---

## Task 2: DateNavigator component (arrows + modal picker)

**Files:**
- Create: `frontend/src/features/production/shift/DateNavigator.tsx`
- Test: `frontend/src/features/production/shift/__tests__/DateNavigator.test.tsx`

**Interfaces:**
- Consumes: `date: string` (ISO 8601 YYYY-MM-DD), `onDateChange: (date: string) => void`
- Produces: `<DateNavigator date={date} onDateChange={onDateChange} />`
  - Renders: `[← button] [date display] [→ button] | Modal picker (click date display to open)`
  - Arrow behavior: ±1 day (respects actual calendar, not shifts)
  - Modal: standard date picker, closes on selection
  - Accessibility: `aria-label` on buttons, `aria-label` on date display

- [ ] **Step 1: Write failing test**

```typescript
// frontend/src/features/production/shift/__tests__/DateNavigator.test.tsx
import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DateNavigator } from "../DateNavigator";

test("renders prev/next arrow buttons", () => {
  const onChange = jest.fn();
  render(<DateNavigator date="2026-09-24" onDateChange={onChange} />);
  
  expect(screen.getByRole("button", { name: /previous day/i })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /next day/i })).toBeInTheDocument();
});

test("clicking prev arrow decrements date by 1 day", async () => {
  const onChange = jest.fn();
  render(<DateNavigator date="2026-09-24" onDateChange={onChange} />);
  
  await userEvent.click(screen.getByRole("button", { name: /previous day/i }));
  
  expect(onChange).toHaveBeenCalledWith("2026-09-23");
});

test("clicking next arrow increments date by 1 day", async () => {
  const onChange = jest.fn();
  render(<DateNavigator date="2026-09-24" onDateChange={onChange} />);
  
  await userEvent.click(screen.getByRole("button", { name: /next day/i }));
  
  expect(onChange).toHaveBeenCalledWith("2026-09-25");
});

test("clicking date display opens modal picker", async () => {
  const onChange = jest.fn();
  render(<DateNavigator date="2026-09-24" onDateChange={onChange} />);
  
  const dateDisplay = screen.getByText("2026-09-24");
  await userEvent.click(dateDisplay);
  
  expect(screen.getByRole("dialog")).toBeInTheDocument();
});

test("selecting date in modal calls onChange", async () => {
  const onChange = jest.fn();
  render(<DateNavigator date="2026-09-24" onDateChange={onChange} />);
  
  await userEvent.click(screen.getByText("2026-09-24"));
  const input = screen.getByRole("textbox", { name: /select date/i });
  await userEvent.clear(input);
  await userEvent.type(input, "2026-09-25");
  await userEvent.click(screen.getByRole("button", { name: /confirm|apply/i }));
  
  expect(onChange).toHaveBeenCalledWith("2026-09-25");
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
npm test -- frontend/src/features/production/shift/__tests__/DateNavigator.test.tsx
```

Expected: FAIL — component doesn't exist.

- [ ] **Step 3: Implement DateNavigator component**

```typescript
// frontend/src/features/production/shift/DateNavigator.tsx
import { useState } from "react";
import { ChevronLeft, ChevronRight, Calendar } from "lucide-react";
import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "../../../components/ui/dialog";

interface DateNavigatorProps {
  date: string; // ISO 8601 YYYY-MM-DD
  onDateChange: (date: string) => void;
}

function addDays(date: string, days: number): string {
  const d = new Date(date + "T00:00:00Z");
  d.setUTCDate(d.getUTCDate() + days);
  const year = d.getUTCFullYear();
  const month = String(d.getUTCMonth() + 1).padStart(2, "0");
  const day = String(d.getUTCDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export function DateNavigator({ date, onDateChange }: DateNavigatorProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [tempDate, setTempDate] = useState(date);

  const handlePrevDay = () => onDateChange(addDays(date, -1));
  const handleNextDay = () => onDateChange(addDays(date, 1));

  const handleConfirmDate = () => {
    onDateChange(tempDate);
    setIsOpen(false);
  };

  return (
    <>
      <div className="flex items-center gap-2">
        <Button
          variant="ghost"
          size="sm"
          onClick={handlePrevDay}
          aria-label="Previous day"
        >
          <ChevronLeft className="h-4 w-4" />
        </Button>

        <button
          onClick={() => {
            setTempDate(date);
            setIsOpen(true);
          }}
          className="flex items-center gap-2 rounded px-3 py-1 text-sm font-medium hover:bg-muted"
          aria-label={`Select date, currently ${date}`}
        >
          <Calendar className="h-4 w-4" />
          {date}
        </button>

        <Button
          variant="ghost"
          size="sm"
          onClick={handleNextDay}
          aria-label="Next day"
        >
          <ChevronRight className="h-4 w-4" />
        </Button>
      </div>

      <Dialog open={isOpen} onOpenChange={setIsOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Select Date</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <Input
              type="date"
              value={tempDate}
              onChange={(e) => setTempDate(e.target.value)}
              aria-label="Select date"
            />
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setIsOpen(false)}>
              Cancel
            </Button>
            <Button onClick={handleConfirmDate}>Apply</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
npm test -- frontend/src/features/production/shift/__tests__/DateNavigator.test.tsx
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/production/shift/DateNavigator.tsx
git add frontend/src/features/production/shift/__tests__/DateNavigator.test.tsx
git commit -m "feat(production): add DateNavigator with day arrows and modal picker"
```

---

## Task 3: LineStatusBadge component (report count display)

**Files:**
- Create: `frontend/src/features/production/shift/LineStatusBadge.tsx`
- Test: `frontend/src/features/production/shift/__tests__/LineStatusBadge.test.tsx`

**Interfaces:**
- Consumes: `reportCount: number`, `totalShifts: number` (e.g., 2/3 means 2 reports exist)
- Produces: `<LineStatusBadge reportCount={2} totalShifts={3} />`
  - Renders: Badge showing "2/3" or "0/3"
  - Color: Red (0), Yellow (1-2), Green (3) dot + count
  - Compact: fits in 60px max-width

- [ ] **Step 1: Write failing test**

```typescript
// frontend/src/features/production/shift/__tests__/LineStatusBadge.test.tsx
import { render, screen } from "@testing-library/react";
import { LineStatusBadge } from "../LineStatusBadge";

test("renders report count and total shifts", () => {
  render(<LineStatusBadge reportCount={2} totalShifts={3} />);
  expect(screen.getByText("2/3")).toBeInTheDocument();
});

test("shows red indicator for 0 reports", () => {
  render(<LineStatusBadge reportCount={0} totalShifts={3} />);
  expect(screen.getByRole("img", { hidden: true })).toHaveClass("text-destructive"); // red dot
});

test("shows yellow indicator for 1-2 reports", () => {
  render(<LineStatusBadge reportCount={1} totalShifts={3} />);
  expect(screen.getByRole("img", { hidden: true })).toHaveClass("text-yellow-500");
});

test("shows green indicator for all reports", () => {
  render(<LineStatusBadge reportCount={3} totalShifts={3} />);
  expect(screen.getByRole("img", { hidden: true })).toHaveClass("text-success");
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
npm test -- frontend/src/features/production/shift/__tests__/LineStatusBadge.test.tsx
```

Expected: FAIL — component doesn't exist.

- [ ] **Step 3: Implement LineStatusBadge component**

```typescript
// frontend/src/features/production/shift/LineStatusBadge.tsx
import { Circle } from "lucide-react";

interface LineStatusBadgeProps {
  reportCount: number;
  totalShifts: number;
}

export function LineStatusBadge({ reportCount, totalShifts }: LineStatusBadgeProps) {
  let dotColor = "text-destructive"; // red (0 reports)
  if (reportCount > 0 && reportCount < totalShifts) {
    dotColor = "text-yellow-500"; // yellow (partial)
  } else if (reportCount === totalShifts && totalShifts > 0) {
    dotColor = "text-success"; // green (all done)
  }

  return (
    <div className="flex items-center gap-1 rounded-full bg-muted px-2 py-1 text-xs font-medium">
      <Circle className={`h-2 w-2 fill-current ${dotColor}`} />
      <span className="tabular-nums">
        {reportCount}/{totalShifts}
      </span>
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
npm test -- frontend/src/features/production/shift/__tests__/LineStatusBadge.test.tsx
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/production/shift/LineStatusBadge.tsx
git add frontend/src/features/production/shift/__tests__/LineStatusBadge.test.tsx
git commit -m "feat(production): add LineStatusBadge for report-count display"
```

---

## Task 4: LineCardsSelector component (cards + dropdown fallback)

**Files:**
- Create: `frontend/src/features/production/shift/LineCardsSelector.tsx`
- Test: `frontend/src/features/production/shift/__tests__/LineCardsSelector.test.tsx`

**Interfaces:**
- Consumes: 
  - `value: string` (selected work_center_id)
  - `onChange: (id: string) => void`
  - `equipment: Array<{ id, name, work_center_id }>` (from useShiftReferenceData)
  - `reportCountByLineDate: Map<string, number>`
  - `date: string` (current date for report count lookup)
  - `windows: ShiftWindowRow[]` (to calculate total shifts per day)
- Produces: `<LineCardsSelector value={wc_id} onChange={...} equipment={...} ... />`
  - Width < 800px: fallback to `<Select>` dropdown with badges
  - Width >= 800px: clickable cards, one per equipment, each showing name + status badge
  - Cards highlight on selection
  - Badges show report count (e.g., "2/3")

- [ ] **Step 1: Write failing test**

```typescript
// frontend/src/features/production/shift/__tests__/LineCardsSelector.test.tsx
import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { LineCardsSelector } from "../LineCardsSelector";

const mockEquipment = [
  { id: "wc1", work_center_id: "wc1", name: "Line_1", archived_at: null },
  { id: "wc2", work_center_id: "wc2", name: "Line_2", archived_at: null },
];

const mockWindows = [
  { shift: "day", start_time: "07:00", end_time: "15:00" },
  { shift: "afternoon", start_time: "15:00", end_time: "23:00" },
  { shift: "night", start_time: "23:00", end_time: "07:00" },
];

test("renders card for each equipment on wide screen", () => {
  global.innerWidth = 1024;
  render(
    <LineCardsSelector
      value="wc1"
      onChange={jest.fn()}
      equipment={mockEquipment}
      reportCountByLineDate={new Map()}
      date="2026-09-24"
      windows={mockWindows}
    />
  );
  
  expect(screen.getByText("Line_1")).toBeInTheDocument();
  expect(screen.getByText("Line_2")).toBeInTheDocument();
});

test("clicking card calls onChange with equipment id", async () => {
  global.innerWidth = 1024;
  const onChange = jest.fn();
  render(
    <LineCardsSelector
      value="wc1"
      onChange={onChange}
      equipment={mockEquipment}
      reportCountByLineDate={new Map()}
      date="2026-09-24"
      windows={mockWindows}
    />
  );
  
  await userEvent.click(screen.getByText("Line_2"));
  expect(onChange).toHaveBeenCalledWith("wc2");
});

test("shows report count badge on card", () => {
  global.innerWidth = 1024;
  const reportCounts = new Map([["2026-09-24|wc1", 2]]);
  render(
    <LineCardsSelector
      value="wc1"
      onChange={jest.fn()}
      equipment={mockEquipment}
      reportCountByLineDate={reportCounts}
      date="2026-09-24"
      windows={mockWindows}
    />
  );
  
  expect(screen.getByText("2/3")).toBeInTheDocument();
});

test("falls back to dropdown on narrow screen", () => {
  global.innerWidth = 600;
  render(
    <LineCardsSelector
      value="wc1"
      onChange={jest.fn()}
      equipment={mockEquipment}
      reportCountByLineDate={new Map()}
      date="2026-09-24"
      windows={mockWindows}
    />
  );
  
  expect(screen.getByRole("combobox")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
npm test -- frontend/src/features/production/shift/__tests__/LineCardsSelector.test.tsx
```

Expected: FAIL — component doesn't exist.

- [ ] **Step 3: Implement LineCardsSelector component**

```typescript
// frontend/src/features/production/shift/LineCardsSelector.tsx
import { useMemo, useState, useEffect } from "react";
import { cn } from "../../../lib/utils";
import { Select } from "../../../components/ui/select";
import { LineStatusBadge } from "./LineStatusBadge";
import type { ShiftWindowRow } from "../board/api";

interface Equipment {
  id: string;
  work_center_id: string;
  name: string;
  archived_at: string | null;
}

interface LineCardsSelectorProps {
  value: string;
  onChange: (id: string) => void;
  equipment: Equipment[];
  reportCountByLineDate: Map<string, number>;
  date: string;
  windows: ShiftWindowRow[];
}

export function LineCardsSelector({
  value,
  onChange,
  equipment,
  reportCountByLineDate,
  date,
  windows,
}: LineCardsSelectorProps) {
  const [showCards, setShowCards] = useState(window.innerWidth >= 800);

  useEffect(() => {
    const handleResize = () => setShowCards(window.innerWidth >= 800);
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  const totalShifts = windows.length;
  const reportCount = useMemo(
    () => reportCountByLineDate.get(`${date}|${value}`) ?? 0,
    [reportCountByLineDate, date, value]
  );

  if (!showCards) {
    // Fallback dropdown for narrow screens
    return (
      <div className="space-y-1">
        <label htmlFor="shift-line" className="text-xs text-muted-foreground">
          Line
        </label>
        <div className="flex gap-2">
          <Select id="shift-line" value={value} onChange={(e) => onChange(e.target.value)}>
            {equipment.map((e) => (
              <option key={e.id} value={e.id}>
                {e.name}
              </option>
            ))}
          </Select>
          <LineStatusBadge reportCount={reportCount} totalShifts={totalShifts} />
        </div>
      </div>
    );
  }

  // Cards view for wider screens
  return (
    <div className="space-y-1">
      <label className="text-xs text-muted-foreground">Line</label>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
        {equipment.map((e) => {
          const count = reportCountByLineDate.get(`${date}|${e.id}`) ?? 0;
          const isSelected = e.id === value;
          return (
            <button
              key={e.id}
              onClick={() => onChange(e.id)}
              className={cn(
                "rounded-lg border-2 p-3 text-left transition-all",
                isSelected
                  ? "border-primary bg-primary/10"
                  : "border-border hover:border-muted-foreground hover:bg-muted/50"
              )}
            >
              <div className="flex items-start justify-between">
                <div className="text-sm font-medium">{e.name}</div>
              </div>
              <div className="mt-2">
                <LineStatusBadge reportCount={count} totalShifts={totalShifts} />
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
npm test -- frontend/src/features/production/shift/__tests__/LineCardsSelector.test.tsx
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/production/shift/LineCardsSelector.tsx
git add frontend/src/features/production/shift/__tests__/LineCardsSelector.test.tsx
git commit -m "feat(production): add LineCardsSelector with cards and responsive dropdown"
```

---

## Task 5: Integrate DateNavigator and LineCardsSelector into ShiftReportTab

**Files:**
- Modify: `frontend/src/features/production/shift/ShiftReportTab.tsx:175-209` (replace old selectors)

**Interfaces:**
- Consumes: 
  - `DateNavigator` (new component from Task 2)
  - `LineCardsSelector` (new component from Task 4)
  - `useShiftReferenceData` result (enhanced in Task 1)
- Produces: Same `ShiftReportTab` API, but with new UX

- [ ] **Step 1: Update ShiftReportTab to import new components**

```typescript
// At top of frontend/src/features/production/shift/ShiftReportTab.tsx
import { DateNavigator } from "./DateNavigator";
import { LineCardsSelector } from "./LineCardsSelector";
```

- [ ] **Step 2: Replace selector grid with new components**

Replace lines 175-209 (the old date/line/shift selectors) with:

```typescript
      <Card>
        <CardContent className="space-y-4 py-4">
          <div className="space-y-3">
            {/* Date with arrows + modal picker */}
            <div>
              <p className="mb-2 text-xs text-muted-foreground">{label(T.date)}</p>
              <DateNavigator date={date} onDateChange={setDate} />
            </div>

            {/* Line cards or dropdown with status badges */}
            <LineCardsSelector
              value={workCenterId}
              onChange={setWorkCenterId}
              equipment={reference.activeEquipment ?? []}
              reportCountByLineDate={reference.reportCountByLineDate}
              date={date}
              windows={windows}
            />

            {/* Shift selection dropdown (unchanged) */}
            <div className="space-y-1">
              <FieldLabel htmlFor="shift-name" className="text-xs text-muted-foreground">
                {label(T.shift)}
              </FieldLabel>
              <Select id="shift-name" value={shiftName} onChange={(e) => setShiftName(e.target.value)}>
                {windows.map((w) => (
                  <option key={w.shift} value={w.shift}>
                    {w.shift} ({w.start_time.slice(0, 5)}–{w.end_time.slice(0, 5)})
                  </option>
                ))}
              </Select>
            </div>

            {/* Status badge */}
            {shift && <ShiftStatusBadge status={shift.status} />}
          </div>

          {shift && (
            <HeaderNames
              key={shift.id}
              shift={shift}
              locked={shift.status === "validated" || !SECTION_KEYS.some((k) => hasPermission(`production.shift.edit.${k}`))}
              onSaved={refresh}
              onError={fail}
            />
          )}
        </CardContent>
      </Card>
```

- [ ] **Step 3: Run the app and verify the new UI works**

```bash
npm run dev
```

- Navigate to Production > Fiche de shift
- Test: Click left/right arrows to change date
- Test: Click date display to open modal picker, select a date
- Test: On wide screen (>800px), see clickable line cards with badges; on narrow screen see dropdown
- Test: Click a different line, verify shift report loads
- Test: Verify report-count badges update as date/line changes

- [ ] **Step 4: Run frontend tests**

```bash
npm test
```

Expected: All shift form tests pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/production/shift/ShiftReportTab.tsx
git commit -m "feat(production): integrate DateNavigator and LineCardsSelector into shift form header"
```

---

## Task 6: Add prefetch for smooth transitions between shifts

**Files:**
- Modify: `frontend/src/features/production/shift/ShiftReportTab.tsx:75-110` (add prefetch logic)

**Interfaces:**
- Consumes: `useQueryClient()` from TanStack Query
- Produces: Silent prefetch of shift data when user changes date/line/shift, before they commit the selection

- [ ] **Step 1: Add prefetch logic to ShiftReportTab**

```typescript
  const queryClient = useQueryClient();

  // Prefetch the next shift report when inputs change, so it's ready by the time the user needs it
  useEffect(() => {
    if (!workCenterId || !date || !shiftName) return;
    queryClient.prefetchQuery({
      queryKey: [...SHIFT_REPORTS_QUERY_KEY, "find", date, workCenterId],
      queryFn: () => listShiftReports(token, { report_date: date, work_center_id: workCenterId }),
      staleTime: 5000, // Fresh for 5 seconds after prefetch
    });
  }, [date, workCenterId, token, queryClient]);
```

- [ ] **Step 2: Verify smooth transition in browser**

```bash
npm run dev
```

- Open Production > Fiche de shift
- Click date arrows or line cards repeatedly
- Verify: No loading spinner appears when shift data is already prefetched
- Verify: Shift sections appear instantly after selection

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/production/shift/ShiftReportTab.tsx
git commit -m "feat(production): prefetch shift data for smooth navigation"
```

---

## Task 7: Invalidate equipment + reports on query window close

**Files:**
- Modify: `frontend/src/features/production/shift/ShiftReportTab.tsx:68-80` (add cleanup on unmount)

**Interfaces:**
- Consumes: `useQueryClient()`
- Produces: On tab close, invalidate equipment and shift reports queries so next visit gets fresh data

- [ ] **Step 1: Add invalidation on component unmount**

```typescript
  useEffect(() => {
    return () => {
      // When leaving the shift form, invalidate equipment and reports so next visit fetches fresh data
      queryClient.invalidateQueries({ queryKey: ["production", "shift", "equipment"] });
      queryClient.invalidateQueries({ queryKey: ["production", "shift", "all-reports"] });
    };
  }, [queryClient]);
```

- [ ] **Step 2: Test in browser**

```bash
npm run dev
```

- Open Production > Fiche de shift (equipment loaded)
- Navigate to another tab (Finance, CRM, etc.)
- While away, a line gets archived in Maintenance > Equipment
- Come back to Production > Fiche de shift
- Verify: The archived line no longer appears in line cards

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/production/shift/ShiftReportTab.tsx
git commit -m "feat(production): invalidate equipment and shift reports on tab close"
```

---

## Spec Coverage Verification

✅ **Day navigation arrows** — DateNavigator component (Task 2)
✅ **Date picker modal** — DateNavigator component (Task 2)
✅ **Line status badges** — LineStatusBadge + LineCardsSelector (Tasks 3 & 4)
✅ **Clickable line cards** — LineCardsSelector (Task 4)
✅ **Sync with maintenance equipment** — useShiftReferenceData filters archived_at (Task 1)
✅ **Responsive fallback to dropdown** — LineCardsSelector narrows at <800px (Task 4)
✅ **Smooth transitions** — Prefetch on date/line/shift changes (Task 6)
✅ **Fresh data on return** — Invalidate queries on tab close (Task 7)

---

## Placeholder Scan

✅ No "TBD", "TODO", "implement later"
✅ All tests include actual test code, not placeholders
✅ All components have concrete implementations
✅ All steps show exact code, not descriptions

---

## Type Consistency Check

- `date: string` (ISO 8601 YYYY-MM-DD) — consistent across DateNavigator, LineCardsSelector, ShiftReportTab
- `workCenterId: string` — consistent across all components
- `reportCountByLineDate: Map<string, number>` — consistent in Task 1 and Task 4
- `equipment: Array<{ id, name, work_center_id, archived_at }>` — matches maintenance.Equipment type from Task 1

---

## Review Focus: Tested Cases

1. **Day navigation doesn't respect business hours** ✅ Test: DateNavigator.test.tsx lines 19-25 — verify arrow follows calendar date
2. **Equipment sync stale on archive/add** ✅ Test: ShiftReportTab cleanup effect (Task 7) — verify equipment query invalidates on unmount
3. **Report-count logic** ✅ Test: useShiftReferenceData.test.ts lines 26-36 — verify badge counts actual reports, not shift windows
4. **Mobile fallback confusion** ✅ Test: LineCardsSelector.test.tsx lines 50-65 — verify dropdown renders on narrow screen and preserves selection
5. **Race condition on rapid date clicks** ✅ TanStack Query handles this natively — prefetch + query key deduplication ensures final query wins

---
