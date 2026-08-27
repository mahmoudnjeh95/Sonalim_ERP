import { apiFetch } from "../../lib/api";

export type PartnerKind = "customer" | "supplier" | "both";
export type PartnerStatus = "active" | "archived";

export interface Partner {
  id: string;
  name: string;
  kind: PartnerKind;
  industry: string | null;
  website: string | null;
  phone: string | null;
  email: string | null;
  status: PartnerStatus;
}

export interface CreatePartnerInput {
  name: string;
  kind: PartnerKind;
  industry?: string;
  website?: string;
  phone?: string;
  email?: string;
}

export interface UpdatePartnerInput {
  name?: string;
  kind?: PartnerKind;
  industry?: string;
  website?: string;
  phone?: string;
  email?: string;
}

export function listPartners(token: string, kind?: PartnerKind) {
  const query = kind ? `?kind=${kind}` : "";
  return apiFetch<Partner[]>(`/core/partners${query}`, { token });
}

export function getPartner(token: string, partnerId: string) {
  return apiFetch<Partner>(`/core/partners/${partnerId}`, { token });
}

export function createPartner(token: string, input: CreatePartnerInput) {
  return apiFetch<Partner>("/core/partners", { method: "POST", token, body: input });
}

export function updatePartner(token: string, partnerId: string, input: UpdatePartnerInput) {
  return apiFetch<Partner>(`/core/partners/${partnerId}`, { method: "PATCH", token, body: input });
}

export function archivePartner(token: string, partnerId: string) {
  return apiFetch<Partner>(`/core/partners/${partnerId}/archive`, { method: "POST", token });
}
