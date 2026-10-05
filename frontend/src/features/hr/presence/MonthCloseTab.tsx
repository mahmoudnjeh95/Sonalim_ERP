import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarCheck, CheckCircle2, Lock, ListChecks, Unlock } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { Badge } from "../../../components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "../../../components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../../components/ui/dialog";
import { FilterTabs } from "../../../components/patterns/FilterTabs";
import { useColumnFilters, type FilterField } from "../../../lib/useColumnFilters";
import type { ColumnDef } from "../../../lib/useTableColumns";
import type { Employee } from "../api";
import { HrListTable } from "../HrListTable";
import {
  HR_KEYS, closePresenceMonth, getMonthGaps, getMonthSummary, listPresenceMonths, reopenPresenceMonth,
  type MonthSummary, type PresenceGap, type PresenceMonth,
} from "../presenceApi";
import { errorText, formatDay, formatDuration, formatMonth, monthStartOf, todayIso } from "../presenceFormat";
import { SUMMARY_TILES } from "./EmployeeMonthTab";

type StatusFilter = "all" | "open" | "closed";
type GapFilter = "all" | "missing" | "no_schedule";
type SummaryRowView = MonthSummary & { employee_no: string; full_name: string };

export function MonthCloseTab({ employees }: { employees: Employee[] }) {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [year, setYear] = useState(Number(todayIso().slice(0, 4)));
  const [selected, setSelected] = useState(monthStartOf(todayIso()));
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [gapFilter, setGapFilter] = useState<GapFilter>("all");
  const [closing, setClosing] = useState(false);
  const [reopening, setReopening] = useState(false);
  const [reason, setReason] = useState("");
  const months = useQuery({ queryKey: [...HR_KEYS.presence, "months", year], queryFn: () => listPresenceMonths(token, year) });
  const current = months.data?.find((m) => m.period === selected);
  const gaps = useQuery({
    queryKey: [...HR_KEYS.presence, "gaps", selected],
    queryFn: () => getMonthGaps(token, selected),
    enabled: current?.status === "open",
  });
  const summary = useQuery({ queryKey: [...HR_KEYS.presence, "summary", selected, ""], queryFn: () => getMonthSummary(token, selected) });
  const refresh = () => queryClient.invalidateQueries({ queryKey: HR_KEYS.presence });

  const close = useMutation({
    mutationFn: () => closePresenceMonth(token, selected),
    onSuccess: () => {
      refresh();
      setClosing(false);
      toast.success(t("hr.presence.months.closedToast"));
    },
    onError: (error) => toast.error(errorText(error, t("hr.common.saveError"))),
  });
  const reopen = useMutation({
    mutationFn: () => reopenPresenceMonth(token, selected, reason.trim()),
    onSuccess: () => {
      refresh();
      setReopening(false);
      setReason("");
      toast.success(t("hr.presence.months.reopened"));
    },
    onError: (error) => toast.error(errorText(error, t("hr.common.saveError"))),
  });

  const monthColumns: ColumnDef<PresenceMonth>[] = [
    { key: "period", header: t("hr.presence.months.period"), defaultWidth: 180, sortValue: (m) => m.period, cell: (m) => <span className="font-medium capitalize">{formatMonth(m.period)}</span> },
    {
      key: "status", header: t("hr.presence.status"), defaultWidth: 130,
      cell: (m) => <Badge variant={m.status === "closed" ? "success" : "warning"}>{t(m.status === "closed" ? "hr.presence.months.status.closed" : "hr.presence.months.status.open")}</Badge>,
    },
    { key: "closedAt", header: t("hr.presence.months.closedAt"), defaultWidth: 150, cell: (m) => (m.closed_at ? formatDay(m.closed_at.slice(0, 10)) : "—") },
    { key: "payroll", header: t("hr.presence.months.payroll"), defaultWidth: 140, cell: (m) => (m.payroll_locked ? <Lock className="h-4 w-4" /> : "—") },
    {
      key: "actions", header: "", defaultWidth: 320, alwaysVisible: true,
      cell: (m) => (
        <div className="flex justify-end gap-2">
          <Button size="sm" variant={m.period === selected ? "default" : "outline"} onClick={() => setSelected(m.period)}>
            <ListChecks className="h-3.5 w-3.5" />
            {t("hr.presence.months.view")}
          </Button>
          {m.status === "open" && hasPermission("hr.close_presence") && (
            <Button size="sm" variant="outline" onClick={() => { setSelected(m.period); setClosing(true); }}>
              <CheckCircle2 className="h-3.5 w-3.5" />
              {t("hr.presence.months.close")}
            </Button>
          )}
          {m.status === "closed" && hasPermission("hr.admin_presence") && (
            <Button size="sm" variant="ghost" disabled={m.payroll_locked} onClick={() => { setSelected(m.period); setReopening(true); }}>
              <Unlock className="h-3.5 w-3.5" />
              {t("hr.presence.months.reopen")}
            </Button>
          )}
        </div>
      ),
    },
  ];
  const monthRows = (months.data ?? []).filter((m) => statusFilter === "all" || m.status === statusFilter);

  const gapFields: FilterField<PresenceGap>[] = [
    { key: "employee", kind: "text", getValue: (g) => `${g.employee_no} ${g.full_name}` },
    { key: "date", kind: "text", getValue: (g) => g.work_date },
  ];
  const gapFilters = useColumnFilters(gapFields);
  const gapRows = gapFilters.apply((gaps.data ?? []).filter((g) => gapFilter === "all" || g.reason === gapFilter));
  const gapColumns: ColumnDef<PresenceGap>[] = [
    {
      key: "employee", header: t("hr.common.employee"), defaultWidth: 240, sortValue: (g) => g.employee_no, cell: (g) => `${g.employee_no} · ${g.full_name}`,
      filterCell: { type: "text", placeholder: t("hr.common.employee"), value: gapFilters.text.employee ?? "", onChange: (v) => gapFilters.setTextValue("employee", v) },
    },
    {
      key: "date", header: t("hr.presence.date"), defaultWidth: 160, sortValue: (g) => g.work_date, cell: (g) => formatDay(g.work_date),
      filterCell: { type: "text", placeholder: "2026-08-…", value: gapFilters.text.date ?? "", onChange: (v) => gapFilters.setTextValue("date", v) },
    },
    { key: "reason", header: t("hr.presence.months.gapColumn"), defaultWidth: 160, cell: (g) => t(g.reason === "missing" ? "hr.presence.months.gapReason.missing" : "hr.presence.months.gapReason.no_schedule") },
  ];

  const byId = new Map(employees.map((e) => [e.id, e]));
  const summaryRows: SummaryRowView[] = (summary.data ?? []).map((row) => ({
    ...row,
    employee_no: byId.get(row.employee_id)?.employee_no ?? "?",
    full_name: byId.get(row.employee_id) ? `${byId.get(row.employee_id)!.first_name} ${byId.get(row.employee_id)!.last_name}` : row.employee_id,
  }));
  const summaryFields: FilterField<SummaryRowView>[] = [
    { key: "employee", kind: "text", getValue: (r) => `${r.employee_no} ${r.full_name}` },
    { key: "worked_days", kind: "range", getValue: (r) => r.worked_days },
    { key: "unpaid_absence_days", kind: "range", getValue: (r) => r.unpaid_absence_days },
  ];
  const summaryFilters = useColumnFilters(summaryFields);
  const summaryColumns: ColumnDef<SummaryRowView>[] = [
    {
      key: "employee", header: t("hr.common.employee"), defaultWidth: 220, alwaysVisible: true, sortValue: (r) => r.employee_no, cell: (r) => `${r.employee_no} · ${r.full_name}`,
      filterCell: { type: "text", placeholder: t("hr.common.employee"), value: summaryFilters.text.employee ?? "", onChange: (v) => summaryFilters.setTextValue("employee", v) },
    },
    ...SUMMARY_TILES.map((tile): ColumnDef<SummaryRowView> => ({
      key: tile.key,
      header: t(tile.label),
      defaultWidth: 120,
      cellClassName: "tabular-nums",
      sortValue: (r) => Number(r[tile.key]),
      cell: (r) => (tile.minutes ? formatDuration(Number(r[tile.key])) : r[tile.key]),
      filterCell:
        tile.key === "worked_days" || tile.key === "unpaid_absence_days"
          ? {
              type: "range",
              min: summaryFilters.range[tile.key]?.min ?? "",
              max: summaryFilters.range[tile.key]?.max ?? "",
              onMinChange: (v) => summaryFilters.setRangeValue(tile.key, "min", v),
              onMaxChange: (v) => summaryFilters.setRangeValue(tile.key, "max", v),
            }
          : undefined,
    })),
  ];

  return (
    <div className="space-y-4">
      <HrListTable
        tableKey="hr.presence.months"
        columns={monthColumns}
        rows={monthRows}
        rowKey={(m) => m.period}
        loading={months.isLoading}
        emptyIcon={<CalendarCheck className="h-5 w-5" />}
        emptyTitle={t("hr.presence.months.period")}
        emptyDescription=""
        rowClassName={(m) => (m.period === selected ? "bg-muted/50" : undefined)}
        toolbar={
          <>
            <Input type="number" className="w-24" aria-label={t("hr.common.year")} value={year} onChange={(e) => setYear(Number(e.target.value) || year)} />
            <FilterTabs
              value={statusFilter}
              onChange={setStatusFilter}
              options={[
                { value: "all", label: t("common.all") },
                { value: "open", label: t("hr.presence.months.status.open") },
                { value: "closed", label: t("hr.presence.months.status.closed") },
              ]}
            />
          </>
        }
      />
      {current?.status === "open" && (
        <Card>
          <CardHeader>
            <CardTitle className="capitalize">{t("hr.presence.months.gaps")} — {formatMonth(selected)}</CardTitle>
          </CardHeader>
          <CardContent>
            <HrListTable
              tableKey="hr.presence.gaps"
              columns={gapColumns}
              rows={gapRows}
              rowKey={(g) => `${g.employee_id}|${g.work_date}`}
              loading={gaps.isLoading}
              emptyIcon={<CheckCircle2 className="h-5 w-5" />}
              emptyTitle={t("hr.presence.months.gapsNone")}
              emptyDescription={t("hr.presence.months.gapsNoneHelp")}
              filtersActive={gapFilters.isActive}
              onClearFilters={gapFilters.reset}
              toolbar={
                <FilterTabs
                  value={gapFilter}
                  onChange={setGapFilter}
                  options={[
                    { value: "all", label: t("common.all") },
                    { value: "missing", label: t("hr.presence.months.gapReason.missing") },
                    { value: "no_schedule", label: t("hr.presence.months.gapReason.no_schedule") },
                  ]}
                />
              }
            />
          </CardContent>
        </Card>
      )}
      <Card>
        <CardHeader>
          <CardTitle className="capitalize">{t("hr.presence.months.summary")} — {formatMonth(selected)}</CardTitle>
        </CardHeader>
        <CardContent>
          <HrListTable
            tableKey="hr.presence.summary"
            columns={summaryColumns}
            rows={summaryFilters.apply(summaryRows)}
            rowKey={(r) => r.employee_id}
            loading={summary.isLoading}
            emptyIcon={<ListChecks className="h-5 w-5" />}
            emptyTitle={t("hr.presence.months.summaryEmpty.title")}
            emptyDescription={t("hr.presence.months.summaryEmpty.description")}
            filtersActive={summaryFilters.isActive}
            onClearFilters={summaryFilters.reset}
          />
        </CardContent>
      </Card>
      <Dialog open={closing} onOpenChange={setClosing}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="capitalize">{t("hr.presence.months.closeTitle")} — {formatMonth(selected)}</DialogTitle>
            <DialogDescription>{t("hr.presence.months.closeHelp")}</DialogDescription>
          </DialogHeader>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setClosing(false)}>{t("common.cancel")}</Button>
            <Button onClick={() => close.mutate()} disabled={close.isPending}>{t("hr.presence.months.close")}</Button>
          </div>
        </DialogContent>
      </Dialog>
      <Dialog open={reopening} onOpenChange={setReopening}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="capitalize">{t("hr.presence.months.reopenTitle")} — {formatMonth(selected)}</DialogTitle>
            <DialogDescription>{t("hr.presence.months.reopenHelp")}</DialogDescription>
          </DialogHeader>
          <div className="space-y-1.5">
            <Label htmlFor="reopen-reason">{t("hr.presence.months.reason")}</Label>
            <Input id="reopen-reason" value={reason} onChange={(e) => setReason(e.target.value)} />
          </div>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setReopening(false)}>{t("common.cancel")}</Button>
            <Button onClick={() => reopen.mutate()} disabled={!reason.trim() || reopen.isPending}>{t("hr.presence.months.reopen")}</Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
