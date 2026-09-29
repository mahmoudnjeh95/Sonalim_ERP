import { apiFetch } from "../../lib/api";

export type PresenceStatus = "present" | "absent" | "late" | "leave" | "holiday" | "rest" | "sick" | "mission" | "suspended";
export type PresenceSource = "manual" | "clock" | "leave" | "holiday";
/** What a supervisor may pick in a grid: leave days come only from an approved leave request. */
export const ENTERABLE_STATUSES: PresenceStatus[] = ["present", "late", "absent", "sick", "mission", "suspended", "holiday", "rest"];
export const WORKED_STATUSES: PresenceStatus[] = ["present", "late", "mission"];

export interface ScheduleDay { weekday: number; start_minute: number; end_minute: number; break_minutes: number }
export interface WorkSchedule { id: string; code: string; name: string; is_night: boolean; active: boolean; days: ScheduleDay[] }
export interface ScheduleInput { code: string; name: string; is_night: boolean; days: ScheduleDay[] }
export interface RotationPattern { id: string; code: string; name: string; anchor_date: string; active: boolean; schedule_ids: string[] }
export interface RotationInput { code: string; name: string; anchor_date: string; schedule_ids: string[] }
export interface ScheduleAssignment {
  id: string; employee_id: string; employee_no: string; full_name: string; schedule_id: string | null; schedule_code: string | null;
  rotation_pattern_id: string | null; rotation_code: string | null; rotation_offset_weeks: number; valid_from: string; valid_to: string | null;
}
export interface AssignmentInput {
  employee_id: string; schedule_id: string | null; rotation_pattern_id: string | null; rotation_offset_weeks: number; valid_from: string; valid_to: string | null;
}
export interface PublicHoliday { id: string; country_code: string; holiday_date: string; name: string; paid: boolean; confirmed: boolean }
export interface HolidayInput { country_code: string; holiday_date: string; name: string; paid: boolean; confirmed: boolean }
export interface PresenceSettingsValues {
  night_start_minute: number | null; night_end_minute: number | null; punch_attach_minutes: number | null;
  punch_dedupe_seconds: number | null; late_grace_minutes: number | null;
}
export interface PresenceSettings extends PresenceSettingsValues { confirmed: boolean; confirmed_at: string | null }

export interface PresenceRecord {
  id: string; status: PresenceStatus; source: PresenceSource; scheduled_minutes: number; worked_minutes: number; late_minutes: number;
  ot_minutes_day: number; ot_minutes_night: number; ot_minutes_rest_holiday: number; night_minutes: number; justified: boolean;
  note: string | null; locked: boolean; leave_request_id: string | null;
}
export interface GridDay {
  work_date: string; employed: boolean; assigned: boolean; schedule_id: string | null; schedule_code: string | null;
  is_working_day: boolean; is_holiday: boolean; planned_minutes: number; default_status: PresenceStatus | null; record: PresenceRecord | null;
}
export interface GridRow { employee_id: string; employee_no: string; full_name: string; department_id: string | null; days: GridDay[] }
export interface EmployeeMonth extends GridRow { period: string; closed: boolean }
export interface PresenceEntry {
  employee_id: string; work_date: string; status: PresenceStatus; worked_minutes: number | null; late_minutes: number;
  ot_minutes_day: number; ot_minutes_night: number; justified: boolean; note: string | null;
}
export interface PresenceMonth { period: string; status: "open" | "closed"; closed_by: string | null; closed_at: string | null; payroll_locked: boolean }
export interface PresenceGap { employee_id: string; employee_no: string; full_name: string; work_date: string; reason: "missing" | "no_schedule" }
export interface MonthSummary {
  employee_id: string; scheduled_days: number; worked_days: number; unpaid_absence_days: number; paid_leave_days: number; sick_days: number;
  holiday_days: number; holidays_worked_days: number; ot_minutes_day: number; ot_minutes_night: number; ot_minutes_rest_holiday: number;
  night_minutes: number; late_minutes: number;
}
export interface MonthCloseResult { period: string; status: string; locked_rows: number; holiday_rows: number; accruals_posted: number }

export interface ClockProfile {
  id: string; code: string; name: string; delimiter: string; has_header: boolean; badge_column: string; timestamp_column: string;
  time_column: string | null; timestamp_format: string; direction_column: string | null; in_values: string[]; out_values: string[]; active: boolean;
}
export type ClockProfileInput = Omit<ClockProfile, "id" | "active">;
export type ClockImportStatus = "staged" | "committed" | "discarded";
export interface ClockDayLabel { employee_id: string; employee_no: string; full_name: string; work_date: string }
export interface ClockConflict extends ClockDayLabel { kept_status: PresenceStatus; kept_source: PresenceSource; clock_status: PresenceStatus; clock_worked_minutes: number }
export interface ClockAnomaly extends ClockDayLabel { codes: string[] }
export interface ClockCommitResult {
  days_written: number; conflicts: ClockConflict[]; anomalies: ClockAnomaly[]; unscheduled: ClockDayLabel[];
  duplicate_punches: number; outside_range_punches: number;
}
export interface ClockImport {
  id: string; profile_id: string; profile_code: string; file_name: string; date_from: string; date_to: string; status: ClockImportStatus;
  total_rows: number; valid_rows: number; error_rows: number; uploaded_by: string; uploaded_by_email: string | null; uploaded_at: string;
  decided_at: string | null; result: ClockCommitResult | null;
}
export interface ClockImportRow {
  line_no: number; raw: string; badge_no: string | null; employee_id: string | null; employee_no: string | null; full_name: string | null;
  punched_at: string | null; direction: "in" | "out" | "unknown"; error_code: string | null;
}
export interface ClockImportDetail extends ClockImport { rows: ClockImportRow[] }
export interface ClockImportInput { profile_id: string; file_name: string; content: string; date_from: string; date_to: string }

export type LeaveRequestStatus = "pending" | "approved" | "rejected" | "cancelled";
export interface LeaveType {
  id: string; code: string; name_en: string; name_fr: string; paid: boolean; accrual_days_per_month: number; max_carry_over: number | null;
  counts_days: "calendar" | "working"; requires_document: boolean; presence_status: "leave" | "sick"; confirmed: boolean; active: boolean;
}
export type LeaveTypeInput = Omit<LeaveType, "id" | "active">;
export interface LeaveRecord {
  id: string; employee_id: string; employee_no: string; full_name: string; leave_type_id: string | null; leave_type_code: string | null;
  leave_type_name_en: string | null; leave_type_name_fr: string | null; legacy_leave_type: string; start_date: string; end_date: string;
  days: number | null; half_day: boolean; reason: string | null; document_ref: string | null; status: LeaveRequestStatus;
  reviewed_by: string | null; reviewed_at: string | null; review_note: string | null;
}
export interface LeaveRecordInput {
  employee_id: string; leave_type_id: string; start_date: string; end_date: string; half_day: boolean; reason: string | null; document_ref: string | null;
}
export interface LeaveBalance {
  employee_id: string; employee_no: string; full_name: string; leave_type_id: string; leave_type_code: string; tracks_balance: boolean;
  year: number; carried_over: number; accrued: number; taken: number; adjusted: number; available: number;
}
export interface LeaveAdjustInput { employee_id: string; leave_type_id: string; year: number; delta: number; reason: string }
export type LeaveDecision = "approve" | "reject" | "cancel";

export const HR_KEYS = {
  employees: ["hr", "employees"] as const,
  departments: ["hr", "departments"] as const,
  schedules: ["hr", "schedules"] as const,
  rotations: ["hr", "rotations"] as const,
  assignments: ["hr", "schedule-assignments"] as const,
  holidays: ["hr", "public-holidays"] as const,
  settings: ["hr", "presence-settings"] as const,
  presence: ["hr", "presence"] as const,
  clockProfiles: ["hr", "clock-profiles"] as const,
  clockImports: ["hr", "clock-imports"] as const,
  leaveTypes: ["hr", "leave-types"] as const,
  leaveRequests: ["hr", "leave-records"] as const,
  leaveBalances: ["hr", "leave-balances"] as const,
};

function query(params: Record<string, string | number | null | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== "") search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

export interface TeamFilter { departmentId?: string; scheduleId?: string }

export const listSchedules = (token: string) => apiFetch<WorkSchedule[]>("/hr/schedules", { token });
export const createSchedule = (token: string, input: ScheduleInput) => apiFetch<WorkSchedule>("/hr/schedules", { method: "POST", token, body: input });
export const updateSchedule = (token: string, id: string, input: Partial<ScheduleInput> & { active?: boolean }) =>
  apiFetch<WorkSchedule>(`/hr/schedules/${id}`, { method: "PATCH", token, body: input });
export const listRotations = (token: string) => apiFetch<RotationPattern[]>("/hr/rotation-patterns", { token });
export const createRotation = (token: string, input: RotationInput) => apiFetch<RotationPattern>("/hr/rotation-patterns", { method: "POST", token, body: input });
export const updateRotation = (token: string, id: string, input: Partial<RotationInput> & { active?: boolean }) =>
  apiFetch<RotationPattern>(`/hr/rotation-patterns/${id}`, { method: "PATCH", token, body: input });
export const listAssignments = (token: string) => apiFetch<ScheduleAssignment[]>("/hr/schedule-assignments", { token });
export const createAssignment = (token: string, input: AssignmentInput) =>
  apiFetch<ScheduleAssignment>("/hr/schedule-assignments", { method: "POST", token, body: input });
export const updateAssignment = (token: string, id: string, input: Omit<AssignmentInput, "employee_id"> & { clear_valid_to: boolean }) =>
  apiFetch<ScheduleAssignment>(`/hr/schedule-assignments/${id}`, { method: "PATCH", token, body: input });
export const listHolidays = (token: string, year: number) => apiFetch<PublicHoliday[]>(`/hr/public-holidays${query({ year })}`, { token });
export const createHoliday = (token: string, input: HolidayInput) => apiFetch<PublicHoliday>("/hr/public-holidays", { method: "POST", token, body: input });
export const updateHoliday = (token: string, id: string, input: Omit<HolidayInput, "country_code">) =>
  apiFetch<PublicHoliday>(`/hr/public-holidays/${id}`, { method: "PATCH", token, body: input });
export const getPresenceSettings = (token: string) => apiFetch<PresenceSettings>("/hr/presence/settings", { token });
export const savePresenceSettings = (token: string, input: PresenceSettingsValues & { confirm: boolean }) =>
  apiFetch<PresenceSettings>("/hr/presence/settings", { method: "PUT", token, body: input });

export const getPresenceGrid = (token: string, workDate: string, team: TeamFilter) =>
  apiFetch<GridRow[]>(`/hr/presence/grid${query({ work_date: workDate, department_id: team.departmentId, schedule_id: team.scheduleId })}`, { token });
export const getPresenceWeek = (token: string, dateFrom: string, team: TeamFilter) =>
  apiFetch<GridRow[]>(`/hr/presence/week${query({ date_from: dateFrom, department_id: team.departmentId, schedule_id: team.scheduleId })}`, { token });
export const savePresenceDays = (token: string, entries: PresenceEntry[]) =>
  apiFetch<{ saved: number }>("/hr/presence/days", { method: "PUT", token, body: { entries } });
export const getEmployeeMonth = (token: string, employeeId: string, period: string) =>
  apiFetch<EmployeeMonth>(`/hr/presence/employee-month${query({ employee_id: employeeId, period })}`, { token });
export const listPresenceMonths = (token: string, year: number) => apiFetch<PresenceMonth[]>(`/hr/presence/months${query({ year })}`, { token });
export const getMonthGaps = (token: string, period: string) => apiFetch<PresenceGap[]>(`/hr/presence/months/${period}/gaps`, { token });
export const getMonthSummary = (token: string, period: string, employeeId?: string) =>
  apiFetch<MonthSummary[]>(`/hr/presence/months/${period}/summary${query({ employee_id: employeeId })}`, { token });
export const closePresenceMonth = (token: string, period: string) =>
  apiFetch<MonthCloseResult>(`/hr/presence/months/${period}/close`, { method: "POST", token });
export const reopenPresenceMonth = (token: string, period: string, reason: string) =>
  apiFetch<{ period: string; status: string }>(`/hr/presence/months/${period}/reopen`, { method: "POST", token, body: { reason } });

export const listClockProfiles = (token: string) => apiFetch<ClockProfile[]>("/hr/clock-profiles", { token });
export const createClockProfile = (token: string, input: ClockProfileInput) =>
  apiFetch<ClockProfile>("/hr/clock-profiles", { method: "POST", token, body: input });
export const updateClockProfile = (token: string, id: string, input: Partial<Omit<ClockProfileInput, "code">> & { active?: boolean }) =>
  apiFetch<ClockProfile>(`/hr/clock-profiles/${id}`, { method: "PATCH", token, body: input });
export const listClockImports = (token: string) => apiFetch<ClockImport[]>("/hr/clock-imports", { token });
export const getClockImport = (token: string, id: string) => apiFetch<ClockImportDetail>(`/hr/clock-imports/${id}`, { token });
export const stageClockImport = (token: string, input: ClockImportInput) =>
  apiFetch<ClockImportDetail>("/hr/clock-imports", { method: "POST", token, body: input });
export const commitClockImport = (token: string, id: string) =>
  apiFetch<ClockCommitResult & { id: string }>(`/hr/clock-imports/${id}/commit`, { method: "POST", token });
export const discardClockImport = (token: string, id: string) =>
  apiFetch<ClockImportDetail>(`/hr/clock-imports/${id}/discard`, { method: "POST", token });

export const listLeaveTypes = (token: string) => apiFetch<LeaveType[]>("/hr/leave-types", { token });
export const createLeaveType = (token: string, input: LeaveTypeInput) => apiFetch<LeaveType>("/hr/leave-types", { method: "POST", token, body: input });
export const updateLeaveType = (token: string, id: string, input: Partial<Omit<LeaveTypeInput, "code">> & { active?: boolean; clear_max_carry_over?: boolean }) =>
  apiFetch<LeaveType>(`/hr/leave-types/${id}`, { method: "PATCH", token, body: input });
export const fetchLeaveRequests = (token: string) => apiFetch<LeaveRecord[]>("/hr/leave/requests", { token });
export const submitLeaveRequest = (token: string, input: LeaveRecordInput) =>
  apiFetch<LeaveRecord>("/hr/leave/requests", { method: "POST", token, body: input });
export const editLeaveRequest = (token: string, id: string, input: Omit<LeaveRecordInput, "employee_id">) =>
  apiFetch<LeaveRecord>(`/hr/leave/requests/${id}`, { method: "PATCH", token, body: input });
export const decideLeaveRequest = (token: string, id: string, decision: LeaveDecision, note: string | null = null) =>
  apiFetch<LeaveRecord>(`/hr/leave/requests/${id}/${decision}`, { method: "POST", token, body: { note } });
export const listLeaveBalances = (token: string, year: number) => apiFetch<LeaveBalance[]>(`/hr/leave/balances${query({ year })}`, { token });
export const adjustLeaveBalance = (token: string, input: LeaveAdjustInput) =>
  apiFetch<LeaveBalance>("/hr/leave/balances/adjust", { method: "POST", token, body: input });
