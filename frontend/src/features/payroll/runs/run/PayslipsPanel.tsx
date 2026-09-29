import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { FilterTabs } from "../../../../components/patterns/FilterTabs";
import { Badge } from "../../../../components/ui/badge";
import { useI18n, type TranslationKey } from "../../../../lib/i18n";
import { useColumnFilters } from "../../../../lib/useColumnFilters";
import type { ColumnDef } from "../../../../lib/useTableColumns";
import { useRunPayslips, type PayslipSummary } from "../../api";
import { PayrollTable } from "../../PayrollTable";
import { formatXof } from "../../format";

type WarningFilter = "all" | "warnings";

/** A run's payslips; a row opens the payslip. Every warning code a payslip carries is shown, never dropped. */
export function PayslipsPanel({ runId }: { runId: string }) {
  const { t } = useI18n();
  const navigate = useNavigate();
  const { data: payslips = [], isLoading } = useRunPayslips(runId);
  const [warningFilter, setWarningFilter] = useState<WarningFilter>("all");
  const filters = useColumnFilters<PayslipSummary>([
    { key: "employee", kind: "text", getValue: (row) => `${row.full_name} ${row.employee_no}` },
    { key: "gross", kind: "range", getValue: (row) => row.gross },
    { key: "net", kind: "range", getValue: (row) => row.net },
  ]);

  // A code with no translation yet is shown as the code itself rather than hidden.
  const warningLabel = (code: string) => {
    const key = `payroll.run.payslips.warning.${code}` as TranslationKey;
    const label = t(key);
    return label === key ? code : label;
  };

  const columns: ColumnDef<PayslipSummary>[] = [
    {
      key: "employee",
      header: t("payroll.run.payslips.column.employee"),
      cell: (row) => (
        <span>
          <span className="font-medium">{row.full_name}</span>
          <span className="ml-1.5 text-xs text-muted-foreground">{row.employee_no}</span>
        </span>
      ),
      defaultWidth: 260,
      sortValue: (row) => row.full_name,
      filterCell: filters.textCell("employee", t("payroll.run.payslips.filter.employee")),
    },
    {
      key: "gross",
      header: t("payroll.run.payslips.column.gross"),
      cell: (row) => formatXof(row.gross),
      defaultWidth: 160,
      cellClassName: "tabular-nums",
      sortValue: (row) => row.gross,
      filterCell: filters.rangeCell("gross"),
    },
    {
      key: "net",
      header: t("payroll.run.payslips.column.net"),
      cell: (row) => formatXof(row.net),
      defaultWidth: 160,
      cellClassName: "tabular-nums",
      sortValue: (row) => row.net,
      filterCell: filters.rangeCell("net"),
    },
    {
      key: "warnings",
      header: t("payroll.run.payslips.column.warnings"),
      cell: (row) =>
        row.warnings.length > 0 ? (
          <span className="flex flex-wrap gap-1">
            {row.warnings.map((code) => (
              <Badge key={code} variant="warning">
                {warningLabel(code)}
              </Badge>
            ))}
          </span>
        ) : (
          <span className="text-muted-foreground">—</span>
        ),
      defaultWidth: 200,
      sortValue: (row) => row.warnings.length,
    },
  ];

  const withWarnings = payslips.filter((row) => row.warnings.length > 0);
  const rows = filters.apply(warningFilter === "warnings" ? withWarnings : payslips);

  return (
    <PayrollTable
      tableKey="payroll.run.payslips"
      columns={columns}
      rows={rows}
      rowKey={(row) => row.id}
      loading={isLoading}
      emptyTitle={t("payroll.run.payslips.empty.title")}
      emptyDescription={t("payroll.run.payslips.empty.description")}
      toolbar={
        <FilterTabs
          options={[
            { value: "all", label: `${t("payroll.run.payslips.filter.all")} (${payslips.length})` },
            { value: "warnings", label: `${t("payroll.run.payslips.filter.warnings")} (${withWarnings.length})` },
          ]}
          value={warningFilter}
          onChange={setWarningFilter}
        />
      }
      filtersActive={filters.isActive || warningFilter !== "all"}
      onClearFilters={() => {
        filters.reset();
        setWarningFilter("all");
      }}
      onRowClick={(row) => navigate(`/payroll/payslips/${row.id}`)}
    />
  );
}
