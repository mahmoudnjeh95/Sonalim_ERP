import { apiFetch } from "../../../lib/api";

// core.audit_log — the single cross-module audit trail. Every module's
// mutations write here via core.audit.record_audit(); this is the one read
// path for all of them (see erp-platform-architecture SKILL.md: "do not
// build a per-module audit table or a parallel history endpoint").
export interface AuditLogEntry {
  id: string;
  actor_id: string;
  actor_email: string | null;
  action: string;
  entity_type: string;
  entity_id: string;
  occurred_at: string;
  payload: Record<string, unknown>;
}

export function listAuditLog(
  token: string,
  params: { entity_type?: string; entity_id?: string; limit?: number } = {},
) {
  const query = new URLSearchParams();
  if (params.entity_type) query.set("entity_type", params.entity_type);
  if (params.entity_id) query.set("entity_id", params.entity_id);
  if (params.limit) query.set("limit", String(params.limit));
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return apiFetch<AuditLogEntry[]>(`/core/audit-log${suffix}`, { token });
}
