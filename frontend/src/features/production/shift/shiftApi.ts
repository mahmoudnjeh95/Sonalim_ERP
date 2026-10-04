import { apiFetch } from "../../../lib/api";

// The paper fiches' order, which is also the order of the screen.
export const SECTION_KEYS = [
  "runs",
  "waste_production",
  "stops",
  "silo",
  "staffing",
  "packing",
  "packet_checks",
  "waste_packing",
  "energy",
] as const;

export type SectionKey = (typeof SECTION_KEYS)[number];
export type SectionStatus = "empty" | "draft" | "submitted" | "nothing_to_report" | "returned";
export type ShiftStatus = "open" | "submitted" | "validated" | "returned";

/** One row of a section table, as the backend stores it. */
export type Row = Record<string, unknown>;
/** A section's rows keyed by part ("runs", "waste_lines", "mold_washes", "energy"...). */
export type SectionPayload = Record<string, unknown>;

export interface SectionState {
  key: SectionKey;
  status: SectionStatus;
  revision: number;
  revised_after_submit: boolean;
  submitted_by: string | null;
  submitted_at: string | null;
  return_reason: string | null;
  /** Present on a single shift, absent on the list. */
  payload?: SectionPayload;
  /** Present on the result of a section action. */
  shift_status?: ShiftStatus;
}

export interface ShiftReport {
  id: string;
  work_center_id: string;
  report_date: string;
  shift: string;
  team: string | null;
  /** The lot new rows start with, from the team and the date; null until the team names a letter. Single shift only. */
  default_lot_number?: string | null;
  conducteur: string | null;
  agent_fabrication: string | null;
  machiniste: string | null;
  aide_machiniste: string | null;
  status: ShiftStatus;
  revision: number;
  created_by: string | null;
  submitted_at: string | null;
  validated_by: string | null;
  validated_at: string | null;
  rejection_reason: string | null;
  sections: SectionState[];
}

export interface SectionRevision {
  revision: number;
  snapshot: SectionPayload;
  reason: string | null;
  actor_id: string | null;
  created_at: string;
  edited_by_validator: boolean;
  edited_after_validation: boolean;
}

export type HeaderFields = Partial<
  Pick<ShiftReport, "team" | "conducteur" | "agent_fabrication" | "machiniste" | "aide_machiniste">
>;

export const SHIFT_REPORTS_QUERY_KEY = ["production", "shift-reports"] as const;

const base = "/production/shift-reports";

export function listShiftReports(
  token: string,
  filters: { report_date?: string; work_center_id?: string; status?: string; of_id?: string } = {},
) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) if (value) params.set(key, value);
  const query = params.toString();
  return apiFetch<ShiftReport[]>(`${base}${query ? `?${query}` : ""}`, { token });
}

export function getShiftReport(token: string, id: string) {
  return apiFetch<ShiftReport>(`${base}/${id}`, { token });
}

export function openShiftReport(
  token: string,
  body: { work_center_id: string; report_date: string; shift: string; team?: string | null },
) {
  return apiFetch<Omit<ShiftReport, "sections">>(base, { method: "POST", body, token });
}

export function updateShiftHeader(token: string, id: string, fields: HeaderFields) {
  return apiFetch<Omit<ShiftReport, "sections">>(`${base}/${id}/header`, { method: "PATCH", body: fields, token });
}

export function saveShiftSection(token: string, id: string, key: SectionKey, payload: SectionPayload, reason?: string) {
  return apiFetch<SectionState>(`${base}/${id}/sections/${key}`, { method: "PUT", body: { payload, reason }, token });
}

/** A validator's correction to a submitted section, mid-review; the reason is required. */
export function validatorEditSection(token: string, id: string, key: SectionKey, payload: SectionPayload, reason: string) {
  return apiFetch<SectionState>(`${base}/${id}/sections/${key}/validator-edit`, { method: "PUT", body: { payload, reason }, token });
}

/** An admin's correction to a section after the shift is already validated; the reason is optional. */
export function unlockedEditSection(token: string, id: string, key: SectionKey, payload: SectionPayload, reason?: string) {
  return apiFetch<SectionState>(`${base}/${id}/sections/${key}/unlocked-edit`, { method: "PUT", body: { payload, reason }, token });
}

export function submitShiftSection(token: string, id: string, key: SectionKey) {
  return apiFetch<SectionState>(`${base}/${id}/sections/${key}/submit`, { method: "POST", token });
}

export function declareSectionEmpty(token: string, id: string, key: SectionKey) {
  return apiFetch<SectionState>(`${base}/${id}/sections/${key}/nothing-to-report`, { method: "POST", token });
}

export function listSectionRevisions(token: string, id: string, key: SectionKey) {
  return apiFetch<SectionRevision[]>(`${base}/${id}/sections/${key}/revisions`, { token });
}

export function validateShiftReport(
  token: string,
  id: string,
  body: {
    seen_revisions?: Record<string, number>;
    shortfall_comment?: string | null;
    /** Where the OFR opened for the shift's rebroyat runs; left out, the production order's own line. */
    regrind_work_center_id?: string | null;
  } = {},
) {
  return apiFetch<ShiftReport>(`${base}/${id}/validate`, { method: "POST", body, token });
}

export function rejectShiftSections(token: string, id: string, body: { sections: SectionKey[]; reason: string }) {
  return apiFetch<ShiftReport>(`${base}/${id}/reject`, { method: "POST", body, token });
}

export function reverseShiftReport(token: string, id: string, body: { reason: string; force?: boolean }) {
  return apiFetch<ShiftReport>(`${base}/${id}/reverse`, { method: "POST", body, token });
}

export function bulkValidateShiftReports(token: string, ids: string[]) {
  return apiFetch<ShiftReport[]>(`${base}/bulk/validate`, { method: "POST", body: { ids }, token });
}

/** One person the fiche's header may name, and the position that puts them on the list. */
export interface ShiftRolePerson {
  id: string;
  name: string;
  position_id: string;
}

/** Who each of the four person fields may name, and the HR positions each role is mapped to. */
export interface ShiftRolePeople {
  people: Record<string, ShiftRolePerson[]>;
  positions: Record<string, string[]>;
}

export const SHIFT_ROLE_PEOPLE_QUERY_KEY = ["production", "shift-roles", "people"] as const;

export function listShiftRolePeople(token: string) {
  return apiFetch<ShiftRolePeople>("/production/shift-roles/people", { token });
}

export function setShiftRolePositions(token: string, role: string, positionIds: string[]) {
  return apiFetch<{ role: string; position_ids: string[] }>(`/production/shift-roles/${role}/positions`, {
    method: "PUT",
    token,
    body: { position_ids: positionIds },
  });
}
