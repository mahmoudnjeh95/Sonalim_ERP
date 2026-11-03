import { useParams } from "react-router-dom";
import { Banknote } from "lucide-react";
import { AppLoader } from "../../../components/patterns/AppLoader";
import { EmptyState } from "../../../components/patterns/EmptyState";
import { useI18n, type TranslationKey } from "../../../lib/i18n";
import { useCashSheet } from "../api";
import { formatPeriod, formatXof } from "../format";
import { PRINT_TABLE, PRINT_TD, PRINT_TH, PrintShell } from "../../../components/patterns/PrintShell";

/** /payroll/payout-batches/:batchId/cash-sheet/print — who gets how much in cash, the note/coin count, a signature column. */
export function CashSheetPrintPage() {
  const { batchId } = useParams<{ batchId: string }>();
  const { t, language } = useI18n();
  const locale = language === "fr" ? "fr-FR" : "en-US";
  const { data: sheet, isLoading, isError, error } = useCashSheet(batchId);

  if (isLoading) return <AppLoader label={t("payroll.common.loading")} fullScreen />;
  if (isError || !sheet) {
    return (
      <EmptyState
        icon={<Banknote className="h-5 w-5" />}
        title={t("payroll.print.notFound")}
        description={error instanceof Error ? error.message : t("payroll.print.notFoundDescription")}
      />
    );
  }

  const count = (value: number) => new Intl.NumberFormat(locale).format(value);
  // Only the notes and coins this batch actually uses get a column; the full list stays in the summary.
  const used = sheet.denominations.filter((value) => (sheet.totals.counts[String(value)] ?? 0) > 0);
  const subtitle = (
    <>
      <p>{formatPeriod(sheet.period, locale)}</p>
      <p>
        {t("payroll.print.status")} {t(`payroll.status.payslipBatch.${sheet.batch.status}` as TranslationKey)}
      </p>
    </>
  );

  return (
    <PrintShell title={t("payroll.print.cashSheetTitle")} subtitle={subtitle} company={sheet.company} backTo={`/payroll/runs/${sheet.batch.run_id}?tab=payouts`}>
      {sheet.lines.length === 0 ? (
        <p className="text-sm text-neutral-600">{t("payroll.print.cashSheet.empty")}</p>
      ) : (
        <table className={PRINT_TABLE}>
          <thead>
            <tr>
              <th className={PRINT_TH}>{t("payroll.print.cashSheet.column.employeeNo")}</th>
              <th className={PRINT_TH}>{t("payroll.print.cashSheet.column.employee")}</th>
              <th className={`${PRINT_TH} text-right`}>{t("payroll.print.cashSheet.column.amount")}</th>
              {used.map((value) => (
                <th key={value} className={`${PRINT_TH} text-right`}>
                  {count(value)}
                </th>
              ))}
              <th className={`${PRINT_TH} w-40`}>{t("payroll.print.cashSheet.column.signature")}</th>
            </tr>
          </thead>
          <tbody>
            {sheet.lines.map((line) => (
              <tr key={line.employee_no} className="break-inside-avoid">
                <td className={PRINT_TD}>{line.employee_no}</td>
                <td className={PRINT_TD}>{line.full_name}</td>
                <td className={`${PRINT_TD} text-right`}>{formatXof(line.amount, locale)}</td>
                {used.map((value) => (
                  <td key={value} className={`${PRINT_TD} text-right`}>
                    {line.counts[String(value)] ? count(line.counts[String(value)]) : ""}
                  </td>
                ))}
                <td className={`${PRINT_TD} h-9 border-l border-neutral-300`} />
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr className="font-semibold">
              <td className="px-2 py-1.5" colSpan={2}>
                {t("payroll.print.total")}
              </td>
              <td className="px-2 py-1.5 text-right">{formatXof(sheet.totals.amount, locale)}</td>
              {used.map((value) => (
                <td key={value} className="px-2 py-1.5 text-right">
                  {count(sheet.totals.counts[String(value)] ?? 0)}
                </td>
              ))}
              <td />
            </tr>
          </tfoot>
        </table>
      )}

      <div className="flex justify-end break-inside-avoid">
        <table className={`${PRINT_TABLE} max-w-sm`}>
          <caption className="pb-1 text-left text-xs font-semibold">{t("payroll.print.cashSheet.totals")}</caption>
          <thead>
            <tr>
              <th className={PRINT_TH}>{t("payroll.print.cashSheet.column.denomination")}</th>
              <th className={`${PRINT_TH} text-right`}>{t("payroll.print.cashSheet.column.count")}</th>
              <th className={`${PRINT_TH} text-right`}>{t("payroll.print.cashSheet.column.amount")}</th>
            </tr>
          </thead>
          <tbody>
            {used.map((value) => {
              const pieces = sheet.totals.counts[String(value)] ?? 0;
              return (
                <tr key={value}>
                  <td className={PRINT_TD}>{formatXof(value, locale)}</td>
                  <td className={`${PRINT_TD} text-right`}>{count(pieces)}</td>
                  <td className={`${PRINT_TD} text-right`}>{formatXof(value * pieces, locale)}</td>
                </tr>
              );
            })}
            {sheet.totals.remainder > 0 && (
              <tr>
                <td className={PRINT_TD} colSpan={2}>
                  {t("payroll.print.cashSheet.remainder")}
                </td>
                <td className={`${PRINT_TD} text-right`}>{formatXof(sheet.totals.remainder, locale)}</td>
              </tr>
            )}
          </tbody>
          <tfoot>
            <tr className="font-semibold">
              <td className="px-2 py-1.5" colSpan={2}>
                {t("payroll.print.total")}
              </td>
              <td className="px-2 py-1.5 text-right">{formatXof(sheet.totals.amount, locale)}</td>
            </tr>
          </tfoot>
        </table>
      </div>

      <div className="grid grid-cols-2 gap-8 pt-6 text-xs break-inside-avoid">
        <p className="border-t border-neutral-900 pt-1 print:border-black">{t("payroll.print.cashSheet.preparedBy")}</p>
        <p className="border-t border-neutral-900 pt-1 print:border-black">{t("payroll.print.cashSheet.paidBy")}</p>
      </div>
    </PrintShell>
  );
}
