import { useQuery } from "@tanstack/react-query";
import { currentLocale, useI18n, type TranslationKey } from "../../lib/i18n";
import { cn } from "../../lib/utils";
import { formatQuantity, productUnit } from "../../lib/units";
import { MOVE_TYPE_VARIANT, signedMoveQuantity, useMoveTypeLabels } from "../../lib/stockMoveTypes";
import { listStockMoves } from "../warehouse/api";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../components/ui/dialog";
import { Badge } from "../../components/ui/badge";
import { Skeleton } from "../../components/ui/skeleton";
import { StatusBadge } from "../../components/patterns/StatusBadge";
import type {
  ConditionnementReportDetail,
  DailyReportDetail,
  ProductionReport,
  ProductionReportWithDetail,
} from "./api";
import { productionSteps, type ProductionStepId, type StageState, type StageStatus } from "./productionSteps";

interface Metric {
  /** Groups figures that can be summed across reports. */
  key: string;
  label: string;
  value: number;
  unit: string | null;
}

interface Props {
  token: string;
  orderId: string;
  /** The OF's finished product — what every packing report on it packs. */
  orderProduct: { id: string; name: string; packets_per_carton: number | null } | null;
  stepId: ProductionStepId | null;
  state: StageState | null;
  details: Map<string, ProductionReportWithDetail["detail"]>;
  loading: boolean;
  products: { id: string; name: string; uom_id: string }[];
  uoms: { id: string; code: string; symbol?: string | null }[];
  locations: { id: string; name: string }[];
  /** The OF's own product unit — what packets are counted in. */
  packetUnit: string | null;
  onOpenReport: (report: ProductionReport) => void;
  onClose: () => void;
}

const RULE_KEY = {
  melange: "production.flow.rule.melange",
  petrissage: "production.flow.rule.petrissage",
  extrusion: "production.flow.rule.extrusion",
  conditionnement: "production.flow.rule.conditionnement",
  stockage: "production.flow.rule.stockage",
} as const satisfies Record<ProductionStepId, TranslationKey>;

const STATUS_KEY = {
  empty: "production.flow.status.empty",
  pending: "production.flow.status.pending",
  done: "production.flow.status.done",
} as const satisfies Record<StageStatus, TranslationKey>;

const STATUS_DOT: Record<StageStatus, string> = {
  empty: "bg-muted-foreground/40",
  pending: "bg-primary",
  done: "bg-success",
};

export function StageDetailsDialog({
  token,
  orderId,
  orderProduct,
  stepId,
  state,
  details,
  loading,
  products,
  uoms,
  locations,
  packetUnit,
  onOpenReport,
  onClose,
}: Props) {
  const { t } = useI18n();
  const step = productionSteps.find((entry) => entry.id === stepId);
  const status: StageStatus = loading ? "empty" : (state?.status ?? "empty");

  const moveLabels = useMoveTypeLabels();
  // A product with no carton line is sold by the sac, and the line counts sacs
  // where a carton product counts packets.
  const hasCartonTier = (orderProduct?.packets_per_carton ?? 0) > 0;
  const countLabel = t(
    hasCartonTier ? "production.conditionnement.field.packetsCounted" : "production.conditionnement.field.sacsCounted",
  );

  // The stock the validated reports actually posted. Only read when the Storage
  // popup is open — a move is the proof that a report reached the store.
  const {
    data: stockMoves = [],
    isLoading: movesLoading,
    isError: movesError,
  } = useQuery({
    queryKey: ["warehouse", "stock-moves", "production", orderProduct?.id, orderId],
    queryFn: () => listStockMoves(token, { product_id: orderProduct!.id, move_type: "production", limit: 5000 }),
    enabled: stepId === "stockage" && Boolean(orderProduct),
  });
  const movesFor = (reportId: string) =>
    stockMoves
      .filter((move) => move.of_id === orderId && move.reference.startsWith(`production_report:${reportId}`))
      .sort((a, b) => a.created_at.localeCompare(b.created_at));
  const locationName = (id: string) => locations.find((location) => location.id === id)?.name ?? "—";

  const productName = (id: string | null) =>
    (id && products.find((p) => p.id === id)?.name) || t("production.waste.unknownItem");

  // What a report contributes to this stage — only the figures the stage
  // lights up on, each in its own unit.
  function metricsFor(report: ProductionReport): Metric[] {
    const detail = details.get(report.id);
    if (!detail || !stepId) return [];

    if (report.report_type === "daily") {
      const daily = detail as DailyReportDetail;
      // The finished product is weighed in the semoule's unit, the same
      // convention the daily report's own figures use.
      const weighedUnit = productUnit(daily.semolina_lines?.[0]?.product_id, products, uoms);
      if (stepId === "melange") {
        return (daily.semolina_lines ?? [])
          .filter((line) => line.quantity > 0)
          .map((line) => ({
            key: "semolina",
            label: productName(line.product_id),
            value: line.quantity,
            unit: productUnit(line.product_id, products, uoms),
          }));
      }
      return [
        {
          key: "finished",
          label: t("production.reports.field.finishedProduct"),
          value: daily.finished_product_quantity,
          unit: weighedUnit,
        },
      ];
    }

    const packing = detail as ConditionnementReportDetail;
    const packets: Metric = { key: "packets", label: countLabel, value: packing.packets_counted, unit: packetUnit };
    // Only closed cartons that held product count, the same net figure the
    // stock posting is worked from. A sac product has no carton line, so a
    // carton figure on its report is not a count of anything.
    const cartons: Metric[] =
      hasCartonTier && packing.carton_quantity > 0
        ? [
            {
              key: "cartons",
              label: t("production.conditionnement.field.carton"),
              value: Math.max(packing.carton_quantity - packing.waste_carton_quantity, 0),
              unit: null,
            },
          ]
        : [];
    if (stepId === "stockage") return [...cartons, packets];
    // Conditionnement also carries the tonnage off the scale, in tonnes
    // (decision 17); extrusion reads the packets alone.
    if (stepId === "conditionnement") {
      return [
        packets,
        ...cartons,
        {
          key: "tonnage",
          label: t("production.reports.field.finishedProduct"),
          value: packing.finished_product_quantity,
          unit: "t",
        },
      ];
    }
    return [packets];
  }

  function destinationFor(report: ProductionReport): string | null {
    if (stepId !== "stockage") return null;
    const detail = details.get(report.id) as ConditionnementReportDetail | null | undefined;
    const id = detail?.finished_goods_location_id;
    return (id && locations.find((location) => location.id === id)?.name) || null;
  }

  // A total only when every figure is in the same unit — a sum across units is
  // a wrong number that reads as a right one.
  const totals = new Map<string, { label: string; sum: number; units: Set<string | null> }>();
  for (const report of state?.reports ?? []) {
    for (const metric of metricsFor(report)) {
      const entry = totals.get(metric.key) ?? { label: metric.key, sum: 0, units: new Set() };
      entry.sum += metric.value;
      entry.units.add(metric.unit);
      entry.label = metric.key === "semolina" ? t("production.dailyReports.field.semolina") : metric.label;
      totals.set(metric.key, entry);
    }
  }

  const postedMoves = stepId === "stockage" ? (state?.reports ?? []).flatMap((report) => movesFor(report.id)) : [];
  const postedTotal = postedMoves.reduce((sum, move) => sum + signedMoveQuantity(move), 0);
  // With a carton line, stock is posted from the carton count rather than the
  // packets counted, so the two can honestly differ.
  const showCartonNote =
    hasCartonTier &&
    (state?.reports ?? []).some((report) => {
      const detail = details.get(report.id) as ConditionnementReportDetail | null | undefined;
      return Boolean(detail) && movesFor(report.id).some((move) => move.quantity !== detail!.packets_counted);
    });

  return (
    <Dialog open={Boolean(step)} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-xl">
        {step && (
          <>
            <DialogHeader className="flex items-center gap-4 space-y-0">
              <img
                src={step.image}
                alt=""
                draggable={false}
                className={cn("h-20 w-28 shrink-0 object-contain", status === "empty" && "opacity-40 grayscale")}
              />
              <div className="min-w-0 space-y-1 pr-6">
                <DialogTitle className="text-lg">{t(step.labelKey)}</DialogTitle>
                <p className="flex items-center gap-1.5 text-sm font-medium">
                  <span className={cn("h-2 w-2 rounded-full", STATUS_DOT[status])} />
                  {t(STATUS_KEY[status])}
                  {!loading && state && state.reportCount > 0 && (
                    <span className="font-normal text-muted-foreground">
                      · {state.reportCount}{" "}
                      {t(state.reportCount === 1 ? "production.flow.report.one" : "production.flow.report.many")}
                    </span>
                  )}
                </p>
                <DialogDescription>{t(RULE_KEY[step.id])}</DialogDescription>
                {step.id === "stockage" && orderProduct && (
                  <p className="text-sm">
                    <span className="text-muted-foreground">{t("production.flow.details.product")} : </span>
                    <span className="font-medium">{orderProduct.name}</span>
                  </p>
                )}
              </div>
            </DialogHeader>

            {loading ? (
              <div className="space-y-2">
                <Skeleton className="h-14 w-full" />
                <Skeleton className="h-14 w-full" />
              </div>
            ) : !state || state.reports.length === 0 ? (
              <p className="rounded-lg border border-dashed border-border p-4 text-center text-sm text-muted-foreground">
                {t("production.flow.details.empty")}
              </p>
            ) : (
              <div className="space-y-3">
                {totals.size > 0 && (
                  <div className="flex flex-wrap gap-2">
                    {[...totals.entries()].map(([key, total]) => {
                      const units = [...total.units];
                      return (
                        <div key={key} className="rounded-lg border border-border bg-muted/40 px-3 py-2">
                          <p className="text-xs text-muted-foreground">
                            {t("production.flow.details.total")} · {total.label}
                          </p>
                          <p className="text-base font-semibold tabular-nums">
                            {units.length === 1 ? formatQuantity(total.sum, units[0]) : "—"}
                          </p>
                        </div>
                      );
                    })}
                    {postedMoves.length > 0 && (
                      <div className="rounded-lg border border-success/30 bg-success-soft px-3 py-2">
                        <p className="text-xs text-muted-foreground">{t("production.flow.details.posted")}</p>
                        <p className="text-base font-semibold tabular-nums">{formatQuantity(postedTotal, packetUnit)}</p>
                      </div>
                    )}
                  </div>
                )}

                <div className="space-y-2">
                  {state.reports.map((report) => {
                    const metrics = metricsFor(report);
                    const destination = destinationFor(report);
                    const moves = movesFor(report.id);
                    return (
                      <button
                        key={report.id}
                        type="button"
                        onClick={() => onOpenReport(report)}
                        className="flex w-full items-start gap-3 rounded-lg border border-border p-3 text-left transition-colors hover:border-primary/30 hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
                      >
                        <div className="min-w-0 flex-1 space-y-1">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="text-sm font-medium">{report.report_date}</span>
                            {report.shift && <span className="text-xs text-muted-foreground">{report.shift}</span>}
                            {report.team && <span className="text-xs text-muted-foreground">· {report.team}</span>}
                          </div>
                          <ul className="space-y-0.5 text-sm">
                            {metrics.map((metric, index) => (
                              <li key={`${metric.key}-${index}`} className="flex justify-between gap-4">
                                <span className="text-muted-foreground">{metric.label}</span>
                                <span className="font-medium tabular-nums">{formatQuantity(metric.value, metric.unit)}</span>
                              </li>
                            ))}
                            {destination && moves.length === 0 && !movesLoading && (
                              <li className="flex justify-between gap-4">
                                <span className="text-muted-foreground">
                                  {t("production.conditionnement.field.finishedGoodsStore")}
                                </span>
                                <span className="font-medium">{destination}</span>
                              </li>
                            )}
                          </ul>
                          {stepId === "stockage" && (
                            <div className="mt-2 space-y-1.5 rounded-md border border-border bg-muted/30 px-2.5 py-2 text-xs">
                              <p className="font-medium text-muted-foreground">{t("production.flow.details.movement")}</p>
                              {movesLoading ? (
                                <Skeleton className="h-5 w-full" />
                              ) : movesError ? (
                                <p className="text-muted-foreground">{t("production.flow.details.movement.unavailable")}</p>
                              ) : moves.length === 0 ? (
                                <p className="text-muted-foreground">{t("production.flow.details.movement.none")}</p>
                              ) : (
                                moves.map((move) => (
                                  <div key={move.id} className="flex flex-wrap items-center gap-x-2 gap-y-1">
                                    <Badge variant={MOVE_TYPE_VARIANT[move.move_type]}>{moveLabels[move.move_type]}</Badge>
                                    <span className="text-sm font-semibold tabular-nums">
                                      {signedMoveQuantity(move) > 0 ? "+" : ""}
                                      {formatQuantity(signedMoveQuantity(move), packetUnit)}
                                    </span>
                                    <span>→ {locationName(move.location_id)}</span>
                                    <span className="text-muted-foreground">
                                      · {new Date(move.created_at).toLocaleString(currentLocale())}
                                    </span>
                                  </div>
                                ))
                              )}
                            </div>
                          )}
                        </div>
                        <StatusBadge status={report.status} />
                      </button>
                    );
                  })}
                </div>
                {showCartonNote && (
                  <p className="text-xs text-muted-foreground">{t("production.flow.details.movement.cartonNote")}</p>
                )}
                <p className="text-xs text-muted-foreground">{t("production.flow.details.openHint")}</p>
              </div>
            )}
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
