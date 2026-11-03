import { apiFetch } from "../../../lib/api";
import type { Location, LocationType } from "../api";

export const SITES_QUERY_KEY = ["warehouse", "sites"] as const;

export function locationTreeQueryKey(siteId: string) {
  return ["warehouse", "locations", "tree", siteId] as const;
}

export interface Site {
  id: string;
  code: string;
  name: string;
  address: string | null;
  is_active: boolean;
}

export interface CreateSiteInput {
  code: string;
  name: string;
  address?: string;
}

export interface UpdateSiteInput {
  code?: string;
  name?: string;
  address?: string;
  is_active?: boolean;
}

export interface CreateHierarchyLocationInput {
  code: string;
  name: string;
  site_id: string;
  location_type: LocationType;
  parent_location_id?: string | null;
  sequence?: number | null;
  is_blocked?: boolean;
  blocked_reason?: string;
}

export function listSites(token: string) {
  return apiFetch<Site[]>("/warehouse/sites", { token });
}

export function createSite(token: string, input: CreateSiteInput) {
  return apiFetch<Site>("/warehouse/sites", { method: "POST", token, body: input });
}

export function updateSite(token: string, siteId: string, input: UpdateSiteInput) {
  return apiFetch<Site>(`/warehouse/sites/${siteId}`, { method: "PATCH", token, body: input });
}

export function getLocationTree(token: string, siteId: string) {
  const query = new URLSearchParams({ site_id: siteId });
  return apiFetch<Location[]>(`/warehouse/locations/tree?${query}`, { token });
}

export function createHierarchyLocation(token: string, input: CreateHierarchyLocationInput) {
  return apiFetch<Location>("/warehouse/locations", { method: "POST", token, body: input });
}

export function reparentLocation(token: string, locationId: string, parentLocationId: string | null) {
  return apiFetch<Location>(`/warehouse/locations/${locationId}/reparent`, {
    method: "PATCH",
    token,
    body: { parent_location_id: parentLocationId },
  });
}
