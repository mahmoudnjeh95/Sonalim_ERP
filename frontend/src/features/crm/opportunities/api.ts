import { apiFetch } from "../../../lib/api";

export type OpportunityStage = "prospecting" | "qualification" | "proposal" | "negotiation" | "won" | "lost";
export type Priority = "low" | "medium" | "high";

export interface Opportunity {
  id: string;
  partner_id: string;
  name: string;
  stage: OpportunityStage;
  amount: number;
  expected_close_date: string | null;
  probability: number;
  owner_id: string | null;
  priority: Priority;
  lost_reason: string | null;
}

export interface CreateOpportunityInput {
  partner_id: string;
  name: string;
  amount: number;
  expected_close_date?: string;
  probability?: number;
  owner_id?: string;
  priority?: Priority;
}

export interface UpdateOpportunityInput {
  partner_id?: string;
  name?: string;
  amount?: number;
  expected_close_date?: string;
  probability?: number;
  owner_id?: string;
  priority?: Priority;
}

export const DEFAULT_PROBABILITY_BY_STAGE: Record<OpportunityStage, number> = {
  prospecting: 10,
  qualification: 30,
  proposal: 60,
  negotiation: 80,
  won: 100,
  lost: 0,
};

export const NEXT_STAGES: Record<OpportunityStage, OpportunityStage[]> = {
  prospecting: ["qualification", "lost"],
  qualification: ["proposal", "lost"],
  proposal: ["negotiation", "lost"],
  negotiation: ["won", "lost"],
  won: [],
  lost: [],
};

export function listOpportunities(token: string, partnerId?: string) {
  const query = partnerId ? `?partner_id=${encodeURIComponent(partnerId)}` : "";
  return apiFetch<Opportunity[]>(`/crm/opportunities${query}`, { token });
}

export function createOpportunity(token: string, input: CreateOpportunityInput) {
  return apiFetch<Opportunity>("/crm/opportunities", { method: "POST", token, body: input });
}

export function updateOpportunity(token: string, opportunityId: string, input: UpdateOpportunityInput) {
  return apiFetch<Opportunity>(`/crm/opportunities/${opportunityId}`, { method: "PATCH", token, body: input });
}

export function transitionOpportunity(
  token: string,
  opportunityId: string,
  stage: OpportunityStage,
  options?: { lostReason?: string; correlationId?: string },
) {
  return apiFetch<Opportunity>(`/crm/opportunities/${opportunityId}/transition`, {
    method: "POST",
    token,
    body: { stage, lost_reason: options?.lostReason, correlation_id: options?.correlationId },
  });
}
