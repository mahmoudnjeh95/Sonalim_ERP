import { Fragment, useMemo, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Download, Loader2 } from "lucide-react";
import { toast } from "sonner";
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
import { TableBody, TableCell, TableHead, TableHeader, TableRow } from "../../components/ui/table";
import { FilterTabs } from "../../components/patterns/FilterTabs";
import {
  exportMonthRecapWorkbook,
  getDaySheet,
  getMonthRecap,
  type DaySheetColumn,
  type DaySheetGrouping,
  type DaySheetRow,
  type DaySheetSection,
  type MonthRecapGrouping,
} from "./api";
import { addDays } from "./board/boardFormat";
import { useWasteTypes } from "./wasteTypes";
import { AppLoader } from "../../components/patterns/AppLoader";
import { useShiftReferenceData } from "./shift/useShiftReferenceData";
import { LineCardsSelector } from "./shift/LineCardsSelector";

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

// Past this many lots a column's lot list is folded to "n lots · first → last".
const LOTS_SHOWN_FOLDED = 3;

type Mode = "day" | "month";
/** What a column stands for: the shift or the lot on a day sheet, the product or the lot on the recap. */
type Grouping = DaySheetGrouping | MonthRecapGrouping;

const today = () => new Date().toLocaleDateString("sv-SE");

/** A "YYYY-MM" month moved by whole months, wrapping over the year. */
function addMonths(month: string, delta: number): string {
  const [year, index] = month.split("-").map(Number);
  const moved = new Date(year, index - 1 + delta, 1);
  return `${moved.getFullYear()}-${String(moved.getMonth() + 1).padStart(2, "0")}`;
}

function shortDate(iso: string): string {
  return new Intl.DateTimeFormat(currentLocale(), { day: "2-digit", month: "2-digit" }).format(new Date(`${iso}T00:00:00`));
}

/** "03/09 → 12/09", or the one day when the column was filed on a single day. */
function period(column: DaySheetColumn): string {
  if (!column.date_from) return "—";
  if (!column.date_to || column.date_to === column.date_from) return shortDate(column.date_from);
  return `${shortDate(column.date_from)} → ${shortDate(column.date_to)}`;
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

const emptyRow = (section: DaySheetSection, key: string, ref: string | null): DaySheetRow => ({
  section,
  key,
  ref,
  name: null,
  unit: "kg",
  by_column: {},
  total: null,
});

/**
 * The rows the sheet prints for one section, in print order.
 *
 * The déchet kinds are printed whether or not anyone lost anything to them, as the
 * Excel prints all of its rows: a kind that is missing from the sheet would read as
 * "not part of this plant's process" instead of "nothing recorded". The same goes for
 * what is lost while packing -- the product (with the déchets, in their total) and
 * the packaging (under Conditionnement, in a total of its own: film is not pasta).
 */
function sectionRows(section: DaySheetSection, rows: DaySheetRow[], wasteCategories: string[]): DaySheetRow[] {
  const own = rows.filter((row) => row.section === section);
  if (section === "packing") {
    if (own.some((row) => row.key === "packing_waste")) return own;
    const total = own.findIndex((row) => row.key === "total_packing_waste");
    return total < 0 ? own : [...own.slice(0, total), emptyRow(section, "packing_waste", null), ...own.slice(total)];
  }
  if (section !== "waste") return own;
  const byKind = new Map(own.filter((row) => row.key === "waste").map((row) => [row.ref, row]));
  const kinds: DaySheetRow[] = wasteCategories.map((category) => byKind.get(category) ?? emptyRow(section, "waste", category));
  const packed = own.filter((row) => row.key === "packed_product_waste");
  return [
    ...kinds,
    ...(packed.length > 0 ? packed : [emptyRow(section, "packed_product_waste", null)]),
    ...own.filter((row) => row.key !== "waste" && row.key !== "packed_product_waste"),
  ];
}

/** The rows that add up the ones above them, so they read as totals and not as one more line. */
const isTotal = (row: DaySheetRow) => row.key.startsWith("total_") || row.key === "yield";

const STICKY_FIRST = "sticky left-0 z-10 bg-background";
const STICKY_TOP = "sticky top-0 z-20 bg-background";

function ColumnHeader({ column, mode, grouping }: { column: DaySheetColumn; mode: Mode; grouping: Grouping }) {
  const { t } = useI18n();
  const pending = column.reports.daily.pending + column.reports.conditionnement.pending;
  const counted = column.reports.daily.validated + column.reports.conditionnement.validated;
  const title =
    grouping === "lot"
      ? column.name || t("production.daySheet.noLot")
      : grouping === "product"
        ? column.name || t("production.daySheet.noProduct")
        : column.key || t("production.daySheet.noShift");
  // What a column is read against: its teams on a day, its days on a month.
  const subtitle = mode === "day" ? column.teams.join(", ") : period(column);
  return (
    <TableHead scope="col" className={cn("min-w-[8.5rem] px-3 text-right align-bottom normal-case", STICKY_TOP)}>
      <div className={cn("text-sm font-semibold text-foreground", grouping === "shift" && "capitalize")} title={title}>
        {title}
      </div>
      <div className="text-xs font-normal text-muted-foreground">{subtitle || "—"}</div>
      <div className="mt-1 flex flex-wrap justify-end gap-1">
        {mode === "month" && counted > 0 && (
          <Badge variant="outline" className="px-1.5 py-0 text-[0.65rem] font-normal">
            {counted} {t("production.daySheet.reportsCounted")}
          </Badge>
        )}
        {pending > 0 && (
          <Badge variant="warning" className="px-1.5 py-0 text-[0.65rem]">
            {pending} {t("production.daySheet.notValidated")}
          </Badge>
        )}
      </div>
    </TableHead>
  );
}

/**
 * A column's lots. Three or fewer are listed; more are folded to "n lots · first → last"
 * with a way to unfold them, so a product packed under 69 lots does not push the whole
 * grid off the screen.
 */
function LotList({ lots, expanded, onToggle }: { lots: string[]; expanded: boolean; onToggle: () => void }) {
  const { t } = useI18n();
  if (lots.length === 0) return <span className="text-muted-foreground/60">—</span>;
  if (lots.length <= LOTS_SHOWN_FOLDED) return <span>{lots.join(", ")}</span>;
  return (
    <div className="space-y-1">
      {expanded ? (
        <p className="max-w-[16rem] whitespace-normal break-words text-left font-mono text-[0.7rem] leading-snug">{lots.join(", ")}</p>
      ) : (
        <p title={lots.join(", ")}>
          <span className="font-semibold text-foreground">{lots.length}</span> {t("production.daySheet.lots")} ·{" "}
          <span className="font-mono">{lots[0]}</span> → <span className="font-mono">{lots[lots.length - 1]}</span>
        </p>
      )}
      <button type="button" className="text-[0.7rem] text-primary underline-offset-2 hover:underline" onClick={onToggle}>
        {expanded ? t("production.daySheet.hideLots") : t("production.daySheet.showAllLots")}
      </button>
    </div>
  );
}

/** The grid every view prints: sections of rows, a column per shift / product / lot and a total. */
function SheetGrid({
  mode,
  grouping,
  lineName,
  columns,
  rows,
}: {
  mode: Mode;
  grouping: Grouping;
  lineName: string;
  columns: DaySheetColumn[];
  rows: DaySheetRow[];
}) {
  const { t } = useI18n();
  const { label: wasteLabel, categoriesFor } = useWasteTypes();
  const [expandedLots, setExpandedLots] = useState<Set<string>>(() => new Set());
  // Finished product lost while packing now comes from the packing side (its own rows);
  // the old Daily kind for it is only printed on a sheet where someone still used it.
  const wasteCategories = useMemo(() => {
    const reported = rows.filter((row) => row.key === "waste" && row.ref).map((row) => row.ref!);
    return categoriesFor("daily", reported).filter(
      (category) => category !== "finished_product_conditioning" || reported.includes(category),
    );
  }, [categoriesFor, rows]);
  const allLots = useMemo(() => new Set(columns.flatMap((column) => column.lots)), [columns]);

  function rowLabel(row: DaySheetRow): string {
    if (row.key === "semolina" || row.key === "finished") return row.name ?? "—";
    if (row.key === "waste") return wasteLabel(row.ref ?? "");
    if (row.key === "packed_product_waste") {
      const kind = wasteLabel("finished_product_conditioning");
      return row.name ? `${kind} · ${row.name}` : kind;
    }
    if (row.key === "packing_waste") {
      // Built-in packaging reads "Déchet emballage"; a plant's own kind keeps its name.
      const kind = !row.ref || row.ref === "packaging" ? t("production.daySheet.row.packing_waste") : wasteLabel(row.ref);
      return row.name ? `${kind} · ${row.name}` : kind;
    }
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

  function toggleLots(key: string) {
    setExpandedLots((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  // Under the header: the lots a column packed (unless the columns are the lots), and
  // the product a lot is made of (when they are).
  const detailRows: { label: string; render: (column: DaySheetColumn) => ReactNode; total: ReactNode }[] = [];
  if (grouping === "lot") {
    detailRows.push({
      label: t("production.daySheet.products"),
      render: (column) => column.products.join(", ") || "—",
      total: null,
    });
  } else {
    detailRows.push({
      label: t("production.daySheet.lot"),
      render: (column) => (
        <LotList lots={column.lots} expanded={expandedLots.has(column.key)} onToggle={() => toggleLots(column.key)} />
      ),
      total: allLots.size > 0 ? `${allLots.size} ${t("production.daySheet.lots")}` : null,
    });
  }

  return (
    <div className="max-h-[75vh] overflow-auto rounded-lg border border-border">
      <table className="w-full text-sm">
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead scope="col" className={cn("min-w-[14rem] align-bottom normal-case", STICKY_FIRST, STICKY_TOP, "z-30")}>
              {lineName}
            </TableHead>
            <TableHead scope="col" className={cn("w-16 px-2", STICKY_TOP)} />
            {columns.map((column) => (
              <ColumnHeader key={column.key} column={column} mode={mode} grouping={grouping} />
            ))}
            <TableHead
              scope="col"
              className={cn("min-w-[8.5rem] px-3 text-right align-bottom text-sm font-semibold normal-case text-foreground", STICKY_TOP, "bg-muted")}
            >
              {t("production.daySheet.total")}
            </TableHead>
          </TableRow>
          {detailRows.map((detail) => (
            <TableRow key={detail.label} className="hover:bg-transparent">
              <TableHead scope="row" className={cn("py-1.5 text-xs font-normal normal-case", STICKY_FIRST)}>
                {detail.label}
              </TableHead>
              <TableHead className="px-2" />
              {columns.map((column) => (
                <TableHead key={column.key} className="px-3 py-1.5 text-right align-top text-xs font-normal normal-case">
                  {detail.render(column)}
                </TableHead>
              ))}
              <TableHead className="bg-muted/40 px-3 py-1.5 text-right text-xs font-normal normal-case">{detail.total ?? ""}</TableHead>
            </TableRow>
          ))}
        </TableHeader>
        <TableBody>
          {SECTIONS.map((section) => (
            <Fragment key={section}>
              <TableRow className="bg-muted/30 hover:bg-muted/30">
                <TableCell className={cn("py-1.5 text-xs font-semibold uppercase tracking-wide text-primary", STICKY_FIRST, "bg-muted/30")}>
                  {t(`production.daySheet.section.${section}` as TranslationKey)}
                </TableCell>
                <TableCell colSpan={columns.length + 2} className="py-1.5" />
              </TableRow>
              {sectionRows(section, rows, wasteCategories).map((row) => (
                <TableRow key={`${row.key}:${row.ref ?? ""}:${row.name ?? ""}`} className={cn(isTotal(row) && "bg-muted/20")}>
                  <TableCell className={cn("py-2", STICKY_FIRST, isTotal(row) && "font-semibold bg-muted/20")}>{rowLabel(row)}</TableCell>
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
      </table>
    </div>
  );
}

/**
 * The plant's Excel workbook in one view: a line's day sheet (a column per shift, the
 * Daily and Conditionnement reports side by side) and its month recap (a column per
 * product, every validated day added up) -- either one also readable with a column
 * per lot. Nothing is typed here -- both are read from the reports, which is what
 * keeps the sheet from disagreeing with them. The month's workbook (every line,
 * every day) is downloaded from the same reports.
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
  const [dayGrouping, setDayGrouping] = useState<DaySheetGrouping>("shift");
  const [monthGrouping, setMonthGrouping] = useState<MonthRecapGrouping>("product");
  const [isExporting, setIsExporting] = useState(false);

  const reference = useShiftReferenceData(true);
  const workCenters = reference.workCenters;
  const selectedLine = lineId || workCenters[0]?.id || "";

  const daySheet = useQuery({
    queryKey: [...DAY_SHEET_QUERY_KEY, date, selectedLine, includePending, dayGrouping],
    queryFn: () => getDaySheet(token, { date, workCenterId: selectedLine, includePending, groupBy: dayGrouping }),
    enabled: mode === "day" && Boolean(date && selectedLine),
  });
  const monthRecap = useQuery({
    queryKey: [...MONTH_RECAP_QUERY_KEY, month, selectedLine, monthGrouping],
    queryFn: () => getMonthRecap(token, { month, workCenterId: selectedLine, groupBy: monthGrouping }),
    enabled: mode === "month" && Boolean(month && selectedLine),
  });

  const active = mode === "day" ? daySheet : monthRecap;
  const data = active.data;
  const grouping: Grouping = mode === "day" ? dayGrouping : monthGrouping;
  const filedReports = (data?.columns ?? []).reduce(
    (sum, c) =>
      sum + c.reports.daily.validated + c.reports.daily.pending + c.reports.conditionnement.validated + c.reports.conditionnement.pending,
    0,
  );
  const waiting = (data?.columns ?? []).reduce((sum, c) => sum + c.reports.daily.pending + c.reports.conditionnement.pending, 0);
  const orders = mode === "day" && daySheet.data ? daySheet.data.ofs : [];
  const exportMonth = mode === "day" ? date.slice(0, 7) : month;

  async function handleExport() {
    setIsExporting(true);
    try {
      const blob = await exportMonthRecapWorkbook(token, { month: exportMonth });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `recap-production-${exportMonth}.xlsx`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : t("production.daySheet.exportError"));
    } finally {
      setIsExporting(false);
    }
  }

  const legend =
    grouping === "lot"
      ? t("production.daySheet.lotLegend")
      : mode === "day"
        ? t("production.daySheet.legend")
        : t("production.daySheet.monthLegend");

  return (
    <Card>
      <CardContent className="space-y-4 pt-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <FilterTabs<Mode>
            value={mode}
            onChange={setMode}
            options={[
              { value: "day", label: t("production.daySheet.mode.day") },
              { value: "month", label: t("production.daySheet.mode.month") },
            ]}
          />
          <Button
            type="button"
            variant="outline"
            disabled={isExporting || !exportMonth}
            onClick={handleExport}
            title={t("production.daySheet.exportHint")}
          >
            {isExporting ? <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" /> : <Download className="mr-2 h-4 w-4" aria-hidden="true" />}
            {isExporting ? t("production.daySheet.exporting") : `${t("production.daySheet.export")} · ${exportMonth}`}
          </Button>
        </div>

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
          <div className="space-y-1.5">
            <Label>{t("production.daySheet.groupBy")}</Label>
            <div>
              {mode === "day" ? (
                <FilterTabs<DaySheetGrouping>
                  value={dayGrouping}
                  onChange={setDayGrouping}
                  options={[
                    { value: "shift", label: t("production.daySheet.groupBy.shift") },
                    { value: "lot", label: t("production.daySheet.groupBy.lot") },
                  ]}
                />
              ) : (
                <FilterTabs<MonthRecapGrouping>
                  value={monthGrouping}
                  onChange={setMonthGrouping}
                  options={[
                    { value: "product", label: t("production.daySheet.groupBy.product") },
                    { value: "lot", label: t("production.daySheet.groupBy.lot") },
                  ]}
                />
              )}
            </div>
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

        <LineCardsSelector
          value={selectedLine}
          onChange={setLineId}
          lines={workCenters}
          reportCountByLineDate={reference.reportCountByLineDate}
          date={date}
          windows={reference.windows}
        />

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
            <SheetGrid mode={mode} grouping={grouping} lineName={data.work_center.name} columns={data.columns} rows={data.rows} />
            <p className="text-xs text-muted-foreground">{legend}</p>
          </>
        )}
      </CardContent>
    </Card>
  );
}
