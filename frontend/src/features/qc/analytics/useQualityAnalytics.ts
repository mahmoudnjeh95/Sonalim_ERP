import { useMemo } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useAuth } from "../../../lib/auth";
import { useI18n, type TranslationKey } from "../../../lib/i18n";
import { buildWindows, localTodayIso } from "../../analytics/manufacturing/metrics";
import { formatNumber, formatPercent } from "../../analytics/manufacturing/format";
import { listWorkCenters, listWorkOrders } from "../../production/api";
import { listProducts } from "../../warehouse/api";
import {
  getDispositionSummary,
  listFollowUps,
  listInspectableShiftReports,
  listInspectionLedger,
  listNonConformities,
} from "../api";
import { buildQualityInsights } from "./qualityInsights";
import {
  alignConformityTrend,
  breakdown,
  summarizeFollowUps,
  summarizeLedger,
  summarizeNonConformities,
  type LedgerLabels,
  type QualityDimension,
} from "./qualityMetrics";

const ROOT = ["qc", "analytics"] as const;

/**
 * Every figure on the quality dashboards, for the last `days` days and the
 * equal window before it. Each source is its own query so one failing (say, no
 * production permission for the line names) leaves the others rendering;
 * callers read `.isError` per source and show an explicit unavailable state
 * rather than a zero. `withBacklog` adds the packing runs still awaiting an
 * inspection -- the QC screen wants it, the cross-module analytics tab does not.
 */
export function useQualityAnalytics(days: number, { withBacklog = false }: { withBacklog?: boolean } = {}) {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const today = useMemo(() => localTodayIso(), []);
  const windows = useMemo(() => buildWindows(days, today), [days, today]);
  const { current, previous } = windows;

  const ledgerCurrent = useQuery({
    queryKey: [...ROOT, "ledger", current.from, current.to],
    placeholderData: keepPreviousData,
    queryFn: () => listInspectionLedger(token, { date_from: current.from, date_to: current.to }),
  });
  const ledgerPrevious = useQuery({
    queryKey: [...ROOT, "ledger", previous.from, previous.to],
    placeholderData: keepPreviousData,
    queryFn: () => listInspectionLedger(token, { date_from: previous.from, date_to: previous.to }),
  });
  const nonConformities = useQuery({ queryKey: ["qc", "non-conformities"], queryFn: () => listNonConformities(token) });
  const followUps = useQuery({ queryKey: ["qc", "follow-ups"], queryFn: () => listFollowUps(token) });
  const dispositions = useQuery({
    queryKey: [...ROOT, "dispositions", current.from, current.to],
    placeholderData: keepPreviousData,
    queryFn: () => getDispositionSummary(token, { date_from: current.from, date_to: current.to }),
  });
  const awaiting = useQuery({
    queryKey: ["qc", "inspectable-conditionnement"],
    queryFn: () => listInspectableShiftReports(token),
    enabled: withBacklog,
  });
  const products = useQuery({ queryKey: ["core", "products"], queryFn: () => listProducts(token) });
  const workOrders = useQuery({ queryKey: ["production", "work-orders"], queryFn: () => listWorkOrders(token) });
  const workCenters = useQuery({ queryKey: ["production", "work-centers"], queryFn: () => listWorkCenters(token) });

  const labels = useMemo<LedgerLabels>(() => {
    const productById = new Map((products.data ?? []).map((product) => [product.id, product]));
    const orderById = new Map((workOrders.data ?? []).map((order) => [order.id, order]));
    const centerById = new Map((workCenters.data ?? []).map((center) => [center.id, center]));
    return {
      product: (productId) => {
        if (!productId) return "—";
        const product = productById.get(productId);
        return product ? product.name : productId;
      },
      line: (ofId) => {
        const order = orderById.get(ofId);
        const center = order?.work_center_id ? centerById.get(order.work_center_id) : undefined;
        return center ? center.name : null;
      },
      order: (ofId) => orderById.get(ofId)?.reference ?? ofId,
      shift: (shift) => {
        if (!shift) return "—";
        const key = `qc.analytics.shift.${shift}` as TranslationKey;
        const text = t(key);
        return text === key ? shift : text;
      },
      team: (team) => team ?? "—",
    };
  }, [products.data, workOrders.data, workCenters.data, t]);

  const summary = useMemo(() => summarizeLedger(ledgerCurrent.data ?? []), [ledgerCurrent.data]);
  const previousSummary = useMemo(() => (ledgerPrevious.data ? summarizeLedger(ledgerPrevious.data) : null), [ledgerPrevious.data]);
  const trend = useMemo(
    () => alignConformityTrend(summary.byDay, previousSummary?.byDay ?? [], windows, days),
    [summary.byDay, previousSummary?.byDay, windows, days],
  );
  const slices = useMemo(() => {
    const rows = ledgerCurrent.data ?? [];
    return Object.fromEntries(
      (["product", "line", "team", "shift", "order"] as QualityDimension[]).map((dimension) => [dimension, breakdown(rows, dimension, labels)]),
    ) as Record<QualityDimension, ReturnType<typeof breakdown>>;
  }, [ledgerCurrent.data, labels]);
  const ncSummary = useMemo(() => summarizeNonConformities(nonConformities.data ?? [], today), [nonConformities.data, today]);
  const followUpSummary = useMemo(() => summarizeFollowUps(followUps.data ?? [], today), [followUps.data, today]);

  const fmt = useMemo(
    () => ({
      number: formatNumber,
      percent: (value: number | null, digits = 1) => formatPercent(value, digits),
      cartons: (value: number) => `${formatNumber(value, 0)} ${t("qc.analytics.unit.cartons")}`,
    }),
    [t],
  );

  const insights = useMemo(
    () =>
      buildQualityInsights({
        current: summary,
        previous: ledgerPrevious.isError ? null : previousSummary,
        byProduct: slices.product,
        byTeam: slices.team,
        byShift: slices.shift,
        nonConformities: ncSummary,
        followUps: followUpSummary,
        awaitingInspection: awaiting.data?.length ?? 0,
        fmt,
      }),
    [summary, previousSummary, ledgerPrevious.isError, slices, ncSummary, followUpSummary, awaiting.data, fmt],
  );

  return {
    today,
    windows,
    sources: { ledgerCurrent, ledgerPrevious, nonConformities, followUps, dispositions, awaiting, products, workOrders, workCenters },
    labels,
    summary,
    previousSummary,
    trend,
    slices,
    ncSummary,
    followUpSummary,
    dispositionRows: dispositions.data ?? [],
    awaitingCount: awaiting.data?.length ?? 0,
    nonConformityRecords: nonConformities.data ?? [],
    insights,
    fmt,
  };
}

export type QualityAnalytics = ReturnType<typeof useQualityAnalytics>;
