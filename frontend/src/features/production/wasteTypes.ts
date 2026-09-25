import { useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import { useAuth } from "../../lib/auth";
import { useI18n, type TranslationKey } from "../../lib/i18n";
import {
  BUILT_IN_WASTE_CATEGORIES,
  listBuiltInWasteTypes,
  listWasteTypes,
  type BuiltInWasteTypeSetting,
  type ReportType,
  type WasteCategory,
  type WasteType,
} from "./api";

export const WASTE_TYPES_QUERY_KEY = ["production", "waste-types"] as const;
// Under the key above, so invalidating it refreshes both lists.
const BUILT_IN_QUERY_KEY = [...WASTE_TYPES_QUERY_KEY, "built-ins"] as const;

const NO_TYPES: WasteType[] = [];
const NO_SETTINGS: BuiltInWasteTypeSetting[] = [];

const BUILT_IN = new Set<string>([...BUILT_IN_WASTE_CATEGORIES.daily, ...BUILT_IN_WASTE_CATEGORIES.conditionnement]);

export function isBuiltInWasteCategory(category: WasteCategory) {
  return BUILT_IN.has(category);
}

/** One kind of a report as the settings list and the forms see it: built-in or the plant's own. */
export interface WasteTypeEntry {
  /** What a line stores: the built-in key or the plant kind's id. */
  key: WasteCategory;
  builtIn: boolean;
  /** What to show: a built-in's custom name, else its translation; a plant kind's name. */
  label: string;
  /** A built-in's translated name, shown as the placeholder when it is renamed. */
  defaultLabel: string | null;
  /** Only for a built-in: whether the plant gave it a name of its own. */
  renamed: boolean;
  is_active: boolean;
}

/**
 * The déchet kinds of this plant: the built-ins, whose names are translated
 * unless the plant renamed them, and the ones an administrator added, whose
 * names are whatever they typed. Both are ordered together per report.
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
  const builtInQuery = useQuery({ queryKey: BUILT_IN_QUERY_KEY, queryFn: () => listBuiltInWasteTypes(token) });
  // Stable references while nothing changed, so the helpers below keep theirs and
  // a memoized caller (analytics' formatters) is not rebuilt on every render.
  const types = query.data ?? NO_TYPES;
  const settings = builtInQuery.data ?? NO_SETTINGS;

  const label = useCallback(
    (category: WasteCategory): string => {
      if (isBuiltInWasteCategory(category)) {
        const renamed = settings.find((setting) => setting.category === category)?.name;
        return renamed ?? t(`production.waste.category.${category}` as TranslationKey);
      }
      const own = types.find((type) => type.id === category);
      // Not loaded yet, or a kind this user may not read: a dash rather than the id.
      return own?.name ?? "—";
    },
    [types, settings, t],
  );

  /**
   * Every kind of one report, retired ones included, in the order the plant set.
   * A built-in the plant never moved sits ahead of its own kinds, in code order.
   */
  const entriesFor = useCallback(
    (reportType: ReportType): WasteTypeEntry[] => {
      const builtIns = BUILT_IN_WASTE_CATEGORIES[reportType].map((category, index) => {
        const setting = settings.find((entry) => entry.category === category);
        const defaultLabel = t(`production.waste.category.${category}` as TranslationKey);
        return {
          sort: setting?.sort_order ?? index - 1000,
          entry: {
            key: category,
            builtIn: true,
            label: setting?.name ?? defaultLabel,
            defaultLabel,
            renamed: setting?.name != null,
            is_active: setting?.is_active ?? true,
          },
        };
      });
      const own = types
        .filter((type) => type.report_type === reportType)
        .map((type) => ({
          sort: type.sort_order,
          entry: {
            key: type.id,
            builtIn: false,
            label: type.name,
            defaultLabel: null,
            renamed: false,
            is_active: type.is_active,
          },
        }));
      return [...builtIns, ...own]
        .sort(
          (a, b) =>
            a.sort - b.sort ||
            Number(b.entry.builtIn) - Number(a.entry.builtIn) ||
            a.entry.label.localeCompare(b.entry.label),
        )
        .map(({ entry }) => entry);
    },
    [types, settings, t],
  );

  /**
   * What a form may offer for one report, in the plant's order, without the
   * kinds it took off the list. `keep` carries the categories already on the
   * rows being edited, so a kind retired since a draft was written is still
   * shown on that draft instead of blanking.
   */
  const categoriesFor = useCallback(
    (reportType: ReportType, keep: WasteCategory[] = []): WasteCategory[] =>
      entriesFor(reportType)
        .filter((entry) => entry.is_active || keep.includes(entry.key))
        .map((entry) => entry.key),
    [entriesFor],
  );

  /** The plant's own kinds for one report, oldest first — the order colours are given in. */
  const ownTypesFor = useCallback(
    (reportType: ReportType): WasteType[] =>
      types.filter((type) => type.report_type === reportType).sort((a, b) => a.id.localeCompare(b.id)),
    [types],
  );

  return {
    types,
    isLoading: query.isLoading || builtInQuery.isLoading,
    label,
    entriesFor,
    categoriesFor,
    ownTypesFor,
  };
}
