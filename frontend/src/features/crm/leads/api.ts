import { apiFetch } from "../../../lib/api";

export type LeadStatus = "new" | "qualified" | "converted" | "disqualified";
export type Priority = "low" | "medium" | "high";

export interface Lead {
  id: string;
  contact_name: string;
  email: string;
  status: LeadStatus;
  source: string | null;
  owner_id: string | null;
  priority: Priority;
  disqualify_reason: string | null;
}

export interface CreateLeadInput {
  contact_name: string;
  email: string;
  source?: string;
  owner_id?: string;
  priority?: Priority;
}

export interface UpdateLeadInput {
  contact_name?: string;
  email?: string;
  source?: string;
  owner_id?: string;
  priority?: Priority;
}

export const LEAD_SOURCES = ["website", "referral", "trade_show", "cold_call", "social_media", "other"] as const;
export type LeadSource = (typeof LEAD_SOURCES)[number];

export function listLeads(token: string) {
  return apiFetch<Lead[]>("/crm/leads", { token });
}

export function createLead(token: string, input: CreateLeadInput) {
  return apiFetch<Lead>("/crm/leads", {
    method: "POST",
    token,
    body: input,
  });
}

export function updateLead(token: string, leadId: string, input: UpdateLeadInput) {
  return apiFetch<Lead>(`/crm/leads/${leadId}`, { method: "PATCH", token, body: input });
}

export function qualifyLead(token: string, leadId: string, correlationId: string) {
  return apiFetch<Lead>(`/crm/leads/${leadId}/qualify`, {
    method: "POST",
    token,
    body: { correlation_id: correlationId },
  });
}

export function disqualifyLead(token: string, leadId: string, reason: string, correlationId: string) {
  return apiFetch<Lead>(`/crm/leads/${leadId}/disqualify`, {
    method: "POST",
    token,
    body: { reason, correlation_id: correlationId },
  });
}

export interface ConvertLeadResult {
  id: string;
  status: LeadStatus;
  partner: { id: string; name: string };
  opportunity: { id: string; name: string; stage: string; amount: number };
}

export function convertLead(token: string, leadId: string, correlationId: string, existingPartnerId?: string) {
  return apiFetch<ConvertLeadResult>(`/crm/leads/${leadId}/convert`, {
    method: "POST",
    token,
    body: { correlation_id: correlationId, existing_partner_id: existingPartnerId },
  });
}
