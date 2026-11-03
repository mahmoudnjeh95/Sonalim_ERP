import { apiFetch } from "../../../lib/api";

export type ActivityKind = "comment" | "task" | "call" | "meeting";
export type ActivitySubjectType = "lead" | "partner" | "opportunity";

export interface Activity {
  id: string;
  kind: ActivityKind;
  subject_type: ActivitySubjectType;
  subject_id: string;
  note: string;
  due_at: string | null;
  completed_at: string | null;
}

export interface CreateActivityInput {
  kind: ActivityKind;
  subject_type: ActivitySubjectType;
  subject_id: string;
  note: string;
  due_at?: string;
}

export interface UpdateActivityInput {
  note?: string;
  due_at?: string;
}

export function listActivities(token: string, limit = 100) {
  return apiFetch<Activity[]>(`/crm/activities?limit=${limit}`, { token });
}

export function createActivity(token: string, input: CreateActivityInput) {
  return apiFetch<Activity>("/crm/activities", { method: "POST", token, body: input });
}

export function updateActivity(token: string, activityId: string, input: UpdateActivityInput) {
  return apiFetch<Activity>(`/crm/activities/${activityId}`, { method: "PATCH", token, body: input });
}

export function completeActivity(token: string, activityId: string) {
  return apiFetch<Activity>(`/crm/activities/${activityId}/complete`, { method: "POST", token });
}
