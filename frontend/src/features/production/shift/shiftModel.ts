import type { SectionDef } from "./sectionConfig";
import type { GridRow } from "./ShiftGrid";
import { blankRow, isBlankRow, newKey } from "./ShiftGrid";
import type { Row, SectionPayload } from "./shiftApi";

/** What a section's grids hold while the team edits: a list per row part, a record per single part. */
export type Draft = Record<string, GridRow[] | Row>;

const blank = (value: unknown) => value === null || value === undefined || value === "";

function toGridRows(rows: unknown, childKey?: string): GridRow[] {
  if (!Array.isArray(rows)) return [];
  return rows.map((raw) => {
    const row = raw as Row;
    const grid: GridRow = { ...row, _key: typeof row.id === "string" ? row.id : newKey() };
    if (childKey) grid[childKey] = toGridRows(row[childKey]);
    return grid;
  });
}

/**
 * The server's payload, shaped for editing. With `withBlankLine`, a table that holds
 * nothing starts with one empty line to type in (the grids of an editable section).
 */
export function toDraft(def: SectionDef, payload: SectionPayload | undefined, withBlankLine = false): Draft {
  const draft: Draft = {};
  for (const part of def.parts) {
    const stored = payload?.[part.payloadKey];
    if (part.shape === "single") {
      draft[part.payloadKey] = { ...((stored as Row | null) ?? {}) };
      continue;
    }
    const rows = toGridRows(stored, part.child?.payloadKey);
    draft[part.payloadKey] = rows.length === 0 && withBlankLine ? [blankRow(part.child?.payloadKey)] : rows;
  }
  return draft;
}

/** The lines somebody filled in: an untouched blank line is not part of the report. */
const filledRows = (rows: GridRow[]) => rows.filter((row) => !isBlankRow(row));

function toRows(rows: GridRow[], childKey?: string): Row[] {
  return rows.map((grid) => {
    const { _key, _fresh, ...row } = grid;
    void _key;
    void _fresh;
    if (childKey) row[childKey] = toRows((grid[childKey] as GridRow[] | undefined) ?? []);
    return row;
  });
}

/** What to send: rows without their client keys, and a single record only when something is filled in. */
export function toPayload(def: SectionDef, draft: Draft): SectionPayload {
  const payload: SectionPayload = {};
  for (const part of def.parts) {
    const value = draft[part.payloadKey];
    if (part.shape === "single") {
      const record = value as Row;
      const given = Object.fromEntries(Object.entries(record).filter(([, v]) => !blank(v)));
      payload[part.payloadKey] = Object.keys(given).length > 0 ? given : null;
    } else {
      const derived = new Set(part.serverDerived ?? []);
      payload[part.payloadKey] = toRows(filledRows(value as GridRow[]), part.child?.payloadKey).map((row) =>
        Object.fromEntries(Object.entries(row).filter(([key]) => !derived.has(key))),
      );
    }
  }
  return payload;
}

/** Whether there is anything to hand in: any row, or any figure in a single record. */
export function hasData(def: SectionDef, draft: Draft): boolean {
  return def.parts.some((part) => {
    const value = draft[part.payloadKey];
    if (part.shape === "single") return Object.values(value as Row).some((v) => !blank(v));
    return filledRows(value as GridRow[]).length > 0;
  });
}

/** How many rows a section holds (a single record counts as one), for the card header. */
export function rowCount(def: SectionDef, draft: Draft): number {
  return def.parts.reduce((total, part) => {
    const value = draft[part.payloadKey];
    if (part.shape === "single") return total + (Object.values(value as Row).some((v) => !blank(v)) ? 1 : 0);
    return total + filledRows(value as GridRow[]).length;
  }, 0);
}
