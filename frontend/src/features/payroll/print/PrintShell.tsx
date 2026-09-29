import type { ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowLeft, Printer } from "lucide-react";
import { Button } from "../../../components/ui/button";
import { useI18n } from "../../../lib/i18n";
import type { CompanyHeader } from "../api";

/**
 * The global print rule (index.css) already hides the sidebar and header. What it does not undo is
 * the app shell's fixed-height scroll box (`h-screen overflow-hidden` around a scrolling <main>),
 * which would clip a printout to its first page. Mounted only while a print page is on screen.
 */
const PRINT_CSS = `
@page { margin: 12mm; }
@media print {
  html, body, #root { height: auto !important; overflow: visible !important; }
  div:has(> main) { display: block !important; height: auto !important; overflow: visible !important; }
  main { overflow: visible !important; }
}
`;

/** Paper-coloured sheet on screen, the page itself on paper. Explicit neutral colours so it reads the same in both. */
export const PRINT_TABLE = "w-full border-collapse text-xs tabular-nums";
export const PRINT_TH = "border-b border-neutral-400 px-2 py-1.5 text-left font-semibold";
export const PRINT_TD = "border-b border-neutral-200 px-2 py-1 align-top";

/** "2026-09-30" -> "30 septembre 2026" / "September 30, 2026"; null -> "—". Read as a calendar day, not a UTC instant. */
export function formatDay(day: string | null | undefined, locale: string): string {
  if (!day) return "—";
  const [year, month, date] = day.slice(0, 10).split("-").map(Number);
  if (!year || !month || !date) return day;
  return new Intl.DateTimeFormat(locale, { dateStyle: "long" }).format(new Date(year, month - 1, date));
}

export function PrintShell({
  title,
  subtitle,
  company,
  backTo,
  children,
}: {
  title: string;
  /** Period, run, batch… — what this document is about. */
  subtitle?: ReactNode;
  /** The employer block from the backend response; null when the endpoint does not serve one (declarations). */
  company: CompanyHeader | null;
  /** Where "Back" goes when the page was opened directly (no in-app history to return to). */
  backTo: string;
  children: ReactNode;
}) {
  const { t } = useI18n();
  const navigate = useNavigate();

  const back = () => {
    const index = (window.history.state as { idx?: number } | null)?.idx ?? 0;
    if (index > 0) navigate(-1);
    else navigate(backTo);
  };

  return (
    <div className="space-y-4 print:space-y-0">
      <style>{PRINT_CSS}</style>
      <div className="print-hidden flex flex-wrap items-center justify-between gap-2">
        <Button variant="ghost" size="sm" onClick={back}>
          <ArrowLeft className="h-4 w-4" />
          {t("payroll.print.back")}
        </Button>
        <Button onClick={() => window.print()}>
          <Printer className="h-4 w-4" />
          {t("payroll.print.button")}
        </Button>
      </div>
      <div className="mx-auto max-w-4xl space-y-5 rounded-lg border border-neutral-200 bg-white p-8 text-neutral-900 print:max-w-none print:rounded-none print:border-0 print:p-0 print:text-black">
        <div className="flex items-start justify-between gap-6 border-b border-neutral-400 pb-3">
          <div className="min-w-0">
            {company && (
              <>
                <p className="text-base font-semibold">{company.name ?? "—"}</p>
                {company.address && <p className="whitespace-pre-line text-xs text-neutral-600">{company.address}</p>}
                {company.employer_inps_no && (
                  <p className="text-xs text-neutral-600">
                    {t("payroll.print.employerInps")} {company.employer_inps_no}
                  </p>
                )}
                {company.employer_tax_id && (
                  <p className="text-xs text-neutral-600">
                    {t("payroll.print.employerTaxId")} {company.employer_tax_id}
                  </p>
                )}
              </>
            )}
          </div>
          <div className="shrink-0 text-right">
            <p className="text-lg font-semibold uppercase tracking-wide">{title}</p>
            {subtitle && <div className="text-xs text-neutral-600">{subtitle}</div>}
          </div>
        </div>
        {children}
      </div>
    </div>
  );
}
