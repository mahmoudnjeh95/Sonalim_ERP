import { describe, expect, it } from "vitest";
import { fitDistance, placeInSlot } from "./framing";

const halfTan = Math.tan((35 * Math.PI) / 360);

describe("fitDistance", () => {
  it("fits the vertical axis on landscape screens", () => {
    expect(fitDistance(2, 35, 16 / 9)).toBeCloseTo(2 / halfTan, 6);
  });

  it("backs off on portrait screens so the sides still fit", () => {
    expect(fitDistance(2, 35, 0.5)).toBeCloseTo((2 / halfTan) * 2, 6);
  });
});

describe("placeInSlot", () => {
  it("centres a centred box on the camera axis", () => {
    const p = placeInSlot({ left: 700, top: 400, width: 40, height: 100 }, 1440, 900, 35, 3);
    expect(p.x).toBeCloseTo(0, 6);
    expect(p.y).toBeCloseTo(0, 6);
    expect(p.z).toBe(-3);
  });

  it("puts a box in the top-left quarter left of and above the axis", () => {
    const p = placeInSlot({ left: 100, top: 100, width: 80, height: 80 }, 1440, 900, 35, 3);
    expect(p.x).toBeLessThan(0);
    expect(p.y).toBeGreaterThan(0);
  });

  it("sizes the object to the box's share of the view height", () => {
    const halfH = 3 * halfTan;
    expect(placeInSlot({ left: 0, top: 0, width: 1440, height: 900 }, 1440, 900, 35, 3).size).toBeCloseTo(2 * halfH, 6);
    expect(placeInSlot({ left: 0, top: 0, width: 90, height: 90 }, 1440, 900, 35, 3).size).toBeCloseTo((90 / 900) * 2 * halfH, 6);
  });

  it("reaches the full half-width at the right edge of a wide screen", () => {
    const p = placeInSlot({ left: 1800, top: 450, width: 0, height: 0 }, 1800, 900, 35, 3);
    expect(p.x).toBeCloseTo(2 * 3 * halfTan, 6);
  });
});
