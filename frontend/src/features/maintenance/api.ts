import { useQuery, useMutation, useQueryClient, type UseMutationOptions } from "@tanstack/react-query";
import { apiFetch, BASE_URL, apiErrorFromResponse, networkError } from "../../lib/api";
import { listWorkCenters, type WorkCenter } from "../production/api";

export type { WorkCenter };
export { listWorkCenters };

export type EquipmentStatus = "operational" | "down" | "maintenance";

/** The stages of a production line a machine can work at, in the order a line runs them. */
export const PRODUCTION_STAGES = ["versement", "extrusion", "conditionnement"] as const;
export type ProductionStage = (typeof PRODUCTION_STAGES)[number];

export interface Equipment {
  id: string;
  work_center_id: string;
  code: string;
  name: string;
  status: EquipmentStatus;
  /** null for a machine that works at none of the stages. */
  production_stage: ProductionStage | null;
  /** Set when the machine is retired from the active registry. */
  archived_at: string | null;
}

export interface CreateEquipmentInput {
  work_center_id: string;
  code: string;
  name: string;
  production_stage?: ProductionStage | null;
}

export interface UpdateEquipmentInput {
  work_center_id?: string;
  code?: string;
  name?: string;
  /** null clears the stage; leaving it out keeps it. */
  production_stage?: ProductionStage | null;
}

export function listEquipment(token: string) {
  return apiFetch<Equipment[]>("/maintenance/equipment", { token });
}

export function createEquipment(token: string, input: CreateEquipmentInput) {
  return apiFetch<Equipment>("/maintenance/equipment", { method: "POST", token, body: input });
}

export function updateEquipment(token: string, equipmentId: string, input: UpdateEquipmentInput) {
  return apiFetch<Equipment>(`/maintenance/equipment/${equipmentId}`, { method: "PATCH", token, body: input });
}

export function setEquipmentStatus(token: string, equipmentId: string, status: EquipmentStatus) {
  return apiFetch<Equipment>(`/maintenance/equipment/${equipmentId}/status`, { method: "POST", token, body: { status } });
}

export function archiveEquipment(token: string, equipmentId: string) {
  return apiFetch<Equipment>(`/maintenance/equipment/${equipmentId}/archive`, { method: "POST", token });
}

export function unarchiveEquipment(token: string, equipmentId: string) {
  return apiFetch<Equipment>(`/maintenance/equipment/${equipmentId}/unarchive`, { method: "POST", token });
}

// ---------------------------------------------------------------------------
// Maintenance workflow (teams, checkpoint maps, jobs, programs, parts).
// Types and endpoints mirror the API contract in
// docs/superpowers/specs/2026-10-01-maintenance-workflow-design.md verbatim —
// do not rename fields without updating that contract (the backend stream
// builds against the same names).
// ---------------------------------------------------------------------------

export type JobStatus = "planned" | "assigned" | "in_progress" | "submitted" | "rework" | "closed" | "cancelled";
// "rejected" is never stored long: a reject moves the check back to "pending"
// with attempt+1. It stays in the type for completeness (e.g. CheckReview.verdict).
export type CheckState = "pending" | "done" | "accepted" | "rejected";
export type CheckAction = "inspect" | "lubricate" | "tighten" | "clean" | "replace" | "measure" | "other";
export type Outcome = "ok" | "issue" | "not_done";

export interface Team {
  id: string;
  name: string;
  chef_user_id: string | null;
  chef_name: string | null;
  archived_at: string | null;
  members: { employee_id: string; name: string }[];
}

/** GET /team-candidates (HR active employees) and GET /chef-candidates (users with maintenance.execute_jobs). */
export interface Person {
  id: string;
  name: string;
}

export interface Checkpoint {
  id: string;
  view_id: string;
  x_pct: number;
  y_pct: number;
  label: string;
  action: CheckAction;
  instructions: string | null;
  measure_unit: string | null;
  requires_photo: boolean;
  sort_order: number;
  archived_at: string | null;
}

/** Image at GET /views/{id}/image?v=<updated_at>. */
export interface EquipmentView {
  id: string;
  equipment_id: string;
  label: string;
  sort_order: number;
  image_mime: string | null;
  updated_at: string;
  checkpoints: Checkpoint[];
}

export interface JobListItem {
  id: string;
  number: string;
  equipment_id: string;
  equipment_code: string;
  equipment_name: string;
  kind: "preventive" | "corrective";
  priority: "normal" | "urgent";
  title: string;
  status: JobStatus;
  due_date: string;
  team_id: string | null;
  team_name: string | null;
  chef_user_id: string | null;
  chef_name: string | null;
  program_id: string | null;
  occurrence_date: string | null;
  stops_machine: boolean;
  checks_total: number;
  checks_done: number;
  minutes_spent: number;
  overdue: boolean;
  created_at: string;
  started_at: string | null;
  submitted_at: string | null;
  closed_at: string | null;
}

/** Photo at GET /check-entries/{id}/photo. */
export interface CheckEntry {
  id: string;
  attempt: number;
  performer_employee_id: string;
  performer_name: string;
  recorded_by: string;
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

export interface CheckReview {
  id: string;
  attempt: number;
  verdict: "accepted" | "rejected";
  reason: string | null;
  reviewer_id: string;
  reviewer_name: string;
  created_at: string;
}

export interface JobCheck {
  id: string;
  sort_order: number;
  checkpoint_id: string | null;
  view_id: string | null;
  x_pct: number | null;
  y_pct: number | null;
  label: string;
  action: CheckAction;
  instructions: string | null;
  measure_unit: string | null;
  requires_photo: boolean;
  assignee_employee_id: string | null;
  assignee_name: string | null;
  state: CheckState;
  attempt: number;
  entries: CheckEntry[];
  reviews: CheckReview[];
}

export interface JobEvent {
  id: string;
  at: string;
  actor_id: string | null;
  actor_name: string | null;
  kind: string;
  payload: Record<string, unknown>;
}

export interface JobDetail extends JobListItem {
  description: string | null;
  created_by: string;
  created_by_name: string;
  cancel_reason: string | null;
  checks: JobCheck[];
  part_requests: PartRequest[];
  timeline: JobEvent[];
}

export interface Program {
  id: string;
  equipment_id: string;
  equipment_name: string;
  name: string;
  description: string | null;
  interval_value: number;
  interval_unit: "day" | "week" | "month";
  start_date: string;
  lead_days: number;
  estimated_minutes: number | null;
  default_team_id: string | null;
  default_team_name: string | null;
  stops_machine: boolean;
  active: boolean;
  checkpoint_ids: string[];
  next_occurrence: string | null;
}

export interface CalendarProjectedOccurrence {
  program_id: string;
  program_name: string;
  equipment_id: string;
  equipment_name: string;
  date: string;
}

export interface CalendarResponse {
  jobs: JobListItem[];
  projected: CalendarProjectedOccurrence[];
}

export interface PartRequestLine {
  id: string;
  product_id: string;
  product_name: string;
  uom_id: string;
  uom_code: string;
  quantity: number;
  location_id: string | null;
  issued_quantity: number | null;
  purchase_quantity: number | null;
}

export interface PartRequest {
  id: string;
  job_id: string;
  job_number: string;
  equipment_name: string;
  status: "pending" | "approved" | "rejected";
  note: string | null;
  requested_by: string;
  requested_by_name: string;
  requested_at: string;
  decided_by: string | null;
  decided_by_name: string | null;
  decided_at: string | null;
  decision_note: string | null;
  lines: PartRequestLine[];
}

export interface AvailabilityLocation {
  location_id: string;
  location_name: string;
  available: number;
}

export interface AvailabilityLine {
  line_id: string;
  product_id: string;
  locations: AvailabilityLocation[];
}

export interface Availability {
  lines: AvailabilityLine[];
}

// ---------------------------------------------------------------------------
// Query keys
// ---------------------------------------------------------------------------

export const MAINTENANCE_EQUIPMENT_QUERY_KEY = ["maintenance", "equipment"] as const;
export const MAINTENANCE_TEAMS_QUERY_KEY = ["maintenance", "teams"] as const;
export const MAINTENANCE_TEAM_CANDIDATES_QUERY_KEY = ["maintenance", "team-candidates"] as const;
export const MAINTENANCE_CHEF_CANDIDATES_QUERY_KEY = ["maintenance", "chef-candidates"] as const;
export const maintenanceEquipmentViewsKey = (equipmentId: string) => ["maintenance", "views", equipmentId] as const;
export const maintenanceJobsKey = (filters: JobFilters = {}) => ["maintenance", "jobs", filters] as const;
export const maintenanceJobKey = (id: string) => ["maintenance", "job", id] as const;
export const MAINTENANCE_PROGRAMS_QUERY_KEY = ["maintenance", "programs"] as const;
export const maintenanceCalendarKey = (from: string, to: string) => ["maintenance", "calendar", from, to] as const;
export const maintenancePartRequestsKey = (status?: PartRequest["status"]) => ["maintenance", "part-requests", status ?? "all"] as const;
export const maintenancePartRequestAvailabilityKey = (id: string) => ["maintenance", "part-requests", id, "availability"] as const;

/** Every maintenance query key shares this prefix, for a broad invalidation after a mutation that touches more than one list. */
const MAINTENANCE_PREFIX = ["maintenance"] as const;

// ---------------------------------------------------------------------------
// Teams
// ---------------------------------------------------------------------------

export function listTeams(token: string) {
  return apiFetch<Team[]>("/maintenance/teams", { token });
}

export interface CreateTeamInput {
  name: string;
  chef_user_id?: string | null;
}

export function createTeam(token: string, input: CreateTeamInput) {
  return apiFetch<Team>("/maintenance/teams", { method: "POST", token, body: input });
}

export interface UpdateTeamInput {
  name?: string;
  chef_user_id?: string | null;
  archived?: boolean;
}

export function updateTeam(token: string, teamId: string, input: UpdateTeamInput) {
  return apiFetch<Team>(`/maintenance/teams/${teamId}`, { method: "PATCH", token, body: input });
}

export function setTeamMembers(token: string, teamId: string, employeeIds: string[]) {
  return apiFetch<Team>(`/maintenance/teams/${teamId}/members`, { method: "PUT", token, body: { employee_ids: employeeIds } });
}

export function listTeamCandidates(token: string) {
  return apiFetch<Person[]>("/maintenance/team-candidates", { token });
}

export function listChefCandidates(token: string) {
  return apiFetch<Person[]>("/maintenance/chef-candidates", { token });
}

// ---------------------------------------------------------------------------
// Equipment views / checkpoints (maps)
// ---------------------------------------------------------------------------

export function listEquipmentViews(token: string, equipmentId: string, includeArchived = false) {
  const query = includeArchived ? "?include_archived=true" : "";
  return apiFetch<EquipmentView[]>(`/maintenance/equipment/${equipmentId}/views${query}`, { token });
}

export function createEquipmentView(token: string, equipmentId: string, input: { label: string; image: File }) {
  const body = new FormData();
  body.set("label", input.label);
  body.set("image", input.image);
  return apiFetch<EquipmentView>(`/maintenance/equipment/${equipmentId}/views`, { method: "POST", token, body });
}

export interface UpdateViewInput {
  label?: string;
  sort_order?: number;
  image?: File;
}

export function updateEquipmentView(token: string, viewId: string, input: UpdateViewInput) {
  const body = new FormData();
  if (input.label !== undefined) body.set("label", input.label);
  if (input.sort_order !== undefined) body.set("sort_order", String(input.sort_order));
  if (input.image !== undefined) body.set("image", input.image);
  return apiFetch<EquipmentView>(`/maintenance/views/${viewId}`, { method: "PATCH", token, body });
}

/** 204 on success, or throws an ApiError with code VIEW_IN_USE (409) when jobs/programs still reference it. */
export function deleteEquipmentView(token: string, viewId: string) {
  return apiFetch<void>(`/maintenance/views/${viewId}`, { method: "DELETE", token });
}

/** Caller builds an object URL from the blob (an <img src> cannot carry the bearer token); append `?v=<updated_at>` to bust the cache after a replace. */
export async function fetchViewImageBlob(token: string, viewId: string, updatedAt?: string): Promise<Blob> {
  const query = updatedAt ? `?v=${encodeURIComponent(updatedAt)}` : "";
  let response: Response;
  try {
    response = await fetch(`${BASE_URL}/maintenance/views/${viewId}/image${query}`, { headers: { Authorization: `Bearer ${token}` } });
  } catch {
    throw networkError();
  }
  if (!response.ok) throw await apiErrorFromResponse(response);
  return await response.blob();
}

export interface CreateCheckpointInput {
  x_pct: number;
  y_pct: number;
  label: string;
  action: CheckAction;
  instructions?: string | null;
  measure_unit?: string | null;
  requires_photo?: boolean;
}

export function createCheckpoint(token: string, viewId: string, input: CreateCheckpointInput) {
  return apiFetch<Checkpoint>(`/maintenance/views/${viewId}/checkpoints`, { method: "POST", token, body: input });
}

export interface UpdateCheckpointInput {
  x_pct?: number;
  y_pct?: number;
  label?: string;
  action?: CheckAction;
  instructions?: string | null;
  measure_unit?: string | null;
  requires_photo?: boolean;
  sort_order?: number;
}

export function updateCheckpoint(token: string, checkpointId: string, input: UpdateCheckpointInput) {
  return apiFetch<Checkpoint>(`/maintenance/checkpoints/${checkpointId}`, { method: "PATCH", token, body: input });
}

export function archiveCheckpoint(token: string, checkpointId: string) {
  return apiFetch<Checkpoint>(`/maintenance/checkpoints/${checkpointId}/archive`, { method: "POST", token });
}

// ---------------------------------------------------------------------------
// Jobs
// ---------------------------------------------------------------------------

export interface JobFilters {
  /** Comma-joined server-side; pass several statuses to OR them. */
  status?: JobStatus[];
  equipment_id?: string;
  from?: string;
  to?: string;
  /** true -> chef_user_id = the current user. */
  mine?: boolean;
}

export function listJobs(token: string, filters: JobFilters = {}) {
  const query = new URLSearchParams();
  if (filters.status?.length) query.set("status", filters.status.join(","));
  if (filters.equipment_id) query.set("equipment_id", filters.equipment_id);
  if (filters.from) query.set("from", filters.from);
  if (filters.to) query.set("to", filters.to);
  if (filters.mine) query.set("mine", "true");
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return apiFetch<JobListItem[]>(`/maintenance/jobs${suffix}`, { token });
}

export function getJob(token: string, jobId: string) {
  return apiFetch<JobDetail>(`/maintenance/jobs/${jobId}`, { token });
}

export interface CreateJobTaskInput {
  label: string;
  action: CheckAction;
  instructions?: string | null;
}

export interface CreateJobInput {
  equipment_id: string;
  title: string;
  description?: string | null;
  priority: "normal" | "urgent";
  due_date: string;
  stops_machine: boolean;
  checkpoint_ids: string[];
  tasks: CreateJobTaskInput[];
  team_id?: string | null;
  chef_user_id?: string | null;
}

export function createJob(token: string, input: CreateJobInput) {
  return apiFetch<JobDetail>("/maintenance/jobs", { method: "POST", token, body: input });
}

export interface AssignJobInput {
  team_id?: string | null;
  chef_user_id: string;
}

export function assignJob(token: string, jobId: string, input: AssignJobInput) {
  return apiFetch<JobDetail>(`/maintenance/jobs/${jobId}/assign`, { method: "POST", token, body: input });
}

export interface DelegateAssignment {
  check_id: string;
  employee_id: string | null;
}

export function delegateJob(token: string, jobId: string, assignments: DelegateAssignment[]) {
  return apiFetch<JobDetail>(`/maintenance/jobs/${jobId}/delegate`, { method: "POST", token, body: { assignments } });
}

export interface AddCheckEntryInput {
  performer_employee_id: string;
  outcome: Outcome;
  note?: string | null;
  measured_value?: number | null;
  /** Either both started_at/finished_at (timer) or manual_minutes (manual entry). */
  started_at?: string;
  finished_at?: string;
  manual_minutes?: number;
  photo?: File | null;
}

export function addCheckEntry(token: string, jobId: string, checkId: string, input: AddCheckEntryInput) {
  const body = new FormData();
  body.set("performer_employee_id", input.performer_employee_id);
  body.set("outcome", input.outcome);
  if (input.note !== undefined && input.note !== null) body.set("note", input.note);
  if (input.measured_value !== undefined && input.measured_value !== null) body.set("measured_value", String(input.measured_value));
  if (input.started_at !== undefined) body.set("started_at", input.started_at);
  if (input.finished_at !== undefined) body.set("finished_at", input.finished_at);
  if (input.manual_minutes !== undefined) body.set("manual_minutes", String(input.manual_minutes));
  if (input.photo) body.set("photo", input.photo);
  return apiFetch<JobDetail>(`/maintenance/jobs/${jobId}/checks/${checkId}/entries`, { method: "POST", token, body });
}

/** Caller builds an object URL from the blob (an <img src> cannot carry the bearer token). */
export async function fetchCheckEntryPhotoBlob(token: string, entryId: string): Promise<Blob> {
  let response: Response;
  try {
    response = await fetch(`${BASE_URL}/maintenance/check-entries/${entryId}/photo`, { headers: { Authorization: `Bearer ${token}` } });
  } catch {
    throw networkError();
  }
  if (!response.ok) throw await apiErrorFromResponse(response);
  return await response.blob();
}

export function submitJob(token: string, jobId: string) {
  return apiFetch<JobDetail>(`/maintenance/jobs/${jobId}/submit`, { method: "POST", token });
}

export interface ReviewVerdict {
  check_id: string;
  verdict: "accepted" | "rejected";
  reason?: string | null;
}

export function reviewJob(token: string, jobId: string, verdicts: ReviewVerdict[]) {
  return apiFetch<JobDetail>(`/maintenance/jobs/${jobId}/review`, { method: "POST", token, body: { verdicts } });
}

export function closeJob(token: string, jobId: string) {
  return apiFetch<JobDetail>(`/maintenance/jobs/${jobId}/close`, { method: "POST", token });
}

export function cancelJob(token: string, jobId: string, reason: string) {
  return apiFetch<JobDetail>(`/maintenance/jobs/${jobId}/cancel`, { method: "POST", token, body: { reason } });
}

// ---------------------------------------------------------------------------
// Programs
// ---------------------------------------------------------------------------

export function listPrograms(token: string) {
  return apiFetch<Program[]>("/maintenance/programs", { token });
}

export interface CreateProgramInput {
  equipment_id: string;
  name: string;
  description?: string | null;
  interval_value: number;
  interval_unit: "day" | "week" | "month";
  start_date: string;
  lead_days: number;
  estimated_minutes?: number | null;
  default_team_id?: string | null;
  stops_machine: boolean;
  checkpoint_ids: string[];
}

export function createProgram(token: string, input: CreateProgramInput) {
  return apiFetch<Program>("/maintenance/programs", { method: "POST", token, body: input });
}

export type UpdateProgramInput = Partial<CreateProgramInput> & { active?: boolean };

export function updateProgram(token: string, programId: string, input: UpdateProgramInput) {
  return apiFetch<Program>(`/maintenance/programs/${programId}`, { method: "PATCH", token, body: input });
}

export function runDuePrograms(token: string) {
  return apiFetch<{ created: number; overdue_notified: number }>("/maintenance/programs/run-due", { method: "POST", token });
}

// ---------------------------------------------------------------------------
// Calendar
// ---------------------------------------------------------------------------

export function getCalendar(token: string, from: string, to: string) {
  const query = new URLSearchParams({ from, to });
  return apiFetch<CalendarResponse>(`/maintenance/calendar?${query.toString()}`, { token });
}

// ---------------------------------------------------------------------------
// Parts
// ---------------------------------------------------------------------------

export function listPartRequests(token: string, status?: PartRequest["status"]) {
  const query = status ? `?status=${encodeURIComponent(status)}` : "";
  return apiFetch<PartRequest[]>(`/maintenance/part-requests${query}`, { token });
}

export interface CreatePartRequestLineInput {
  product_id: string;
  uom_id: string;
  quantity: number;
}

export function createPartRequest(token: string, jobId: string, input: { lines: CreatePartRequestLineInput[]; note?: string | null }) {
  return apiFetch<PartRequest>(`/maintenance/jobs/${jobId}/part-requests`, { method: "POST", token, body: input });
}

export function getPartRequestAvailability(token: string, partRequestId: string) {
  return apiFetch<Availability>(`/maintenance/part-requests/${partRequestId}/availability`, { token });
}

export interface ApprovePartRequestLineInput {
  line_id: string;
  location_id: string | null;
  issue_quantity: number;
}

export function approvePartRequest(
  token: string,
  partRequestId: string,
  input: { lines: ApprovePartRequestLineInput[]; note?: string | null },
) {
  return apiFetch<PartRequest>(`/maintenance/part-requests/${partRequestId}/approve`, { method: "POST", token, body: input });
}

export function rejectPartRequest(token: string, partRequestId: string, note: string) {
  return apiFetch<PartRequest>(`/maintenance/part-requests/${partRequestId}/reject`, { method: "POST", token, body: { note } });
}

// ---------------------------------------------------------------------------
// Query hooks
// ---------------------------------------------------------------------------

type Token = string;

function invalidatePrefix(queryClient: ReturnType<typeof useQueryClient>) {
  queryClient.invalidateQueries({ queryKey: MAINTENANCE_PREFIX });
}

/** A mutation whose success invalidates every `["maintenance", ...]` query — the simplest-correct choice given how cross-cutting these writes are (e.g. closing a job can also resolve a part request, assigning a job changes both the list and detail caches). */
function useMaintenanceMutation<TData, TVariables, TContext = unknown>(
  mutationFn: (variables: TVariables) => Promise<TData>,
  options: Omit<UseMutationOptions<TData, unknown, TVariables, TContext>, "mutationFn"> = {},
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn,
    ...options,
    onSuccess: (data, variables, onMutateResult, context) => {
      invalidatePrefix(queryClient);
      options.onSuccess?.(data, variables, onMutateResult, context);
    },
  });
}

export function useTeams(token: Token) {
  return useQuery({ queryKey: MAINTENANCE_TEAMS_QUERY_KEY, queryFn: () => listTeams(token), enabled: !!token });
}

export function useTeamCandidates(token: Token) {
  return useQuery({ queryKey: MAINTENANCE_TEAM_CANDIDATES_QUERY_KEY, queryFn: () => listTeamCandidates(token), enabled: !!token });
}

export function useChefCandidates(token: Token) {
  return useQuery({ queryKey: MAINTENANCE_CHEF_CANDIDATES_QUERY_KEY, queryFn: () => listChefCandidates(token), enabled: !!token });
}

export function useCreateTeam(token: Token) {
  return useMaintenanceMutation((input: CreateTeamInput) => createTeam(token, input));
}

export function useUpdateTeam(token: Token) {
  return useMaintenanceMutation(({ teamId, input }: { teamId: string; input: UpdateTeamInput }) => updateTeam(token, teamId, input));
}

export function useSetTeamMembers(token: Token) {
  return useMaintenanceMutation(({ teamId, employeeIds }: { teamId: string; employeeIds: string[] }) => setTeamMembers(token, teamId, employeeIds));
}

export function useEquipmentViews(token: Token, equipmentId: string | null, includeArchived = false) {
  return useQuery({
    queryKey: equipmentId ? maintenanceEquipmentViewsKey(equipmentId) : ["maintenance", "views", "none"],
    queryFn: () => listEquipmentViews(token, equipmentId!, includeArchived),
    enabled: !!token && !!equipmentId,
  });
}

export function useCreateEquipmentView(token: Token) {
  return useMaintenanceMutation(({ equipmentId, input }: { equipmentId: string; input: { label: string; image: File } }) =>
    createEquipmentView(token, equipmentId, input),
  );
}

export function useUpdateEquipmentView(token: Token) {
  return useMaintenanceMutation(({ viewId, input }: { viewId: string; input: UpdateViewInput }) => updateEquipmentView(token, viewId, input));
}

export function useDeleteEquipmentView(token: Token) {
  return useMaintenanceMutation((viewId: string) => deleteEquipmentView(token, viewId));
}

export function useCreateCheckpoint(token: Token) {
  return useMaintenanceMutation(({ viewId, input }: { viewId: string; input: CreateCheckpointInput }) => createCheckpoint(token, viewId, input));
}

export function useUpdateCheckpoint(token: Token) {
  return useMaintenanceMutation(({ checkpointId, input }: { checkpointId: string; input: UpdateCheckpointInput }) =>
    updateCheckpoint(token, checkpointId, input),
  );
}

export function useArchiveCheckpoint(token: Token) {
  return useMaintenanceMutation((checkpointId: string) => archiveCheckpoint(token, checkpointId));
}

export function useJobs(token: Token, filters: JobFilters = {}) {
  return useQuery({ queryKey: maintenanceJobsKey(filters), queryFn: () => listJobs(token, filters), enabled: !!token });
}

export function useJob(token: Token, jobId: string | null) {
  return useQuery({
    queryKey: jobId ? maintenanceJobKey(jobId) : ["maintenance", "job", "none"],
    queryFn: () => getJob(token, jobId!),
    enabled: !!token && !!jobId,
  });
}

export function useCreateJob(token: Token) {
  return useMaintenanceMutation((input: CreateJobInput) => createJob(token, input));
}

export function useAssignJob(token: Token) {
  return useMaintenanceMutation(({ jobId, input }: { jobId: string; input: AssignJobInput }) => assignJob(token, jobId, input));
}

export function useDelegateJob(token: Token) {
  return useMaintenanceMutation(({ jobId, assignments }: { jobId: string; assignments: DelegateAssignment[] }) =>
    delegateJob(token, jobId, assignments),
  );
}

export function useAddCheckEntry(token: Token) {
  return useMaintenanceMutation(({ jobId, checkId, input }: { jobId: string; checkId: string; input: AddCheckEntryInput }) =>
    addCheckEntry(token, jobId, checkId, input),
  );
}

export function useSubmitJob(token: Token) {
  return useMaintenanceMutation((jobId: string) => submitJob(token, jobId));
}

export function useReviewJob(token: Token) {
  return useMaintenanceMutation(({ jobId, verdicts }: { jobId: string; verdicts: ReviewVerdict[] }) => reviewJob(token, jobId, verdicts));
}

export function useCloseJob(token: Token) {
  return useMaintenanceMutation((jobId: string) => closeJob(token, jobId));
}

export function useCancelJob(token: Token) {
  return useMaintenanceMutation(({ jobId, reason }: { jobId: string; reason: string }) => cancelJob(token, jobId, reason));
}

export function usePrograms(token: Token) {
  return useQuery({ queryKey: MAINTENANCE_PROGRAMS_QUERY_KEY, queryFn: () => listPrograms(token), enabled: !!token });
}

export function useCreateProgram(token: Token) {
  return useMaintenanceMutation((input: CreateProgramInput) => createProgram(token, input));
}

export function useUpdateProgram(token: Token) {
  return useMaintenanceMutation(({ programId, input }: { programId: string; input: UpdateProgramInput }) =>
    updateProgram(token, programId, input),
  );
}

export function useRunDuePrograms(token: Token) {
  return useMaintenanceMutation(() => runDuePrograms(token));
}

export function useCalendar(token: Token, from: string, to: string) {
  return useQuery({ queryKey: maintenanceCalendarKey(from, to), queryFn: () => getCalendar(token, from, to), enabled: !!token && !!from && !!to });
}

export function usePartRequests(token: Token, status?: PartRequest["status"]) {
  return useQuery({ queryKey: maintenancePartRequestsKey(status), queryFn: () => listPartRequests(token, status), enabled: !!token });
}

export function usePartRequestAvailability(token: Token, partRequestId: string | null) {
  return useQuery({
    queryKey: partRequestId ? maintenancePartRequestAvailabilityKey(partRequestId) : ["maintenance", "part-requests", "none", "availability"],
    queryFn: () => getPartRequestAvailability(token, partRequestId!),
    enabled: !!token && !!partRequestId,
  });
}

export function useCreatePartRequest(token: Token) {
  return useMaintenanceMutation(
    ({ jobId, input }: { jobId: string; input: { lines: CreatePartRequestLineInput[]; note?: string | null } }) =>
      createPartRequest(token, jobId, input),
  );
}

export function useApprovePartRequest(token: Token) {
  return useMaintenanceMutation(
    ({ partRequestId, input }: { partRequestId: string; input: { lines: ApprovePartRequestLineInput[]; note?: string | null } }) =>
      approvePartRequest(token, partRequestId, input),
  );
}

export function useRejectPartRequest(token: Token) {
  return useMaintenanceMutation(({ partRequestId, note }: { partRequestId: string; note: string }) => rejectPartRequest(token, partRequestId, note));
}
