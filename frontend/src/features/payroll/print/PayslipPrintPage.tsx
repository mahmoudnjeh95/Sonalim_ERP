import { useParams } from "react-router-dom";
import { Receipt } from "lucide-react";
import { AppLoader } from "../../../components/patterns/AppLoader";
import { EmptyState } from "../../../components/patterns/EmptyState";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { useCertificate, usePayslip, useRuleSet } from "../api";
import { formatPeriod } from "../format";
import { PayslipDocument } from "./PayslipDocument";
import { PrintShell } from "./PrintShell";
import { WorkCertificate } from "./WorkCertificate";

/** /payroll/payslips/:payslipId/print — one payslip, plus the work certificate on a final settlement. */
export function PayslipPrintPage() {
  const { payslipId } = useParams<{ payslipId: string }>();
  const { t } = useI18n();
  const { hasPermission } = useAuth();
  const { data: payslip, isLoading, isError, error } = usePayslip(payslipId);

  const snapshot = payslip?.snapshot as { settlement?: unknown; rule_set?: { id?: string } | null } | undefined;
  const { data: certificate } = useCertificate(snapshot?.settlement ? payslipId : undefined);
  // The draft rule set is named for Rules readers; others still see the (unnamed) draft banner.
  const draftId = payslip?.rule_set_status === "draft" && hasPermission("payroll.view_rules") ? (snapshot?.rule_set?.id ?? undefined) : undefined;
  const { data: draftRuleSet } = useRuleSet(draftId);

  if (isLoading) return <AppLoader label={t("payroll.common.loading")} fullScreen />;
  if (isError || !payslip) {
    return (
      <EmptyState
        icon={<Receipt className="h-5 w-5" />}
        title={t("payroll.print.notFound")}
        description={error instanceof Error ? error.message : t("payroll.print.notFoundDescription")}
      />
    );
  }

  return (
    <PrintShell
      title={t("payroll.print.payslipTitle")}
      subtitle={formatPeriod(payslip.period)}
      company={payslip.company}
      backTo={`/payroll/payslips/${payslip.id}`}
    >
      <PayslipDocument payslip={payslip} draftRuleSetName={draftRuleSet?.name} />
      {certificate && (
        <div className="border-t border-neutral-300 pt-6 print:break-before-page print:border-0 print:pt-0">
          <WorkCertificate certificate={certificate} />
        </div>
      )}
    </PrintShell>
  );
}
