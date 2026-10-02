import { describe, expect, it } from "vitest";
import { bezier, brandEase, clamp01, easeInOut, lerp, progress, random } from "./math";

describe("bezier easing", () => {
  it("runs from 0 to 1", () => {
    expect(brandEase(0)).toBe(0);
    expect(brandEase(1)).toBe(1);
  });

  it("is the identity for a linear curve", () => {
    expect(bezier(0, 0, 1, 1)(0.3)).toBeCloseTo(0.3, 5);
  });

  it("makes the brand easing a strong ease-out", () => {
    // EASE = [0.22, 1, 0.36, 1] covers ~96 % of the move by half time.
    expect(brandEase(0.5)).toBeGreaterThan(0.9);
  });

  it("never goes backwards", () => {
    let previous = 0;
    for (let x = 0; x <= 1; x += 0.01) {
      const y = brandEase(x);
      expect(y).toBeGreaterThanOrEqual(previous - 1e-9);
      previous = y;
    }
  });

  it("keeps the camera ease symmetric", () => {
    expect(easeInOut(0.5)).toBeCloseTo(0.5, 3);
  });
});

describe("progress, clamp01, lerp", () => {
  it("is 0 before, 1 after and linear inside the window", () => {
    expect(progress(0.5, 1, 2)).toBe(0);
    expect(progress(2, 1, 2)).toBe(0.5);
    expect(progress(9, 1, 2)).toBe(1);
  });

  it("clamps and interpolates", () => {
    expect(clamp01(-3)).toBe(0);
    expect(clamp01(4)).toBe(1);
    expect(lerp(2, 4, 0.25)).toBe(2.5);
  });
});

describe("random", () => {
  it("repeats the same sequence for the same seed", () => {
    const a = random(42);
    const b = random(42);
    expect([a(), a(), a()]).toEqual([b(), b(), b()]);
  });

  it("gives different sequences for different seeds", () => {
    expect(random(1)()).not.toBe(random(2)());
  });

  it("stays inside [0, 1)", () => {
    const r = random(7);
    for (let i = 0; i < 1000; i++) {
      const v = r();
      expect(v).toBeGreaterThanOrEqual(0);
      expect(v).toBeLessThan(1);
    }
  });
});
