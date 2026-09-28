import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileSearch, X } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../../lib/auth";
import { useI18n, type TranslationKey } from "../../../lib/i18n";
import { Button } from "../../../components/ui/button";
import { Badge } from "../../../components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "../../../components/ui/card";
import { Skeleton } from "../../../components/ui/skeleton";
import { FilterTabs } from "../../../components/patterns/FilterTabs";
import { useColumnFilters, type FilterField } from "../../../lib/useColumnFilters";
import type { ColumnDef } from "../../../lib/useTableColumns";
import { HrListTable } from "../HrListTable";
import {
  HR_KEYS, commitClockImport, discardClockImport, getClockImport,
  type ClockAnomaly, type ClockCommitResult, type ClockConflict, type ClockImportRow,
} from "../presenceApi";
import { errorText, formatDay, formatDuration } from "../presenceFormat";
import { PresenceStatusBadge } from "./PresenceStatusBadge";

export const ROW_ERROR_LABEL: Record<string, TranslationKey> = {
  MISSING_BADGE: "hr.clock.error.MISSING_BADGE",
  BAD_TIMESTAMP: "hr.clock.error.BAD_TIMESTAMP",
  MISSING_COLUMN: "hr.clock.error.MISSING_COLUMN",
  DUPLICATE_PUNCH: "hr.clock.error.DUPLICATE_PUNCH",
  UNKNOWN_BADGE: "hr.clock.error.UNKNOWN_BADGE",
  OUTSIDE_RANGE: "hr.clock.error.OUTSIDE_RANGE",
};
const ANOMALY_LABEL: Record<string, TranslationKey> = { MISSING_OUT: "hr.clock.anomaly.MISSING_OUT", MISSING_IN: "hr.clock.anomaly.MISSING_IN" };
const DIRECTION_LABEL: Record<ClockImportRow["direction"], TranslationKey> = { in: "hr.clock.direction.in", out: "hr.clock.direction.out", unknown: "hr.clock.direction.unknown" };
const label = (map: Record<string, TranslationKey>, code: string, t: (key: TranslationKey) => string) => (map[code] ? t(map[code]) : code);

function ImportResult({ result }: { result: ClockCommitResult }) {
  const { t } = useI18n();
  const conflictColumns: ColumnDef<ClockConflict>[] = [
    { key: "employee", header: t("hr.common.employee"), defaultWidth: 220, sortValue: (c) => c.employee_no, cell: (c) => `${c.employee_no} · ${c.full_name}` },
    { key: "date", header: t("hr.presence.date"), defaultWidth: 140, sortValue: (c) => c.work_date, cell: (c) => formatDay(c.work_date) },
    { key: "kept", header: t("hr.clock.result.kept"), defaultWidth: 140, cell: (c) => <PresenceStatusBadge status={c.kept_status} /> },
    {
      key: "clock", header: t("hr.clock.result.clock"), defaultWidth: 180,
      cell: (c) => <span className="inline-flex items-center gap-2"><PresenceStatusBadge status={c.clock_status} />{formatDuration(c.clock_worked_minutes)}</span>,
    },
  ];
  const anomalyColumns: ColumnDef<ClockAnomaly>[] = [
    { key: "employee", header: t("hr.common.employee"), defaultWidth: 220, sortValue: (a) => a.employee_no, cell: (a) => `${a.employee_no} · ${a.full_name}` },
    { key: "date", header: t("hr.presence.date"), defaultWidth: 140, sortValue: (a) => a.work_date, cell: (a) => formatDay(a.work_date) },
    { key: "codes", header: t("hr.clock.result.codes"), defaultWidth: 240, cell: (a) => a.codes.map((code) => label(ANOMALY_LABEL, code, t)).join(", ") },
  ];
  const stat = (value: number, key: TranslationKey) => (
    <div className="rounded-md border border-border p-2">
      <p className="text-lg font-semibold tabular-nums">{value}</p>
      <p className="text-xs text-muted-foreground">{t(key)}</p>
    </div>
  );
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {stat(result.days_written, "hr.clock.result.daysWritten")}
        {stat(result.duplicate_punches, "hr.clock.result.duplicates")}
        {stat(result.outside_range_punches, "hr.clock.result.outside")}
        {stat(result.unscheduled.length, "hr.clock.result.unscheduled")}
      </div>
      <div className="space-y-2">
        <h3 className="text-sm font-semibold">{t("hr.clock.result.conflicts")}</h3>
        <p className="text-xs text-muted-foreground">{t("hr.clock.result.conflictsHelp")}</p>
        <HrListTable tableKey="hr.clock.conflicts" columns={conflictColumns} rows={result.conflicts} rowKey={(c) => `${c.employee_id}|${c.work_date}`} loading={false}
          emptyIcon={<FileSearch className="h-5 w-5" />} emptyTitle={t("hr.clock.result.none")} emptyDescription="" />
      </div>
      <div className="space-y-2">
        <h3 className="text-sm font-semibold">{t("hr.clock.result.anomalies")}</h3>
        <HrListTable tableKey="hr.clock.anomalies" columns={anomalyColumns} rows={result.anomalies} rowKey={(a) => `${a.employee_id}|${a.work_date}`} loading={false}
          emptyIcon={<FileSearch className="h-5 w-5" />} emptyTitle={t("hr.clock.result.none")} emptyDescription="" />
      </div>
    </div>
  );
}

type RowFilter = "all" | "errors" | "valid";

export function ClockImportReview({ importId, onClose }: { importId: string; onClose: () => void }) {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const detail = useQuery({ queryKey: [...HR_KEYS.clockImports, importId], queryFn: () => getClockImport(token, importId) });
  const [rowFilter, setRowFilter] = useState<RowFilter>("all");
  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: HR_KEYS.clockImports });
    queryClient.invalidateQueries({ queryKey: HR_KEYS.presence });
  };
  const commit = useMutation({
    mutationFn: () => commitClockImport(token, importId),
    onSuccess: () => {
      refresh();
      toast.success(t("hr.clock.review.committed"));
    },
    onError: (error) => toast.error(errorText(error, t("hr.common.saveError"))),
  });
  const discard = useMutation({
    mutationFn: () => discardClockImport(token, importId),
    onSuccess: () => {
      refresh();
      toast.success(t("hr.clock.review.discarded"));
    },
    onError: (error) => toast.error(errorText(error, t("hr.common.saveError"))),
  });

  const fields: FilterField<ClockImportRow>[] = [
    { key: "line", kind: "range", getValue: (r) => r.line_no },
    { key: "badge", kind: "text", getValue: (r) => r.badge_no },
    { key: "employee", kind: "text", getValue: (r) => (r.employee_no ? `${r.employee_no} ${r.full_name}` : "") },
    { key: "error", kind: "text", getValue: (r) => (r.error_code ? label(ROW_ERROR_LABEL, r.error_code, t) : "") },
  ];
  const filters = useColumnFilters(fields);
  const rows = filters.apply((detail.data?.rows ?? []).filter((r) => rowFilter === "all" || (rowFilter === "errors") === (r.error_code !== null)));
  const columns: ColumnDef<ClockImportRow>[] = [
    {
      key: "line", header: t("hr.clock.review.line"), defaultWidth: 90, cellClassName: "tabular-nums", sortValue: (r) => r.line_no, cell: (r) => r.line_no,
      filterCell: { type: "range", min: filters.range.line?.min ?? "", max: filters.range.line?.max ?? "", onMinChange: (v) => filters.setRangeValue("line", "min", v), onMaxChange: (v) => filters.setRangeValue("line", "max", v) },
    },
    {
      key: "badge", header: t("hr.clock.review.badge"), defaultWidth: 110, sortValue: (r) => r.badge_no, cell: (r) => r.badge_no ?? "—",
      filterCell: { type: "text", placeholder: t("hr.clock.review.badge"), value: filters.text.badge ?? "", onChange: (v) => filters.setTextValue("badge", v) },
    },
    {
      key: "employee", header: t("hr.common.employee"), defaultWidth: 220, cell: (r) => (r.employee_no ? `${r.employee_no} · ${r.full_name}` : "—"),
      filterCell: { type: "text", placeholder: t("hr.common.employee"), value: filters.text.employee ?? "", onChange: (v) => filters.setTextValue("employee", v) },
    },
    { key: "punchedAt", header: t("hr.clock.review.punchedAt"), defaultWidth: 170, sortValue: (r) => r.punched_at, cell: (r) => (r.punched_at ? r.punched_at.replace("T", " ").slice(0, 16) : "—") },
    { key: "direction", header: t("hr.clock.review.direction"), defaultWidth: 100, cell: (r) => t(DIRECTION_LABEL[r.direction]) },
    {
      key: "error", header: t("hr.clock.review.error"), defaultWidth: 240,
      cell: (r) => (r.error_code ? <Badge variant="destructive">{label(ROW_ERROR_LABEL, r.error_code, t)}</Badge> : null),
      filterCell: { type: "text", placeholder: t("hr.clock.review.error"), value: filters.text.error ?? "", onChange: (v) => filters.setTextValue("error", v) },
    },
    { key: "raw", header: t("hr.clock.review.raw"), defaultWidth: 260, cell: (r) => <code className="text-xs">{r.raw}</code> },
  ];

  if (detail.isLoading || !detail.data) return <Skeleton className="h-64 w-full" />;
  const current = detail.data;
  const result = commit.data ?? current.result;
  const canAct = current.status === "staged" && hasPermission("hr.import_clock");
  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-3">
        <div className="space-y-1">
          <CardTitle>{t("hr.clock.review.title")} — {current.file_name}</CardTitle>
          <p className="text-sm text-muted-foreground">
            {current.profile_code} · {formatDay(current.date_from)} → {formatDay(current.date_to)} · {current.total_rows} {t("hr.clock.imports.rows")} · {current.error_rows} {t("hr.clock.imports.errors")}
          </p>
          <p className="text-xs text-muted-foreground">{t("hr.clock.review.help")}</p>
        </div>
        <div className="flex gap-2">
          {canAct && (
            <>
              <Button size="sm" onClick={() => commit.mutate()} disabled={commit.isPending || current.valid_rows === 0}>
                {commit.isPending ? t("hr.clock.review.committing") : t("hr.clock.review.commit")}
              </Button>
              <Button size="sm" variant="outline" onClick={() => discard.mutate()} disabled={discard.isPending}>{t("hr.clock.review.discard")}</Button>
            </>
          )}
          <Button size="sm" variant="ghost" aria-label={t("hr.clock.review.close")} onClick={onClose}><X className="h-4 w-4" /></Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-6">
        {result && (
          <div className="space-y-2">
            <h3 className="text-sm font-semibold">{t("hr.clock.result.title")}</h3>
            <ImportResult result={result} />
          </div>
        )}
        <HrListTable
          tableKey="hr.clock.importRows"
          columns={columns}
          rows={rows}
          rowKey={(r) => String(r.line_no)}
          loading={false}
          emptyIcon={<FileSearch className="h-5 w-5" />}
          emptyTitle={t("hr.clock.review.empty.title")}
          emptyDescription={t("hr.clock.review.empty.description")}
          filtersActive={filters.isActive}
          onClearFilters={filters.reset}
          toolbar={
            <FilterTabs
              value={rowFilter}
              onChange={setRowFilter}
              options={[
                { value: "all", label: t("hr.clock.review.filter.all") },
                { value: "errors", label: t("hr.clock.review.filter.errors") },
                { value: "valid", label: t("hr.clock.review.filter.valid") },
              ]}
            />
          }
        />
      </CardContent>
    </Card>
  );
}
