import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { motion } from "framer-motion";
import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  ClipboardList,
  Droplets,
  Factory,
  FlaskConical,
  FileText,
  PauseCircle,
  PlayCircle,
  Recycle,
  Rocket,
  ShieldCheck,
} from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import { ApiError } from "../../lib/api";
import { Button } from "../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Badge } from "../../components/ui/badge";
import { StatusBadge } from "../../components/patterns/StatusBadge";
import { HelpTooltip } from "../../components/patterns/HelpTooltip";
import { RecipeCheckPanel } from "./RecipeCheckPanel";
import { PackagingVariancePanel } from "./PackagingVariancePanel";
import { EmptyState } from "../../components/patterns/EmptyState";
import { cn } from "../../lib/utils";
import {
  ACTIVE_CONSOLIDATIONS_QUERY_KEY,
  WORK_ORDER_OVERVIEW_QUERY_KEY,
  closeWorkOrder,
  getPreCloseCheck,
  getWorkOrderConsolidation,
  getWorkOrderPackagingVariance,
  getWorkOrdersOverview,
  listMolds,
  listProducts,
  listRegrindDefaults,
  listReports,
  listWorkCenters,
  listWorkOrders,
  resumeWorkOrder,
  startWorkOrder,
  suspendWorkOrder,
  type ProductionReport,
} from "./api";
import { SHIFT_REPORTS_QUERY_KEY, listShiftReports } from "./shift/shiftApi";
import { DailyReportDialog } from "./DailyReportsTab";
import { PackingReportDialog } from "./ConditionnementTab";
import { ProductionFlow } from "./ProductionFlow";
import { StageDetailsDialog } from "./StageDetailsDialog";
import type { ProductionStepId } from "./productionSteps";
import { useOfStageStates } from "./useOfStageStates";
import {
  getDispositionSummary,
  listNonConformities,
  listQualityReports,
  type NonConformity,
  type QualityReport,
} from "../qc/api";
import { QualityReportDialog } from "../qc/QualityReportsTab";
import { NonConformityDetailDialog } from "../qc/NonConformityDetailDialog";
import { listLocations, listUoms } from "../warehouse/api";
import { listPartners } from "../partners/api";
import { UTILITY_UNITS, formatDuration, formatQuantity, productUnit } from "../../lib/units";
import { AppLoader } from "../../components/patterns/AppLoader";

export function WorkOrderDetailsPage() {
  const { workOrderId = "" } = useParams();
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();

  const { data: workOrders = [], isLoading } = useQuery({
    queryKey: ["production", "work-orders"],
    queryFn: () => listWorkOrders(token),
  });
  const order = workOrders.find((o) => o.id === workOrderId);

  const { data: packagingVariance } = useQuery({
    queryKey: ["production", "packaging-variance", "of", workOrderId],
    queryFn: () => getWorkOrderPackagingVariance(session!.token, workOrderId!),
    enabled: Boolean(workOrderId),
  });

  const { data: consolidation } = useQuery({
    queryKey: ["production", "of-consolidation", workOrderId],
    queryFn: () => getWorkOrderConsolidation(token, workOrderId),
    enabled: Boolean(workOrderId),
  });
  const { data: reports = [], isLoading: reportsLoading } = useQuery({
    queryKey: ["production", "reports", "of", workOrderId],
    queryFn: () => listReports(token, { of_id: workOrderId }),
    enabled: Boolean(workOrderId),
  });
  // Every shift that worked on this order, validated or not, and what is still waiting on it.
  const { data: shifts = [] } = useQuery({
    queryKey: [...SHIFT_REPORTS_QUERY_KEY, "of", workOrderId],
    queryFn: () => listShiftReports(token, { of_id: workOrderId }),
    enabled: Boolean(workOrderId),
    retry: false,
  });
  const { data: workCenters = [] } = useQuery({ queryKey: ["production", "work-centers"], queryFn: () => listWorkCenters(token) });
  const { data: overview = [] } = useQuery({
    queryKey: WORK_ORDER_OVERVIEW_QUERY_KEY,
    queryFn: () => {
      const now = new Date();
      const pad = (n: number) => String(n).padStart(2, "0");
      return getWorkOrdersOverview(token, {
        date: `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`,
        at: `${pad(now.getHours())}:${pad(now.getMinutes())}`,
      });
    },
  });
  const pendingQuantity = overview.find((row) => row.of_id === workOrderId)?.pending_quantity ?? 0;
  const { data: qualityReports = [] } = useQuery({
    queryKey: ["qc", "quality-reports", "of", workOrderId],
    queryFn: () => listQualityReports(token, { of_id: workOrderId }),
    enabled: Boolean(workOrderId),
  });
  const { data: nonConformities = [] } = useQuery({
    queryKey: ["qc", "non-conformities", "of", workOrderId],
    queryFn: () => listNonConformities(token, { of_id: workOrderId }),
    enabled: Boolean(workOrderId),
  });
  const { data: dispositionSummary } = useQuery({
    queryKey: ["qc", "disposition-summary", "of", workOrderId],
    queryFn: () => getDispositionSummary(token, { of_id: workOrderId }),
    enabled: Boolean(workOrderId),
  });
  const { data: products = [] } = useQuery({
    queryKey: ["core", "products"],
    queryFn: () => listProducts(token),
  });
  const { data: uoms = [] } = useQuery({ queryKey: ["core", "uoms"], queryFn: () => listUoms(token) });
  const { data: preClose } = useQuery({
    queryKey: ["production", "pre-close-check", workOrderId],
    queryFn: () => getPreCloseCheck(token, workOrderId),
    enabled: Boolean(workOrderId),
  });

  // Reference data a report's own detail dialog needs — fetched here (rather
  // than only inside the tabs that list reports) so a report opened from this
  // page renders the same dialog in place, instead of navigating off to the
  // Production or Quality tab and losing this view.
  const { data: locations = [] } = useQuery({ queryKey: ["warehouse", "locations"], queryFn: () => listLocations(token) });
  const { data: molds = [] } = useQuery({ queryKey: ["production", "molds"], queryFn: () => listMolds(token) });
  const { data: partners = [] } = useQuery({ queryKey: ["core", "partners"], queryFn: () => listPartners(token) });
  const suppliers = partners.filter((p) => p.kind === "supplier" || p.kind === "both");
  const { data: regrindDefaults = [] } = useQuery({
    queryKey: ["production", "regrind-defaults"],
    queryFn: () => listRegrindDefaults(token),
  });
  const regrindOutputProductId = regrindDefaults.find((d) => d.input_product_id === null)?.output_product_id ?? null;

  const {
    states: stageStates,
    details: stageDetails,
    isLoading: stagesLoading,
  } = useOfStageStates(token, reports, order?.status ?? "planned");
  // The stage whose popup is open. It lists the reports behind the stage's
  // status; opening one of them swaps this popup for that report's dialog.
  const [openStage, setOpenStage] = useState<ProductionStepId | null>(null);

  const [openReport, setOpenReport] = useState<ProductionReport | null>(null);
  const [openQualityReport, setOpenQualityReport] = useState<QualityReport | null>(null);
  const [openNc, setOpenNc] = useState<NonConformity | null>(null);
  const orderProduct = order ? products.find((p) => p.id === order.product_id) : undefined;
  const packetsPerCarton = orderProduct?.packets_per_carton && orderProduct.packets_per_carton > 0 ? orderProduct.packets_per_carton : null;

  function invalidate() {
    for (const key of [
      ["production", "work-orders"],
      ["production", "of-consolidation", workOrderId],
      // Start, suspend and close change which orders the cockpit counts as active.
      ACTIVE_CONSOLIDATIONS_QUERY_KEY,
      ["production", "pre-close-check", workOrderId],
    ]) {
      queryClient.invalidateQueries({ queryKey: key });
    }
  }

  function lifecycle(action: () => Promise<unknown>, successKey: string, errorKey: string) {
    return {
      mutationFn: action,
      onSuccess: () => {
        invalidate();
        toast.success(t(successKey as Parameters<typeof t>[0]));
      },
      onError: (error: unknown) => {
        toast.error(t(errorKey as Parameters<typeof t>[0]), {
          description: error instanceof ApiError ? error.message : undefined,
        });
      },
    };
  }

  const startMutation = useMutation(
    lifecycle(
      () => startWorkOrder(token, workOrderId),
      "production.workOrders.started",
      "production.workOrders.startError",
    ),
  );
  const suspendMutation = useMutation(
    lifecycle(
      () => suspendWorkOrder(token, workOrderId),
      "production.workOrders.suspendedToast",
      "production.workOrders.suspendError",
    ),
  );
  const resumeMutation = useMutation(
    lifecycle(
      () => resumeWorkOrder(token, workOrderId),
      "production.workOrders.resumedToast",
      "production.workOrders.resumeError",
    ),
  );
  const closeMutation = useMutation(
    lifecycle(
      () => closeWorkOrder(token, workOrderId, crypto.randomUUID()),
      "production.workOrders.closedToast",
      "production.workOrders.closeError",
    ),
  );

  if (isLoading) {
    return (
      <AppLoader className="py-8" />
    );
  }

  if (!order) {
    return (
      <EmptyState
        icon={<Factory className="h-5 w-5" />}
        title={t("production.ofDetails.notFound.title")}
        description={t("production.ofDetails.notFound.description")}
        action={
          <Button asChild size="sm" variant="outline">
            <Link to="/production">{t("production.ofDetails.back")}</Link>
          </Button>
        }
      />
    );
  }

  // Produced against what was actually poured in — semoule plus any rebroyat
  // recycled back into the mix — rather than against the schedule.
  const transformation = consolidation?.transformation_ratio ?? 0;
  // Everything the OF consumes and produces is counted in its product's own unit.
  // An order can pack several products: their common unit, and a bare number when they differ.
  const orderUnits = new Set(
    (consolidation?.product_ids?.length ? consolidation.product_ids : order?.product_id ? [order.product_id] : []).map(
      (id) => productUnit(id, products, uoms) ?? "",
    ),
  );
  const productUom = orderUnits.size === 1 && [...orderUnits][0] ? [...orderUnits][0] : null;
  // Each consolidated figure is in its own product's unit. Null where the
  // validated reports named different products, and the figure then shows bare.
  const semolinaUom = productUnit(consolidation?.raw_material.semolina_product_id, products, uoms);
  const regrindUom = productUnit(consolidation?.raw_material.regrind_input_product_id, products, uoms);
  const filmUom = productUnit(consolidation?.packaging.film_product_id, products, uoms);
  const cartonUom = productUnit(consolidation?.packaging.carton_product_id, products, uoms);
  const scotchUom = productUnit(consolidation?.packaging.scotch_product_id, products, uoms);
  const rubanUom = productUnit(consolidation?.packaging.ruban_product_id, products, uoms);
  const regrindWasteUom = productUnit(consolidation?.waste.regrind.product_id, products, uoms);
  const productName = (id: string | null) =>
    (id && products.find((p) => p.id === id)?.name) || t("production.waste.unknownItem");

  // Déchets, one row per item, because that is the only grouping that can carry
  // a unit. The old card had a row per category and gave them all the semoule's
  // unit, which is how five broken cartons came to read as five tonnes.
  const wasteRows = [
    ...(consolidation?.waste.by_product ?? []).map((entry) => ({
      label: productName(entry.product_id),
      value: entry.quantity,
      unit: productUnit(entry.product_id, products, uoms),
    })),
    // Only ever above zero for reports written before waste named its item.
    // Shown bare, with no unit, because there is none to give it honestly.
    ...(consolidation && consolidation.waste.unattributed_quantity > 0
      ? [
          {
            label: t("production.waste.unattributed"),
            value: consolidation.waste.unattributed_quantity,
            unit: null,
          },
        ]
      : []),
    // Not a déchet: recovered material that opens its own regrind OF. It sits
    // here because it is what the shift writes on the same line of the form.
    ...(consolidation && consolidation.waste.regrind.quantity > 0
      ? [
          {
            label: `${t("production.dailyReports.field.regrind")} — ${productName(
              consolidation.waste.regrind.product_id,
            )}`,
            value: consolidation.waste.regrind.quantity,
            unit: regrindWasteUom,
            hint: t("production.ofDetails.waste.regrindHint"),
          },
        ]
      : []),
  ];

  const reportStatusIcon = (status: string) => {
    switch (status) {
      case "draft":
        return <FileText className="h-3.5 w-3.5 text-primary" />;
      case "submitted":
        return <Rocket className="h-3.5 w-3.5 text-warning" />;
      case "validated":
        return <ShieldCheck className="h-3.5 w-3.5 text-success" />;
      case "rejected":
        return <AlertTriangle className="h-3.5 w-3.5 text-destructive" />;
      default:
        return <FileText className="h-3.5 w-3.5 text-primary" />;
    }
  };

  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}>
        <Button asChild size="sm" variant="ghost" className="-ml-2 mb-2">
          <Link to="/production">
            <ArrowLeft className="h-3.5 w-3.5" />
            {t("production.ofDetails.back")}
          </Link>
        </Button>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-xl font-semibold tracking-tight">{order.reference}</h1>
          <StatusBadge status={order.status} />
          {order.product_type && <Badge variant="outline">{order.product_type}</Badge>}
          <div className="ml-auto flex flex-wrap gap-2">
            {order.status === "planned" && (
              <Button size="sm" variant="outline" onClick={() => startMutation.mutate()} disabled={startMutation.isPending}>
                <PlayCircle className="h-3.5 w-3.5" />
                {t("production.workOrders.start")}
              </Button>
            )}
            {order.status === "ongoing" && (
              <>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => suspendMutation.mutate()}
                  disabled={suspendMutation.isPending}
                >
                  <PauseCircle className="h-3.5 w-3.5" />
                  {t("production.workOrders.suspend")}
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => closeMutation.mutate()}
                  disabled={closeMutation.isPending || preClose?.can_close === false}
                  title={preClose?.can_close === false ? t("production.ofDetails.closeBlocked") : undefined}
                >
                  <CheckCircle2 className="h-3.5 w-3.5" />
                  {t("production.workOrders.close")}
                </Button>
              </>
            )}
            {order.status === "suspended" && (
              <Button size="sm" variant="outline" onClick={() => resumeMutation.mutate()} disabled={resumeMutation.isPending}>
                <PlayCircle className="h-3.5 w-3.5" />
                {t("production.workOrders.resume")}
              </Button>
            )}
          </div>
        </div>
        <p className="mt-1 text-sm text-muted-foreground">
          {order.start_date ?? "—"}
          {order.closed_at ? ` → ${order.closed_at.slice(0, 10)}` : ""}
        </p>
      </motion.div>

      <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.24, ease: "easeOut" }}>
        <Card>
          <CardHeader>
            <CardTitle>{t("production.flow.title")}</CardTitle>
            <p className="mt-0.5 text-sm text-muted-foreground">{t("production.flow.subtitle")}</p>
          </CardHeader>
          <CardContent>
            <ProductionFlow states={stageStates} loading={reportsLoading || stagesLoading} onStepClick={setOpenStage} />
          </CardContent>
        </Card>
      </motion.div>

      {preClose && (preClose.blockers.length > 0 || preClose.warnings.length > 0) && (
        <Card>
          <CardHeader>
            <CardTitle>{t("production.ofDetails.closure.title")}</CardTitle>
            <p className="mt-0.5 text-sm text-muted-foreground">{t("production.ofDetails.closure.subtitle")}</p>
          </CardHeader>
          <CardContent className="space-y-2">
            {preClose.blockers.map((finding) => (
              <div
                key={finding.code}
                className="flex items-start gap-3 rounded-lg border border-destructive/20 bg-destructive-soft p-3"
              >
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
                <div>
                  <p className="text-sm font-medium text-destructive">{t("production.ofDetails.closure.blocker")}</p>
                  <p className="text-sm text-muted-foreground">
                    {finding.count} · {finding.message}
                  </p>
                </div>
              </div>
            ))}
            {preClose.warnings.map((finding) => (
              <div key={finding.code} className="flex items-start gap-3 rounded-lg border border-border p-3">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
                <div>
                  <p className="text-sm font-medium">{t("production.ofDetails.closure.warning")}</p>
                  <p className="text-sm text-muted-foreground">{finding.message}</p>
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.24, ease: "easeOut" }}>
        <Card>
          <CardHeader>
            <CardTitle>{t("production.ofDetails.progress.title")}</CardTitle>
            <p className="mt-0.5 text-sm text-muted-foreground">{t("production.ofDetails.progress.subtitle")}</p>
          </CardHeader>
          <CardContent className="space-y-3">
          <div className="flex items-baseline justify-between">
            {/* Tonnes throughout: the OF is planned in them (decision 19) and the
                packing reports report them (decision 17). The packet count is the
                separate figure below, because it answers a different question. */}
            <span className="text-2xl font-semibold tabular-nums">
              {formatQuantity(consolidation?.produced_quantity, "t")}
            </span>
            <span className="text-sm text-muted-foreground">
              / {formatQuantity(consolidation?.material_input_quantity, "t")} ·{" "}
              {Math.round(transformation * 100)}%
            </span>
          </div>
          <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
            <motion.div
              className="h-full rounded-full bg-success"
              initial={{ width: 0 }}
              animate={{ width: `${Math.min(100, transformation * 100)}%` }}
              transition={{ duration: 0.4, ease: "easeOut" }}
            />
          </div>
            <p className="text-xs text-muted-foreground">
              {t("production.ofDetails.progress.planned")}: {formatQuantity(order.planned_quantity, "t")} ·{" "}
              {t("production.conditionnement.field.packetsCounted")}:{" "}
              {formatQuantity(consolidation?.packets_counted, productUom)}
            </p>
            {/* What is handed in or still being typed: shown beside the official figure, never inside it. */}
            {pendingQuantity > 0 && (
              <p className="text-xs text-muted-foreground">
                + {formatQuantity(pendingQuantity, "t")} {t("production.ofDetails.pending")}
              </p>
            )}
          </CardContent>
        </Card>
      </motion.div>

      {/* The écart net. Read-only by decision 22 — it never held anything up, and
          it sits here because this is where a supervisor decides whether a run
          lost product or simply mis-weighed it. */}
      {packagingVariance && (
        <Card>
          <CardHeader>
            <CardTitle>{t("production.ofDetails.packagingVariance.title")}</CardTitle>
            {"multi_product" in packagingVariance && (
              <p className="mt-0.5 text-sm text-muted-foreground">{t("production.packagingVariance.perProduct")}</p>
            )}
          </CardHeader>
          <CardContent className="space-y-4">
            {"multi_product" in packagingVariance ? (
              packagingVariance.products.map((entry) => (
                <div key={entry.product_id} className="space-y-2">
                  <p className="text-sm font-medium">{productName(entry.product_id)}</p>
                  <PackagingVariancePanel variance={entry} net dispositionSummary={dispositionSummary} />
                </div>
              ))
            ) : (
              <>
                <PackagingVariancePanel variance={packagingVariance} net dispositionSummary={dispositionSummary} />
                {packagingVariance.parameters_varied && (
                  <p className="text-xs text-muted-foreground">{t("production.packagingVariance.parametersVaried")}</p>
                )}
              </>
            )}
          </CardContent>
        </Card>
      )}

      {/* Directly under the progress bar: the mix that produced those figures is
          what a supervisor questions first when the numbers look wrong. */}
      <RecipeCheckPanel workOrderId={order.id} products={products} />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <ConsolidationCard
          title={t("production.ofDetails.material.title")}
          icon={<ClipboardList className="h-4 w-4" />}
          rows={[
            {
              label: t("production.dailyReports.field.semolina"),
              value: consolidation?.raw_material.semolina_quantity,
              unit: semolinaUom,
            },
            {
              label: t("production.dailyReports.field.regrindInput"),
              value: consolidation?.raw_material.regrind_input_quantity,
              unit: regrindUom,
            },
            {
              label: t("production.conditionnement.field.film"),
              value: consolidation?.packaging.film_quantity,
              unit: filmUom,
            },
            {
              label: t("production.conditionnement.field.carton"),
              value: consolidation?.packaging.carton_quantity,
              unit: cartonUom,
            },
            {
              label: t("production.conditionnement.field.wasteCarton"),
              value: consolidation?.packaging.waste_carton_quantity,
              unit: cartonUom,
            },
            {
              label: t("production.conditionnement.field.scotch"),
              value: consolidation?.packaging.scotch_quantity,
              unit: scotchUom,
            },
            {
              label: t("production.conditionnement.field.ruban"),
              value: consolidation?.packaging.ruban_quantity,
              unit: rubanUom,
            },
          ]}
        />
        <ConsolidationCard
          title={t("production.ofDetails.utilities.title")}
          icon={<Droplets className="h-4 w-4" />}
          rows={[
            {
              label: t("production.dailyReports.field.water"),
              value: consolidation?.utilities.water_quantity,
              unit: UTILITY_UNITS.water,
            },
            {
              label: t("production.dailyReports.field.fuel"),
              value: consolidation?.utilities.fuel_quantity,
              unit: UTILITY_UNITS.fuel,
            },
            {
              label: t("production.dailyReports.field.electricity"),
              value: consolidation?.utilities.electricity_quantity,
              unit: UTILITY_UNITS.electricity,
            },
            {
              label: t("production.ofDetails.time.production"),
              value: consolidation?.time.production_minutes,
              duration: true,
            },
            {
              label: t("production.ofDetails.time.downtime"),
              value: consolidation?.time.downtime_minutes,
              duration: true,
            },
          ]}
        />
        <ConsolidationCard
          title={t("production.ofDetails.waste.title")}
          icon={<Recycle className="h-4 w-4" />}
          rows={wasteRows}
          empty={t("production.ofDetails.waste.none")}
          emptyHint={t("production.ofDetails.waste.noneHint")}
        />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {/* Every shift that worked on this order, validated or not. A row opens that shift in the shift
            screen, where it is read and, if it is still open, filled in. */}
        <Card>
          <CardHeader>
            <CardTitle>{t("production.ofDetails.shifts.title")}</CardTitle>
            <p className="mt-0.5 text-sm text-muted-foreground">{t("production.ofDetails.shifts.subtitle")}</p>
          </CardHeader>
          <CardContent className={shifts.length === 0 ? "p-0" : "space-y-2"}>
            {shifts.length === 0 ? (
              <EmptyState
                icon={<ClipboardList className="h-5 w-5" />}
                title={t("production.ofDetails.shifts.title")}
                description={t("production.ofDetails.shifts.empty")}
              />
            ) : (
              shifts.map((shift) => (
                <Link
                  key={shift.id}
                  to={`/production?tab=shift-report&line=${encodeURIComponent(shift.work_center_id)}&date=${shift.report_date}&shift=${encodeURIComponent(shift.shift)}`}
                  title={t("production.ofDetails.shifts.open")}
                  className="flex w-full items-center gap-3 rounded-lg border border-border p-3 text-left transition-colors hover:border-primary/30 hover:bg-muted/40"
                >
                  <div className="flex h-9 w-9 items-center justify-center rounded-lg border border-primary/15 bg-primary/10 text-primary">
                    {reportStatusIcon(shift.status === "open" ? "draft" : shift.status === "returned" ? "rejected" : shift.status)}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-medium tabular-nums">{shift.report_date}</span>
                      <Badge variant="outline">{shift.shift}</Badge>
                      <span className="text-xs text-muted-foreground">
                        {workCenters.find((wc) => wc.id === shift.work_center_id)?.name ?? "—"}
                      </span>
                    </div>
                  </div>
                  <StatusBadge status={shift.status} />
                </Link>
              ))
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>{t("production.ofDetails.quality.title")}</CardTitle>
            <p className="mt-0.5 text-sm text-muted-foreground">{t("production.ofDetails.quality.subtitle")}</p>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex items-baseline justify-between">
              <span className="text-sm text-muted-foreground">{t("production.dashboard.health.conformity")}</span>
              <span
                className={cn(
                  "text-sm font-medium tabular-nums",
                  consolidation?.quality.conformity_rate == null && "text-muted-foreground",
                )}
              >
                {consolidation?.quality.conformity_rate == null
                  ? t("production.dashboard.health.noData")
                  : `${(consolidation.quality.conformity_rate * 100).toFixed(1)}%`}
              </span>
            </div>

            {consolidation && consolidation.quality.pending_nc_reports.length > 0 && (
              <div className="space-y-2 rounded-lg border border-destructive/30 bg-destructive-soft p-3">
                <div className="flex items-start gap-2">
                  <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
                  <p className="text-sm font-medium text-destructive">
                    {consolidation.quality.pending_nc_reports.length > 1
                      ? t("production.ofDetails.quality.pendingNc.titlePlural")
                      : t("production.ofDetails.quality.pendingNc.title")}
                  </p>
                </div>
                <p className="text-xs text-muted-foreground">{t("production.ofDetails.quality.pendingNc.hint")}</p>
                <div className="space-y-1.5">
                  {consolidation.quality.pending_nc_reports.map((pending) => {
                    const report = qualityReports.find((r) => r.id === pending.report_id);
                    return (
                      <button
                        key={pending.report_id}
                        type="button"
                        onClick={() => report && setOpenQualityReport(report)}
                        className="flex w-full items-center justify-between gap-2 rounded-md border border-destructive/20 bg-background px-2.5 py-1.5 text-left text-xs transition-colors hover:border-destructive/40 hover:bg-muted/40"
                      >
                        <span className="font-medium">{pending.report_date}</span>
                        <span className="text-muted-foreground">
                          {formatQuantity(pending.non_conforming_cartons)}{" "}
                          {t("production.ofDetails.quality.pendingNc.cartonsSuffix")}
                        </span>
                      </button>
                    );
                  })}
                </div>
              </div>
            )}

            {qualityReports.length === 0 && nonConformities.length === 0 ? (
              <EmptyState
                icon={<FlaskConical className="h-5 w-5" />}
                title={t("production.ofDetails.quality.empty.title")}
                description={t("production.ofDetails.quality.empty.description")}
              />
            ) : (
              <div className="space-y-2">
                {qualityReports.map((report) => (
                  <motion.button
                    key={report.id}
                    type="button"
                    onClick={() => setOpenQualityReport(report)}
                    whileHover={{ y: -1 }}
                    transition={{ duration: 0.15 }}
                    className="flex w-full items-center gap-3 rounded-lg border border-border p-3 text-left transition-colors hover:border-primary/30 hover:bg-muted/40"
                  >
                    <div className="flex h-9 w-9 items-center justify-center rounded-lg border border-primary/15 bg-primary/10 text-primary">
                      {reportStatusIcon(report.status)}
                    </div>
                    <span className="min-w-0 flex-1 text-sm">{report.report_date}</span>
                    {report.revision > 1 && (
                      <span className="flex items-center gap-1">
                        <Badge variant="outline" className="text-xs">
                          {t("production.ofDetails.quality.revisionLabel")} {report.revision}
                        </Badge>
                        <HelpTooltip text={t("production.ofDetails.quality.revisionHint")} />
                      </span>
                    )}
                    <StatusBadge status={report.status} />
                  </motion.button>
                ))}
                {nonConformities.map((nc) => (
                  <button
                    key={nc.id}
                    type="button"
                    onClick={() => setOpenNc(nc)}
                    className="flex w-full items-center gap-3 rounded-lg border border-border p-3 text-left transition-colors hover:border-destructive/30 hover:bg-muted/40"
                  >
                    <AlertTriangle className="h-4 w-4 shrink-0 text-destructive" />
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium">{nc.reference}</p>
                      <p className="truncate text-xs text-muted-foreground">
                        {nc.defect_type} · {formatQuantity(nc.quantity)}
                      </p>
                    </div>
                    <StatusBadge status={nc.status} />
                  </button>
                ))}
              </div>
            )}
            <p className="text-xs text-muted-foreground">{t("production.ofDetails.quality.outlives")}</p>
            {(qualityReports.length > 0 || nonConformities.length > 0) && (
              <p className="text-xs text-muted-foreground">{t("production.ofDetails.quality.openHint")}</p>
            )}
          </CardContent>
        </Card>
      </div>

      <StageDetailsDialog
        token={token}
        orderId={workOrderId}
        orderProduct={
          orderProduct
            ? { id: orderProduct.id, name: orderProduct.name, packets_per_carton: orderProduct.packets_per_carton }
            : null
        }
        stepId={openStage}
        state={openStage ? stageStates[openStage] : null}
        details={stageDetails}
        loading={stagesLoading}
        products={products}
        uoms={uoms}
        locations={locations}
        packetUnit={productUom}
        onOpenReport={(report) => {
          setOpenStage(null);
          setOpenReport(report);
        }}
        onClose={() => setOpenStage(null)}
      />

      {openReport &&
        (openReport.report_type === "daily" ? (
          <DailyReportDialog
            key={openReport.id}
            report={openReport}
            reference={order.reference}
            products={products}
            locations={locations}
            uoms={uoms}
            workOrders={workOrders}
            molds={molds}
            regrindOutputProductId={regrindOutputProductId}
            suppliers={suppliers}
            onClose={() => setOpenReport(null)}
          />
        ) : (
          <PackingReportDialog
            key={openReport.id}
            report={openReport}
            reference={order.reference}
            finishedProductId={order.product_id ?? undefined}
            orderType={order.product_type}
            products={products}
            locations={locations}
            uoms={uoms}
            suppliers={suppliers}
            onClose={() => setOpenReport(null)}
          />
        ))}

      {openQualityReport && (
        <QualityReportDialog
          key={openQualityReport.id}
          report={openQualityReport}
          reference={order.reference}
          packetsPerCarton={packetsPerCarton}
          productId={order.product_id ?? undefined}
          onClose={() => setOpenQualityReport(null)}
        />
      )}

      {openNc && (
        <NonConformityDetailDialog
          nonConformity={openNc}
          ofReference={order.reference}
          products={products}
          uoms={uoms}
          locations={locations}
          onClose={() => setOpenNc(null)}
        />
      )}
    </div>
  );
}

function ConsolidationCard({
  title,
  icon,
  rows,
  empty,
  emptyHint,
}: {
  title: string;
  icon: React.ReactNode;
  rows: {
    label: string;
    value: number | undefined;
    unit?: string | null;
    duration?: boolean;
    /** Shown next to the label when the figure needs a word of explanation. */
    hint?: string;
  }[];
  /**
   * What to say when there are no rows. Only cards whose rows are built from
   * data pass it — a fixed row list is never empty, and "nothing recorded" is a
   * different statement from a figure of zero.
   */
  empty?: string;
  emptyHint?: string;
}) {
  const { t } = useI18n();
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-1.5 text-base">
          {icon}
          {title}
        </CardTitle>
      </CardHeader>
      <CardContent>
        {rows.length === 0 && empty ? (
          <div>
            <p className="text-sm text-muted-foreground">{empty}</p>
            {emptyHint && <p className="mt-0.5 text-xs text-muted-foreground">{emptyHint}</p>}
          </div>
        ) : null}
        <dl className="space-y-1.5">
          {rows.map((row, index) => (
            <div key={`${row.label}-${index}`} className="flex items-baseline justify-between gap-3">
              <dt className="flex items-center gap-1 text-sm text-muted-foreground">
                {row.label}
                {row.hint && <HelpTooltip text={row.hint} />}
              </dt>
              <dd className="text-sm font-medium tabular-nums">
                {row.value === undefined
                  ? t("production.dashboard.health.noData")
                  : row.duration
                    ? formatDuration(row.value)
                    : formatQuantity(row.value, row.unit)}
              </dd>
            </div>
          ))}
        </dl>
      </CardContent>
    </Card>
  );
}
