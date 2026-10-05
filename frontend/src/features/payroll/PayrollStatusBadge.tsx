import { Badge } from "../../components/ui/badge";
import { useI18n, type TranslationKey } from "../../lib/i18n";

/** Whose status vocabulary: runs, payout batches, advances, loans (each its own i18n namespace). */
export type PayrollStatusDomain = "run" | "payslipBatch" | "advance" | "loan";

const VARIANT: Record<string, "outline" | "default" | "success" | "destructive"> = {
  draft: "outline",
  requested: "outline",
  generated: "outline",
  calculated: "default",
  approved: "default",
  active: "default",
  paid: "success",
  confirmed: "success",
  reversed: "destructive",
  cancelled: "destructive",
};

export function PayrollStatusBadge({ domain, status }: { domain: PayrollStatusDomain; status: string }) {
  const { t } = useI18n();
  const key = `payroll.status.${domain}.${status}` as TranslationKey;
  return <Badge variant={VARIANT[status] ?? "outline"}>{t(key)}</Badge>;
}
