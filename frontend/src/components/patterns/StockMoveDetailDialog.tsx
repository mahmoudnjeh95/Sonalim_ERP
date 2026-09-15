import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import { formatQuantity } from "../../lib/units";
import {
  formatMoveReference,
  relatedPurchaseOrderReceiptId,
  relatedRegrindBatchId,
  relatedWorkOrderId,
  signedMoveQuantity,
  MOVE_TYPE_VARIANT,
  useReferenceKindLabels,
} from "../../lib/stockMoveTypes";
import { Badge } from "../ui/badge";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../ui/dialog";
import { useScrapTypeLabels } from "../../lib/scrapTypes";
import { getPurchaseOrderReceipt } from "../../features/procurement/api";
import type { StockMove } from "../../features/warehouse/api";
import type { RegrindScrapInput } from "../../features/production/api";

function formatWhenFull(iso: string, language: string) {
  return new Date(iso).toLocaleString(language === "fr" ? "fr-FR" : "en-US", { dateStyle: "long", timeStyle: "medium" });
}

/**
 * Opened from a click on any stock-move row -- the table only has room for a
 * short label per column (truncated type, id-suffixed reference), so this is
 * where the full record lives. Deliberately shows no raw id: the reference is
 * reduced to its human label, and the work order behind the movement (when
 * there is one) is shown by its own "OF-..." reference, not `of_id`.
 */
export function StockMoveDetailDialog({
  move,
  moveTypeLabel,
  productLabel,
  productSku,
  locationLabel,
  locationCode,
  unit,
  workOrders,
  productName,
  regrindSources,
  onClose,
}: {
  move: StockMove;
  moveTypeLabel: string;
  productLabel: string;
  productSku?: string | null;
  locationLabel: string;
  locationCode?: string | null;
  unit: string | null;
  /** Looked up against `relatedWorkOrderId(move)` -- omit the "Work order" row entirely when not given or not found. */
  workOrders?: { id: string; reference: string }[];
  /** Resolves an arbitrary product id to its name -- used for the "Sourced from" section's own products, not this move's. */
  productName?: (id: string) => string;
  /** Scrap inputs behind a regrind receipt, keyed by the regrind batch's own work order id (`relatedRegrindBatchId(move)`). Omit the section entirely when there's nothing for this move. */
  regrindSources?: Record<string, RegrindScrapInput[]>;
  onClose: () => void;
}) {
  const { session } = useAuth();
  const token = session!.token;
  const { t, language } = useI18n();
  const referenceKindLabels = useReferenceKindLabels();
  const scrapTypeLabels = useScrapTypeLabels();
  const { label: referenceLabel } = formatMoveReference(move.reference, referenceKindLabels);
  const workOrderId = relatedWorkOrderId(move);
  const workOrder = workOrderId ? workOrders?.find((wo) => wo.id === workOrderId) : undefined;
  const signedQuantity = signedMoveQuantity(move);
  const regrindBatchId = relatedRegrindBatchId(move);
  const sources = regrindBatchId ? regrindSources?.[regrindBatchId] : undefined;
  const receiptId = relatedPurchaseOrderReceiptId(move);
  const { data: receipt } = useQuery({
    queryKey: ["procurement", "receipts", receiptId],
    queryFn: () => getPurchaseOrderReceipt(token, receiptId!),
    enabled: receiptId !== null,
  });

  const rows: { label: string; value: React.ReactNode }[] = [
    { label: t("warehouse.stockHistory.column.when"), value: formatWhenFull(move.created_at, language) },
    {
      label: t("warehouse.stockHistory.column.product"),
      value: (
        <>
          {productLabel}
          {productSku && <span className="ml-1.5 text-xs text-muted-foreground">({productSku})</span>}
        </>
      ),
    },
    {
      label: t("warehouse.stockHistory.column.location"),
      value: (
        <>
          {locationLabel}
          {locationCode && <span className="ml-1.5 text-xs text-muted-foreground">({locationCode})</span>}
        </>
      ),
    },
    { label: t("warehouse.stockHistory.column.reference"), value: referenceLabel },
    ...(workOrder
      ? [
          {
            label: t("warehouse.stockHistory.detail.workOrder"),
            value: (
              <Link to={`/production/work-orders/${workOrder.id}`} className="text-primary hover:underline">
                {workOrder.reference}
              </Link>
            ),
          },
        ]
      : []),
    ...(receipt
      ? [
          {
            label: t("warehouse.stockHistory.detail.purchaseOrder"),
            value: (
              <Link to={`/procurement?order=${receipt.purchase_order_id}`} className="text-primary hover:underline">
                {t("warehouse.stockHistory.detail.viewPurchaseOrder")}
              </Link>
            ),
          },
        ]
      : []),
    { label: t("warehouse.stockHistory.column.reason"), value: move.reason || "—" },
  ];

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex flex-wrap items-center gap-2">
            <Badge variant={MOVE_TYPE_VARIANT[move.move_type]} dot>
              {moveTypeLabel}
            </Badge>
            <span className={`tabular-nums ${signedQuantity < 0 ? "text-destructive" : "text-success"}`}>
              {signedQuantity > 0 ? "+" : ""}
              {formatQuantity(signedQuantity, unit)}
            </span>
          </DialogTitle>
          <DialogDescription>{productLabel}</DialogDescription>
        </DialogHeader>

        <dl className="grid grid-cols-1 gap-x-6 gap-y-2">
          {rows.map((row) => (
            <div key={row.label} className="flex items-baseline justify-between gap-3">
              <dt className="shrink-0 text-sm text-muted-foreground">{row.label}</dt>
              <dd className="min-w-0 text-right text-sm font-medium">{row.value}</dd>
            </div>
          ))}
        </dl>

        {sources && sources.length > 0 && (
          <div className="space-y-1.5 border-t border-border pt-3">
            <p className="text-sm text-muted-foreground">{t("warehouse.stockHistory.detail.regrindSources")}</p>
            <ul className="space-y-1">
              {sources.map((source) => {
                const sourceWorkOrder = source.work_order_id ? workOrders?.find((wo) => wo.id === source.work_order_id) : undefined;
                return (
                  <li key={source.id} className="flex items-baseline justify-between gap-3 text-sm">
                    <span className="min-w-0 truncate text-muted-foreground">
                      {sourceWorkOrder ? (
                        <Link to={`/production/work-orders/${sourceWorkOrder.id}`} className="text-primary hover:underline">
                          {sourceWorkOrder.reference}
                        </Link>
                      ) : (
                        "—"
                      )}
                      {" · "}
                      {scrapTypeLabels[source.scrap_type]}
                      {" · "}
                      {productName ? productName(source.product_id) : source.product_id}
                    </span>
                    <span className="shrink-0 font-medium tabular-nums">{formatQuantity(source.quantity, unit)}</span>
                  </li>
                );
              })}
            </ul>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
