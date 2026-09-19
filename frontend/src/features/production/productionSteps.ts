import melange from "../../assets/illustrations/production/stage-melange.webp";
import petrissage from "../../assets/illustrations/production/stage-petrissage.webp";
import extrusion from "../../assets/illustrations/production/stage-extrusion.webp";
import conditionnement from "../../assets/illustrations/production/stage-conditionnement.webp";
import stockage from "../../assets/illustrations/production/stage-stockage.webp";
import type {
  ConditionnementReportDetail,
  DailyReportDetail,
  ProductionReport,
  ProductionReportWithDetail,
  ReportType,
  WorkOrderStatus,
} from "./api";
import type { TranslationKey } from "../../lib/i18n";

export type ProductionStepId = "melange" | "petrissage" | "extrusion" | "conditionnement" | "stockage";

export interface ProductionStep {
  id: ProductionStepId;
  labelKey: TranslationKey;
  image: string;
  /** The report type that carries this stage's figures. */
  reportType: ReportType;
}

export const productionSteps: ProductionStep[] = [
  { id: "melange", labelKey: "production.flow.step.melange", image: melange, reportType: "daily" },
  { id: "petrissage", labelKey: "production.flow.step.petrissage", image: petrissage, reportType: "daily" },
  { id: "extrusion", labelKey: "production.flow.step.extrusion", image: extrusion, reportType: "conditionnement" },
  {
    id: "conditionnement",
    labelKey: "production.flow.step.conditionnement",
    image: conditionnement,
    reportType: "conditionnement",
  },
  { id: "stockage", labelKey: "production.flow.step.stockage", image: stockage, reportType: "conditionnement" },
];

/**
 * empty   — nothing filed for the stage (artwork greyed out)
 * pending — figures filed, at least one report not validated yet (pulsing dot)
 * done    — figures filed and every one of those reports validated (green check)
 */
export type StageStatus = "empty" | "pending" | "done";

export interface StageState {
  status: StageStatus;
  /** Reports that carry this stage's figures, newest first. */
  reports: ProductionReport[];
  reportCount: number;
  /** ISO date of the most recent of them, for the tooltip. */
  lastReportDate: string | null;
}

export type StageStates = Record<ProductionStepId, StageState>;

// A stage counts as filled when its own figure is above zero — the signal each
// one lights up on. Pétrissage reads the weight of finished product off the
// daily report; extrusion and conditionnement both read the packets counted on
// the packing report. Stockage is the exception: it only exists once validation
// has posted the packed product into the finished-goods store.
const SIGNALS: Record<ProductionStepId, (detail: DailyReportDetail | ConditionnementReportDetail) => boolean> = {
  melange: (d) => (d as DailyReportDetail).semolina_lines?.some((line) => line.quantity > 0) ?? false,
  petrissage: (d) => (d as DailyReportDetail).finished_product_quantity > 0,
  extrusion: (d) => (d as ConditionnementReportDetail).packets_counted > 0,
  conditionnement: (d) => (d as ConditionnementReportDetail).packets_counted > 0,
  stockage: (d) => (d as ConditionnementReportDetail).packets_counted > 0,
};

const EMPTY_STATE: StageState = { status: "empty", reports: [], reportCount: 0, lastReportDate: null };

export function deriveStageStates(
  reports: ProductionReport[],
  details: Map<string, ProductionReportWithDetail["detail"]>,
  orderStatus: WorkOrderStatus,
): StageStates {
  const states = {} as StageStates;

  for (const step of productionSteps) {
    const carrying = reports.filter((report) => {
      if (report.report_type !== step.reportType || report.status === "rejected") return false;
      // Stockage waits on validation — a draft packing report has posted nothing.
      if (step.id === "stockage" && report.status !== "validated") return false;
      const detail = details.get(report.id);
      return Boolean(detail) && SIGNALS[step.id](detail!);
    });

    if (carrying.length === 0) {
      states[step.id] = EMPTY_STATE;
      continue;
    }

    const newestFirst = [...carrying].sort((a, b) => b.report_date.localeCompare(a.report_date));
    const allValidated = carrying.every((report) => report.status === "validated");
    states[step.id] = {
      // A closed OF has nothing outstanding — closing is blocked while reports
      // are unfinished — so whatever it filed reads as done.
      status: allValidated || orderStatus === "closed" ? "done" : "pending",
      reports: newestFirst,
      reportCount: carrying.length,
      lastReportDate: newestFirst[0].report_date,
    };
  }

  return states;
}
