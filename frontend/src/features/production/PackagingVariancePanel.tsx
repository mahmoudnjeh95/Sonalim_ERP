import { motion } from "framer-motion";
import { AlertTriangle, Boxes, CheckCircle2, Cpu, HelpCircle, PackageSearch, Scale } from "lucide-react";
import { useI18n } from "../../lib/i18n";
import { cn } from "../../lib/utils";
import { formatQuantity } from "../../lib/units";
import { HelpTooltip } from "../../components/patterns/HelpTooltip";
import { AnimatedGauge } from "../../components/motion/AnimatedGauge";
import type { PackagingVariance } from "./api";
import type { DispositionSummaryRow } from "../qc/api";

const GRAMS_PER_TONNE = 1_000_000;
// Only these take product off the market. Retouche and retour en stock come back
// (qc's get_rejected_quantity_for_of), so they are shown but never deducted.
const DEDUCTED_DISPOSITIONS = new Set(["dechet", "regrind"]);

/**
 * The écart between what a tonnage should have packed and what the line counted.
 *
 * Read-only, always — decision 22. Phase 7 established that quality findings
 * arrive after production is over, so a blocking check here would fire on data
 * that is not in yet and would only teach people to type past it.
 *
 * It leads with the three independent measures of the same output — the scale,
 * the full cartons, the machine counter — side by side in tonnes. Judging the
 * counter alone against the scale hid which of the three was the outlier: a
 * counter 44 % over a scale the cartons agree with is a counter problem, not
 * lost product, and only the three together say so.
 */
export function PackagingVariancePanel({
  variance,
  /** Whether quality's subtraction is included. Never label a gross figure as net. */
  net = false,
  /**
   * This OF's product-component dispositions (déchet, rebroyat, retouche,
   * retour en stock). Purely explanatory: `rejected_packets` already reflects
   * the settled quantity the moment it is dispositioned (decision 21), so
   * this never changes the figures above it — it only says what became of
   * them, which the raw total can't show on its own.
   */
  dispositionSummary,
  className,
}: {
  variance: PackagingVariance;
  net?: boolean;
  dispositionSummary?: DispositionSummaryRow[];
  className?: string;
}) {
  const { t } = useI18n();

  // Decision 25: tonnage is often absent now (always at report scope, and at OF
  // scope until a daily report is validated), so the weight-based figures and
  // machine_carton_variance are shown independently rather than one gating the
  // other. Only when neither exists is there truly nothing to compare.
  const hasWeightEcart = variance.expected_packets !== null;

  // A sac is its own selling unit: the line counts sacs, and there is no carton
  // tier to reconcile against, so every carton figure is left out.
  const isSac = variance.packaging_format === "sac";
  const hasMachineEcart = variance.machine_carton_variance !== null;

  if (!hasWeightEcart && !hasMachineEcart) {
    return (
      <div className={cn("rounded-lg border border-border p-3", className)}>
        <p className="flex items-center gap-1.5 text-sm text-muted-foreground">
          <HelpCircle className="h-4 w-4" />
          {variance.missing.includes("net_weight_grams")
            ? t("production.packagingVariance.noNetWeight")
            : t("production.packagingVariance.noEcartAvailable")}
        </p>
      </div>
    );
  }

  const machineOk = variance.machine_carton_variance === 0;
  const machineShort = (variance.machine_carton_variance ?? 0) < 0;

  // The header colour follows the weight-based ecart when it exists; otherwise
  // it falls back to the machine/carton figure, the one that's actually there.
  const short = hasWeightEcart ? (variance.packet_variance ?? 0) < 0 : machineShort;
  const ok = hasWeightEcart ? variance.within_tolerance === true : machineOk;
  // The weight ecart is only judged against a tolerance the plant configured; with
  // none set the figures are shown as they are, not coloured against a guess.
  const judged = !hasWeightEcart || variance.within_tolerance !== null;
  const tone = !judged ? "neutral" : ok ? "success" : short ? "destructive" : "warning";

  const percent = (ratio: number | null) => (ratio === null ? null : `${ratio > 0 ? "+" : ""}${(ratio * 100).toFixed(2)} %`);
  const ratioLabel = percent(variance.packet_variance_ratio);
  const cartonRatioLabel = percent(variance.carton_variance_ratio);

  const showMeasures =
    hasWeightEcart &&
    !isSac &&
    variance.tonnage !== null &&
    variance.net_weight_grams !== null &&
    variance.packets_per_carton !== null &&
    variance.expected_cartons !== null;

  const disposed = (dispositionSummary ?? []).filter((row) => row.quantity > 0);
  const deducted = disposed.filter((row) => DEDUCTED_DISPOSITIONS.has(row.disposition));
  const returned = disposed.filter((row) => !DEDUCTED_DISPOSITIONS.has(row.disposition));
  const dispositionText = (rows: DispositionSummaryRow[]) =>
    rows
      .map(
        (row) =>
          `${t(`qc.nc.disposition.${row.disposition}` as Parameters<typeof t>[0])} ${formatQuantity(row.quantity)}`,
      )
      .join(" + ");

  return (
    <div
      className={cn(
        "overflow-hidden rounded-xl border",
        tone === "neutral" && "border-border",
        tone === "success" && "border-success/20",
        tone === "destructive" && "border-destructive/30",
        tone === "warning" && "border-warning/30",
        className,
      )}
    >
      <div
        className={cn(
          "flex items-center gap-2 border-b px-4 py-2.5",
          tone === "neutral" && "border-border bg-muted/40",
          tone === "success" && "border-success/20 bg-success-soft",
          tone === "destructive" && "border-destructive/30 bg-destructive-soft",
          tone === "warning" && "border-warning/30 bg-warning-soft",
        )}
      >
        {tone === "neutral" ? (
          <PackageSearch className="h-4 w-4 text-muted-foreground" />
        ) : ok ? (
          <CheckCircle2 className="h-4 w-4 text-success" />
        ) : (
          <AlertTriangle className={cn("h-4 w-4", short ? "text-destructive" : "text-warning")} />
        )}
        <p className="text-xs font-semibold uppercase tracking-wide">
          {net ? t("production.packagingVariance.titleNet") : t("production.packagingVariance.titleGross")}
        </p>
        <HelpTooltip
          text={net ? t("production.packagingVariance.help.net") : t("production.packagingVariance.help.gross")}
        />
      </div>

      {showMeasures && <ThreeMeasures variance={variance} tolerancePercent={variance.tolerance_percent} />}

      <div className="grid grid-cols-2 gap-x-4 gap-y-3 p-4 sm:grid-cols-4">
        {hasWeightEcart ? (
          <>
            <Figure
              label={t("production.packagingVariance.field.tonnage")}
              value={formatQuantity(variance.tonnage, "t")}
            />
            <Figure
              label={t(
                isSac
                  ? "production.packagingVariance.field.expectedSacs"
                  : "production.packagingVariance.field.expectedPackets",
              )}
              value={formatQuantity(variance.expected_packets)}
            />
            <Figure
              label={t(
                isSac
                  ? "production.packagingVariance.field.countedSacs"
                  : "production.packagingVariance.field.countedPackets",
              )}
              value={formatQuantity(variance.counted_packets)}
            />
            <Figure
              label={t("production.packagingVariance.field.packetVariance")}
              value={`${formatQuantity(variance.packet_variance)}${ratioLabel ? ` (${ratioLabel})` : ""}`}
              emphasis={tone === "neutral" ? undefined : tone}
              gauge={
                tone !== "neutral" &&
                variance.packet_variance_ratio !== null &&
                variance.tolerance_percent !== null &&
                variance.tolerance_percent > 0
                  ? {
                      percent: (Math.abs(variance.packet_variance_ratio) * 100 * 100) / variance.tolerance_percent,
                      tone,
                    }
                  : undefined
              }
            />
            {!isSac && variance.expected_cartons !== null && (
              <>
                <Figure
                  label={t("production.packagingVariance.field.expectedCartons")}
                  value={formatQuantity(variance.expected_cartons)}
                />
                <Figure
                  label={t("production.packagingVariance.field.countedCartons")}
                  value={formatQuantity(variance.counted_cartons)}
                  // The carton figures below are all judged on the full cartons,
                  // so the raw tally says how it got there.
                  hint={
                    variance.waste_cartons > 0
                      ? `${t("production.packagingVariance.field.wasteCartonsPrefix")} ${formatQuantity(
                          variance.waste_cartons,
                        )} ${t("production.packagingVariance.field.emptyCartons")} → ${formatQuantity(
                          variance.good_cartons,
                        )} ${t("production.packagingVariance.field.fullCartons")}`
                      : undefined
                  }
                />
                <Figure
                  label={t("production.packagingVariance.field.cartonVariance")}
                  value={`${formatQuantity(variance.carton_variance)}${
                    cartonRatioLabel ? ` (${cartonRatioLabel})` : ""
                  }`}
                  hint={t("production.packagingVariance.field.cartonVarianceHint")}
                />
              </>
            )}
          </>
        ) : (
          <p className="col-span-2 flex items-center gap-1.5 text-xs text-muted-foreground sm:col-span-4">
            <HelpCircle className="h-3.5 w-3.5 shrink-0" />
            {t("production.packagingVariance.tonnageNotTracked")}
          </p>
        )}

        {!hasWeightEcart && (
          <>
            <Figure
              label={t(
                isSac
                  ? "production.packagingVariance.field.countedSacs"
                  : "production.packagingVariance.field.countedPackets",
              )}
              value={formatQuantity(variance.counted_packets)}
            />
            {!isSac && (
              <Figure
                label={t("production.packagingVariance.field.countedCartons")}
                value={formatQuantity(variance.counted_cartons)}
              />
            )}
          </>
        )}
        {hasMachineEcart && (
          <Figure
            label={t("production.packagingVariance.field.machineCartonVariance")}
            value={formatQuantity(variance.machine_carton_variance)}
            emphasis={machineOk ? "success" : machineShort ? "destructive" : "warning"}
            hint={
              machineOk
                ? t("production.packagingVariance.field.machineAgrees")
                : `${t(
                    machineShort
                      ? "production.packagingVariance.field.machineFewerPrefix"
                      : "production.packagingVariance.field.machineMorePrefix",
                  )} ${formatQuantity(Math.abs(variance.machine_carton_variance ?? 0))} ${t(
                    machineShort
                      ? "production.packagingVariance.field.machineFewerSuffix"
                      : "production.packagingVariance.field.machineMoreSuffix",
                  )} ${formatQuantity(variance.good_cartons)} ${t("production.packagingVariance.field.fullCartons")}`
            }
          />
        )}
      </div>

      {net && (variance.rejected_packets > 0 || disposed.length > 0) && (
        <div className="flex flex-col gap-1 border-t border-border/60 px-4 py-3 text-sm sm:flex-row sm:items-baseline sm:gap-4">
          <p className="text-xs text-muted-foreground">{t("production.packagingVariance.field.rejected")}</p>
          <p className="font-medium tabular-nums">
            {formatQuantity(variance.rejected_packets)}
            <span className="ml-1.5 text-xs font-normal text-muted-foreground">
              {[
                deducted.length > 0 ? `= ${dispositionText(deducted)}` : null,
                variance.undecided_packets > 0
                  ? `+ ${formatQuantity(variance.undecided_packets)} ${t(
                      "production.packagingVariance.field.undecidedSuffix",
                    )}`
                  : null,
              ]
                .filter(Boolean)
                .join(" ")}
            </span>
          </p>
          {returned.length > 0 && (
            <p className="text-xs text-muted-foreground sm:ml-auto">
              {dispositionText(returned)} · {t("production.packagingVariance.field.returnedNotDeducted")}
            </p>
          )}
        </div>
      )}

      <p className="flex items-center gap-1.5 border-t border-border/60 bg-muted/20 px-4 py-2 text-xs text-muted-foreground">
        <PackageSearch className="h-3.5 w-3.5 shrink-0" />
        {[
          `${t(
            isSac ? "production.packagingVariance.basis.sacWeight" : "production.packagingVariance.basis.weight",
          )} ${formatQuantity(variance.net_weight_grams, "g")}`,
          ...(isSac
            ? []
            : [
                `${t("production.packagingVariance.basis.perCarton")} ${
                  variance.packets_per_carton === null
                    ? t("production.packagingVariance.noCarton")
                    : formatQuantity(variance.packets_per_carton)
                }`,
              ]),
          variance.tolerance_percent !== null
            ? `${t("production.packagingVariance.basis.tolerance")} ${variance.tolerance_percent} %`
            : t("production.packagingVariance.basis.noTolerance"),
        ].join(" · ")}
      </p>
    </div>
  );
}

/**
 * The scale, the full cartons and the machine counter, each restated in tonnes
 * with the product's own net weight, on one shared axis with the scale marked.
 * All three are recorded figures; nothing here is a target.
 */
function ThreeMeasures({ variance, tolerancePercent }: { variance: PackagingVariance; tolerancePercent: number | null }) {
  const { t } = useI18n();
  const grams = variance.net_weight_grams!;
  const perCarton = variance.packets_per_carton!;
  const scale = variance.tonnage!;
  const cartons = (variance.good_cartons * perCarton * grams) / GRAMS_PER_TONNE;
  const counter = (variance.good_packets * grams) / GRAMS_PER_TONNE;
  const axisMax = Math.max(scale, cartons, counter) * 1.08 || 1;
  const width = (value: number) => `${Math.max(0, (value / axisMax) * 100)}%`;

  const rows = [
    {
      key: "scale",
      icon: <Scale className="h-4 w-4" />,
      label: t("production.packagingVariance.measures.scale"),
      detail: t("production.packagingVariance.measures.scaleDetail"),
      tonnes: scale,
      ratio: null as number | null,
      judged: false,
    },
    {
      key: "cartons",
      icon: <Boxes className="h-4 w-4" />,
      label: t("production.packagingVariance.measures.cartons"),
      detail: `${formatQuantity(variance.good_cartons)} × ${formatQuantity(perCarton)} × ${formatQuantity(grams, "g")}`,
      tonnes: cartons,
      ratio: variance.carton_variance_ratio,
      // Cartons round down from packets, so the tolerance is never judged on them.
      judged: false,
    },
    {
      key: "counter",
      icon: <Cpu className="h-4 w-4" />,
      label: t("production.packagingVariance.measures.counter"),
      detail: `${formatQuantity(variance.good_packets)} × ${formatQuantity(grams, "g")}${
        variance.rejected_packets > 0 ? ` · ${t("production.packagingVariance.measures.netOfRefusals")}` : ""
      }`,
      tonnes: counter,
      ratio: variance.packet_variance_ratio,
      judged: true,
    },
  ];

  return (
    <div className="space-y-3 border-b border-border/60 px-4 py-4">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <p className="text-sm font-semibold">{t("production.packagingVariance.measures.title")}</p>
        <p className="text-xs text-muted-foreground">{t("production.packagingVariance.measures.hint")}</p>
      </div>
      <div className="relative space-y-3">
        {rows.map((row, index) => {
          const outside =
            row.judged && row.ratio !== null && tolerancePercent !== null
              ? Math.abs(row.ratio) * 100 > tolerancePercent
              : null;
          return (
            <div key={row.key} className="grid grid-cols-[minmax(0,15rem)_1fr_auto] items-center gap-3">
              <div className="flex min-w-0 items-center gap-2">
                <span
                  className={cn(
                    "flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border",
                    row.key === "scale"
                      ? "border-foreground/15 bg-foreground/5 text-foreground"
                      : "border-primary/15 bg-primary/10 text-primary",
                  )}
                >
                  {row.icon}
                </span>
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">{row.label}</p>
                  <p className="truncate text-xs tabular-nums text-muted-foreground" title={row.detail}>
                    {row.detail}
                  </p>
                </div>
              </div>
              <div className="relative h-3 rounded-full bg-muted">
                <motion.div
                  className={cn(
                    "h-full rounded-full",
                    row.key === "scale" ? "bg-foreground/60" : "bg-primary/70",
                  )}
                  initial={{ width: 0 }}
                  animate={{ width: width(row.tonnes) }}
                  transition={{ duration: 0.5, delay: index * 0.08, ease: "easeOut" }}
                />
                {/* The scale's own position, carried across every bar. */}
                <span
                  aria-hidden
                  className="absolute -inset-y-1 w-0.5 rounded-full bg-foreground"
                  style={{ left: width(scale) }}
                />
              </div>
              <div className="flex min-w-[9.5rem] items-center justify-end gap-2">
                <span className="text-sm font-semibold tabular-nums">{formatQuantity(row.tonnes, "t")}</span>
                {row.ratio === null ? (
                  <span className="rounded-full border border-border px-2 py-0.5 text-[11px] text-muted-foreground">
                    {t("production.packagingVariance.measures.reference")}
                  </span>
                ) : (
                  <span
                    className={cn(
                      "rounded-full px-2 py-0.5 text-[11px] font-semibold tabular-nums",
                      outside === null && "bg-muted text-foreground",
                      outside === false && "bg-success-soft text-success",
                      outside === true && "bg-warning-soft text-warning",
                    )}
                  >
                    {`${row.ratio > 0 ? "+" : ""}${(row.ratio * 100).toFixed(1)} %`}
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Figure({
  label,
  value,
  emphasis,
  hint,
  gauge,
}: {
  label: string;
  value: string;
  emphasis?: "success" | "warning" | "destructive";
  hint?: string;
  /** Share of the tolerance band this variance has used up. */
  gauge?: { percent: number; tone: "success" | "warning" | "destructive" };
}) {
  return (
    <div>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p
        className={cn(
          "text-sm font-semibold tabular-nums",
          emphasis === "success" && "text-success",
          emphasis === "warning" && "text-warning",
          emphasis === "destructive" && "text-destructive",
        )}
      >
        {value}
      </p>
      {gauge && <AnimatedGauge percent={gauge.percent} tone={gauge.tone} className="mt-1" />}
      {hint && <p className="mt-0.5 text-xs leading-snug text-muted-foreground">{hint}</p>}
    </div>
  );
}
