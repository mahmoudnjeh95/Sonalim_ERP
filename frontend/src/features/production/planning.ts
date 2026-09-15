/**
 * Production planning: turns open demand (draft sales orders, most of them born
 * from a won CRM deal) into a prioritized list of shortfalls a supervisor can
 * convert into a Work Order (OF).
 *
 * Pure and framework-free so the aggregation logic — the part worth getting
 * right — is unit-testable without a running app.
 */
import type { Opportunity } from "../crm/opportunities/api";
import type { Location, StockItem } from "../warehouse/api";
import type { SalesOrder } from "../sales/api";
import type { WorkOrder } from "./api";

const OPEN_WORK_ORDER_STATUSES = new Set(["planned", "ongoing", "suspended"]);

export interface ContributingOrder {
  order_id: string;
  partner_id: string;
  quantity: number;
}

export interface ProductionSuggestion {
  product_id: string;
  demandQty: number;
  availableQty: number;
  openOfQty: number;
  shortfallQty: number;
  /** Earliest requested_ship_date among contributing orders, or null if none set. */
  earliestShipDate: string | null;
  /**
   * Internal-only ranking signal (sum of each contributing order's value —
   * the linked opportunity's amount when there is one, else the order's own
   * total_amount). Not attributed per line, so it isn't safe to display as a
   * per-product monetary total, only to sort by.
   */
  value: number;
  contributingOrders: ContributingOrder[];
}

/** Stock available for promising, per product: on-hand minus reserved, at non-blocked locations only. */
function computeAvailableByProduct(stockItems: StockItem[], locations: Location[]): Map<string, number> {
  const blockedLocationIds = new Set(locations.filter((location) => location.is_blocked).map((location) => location.id));
  const availableByProduct = new Map<string, number>();
  for (const item of stockItems) {
    if (blockedLocationIds.has(item.location_id)) continue;
    const current = availableByProduct.get(item.product_id) ?? 0;
    availableByProduct.set(item.product_id, current + (item.quantity_on_hand - item.quantity_reserved));
  }
  return availableByProduct;
}

/** Quantity already planned for each product by an OF that hasn't closed or been cancelled. */
function computeOpenOfByProduct(workOrders: WorkOrder[]): Map<string, number> {
  const openOfByProduct = new Map<string, number>();
  for (const workOrder of workOrders) {
    if (!workOrder.product_id || workOrder.planned_quantity === null) continue;
    if (!OPEN_WORK_ORDER_STATUSES.has(workOrder.status)) continue;
    const current = openOfByProduct.get(workOrder.product_id) ?? 0;
    openOfByProduct.set(workOrder.product_id, current + workOrder.planned_quantity);
  }
  return openOfByProduct;
}

function orderValue(order: SalesOrder, opportunities: Opportunity[]): number {
  const opportunity = order.opportunity_id ? opportunities.find((o) => o.id === order.opportunity_id) : undefined;
  return opportunity ? opportunity.amount : order.total_amount;
}

function earlierDate(a: string | null, b: string | null): string | null {
  if (!a) return b;
  if (!b) return a;
  return a < b ? a : b;
}

export function computeProductionSuggestions(
  orders: SalesOrder[],
  opportunities: Opportunity[],
  stockItems: StockItem[],
  locations: Location[],
  workOrders: WorkOrder[],
): ProductionSuggestion[] {
  const availableByProduct = computeAvailableByProduct(stockItems, locations);
  const openOfByProduct = computeOpenOfByProduct(workOrders);

  const demandByProduct = new Map<
    string,
    { qty: number; earliestShipDate: string | null; value: number; contributingOrders: ContributingOrder[] }
  >();

  for (const order of orders) {
    if (order.status !== "draft") continue;
    const value = orderValue(order, opportunities);
    for (const line of order.lines) {
      const entry = demandByProduct.get(line.product_id) ?? { qty: 0, earliestShipDate: null, value: 0, contributingOrders: [] };
      entry.qty += line.quantity;
      entry.value += value;
      entry.earliestShipDate = earlierDate(entry.earliestShipDate, order.requested_ship_date);
      entry.contributingOrders.push({ order_id: order.id, partner_id: order.partner_id, quantity: line.quantity });
      demandByProduct.set(line.product_id, entry);
    }
  }

  const suggestions: ProductionSuggestion[] = [];
  for (const [productId, entry] of demandByProduct) {
    const availableQty = availableByProduct.get(productId) ?? 0;
    const openOfQty = openOfByProduct.get(productId) ?? 0;
    const shortfallQty = Math.max(0, entry.qty - availableQty - openOfQty);
    if (shortfallQty <= 0) continue;
    suggestions.push({
      product_id: productId,
      demandQty: entry.qty,
      availableQty,
      openOfQty,
      shortfallQty,
      earliestShipDate: entry.earliestShipDate,
      value: entry.value,
      contributingOrders: entry.contributingOrders,
    });
  }

  suggestions.sort((a, b) => {
    if (a.earliestShipDate !== b.earliestShipDate) {
      if (!a.earliestShipDate) return 1;
      if (!b.earliestShipDate) return -1;
      return a.earliestShipDate < b.earliestShipDate ? -1 : 1;
    }
    return b.value - a.value;
  });
  return suggestions;
}
