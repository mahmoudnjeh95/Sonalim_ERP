import { useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { CalendarRange, Download, Info, Landmark, Printer } from "lucide-react";
import { EmptyState } from "../../../../components/patterns/EmptyState";
import { FilterTabs } from "../../../../components/patterns/FilterTabs";
import { Button } from "../../../../components/ui/button";
import { Input } from "../../../../components/ui/input";
import { Label } from "../../../../components/ui/label";
import { Skeleton } from "../../../../components/ui/skeleton";
import { useAuth } from "../../../../lib/auth";
import { useI18n, type TranslationKey } from "../../../../lib/i18n";
import { useColumnFilters } from "../../../../lib/useColumnFilters";
import type { ColumnDef } from "../../../../lib/useTableColumns";
import {
  annualRecapCsvUrl,
  declarationCsvUrl,
  fetchPayrollFile,
  useDeclaration,
  useDeclarationCodes,
  type Declaration,
  type PayrollRun,
} from "../../api";
import { formatPeriod, formatXof } from "../../format";
import { PayrollTable } from "../../PayrollTable";

type DeclarationRow = Declaration["rows"][number];

/** Columns that are not amounts; every other declaration column is F CFA. */
const TEXT_COLUMNS = new Set(["employee_no", "full_name", "identifier", "months"]);

function errorText(error: unknown): string | undefined {
  return error instanceof Error ? error.message : undefined;
}

function saveBlob(blob: Blob, fileName: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

/**
 * The month's declarations (the codes come from the payslips' rule set: contributions, taxes and
 * employer taxes), counting every approved or paid run of the period, plus the annual recap.
 * CSVs need the session token, so they are fetched and saved rather than linked.
 */
export function DeclarationsPanel({ run }: { run: PayrollRun }) {
  const { t } = useI18n();
  const { session } = useAuth();
  const token = session?.token ?? "";
  const codes = useDeclarationCodes(run.period);
  const [picked, setPicked] = useState("");
  const available = codes.data ?? [];
  const code = available.includes(picked) ? picked : (available[0] ?? "");
  const declaration = useDeclaration(run.period, code || undefined);
  const [year, setYear] = useState(run.period.slice(0, 4));
  const [downloading, setDownloading] = useState<"declaration" | "annual" | null>(null);
  const filters = useColumnFilters<DeclarationRow>([
    { key: "employee", kind: "text", getValue: (row) => `${row.full_name ?? ""} ${row.employee_no ?? ""}` },
  ]);

  // A label for each known code or column; one nobody translated shows as itself.
  const labelOr = (key: string, fallback: string) => {
    const label = t(key as TranslationKey);
    return label === key ? fallback : label;
  };
  const codeLabel = (value: string) => labelOr(`payroll.declarations.codeLabel.${value}`, value);
  const columnLabel = (column: string) => {
    const share = column.match(/^(.+)_(employee|employer)$/);
    if (share) return `${share[1]} (${t(`payroll.declarations.share.${share[2]}` as TranslationKey)})`;
    return labelOr(`payroll.declarations.column.${column}`, column);
  };

  const download = async (kind: "declaration" | "annual") => {
    setDownloading(kind);
    try {
      if (kind === "declaration") {
        saveBlob(await fetchPayrollFile(token, declarationCsvUrl(run.period, code)), `${code.toLowerCase()}-${run.period.slice(0, 7)}.csv`);
      } else {
        saveBlob(await fetchPayrollFile(token, annualRecapCsvUrl(Number(year))), `recap-annuel-${year}.csv`);
      }
    } catch (error) {
      toast.error(t("payroll.declarations.downloadRefused"), { description: errorText(error) });
    } finally {
      setDownloading(null);
    }
  };

  const data = declaration.data;
  const serverColumns = data?.columns ?? [];
  const merged = serverColumns.includes("employee_no") && serverColumns.includes("full_name");
  const amountColumns = serverColumns.filter((column) => !TEXT_COLUMNS.has(column));

  const columns: ColumnDef<DeclarationRow>[] = [
    ...(merged
      ? [
          {
            key: "employee",
            header: t("payroll.declarations.column.employee"),
            cell: (row: DeclarationRow) => (
              <span>
                <span className="font-medium">{row.full_name}</span>
                <span className="ml-1.5 text-xs text-muted-foreground">{row.employee_no}</span>
              </span>
            ),
            defaultWidth: 260,
            sortValue: (row: DeclarationRow) => String(row.full_name ?? ""),
            filterCell: filters.textCell("employee", t("payroll.run.payslips.filter.employee")),
          },
        ]
      : []),
    ...serverColumns
      .filter((column) => !(merged && (column === "employee_no" || column === "full_name")))
      .map((column): ColumnDef<DeclarationRow> => {
        const amount = !TEXT_COLUMNS.has(column);
        return {
          key: column,
          header: columnLabel(column),
          cell: (row) => {
            const value = row[column];
            if (value === null || value === undefined || value === "") return <span className="text-muted-foreground">—</span>;
            return amount && typeof value === "number" ? formatXof(value) : String(value);
          },
          defaultWidth: amount ? 160 : 150,
          headerClassName: amount ? "text-right" : undefined,
          cellClassName: amount ? "text-right tabular-nums" : undefined,
          sortValue: (row) => row[column],
        };
      }),
  ];

  const scope = (
    <p className="flex items-start gap-2 text-xs text-muted-foreground">
      <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
      <span>
        {t("payroll.declarations.scope").replace("{period}", formatPeriod(run.period))}
        {(run.status === "draft" || run.status === "calculated") && <> {t("payroll.declarations.notYetCounted")}</>}
      </span>
    </p>
  );

  const annual = (
    <div className="flex flex-wrap items-end gap-3 rounded-lg border border-border bg-muted/30 p-4">
      <div className="mr-auto space-y-0.5">
        <p className="flex items-center gap-2 text-sm font-semibold">
          <CalendarRange className="h-4 w-4 text-muted-foreground" aria-hidden />
          {t("payroll.declarations.annual")}
        </p>
        <p className="text-xs text-muted-foreground">{t("payroll.declarations.annualHint")}</p>
      </div>
      <div className="w-28 space-y-1.5">
        <Label htmlFor="declarations-annual-year">{t("payroll.declarations.annualYear")}</Label>
        <Input
          id="declarations-annual-year"
          type="number"
          min={2000}
          max={2100}
          step={1}
          value={year}
          onChange={(event) => setYear(event.target.value)}
        />
      </div>
      <Button variant="outline" size="sm" disabled={!/^\d{4}$/.test(year) || downloading === "annual"} onClick={() => void download("annual")}>
        <Download className="h-4 w-4" />
        {t("payroll.declarations.download")}
      </Button>
      {/^\d{4}$/.test(year) && (
        <Button variant="outline" size="sm" asChild>
          <Link to={`/payroll/declarations/print?year=${year}`}>
            <Printer className="h-4 w-4" />
            {t("payroll.declarations.print")}
          </Link>
        </Button>
      )}
    </div>
  );

  if (codes.isSuccess && available.length === 0) {
    return (
      <div className="space-y-3">
        {scope}
        <EmptyState icon={<Landmark className="h-5 w-5" />} title={t("payroll.declarations.empty.title")} description={t("payroll.declarations.empty.description")} />
        {annual}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {scope}
      <PayrollTable
        tableKey="payroll.run.declarations"
        columns={columns}
        rows={filters.apply(data ? [...data.rows] : [])}
        rowKey={(row) => String(row.employee_no ?? "")}
        loading={codes.isLoading || declaration.isLoading}
        emptyTitle={t("payroll.declarations.empty.title")}
        emptyDescription={codes.isError || declaration.isError ? (errorText(codes.error ?? declaration.error) ?? "") : t("payroll.declarations.empty.description")}
        emptyIcon={<Landmark className="h-5 w-5" />}
        filtersActive={filters.isActive}
        onClearFilters={filters.reset}
        toolbar={
          codes.isLoading ? (
            <Skeleton className="h-8 w-64" />
          ) : (
            <>
              <FilterTabs value={code} onChange={setPicked} options={available.map((value) => ({ value, label: codeLabel(value) }))} />
              {code && (
                <>
                  <Button variant="outline" size="sm" disabled={downloading === "declaration"} onClick={() => void download("declaration")}>
                    <Download className="h-4 w-4" />
                    {t("payroll.declarations.download")}
                  </Button>
                  <Button variant="outline" size="sm" asChild>
                    <Link to={`/payroll/declarations/print?period=${run.period}&code=${encodeURIComponent(code)}`}>
                      <Printer className="h-4 w-4" />
                      {t("payroll.declarations.print")}
                    </Link>
                  </Button>
                </>
              )}
            </>
          )
        }
      />
      {data && data.rows.length > 0 && amountColumns.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{t("payroll.declarations.totals")}</p>
          <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
            {amountColumns.map((column) => (
              <div key={column} className="rounded-lg border border-border bg-background px-3 py-2">
                <dt className="truncate text-xs text-muted-foreground" title={columnLabel(column)}>
                  {columnLabel(column)}
                </dt>
                <dd className="text-sm font-semibold tabular-nums">{formatXof(data.totals[column] ?? 0)}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}
      {annual}
    </div>
  );
}
