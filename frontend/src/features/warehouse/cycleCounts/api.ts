import { apiFetch } from "../../../lib/api";

export type CycleCountStatus = "draft" | "in_progress" | "completed" | "cancelled";
export type CycleCountType = "scheduled" | "blind";
export type CycleCountLineStatus = "pending" | "counted";
export type CycleCountLineResolution = "matched" | "approved" | "rejected" | null;

export interface CycleCount {
  id: string;
  number: string | null;
  site_id: string;
  scope_location_id: string | null;
  count_type: CycleCountType;
  status: CycleCountStatus;
  scheduled_for: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_by: string;
  created_at: string;
}

export interface CycleCountLine {
  id: string;
  cycle_count_id: string;
  location_id: string;
  product_id: string;
  // null while a blind count's line is still pending -- masked, not just zero.
  expected_quantity: number | null;
  counted_quantity: number | null;
  status: CycleCountLineStatus;
  resolution: CycleCountLineResolution;
  counted_by: string | null;
  counted_at: string | null;
  resolved_by: string | null;
  resolved_at: string | null;
  // Two equal counts settle a line, two different ones need a third. counted_quantity is the settled
  // figure; the raw counts stay null until then, so only their number is known while counting.
  count_1: number | null;
  count_2: number | null;
  count_3: number | null;
  counts_recorded: number;
}

export interface CycleCountDetail extends CycleCount {
  lines: CycleCountLine[];
}

export const CYCLE_COUNTS_QUERY_KEY = ["warehouse", "cycleCounts"] as const;

export function cycleCountQueryKey(id: string) {
  return ["warehouse", "cycleCounts", id] as const;
}

export function listCycleCounts(token: string, params: { site_id?: string; status?: CycleCountStatus } = {}) {
  const query = new URLSearchParams();
  if (params.site_id) query.set("site_id", params.site_id);
  if (params.status) query.set("status", params.status);
  const suffix = query.size > 0 ? `?${query}` : "";
  return apiFetch<CycleCount[]>(`/warehouse/cycle-counts${suffix}`, { token });
}

export interface FrozenLocation {
  cycle_count_id: string;
  number: string;
  name: string;
}

export function listFrozenLocations(token: string) {
  return apiFetch<FrozenLocation[]>("/warehouse/frozen-locations", { token });
}

export function addCycleCountFoundLine(token: string, cycleCountId: string, input: { location_id: string; product_id: string }) {
  return apiFetch<CycleCountLine>(`/warehouse/cycle-counts/${cycleCountId}/lines`, { method: "POST", token, body: input });
}

export function getCycleCount(token: string, cycleCountId: string) {
  return apiFetch<CycleCountDetail>(`/warehouse/cycle-counts/${cycleCountId}`, { token });
}

export interface CreateCycleCountInput {
  site_id: string;
  scope_location_id?: string | null;
  count_type?: CycleCountType;
  scheduled_for?: string | null;
}

export function createCycleCount(token: string, input: CreateCycleCountInput) {
  return apiFetch<CycleCount>("/warehouse/cycle-counts", { method: "POST", token, body: input });
}

export function startCycleCount(token: string, cycleCountId: string) {
  return apiFetch<CycleCount>(`/warehouse/cycle-counts/${cycleCountId}/start`, { method: "POST", token });
}

export function submitCycleCountLine(token: string, cycleCountId: string, lineId: string, countedQuantity: number) {
  return apiFetch<CycleCountLine>(`/warehouse/cycle-counts/${cycleCountId}/lines/${lineId}/count`, {
    method: "POST",
    token,
    body: { counted_quantity: countedQuantity },
  });
}

export function resolveCycleCountLine(token: string, cycleCountId: string, lineId: string, decision: "approve" | "reject") {
  return apiFetch<CycleCountLine>(`/warehouse/cycle-counts/${cycleCountId}/lines/${lineId}/resolve`, {
    method: "POST",
    token,
    body: { decision },
  });
}

export function completeCycleCount(token: string, cycleCountId: string) {
  return apiFetch<CycleCount>(`/warehouse/cycle-counts/${cycleCountId}/complete`, {
    method: "POST",
    token,
    body: { correlation_id: crypto.randomUUID() },
  });
}

export function cancelCycleCount(token: string, cycleCountId: string) {
  return apiFetch<CycleCount>(`/warehouse/cycle-counts/${cycleCountId}/cancel`, { method: "POST", token });
}
