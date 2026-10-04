import { describe, expect, it } from "vitest";
import type { Row } from "./shiftApi";
import { semolinaFlowRate, shiftContext, stopMinutes, totalStopMinutes } from "./shiftDerived";

describe("stopMinutes", () => {
  it("is the span from HD to HF", () => {
    expect(stopMinutes({ started_at: "2026-09-30T08:00:00Z", ended_at: "2026-09-30T08:25:00Z" })).toBe(25);
  });

  it("rounds to the minute the operator typed", () => {
    expect(stopMinutes({ started_at: "2026-09-30T08:00:30Z", ended_at: "2026-09-30T08:25:10Z" })).toBe(25);
  });

  it("is nothing while the stop is still running (no HF)", () => {
    expect(stopMinutes({ started_at: "2026-09-30T08:00:00Z", ended_at: null })).toBeNull();
    expect(stopMinutes({ started_at: null, ended_at: "2026-09-30T08:25:00Z" })).toBeNull();
  });

  it("is nothing when HF is before HD, rather than a negative stop", () => {
    expect(stopMinutes({ started_at: "2026-09-30T08:25:00Z", ended_at: "2026-09-30T08:00:00Z" })).toBeNull();
  });

  it("is nothing when a time cannot be read", () => {
    expect(stopMinutes({ started_at: "not a time", ended_at: "2026-09-30T08:25:00Z" })).toBeNull();
  });

  it("counts a stop that runs past midnight (a 23-07 shift)", () => {
    expect(stopMinutes({ started_at: "2026-09-30T23:50:00Z", ended_at: "2026-10-01T00:10:00Z" })).toBe(20);
  });
});

describe("totalStopMinutes", () => {
  it("adds up the stops that have both times", () => {
    expect(
      totalStopMinutes([
        { started_at: "2026-09-30T08:00:00Z", ended_at: "2026-09-30T08:25:00Z" },
        { started_at: "2026-09-30T09:00:00Z", ended_at: "2026-09-30T09:15:00Z" },
        { started_at: "2026-09-30T10:00:00Z", ended_at: null },
      ]),
    ).toBe(40);
  });

  it("is zero when nothing stopped", () => {
    expect(totalStopMinutes([])).toBe(0);
  });
});

describe("semolinaFlowRate", () => {
  it("is all the MP poured in over the hours the line actually ran", () => {
    // 40 t semoule + 2 t rebroyat over an 8 h shift less 60 min of stops = 42 / 7
    expect(semolinaFlowRate({ semolinaTons: 40, regrindTons: 2, shiftMinutes: 480, stopMinutes: 60 })).toBe(6);
  });

  it("rounds to two decimals, the way the box was typed", () => {
    expect(semolinaFlowRate({ semolinaTons: 41, regrindTons: 0, shiftMinutes: 480, stopMinutes: 60 })).toBe(5.86);
  });

  it("is nothing when the shift's hours are not configured", () => {
    expect(semolinaFlowRate({ semolinaTons: 40, regrindTons: 2, shiftMinutes: null, stopMinutes: 60 })).toBeNull();
  });

  it("is nothing when the stops leave no running time", () => {
    expect(semolinaFlowRate({ semolinaTons: 40, regrindTons: 2, shiftMinutes: 480, stopMinutes: 480 })).toBeNull();
    expect(semolinaFlowRate({ semolinaTons: 40, regrindTons: 2, shiftMinutes: 480, stopMinutes: 600 })).toBeNull();
  });

  it("is nothing before anything has been poured in", () => {
    expect(semolinaFlowRate({ semolinaTons: 0, regrindTons: 0, shiftMinutes: 480, stopMinutes: 0 })).toBeNull();
  });
});

describe("shiftContext", () => {
  const rows: Record<string, Record<string, Row[]>> = {
    runs: {
      runs: [{ of_id: "OF-1" }, { of_id: "OF-2" }],
      versements: [{ quantity: 25 }, { quantity: 15 }],
      rebroyat_versements: [{ quantity: 2 }],
    },
    stops: {
      stops: [
        { started_at: "2026-09-30T08:00:00Z", ended_at: "2026-09-30T08:40:00Z" },
        { started_at: "2026-09-30T09:00:00Z", ended_at: "2026-09-30T09:20:00Z" },
      ],
    },
  };
  const rowsOf = (key: string, part: string) => rows[key]?.[part] ?? [];

  it("names the OF the first production row ran", () => {
    expect(shiftContext(rowsOf, 480).runOrderId).toBe("OF-1");
  });

  it("works the flow out from the versements and the stops", () => {
    // 40 t semoule + 2 t rebroyat, 480 min less 60 min stopped = 7 h
    expect(shiftContext(rowsOf, 480).semolinaFlowRate).toBe(6);
  });

  it("skips a production row that has not named its OF yet", () => {
    const partial = (key: string, part: string) => (key === "runs" && part === "runs" ? [{ of_id: null }, { of_id: "OF-3" }] : rowsOf(key, part));
    expect(shiftContext(partial, 480).runOrderId).toBe("OF-3");
  });

  it("has no OF and no flow on an empty shift", () => {
    expect(shiftContext(() => [], 480)).toEqual({ runOrderId: null, semolinaFlowRate: null });
  });

  it("has no flow when the shift's hours are not configured", () => {
    expect(shiftContext(rowsOf, null).semolinaFlowRate).toBeNull();
  });
});
