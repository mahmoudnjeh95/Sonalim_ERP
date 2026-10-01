import { describe, expect, it } from "vitest";
import type { CheckEntry, JobCheck, JobDetail } from "../api";
import {
  EMPTY_DRAFT,
  currentEntry,
  formatSpan,
  missingProof,
  nextPendingIndex,
  parseDecimal,
  validateDraft,
  wizardStepIds,
  type StepDraft,
} from "./wizardModel";

const entry = (attempt: number, extra: Partial<CheckEntry> = {}): CheckEntry => ({
  id: `E${attempt}-${extra.outcome ?? "ok"}`,
  attempt,
  performer_employee_id: "P1",
  performer_name: "Moussa Diarra",
  recorded_by: "U1",
  recorded_by_name: "Awa Traoré",
  started_at: "2026-10-01T08:00:00+00:00",
  finished_at: "2026-10-01T08:10:00+00:00",
  duration_seconds: 600,
  duration_source: "timer",
  outcome: "ok",
  note: null,
  measured_value: null,
  has_photo: false,
  ...extra,
});

const check = (id: string, extra: Partial<JobCheck> = {}): JobCheck => ({
  id,
  sort_order: 0,
  checkpoint_id: null,
  view_id: null,
  x_pct: null,
  y_pct: null,
  label: id,
  action: "inspect",
  instructions: null,
  measure_unit: null,
  requires_photo: false,
  assignee_employee_id: null,
  assignee_name: null,
  state: "pending",
  attempt: 1,
  entries: [],
  reviews: [],
  ...extra,
});

const job = (checks: JobCheck[]) => ({ checks }) as unknown as JobDetail;
const finished = { startedAt: 1_000, finishedAt: 61_000 };
const draft = (extra: Partial<StepDraft>): StepDraft => ({ ...EMPTY_DRAFT, ...extra });

describe("wizardStepIds", () => {
  it("walks every point before the first review, recorded ones included", () => {
    expect(wizardStepIds(job([check("A", { state: "done" }), check("B")]))).toEqual(["A", "B"]);
  });

  it("walks only the points not accepted in a rework", () => {
    const checks = [check("A", { state: "accepted" }), check("B", { state: "pending", attempt: 2 }), check("C", { state: "accepted" })];
    expect(wizardStepIds(job(checks))).toEqual(["B"]);
  });
});

describe("currentEntry / nextPendingIndex", () => {
  it("ignores entries of an earlier attempt", () => {
    const redo = check("A", { attempt: 2, entries: [entry(1)] });
    expect(currentEntry(redo)).toBeNull();
    const redone = check("A", { attempt: 2, state: "done", entries: [entry(1), entry(2, { outcome: "issue" })] });
    expect(currentEntry(redone)?.outcome).toBe("issue");
  });

  it("finds the next point still to record after the current one", () => {
    const steps = [check("A"), check("B", { state: "done" }), check("C")];
    expect(nextPendingIndex(steps, 0)).toBe(2);
    expect(nextPendingIndex(steps, 2)).toBe(-1);
  });
});

describe("parseDecimal", () => {
  it("reads a French comma and a dot", () => {
    expect(parseDecimal("2,5")).toBe(2.5);
    expect(parseDecimal(" 12.75 ")).toBe(12.75);
    expect(parseDecimal("-3")).toBe(-3);
  });

  it("refuses what is not a plain number", () => {
    expect(parseDecimal("")).toBeNull();
    expect(parseDecimal("abc")).toBeNull();
    expect(parseDecimal("1,2,3")).toBeNull();
    expect(parseDecimal("1e3")).toBeNull();
  });
});

describe("validateDraft", () => {
  it("needs a performer, a timing and an outcome", () => {
    expect(validateDraft(check("A"), EMPTY_DRAFT, "", null)).toEqual({
      performer: "maintenance.wizard.error.performer",
      timing: "maintenance.wizard.error.timerNotStarted",
      outcome: "maintenance.wizard.error.outcome",
    });
  });

  it("refuses a running timer and a zero manual duration", () => {
    expect(validateDraft(check("A"), draft({ outcome: "ok" }), "P1", { startedAt: 1, finishedAt: null }).timing).toBe(
      "maintenance.wizard.error.timerRunning",
    );
    expect(validateDraft(check("A"), draft({ outcome: "ok", manual: true, manualMinutes: "0" }), "P1", null).timing).toBe(
      "maintenance.wizard.error.minutes",
    );
    expect(validateDraft(check("A"), draft({ outcome: "ok", manual: true, manualMinutes: "7,5" }), "P1", null)).toEqual({});
  });

  it("asks for the photo and the measure unless the point was not done", () => {
    const point = check("A", { action: "measure", requires_photo: true, measure_unit: "bar" });
    expect(validateDraft(point, draft({ outcome: "ok" }), "P1", finished)).toEqual({
      measure: "maintenance.wizard.error.measure",
      photo: "maintenance.wizard.error.photo",
    });
    expect(validateDraft(point, draft({ outcome: "not_done", note: "machine en production" }), "P1", finished)).toEqual({});
  });

  it("needs a note for an issue or a point not done, not for OK", () => {
    expect(validateDraft(check("A"), draft({ outcome: "issue" }), "P1", finished).note).toBe("maintenance.wizard.error.note");
    expect(validateDraft(check("A"), draft({ outcome: "not_done" }), "P1", finished).note).toBe("maintenance.wizard.error.note");
    expect(validateDraft(check("A"), draft({ outcome: "ok" }), "P1", finished)).toEqual({});
  });
});

describe("missingProof", () => {
  it("flags a recorded point without the proof submit will ask for", () => {
    const photoPoint = check("A", { requires_photo: true, state: "done", entries: [entry(1)] });
    expect(missingProof(photoPoint)).toBe("photo");
    const notDone = check("A", { requires_photo: true, state: "done", entries: [entry(1, { outcome: "not_done" })] });
    expect(missingProof(notDone)).toBeNull();
    const measured = check("B", { action: "measure", state: "done", entries: [entry(1, { measured_value: 2.5 })] });
    expect(missingProof(measured)).toBeNull();
  });
});

describe("formatSpan", () => {
  it("spells a duration out so it never reads as a time of day", () => {
    expect(formatSpan(45)).toBe("45 s");
    expect(formatSpan(845)).toBe("14 min 5 s");
    expect(formatSpan(600)).toBe("10 min");
    expect(formatSpan(5160)).toBe("1 h 26 min");
  });
});
