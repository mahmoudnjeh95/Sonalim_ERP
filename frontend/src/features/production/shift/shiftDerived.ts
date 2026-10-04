import type { Row } from "./shiftApi";

/**
 * The figures the fiche works out for itself, rather than asking the team to type them.
 *
 * They are all derived from what is already on the paper: a stop's length from its two
 * times, the semoule flow from the versements over the hours the line actually ran. The
 * screen shows them read-only and never sends them back -- the server keeps deriving what
 * it stores, so a report opened later says the same thing as the day it was typed.
 */

const MS_PER_MINUTE = 60_000;

const at = (value: unknown): number | null => {
  if (typeof value !== "string" || !value) return null;
  const ms = new Date(value).getTime();
  return Number.isNaN(ms) ? null : ms;
};

/**
 * How long a stop lasted, in minutes: HF less HD.
 *
 * Null while the stop is still open (no HF yet), and null rather than negative when the
 * two times are the wrong way round -- a stop that ended before it started is a typo, and
 * showing "-25 min" would invite somebody to believe it.
 */
export function stopMinutes(row: { started_at?: unknown; ended_at?: unknown }): number | null {
  const started = at(row.started_at);
  const ended = at(row.ended_at);
  if (started === null || ended === null) return null;
  const minutes = Math.round((ended - started) / MS_PER_MINUTE);
  return minutes < 0 ? null : minutes;
}

/** Everything the line stood still for this shift; a stop still open counts for nothing yet. */
export function totalStopMinutes(rows: readonly { started_at?: unknown; ended_at?: unknown }[]): number {
  return rows.reduce((total, row) => total + (stopMinutes(row) ?? 0), 0);
}

/**
 * The shift's semoule flow, in tonnes an hour: everything poured into the line -- semoule
 * and rebroyat both -- over the hours it actually ran, which is the shift's length less
 * the stops recorded in the Arrêts section.
 *
 * One figure for the whole shift: the versements are recorded once per shift, not per run,
 * so every run row shows the same rate. Null when it cannot be worked out -- the shift's
 * hours are not configured, the stops leave no running time, or nothing has been poured in
 * yet -- so the cell says "—" instead of a number nobody can account for.
 */
export function semolinaFlowRate({
  semolinaTons,
  regrindTons,
  shiftMinutes,
  stopMinutes: stopped,
}: {
  semolinaTons: number;
  regrindTons: number;
  shiftMinutes: number | null;
  stopMinutes: number;
}): number | null {
  if (shiftMinutes === null || shiftMinutes <= 0) return null;
  const running = shiftMinutes - stopped;
  if (running <= 0) return null;
  const tons = semolinaTons + regrindTons;
  if (tons <= 0) return null;
  return Math.round((tons / (running / 60)) * 100) / 100;
}

/** A section's saved rows, from the report the server last sent. */
type SectionRows = (key: string, part: string) => Row[];

/**
 * What the sections work out from each other, gathered once for the whole screen.
 *
 * A section only ever edits its own rows, but some of its figures come from elsewhere on the
 * fiche -- the packing lots follow the OF production ran, the semoule flow divides the
 * versements by the hours the stops left. Reading the saved sections here keeps each section
 * card ignorant of the others.
 */
export interface ShiftContext {
  /** The OF the shift's first production row names; what a new packing lot starts on. */
  runOrderId: string | null;
  /** The shift's semoule flow in t/h, the same figure on every run row; null when it cannot be worked out. */
  semolinaFlowRate: number | null;
}

export function shiftContext(rowsOf: SectionRows, shiftMinutes: number | null): ShiftContext {
  const runs = rowsOf("runs", "runs");
  const firstOrder = runs.map((row) => row.of_id).find((id) => typeof id === "string" && id !== "");

  const tons = (rows: Row[]) =>
    rows.reduce((total, row) => {
      const quantity = Number(row.quantity);
      return total + (Number.isFinite(quantity) ? quantity : 0);
    }, 0);

  return {
    runOrderId: typeof firstOrder === "string" ? firstOrder : null,
    semolinaFlowRate: semolinaFlowRate({
      semolinaTons: tons(rowsOf("runs", "versements")),
      regrindTons: tons(rowsOf("runs", "rebroyat_versements")),
      shiftMinutes,
      stopMinutes: totalStopMinutes(rowsOf("stops", "stops")),
    }),
  };
}
