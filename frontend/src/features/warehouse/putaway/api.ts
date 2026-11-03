import { apiFetch } from "../../../lib/api";
import type { Location } from "../api";

export interface PutawayRule {
  id: string;
  site_id: string;
  product_id: string;
  target_location_id: string;
  created_by: string;
  created_at: string;
}

export const PUTAWAY_RULES_QUERY_KEY = ["warehouse", "putawayRules"] as const;

export function suggestionsQueryKey(siteId: string, productId: string, fromLocationId: string) {
  return ["warehouse", "putawaySuggestions", siteId, productId, fromLocationId] as const;
}

export function getPutawaySuggestions(token: string, siteId: string, productId: string, fromLocationId: string) {
  const query = new URLSearchParams({ site_id: siteId, product_id: productId, from_location_id: fromLocationId });
  return apiFetch<Location[]>(`/warehouse/putaway/suggestions?${query}`, { token });
}

export function listPutawayRules(token: string, siteId?: string) {
  const query = siteId ? `?${new URLSearchParams({ site_id: siteId })}` : "";
  return apiFetch<PutawayRule[]>(`/warehouse/putaway/rules${query}`, { token });
}

export interface CreatePutawayRuleInput {
  site_id: string;
  product_id: string;
  target_location_id: string;
}

export function createPutawayRule(token: string, input: CreatePutawayRuleInput) {
  return apiFetch<PutawayRule>("/warehouse/putaway/rules", { method: "POST", token, body: input });
}

export function deletePutawayRule(token: string, ruleId: string) {
  return apiFetch<void>(`/warehouse/putaway/rules/${ruleId}`, { method: "DELETE", token });
}

export interface ConfirmPutawayInput {
  site_id: string;
  product_id: string;
  from_location_id: string;
  to_location_id: string;
  quantity: number;
}

export function confirmPutaway(token: string, input: ConfirmPutawayInput) {
  return apiFetch<{ status: string }>("/warehouse/putaway/confirm", {
    method: "POST",
    token,
    body: { ...input, correlation_id: crypto.randomUUID() },
  });
}
