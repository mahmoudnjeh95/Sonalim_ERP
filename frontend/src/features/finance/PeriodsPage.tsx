import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarRange, Lock, LockOpen } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import { useColumnFilters, type FilterField } from "../../lib/useColumnFilters";
import type { ColumnDef } from "../../lib/useTableColumns";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Input } from "../../components/ui/input";
import { FilterTabs } from "../../components/patterns/FilterTabs";
import { LedgerTable, textFilter } from "./LedgerTable";
import { errorText, formatDate, formatMonth } from "./ledgerFormat";
import {
  LEDGER_KEYS,
  closePeriod,
  invalidateLedgerData,
  listPeriods,
  openFiscalYear,
  reopenPeriod,
  type AccountingPeriod,
  type PeriodStatus,
} from "./ledgerApi";

export function PeriodsPage() {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const canAdmin = hasPermission("finance.admin_periods");
  const [yearFilter, setYearFilter] = useState<string>("all");
  const [statusFilter, setStatusFilter] = useState<"all" | PeriodStatus>("all");
  const [newYear, setNewYear] = useState(String(new Date().getFullYear()));
  const { data: periods = [], isLoading } = useQuery({ queryKey: LEDGER_KEYS.periods, queryFn: () => listPeriods(token) });
  const years = [...new Set(periods.map((period) => String(period.year)))].sort().reverse();

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: LEDGER_KEYS.periods });
    invalidateLedgerData(queryClient);
  };
  const openYearMutation = useMutation({
    mutationFn: () => openFiscalYear(token, Number(newYear)),
    onSuccess: () => {
      refresh();
      toast.success(t("finance.periods.yearOpened"));
    },
    onError: (error) => toast.error(t("finance.periods.yearError"), { description: errorText(error) }),
  });
  const statusMutation = useMutation({
    mutationFn: ({ period, close }: { period: string; close: boolean }) =>
      close ? closePeriod(token, period) : reopenPeriod(token, period),
    onSuccess: (_, { close }) => {
      refresh();
      toast.success(t(close ? "finance.periods.closedToast" : "finance.periods.reopenedToast"));
    },
    onError: (error) => toast.error(t("finance.periods.statusError"), { description: errorText(error) }),
  });

  const fields: FilterField<AccountingPeriod>[] = [{ key: "period", kind: "text", getValue: (row) => formatMonth(row.period) }];
  const columnFilters = useColumnFilters(fields);
  const rows = columnFilters.apply(
    periods.filter(
      (row) => (yearFilter === "all" || String(row.year) === yearFilter) && (statusFilter === "all" || row.status === statusFilter),
    ),
  );
  const columns: ColumnDef<AccountingPeriod>[] = [
    {
      key: "period",
      header: t("finance.periods.column.period"),
      defaultWidth: 200,
      cell: (row) => <span className="capitalize">{formatMonth(row.period)}</span>,
      filterCell: textFilter(columnFilters, "period", t("finance.periods.column.period")),
      sortValue: (row) => row.period,
    },
    {
      key: "status",
      header: t("finance.periods.column.status"),
      defaultWidth: 130,
      cell: (row) =>
        row.status === "open" ? (
          <Badge variant="success">{t("finance.periods.status.open")}</Badge>
        ) : (
          <Badge>{t("finance.periods.status.closed")}</Badge>
        ),
      sortValue: (row) => row.status,
    },
    {
      key: "closed_at",
      header: t("finance.periods.column.closedAt"),
      defaultWidth: 140,
      cell: (row) => (row.closed_at ? formatDate(row.closed_at) : "—"),
      sortValue: (row) => row.closed_at ?? "",
    },
    {
      key: "actions",
      header: t("finance.column.action"),
      defaultWidth: 140,
      alwaysVisible: true,
      headerClassName: "text-right",
      cell: (row) =>
        canAdmin ? (
          <div className="flex justify-end">
            {row.status === "open" ? (
              <Button
                size="sm"
                variant="outline"
                disabled={statusMutation.isPending}
                onClick={() => {
                  if (window.confirm(t("finance.periods.closeConfirm"))) statusMutation.mutate({ period: row.period, close: true });
                }}
              >
                <Lock className="h-3.5 w-3.5" />
                {t("finance.periods.close")}
              </Button>
            ) : (
              <Button
                size="sm"
                variant="outline"
                disabled={statusMutation.isPending}
                onClick={() => statusMutation.mutate({ period: row.period, close: false })}
              >
                <LockOpen className="h-3.5 w-3.5" />
                {t("finance.periods.reopen")}
              </Button>
            )}
          </div>
        ) : null,
    },
  ];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">{t("finance.periods.title")}</h1>
          <p className="text-sm text-muted-foreground">{t("finance.periods.subtitle")}</p>
        </div>
        {canAdmin && (
          <div className="flex items-center gap-2">
            <Input
              type="number"
              min={2000}
              max={2100}
              className="h-9 w-24"
              value={newYear}
              onChange={(event) => setNewYear(event.target.value)}
              aria-label={t("finance.periods.year")}
            />
            <Button onClick={() => openYearMutation.mutate()} disabled={openYearMutation.isPending}>
              <CalendarRange className="h-4 w-4" />
              {t("finance.periods.openYear")}
            </Button>
          </div>
        )}
      </div>
      <Card>
        <CardHeader>
          <CardTitle>{t("finance.periods.tableTitle")}</CardTitle>
        </CardHeader>
        <CardContent className="p-0 pb-2">
          <LedgerTable
            tableKey="finance.periods"
            columns={columns}
            rows={rows}
            rowKey={(row) => row.period}
            isLoading={isLoading}
            emptyIcon={<CalendarRange className="h-5 w-5" />}
            emptyTitle={t("finance.periods.emptyTitle")}
            emptyDescription={t("finance.periods.emptyDescription")}
            toolbar={
              <>
                <FilterTabs
                  value={yearFilter}
                  onChange={setYearFilter}
                  options={[{ value: "all", label: t("common.all") }, ...years.map((year) => ({ value: year, label: year }))]}
                />
                <FilterTabs
                  value={statusFilter}
                  onChange={setStatusFilter}
                  options={[
                    { value: "all", label: t("common.all") },
                    { value: "open", label: t("finance.periods.status.open") },
                    { value: "closed", label: t("finance.periods.status.closed") },
                  ]}
                />
                {columnFilters.isActive && (
                  <Button variant="ghost" size="sm" onClick={columnFilters.reset}>
                    {t("common.clearFilters")}
                  </Button>
                )}
              </>
            }
          />
        </CardContent>
      </Card>
    </div>
  );
}
