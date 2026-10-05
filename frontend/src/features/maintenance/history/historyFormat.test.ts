import { describe, expect, it } from "vitest";
import { fill, initials, largestIndex, minutesOrDash, monthKey, sparklinePoints } from "./historyFormat";

describe("historyFormat", () => {
  it("fills every placeholder and leaves unknown ones", () => {
    expect(fill("{ok} OK · {issue} anomalie(s) · {x}", { ok: 3, issue: 1 })).toBe("3 OK · 1 anomalie(s) · {x}");
  });

  it("shows a dash for a figure that cannot be computed", () => {
    expect(minutesOrDash(null)).toBe("—");
    expect(minutesOrDash(57)).toBe("57 min");
    expect(minutesOrDash(400)).toBe("6 h 40 min");
  });

  it("groups by month and finds the largest bar", () => {
    expect(monthKey("2026-09-28T09:40:00+00:00")).toBe("2026-09");
    expect(largestIndex([290, 80, 290, 30])).toBe(0);
    expect(largestIndex([])).toBe(-1);
  });

  it("draws a sparkline oldest left and a flat series in the middle", () => {
    expect(sparklinePoints([1, 3], 20, 10, 0)).toEqual([{ x: 0, y: 10 }, { x: 20, y: 0 }]);
    expect(sparklinePoints([5, 5], 20, 10, 0).map((p) => p.y)).toEqual([5, 5]);
  });

  it("makes initials from a full name", () => {
    expect(initials("Awa Diarra")).toBe("AD");
    expect(initials("Moussa")).toBe("M");
  });
});
