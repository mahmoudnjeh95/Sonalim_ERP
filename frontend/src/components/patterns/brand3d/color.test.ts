import { describe, expect, it } from "vitest";
import { acesFilmic, hexToRgb, linearToSrgb, mixHex, srgbToLinear, untone } from "./color";
import type { Vec3 } from "./math";

const to255 = (linear: Vec3) => linear.map((c) => Math.round(linearToSrgb(c) * 255));

describe("hexToRgb / mixHex", () => {
  it("reads brand hexes", () => {
    expect(hexToRgb("#071F43").map((c) => Math.round(c * 255))).toEqual([7, 31, 67]);
    expect(hexToRgb("#fff")).toEqual([1, 1, 1]);
  });

  it("mixes two hexes", () => {
    expect(mixHex("#000000", "#ffffff", 0.5)).toBe("#808080");
    expect(mixHex("#F5A900", "#FFD45A", 0)).toBe("#f5a900");
  });
});

describe("untone", () => {
  for (const hex of ["#071F43", "#123B6D"]) {
    it(`lands back on ${hex} after ACES at exposure 0.95`, () => {
      expect(to255(acesFilmic(untone(hex, 0.95), 0.95))).toEqual(hexToRgb(hex).map((c) => Math.round(c * 255)));
    });
  }

  it("is needed: ACES really shifts the plain swatch", () => {
    const plain = hexToRgb("#071F43").map(srgbToLinear) as Vec3;
    expect(to255(acesFilmic(plain, 0.95))).not.toEqual([7, 31, 67]);
  });
});
