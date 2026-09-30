/**
 * Type sizes a stat figure steps down through when its card is too narrow.
 *
 * A KPI figure is never rounded, abbreviated or truncated to make it fit -- a
 * displayed figure is the recorded figure. When space runs out the type gets
 * smaller instead, and at the smallest step the unit wraps to its own line.
 *
 * Ordered largest first; the index is the "step".
 */
export const FIGURE_STEPS = [
  { className: "text-2xl", px: 24 },
  { className: "text-xl", px: 20 },
  { className: "text-lg", px: 18 },
] as const;

/**
 * The step at which `measuredWidth` fits into `available`.
 *
 * `measuredWidth` is the figure's rendered width *at `measuredStep`*, so widths
 * are first scaled back to the largest step before being compared -- otherwise
 * a figure measured while already shrunk would look like it fits and the card
 * would oscillate between two sizes.
 *
 * `available` of 0 means the card has not been laid out yet (hidden tab, first
 * paint). Shrinking on that would drop every card to the smallest type on
 * mount, so the current step is kept until a real measurement arrives.
 */
export function fitFigureStep(measuredWidth: number, available: number, measuredStep: number): number {
  if (available <= 0 || measuredWidth <= 0) return clampStep(measuredStep);

  const base = FIGURE_STEPS[clampStep(measuredStep)].px;
  const widthAtLargest = (measuredWidth * FIGURE_STEPS[0].px) / base;

  for (let step = 0; step < FIGURE_STEPS.length; step += 1) {
    const widthAtStep = (widthAtLargest * FIGURE_STEPS[step].px) / FIGURE_STEPS[0].px;
    // Sub-pixel rounding in the measured width must not force a needless step down.
    if (widthAtStep <= available + 0.5) return step;
  }
  return FIGURE_STEPS.length - 1;
}

function clampStep(step: number): number {
  if (!Number.isFinite(step) || step < 0) return 0;
  return Math.min(Math.trunc(step), FIGURE_STEPS.length - 1);
}
