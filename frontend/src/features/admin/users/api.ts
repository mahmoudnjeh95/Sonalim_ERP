import { apiFetch } from "../../../lib/api";

export interface UserSummary {
  id: string;
  email: string;
  permissions: string[];
}

export interface PermissionCatalogEntry {
  module: string;
  permission: string;
}

export function listUsers(token: string) {
  return apiFetch<UserSummary[]>("/core/users", { token });
}

export function listPermissionCatalog(token: string) {
  return apiFetch<PermissionCatalogEntry[]>("/core/permissions/catalog", { token });
}

export function grantPermission(token: string, userId: string, permission: string) {
  return apiFetch<{ user_id: string; permission: string }>(`/core/users/${userId}/permissions`, {
    method: "POST",
    token,
    body: { permission },
  });
}

export function revokePermission(token: string, userId: string, permission: string) {
  return apiFetch<void>(`/core/users/${userId}/permissions/${encodeURIComponent(permission)}`, {
    method: "DELETE",
    token,
  });
}
