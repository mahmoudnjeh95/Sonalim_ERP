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

// --- Tags (specialties, sharing core.product_tags) -------------------------------------

export interface PartnerTagLink {
  partner_id: string;
  tag_id: string;
  tag_name: string;
  is_preferred: boolean;
  lead_time_days: number | null;
  min_order_qty: number | null;
}

export function listTagsForPartner(token: string, partnerId: string) {
  return apiFetch<PartnerTagLink[]>(`/core/partners/${partnerId}/tags`, { token });
}

export function setPartnerTags(token: string, partnerId: string, tagIds: string[]) {
  return apiFetch<PartnerTagLink[]>(`/core/partners/${partnerId}/tags`, { method: "PUT", token, body: { tag_ids: tagIds } });
}

export interface UpdatePartnerTagLinkInput {
  is_preferred?: boolean;
  lead_time_days?: number;
  min_order_qty?: number;
}

export function updatePartnerTagLink(token: string, partnerId: string, tagId: string, input: UpdatePartnerTagLinkInput) {
  return apiFetch<PartnerTagLink>(`/core/partners/${partnerId}/tags/${tagId}`, { method: "PATCH", token, body: input });
}
