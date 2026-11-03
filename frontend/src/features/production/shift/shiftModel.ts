import type { PartDef, SectionDef } from "./sectionConfig";
import type { GridRow } from "./ShiftGrid";
import { blankRow, isBlankRow, newKey, withDefaults } from "./ShiftGrid";
import type { Row, SectionPayload } from "./shiftApi";

/** What a section's grids hold while the team edits: a list per row part, a record per single part. */
export type Draft = Record<string, GridRow[] | Row>;

const blank = (value: unknown) => value === null || value === undefined || value === "";

const pad = (n: number) => String(n).padStart(2, "0");

/** A blank datetime field defaults to the shift's date at the moment the line is added, so only the time needs typing. */
function dateTimeDefault(reportDate: string): string | null {
  const now = new Date();
  const local = new Date(`${reportDate}T${pad(now.getHours())}:${pad(now.getMinutes())}`);
  return Number.isNaN(local.getTime()) ? null : local.toISOString();
}

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
 * What a line added to this table starts with: the shift's lot and date, in a table that has
 * them to write -- so the team only has to type the time, not the whole date, on every row --
 * and, for the packing lots, the OF the shift's production ran.
 *
 * These are the screen's values, not the team's: `withDefaults` marks them, so a line holding
 * nothing else still counts as blank and is never handed in.
 */
export function partDefaults(
  part: PartDef,
  lotNumber: string | null | undefined,
  reportDate?: string | null,
  /** The OF the production rows named; the packing lots start on the same one. */
  runOrderId?: string | null,
): Row {
  if (part.shape !== "rows") return {};
  const defaults: Row = {};
  if (lotNumber && part.columns.some((c) => c.key === "lot_number")) defaults.lot_number = lotNumber;
  // Only a table that picks its OF from the shift's orders follows production; the production
  // rows name the OF themselves, so they are the source, never the follower.
  if (runOrderId && part.columns.some((c) => c.key === "of_id" && c.options === "shiftOrders")) {
    defaults.of_id = runOrderId;
  }
  if (reportDate) {
    for (const column of part.columns) {
      if (column.kind === "date") defaults[column.key] = reportDate;
      else if (column.kind === "datetime") {
        const value = dateTimeDefault(reportDate);
        if (value) defaults[column.key] = value;
      }
    }
  }
  return defaults;
}

/**
 * The server's payload, shaped for editing. With `withBlankLine`, a table that holds
 * nothing starts with one empty line to type in (the grids of an editable section),
 * carrying the shift's lot when it has one.
 */
export function toDraft(
  def: SectionDef,
  payload: SectionPayload | undefined,
  withBlankLine = false,
  lotNumber?: string | null,
  reportDate?: string | null,
  runOrderId?: string | null,
): Draft {
  const draft: Draft = {};
  for (const part of def.parts) {
    const stored = payload?.[part.payloadKey];
    if (part.shape === "single") {
      draft[part.payloadKey] = { ...((stored as Row | null) ?? {}) };
      continue;
    }
    const rows = toGridRows(stored, part.child?.payloadKey);
    draft[part.payloadKey] =
      rows.length === 0 && withBlankLine
        ? [blankRow(part.child?.payloadKey, partDefaults(part, lotNumber, reportDate, runOrderId))]
        : rows;
  }
  return draft;
}

/**
 * What the screen fills in changed -- the shift's lot (the team was named or renamed), or the
 * OF its production ran: the lines nobody has typed in follow it. A line somebody started
 * typing keeps what it has.
 */
export function followDefaults(
  def: SectionDef,
  draft: Draft,
  lotNumber: string | null | undefined,
  reportDate?: string | null,
  runOrderId?: string | null,
): Draft {
  const next: Draft = { ...draft };
  for (const part of def.parts) {
    if (part.shape !== "rows") continue;
    const defaults = partDefaults(part, lotNumber, reportDate, runOrderId);
    next[part.payloadKey] = (draft[part.payloadKey] as GridRow[]).map((row) =>
      isBlankRow(row) ? withDefaults(row, defaults) : row,
    );
  }
  return next;
}

/** The lines somebody filled in: an untouched blank line is not part of the report. */
const filledRows = (rows: GridRow[]) => rows.filter((row) => !isBlankRow(row));

function toRows(rows: GridRow[], childKey?: string): Row[] {
  return rows.map((grid) => {
    const { _key, _fresh, _auto, ...row } = grid;
    void _key;
    void _fresh;
    void _auto;
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
