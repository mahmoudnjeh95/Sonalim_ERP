import { apiFetch } from "../../../lib/api";

export interface RoleRef {
  id: string;
  code: string;
  name: string;
}

export interface UserSummary {
  id: string;
  email: string;
  permissions: string[];
  roles: RoleRef[];
}

export interface PermissionCatalogEntry {
  module: string;
  permission: string;
}

export interface Role {
  id: string;
  code: string;
  name: string;
  description: string | null;
  permissions: string[];
}

export interface RoleInput {
  code: string;
  name: string;
  description?: string | null;
  permissions: string[];
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

export function listRoles(token: string) {
  return apiFetch<Role[]>("/core/roles", { token });
}

export function createRole(token: string, input: RoleInput) {
  return apiFetch<Role>("/core/roles", { method: "POST", token, body: input });
}

export function updateRole(token: string, roleId: string, input: Omit<RoleInput, "code">) {
  return apiFetch<Role>(`/core/roles/${roleId}`, { method: "PATCH", token, body: input });
}

export function deleteRole(token: string, roleId: string) {
  return apiFetch<void>(`/core/roles/${roleId}`, { method: "DELETE", token });
}

export function assignRole(token: string, userId: string, roleId: string) {
  return apiFetch<{ user_id: string; role_id: string }>(`/core/users/${userId}/roles`, {
    method: "POST",
    token,
    body: { role_id: roleId },
  });
}

export function unassignRole(token: string, userId: string, roleId: string) {
  return apiFetch<void>(`/core/users/${userId}/roles/${roleId}`, {
    method: "DELETE",
    token,
  });
}
