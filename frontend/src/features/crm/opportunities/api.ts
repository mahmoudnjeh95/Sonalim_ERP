import { apiFetch } from "../../../lib/api";

export type OpportunityStage = "prospecting" | "qualification" | "proposal" | "negotiation" | "won" | "lost";

export interface Opportunity {
  id: string;
  partner_id: string;
  name: string;
  stage: OpportunityStage;
  amount: number;
  expected_close_date: string | null;
}

export interface CreateOpportunityInput {
  partner_id: string;
  name: string;
  amount: number;
  expected_close_date?: string;
}

export interface UpdateOpportunityInput {
  partner_id?: string;
  name?: string;
  amount?: number;
  expected_close_date?: string;
}

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

export function transitionOpportunity(token: string, opportunityId: string, stage: OpportunityStage) {
  return apiFetch<Opportunity>(`/crm/opportunities/${opportunityId}/transition`, {
    method: "POST",
    token,
    body: { stage },
  });
}
