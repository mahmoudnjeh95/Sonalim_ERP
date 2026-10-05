import { describe, expect, it } from "vitest";
import { nextTier, pixelRatio, SAMPLE_FRAMES } from "./quality";

const frames = (ms: number, n = SAMPLE_FRAMES) => Array.from({ length: n }, () => ms);

describe("nextTier", () => {
  it("keeps the tier until a full sample is in", () => {
    expect(nextTier("high", frames(50, SAMPLE_FRAMES - 1), true)).toBe("high");
  });

  it("keeps high on a smooth machine", () => {
    expect(nextTier("high", frames(16), true)).toBe("high");
  });

  it("steps high down to low past 22 ms", () => {
    expect(nextTier("high", frames(25), true)).toBe("low");
  });

  it("steps one tier at a time, even when very slow", () => {
    expect(nextTier("high", frames(80), true)).toBe("low");
  });

  it("freezes a low tier past 33 ms on the login page", () => {
    expect(nextTier("low", frames(40), true)).toBe("still");
  });

  it("never freezes during the intro", () => {
    expect(nextTier("low", frames(40), false)).toBe("low");
  });

  it("judges by the median, so a couple of hitches do not downgrade", () => {
    const xs = frames(16);
    xs[3] = 400;
    xs[9] = 300;
    expect(nextTier("high", xs, true)).toBe("high");
  });

  it("never climbs back up", () => {
    expect(nextTier("low", frames(8), true)).toBe("low");
    expect(nextTier("still", frames(8), true)).toBe("still");
  });
});

describe("pixelRatio", () => {
  it("caps retina screens at 1.5 on high and 1 below", () => {
    expect(pixelRatio(3, "high")).toBe(1.5);
    expect(pixelRatio(1, "high")).toBe(1);
    expect(pixelRatio(2, "low")).toBe(1);
    expect(pixelRatio(2, "still")).toBe(1);
  });
});
