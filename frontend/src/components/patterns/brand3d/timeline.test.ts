import { describe, expect, it } from "vitest";
import { cssEase } from "./math";
import { cameraPose, cameraPosition, INTRO, introState, logoState, skipTime, withPointer } from "./timeline";

describe("introState", () => {
  it("opens on the semolina stream alone", () => {
    const s = introState(0.6);
    expect(s.stream).toBeCloseTo(0.5, 6);
    expect(s.condense).toBe(0);
    expect(s.wordmark).toBe(0);
    expect(s.handoff).toBe(0);
  });

  it("condenses grains into pasta between 1.2 and 2.4 s", () => {
    expect(introState(1.8).condense).toBeCloseTo(0.5, 6);
    expect(introState(2.4).condense).toBeCloseTo(1, 9);
  });

  it("shows the wordmark from 3.0 s and clears it for the handoff", () => {
    expect(introState(2.9).wordmark).toBe(0);
    expect(introState(3.45).wordmark).toBeCloseTo(1, 9);
    expect(introState(3.8).wordmark).toBeCloseTo(0, 6);
  });

  it("hands off between 3.6 and 4.0 s", () => {
    expect(introState(3.6).handoff).toBe(0);
    expect(introState(4).handoff).toBeCloseTo(1, 6);
  });

  it("is settled long after the end, so a tab hidden mid-intro returns to the login", () => {
    const s = introState(14);
    expect(s.handoff).toBe(1);
    expect(s.wordmark).toBe(0);
    expect(s.orbit).toBe(1);
  });
});

describe("logoState", () => {
  it("is not there before its beat", () => {
    expect(logoState(2.3, 0)).toEqual({ ring: 0, glyph: 0, flash: 0 });
  });

  it("closes the ring at 3.1 s with the flash at its peak", () => {
    const s = logoState(3.1, 0);
    expect(s.ring).toBeCloseTo(1, 9);
    expect(s.flash).toBe(1);
  });

  it("lets the flash die out by 3.45 s", () => {
    expect(logoState(3.46, 0).flash).toBe(0);
  });

  it("plays the SVG's own build on a login reached without the intro", () => {
    expect(logoState(null, 0).ring).toBe(0);
    expect(logoState(null, 0.9).ring).toBeCloseTo(cssEase(0.5), 6);
    expect(logoState(null, 1.8)).toEqual({ ring: 1, glyph: 1, flash: 0 });
  });

  it("shows the finished mark once the intro handed it over", () => {
    expect(logoState(null, Infinity)).toEqual({ ring: 1, glyph: 1, flash: 0 });
  });
});

describe("skipTime", () => {
  it("fast-forwards to the handoff in 0.3 s", () => {
    expect(skipTime(1, 0.3)).toBeCloseTo(INTRO.handoff, 9);
  });

  it("then runs on at normal speed", () => {
    expect(skipTime(1, 0.5)).toBeCloseTo(3.8, 9);
  });

  it("passes through the middle halfway", () => {
    expect(skipTime(1, 0.15)).toBeCloseTo(2.3, 2);
  });

  it("changes nothing once the handoff has begun", () => {
    expect(skipTime(3.7, 0.1)).toBeCloseTo(3.8, 9);
  });
});

describe("cameraPose", () => {
  it("lands exactly on the login pose once the handoff is over", () => {
    expect(cameraPose(4.2, 12, 16 / 9)).toEqual(cameraPose(null, 12, 16 / 9));
  });

  it("is continuous at the end of the handoff", () => {
    const a = cameraPose(3.999, 12, 16 / 9);
    const b = cameraPose(null, 12, 16 / 9);
    expect(a.radius).toBeCloseTo(b.radius, 2);
    expect(a.azimuth).toBeCloseTo(b.azimuth, 2);
    expect(a.elevation).toBeCloseTo(b.elevation, 2);
  });

  it("opens looking down the semolina stream, behind the logo's place", () => {
    expect(cameraPose(0, 0, 16 / 9).target[2]).toBeLessThan(-3);
    expect(cameraPose(INTRO.pastaEnd, 0, 16 / 9).target).toEqual([0, 0, 0]);
  });

  it("frames the logo closer during the intro than the login does", () => {
    expect(cameraPose(3, 3, 16 / 9).radius).toBeLessThan(cameraPose(null, 3, 16 / 9).radius);
  });

  it("backs off on portrait screens", () => {
    expect(cameraPose(null, 0, 9 / 16).radius).toBeGreaterThan(cameraPose(null, 0, 16 / 9).radius);
  });
});

describe("cameraPosition / withPointer", () => {
  it("puts azimuth 0, elevation 0 straight in front of the target", () => {
    const [x, y, z] = cameraPosition({ radius: 10, azimuth: 0, elevation: 0, target: [0, 0, -1] });
    expect(x).toBeCloseTo(0, 9);
    expect(y).toBeCloseTo(0, 9);
    expect(z).toBeCloseTo(9, 9);
  });

  it("tilts at most 2.5° sideways and 2° vertically for the pointer", () => {
    const p = withPointer({ radius: 10, azimuth: 1, elevation: 4, target: [0, 0, 0] }, { x: 1, y: -1 });
    expect(p.azimuth).toBe(3.5);
    expect(p.elevation).toBe(6);
  });
});
