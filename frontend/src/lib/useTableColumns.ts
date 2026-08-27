import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { FilterCell } from "../components/patterns/ColumnFilterRow";
import { useAuth } from "./auth";
import {
  getTablePreferences,
  saveTablePreferences,
  type StoredColumnPreference,
  type TableColumnsPreference,
} from "./tablePreferences";

export interface ColumnDef<Row> {
  key: string;
  header: ReactNode;
  cell: (row: Row) => ReactNode;
  /** Starting column width in px. Falls back to DEFAULT_WIDTH. */
  defaultWidth?: number;
  /** Actions/buttons columns that must always stay visible. */
  alwaysVisible?: boolean;
  headerClassName?: string;
  cellClassName?: string;
  /** For tables with a <ColumnFilterRow> — the per-column filter control, if any. */
  filterCell?: FilterCell;
}

const DEFAULT_WIDTH = 160;
const MIN_WIDTH = 72;

function tablePreferencesQueryKey(tableKey: string) {
  return ["core", "table-preferences", tableKey] as const;
}

/**
 * Shared per-user column visibility + width state for a table, backed by
 * core.user_table_preferences (GET/PUT /core/table-preferences/{tableKey}).
 * `tableKey` must be a stable, globally unique id for the table (e.g. "partners.list").
 */
export function useTableColumns<Row>(tableKey: string, columns: ColumnDef<Row>[]) {
  const { session } = useAuth();
  const token = session!.token;
  const queryClient = useQueryClient();
  const queryKey = tablePreferencesQueryKey(tableKey);

  const { data } = useQuery({
    queryKey,
    queryFn: () => getTablePreferences(token, tableKey),
  });

  const [overrides, setOverrides] = useState<TableColumnsPreference>({});

  useEffect(() => {
    if (data) setOverrides(data.columns);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

  const saveMutation = useMutation({
    mutationFn: (next: TableColumnsPreference) => saveTablePreferences(token, tableKey, next),
    onSuccess: (result) => queryClient.setQueryData(queryKey, result),
  });

  function defaultsFor(column: ColumnDef<Row>): StoredColumnPreference {
    return { visible: true, width: column.defaultWidth ?? DEFAULT_WIDTH };
  }

  function preferenceFor(column: ColumnDef<Row>): StoredColumnPreference {
    return overrides[column.key] ?? defaultsFor(column);
  }

  function isVisible(key: string) {
    const column = columns.find((c) => c.key === key);
    if (!column) return true;
    return column.alwaysVisible === true || preferenceFor(column).visible;
  }

  function toggleVisible(key: string) {
    const column = columns.find((c) => c.key === key);
    if (!column || column.alwaysVisible) return;
    const current = preferenceFor(column);
    const next = { ...overrides, [key]: { ...current, visible: !current.visible } };
    setOverrides(next);
    saveMutation.mutate(next);
  }

  function getWidth(key: string) {
    const column = columns.find((c) => c.key === key);
    return column ? preferenceFor(column).width : DEFAULT_WIDTH;
  }

  function setWidth(key: string, width: number) {
    const column = columns.find((c) => c.key === key);
    if (!column) return;
    const current = preferenceFor(column);
    const clamped = Math.max(MIN_WIDTH, Math.round(width));
    const next = { ...overrides, [key]: { ...current, width: clamped } };
    setOverrides(next);
    saveMutation.mutate(next);
  }

  function resetAll() {
    setOverrides({});
    saveMutation.mutate({});
  }

  const visibleColumns = useMemo(
    () => columns.filter((column) => column.alwaysVisible === true || preferenceFor(column).visible),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [columns, overrides],
  );

  const colWidths = useMemo(
    () => visibleColumns.map((column) => preferenceFor(column).width),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [visibleColumns, overrides],
  );

  const toggleableColumns = useMemo(() => columns.filter((column) => !column.alwaysVisible), [columns]);

  return {
    visibleColumns,
    colWidths,
    toggleableColumns,
    isVisible,
    toggleVisible,
    getWidth,
    setWidth,
    resetAll,
  };
}
