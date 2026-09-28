import { apiFetch } from "../../../lib/api";

export type ProposalStatus = "open" | "approved" | "dismissed" | "fulfilled";

export interface ReorderRule {
  id: string;
  product_id: string;
  site_id: string | null;
  reorder_point: number;
  order_up_to: number;
  min_order_quantity: number;
  preferred_supplier_id: string | null;
  is_active: boolean;
  created_by: string;
  created_at: string;
}

export interface ReplenishmentProposal {
  id: string;
  rule_id: string;
  product_id: string;
  site_id: string | null;
  available_at_proposal: number;
  quantity: number;
  supplier_id: string | null;
  status: ProposalStatus;
  created_at: string;
  decided_by: string | null;
  decided_at: string | null;
  closed_at: string | null;
}

export const REORDER_RULES_QUERY_KEY = ["warehouse", "reorderRules"] as const;
export const PROPOSALS_QUERY_KEY = ["warehouse", "replenishmentProposals"] as const;

export function listReorderRules(token: string) {
  return apiFetch<ReorderRule[]>("/warehouse/reorder-rules", { token });
}

export interface ReorderRuleInput {
  product_id: string;
  site_id?: string | null;
  reorder_point: number;
  order_up_to: number;
  min_order_quantity?: number;
  preferred_supplier_id?: string | null;
}

export function createReorderRule(token: string, input: ReorderRuleInput) {
  return apiFetch<ReorderRule>("/warehouse/reorder-rules", { method: "POST", token, body: input });
}

export function updateReorderRule(
  token: string,
  ruleId: string,
  input: Partial<Omit<ReorderRuleInput, "product_id" | "site_id">> & { is_active?: boolean },
) {
  return apiFetch<ReorderRule>(`/warehouse/reorder-rules/${ruleId}`, { method: "PATCH", token, body: input });
}

export function deleteReorderRule(token: string, ruleId: string) {
  return apiFetch<void>(`/warehouse/reorder-rules/${ruleId}`, { method: "DELETE", token });
}

export function listProposals(token: string) {
  return apiFetch<ReplenishmentProposal[]>("/warehouse/replenishment/proposals", { token });
}

export function evaluateReplenishment(token: string) {
  return apiFetch<{ created: ReplenishmentProposal[]; fulfilled: ReplenishmentProposal[] }>("/warehouse/replenishment/evaluate", {
    method: "POST",
    token,
  });
}

export function approveProposal(token: string, proposalId: string, input: { quantity?: number; supplier_id?: string | null }) {
  return apiFetch<ReplenishmentProposal>(`/warehouse/replenishment/proposals/${proposalId}/approve`, {
    method: "POST",
    token,
    body: { ...input, correlation_id: crypto.randomUUID() },
  });
}

export function dismissProposal(token: string, proposalId: string) {
  return apiFetch<ReplenishmentProposal>(`/warehouse/replenishment/proposals/${proposalId}/dismiss`, { method: "POST", token });
}
