import { useSearchParams } from "react-router-dom";
import { Landmark } from "lucide-react";
import { AppLoader } from "../../../components/patterns/AppLoader";
import { EmptyState } from "../../../components/patterns/EmptyState";
import { useI18n, type TranslationKey } from "../../../lib/i18n";
import { useAnnualRecap, useDeclaration } from "../api";
import { formatPeriod, formatXof } from "../format";
import { PRINT_TABLE, PRINT_TD, PRINT_TH, PrintShell } from "./PrintShell";

const TEXT_COLUMNS = new Set(["employee_no", "full_name", "identifier"]);
const COUNT_COLUMNS = new Set(["months"]);

/**
 * /payroll/declarations/print?period=YYYY-MM-01&code=CODE (a monthly declaration) or ?year=YYYY (the
 * annual recap). Both endpoints return {code, columns, rows, totals} and no employer block, so the
 * sheet prints without one rather than inventing it.
 */
export function DeclarationPrintPage() {
  const [params] = useSearchParams();
  const { t, language } = useI18n();
  const locale = language === "fr" ? "fr-FR" : "en-US";
  const period = params.get("period") ?? "";
  const code = params.get("code") ?? undefined;
  const year = Number(params.get("year") ?? 0) || 0;
  // Both hooks always run (rules of hooks); each is disabled when its own params are missing.
  const declaration = useDeclaration(year ? "" : period, year ? undefined : code);
  const annual = useAnnualRecap(year);
  const { data, isLoading, isError, error } = year ? annual : declaration;

  if (!year && !(period && code)) {
    return <EmptyState icon={<Landmark className="h-5 w-5" />} title={t("payroll.print.notFound")} description={t("payroll.print.declaration.missingParams")} />;
  }
  if (isLoading) return <AppLoader label={t("payroll.common.loading")} fullScreen />;
  if (isError || !data) {
    // A month with nothing to declare for this code is refused with a worded NOT_FOUND.
    return (
      <EmptyState
        icon={<Landmark className="h-5 w-5" />}
        title={t("payroll.print.declaration.empty")}
        description={error instanceof Error ? error.message : t("payroll.print.notFoundDescription")}
      />
    );
  }

  const columnLabel = (column: string) => {
    for (const share of ["employee", "employer"] as const) {
      if (column.endsWith(`_${share}`)) return `${column.slice(0, -share.length - 1)} (${t(`payroll.print.declaration.share.${share}`)})`;
    }
    const key = `payroll.print.declaration.column.${column}` as TranslationKey;
    const label = t(key);
    return label === key ? column : label;
  };
  const cell = (column: string, value: string | number | null | undefined) => {
    if (value === null || value === undefined || value === "") return "";
    if (TEXT_COLUMNS.has(column) || typeof value !== "number") return String(value);
    if (COUNT_COLUMNS.has(column)) return new Intl.NumberFormat(locale).format(value);
    return formatXof(value, locale);
  };
  const numeric = (column: string) => !TEXT_COLUMNS.has(column);

  const title = year ? t("payroll.print.annualTitle") : `${t("payroll.print.declarationTitle")} ${data.code}`;
  const subtitle = year ? String(year) : formatPeriod(period, locale);
  const firstTotal = data.columns.findIndex((column) => column in data.totals);

  return (
    <PrintShell title={title} subtitle={subtitle} company={null} backTo="/payroll/runs">
      {data.rows.length === 0 ? (
        <p className="text-sm text-neutral-600">{t("payroll.print.declaration.noRows")}</p>
      ) : (
        <table className={PRINT_TABLE}>
          <thead>
            <tr>
              {data.columns.map((column) => (
                <th key={column} className={`${PRINT_TH} ${numeric(column) ? "text-right" : ""}`}>
                  {columnLabel(column)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.rows.map((row, index) => (
              <tr key={`${String(row.employee_no ?? "")}-${index}`} className="break-inside-avoid">
                {data.columns.map((column) => (
                  <td key={column} className={`${PRINT_TD} ${numeric(column) ? "text-right" : ""}`}>
                    {cell(column, row[column])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
          {firstTotal > 0 && (
            <tfoot>
              <tr className="font-semibold">
                <td className="px-2 py-1.5" colSpan={firstTotal}>
                  {t("payroll.print.total")}
                </td>
                {data.columns.slice(firstTotal).map((column) => (
                  <td key={column} className="px-2 py-1.5 text-right">
                    {column in data.totals ? cell(column, data.totals[column]) : ""}
                  </td>
                ))}
              </tr>
            </tfoot>
          )}
        </table>
      )}
    </PrintShell>
  );
}
