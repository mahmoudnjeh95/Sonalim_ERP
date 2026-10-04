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
    expect(fitted[0]).toBeGreaterThanOrEqual(200);
    expect(fitted[1]).toBeGreaterThanOrEqual(90);
  });

  it("keeps the chosen widths when not even the floors fit, so the table scrolls instead", () => {
    // A wide table on a phone: 8 columns of 160px in 358px of space. Squeezing
    // every column to its 72px floor would make the whole table unreadable to
    // save a sideways swipe, so the widths stand and the wrapper scrolls.
    const columns = Array.from({ length: 8 }, () => ({ width: 160, minWidth: 72 }));
    expect(fitToWidth(columns, 358)).toEqual(columns.map((c) => c.width));
  });
});
