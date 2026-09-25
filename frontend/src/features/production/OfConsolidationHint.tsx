import { useQuery } from "@tanstack/react-query";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import { formatQuantity } from "../../lib/units";
import { getWorkOrderConsolidation } from "./api";

/**
 * What an operator filling a daily or conditionnement report should see the
 * moment they pick which OF it's about, before typing anything else -- the
 * same hint-panel pattern QC already uses when picking which conditionnement
 * run to inspect (see QualityReportsTab), backed by data the OF consolidation
 * endpoint already computes live for any OF regardless of status.
 */
export function OfConsolidationHint({ workOrderId }: { workOrderId: string | undefined }) {
  const { session } = useAuth();
  const token = session!.token;
  const { t } = useI18n();

  const { data: consolidation } = useQuery({
    queryKey: ["production", "workOrderConsolidation", workOrderId],
    queryFn: () => getWorkOrderConsolidation(token, workOrderId!),
    enabled: !!workOrderId,
  });

  if (!consolidation) return null;

  return (
    <div className="rounded-md border border-border bg-muted/30 p-3">
      <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {t("production.hint.title")}
      </p>
      <div className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-3">
        <div>
          <span className="text-muted-foreground">{t("production.hint.producedSoFar")}: </span>
          {formatQuantity(consolidation.produced_quantity, "t")}
        </div>
        <div>
          {/* Not produced / planned: the plant runs an order past its plan, so that
              share reads 600 % on a healthy order. Yield is the figure that means something. */}
          <span className="text-muted-foreground">{t("production.workOrders.column.yield")}: </span>
          {consolidation.yield_ratio !== null ? `${(consolidation.yield_ratio * 100).toFixed(1)}%` : "—"}
        </div>
        <div>
          <span className="text-muted-foreground">{t("production.hint.semolinaSoFar")}: </span>
          {formatQuantity(consolidation.raw_material.semolina_quantity, "t")}
        </div>
        <div>
          <span className="text-muted-foreground">{t("production.hint.reportsFiled")}: </span>
          {consolidation.report_counts.daily} / {consolidation.report_counts.conditionnement}
        </div>
      </div>
    </div>
  );
}
