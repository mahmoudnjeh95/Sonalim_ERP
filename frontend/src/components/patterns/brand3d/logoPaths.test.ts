import { describe, expect, it } from "vitest";
import logoSvg from "../../../assets/animations/logo-mark.svg?raw";
import { parseLogoSvg, parsePathData, toLogoSpace } from "./logoPaths";

describe("parsePathData", () => {
  it("chains relative cubic curves from the current point", () => {
    const [sub] = parsePathData("M-58 24c-8-38 0-67 25-92 25 30 34 61 22 92");
    expect(sub.start).toEqual([-58, 24]);
    expect(sub.segments).toEqual([
      { kind: "C", c1: [-66, -14], c2: [-58, -43], to: [-33, -68] },
      { kind: "C", c1: [-8, -38], c2: [1, -7], to: [-11, 24] },
    ]);
  });

  it("starts a new subpath on every move and reads line-tos", () => {
    const subs = parsePathData("M-38 1l31-25M-39 19l33-24M-34-16l24-18");
    expect(subs).toHaveLength(3);
    expect(subs[2]).toEqual({ start: [-34, -16], segments: [{ kind: "L", to: [-10, -34] }], closed: false });
  });

  it("marks a z-closed path", () => {
    expect(parsePathData("M22 17c-20-8-28-28-16-45 21 3 33 18 29 39-2 4-7 7-13 6z")[0].closed).toBe(true);
  });

  it("refuses commands the mark does not use instead of drawing them wrong", () => {
    expect(() => parsePathData("M0 0 A5 5 0 0 1 10 10")).toThrow(/unsupported/);
  });
});

describe("parseLogoSvg on logo-mark.svg", () => {
  const spec = parseLogoSvg(logoSvg);

  it("finds the ring", () => {
    expect(spec.viewBox).toBe(200);
    expect(spec.ring).toEqual({ cx: 100, cy: 100, r: 88, width: 3 });
  });

  it("finds the glyph transform and its four strokes", () => {
    expect(spec.glyph.translate).toEqual([103.5, 123]);
    expect(spec.glyph.scale).toBe(0.78);
    expect(spec.glyph.strokes.map((s) => s.width)).toEqual([8, 6, 7, 5]);
    expect(spec.glyph.strokes.map((s) => s.subpaths.length)).toEqual([1, 3, 1, 1]);
  });

  it("maps glyph units into centred logo space, y up", () => {
    const [x, y] = toLogoSpace([0, 0], spec);
    expect(x).toBeCloseTo(0.035, 6);
    expect(y).toBeCloseTo(-0.23, 6);
  });
});
