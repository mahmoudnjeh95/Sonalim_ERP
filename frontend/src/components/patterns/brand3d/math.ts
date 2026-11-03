/**
 * Maths shared by the brand 3D scene, ported from the brand-motion-design
 * skill's kit (kit/film.js). Pure: no DOM, no WebGL, so it runs under Vitest.
 */

export type Vec2 = [number, number];
export type Vec3 = [number, number, number];

export const clamp01 = (u: number): number => (u < 0 ? 0 : u > 1 ? 1 : u);
export const lerp = (a: number, b: number, u: number): number => a + (b - a) * u;
/** How far through [start, start + length] time `t` is, clamped to 0..1. */
export const progress = (t: number, start: number, length: number): number => clamp01((t - start) / length);

/** A CSS cubic-bezier() as a function of 0..1 (the kit's PF.bezier). */
export function bezier(x1: number, y1: number, x2: number, y2: number): (x: number) => number {
  const cx = 3 * x1;
  const bx = 3 * (x2 - x1) - cx;
  const ax = 1 - cx - bx;
  const cy = 3 * y1;
  const by = 3 * (y2 - y1) - cy;
  const ay = 1 - cy - by;
  const sx = (u: number) => ((ax * u + bx) * u + cx) * u;
  const sy = (u: number) => ((ay * u + by) * u + cy) * u;
  const dx = (u: number) => (3 * ax * u + 2 * bx) * u + cx;
  function solve(x: number): number {
    let u = x;
    for (let i = 0; i < 8; i++) {
      const e = sx(u) - x;
      if (Math.abs(e) < 1e-6) return u;
      const d = dx(u);
      if (Math.abs(d) < 1e-6) break;
      u -= e / d;
    }
    let lo = 0;
    let hi = 1;
    u = x;
    while (lo < hi) {
      const v = sx(u);
      if (Math.abs(v - x) < 1e-6) return u;
      if (x > v) lo = u;
      else hi = u;
      u = (lo + hi) / 2;
      if (hi - lo < 1e-7) break;
    }
    return u;
  }
  return (x) => (x <= 0 ? 0 : x >= 1 ? 1 : sy(solve(x)));
}

/** The app's motion token: EASE = [0.22, 1, 0.36, 1] in LoginPage.tsx and BrandLoader.tsx. */
export const brandEase = bezier(0.22, 1, 0.36, 1);
/** CSS `ease`: the timing of logo-mark.svg's own build. */
export const cssEase = bezier(0.25, 0.1, 0.25, 1);
/** Symmetric ease for camera moves and the skip fast-forward. */
export const easeInOut = bezier(0.65, 0, 0.35, 1);

/** Seeded PRNG (mulberry32), the scene's only randomness: every layout repeats exactly. */
export function random(seed: number): () => number {
  let s = seed >>> 0;
  return () => {
    s = (s + 0x6d2b79f5) >>> 0;
    let r = Math.imul(s ^ (s >>> 15), 1 | s);
    r = (r + Math.imul(r ^ (r >>> 7), 61 | r)) ^ r;
    return ((r ^ (r >>> 14)) >>> 0) / 4294967296;
  };
}
