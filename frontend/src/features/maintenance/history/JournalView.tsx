import { useMemo, useState } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { ClipboardList, FileSpreadsheet } from "lucide-react";
import { toast } from "sonner";
import HistoryEmptyIllustration from "../../../assets/illustrations/maintenance/history-empty.svg?react";
import { ColumnFilterRow } from "../../../components/patterns/ColumnFilterRow";
import { EmptyState } from "../../../components/patterns/EmptyState";
import { FilterTabs } from "../../../components/patterns/FilterTabs";
import { MobileCardList } from "../../../components/patterns/MobileCardList";
import { Badge } from "../../../components/ui/badge";
import { Button } from "../../../components/ui/button";
import { Card, CardContent } from "../../../components/ui/card";
import { Skeleton } from "../../../components/ui/skeleton";
import { ResizableTableHead, Table, TableBody, TableCell, TableHeader, TableRow } from "../../../components/ui/table";
import { ApiError } from "../../../lib/api";
import { useAuth } from "../../../lib/auth";
import { CURRENCY_CODE, formatXofWithCode } from "../../../lib/currency";
import { useI18n } from "../../../lib/i18n";
import { formatDuration } from "../../../lib/units";
import { useColumnFilters, type FilterField } from "../../../lib/useColumnFilters";
import { useIsMobile } from "../../../lib/useIsMobile";
import { useTableColumns, type ColumnDef } from "../../../lib/useTableColumns";
import { formatDay } from "../jobs/jobFormat";
import { JOB_KIND_LABEL_KEY, OUTCOME_LABEL_KEY } from "../labels";
import { exportJournalWorkbook, useHistoryJournal, type JournalFilters, type JournalKind, type JournalRow, type JournalStatus } from "./api";
import { fill, initials } from "./historyFormat";
import type { Period } from "./historyPeriod";

type KindFilter = "all" | JournalKind;
const STATUSES: JournalStatus[] = ["closed", "cancelled", "all"];
const KINDS: KindFilter[] = ["all", "preventive", "corrective"];

function ResultBar({ row }: { row: JournalRow }) {
  const { t } = useI18n();
  const { ok, issue, not_done: notDone } = row.outcomes;
  const total = Math.max(ok + issue + notDone, 1);
  return (
    <span className="flex items-center gap-2">
      <span className="flex h-2 w-14 shrink-0 overflow-hidden rounded-full bg-muted">
        <span className="bg-success" style={{ width: `${(ok / total) * 100}%` }} />
        <span className="bg-destructive" style={{ width: `${(issue / total) * 100}%` }} />
        <span className="bg-muted-foreground/40" style={{ width: `${(notDone / total) * 100}%` }} />
      </span>
      <span className="truncate text-xs text-muted-foreground">
        {ok} OK
        {issue > 0 && <span className="text-destructive"> · {fill(t("maintenance.history.points.issues"), { n: issue })}</span>}
        {notDone > 0 && ` · ${notDone} ${t(OUTCOME_LABEL_KEY.not_done).toLowerCase()}`}
      </span>
    </span>
  );
}

export function JournalView({ period, equipmentId }: { period: Period; equipmentId: string }) {
  const { session } = useAuth();
  const token = session!.token;
  const { t, language } = useI18n();
  const navigate = useNavigate();
  const location = useLocation();
  const isMobile = useIsMobile();
  const [searchParams, setSearchParams] = useSearchParams();
  const [exporting, setExporting] = useState(false);

  const statusParam = searchParams.get("jstatus") as JournalStatus | null;
  const status: JournalStatus = statusParam && STATUSES.includes(statusParam) ? statusParam : "closed";
  const kindParam = searchParams.get("kind") as KindFilter | null;
  const kind: KindFilter = kindParam && KINDS.includes(kindParam) ? kindParam : "all";

  const filters = useMemo<JournalFilters>(
    () => ({ ...period, equipment_id: equipmentId || undefined, kind: kind === "all" ? undefined : kind, status }),
    [period, equipmentId, kind, status],
  );
  const journal = useHistoryJournal(token, filters);
  const costsVisible = journal.data?.costs_visible ?? false;

  function update(key: string, value: string | null) {
    setSearchParams(
      (current) => {
        const next = new URLSearchParams(current);
        if (value === null) next.delete(key);
        else next.set(key, value);
        return next;
      },
      { replace: true },
    );
  }

  async function exportExcel() {
    setExporting(true);
    try {
      const blob = await exportJournalWorkbook(token, { ...filters, lang: language });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `maintenance-journal-${period.from}_${period.to}.xlsx`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (error) {
      toast.error(t("maintenance.history.journal.exportError"), { description: error instanceof ApiError ? error.message : undefined });
    } finally {
      setExporting(false);
    }
  }

  const fields: FilterField<JournalRow>[] = [
    { key: "number", kind: "text", getValue: (r) => r.number },
    { key: "machine", kind: "text", getValue: (r) => `${r.equipment_code} ${r.equipment_name}` },
    { key: "title", kind: "text", getValue: (r) => r.title },
    { key: "performers", kind: "text", getValue: (r) => r.performers.map((p) => p.name).join(" ") },
    { key: "time", kind: "range", getValue: (r) => Math.round(r.technician_seconds / 60) },
    { key: "cost", kind: "range", getValue: (r) => r.parts_cost },
  ];
  const columnFilters = useColumnFilters(fields);
  const text = (key: string, placeholder: string) => ({
    type: "text" as const,
    value: columnFilters.text[key] ?? "",
    onChange: (v: string) => columnFilters.setTextValue(key, v),
    placeholder,
  });
  const range = (key: string) => ({
    type: "range" as const,
    min: columnFilters.range[key]?.min ?? "",
    max: columnFilters.range[key]?.max ?? "",
    onMinChange: (v: string) => columnFilters.setRangeValue(key, "min", v),
    onMaxChange: (v: string) => columnFilters.setRangeValue(key, "max", v),
  });

  const columns: ColumnDef<JournalRow>[] = [
    {
      key: "number",
      header: t("maintenance.history.journal.column.number"),
      defaultWidth: 130,
      minWidth: 124,
      alwaysVisible: true,
      mobileRole: "subtitle",
      sortValue: (r) => r.number,
      filterCell: text("number", t("maintenance.history.journal.column.number")),
      cell: (r) => <span className="whitespace-nowrap font-mono text-xs font-medium text-primary">{r.number}</span>,
    },
    {
      key: "date",
      header: t("maintenance.history.journal.column.date"),
      defaultWidth: 112,
      minWidth: 104,
      sortValue: (r) => r.date ?? "",
      cell: (r) => <span className="whitespace-nowrap">{formatDay(r.date)}</span>,
    },
    {
      key: "machine",
      header: t("maintenance.history.column.machine"),
      defaultWidth: 150,
      sortValue: (r) => r.equipment_name,
      filterCell: text("machine", t("maintenance.history.column.machine")),
      cell: (r) => (
        <span className="block truncate" title={`${r.equipment_code} — ${r.equipment_name}`}>
          {r.equipment_name}
        </span>
      ),
    },
    {
      key: "kind",
      header: t("maintenance.history.journal.column.kind"),
      defaultWidth: 110,
      minWidth: 100,
      sortValue: (r) => r.kind,
      cell: (r) => <Badge variant={r.kind === "corrective" ? "destructive" : "primary"}>{t(JOB_KIND_LABEL_KEY[r.kind])}</Badge>,
    },
    {
      key: "title",
      header: t("maintenance.history.journal.column.title"),
      defaultWidth: 190,
      mobileRole: "title",
      sortValue: (r) => r.title,
      filterCell: text("title", t("maintenance.history.journal.column.title")),
      cell: (r) => (
        <span className="block truncate" title={r.cancel_reason ?? r.title}>
          {r.title}
        </span>
      ),
    },
    {
      key: "performers",
      header: t("maintenance.history.journal.column.performers"),
      defaultWidth: 112,
      filterCell: text("performers", t("maintenance.history.journal.column.performers")),
      cell: (r) => (
        <span className="flex items-center" title={r.performers.map((p) => p.name).join(", ")}>
          {r.performers.length === 0 && <span className="text-muted-foreground">—</span>}
          {r.performers.slice(0, 3).map((p) => (
            <span
              key={p.employee_id}
              className="-ml-1.5 grid h-6 w-6 shrink-0 place-items-center rounded-full border-2 border-card bg-primary text-[9px] font-bold text-primary-foreground first:ml-0"
            >
              {initials(p.name)}
            </span>
          ))}
          {r.performers.length > 3 && (
            <span className="-ml-1.5 grid h-6 min-w-6 shrink-0 place-items-center rounded-full border-2 border-card bg-muted px-1 text-[9px] font-bold text-muted-foreground">
              +{r.performers.length - 3}
            </span>
          )}
        </span>
      ),
    },
    {
      key: "time",
      header: t("maintenance.history.journal.column.time"),
      defaultWidth: 100,
      minWidth: 92,
      sortValue: (r) => r.technician_seconds,
      filterCell: range("time"),
      cell: (r) => (
        <span className="whitespace-nowrap tabular-nums">{r.technician_seconds > 0 ? formatDuration(r.technician_seconds / 60) : "—"}</span>
      ),
    },
    {
      key: "result",
      header: t("maintenance.history.journal.column.result"),
      defaultWidth: 170,
      cell: (r) => <ResultBar row={r} />,
    },
    {
      key: "parts",
      header: t("maintenance.history.journal.column.parts"),
      defaultWidth: 80,
      // The cost column says the same when costs are visible; one column fewer on a laptop.
      hiddenByDefault: true,
      sortValue: (r) => r.parts.issued_lines + r.parts.purchase_lines,
      cell: (r) => <span className="tabular-nums">{r.parts.issued_lines + r.parts.purchase_lines || "—"}</span>,
    },
    ...(costsVisible
      ? [
          {
            key: "cost",
            header: `${t("maintenance.history.journal.column.cost")} (${CURRENCY_CODE})`,
            defaultWidth: 112,
            minWidth: 100,
            sortValue: (r: JournalRow) => r.parts_cost ?? 0,
            filterCell: range("cost"),
            cell: (r: JournalRow) => (
              <span className="whitespace-nowrap tabular-nums">{r.parts_cost ? formatXofWithCode(r.parts_cost) : "—"}</span>
            ),
          },
        ]
      : []),
  ];
  const table = useTableColumns("maintenance.history.journal", columns);
  const rows = table.sortRows(columnFilters.apply(journal.data?.rows ?? []));
  const span = table.visibleColumns.length;
  const loading = journal.isLoading;

  function openJob(row: JournalRow) {
    navigate(`/maintenance/jobs/${row.job_id}`, { state: { from: `${location.pathname}${location.search}` } });
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <FilterTabs<JournalStatus>
            options={STATUSES.map((value) => ({ value, label: t(`maintenance.history.journal.status.${value}` as const) }))}
            value={status}
            onChange={(value) => update("jstatus", value === "closed" ? null : value)}
          />
          <FilterTabs<KindFilter>
            options={KINDS.map((value) => ({ value, label: t(`maintenance.history.journal.kind.${value}` as const) }))}
            value={kind}
            onChange={(value) => update("kind", value === "all" ? null : value)}
          />
          {columnFilters.isActive && (
            <Button variant="ghost" size="sm" onClick={columnFilters.reset}>
              {t("common.clearFilters")}
            </Button>
          )}
        </div>
        <Button onClick={exportExcel} disabled={exporting || rows.length === 0} className="w-full sm:w-auto">
          <FileSpreadsheet className="h-4 w-4" />
          {t("maintenance.history.journal.export")}
        </Button>
      </div>

      {isMobile ? (
        <MobileCardList
          columns={table.visibleColumns}
          rows={rows}
          rowKey={(r) => r.job_id}
          loading={loading}
          emptyIcon={<ClipboardList className="h-5 w-5" />}
          emptyTitle={t("maintenance.history.journal.empty.title")}
          emptyDescription={t("maintenance.history.journal.empty.description")}
          onRowClick={openJob}
        />
      ) : (
        <Card>
          <CardContent className="p-0">
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
                {loading &&
                  [0, 1, 2].map((index) => (
                    <TableRow key={`skeleton-${index}`}>
                      <TableCell colSpan={span}>
                        <Skeleton className="h-5 w-full" />
                      </TableCell>
                    </TableRow>
                  ))}
                {!loading && rows.length === 0 && (
                  <TableRow className="hover:bg-transparent">
                    <TableCell colSpan={span} className="p-0">
                      <EmptyState
                        icon={<ClipboardList className="h-5 w-5" />}
                        illustration={<HistoryEmptyIllustration aria-hidden className="h-44 w-52" />}
                        title={t("maintenance.history.journal.empty.title")}
                        description={t("maintenance.history.journal.empty.description")}
                      />
                    </TableCell>
                  </TableRow>
                )}
                {!loading &&
                  rows.map((row) => (
                    <TableRow key={row.job_id} onClick={() => openJob(row)} className="cursor-pointer">
                      {table.visibleColumns.map((column) => (
                        <TableCell key={column.key} className={column.cellClassName}>
                          {column.cell(row)}
                        </TableCell>
                      ))}
                    </TableRow>
                  ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
