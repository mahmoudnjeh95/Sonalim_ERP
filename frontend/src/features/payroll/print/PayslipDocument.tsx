import { AlertTriangle } from "lucide-react";
import { useI18n, type TranslationKey } from "../../../lib/i18n";
import type { PayslipDetail, PayslipLine } from "../api";
import { DraftRuleSetBanner } from "../DraftRuleSetBanner";
import { formatPeriod, formatXof } from "../format";
import { formatDay, PRINT_TABLE, PRINT_TD, PRINT_TH } from "./PrintShell";

const SECTION_ORDER = ["earning", "employee_contribution", "relief", "tax", "deduction", "employer_contribution", "employer_charge"];

/** The payslip snapshot fields this document reads (the rest of the snapshot is not printed). */
interface PrintedSnapshot {
  employee?: { hire_date?: string | null; inps_no?: string | null } | null;
  rule_set?: { id?: string } | null;
}

function groupBySection(lines: PayslipLine[]): [string, PayslipLine[]][] {
  const known = SECTION_ORDER.map((section) => [section, lines.filter((line) => line.section === section)] as [string, PayslipLine[]]);
  // A section this list does not know yet is still printed, after the known ones — never dropped.
  const others = [...new Set(lines.map((line) => line.section))].filter((section) => !SECTION_ORDER.includes(section));
  return [...known, ...others.map((section) => [section, lines.filter((line) => line.section === section)] as [string, PayslipLine[]])].filter(
    ([, rows]) => rows.length > 0,
  );
}

/**
 * One printed payslip: employee block, carried warnings, the line table by section, totals.
 * `draftRuleSetName` names the draft rule set when the caller could look it up.
 */
export function PayslipDocument({ payslip, draftRuleSetName }: { payslip: PayslipDetail; draftRuleSetName?: string }) {
  const { t, language } = useI18n();
  const locale = language === "fr" ? "fr-FR" : "en-US";
  const snapshot = payslip.snapshot as PrintedSnapshot;
  const number = (value: number | null) => (value === null ? "" : new Intl.NumberFormat(locale, { maximumFractionDigits: 4 }).format(value));

  const sectionLabel = (section: string) => {
    const key = `payroll.print.section.${section}` as TranslationKey;
    const label = t(key);
    return label === key ? section : label;
  };
  // A warning code with no translation yet is printed as the code itself rather than hidden.
  const warningLabel = (code: string) => {
    const key = `payroll.run.payslips.warning.${code}` as TranslationKey;
    const label = t(key);
    return label === key ? code : label;
  };

  const facts: { label: string; value: string }[] = [
    { label: t("payroll.print.payslip.employeeNo"), value: payslip.employee_no },
    { label: t("payroll.print.payslip.period"), value: formatPeriod(payslip.period, locale) },
    ...(snapshot.employee?.hire_date ? [{ label: t("payroll.print.payslip.hireDate"), value: formatDay(snapshot.employee.hire_date, locale) }] : []),
    ...(snapshot.employee?.inps_no ? [{ label: t("payroll.print.payslip.inpsNo"), value: snapshot.employee.inps_no }] : []),
  ];

  const totals: { label: string; value: number; strong?: boolean }[] = [
    { label: t("payroll.print.totals.gross"), value: payslip.gross },
    { label: t("payroll.print.totals.employeeContrib"), value: payslip.employee_contrib },
    { label: t("payroll.print.totals.its"), value: payslip.its },
    { label: t("payroll.print.totals.deductions"), value: payslip.deductions },
    { label: t("payroll.print.totals.net"), value: payslip.net, strong: true },
  ];

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <p className="text-base font-semibold">{payslip.full_name}</p>
        <dl className="grid grid-cols-[auto_auto] gap-x-3 text-xs">
          {facts.map((fact) => (
            <div key={fact.label} className="contents">
              <dt className="text-neutral-600">{fact.label}</dt>
              <dd className="text-right font-medium">{fact.value}</dd>
            </div>
          ))}
        </dl>
      </div>

      <DraftRuleSetBanner
        ruleSet={payslip.rule_set_status === "draft" ? { id: snapshot.rule_set?.id ?? "", name: draftRuleSetName ?? "", status: "draft" } : null}
      />

      {/* Worded, bordered and bold: readable on a black-and-white printout, not carried by colour alone. */}
      {payslip.warnings.length > 0 && (
        <div role="alert" className="flex items-start gap-2 rounded-md border-2 border-amber-600 px-3 py-2 text-sm font-semibold text-amber-900 print:border-black print:text-black">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
          <span>
            {t("payroll.print.warnings")} {payslip.warnings.map(warningLabel).join(" · ")}
          </span>
        </div>
      )}

      <table className={PRINT_TABLE}>
        <thead>
          <tr>
            <th className={PRINT_TH}>{t("payroll.print.line.label")}</th>
            <th className={`${PRINT_TH} text-right`}>{t("payroll.print.line.base")}</th>
            <th className={`${PRINT_TH} text-right`}>{t("payroll.print.line.qty")}</th>
            <th className={`${PRINT_TH} text-right`}>{t("payroll.print.line.rate")}</th>
            <th className={`${PRINT_TH} text-right`}>{t("payroll.print.line.amount")}</th>
          </tr>
        </thead>
        {groupBySection(payslip.lines).map(([section, lines]) => (
          <tbody key={section} className="break-inside-avoid">
            <tr>
              <td colSpan={5} className="px-2 pb-1 pt-3 text-[11px] font-semibold uppercase tracking-wide text-neutral-700 print:text-black">
                {sectionLabel(section)}
              </td>
            </tr>
            {lines.map((line) => (
              <tr key={line.line_no}>
                <td className={PRINT_TD}>{language === "fr" ? line.name_fr : line.name_en}</td>
                <td className={`${PRINT_TD} text-right`}>{line.base === null ? "" : formatXof(line.base, locale)}</td>
                <td className={`${PRINT_TD} text-right`}>{number(line.qty)}</td>
                <td className={`${PRINT_TD} text-right`}>{number(line.rate)}</td>
                <td className={`${PRINT_TD} text-right`}>{formatXof(line.amount, locale)}</td>
              </tr>
            ))}
          </tbody>
        ))}
      </table>

      {payslip.lines.length === 0 && <p className="text-xs italic text-neutral-600">{t("payroll.print.payslip.noLines")}</p>}

      <div className="flex justify-end">
        <dl className="w-full max-w-xs text-xs break-inside-avoid">
          {totals.map((row) => (
            <div key={row.label} className={`flex justify-between gap-4 py-0.5 ${row.strong ? "border-t-2 border-neutral-900 pt-1 text-sm font-semibold print:border-black" : ""}`}>
              <dt>{row.label}</dt>
              <dd className="tabular-nums">{formatXof(row.value, locale)}</dd>
            </div>
          ))}
          <div className="flex justify-between gap-4 pt-1 text-neutral-600">
            <dt>{t("payroll.print.totals.employerCost")}</dt>
            <dd className="tabular-nums">{formatXof(payslip.employer_cost, locale)}</dd>
          </div>
        </dl>
      </div>

      {payslip.note && (
        <p className="text-xs">
          <span className="font-semibold">{t("payroll.print.payslip.note")}</span> {payslip.note}
        </p>
      )}
    </div>
  );
}
