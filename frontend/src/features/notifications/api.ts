import { apiFetch } from "../../lib/api";

// Cross-module notifications (maintenance job assignments, parts requests, …)
// surfaced through the shared kernel. Any module can create one; the frontend
// only ever reads/acknowledges them here. `link` is an in-app path the bell
// navigates to on click (e.g. `/maintenance/jobs/<id>`).
export interface AppNotification {
  id: string;
  kind: string;
  title: string;
  title_fr: string;
  body: string | null;
  body_fr: string | null;
  link: string | null;
  created_at: string;
  read_at: string | null;
}

export function listNotifications(token: string, params: { unread?: boolean } = {}) {
  const query = new URLSearchParams();
  if (params.unread) query.set("unread", "true");
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return apiFetch<AppNotification[]>(`/core/notifications${suffix}`, { token });
}

export function getUnreadNotificationCount(token: string) {
  return apiFetch<{ count: number }>("/core/notifications/unread-count", { token });
}

export function markNotificationRead(token: string, notificationId: string) {
  return apiFetch<void>(`/core/notifications/${notificationId}/read`, { method: "POST", token });
}

export function markAllNotificationsRead(token: string) {
  return apiFetch<void>("/core/notifications/read-all", { method: "POST", token });
}
