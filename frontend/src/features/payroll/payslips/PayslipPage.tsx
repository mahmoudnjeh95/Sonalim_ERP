import { Fragment, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { motion } from "framer-motion";
import { AlertTriangle, ArrowLeft, FileText, Pencil, Printer, Receipt, StickyNote } from "lucide-react";
import { AppLoader } from "../../../components/patterns/AppLoader";
import { EmptyState } from "../../../components/patterns/EmptyState";
import { Button } from "../../../components/ui/button";
import { Card } from "../../../components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../../../components/ui/table";
import { useAuth } from "../../../lib/auth";
import { currentLocale, useI18n, type TranslationKey } from "../../../lib/i18n";
import { useCertificate, usePayslip, useRuleSet, type PayslipLine } from "../api";
import { DraftRuleSetBanner } from "../DraftRuleSetBanner";
import { formatPeriod, formatXof } from "../format";
import { PayrollStatusBadge } from "../PayrollStatusBadge";
import { PayslipEditDialog } from "./PayslipEditDialog";

/** Payslip order (backend domain/inputs.py SECTIONS); a section not listed here still shows, after these. */
const SECTION_ORDER = ["earning", "employee_contribution", "relief", "tax", "deduction", "employer_contribution", "employer_charge"];

/** "YYYY-MM-DD" -> a local date, without the UTC shift `new Date(iso)` would apply. */
function formatDay(iso: string | null, locale: string): string {
  if (!iso) return "—";
  const [year, month, day] = iso.slice(0, 10).split("-").map(Number);
  return new Intl.DateTimeFormat(locale, { dateStyle: "long" }).format(new Date(year, month - 1, day));
}

export function PayslipPage() {
  const { payslipId } = useParams<{ payslipId: string }>();
  const { t, language } = useI18n();
  const { hasPermission } = useAuth();
  const { data: payslip, isLoading, isError } = usePayslip(payslipId);
  const [editOpen, setEditOpen] = useState(false);

  const snapshot = payslip?.snapshot as { rule_set?: { id?: string }; settlement?: unknown } | undefined;
  // The payslip keeps the rule set's status at calculation time; its id is in the snapshot.
  const draftId = payslip?.rule_set_status === "draft" ? (snapshot?.rule_set?.id ?? "") : "";
  const { data: ruleSet } = useRuleSet(draftId && hasPermission("payroll.view_rules") ? draftId : undefined);
  // A final-settlement payslip comes with a work certificate (the server says which).
  const { data: certificate } = useCertificate(snapshot?.settlement ? payslip?.id : undefined);

  if (isLoading) return <AppLoader label={t("payroll.common.loading")} fullScreen />;
  if (isError || !payslip) {
    return (
      <EmptyState
        icon={<Receipt className="h-5 w-5" />}
        title={t("payroll.payslip.notFound.title")}
        description={t("payroll.payslip.notFound.description")}
        action={
          <Button variant="outline" asChild>
            <Link to="/payroll/runs">{t("payroll.run.back")}</Link>
          </Button>
        }
      />
    );
  }

  const locale = currentLocale();
  const money = new Intl.NumberFormat(locale, { maximumFractionDigits: 0 });
  const quantity = new Intl.NumberFormat(locale, { maximumFractionDigits: 2 });
  const rate = new Intl.NumberFormat(locale, { maximumFractionDigits: 4 });
  // A paid or reversed run's payslips are locked server-side: no edit to offer.
  const canEdit = hasPermission("payroll.admin_payslips") && payslip.run_status !== "paid" && payslip.run_status !== "reversed";

  // Named while the rule set is still a draft; once confirmed since, the banner says only what the payslip was computed from.
  const draftRuleSet =
    payslip.rule_set_status === "draft" ? { id: draftId, name: ruleSet?.status === "draft" ? ruleSet.name : "", status: "draft" } : null;

  // A code with no translation yet is shown as the code itself rather than hidden.
  const translated = (key: string, fallback: string) => {
    const label = t(key as TranslationKey);
    return label === key ? fallback : label;
  };

  const sections = [...SECTION_ORDER, ...new Set(payslip.lines.map((line) => line.section).filter((section) => !SECTION_ORDER.includes(section)))]
    .map((section) => ({ section, lines: payslip.lines.filter((line) => line.section === section) }))
    .filter((group) => group.lines.length > 0);

  const netNegative = payslip.warnings.includes("NET_NEGATIVE");
  const summary: { label: string; value: string; warn?: boolean }[] = [
    { label: t("payroll.payslip.totals.gross"), value: formatXof(payslip.gross) },
    { label: t("payroll.payslip.totals.net"), value: formatXof(payslip.net), warn: netNegative },
    { label: t("payroll.payslip.totals.employerCost"), value: formatXof(payslip.employer_cost) },
  ];

  const lineName = (line: PayslipLine) => (language === "fr" ? line.name_fr : line.name_en) || line.code;

  return (
    <div className="space-y-6">
      <motion.div
        initial={{ opacity: 0, y: -6 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.25 }}
        className="flex flex-wrap items-start justify-between gap-3"
      >
        <div className="flex items-start gap-3">
          <Button variant="ghost" size="sm" asChild>
            <Link to={`/payroll/runs/${payslip.run_id}?tab=payslips`}>
              <ArrowLeft className="h-4 w-4" />
              {t("payroll.payslip.back")}
            </Link>
          </Button>
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-xl font-semibold tracking-tight">{payslip.full_name}</h1>
              <span className="text-sm text-muted-foreground">{payslip.employee_no}</span>
              <PayrollStatusBadge domain="run" status={payslip.run_status} />
            </div>
            <p className="text-sm text-muted-foreground">
              {t("payroll.payslip.title")} · {formatPeriod(payslip.period)} · {t(`payroll.runs.type.${payslip.run_type}` as TranslationKey)}
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {canEdit && (
            <Button variant="outline" onClick={() => setEditOpen(true)}>
              <Pencil className="h-4 w-4" />
              {t("payroll.payslip.edit")}
            </Button>
          )}
          <Button variant="outline" asChild>
            <Link to={`/payroll/payslips/${payslip.id}/print`}>
              <Printer className="h-4 w-4" />
              {t("payroll.payslip.print")}
            </Link>
          </Button>
        </div>
      </motion.div>

      <dl className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        {summary.map((item) => (
          <div key={item.label} className="rounded-lg border border-border bg-background px-3 py-2">
            <dt className="text-xs text-muted-foreground">{item.label}</dt>
            <dd className={`text-sm font-semibold tabular-nums ${item.warn ? "text-warning" : ""}`}>{item.value}</dd>
          </div>
        ))}
      </dl>

      {(draftRuleSet || payslip.warnings.length > 0 || payslip.note || certificate) && (
        <div className="space-y-2">
          <DraftRuleSetBanner ruleSet={draftRuleSet} />
          {/* Every warning the payslip carries is spelled out, never shown by colour alone. */}
          {payslip.warnings.length > 0 && (
            <div role="alert" className="flex items-start gap-3 rounded-lg border border-warning/30 bg-warning-soft px-3 py-2 text-sm">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" aria-hidden />
              <div className="flex-1 space-y-1">
                <p className="font-medium">{t("payroll.payslip.warnings")}</p>
                <ul className="space-y-1">
                  {payslip.warnings.map((code) => (
                    <li key={code}>
                      <span className="font-medium">{translated(`payroll.run.payslips.warning.${code}`, code)}</span>
                      {translated(`payroll.payslip.warning.${code}.hint`, "") && (
                        <span className="text-muted-foreground"> — {translated(`payroll.payslip.warning.${code}.hint`, "")}</span>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          )}
          {certificate && (
            <p className="flex items-start gap-2 rounded-lg border border-border bg-muted/40 px-3 py-2 text-sm">
              <FileText className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
              <span>
                <span className="font-medium">{t("payroll.payslip.certificate")}</span>{" "}
                {t("payroll.payslip.certificate.hint")
                  .replace("{hireDate}", formatDay(certificate.hire_date, locale))
                  .replace("{terminationDate}", formatDay(certificate.termination_date, locale))}
              </span>
            </p>
          )}
          {payslip.note && (
            <p className="flex items-start gap-2 rounded-lg border border-border bg-muted/40 px-3 py-2 text-sm">
              <StickyNote className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
              <span>
                <span className="font-medium">{t("payroll.common.note")}</span> <span className="whitespace-pre-wrap">{payslip.note}</span>
              </span>
            </p>
          )}
        </div>
      )}

      <Card className="overflow-hidden">
        {sections.length === 0 ? (
          <p className="px-5 py-8 text-center text-sm text-muted-foreground">{t("payroll.payslip.noLines")}</p>
        ) : (
          <Table>
            <TableHeader>
              <tr>
                <TableHead>{t("payroll.payslip.column.item")}</TableHead>
                <TableHead className="text-right">{t("payroll.payslip.column.base")}</TableHead>
                <TableHead className="text-right">{t("payroll.payslip.column.qty")}</TableHead>
                <TableHead className="text-right">{t("payroll.payslip.column.rate")}</TableHead>
                <TableHead className="text-right">{t("payroll.payslip.column.amount")}</TableHead>
              </tr>
            </TableHeader>
            <TableBody>
              {sections.map(({ section, lines }) => (
                <Fragment key={section}>
                  <tr className="bg-muted/40">
                    <td colSpan={5} className="px-4 py-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                      {translated(`payroll.payslip.section.${section}`, section)}
                    </td>
                  </tr>
                  {lines.map((line) => (
                    <TableRow key={line.line_no}>
                      <TableCell className="py-2">{lineName(line)}</TableCell>
                      <TableCell className="py-2 text-right tabular-nums">{line.base === null ? "" : money.format(line.base)}</TableCell>
                      <TableCell className="py-2 text-right tabular-nums">{line.qty === null ? "" : quantity.format(line.qty)}</TableCell>
                      <TableCell className="py-2 text-right tabular-nums">{line.rate === null ? "" : rate.format(line.rate)}</TableCell>
                      <TableCell className="py-2 text-right font-medium tabular-nums">{money.format(line.amount)}</TableCell>
                    </TableRow>
                  ))}
                </Fragment>
              ))}
            </TableBody>
          </Table>
        )}
      </Card>

      {canEdit && <PayslipEditDialog open={editOpen} onOpenChange={setEditOpen} payslip={payslip} />}
    </div>
  );
}
