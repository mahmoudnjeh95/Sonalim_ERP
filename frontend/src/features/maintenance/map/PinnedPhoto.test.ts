import { describe, expect, it } from "vitest";
import { isDrag } from "./PinnedPhoto";

describe("isDrag", () => {
  it("treats a finger's jitter on a tap as a tap", () => {
    expect(isDrag({ x: 100, y: 100 }, { x: 101, y: 102 })).toBe(false);
  });

  it("treats a real move as a drag", () => {
    expect(isDrag({ x: 100, y: 100 }, { x: 112, y: 100 })).toBe(true);
  });
});
