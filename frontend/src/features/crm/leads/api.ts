import { apiFetch } from "../../../lib/api";

export type LeadStatus = "new" | "qualified" | "converted";

export interface Lead {
  id: string;
  contact_name: string;
  email: string;
  status: LeadStatus;
}

export interface CreateLeadInput {
  contact_name: string;
  email: string;
}

export interface UpdateLeadInput {
  contact_name?: string;
  email?: string;
}

export function listLeads(token: string) {
  return apiFetch<Lead[]>("/crm/leads", { token });
}

// modules/crm/api/router.py's create/qualify endpoints only return
// {id, status} — the caller merges in what it already knows (the create
// input) for an optimistic row, then the list re-fetch reconciles it.
export function createLead(token: string, input: CreateLeadInput) {
  return apiFetch<{ id: string; status: LeadStatus }>("/crm/leads", {
    method: "POST",
    token,
    body: input,
  });
}

export function updateLead(token: string, leadId: string, input: UpdateLeadInput) {
  return apiFetch<Lead>(`/crm/leads/${leadId}`, { method: "PATCH", token, body: input });
}

export function qualifyLead(token: string, leadId: string, correlationId: string) {
  return apiFetch<{ id: string; status: LeadStatus }>(`/crm/leads/${leadId}/qualify`, {
    method: "POST",
    token,
    body: { correlation_id: correlationId },
  });
}

export interface ConvertLeadResult {
  id: string;
  status: LeadStatus;
  partner: { id: string; name: string };
  opportunity: { id: string; name: string; stage: string; amount: number };
}

export function convertLead(token: string, leadId: string, correlationId: string) {
  return apiFetch<ConvertLeadResult>(`/crm/leads/${leadId}/convert`, {
    method: "POST",
    token,
    body: { correlation_id: correlationId },
  });
}
