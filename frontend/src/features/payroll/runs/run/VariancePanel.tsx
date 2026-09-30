import { useState } from "react";
import { Link } from "react-router-dom";
import { ArrowLeftRight } from "lucide-react";
import { EmptyState } from "../../../../components/patterns/EmptyState";
import { FilterTabs } from "../../../../components/patterns/FilterTabs";
import { Badge } from "../../../../components/ui/badge";
import { ApiError } from "../../../../lib/api";
import { useI18n, type TranslationKey } from "../../../../lib/i18n";
import { useColumnFilters } from "../../../../lib/useColumnFilters";
import type { ColumnDef } from "../../../../lib/useTableColumns";
import { useRunVariance, type VarianceRow } from "../../api";
import { formatPeriod, formatXof } from "../../format";
import { PayrollTable } from "../../PayrollTable";

type Change = VarianceRow["change"];
const CHANGES: Change[] = ["changed", "new", "left", "same"];
type ChangeFilter = "all" | Change;

const CHANGE_VARIANT: Record<Change, "primary" | "accent" | "warning" | "default"> = {
  new: "primary",
  left: "accent",
  changed: "warning",
  same: "default",
};

/** A signed difference: "+12 000 XOF", "-3 500 XOF", or a muted zero. */
function Delta({ value }: { value: number }) {
  if (value === 0) return <span className="text-muted-foreground">{formatXof(0)}</span>;
  return <span className="font-medium">{value > 0 ? `+${formatXof(value)}` : formatXof(value)}</span>;
}

/**
 * Each employee's gross and net against the previous month's approved (or paid) regular run —
 * who is new, who left, whose pay moved. The server classifies every row; nothing is judged here.
 */
export function VariancePanel({ runId }: { runId: string }) {
  const { t } = useI18n();
  const { data: variance, isLoading, error } = useRunVariance(runId);
  const [change, setChange] = useState<ChangeFilter>("all");
  const filters = useColumnFilters<VarianceRow>([
    { key: "employee", kind: "text", getValue: (row) => `${row.full_name} ${row.employee_no}` },
    { key: "deltaGross", kind: "range", getValue: (row) => row.delta_gross },
    { key: "deltaNet", kind: "range", getValue: (row) => row.delta_net },
  ]);

  if (error) {
    return <p className="text-sm text-destructive">{error instanceof ApiError ? error.message : t("payroll.variance.loadError")}</p>;
  }

  if (!isLoading && variance && !variance.previous_run_id) {
    return (
      <EmptyState
        icon={<ArrowLeftRight className="h-5 w-5" />}
        title={t("payroll.variance.none")}
        description={t("payroll.variance.noneHint").replace("{period}", formatPeriod(variance.previous_period))}
      />
    );
  }

  const all = variance?.rows ?? [];
  const count = (value: Change) => all.filter((row) => row.change === value).length;
  const rows = filters.apply(change === "all" ? all : all.filter((row) => row.change === change));

  const money = (key: string, header: TranslationKey, get: (row: VarianceRow) => number | null): ColumnDef<VarianceRow> => ({
    key,
    header: t(header),
    defaultWidth: 150,
    headerClassName: "text-right",
    cellClassName: "text-right tabular-nums",
    cell: (row) => formatXof(get(row)),
    sortValue: get,
  });

  const columns: ColumnDef<VarianceRow>[] = [
    {
      key: "employee",
      header: t("payroll.variance.column.employee"),
      defaultWidth: 240,
      cell: (row) => (
        <span>
          <span className="font-medium">{row.full_name}</span>
          <span className="ml-1.5 text-xs text-muted-foreground">{row.employee_no}</span>
        </span>
      ),
      sortValue: (row) => row.full_name,
      filterCell: filters.textCell("employee", t("payroll.run.payslips.filter.employee")),
    },
    money("previousGross", "payroll.variance.column.previousGross", (row) => row.previous_gross),
    money("currentGross", "payroll.variance.column.currentGross", (row) => row.current_gross),
    {
      key: "deltaGross",
      header: t("payroll.variance.column.deltaGross"),
      defaultWidth: 150,
      headerClassName: "text-right",
      cellClassName: "text-right tabular-nums",
      cell: (row) => <Delta value={row.delta_gross} />,
      sortValue: (row) => row.delta_gross,
      filterCell: filters.rangeCell("deltaGross"),
    },
    money("previousNet", "payroll.variance.column.previousNet", (row) => row.previous_net),
    money("currentNet", "payroll.variance.column.currentNet", (row) => row.current_net),
    {
      key: "deltaNet",
      header: t("payroll.variance.column.deltaNet"),
      defaultWidth: 150,
      headerClassName: "text-right",
      cellClassName: "text-right tabular-nums",
      cell: (row) => <Delta value={row.delta_net} />,
      sortValue: (row) => row.delta_net,
      filterCell: filters.rangeCell("deltaNet"),
    },
    {
      key: "change",
      header: t("payroll.variance.column.change"),
      defaultWidth: 130,
      cell: (row) => <Badge variant={CHANGE_VARIANT[row.change]}>{t(`payroll.variance.change.${row.change}` as TranslationKey)}</Badge>,
      sortValue: (row) => CHANGES.indexOf(row.change),
    },
  ];

  const totals = variance?.totals;
  const summary = totals
    ? [
        { label: t("payroll.run.summary.gross"), previous: totals.previous_gross, current: totals.current_gross },
        { label: t("payroll.run.summary.net"), previous: totals.previous_net, current: totals.current_net },
      ]
    : [];

  return (
    <div className="space-y-3">
      {variance?.previous_run_id && (
        <p className="text-sm text-muted-foreground">
          {t("payroll.variance.title")} ·{" "}
          <Link to={`/payroll/runs/${variance.previous_run_id}`} className="font-medium capitalize text-primary hover:underline">
            {formatPeriod(variance.previous_period)}
          </Link>
        </p>
      )}
      {summary.length > 0 && (
        <dl className="grid gap-3 sm:grid-cols-2">
          {summary.map((item) => (
            <div key={item.label} className="rounded-lg border border-border bg-background px-3 py-2">
              <dt className="text-xs text-muted-foreground">{item.label}</dt>
              <dd className="flex flex-wrap items-baseline gap-x-2 text-sm tabular-nums">
                <span className="text-muted-foreground">{formatXof(item.previous)}</span>
                <span aria-hidden>→</span>
                <span className="font-semibold">{formatXof(item.current)}</span>
                <span className="text-xs">
                  (<Delta value={item.current - item.previous} />)
                </span>
              </dd>
            </div>
          ))}
        </dl>
      )}
      <PayrollTable
        tableKey="payroll.run.variance"
        columns={columns}
        rows={rows}
        rowKey={(row) => row.employee_id}
        loading={isLoading}
        emptyTitle={t("payroll.variance.empty.title")}
        emptyDescription={t("payroll.variance.empty.description")}
        emptyIcon={<ArrowLeftRight className="h-5 w-5" />}
        toolbar={
          <FilterTabs
            value={change}
            onChange={setChange}
            options={[
              { value: "all" as ChangeFilter, label: `${t("payroll.runs.filter.all")} (${all.length})` },
              ...CHANGES.map((entry) => ({ value: entry as ChangeFilter, label: `${t(`payroll.variance.change.${entry}` as TranslationKey)} (${count(entry)})` })),
            ]}
          />
        }
        filtersActive={filters.isActive || change !== "all"}
        onClearFilters={() => {
          filters.reset();
          setChange("all");
        }}
      />
    </div>
  );
}
