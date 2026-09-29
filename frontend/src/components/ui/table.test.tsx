import { describe, expect, it } from "vitest";
import { fitToWidth } from "./table";

describe("fitToWidth", () => {
  it("does not shrink a column below its own minWidth even when others still have room", () => {
    const columns = [
      { width: 300, minWidth: 100 },
      { width: 100, minWidth: 72 },
    ];
    // Total 400, available 250: the second column gives up its full 28px of slack
    // (100 -> 72) first; the first column absorbs the remaining shrink (300 -> 178),
    // still well above its own floor of 100.
    const fitted = fitToWidth(columns, 250);
    expect(fitted[1]).toBe(72);
    expect(fitted[0]).toBe(178);
  });

  it("stops shrinking a column at its own minWidth once reached, redistributing remaining shrink", () => {
    const columns = [
      { width: 300, minWidth: 250 },
      { width: 300, minWidth: 72 },
    ];
    // Total 600, available 350. If both shrank proportionally the first would go
    // below 250 (its floor) -- it must stop there and let the second absorb the rest.
    const fitted = fitToWidth(columns, 350);
    expect(fitted[0]).toBe(250);
    expect(fitted[1]).toBe(100);
  });

  it("returns the stored widths unchanged when they already fit", () => {
    const columns = [
      { width: 100, minWidth: 72 },
      { width: 100, minWidth: 72 },
    ];
    expect(fitToWidth(columns, 500)).toEqual([100, 100]);
  });

  it("never returns a width below the column's own minWidth even at extreme squeeze", () => {
    const columns = [
      { width: 300, minWidth: 200 },
      { width: 100, minWidth: 90 },
    ];
    const fitted = fitToWidth(columns, 50);
    expect(fitted[0]).toBe(200);
    expect(fitted[1]).toBe(90);
  });
});
