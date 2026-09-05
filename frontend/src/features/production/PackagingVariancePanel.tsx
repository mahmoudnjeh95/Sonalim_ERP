import { AlertTriangle, CheckCircle2, HelpCircle, PackageSearch } from "lucide-react";
import { useI18n } from "../../lib/i18n";
import { cn } from "../../lib/utils";
import { formatQuantity } from "../../lib/units";
import { HelpTooltip } from "../../components/patterns/HelpTooltip";
import type { PackagingVariance } from "./api";

/**
 * The écart between what a tonnage should have packed and what the line counted.
 *
 * Read-only, always — decision 22. Phase 7 established that quality findings
 * arrive after production is over, so a blocking check here would fire on data
 * that is not in yet and would only teach people to type past it.
 *
 * The panel leads with the comparison rather than the verdict: expected against
 * counted, then the gap. A supervisor deciding whether a shift lost a pallet or
 * mistyped a tonnage needs the two figures side by side, and a single red number
 * would hide exactly the information that distinguishes those two cases.
 */
export function PackagingVariancePanel({
  variance,
  /** Whether quality's subtraction is included. Never label a gross figure as net. */
  net = false,
  className,
}: {
  variance: PackagingVariance;
  net?: boolean;
  className?: string;
}) {
  const { t } = useI18n();

  // Without a net weight there is nothing to compare against. Saying so beats
  // rendering dashes that read as a broken screen.
  if (variance.expected_packets === null) {
    return (
      <div className={cn("rounded-lg border border-border p-3", className)}>
        <p className="flex items-center gap-1.5 text-sm text-muted-foreground">
          <HelpCircle className="h-4 w-4" />
          {t("production.packagingVariance.noNetWeight")}
        </p>
      </div>
    );
  }

  const short = (variance.packet_variance ?? 0) < 0;
  const ok = variance.within_tolerance === true;

  const ratioLabel =
    variance.packet_variance_ratio === null
      ? null
      : `${(variance.packet_variance_ratio * 100).toFixed(2)} %`;

  return (
    <div
      className={cn(
        "overflow-hidden rounded-lg border",
        ok ? "border-success/20" : short ? "border-destructive/30" : "border-warning/30",
        className,
      )}
    >
      <div
        className={cn(
          "flex items-center gap-2 border-b px-3 py-2",
          ok
            ? "border-success/20 bg-success-soft"
            : short
              ? "border-destructive/30 bg-destructive-soft"
              : "border-warning/30 bg-warning-soft",
        )}
      >
        {ok ? (
          <CheckCircle2 className="h-4 w-4 text-success" />
        ) : (
          <AlertTriangle className={cn("h-4 w-4", short ? "text-destructive" : "text-warning")} />
        )}
        <p className="text-xs font-semibold uppercase tracking-wide">
          {net ? t("production.packagingVariance.titleNet") : t("production.packagingVariance.titleGross")}
        </p>
        <HelpTooltip
          text={
            net
              ? t("production.packagingVariance.help.net")
              : t("production.packagingVariance.help.gross")
          }
        />
      </div>

      <div className="grid grid-cols-2 gap-x-4 gap-y-2 p-3 sm:grid-cols-4">
        <Figure
          label={t("production.packagingVariance.field.tonnage")}
          value={formatQuantity(variance.tonnage, "t")}
        />
        <Figure
          label={t("production.packagingVariance.field.expectedPackets")}
          value={formatQuantity(variance.expected_packets)}
        />
        <Figure
          label={t("production.packagingVariance.field.countedPackets")}
          value={formatQuantity(variance.counted_packets)}
        />
        <Figure
          label={t("production.packagingVariance.field.packetVariance")}
          value={`${formatQuantity(variance.packet_variance)}${ratioLabel ? ` (${ratioLabel})` : ""}`}
          emphasis={ok ? "success" : short ? "destructive" : "warning"}
        />

        {variance.expected_cartons !== null && (
          <>
            <Figure
              label={t("production.packagingVariance.field.expectedCartons")}
              value={formatQuantity(variance.expected_cartons)}
            />
            <Figure
              label={t("production.packagingVariance.field.countedCartons")}
              value={formatQuantity(variance.counted_cartons)}
            />
            <Figure
              label={t("production.packagingVariance.field.cartonVariance")}
              value={formatQuantity(variance.carton_variance)}
            />
          </>
        )}

        {net && (
          <Figure
            label={t("production.packagingVariance.field.rejected")}
            value={formatQuantity(variance.rejected_packets)}
            // An open case is not a loss yet, and the panel must not imply it is.
            hint={
              variance.undecided_packets > 0
                ? `${t("production.packagingVariance.field.undecidedPrefix")} ${formatQuantity(
                    variance.undecided_packets,
                  )} ${t("production.packagingVariance.field.undecidedSuffix")}`
                : undefined
            }
          />
        )}
      </div>

      <p className="flex items-center gap-1.5 border-t border-border/60 px-3 py-2 text-xs text-muted-foreground">
        <PackageSearch className="h-3.5 w-3.5 shrink-0" />
        {[
          `${t("production.packagingVariance.basis.weight")} ${formatQuantity(variance.net_weight_grams, "g")}`,
          `${t("production.packagingVariance.basis.perCarton")} ${
            variance.packets_per_carton === null
              ? t("production.packagingVariance.noCarton")
              : formatQuantity(variance.packets_per_carton)
          }`,
          `${t("production.packagingVariance.basis.tolerance")} ${variance.tolerance_percent} %`,
        ].join(" · ")}
      </p>
    </div>
  );
}

function Figure({
  label,
  value,
  emphasis,
  hint,
}: {
  label: string;
  value: string;
  emphasis?: "success" | "warning" | "destructive";
  hint?: string;
}) {
  return (
    <div>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p
        className={cn(
          "text-sm font-medium tabular-nums",
          emphasis === "success" && "text-success",
          emphasis === "warning" && "text-warning",
          emphasis === "destructive" && "text-destructive",
        )}
      >
        {value}
      </p>
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}
