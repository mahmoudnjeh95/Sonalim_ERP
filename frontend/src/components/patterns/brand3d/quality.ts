/**
 * Quality tiers for the live scene, chosen by measuring (spec §5): start high,
 * step down one tier when the median frame is too slow, never step back up.
 */

export type Tier = "high" | "low" | "still";

export interface TierSettings {
  grains: number;
  pieces: number;
  bloom: boolean;
  maxPixelRatio: number;
}

export const TIERS: Record<"high" | "low", TierSettings> = {
  high: { grains: 1200, pieces: 60, bloom: true, maxPixelRatio: 1.5 },
  low: { grains: 500, pieces: 30, bloom: false, maxPixelRatio: 1 },
};

export const SAMPLE_FRAMES = 60;
export const SLOW_MS = 22;
export const STILL_MS = 33;

export function median(xs: readonly number[]): number {
  const sorted = [...xs].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

/**
 * The tier after a full sample of frame times. One step down when the median is
 * too slow, never up. The intro never freezes (a frozen intro reads as broken),
 * so `allowStill` is false while it plays.
 */
export function nextTier(current: Tier, frameMs: readonly number[], allowStill: boolean): Tier {
  if (current === "still" || frameMs.length < SAMPLE_FRAMES) return current;
  const m = median(frameMs);
  if (current === "high") return m > SLOW_MS ? "low" : "high";
  return allowStill && m > STILL_MS ? "still" : "low";
}

export function pixelRatio(device: number, tier: Tier): number {
  return Math.min(device, tier === "high" ? TIERS.high.maxPixelRatio : TIERS.low.maxPixelRatio);
}
