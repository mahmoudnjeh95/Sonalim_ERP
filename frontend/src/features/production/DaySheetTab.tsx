import { Fragment, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useAuth } from "../../lib/auth";
import { ApiError } from "../../lib/api";
import { currentLocale, useI18n, type TranslationKey } from "../../lib/i18n";
import { formatQuantity } from "../../lib/units";
import { cn } from "../../lib/utils";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card, CardContent } from "../../components/ui/card";
import { Checkbox } from "../../components/ui/checkbox";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select } from "../../components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../../components/ui/table";
import { FilterTabs } from "../../components/patterns/FilterTabs";
import {
  getDaySheet,
  getMonthRecap,
  listWorkCenters,
  type DaySheetColumn,
  type DaySheetRow,
  type DaySheetSection,
} from "./api";
import { addDays } from "./board/boardFormat";
import { useWasteTypes } from "./wasteTypes";
import { AppLoader } from "../../components/patterns/AppLoader";

const WORK_CENTERS_QUERY_KEY = ["production", "work-centers"] as const;
export const DAY_SHEET_QUERY_KEY = ["production", "day-sheet"] as const;
export const MONTH_RECAP_QUERY_KEY = ["production", "month-recap"] as const;

// The order the plant's Excel prints its sections in.
const SECTIONS: DaySheetSection[] = ["material", "production", "waste", "packing", "energy"];

// The fraction digits each unit is printed with, so a column of tonnes reads as one
// (10.80, 22.90, 1.395) instead of jagging between 0, 1, 2 and 3 decimals. Units not
// listed here (packets, cartons, metres...) are printed as they come.
const FRACTION_DIGITS: Record<string, { min: number; max: number }> = {
  T: { min: 2, max: 3 },
  h: { min: 2, max: 2 },
  kg: { min: 0, max: 2 },
  l: { min: 0, max: 0 },
  kWh: { min: 0, max: 0 },
  "kg/h": { min: 0, max: 0 },
  "%": { min: 1, max: 1 },
};

type Mode = "day" | "month";

const today = () => new Date().toLocaleDateString("sv-SE");

/** A "YYYY-MM" month moved by whole months, wrapping over the year. */
function addMonths(month: string, delta: number): string {
  const [year, index] = month.split("-").map(Number);
  const moved = new Date(year, index - 1 + delta, 1);
  return `${moved.getFullYear()}-${String(moved.getMonth() + 1).padStart(2, "0")}`;
}

/** The small arrow beside the date / month field that steps it one day / month back or forward. */
function StepButton({
  direction,
  label,
  disabled,
  onClick,
}: {
  direction: "prev" | "next";
  label: string;
  disabled: boolean;
  onClick: () => void;
}) {
  const Icon = direction === "prev" ? ChevronLeft : ChevronRight;
  return (
    <Button type="button" variant="outline" className="w-9 shrink-0 px-0" aria-label={label} title={label} disabled={disabled} onClick={onClick}>
      <Icon className="h-4 w-4" aria-hidden="true" />
    </Button>
  );
}

/**
 * The rows the sheet prints for one section, in print order.
 *
 * The déchet kinds are printed whether or not anyone lost anything to them, as the
 * Excel prints all of its rows: a kind that is missing from the sheet would read as
 * "not part of this plant's process" instead of "nothing recorded".
 */
function sectionRows(section: DaySheetSection, rows: DaySheetRow[], wasteCategories: string[]): DaySheetRow[] {
  const own = rows.filter((row) => row.section === section);
  if (section !== "waste") return own;
  const byKind = new Map(own.filter((row) => row.key === "waste").map((row) => [row.ref, row]));
  const kinds: DaySheetRow[] = wasteCategories.map(
    (category) =>
      byKind.get(category) ?? {
        section,
        key: "waste",
        ref: category,
        name: null,
        unit: "kg",
        by_column: {},
        total: null,
      },
  );
  return [...kinds, ...own.filter((row) => row.key !== "waste")];
}

/** The rows that add up the ones above them, so they read as totals and not as one more line. */
const isTotal = (row: DaySheetRow) => row.key.startsWith("total_") || row.key === "yield";

function ColumnHeader({ column, mode }: { column: DaySheetColumn; mode: Mode }) {
  const { t } = useI18n();
  const pending = column.reports.daily.pending + column.reports.conditionnement.pending;
  const title =
    mode === "month"
      ? column.name || t("production.daySheet.noProduct")
      : column.key || t("production.daySheet.noShift");
  return (
    <TableHead scope="col" className="min-w-[8.5rem] px-3 text-right normal-case">
      <div className="text-sm font-semibold capitalize text-foreground">{title}</div>
      {mode === "day" && (
        <div className="text-xs font-normal text-muted-foreground">{column.teams.join(", ") || "—"}</div>
      )}
      <div className="mt-1 flex flex-wrap justify-end gap-1">
        <Badge variant="default" className="px-1.5 py-0 text-[0.65rem]">
          {t("production.daySheet.dailyShort")} {column.reports.daily.validated}
        </Badge>
        <Badge variant="default" className="px-1.5 py-0 text-[0.65rem]">
          {t("production.daySheet.packingShort")} {column.reports.conditionnement.validated}
        </Badge>
        {pending > 0 && (
          <Badge variant="warning" className="px-1.5 py-0 text-[0.65rem]">
            {pending} {t("production.daySheet.notValidated")}
          </Badge>
        )}
      </div>
    </TableHead>
  );
}

/** The grid both views print: sections of rows, a column per shift (or product) and a total. */
function SheetGrid({
  mode,
  lineName,
  columns,
  rows,
}: {
  mode: Mode;
  lineName: string;
  columns: DaySheetColumn[];
  rows: DaySheetRow[];
}) {
  const { t } = useI18n();
  const { label: wasteLabel, categoriesFor } = useWasteTypes();
  const wasteCategories = useMemo(
    () =>
      categoriesFor(
        "daily",
        rows.filter((row) => row.key === "waste" && row.ref).map((row) => row.ref!),
      ),
    [categoriesFor, rows],
  );

  function rowLabel(row: DaySheetRow): string {
    if (row.key === "semolina" || row.key === "finished") return row.name ?? "—";
    if (row.key === "waste") return wasteLabel(row.ref ?? "");
    if (row.key === "packing_waste") return `${wasteLabel(row.ref ?? "")} · ${row.name ?? "—"}`;
    return t(`production.daySheet.row.${row.key}` as TranslationKey);
  }

  function cell(value: number | null | undefined, unit: string | null) {
    if (value === null || value === undefined) return <span className="text-muted-foreground/60">—</span>;
    const digits = unit ? FRACTION_DIGITS[unit] : undefined;
    return digits
      ? new Intl.NumberFormat(currentLocale(), {
          minimumFractionDigits: digits.min,
          maximumFractionDigits: digits.max,
        }).format(value)
      : formatQuantity(value);
  }

  return (
    <Table>
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          <TableHead scope="col" className="min-w-[14rem] normal-case">
            {lineName}
          </TableHead>
          <TableHead scope="col" className="w-16 px-2" />
          {columns.map((column) => (
            <ColumnHeader key={column.key} column={column} mode={mode} />
          ))}
          <TableHead
            scope="col"
            className="min-w-[8.5rem] bg-muted/40 px-3 text-right text-sm font-semibold normal-case text-foreground"
          >
            {t("production.daySheet.total")}
          </TableHead>
        </TableRow>
        <TableRow className="hover:bg-transparent">
          <TableHead scope="row" className="py-1.5 text-xs font-normal normal-case">
            {t("production.daySheet.lot")}
          </TableHead>
          <TableHead className="px-2" />
          {columns.map((column) => (
            <TableHead key={column.key} className="px-3 py-1.5 text-right text-xs font-normal normal-case">
              {column.lots.join(", ") || "—"}
            </TableHead>
          ))}
          <TableHead className="bg-muted/40" />
        </TableRow>
      </TableHeader>
      <TableBody>
        {SECTIONS.map((section) => (
          <Fragment key={section}>
            <TableRow className="bg-muted/30 hover:bg-muted/30">
              <TableCell
                colSpan={columns.length + 3}
                className="py-1.5 text-xs font-semibold uppercase tracking-wide text-primary"
              >
                {t(`production.daySheet.section.${section}` as TranslationKey)}
              </TableCell>
            </TableRow>
            {sectionRows(section, rows, wasteCategories).map((row) => (
              <TableRow key={`${row.key}:${row.ref ?? ""}:${row.name ?? ""}`}>
                <TableCell className={cn("py-2", isTotal(row) && "font-semibold")}>{rowLabel(row)}</TableCell>
                <TableCell className="px-2 py-2 text-xs text-muted-foreground">{row.unit}</TableCell>
                {columns.map((column) => (
                  <TableCell
                    key={column.key}
                    className={cn("px-3 py-2 text-right tabular-nums", isTotal(row) && "font-semibold")}
                  >
                    {cell(row.by_column[column.key], row.unit)}
                  </TableCell>
                ))}
                <TableCell className="bg-muted/40 px-3 py-2 text-right font-semibold tabular-nums">
                  {cell(row.total, row.unit)}
                </TableCell>
              </TableRow>
            ))}
          </Fragment>
        ))}
      </TableBody>
    </Table>
  );
}

/**
 * The plant's Excel workbook in one view: a line's day sheet (a column per shift, the
 * Daily and Conditionnement reports side by side) and its month recap (a column per
 * product, every validated day added up). Nothing is typed here -- both are read from
 * the reports, which is what keeps the sheet from disagreeing with them.
 */
export function DaySheetTab() {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const [mode, setMode] = useState<Mode>("day");
  const [date, setDate] = useState(today);
  const [month, setMonth] = useState(() => today().slice(0, 7));
  const [lineId, setLineId] = useState("");
  const [includePending, setIncludePending] = useState(false);

  const { data: workCenters = [] } = useQuery({ queryKey: WORK_CENTERS_QUERY_KEY, queryFn: () => listWorkCenters(token) });
  const selectedLine = lineId || workCenters[0]?.id || "";

  const daySheet = useQuery({
    queryKey: [...DAY_SHEET_QUERY_KEY, date, selectedLine, includePending],
    queryFn: () => getDaySheet(token, { date, workCenterId: selectedLine, includePending }),
    enabled: mode === "day" && Boolean(date && selectedLine),
  });
  const monthRecap = useQuery({
    queryKey: [...MONTH_RECAP_QUERY_KEY, month, selectedLine],
    queryFn: () => getMonthRecap(token, { month, workCenterId: selectedLine }),
    enabled: mode === "month" && Boolean(month && selectedLine),
  });

  const active = mode === "day" ? daySheet : monthRecap;
  const data = active.data;
  const filedReports = (data?.columns ?? []).reduce(
    (sum, c) =>
      sum + c.reports.daily.validated + c.reports.daily.pending + c.reports.conditionnement.validated + c.reports.conditionnement.pending,
    0,
  );
  const waiting = (data?.columns ?? []).reduce((sum, c) => sum + c.reports.daily.pending + c.reports.conditionnement.pending, 0);
  const orders = mode === "day" && daySheet.data ? daySheet.data.ofs : [];

  return (
    <Card>
      <CardContent className="space-y-4 pt-6">
        <FilterTabs<Mode>
          value={mode}
          onChange={setMode}
          options={[
            { value: "day", label: t("production.daySheet.mode.day") },
            { value: "month", label: t("production.daySheet.mode.month") },
          ]}
        />

        <div className="flex flex-wrap items-end gap-4">
          {mode === "day" ? (
            <div className="space-y-1.5">
              <Label htmlFor="day-sheet-date">{t("production.daySheet.date")}</Label>
              <div className="flex items-center gap-1.5">
                <StepButton
                  direction="prev"
                  label={t("production.board.prevDay")}
                  disabled={!date}
                  onClick={() => setDate(addDays(date, -1))}
                />
                <Input id="day-sheet-date" type="date" value={date} onChange={(event) => setDate(event.target.value)} />
                <StepButton
                  direction="next"
                  label={t("production.board.nextDay")}
                  disabled={!date || date >= today()}
                  onClick={() => setDate(addDays(date, 1))}
                />
              </div>
            </div>
          ) : (
            <div className="space-y-1.5">
              <Label htmlFor="day-sheet-month">{t("production.daySheet.month")}</Label>
              <div className="flex items-center gap-1.5">
                <StepButton
                  direction="prev"
                  label={t("production.daySheet.prevMonth")}
                  disabled={!month}
                  onClick={() => setMonth(addMonths(month, -1))}
                />
                <Input id="day-sheet-month" type="month" value={month} onChange={(event) => setMonth(event.target.value)} />
                <StepButton
                  direction="next"
                  label={t("production.daySheet.nextMonth")}
                  disabled={!month || month >= today().slice(0, 7)}
                  onClick={() => setMonth(addMonths(month, 1))}
                />
              </div>
            </div>
          )}
          <div className="min-w-[12rem] space-y-1.5">
            <Label htmlFor="day-sheet-line">{t("production.daySheet.line")}</Label>
            <Select id="day-sheet-line" value={selectedLine} onChange={(event) => setLineId(event.target.value)}>
              {workCenters.map((line) => (
                <option key={line.id} value={line.id}>
                  {line.name}
                </option>
              ))}
            </Select>
          </div>
          {mode === "day" && (
            <div className="flex items-center gap-2 pb-2">
              <Checkbox
                id="day-sheet-pending"
                checked={includePending}
                onCheckedChange={(checked) => setIncludePending(checked === true)}
              />
              <Label htmlFor="day-sheet-pending" className="font-normal">
                {t("production.daySheet.includePending")}
              </Label>
            </div>
          )}
        </div>

        {active.isError ? (
          <p role="alert" className="text-sm text-destructive">
            {active.error instanceof ApiError ? active.error.message : t("production.daySheet.loadError")}
          </p>
        ) : !data ? (
          <AppLoader className="py-8" />
        ) : (
          <>
            {orders.length > 0 && (
              <p className="text-xs text-muted-foreground">
                {t("production.daySheet.orders")}{" "}
                {orders.map((of) => [of.reference, of.product_name].filter(Boolean).join(" · ")).join(" — ")}
              </p>
            )}
            {filedReports === 0 && (
              <p className="text-sm text-muted-foreground">
                {mode === "day" ? t("production.daySheet.noReports") : t("production.daySheet.noReportsMonth")}
              </p>
            )}
            {waiting > 0 && (
              <p className="text-sm text-warning">
                {mode === "day" && includePending
                  ? t("production.daySheet.pendingIncluded")
                  : t("production.daySheet.pendingLeftOut")}
              </p>
            )}
            <SheetGrid mode={mode} lineName={data.work_center.name} columns={data.columns} rows={data.rows} />
            <p className="text-xs text-muted-foreground">
              {mode === "day" ? t("production.daySheet.legend") : t("production.daySheet.monthLegend")}
            </p>
          </>
        )}
      </CardContent>
    </Card>
  );
}
