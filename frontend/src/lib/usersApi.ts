import { apiFetch } from "./api";

export interface UserDirectoryEntry {
  id: string;
  email: string;
  full_name: string | null;
}

export function listUserDirectory(token: string) {
  return apiFetch<UserDirectoryEntry[]>("/core/users/directory", { token });
}

export function userDisplayName(user: UserDirectoryEntry) {
  return user.full_name?.trim() || user.email;
}
