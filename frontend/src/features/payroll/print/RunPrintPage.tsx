import { useParams } from "react-router-dom";
import { Receipt, Wallet } from "lucide-react";
import { AppLoader } from "../../../components/patterns/AppLoader";
import { EmptyState } from "../../../components/patterns/EmptyState";
import { useAuth } from "../../../lib/auth";
import { useI18n, type TranslationKey } from "../../../lib/i18n";
import { useRuleSet, useRunPrint } from "../api";
import { formatPeriod } from "../format";
import { PayslipDocument } from "./PayslipDocument";
import { PrintShell } from "../../../components/patterns/PrintShell";

/** /payroll/runs/:runId/print — every payslip of the run, one per printed page. */
export function RunPrintPage() {
  const { runId } = useParams<{ runId: string }>();
  const { t } = useI18n();
  const { hasPermission } = useAuth();
  const { data: document, isLoading, isError, error } = useRunPrint(runId);

  // A run's payslips come from one calculation, so one lookup names the draft rule set for all of them.
  const draftPayslip = document?.payslips.find((payslip) => payslip.rule_set_status === "draft");
  const draftId = draftPayslip && hasPermission("payroll.view_rules") ? (draftPayslip.snapshot as { rule_set?: { id?: string } | null }).rule_set?.id : undefined;
  const { data: draftRuleSet } = useRuleSet(draftId);

  if (isLoading) return <AppLoader label={t("payroll.common.loading")} fullScreen />;
  if (isError || !document) {
    return (
      <EmptyState
        icon={<Wallet className="h-5 w-5" />}
        title={t("payroll.print.notFound")}
        description={error instanceof Error ? error.message : t("payroll.print.notFoundDescription")}
      />
    );
  }

  const { run } = document;
  const subtitle = (
    <>
      <p>
        {formatPeriod(run.period)} · {t(`payroll.runs.type.${run.run_type}` as TranslationKey)}
      </p>
      {run.label && <p>{run.label}</p>}
      <p>
        {t("payroll.print.status")} {t(`payroll.status.run.${run.status}` as TranslationKey)}
      </p>
    </>
  );

  return (
    <PrintShell title={t("payroll.print.runTitle")} subtitle={subtitle} company={document.company} backTo={`/payroll/runs/${run.id}`}>
      {document.payslips.length === 0 ? (
        <EmptyState icon={<Receipt className="h-5 w-5" />} title={t("payroll.print.run.empty.title")} description={t("payroll.print.run.empty.description")} />
      ) : (
        <div className="space-y-8 print:space-y-0">
          {document.payslips.map((payslip, index) => (
            <div
              key={payslip.id}
              className={index < document.payslips.length - 1 ? "border-b border-dashed border-neutral-300 pb-8 print:break-after-page print:border-0 print:pb-0" : ""}
            >
              <PayslipDocument payslip={payslip} draftRuleSetName={draftRuleSet?.name} />
            </div>
          ))}
        </div>
      )}
    </PrintShell>
  );
}
