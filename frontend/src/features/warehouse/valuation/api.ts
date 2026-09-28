import { apiFetch } from "../../../lib/api";

export interface ProductValuation {
  product_id: string;
  quantity: number;
  value: number;
  unvalued_quantity: number;
  average_unit_cost: number | null;
  currency: "XOF";
}

export interface CostLayer {
  id: string;
  product_id: string;
  reference: string;
  move_type: string;
  quantity_in: number;
  quantity_remaining: number;
  unit_cost: number | null;
  received_at: string;
}

export const VALUATION_QUERY_KEY = ["warehouse", "valuation"] as const;

export function costLayersQueryKey(productId: string) {
  return ["warehouse", "valuation", productId, "layers"] as const;
}

export function getValuation(token: string) {
  return apiFetch<ProductValuation[]>("/warehouse/valuation", { token });
}

export function listCostLayers(token: string, productId: string) {
  return apiFetch<CostLayer[]>(`/warehouse/valuation/${productId}/layers`, { token });
}
