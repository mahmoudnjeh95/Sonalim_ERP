/**
 * The tenant's shift and team lists.
 *
 * These were free text on every report form, so the same shift arrived spelled
 * three ways and nothing grouped by it. They live in `core` rather than in
 * production because quality files against the same shifts.
 */
import { apiFetch } from "./api";

export type ReportOptionKind = "shift" | "team";

export interface ReportOption {
  id: string;
  kind: ReportOptionKind;
  label: string;
  sort_order: number;
  is_active: boolean;
}

export const REPORT_OPTIONS_QUERY_KEY = ["core", "report-options"] as const;

export function listReportOptions(token: string, includeInactive = false) {
  const query = includeInactive ? "?include_inactive=true" : "";
  return apiFetch<ReportOption[]>(`/core/report-options${query}`, { token });
}

export function createReportOption(
  token: string,
  input: { kind: ReportOptionKind; label: string; sort_order?: number },
) {
  return apiFetch<ReportOption>("/core/report-options", { method: "POST", token, body: input });
}

export function updateReportOption(
  token: string,
  optionId: string,
  input: { label?: string; sort_order?: number; is_active?: boolean },
) {
  return apiFetch<ReportOption>(`/core/report-options/${optionId}`, {
    method: "PATCH",
    token,
    body: input,
  });
}

/**
 * Remove the option — or retire it, when reports were already filed under its
 * name. The response says which happened so the screen can explain it.
 */
export function deleteReportOption(token: string, optionId: string) {
  return apiFetch<{ outcome: "deleted" | "retired"; option: ReportOption }>(
    `/core/report-options/${optionId}`,
    { method: "DELETE", token },
  );
}

/**
 * The options to offer for one field.
 *
 * A report that already carries a retired name keeps it in the list — otherwise
 * opening an old report to edit it would silently blank the shift it was filed
 * under, and saving would rewrite history.
 */
export function optionsFor(
  options: ReportOption[],
  kind: ReportOptionKind,
  currentValue?: string | null,
): string[] {
  const active = options
    .filter((option) => option.kind === kind && option.is_active)
    .sort((a, b) => a.sort_order - b.sort_order || a.label.localeCompare(b.label))
    .map((option) => option.label);
  if (currentValue && !active.includes(currentValue)) return [currentValue, ...active];
  return active;
}
