/**
 * The review's rules, kept free of React so they can be tested: which cells are still in
 * doubt, which required values are missing (and whether the save would refuse the
 * section without them), which sections will be written, and the body sent on apply.
 */
import type { Column, SectionDef } from "../production/shift/sectionConfig";
import { isBlankRow, type GridRow } from "../production/shift/ShiftGrid";
import type { Row, SectionKey } from "../production/shift/shiftApi";
import type { ApplyBody, Choice, Proposal, ReviewValues, ShiftState } from "./scanApi";

export const APPLY_ORDER: readonly SectionKey[] = [
  "runs", "waste_production", "stops", "silo", "staffing", "packing", "packet_checks", "waste_packing",
];

// Values save_section refuses a section without; the other required columns are only needed at submit.
const BLOCKING = new Set([
  "runs.runs.of_id", "stops.stops.started_at", "waste_production.waste_lines.category",
  "waste_packing.waste_lines.category", "silo.states.side", "silo.states.phase",
]);
const CLIENT_KEYS = new Set(["_key", "_fresh", "_auto"]);

export const fieldPath = (section: string, part: string, ref: string, field: string) => `${section}/${part}/${ref}/${field}`;
export const sectionNotice = (section: string) => fieldPath(section, "-", "-", "-");
export const rowRef = (row: Row) => (typeof row._scan_ref === "string" ? row._scan_ref : "-");
export const isEmpty = (value: unknown) => value === null || value === undefined || value === "";
export const isBlocking = (section: string, part: string, field: string) => BLOCKING.has(`${section}.${part}.${field}`);
export const sameValue = (a: unknown, b: unknown) => (isEmpty(a) && isEmpty(b)) || String(a) === String(b);

type PartValue = GridRow[] | Row;

export function valuesFromProposal(proposal: Proposal): ReviewValues {
  const sections: ReviewValues["sections"] = {};
  for (const [key, parts] of Object.entries(proposal.sections) as [SectionKey, Record<string, unknown>][]) {
    const out: Record<string, PartValue> = {};
    for (const [part, value] of Object.entries(parts)) {
      out[part] = Array.isArray(value)
        ? (value as Row[]).map((row) => ({ ...row, _key: String(row._scan_ref) }))
        : { ...((value ?? {}) as Row) };
    }
    sections[key] = out;
  }
  return { header: { ...proposal.header }, sections };
}

/** A new proposal (another photo read) refreshes what the user has not touched. */
export function mergeProposal(current: ReviewValues, proposal: Proposal, touched: ReadonlySet<SectionKey>): ReviewValues {
  const fresh = valuesFromProposal(proposal);
  const sections = { ...fresh.sections };
  for (const key of touched) if (current.sections[key]) sections[key] = current.sections[key];
  const header = { ...fresh.header };
  for (const [field, value] of Object.entries(current.header)) if (!isEmpty(value)) header[field] = value;
  return { header, sections };
}

export function valuesByPath(values: ReviewValues): Map<string, unknown> {
  const out = new Map<string, unknown>();
  for (const [field, value] of Object.entries(values.header)) out.set(fieldPath("header", "-", "-", field), value);
  for (const [section, parts] of Object.entries(values.sections)) {
    for (const [part, value] of Object.entries(parts ?? {})) {
      const rows = Array.isArray(value) ? value : [value as Row];
      for (const row of rows) {
        const ref = Array.isArray(value) ? rowRef(row) : "-";
        for (const [key, cell] of Object.entries(row)) if (!key.startsWith("_")) out.set(fieldPath(section, part, ref, key), cell);
      }
    }
  }
  return out;
}

/** Doubts still standing: flagged, still the value read, and not confirmed -- in the sections being written. */
export function openDoubts(
  proposal: Proposal, values: ReviewValues, confirmed: ReadonlySet<string>, sections: readonly SectionKey[],
): string[] {
  const proposed = valuesByPath(valuesFromProposal(proposal));
  const current = valuesByPath(values);
  return Object.keys(proposal.flags).filter((path) => {
    const section = path.split("/", 1)[0];
    if (path.endsWith("/-/-/-") || confirmed.has(path)) return false;
    if (section !== "header" && !sections.includes(section as SectionKey)) return false;
    return current.has(path) && sameValue(current.get(path), proposed.get(path));
  });
}

export interface Missing {
  section: SectionKey;
  part: string;
  ref: string;
  column: Column;
  blocking: boolean;
}

export function missingRequired(values: ReviewValues, defs: readonly SectionDef[], sections: readonly SectionKey[]): Missing[] {
  const out: Missing[] = [];
  for (const def of defs) {
    if (!sections.includes(def.key)) continue;
    for (const part of def.parts) {
      const value = values.sections[def.key]?.[part.payloadKey];
      if (value === undefined) continue;
      const rows = part.shape === "rows" ? (value as GridRow[]).filter((row) => !isBlankRow(row)) : [value as Row];
      for (const row of rows) {
        for (const column of part.columns) {
          if (column.required && isEmpty(row[column.key])) {
            out.push({ section: def.key, part: part.payloadKey, ref: rowRef(row), column, blocking: isBlocking(def.key, part.payloadKey, column.key) });
          }
        }
      }
    }
  }
  return out;
}

export function sectionsToWrite(
  values: ReviewValues, choices: Partial<Record<SectionKey, Choice>>, shift: ShiftState | null,
): SectionKey[] {
  return APPLY_ORDER.filter(
    (key) => values.sections[key] !== undefined && ((shift?.sections[key]?.rows ?? 0) === 0 || choices[key] === "replace"),
  );
}

const clean = (row: GridRow): Row => Object.fromEntries(Object.entries(row).filter(([key]) => !CLIENT_KEYS.has(key)));

export function applyBody(values: ReviewValues, sections: readonly SectionKey[], shift: ShiftState | null): ApplyBody {
  const out: ApplyBody["sections"] = {};
  for (const key of sections) {
    const parts = values.sections[key] ?? {};
    out[key] = Object.fromEntries(
      Object.entries(parts).map(([part, value]) => [
        part,
        Array.isArray(value) ? value.filter((row) => !isBlankRow(row)).map(clean) : value,
      ]),
    );
  }
  return {
    header: values.header,
    sections: out,
    fingerprints: Object.fromEntries(sections.map((key) => [key, shift?.sections[key]?.fingerprint ?? null])),
  };
}
