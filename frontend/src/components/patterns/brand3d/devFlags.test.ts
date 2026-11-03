import { describe, expect, it } from "vitest";
import { parseBrandFlags } from "./devFlags";

describe("parseBrandFlags", () => {
  it("reads nothing from a plain URL", () => {
    expect(parseBrandFlags("")).toEqual({ introAt: null, tier: null, fallback: false });
  });

  it("reads a frozen intro time, a forced tier and a forced fallback", () => {
    expect(parseBrandFlags("?brand-t=2.9&brand-tier=low&brand-fallback=1")).toEqual({ introAt: 2.9, tier: "low", fallback: true });
  });

  it("ignores values it does not know", () => {
    expect(parseBrandFlags("?brand-t=soon&brand-tier=ultra&brand-fallback=yes")).toEqual({ introAt: null, tier: null, fallback: false });
  });
});
