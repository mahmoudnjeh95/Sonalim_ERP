import { useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import { useAuth } from "../../lib/auth";
import { useI18n, type TranslationKey } from "../../lib/i18n";
import {
  BUILT_IN_WASTE_CATEGORIES,
  listWasteTypes,
  type ReportType,
  type WasteCategory,
  type WasteType,
} from "./api";

export const WASTE_TYPES_QUERY_KEY = ["production", "waste-types"] as const;

const NO_TYPES: WasteType[] = [];

const BUILT_IN = new Set<string>([...BUILT_IN_WASTE_CATEGORIES.daily, ...BUILT_IN_WASTE_CATEGORIES.conditionnement]);

export function isBuiltInWasteCategory(category: WasteCategory) {
  return BUILT_IN.has(category);
}

/**
 * The déchet kinds of this plant: the built-ins, whose names are translated, and
 * the ones an administrator added, whose names are whatever they typed.
 *
 * A line stores either a built-in key or the id of a plant kind, so every screen
 * that prints a category goes through `label` rather than translating the raw
 * value — a plant kind's id would otherwise reach the page as an unreadable
 * string.
 */
export function useWasteTypes() {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const query = useQuery({ queryKey: WASTE_TYPES_QUERY_KEY, queryFn: () => listWasteTypes(token) });
  // A stable reference while nothing changed, so the helpers below keep theirs and
  // a memoized caller (analytics' formatters) is not rebuilt on every render.
  const types = query.data ?? NO_TYPES;

  const label = useCallback(
    (category: WasteCategory): string => {
      if (isBuiltInWasteCategory(category)) return t(`production.waste.category.${category}` as TranslationKey);
      const own = types.find((type) => type.id === category);
      // Not loaded yet, or a kind this user may not read: a dash rather than the id.
      return own?.name ?? "—";
    },
    [types, t],
  );

  /**
   * What a form may offer for one report: the built-ins in the form's own order,
   * then the plant's active kinds in the order its administrator set. `keep`
   * carries the categories already on the rows being edited, so a kind retired
   * since a draft was written is still shown on that draft instead of blanking.
   */
  const categoriesFor = useCallback(
    (reportType: ReportType, keep: WasteCategory[] = []): WasteCategory[] => {
      const own = types
        .filter((type) => type.report_type === reportType && (type.is_active || keep.includes(type.id)))
        .map((type) => type.id);
      return [...BUILT_IN_WASTE_CATEGORIES[reportType], ...own];
    },
    [types],
  );

  /** The plant's own kinds for one report, oldest first — the order colours are given in. */
  const ownTypesFor = useCallback(
    (reportType: ReportType): WasteType[] =>
      types.filter((type) => type.report_type === reportType).sort((a, b) => a.id.localeCompare(b.id)),
    [types],
  );

  return { types, isLoading: query.isLoading, label, categoriesFor, ownTypesFor };
}
