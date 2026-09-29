import { Link } from "react-router-dom";
import { AlertTriangle } from "lucide-react";
import { useI18n } from "../../lib/i18n";

/**
 * Shown wherever a run or payslip was computed from a draft rule set (spec: "a banner on every
 * payslip computed from a draft rule set"). Renders nothing for a confirmed or missing rule set.
 * The link to Rules is left out when the caller only knows the status, not the rule set's id.
 */
export function DraftRuleSetBanner({ ruleSet }: { ruleSet: { id: string; name: string; status: string } | null | undefined }) {
  const { t } = useI18n();
  if (!ruleSet || ruleSet.status !== "draft") return null;
  // t() has no interpolation: the rule set's name is the one dynamic fragment, swapped in here.
  const message = ruleSet.name ? t("payroll.rules.draftBanner").replace("{name}", ruleSet.name) : t("payroll.rules.draftBanner.unnamed");
  return (
    <div role="status" className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border border-warning/30 bg-warning-soft px-3 py-2 text-sm">
      <AlertTriangle className="h-4 w-4 shrink-0 text-warning" aria-hidden />
      <span className="min-w-0 flex-1">{message}</span>
      {ruleSet.id && (
        <Link to={`/payroll/rules?ruleSet=${encodeURIComponent(ruleSet.id)}`} className="shrink-0 font-medium text-warning underline underline-offset-2 print:hidden">
          {t("payroll.rules.draftBanner.link")}
        </Link>
      )}
    </div>
  );
}
