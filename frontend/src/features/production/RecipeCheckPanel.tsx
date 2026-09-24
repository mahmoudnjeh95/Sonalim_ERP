import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Beaker, CheckCircle2 } from "lucide-react";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import { cn } from "../../lib/utils";
import { Badge } from "../../components/ui/badge";
import { getWorkOrderRecipeCheck, type RecipeFinding } from "./api";
import { AppLoader } from "../../components/patterns/AppLoader";

/**
 * What went into the mix, against the formula it was meant to follow.
 *
 * Advisory only, and the panel says so. The plant's rule is warn-never-block: a
 * line that has already run cannot be un-run by refusing its report, so nothing
 * here gates anything. It exists so a supervisor sees the drift in time to
 * change the next batch.
 */
export function RecipeCheckPanel({
  workOrderId,
  products,
  className,
}: {
  workOrderId: string;
  products: { id: string; name: string }[];
  className?: string;
}) {
  const { session } = useAuth();
  const { t } = useI18n();

  const { data: check, isLoading } = useQuery({
    queryKey: ["production", "recipe-check", workOrderId],
    queryFn: () => getWorkOrderRecipeCheck(session!.token, workOrderId),
  });

  if (isLoading) return <AppLoader size={72} className={cn("py-2", className)} />;
  if (!check) return null;

  const nameOf = (productId: string | null) =>
    (productId && products.find((p) => p.id === productId)?.name) || productId || "—";

  // An OF with no recipe was not checked and passed — it was never checked at
  // all. Showing it as a green tick would be a claim nobody made.
  if (!check.has_recipe) {
    return (
      <div className={cn("rounded-lg border border-border p-3", className)}>
        <p className="flex items-center gap-1.5 text-sm text-muted-foreground">
          <Beaker className="h-4 w-4" />
          {t("production.recipeCheck.noRecipe")}
        </p>
      </div>
    );
  }

  if (check.findings.length === 0) {
    return (
      <div className={cn("rounded-lg border border-success/20 bg-success-soft p-3", className)}>
        <p className="flex items-center gap-1.5 text-sm text-success">
          <CheckCircle2 className="h-4 w-4" />
          {check.mix_total > 0
            ? t("production.recipeCheck.withinLimits")
            : t("production.recipeCheck.nothingPouredYet")}
        </p>
      </div>
    );
  }

  return (
    <div className={cn("overflow-hidden rounded-lg border border-warning/30", className)}>
      <div className="flex items-center gap-2 border-b border-warning/30 bg-warning-soft px-3 py-2">
        <AlertTriangle className="h-4 w-4 text-warning" />
        <p className="text-sm font-medium text-warning">{t("production.recipeCheck.title")}</p>
        <Badge variant="outline" className="ml-auto">
          {t("production.recipeCheck.advisory")}
        </Badge>
      </div>
      <ul className="divide-y divide-border">
        {check.findings.map((finding, index) => (
          <li key={`${finding.code}:${finding.component_product_id ?? index}`} className="p-3">
            <div className="flex flex-wrap items-baseline gap-2">
              <span className="text-sm font-medium">{nameOf(finding.component_product_id)}</span>
              <Badge variant={finding.severity === "hard" ? "destructive" : "outline"}>
                {t(
                  finding.severity === "hard"
                    ? "production.recipeCheck.severity.hard"
                    : "production.recipeCheck.severity.soft",
                )}
              </Badge>
            </div>
            <p className="mt-0.5 text-sm text-muted-foreground">
              {t(FINDING_LABEL_KEYS[finding.code] ?? "production.recipeCheck.finding.unknown")}
              {describeShare(finding)}
            </p>
          </li>
        ))}
      </ul>
    </div>
  );
}

const FINDING_LABEL_KEYS: Record<string, Parameters<ReturnType<typeof useI18n>["t"]>[0]> = {
  BELOW_MINIMUM: "production.recipeCheck.finding.belowMinimum",
  ABOVE_MAXIMUM: "production.recipeCheck.finding.aboveMaximum",
  COMPONENT_NOT_POURED: "production.recipeCheck.finding.notPoured",
  NOT_IN_RECIPE: "production.recipeCheck.finding.notInRecipe",
  NEGATIVE_QUANTITY: "production.recipeCheck.finding.negative",
};

/** " — 30.0% (5–15%)". Omitted when the check withheld the numbers. */
function describeShare(finding: RecipeFinding): string {
  if (finding.actual_percentage === null) return "";
  const actual = `${finding.actual_percentage.toFixed(1)}%`;
  if (finding.min_percentage === null || finding.max_percentage === null) return ` — ${actual}`;
  return ` — ${actual} (${finding.min_percentage}–${finding.max_percentage}%)`;
}
