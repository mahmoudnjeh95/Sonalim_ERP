import type { BadgeProps } from "../components/ui/badge";
import type { StockMove, StockMoveType } from "../features/warehouse/api";
import { useI18n } from "./i18n";

export const MOVE_TYPE_VARIANT: Record<StockMoveType, BadgeProps["variant"]> = {
  receipt: "success",
  issue: "warning",
  adjustment: "accent",
  reservation: "default",
  reservation_released: "outline",
  production: "primary",
  send_to_production: "primary",
  production_consumption: "primary",
  transfer_out: "warning",
  transfer_in: "success",
  admin_correction: "destructive",
};

export function useMoveTypeLabels(): Record<StockMoveType, string> {
  const { t } = useI18n();
  return {
    receipt: t("warehouse.stockHistory.type.receipt"),
    issue: t("warehouse.stockHistory.type.issue"),
    adjustment: t("warehouse.stockHistory.type.adjustment"),
    reservation: t("warehouse.stockHistory.type.reservation"),
    reservation_released: t("warehouse.stockHistory.type.reservationReleased"),
    production: t("warehouse.stockHistory.type.production"),
    send_to_production: t("warehouse.stockHistory.type.sendToProduction"),
    production_consumption: t("warehouse.stockHistory.type.productionConsumption"),
    transfer_out: t("warehouse.stockHistory.type.transferOut"),
    transfer_in: t("warehouse.stockHistory.type.transferIn"),
    admin_correction: t("warehouse.stockHistory.type.adminCorrection"),
  };
}

/**
 * Backend references are `{entity_type}:{ulid}` (e.g. "production_report:01M1YH...").
 * Raw ULIDs aren't meaningful to a user, so this maps the prefix to a translated
 * label and keeps only a short suffix of the id -- the full reference stays
 * available as a tooltip (see `title` on the rendered cell).
 */
const REFERENCE_KIND_KEY = {
  purchase_order_receipt: "warehouse.stockHistory.referenceKind.purchaseOrderReceipt",
  sales_order: "warehouse.stockHistory.referenceKind.salesOrder",
  non_conformity: "warehouse.stockHistory.referenceKind.nonConformity",
  work_order: "warehouse.stockHistory.referenceKind.workOrder",
  production_report: "warehouse.stockHistory.referenceKind.productionReport",
  manual_adjustment: "warehouse.stockHistory.referenceKind.manualAdjustment",
} as const;
type ReferenceKind = keyof typeof REFERENCE_KIND_KEY;

/** Call once per render (like useMoveTypeLabels) -- never inside a per-row cell callback. */
export function useReferenceKindLabels(): Record<ReferenceKind, string> {
  const { t } = useI18n();
  return {
    purchase_order_receipt: t("warehouse.stockHistory.referenceKind.purchaseOrderReceipt"),
    sales_order: t("warehouse.stockHistory.referenceKind.salesOrder"),
    non_conformity: t("warehouse.stockHistory.referenceKind.nonConformity"),
    work_order: t("warehouse.stockHistory.referenceKind.workOrder"),
    production_report: t("warehouse.stockHistory.referenceKind.productionReport"),
    manual_adjustment: t("warehouse.stockHistory.referenceKind.manualAdjustment"),
  };
}

function isReferenceKind(kind: string, labels: Record<ReferenceKind, string>): kind is ReferenceKind {
  return kind in labels;
}

/** Pure formatter -- safe to call per row inside a table's .map(). */
export function formatMoveReference(
  reference: string,
  referenceKindLabels: Record<ReferenceKind, string>,
): { label: string; suffix: string | null } {
  const separatorIndex = reference.indexOf(":");
  if (separatorIndex === -1) {
    return { label: isReferenceKind(reference, referenceKindLabels) ? referenceKindLabels[reference] : reference, suffix: null };
  }
  const kind = reference.slice(0, separatorIndex);
  const id = reference.slice(separatorIndex + 1);
  return {
    label: isReferenceKind(kind, referenceKindLabels) ? referenceKindLabels[kind] : kind,
    suffix: id.length > 6 ? id.slice(-6) : id,
  };
}

/**
 * The work order behind a movement, when there is one -- so the UI can show a
 * real "OF-000123" instead of a ULID. Two paths, because only one of them
 * writes `of_id` onto the move (see report_stock_service.py): a production
 * report's `of_id` is stored directly on the move, while a regrind batch's
 * `receive_stock` call has no `of_id` param and instead puts the work order's
 * own id straight in the reference (`work_order:{id}`).
 */
export function relatedWorkOrderId(move: StockMove): string | null {
  if (move.of_id) return move.of_id;
  const separatorIndex = move.reference.indexOf(":");
  if (separatorIndex === -1) return null;
  const kind = move.reference.slice(0, separatorIndex);
  return kind === "work_order" ? move.reference.slice(separatorIndex + 1) : null;
}

/**
 * A move's own `quantity` is stored unsigned; direction comes from
 * `move_type` instead. `adjustment` and `admin_correction` carry their own
 * signed delta already. The rest leave stock ("issue", "production_consumption",
 * "transfer_out", "send_to_production" -- see the matching `post_*`/`issue_stock`
 * calls in modules/warehouse/api/service.py, which all subtract from
 * `quantity_on_hand` even though the move row only ever stores the unsigned
 * amount) or arrive ("receipt", "production", "transfer_in", the two
 * reservation types). Shared here so the moves table, the detail dialog and
 * any added/used rollup (e.g. a per-product history chart) agree on the same
 * sign instead of each re-deriving it.
 */
const OUT_MOVE_TYPES = new Set<StockMoveType>(["issue", "production_consumption", "transfer_out", "send_to_production"]);

export function signedMoveQuantity(move: StockMove): number {
  if (move.move_type === "adjustment" || move.move_type === "admin_correction") return move.quantity;
  if (OUT_MOVE_TYPES.has(move.move_type)) return -Math.abs(move.quantity);
  return move.quantity;
}

/**
 * Only a regrind batch's receipt puts the work order id straight in the
 * reference (`work_order:{id}`) rather than on `of_id` -- see
 * `relatedWorkOrderId`. That makes the reference shape itself a reliable tag
 * for "this stock came from grinding scrap", not just a display hint.
 */
export function relatedRegrindBatchId(move: StockMove): string | null {
  return move.of_id ? null : relatedWorkOrderId(move);
}

/**
 * The purchase-order receipt behind a goods-in movement, when there is one
 * (`purchase_order_receipt:{receipt_id}`, set in confirm_receipt -- see
 * modules/procurement/api/service.py). Lets the detail dialog resolve the
 * receipt to its parent order and link straight to it.
 */
export function relatedPurchaseOrderReceiptId(move: StockMove): string | null {
  const separatorIndex = move.reference.indexOf(":");
  if (separatorIndex === -1) return null;
  const kind = move.reference.slice(0, separatorIndex);
  return kind === "purchase_order_receipt" ? move.reference.slice(separatorIndex + 1) : null;
}
