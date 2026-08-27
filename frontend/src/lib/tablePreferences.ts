import { apiFetch } from "./api";

export interface StoredColumnPreference {
  visible: boolean;
  width: number;
}

export type TableColumnsPreference = Record<string, StoredColumnPreference>;

export interface TablePreferences {
  table_key: string;
  columns: TableColumnsPreference;
}

export function getTablePreferences(token: string, tableKey: string) {
  return apiFetch<TablePreferences>(`/core/table-preferences/${tableKey}`, { token });
}

export function saveTablePreferences(token: string, tableKey: string, columns: TableColumnsPreference) {
  return apiFetch<TablePreferences>(`/core/table-preferences/${tableKey}`, {
    method: "PUT",
    token,
    body: { columns },
  });
}
