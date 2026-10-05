import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { apiErrorFromResponse, apiFetch, BASE_URL, networkError } from "../../../lib/api";
import type { CheckAction, EquipmentStatus, JobListItem, JobStatus, Outcome, ProductionStage } from "../api";
import type { Period } from "./historyPeriod";

export interface ProductionBlock {
  stops: number;
  stop_minutes: number;
  stops_by_type: { type: string | null; count: number; minutes: number }[];
  breakdowns: number;
  breakdown_minutes: number;
  breakdowns_by_system: { classification: string | null; count: number; minutes: number }[];
  running_minutes: number;
  mtbf_minutes: number | null;
  mttr_minutes: number | null;
}

export interface MaintenanceBlock {
  breakdowns: number;
  preventive: { due: number; closed: number; closed_on_time: number; overdue: number };
  immobilised_minutes: number;
  immobilisations: number;
  mean_immobilisation_minutes: number | null;
  calendar_minutes: number;
  calendar_mtbf_minutes: number | null;
  technician_seconds: number;
  parts: { issued_lines: number; purchase_lines: number };
  /** null when the user may not see costs (warehouse.view_valuation) or the warehouse module is absent. */
  parts_cost: number | null;
  parts_unvalued_quantity: number | null;
  status_changes: number;
}

export interface MachineSummary {
  equipment_id: string;
  code: string;
  name: string;
  work_center_id: string;
  production_stage: ProductionStage | null;
  status: EquipmentStatus;
  archived_at: string | null;
  /** The first view of the machine's plan that has a photo, for its thumbnail. */
  photo_view_id: string | null;
  photo_version: string | null;
}

export interface MachineIndicators extends MachineSummary {
  /** null when production figures are not available. */
  production: ProductionBlock | null;
  maintenance: MaintenanceBlock;
}

export interface IndicatorsResponse {
  from: string;
  to: string;
  costs_visible: boolean;
  production_available: boolean;
  machines: MachineIndicators[];
  unattributed_stops: { count: number; minutes: number } | null;
}

export type JournalStatus = "closed" | "cancelled" | "all";
export type JournalKind = JobListItem["kind"];

export interface JournalRow {
  job_id: string;
  number: string;
  equipment_id: string;
  equipment_code: string;
  equipment_name: string;
  kind: JournalKind;
  priority: JobListItem["priority"];
  title: string;
  status: JobStatus;
  /** Close (or cancel) date; null for a job still open (logbook only). */
  date: string | null;
  due_date: string;
  created_at: string;
  started_at: string | null;
  closed_on_time: boolean | null;
  cancel_reason: string | null;
  chef_name: string | null;
  performers: { employee_id: string; name: string }[];
  technician_seconds: number;
  checks_total: number;
  checks_done: number;
  outcomes: { ok: number; issue: number; not_done: number; pending: number };
  parts: { issued_lines: number; purchase_lines: number };
  parts_cost: number | null;
  machine_stopped: boolean;
  machine_restarted: boolean;
}

export interface JournalResponse {
  from: string;
  to: string;
  costs_visible: boolean;
  rows: JournalRow[];
}

export interface ProductionStopItem {
  started_at: string;
  ended_at: string;
  minutes: number;
  downtime_type: string | null;
  classification: string | null;
  motif: string | null;
  note: string | null;
  corrective_action: string | null;
  report_date: string;
  team: string | null;
  shift_report_id: string;
}

export type TimelineItem =
  | { kind: "job"; at: string; job: JournalRow }
  | { kind: "production_stop"; at: string; stop: ProductionStopItem }
  | { kind: "status_change"; at: string; from_status: EquipmentStatus; to_status: EquipmentStatus; actor_name: string | null };

export interface CheckpointSummary {
  checkpoint_id: string;
  view_id: string;
  view_label: string;
  label: string;
  action: CheckAction;
  measure_unit: string | null;
  sort_order: number;
  archived: boolean;
  checks_count: number;
  issues_count: number;
  last_checked_at: string | null;
  last_outcome: Outcome | null;
  last_measured_value: number | null;
  recent_measures: { at: string; value: number }[];
}

export interface EquipmentHistory {
  equipment: MachineSummary;
  indicators: { production: ProductionBlock | null; maintenance: MaintenanceBlock };
  costs_visible: boolean;
  production_available: boolean;
  timeline: TimelineItem[];
  checkpoints: CheckpointSummary[];
}

export interface PointEntry {
  entry_id: string;
  performer_name: string;
  recorded_by_name: string;
  started_at: string;
  finished_at: string;
  duration_seconds: number;
  duration_source: "timer" | "manual";
  outcome: Outcome;
  note: string | null;
  measured_value: number | null;
  has_photo: boolean;
}

export interface PointAttempt {
  attempt: number;
  entries: PointEntry[];
  review: { verdict: "accepted" | "rejected"; reason: string | null; reviewer_name: string; created_at: string } | null;
}

export interface PointCheck {
  job_id: string;
  job_number: string;
  job_kind: JournalKind;
  job_status: JobStatus;
  check_id: string;
  attempts: PointAttempt[];
}

export interface CheckpointHistory {
  checkpoint: {
    id: string;
    label: string;
    action: CheckAction;
    instructions: string | null;
    measure_unit: string | null;
    requires_photo: boolean;
    view_id: string;
    view_label: string;
    view_version: string | null;
    x_pct: number;
    y_pct: number;
    equipment_id: string;
    equipment_name: string;
    archived_at: string | null;
  };
  summary: { checks_count: number; issues_count: number; last_checked_at: string | null };
  measures: { at: string; value: number; outcome: Outcome; job_number: string }[];
  checks: PointCheck[];
}

export interface JournalFilters extends Period {
  equipment_id?: string;
  kind?: JournalKind;
  status: JournalStatus;
}

function query(params: Record<string, string | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) if (value) search.set(key, value);
  return search.toString();
}

// Every key starts with ["maintenance"], so a maintenance write (which invalidates that prefix) refreshes the history too.
export const historyIndicatorsKey = (period: Period) => ["maintenance", "history", "indicators", period.from, period.to] as const;
export const historyJournalKey = (filters: JournalFilters) => ["maintenance", "history", "journal", filters] as const;
export const equipmentHistoryKey = (equipmentId: string, period: Period) =>
  ["maintenance", "history", "equipment", equipmentId, period.from, period.to] as const;
export const checkpointHistoryKey = (checkpointId: string) => ["maintenance", "history", "checkpoint", checkpointId] as const;

export function useHistoryIndicators(token: string, period: Period) {
  return useQuery({
    queryKey: historyIndicatorsKey(period),
    queryFn: () => apiFetch<IndicatorsResponse>(`/maintenance/history/indicators?${query({ ...period })}`, { token }),
    enabled: !!token,
    placeholderData: keepPreviousData,
  });
}

export function useHistoryJournal(token: string, filters: JournalFilters) {
  return useQuery({
    queryKey: historyJournalKey(filters),
    queryFn: () => apiFetch<JournalResponse>(`/maintenance/history/journal?${query({ ...filters })}`, { token }),
    enabled: !!token,
    placeholderData: keepPreviousData,
  });
}

export function useEquipmentHistory(token: string, equipmentId: string, period: Period) {
  return useQuery({
    queryKey: equipmentHistoryKey(equipmentId, period),
    queryFn: () => apiFetch<EquipmentHistory>(`/maintenance/equipment/${equipmentId}/history?${query({ ...period })}`, { token }),
    enabled: !!token && !!equipmentId,
    placeholderData: keepPreviousData,
  });
}

export function useCheckpointHistory(token: string, checkpointId: string | null) {
  return useQuery({
    queryKey: checkpointHistoryKey(checkpointId ?? ""),
    queryFn: () => apiFetch<CheckpointHistory>(`/maintenance/checkpoints/${checkpointId}/history`, { token }),
    enabled: !!token && !!checkpointId,
  });
}

/** The journal as .xlsx (GET /maintenance/history/journal/export). Bypasses apiFetch, which always parses JSON. */
export async function exportJournalWorkbook(token: string, filters: JournalFilters & { lang: string }): Promise<Blob> {
  let response: Response;
  try {
    response = await fetch(`${BASE_URL}/maintenance/history/journal/export?${query({ ...filters })}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
  } catch {
    throw networkError();
  }
  if (!response.ok) throw await apiErrorFromResponse(response);
  return response.blob();
}
