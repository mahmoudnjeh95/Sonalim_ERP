import { useState } from "react";
import type { FilterCell } from "../components/patterns/ColumnFilterRow";

export type TextFilterField<Row> = {
  key: string;
  kind: "text";
  getValue: (row: Row) => string | number | null | undefined;
};

export type RangeFilterField<Row> = {
  key: string;
  kind: "range";
  getValue: (row: Row) => number | null | undefined;
};

export type FilterField<Row> = TextFilterField<Row> | RangeFilterField<Row>;

/**
 * Per-column filtering for hand-rolled tables: a text field does a
 * case-insensitive substring match, a range field does inclusive min/max.
 * Pair with <ColumnFilterRow/> for the input UI. Enum/status columns are
 * intentionally out of scope here — they're already covered by FilterTabs
 * above the table, so don't duplicate that as a column filter too.
 */
export function useColumnFilters<Row>(fields: FilterField<Row>[]) {
  const [text, setText] = useState<Record<string, string>>({});
  const [range, setRange] = useState<Record<string, { min: string; max: string }>>({});

  function setTextValue(key: string, value: string) {
    setText((prev) => ({ ...prev, [key]: value }));
  }

  function setRangeValue(key: string, part: "min" | "max", value: string) {
    setRange((prev) => ({ ...prev, [key]: { ...(prev[key] ?? { min: "", max: "" }), [part]: value } }));
  }

  const isActive =
    Object.values(text).some((v) => v.trim() !== "") ||
    Object.values(range).some((r) => r.min.trim() !== "" || r.max.trim() !== "");

  function reset() {
    setText({});
    setRange({});
  }

  function apply(rows: Row[]): Row[] {
    if (!isActive) return rows;
    return rows.filter((row) =>
      fields.every((field) => {
        if (field.kind === "text") {
          const query = text[field.key]?.trim().toLowerCase();
          if (!query) return true;
          const value = field.getValue(row);
          return value != null && String(value).toLowerCase().includes(query);
        }
        const bounds = range[field.key];
        if (!bounds || (!bounds.min.trim() && !bounds.max.trim())) return true;
        const value = field.getValue(row);
        if (value == null) return false;
        if (bounds.min.trim() && value < Number(bounds.min)) return false;
        if (bounds.max.trim() && value > Number(bounds.max)) return false;
        return true;
      }),
    );
  }

  /** A ready `FilterCell` for `<ColumnFilterRow>` -- avoids every table
   * re-declaring the same `{ type: "text", value, onChange }` closure. */
  function textCell(key: string, placeholder: string): FilterCell {
    return { type: "text", placeholder, value: text[key] ?? "", onChange: (value) => setTextValue(key, value) };
  }

  function rangeCell(key: string): FilterCell {
    const bounds = range[key];
    return {
      type: "range",
      min: bounds?.min ?? "",
      max: bounds?.max ?? "",
      onMinChange: (value) => setRangeValue(key, "min", value),
      onMaxChange: (value) => setRangeValue(key, "max", value),
    };
  }

  return { text, range, setTextValue, setRangeValue, isActive, reset, apply, textCell, rangeCell };
}
