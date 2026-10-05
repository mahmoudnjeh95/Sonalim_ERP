import { describe, expect, it } from "vitest";
import { matchingPreset, periodFromParams, presetRange } from "./historyPeriod";

const TODAY = new Date(2026, 9, 2); // 2 Oct 2026, local time

describe("presetRange", () => {
  it("covers the month, last month, three months and the year up to today", () => {
    expect(presetRange("month", TODAY)).toEqual({ from: "2026-10-01", to: "2026-10-02" });
    expect(presetRange("lastMonth", TODAY)).toEqual({ from: "2026-09-01", to: "2026-09-30" });
    expect(presetRange("threeMonths", TODAY)).toEqual({ from: "2026-08-01", to: "2026-10-02" });
    expect(presetRange("year", TODAY)).toEqual({ from: "2026-01-01", to: "2026-10-02" });
  });

  it("crosses the year in January", () => {
    expect(presetRange("lastMonth", new Date(2026, 0, 15))).toEqual({ from: "2025-12-01", to: "2025-12-31" });
  });
});

describe("matchingPreset and periodFromParams", () => {
  it("recognises a preset and treats anything else as custom", () => {
    expect(matchingPreset({ from: "2026-09-01", to: "2026-09-30" }, TODAY)).toBe("lastMonth");
    expect(matchingPreset({ from: "2026-09-03", to: "2026-09-30" }, TODAY)).toBeNull();
  });

  it("falls back to this year for a missing, malformed or reversed period", () => {
    const year = { from: "2026-01-01", to: "2026-10-02" };
    expect(periodFromParams(new URLSearchParams(""), TODAY)).toEqual(year);
    expect(periodFromParams(new URLSearchParams("from=2026-9-1&to=2026-09-30"), TODAY)).toEqual(year);
    expect(periodFromParams(new URLSearchParams("from=2026-09-30&to=2026-09-01"), TODAY)).toEqual(year);
    expect(periodFromParams(new URLSearchParams("from=2026-09-01&to=2026-09-30"), TODAY)).toEqual({ from: "2026-09-01", to: "2026-09-30" });
  });
});
