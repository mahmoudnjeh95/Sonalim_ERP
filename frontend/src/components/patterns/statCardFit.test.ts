import { describe, expect, it } from "vitest";
import { FIGURE_STEPS, fitFigureStep } from "./statCardFit";

describe("fitFigureStep", () => {
  it("keeps the largest type when the figure already fits", () => {
    // Measured at the largest step: 145px of text in a 200px box.
    expect(fitFigureStep(145, 200, 0)).toBe(0);
  });

  it("steps down until the figure fits the space it has", () => {
    // 145px at 24px type scales to ~121px at 20px and ~109px at 18px.
    // A 130px box clears the 20px step, so that is where it stops.
    expect(fitFigureStep(145, 130, 0)).toBe(1);
  });

  it("stops at the smallest step rather than shrinking without limit", () => {
    // The CRM case that spills +52px at 1280px: nothing fits, so the smallest
    // step is used and the unit wraps instead of the number being cut off.
    const step = fitFigureStep(145, 40, 0);
    expect(step).toBe(FIGURE_STEPS.length - 1);
  });

  it("returns to a larger step when the container grows again", () => {
    // Widening the window must undo the shrink, not leave the card small.
    expect(fitFigureStep(109, 200, FIGURE_STEPS.length - 1)).toBe(0);
  });

  it("measures against the step the figure was measured at", () => {
    // Same figure measured while already shrunk to the 18px step: 109px there is
    // ~145px at 24px and ~121px at 20px, so neither larger step fits a 120px box
    // and it correctly stays at 18px. Scaling back from the measured step is what
    // stops a shrunk figure from looking like it fits and oscillating.
    expect(fitFigureStep(109, 120, 2)).toBe(2);
    // With a little more room the 20px step does fit, so it steps back up.
    expect(fitFigureStep(109, 125, 2)).toBe(1);
  });

  it("treats a zero-width container as unmeasured and keeps the current step", () => {
    // A hidden or not-yet-laid-out card reports 0; shrinking on that would make
    // every card jump to the smallest type on mount.
    expect(fitFigureStep(145, 0, 0)).toBe(0);
  });

  it("never returns a step outside the table", () => {
    for (const available of [0, 1, 50, 500]) {
      const step = fitFigureStep(145, available, 0);
      expect(step).toBeGreaterThanOrEqual(0);
      expect(step).toBeLessThan(FIGURE_STEPS.length);
    }
  });
});
