import { apiFetch } from "../../lib/api";

// Quality control and non-conformity. qc is its own module: `of_id` is an opaque
// id here exactly as it is on the backend — anything richer about the OF comes
// from the production API, never from a join.

// --- Quality reports --------------------------------------------------------
//
// Each shift files three reports — daily, conditionnement and quality — so one OF
// carries many quality reports, one per date and shift.

export type QualityReportStatus = "draft" | "submitted" | "validated" | "rejected";

export interface QualityReport {
  id: string;
  shift_report_id: string;
  report_date: string;
  status: QualityReportStatus;
  revision: number;
  team: string | null;
  shift: string | null;
  created_by: string | null;
  submitted_at: string | null;
  validated_by: string | null;
  validated_at: string | null;
  rejection_reason: string | null;
}

export interface QualityReportDetail {
  comments: string | null;
  corrective_action: string | null;
}

export interface ConformityLine {
  id: string;
  shift_packing_row_id: string;
  of_id: string;
  product_id: string;
  conforming_cartons: number;
  non_conforming_cartons: number;
  defect_details: string | null;
}

export interface QualityReportWithDetail extends QualityReport {
  detail: QualityReportDetail | null;
  lines: ConformityLine[];
}

export interface InspectableShiftReport {
  shift_report_id: string;
  work_center_id: string;
  report_date: string;
  shift: string | null;
  team: string | null;
}

export interface ParameterEntry {
  id: string;
  group_key: string;
  entry_label: string | null;
  fields: Record<string, number | string | null>;
}

export function listInspectableShiftReports(token: string) {
  return apiFetch<InspectableShiftReport[]>("/qc/shift-reports", { token });
}

// --- Team conformity ---------------------------------------------------------
//
// Conformity from validated quality reports, bucketed by team and by calendar
// period — the same grouping shape as production's team-performance endpoint,
// so the two compose by (team, period) on the frontend.

export type PerformanceGrain = "day" | "week" | "month" | "year";

export interface TeamConformityRow {
  team: string | null;
  period: string;
  report_count: number;
  conforming_cartons: number;
  non_conforming_cartons: number;
}

export function listQualityTeamPerformance(
  token: string,
  params: { grain: PerformanceGrain; date_from?: string; date_to?: string },
) {
  const query = new URLSearchParams({ grain: params.grain });
  if (params.date_from) query.set("date_from", params.date_from);
  if (params.date_to) query.set("date_to", params.date_to);
  return apiFetch<TeamConformityRow[]>(`/qc/quality-reports/team-performance?${query.toString()}`, { token });
}

export function listQualityReports(
  token: string,
  params: { of_id?: string; status?: QualityReportStatus } = {},
) {
  const query = new URLSearchParams();
  if (params.of_id) query.set("of_id", params.of_id);
  if (params.status) query.set("status", params.status);
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return apiFetch<QualityReport[]>(`/qc/quality-reports${suffix}`, { token });
}

export function getQualityReport(token: string, reportId: string) {
  return apiFetch<QualityReportWithDetail>(`/qc/quality-reports/${reportId}`, { token });
}

export function createQualityReport(token: string, shiftReportId: string) {
  return apiFetch<QualityReportWithDetail>("/qc/quality-reports", {
    method: "POST", token, body: { shift_report_id: shiftReportId },
  });
}

export function updateQualityReport(
  token: string,
  reportId: string,
  input: { lines: Partial<ConformityLine>[]; detail?: Partial<QualityReportDetail> },
) {
  return apiFetch<QualityReportWithDetail>(`/qc/quality-reports/${reportId}`, {
    method: "PATCH", token, body: input,
  });
}

// Edit-in-place. Needs qc.admin_quality_reports — a more trusted right than
// moving a report through its normal workflow.
export function adminUpdateQualityReport(
  token: string,
  reportId: string,
  input: {
    lines?: Partial<ConformityLine>[];
    detail?: Partial<QualityReportDetail>;
    // Re-linking re-derives team, shift and report_date together -- there is
    // no way to set those independently, even here.
    shift_report_id?: string;
    reason?: string;
  },
) {
  return apiFetch<QualityReportWithDetail>(`/qc/quality-reports/${reportId}/admin`, {
    method: "PATCH",
    token,
    body: input,
  });
}

// Deleting takes the report's follow-up window with it. Refused with
// NON_CONFORMITY_ATTACHED while an NC raised from the report is still open,
// because that NC holds product in quarantine.
export function deleteQualityReport(token: string, reportId: string, reason: string) {
  return apiFetch<{ deleted: string }>(`/qc/quality-reports/${reportId}`, {
    method: "DELETE",
    token,
    body: { reason },
  });
}

export function submitQualityReport(token: string, reportId: string) {
  return apiFetch<QualityReport>(`/qc/quality-reports/${reportId}/submit`, { method: "POST", token });
}

// No product_id: follow-ups are opened per conformity line, each of which
// already carries its own product.
export function validateQualityReport(token: string, reportId: string, correlationId: string) {
  return apiFetch<{ report: QualityReport; lines: ConformityLine[]; follow_ups: { follow_up_id: string; of_id: string; window_ends_on: string }[] }>(
    `/qc/quality-reports/${reportId}/validate`,
    { method: "POST", token, body: { correlation_id: correlationId } },
  );
}

export function listParameters(token: string, reportId: string) {
  return apiFetch<ParameterEntry[]>(`/qc/quality-reports/${reportId}/parameters`, { token });
}

export function saveParameterEntry(
  token: string, reportId: string, input: { group_key: string; entry_label?: string | null; fields: Record<string, number | string | null> },
) {
  return apiFetch<ParameterEntry>(`/qc/quality-reports/${reportId}/parameters`, { method: "POST", token, body: input });
}

export function deleteParameterEntry(token: string, reportId: string, entryId: string) {
  return apiFetch<{ deleted: string }>(`/qc/quality-reports/${reportId}/parameters/${entryId}`, { method: "DELETE", token });
}

export function rejectQualityReport(token: string, reportId: string, reason: string) {
  return apiFetch<QualityReport>(`/qc/quality-reports/${reportId}/reject`, {
    method: "POST",
    token,
    body: { reason },
  });
}

export function reviseQualityReport(token: string, reportId: string) {
  return apiFetch<QualityReport>(`/qc/quality-reports/${reportId}/revise`, { method: "POST", token });
}

// --- Follow-up window -------------------------------------------------------

export type FollowUpStatus = "open" | "in_progress" | "completed";

export interface FollowUp {
  id: string;
  quality_report_id: string;
  of_id: string;
  window_ends_on: string;
  observed_on: string;
  status: FollowUpStatus;
  result: string | null;
  observation: string | null;
  actor_id: string | null;
}

// A tenant-wide default with an optional per-product override. product_id null is
// the tenant default row.
export interface FollowUpPolicy {
  product_id: string | null;
  window_days: number;
}

export function listFollowUpPolicies(token: string) {
  return apiFetch<FollowUpPolicy[]>("/qc/follow-up-policies", { token });
}

export function setFollowUpPolicy(token: string, windowDays: number, productId?: string) {
  return apiFetch<FollowUpPolicy>("/qc/follow-up-policies", {
    method: "PUT",
    token,
    body: { window_days: windowDays, product_id: productId },
  });
}

export function listFollowUps(
  token: string,
  params: { quality_report_id?: string; of_id?: string; status?: FollowUpStatus } = {},
) {
  const query = new URLSearchParams();
  if (params.quality_report_id) query.set("quality_report_id", params.quality_report_id);
  if (params.of_id) query.set("of_id", params.of_id);
  if (params.status) query.set("status", params.status);
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return apiFetch<FollowUp[]>(`/qc/follow-ups${suffix}`, { token });
}

export function recordObservation(
  token: string,
  input: { quality_report_id: string; observed_on: string; observation?: string; result?: string },
) {
  return apiFetch<FollowUp>("/qc/follow-ups", { method: "POST", token, body: input });
}

export function transitionFollowUp(token: string, followUpId: string, status: FollowUpStatus, result?: string) {
  return apiFetch<FollowUp>(`/qc/follow-ups/${followUpId}/transition`, {
    method: "POST",
    token,
    body: { status, result },
  });
}

// --- Non-conformity ---------------------------------------------------------

export type NonConformityStatus = "raised" | "quarantined" | "dispositioned" | "closed";
export type NonConformitySeverity = "minor" | "major" | "critical";
export type NcComponent = "product" | "film" | "carton" | "tape";
export type NcDisposition = "regrind" | "dechet" | "rework" | "return_to_stock";

export interface NonConformity {
  id: string;
  reference: string;
  of_id: string;
  quality_report_id: string | null;
  product_id: string;
  quantity: number;
  source_location_id: string;
  quarantine_location_id: string | null;
  defect_type: string;
  severity: NonConformitySeverity;
  status: NonConformityStatus;
  description: string | null;
  corrective_action: string | null;
  raised_by: string | null;
  raised_at: string | null;
  closed_by: string | null;
  closed_at: string | null;
}

export interface DispositionLine {
  component: NcComponent;
  disposition: NcDisposition;
  quantity: number;
  // Resolved server-side for display: the non-conformity's own product's unit
  // for a "product" line, a fixed label for film/carton/tape. Never sent when
  // creating a disposition -- there's nothing for the caller to choose.
  unit: string | null;
  note: string | null;
}

export interface NonConformityWithDispositions extends NonConformity {
  dispositions: DispositionLine[];
}

export interface RaiseNonConformityInput {
  of_id: string;
  product_id: string;
  quantity: number;
  source_location_id: string;
  defect_type: string;
  correlation_id: string;
  // Required: product is segregated into a blocked location the moment it is
  // pulled, so there is never a window where it is rejected but still sellable.
  quarantine_location_id: string;
  severity?: NonConformitySeverity;
  quality_report_id?: string;
  description?: string;
}

export function listNonConformities(
  token: string,
  params: { of_id?: string; status?: NonConformityStatus } = {},
) {
  const query = new URLSearchParams();
  if (params.of_id) query.set("of_id", params.of_id);
  if (params.status) query.set("status", params.status);
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return apiFetch<NonConformity[]>(`/qc/non-conformities${suffix}`, { token });
}

export function getNonConformity(token: string, nonConformityId: string) {
  return apiFetch<NonConformityWithDispositions>(`/qc/non-conformities/${nonConformityId}`, { token });
}

// Works against a closed OF too — the follow-up window outlives production.
// Raising also transfers the product into quarantine in the same transaction.
export function raiseNonConformity(token: string, input: RaiseNonConformityInput) {
  return apiFetch<NonConformity>("/qc/non-conformities", { method: "POST", token, body: input });
}

// Breaks the rejected product into its components: the pasta to rebroyat, the
// film / carton / tape recorded as déchet without a second stock deduction.
export function dispositionNonConformity(
  token: string,
  nonConformityId: string,
  lines: Array<Omit<DispositionLine, "unit" | "note"> & { note?: string }>,
  correlationId: string,
) {
  return apiFetch<NonConformityWithDispositions>(`/qc/non-conformities/${nonConformityId}/disposition`, {
    method: "POST",
    token,
    body: { lines, correlation_id: correlationId },
  });
}

export function closeNonConformity(token: string, nonConformityId: string, correctiveAction: string) {
  return apiFetch<NonConformity>(`/qc/non-conformities/${nonConformityId}/close`, {
    method: "POST",
    token,
    body: { corrective_action: correctiveAction },
  });
}

// Edit-in-place. Needs qc.admin_non_conformities.
export interface DispositionSummaryRow {
  disposition: NcDisposition;
  quantity: number;
  count: number;
  /** Total weight in kg, only when every contributing product has a known net weight. */
  weight_kg: number | null;
}

/**
 * Where rejected product ended up — regrind, déchet, rework, back to stock.
 * Restricted server-side to the `product` component, so quantity is always
 * comparable across rows. Pass `of_id` to scope this to one work order.
 */
export function getDispositionSummary(
  token: string,
  params: { of_id?: string; date_from?: string; date_to?: string } = {},
) {
  const query = new URLSearchParams();
  if (params.of_id) query.set("of_id", params.of_id);
  if (params.date_from) query.set("date_from", params.date_from);
  if (params.date_to) query.set("date_to", params.date_to);
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return apiFetch<DispositionSummaryRow[]>(`/qc/non-conformities/disposition-summary${suffix}`, { token });
}

export function adminUpdateNonConformity(
  token: string,
  nonConformityId: string,
  input: {
    quantity?: number;
    defect_type?: string;
    severity?: NonConformitySeverity;
    description?: string;
    corrective_action?: string;
  },
) {
  return apiFetch<NonConformity>(`/qc/non-conformities/${nonConformityId}`, {
    method: "PATCH",
    token,
    body: input,
  });
}
