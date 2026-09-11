import { useState } from "react";

/**
 * Row selection for bulk actions. `eligibleIds` scopes what "select all" and
 * the returned count/ids mean — a row that stops being eligible (e.g. a batch
 * that got assigned while selected) drops out on its own rather than lingering
 * as a stale selection.
 */
export function useSelection(eligibleIds: string[]) {
  const [selected, setSelected] = useState<Set<string>>(new Set());

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleAll() {
    setSelected((prev) => {
      const allSelected = eligibleIds.length > 0 && eligibleIds.every((id) => prev.has(id));
      return allSelected ? new Set() : new Set(eligibleIds);
    });
  }

  function clear() {
    setSelected(new Set());
  }

  const selectedIds = eligibleIds.filter((id) => selected.has(id));

  return {
    selectedIds,
    count: selectedIds.length,
    isSelected: (id: string) => selected.has(id),
    allSelected: eligibleIds.length > 0 && eligibleIds.every((id) => selected.has(id)),
    toggle,
    toggleAll,
    clear,
  };
}
