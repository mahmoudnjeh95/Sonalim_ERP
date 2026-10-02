/**
 * Reads the logo's geometry straight from logo-mark.svg, so the 3D mark is
 * built from the same file the app shows in 2D and follows it if it changes.
 * Pure string parsing (no DOMParser), so it runs under Vitest. It handles
 * exactly what the mark uses (M/m, L/l, C/c, Z/z) and refuses anything else.
 */
import type { Vec2 } from "./math";

export type Segment = { kind: "L"; to: Vec2 } | { kind: "C"; c1: Vec2; c2: Vec2; to: Vec2 };

export interface SubPath {
  start: Vec2;
  segments: Segment[];
  closed: boolean;
}

export interface GlyphStroke {
  width: number;
  subpaths: SubPath[];
}

export interface LogoSpec {
  viewBox: number;
  ring: { cx: number; cy: number; r: number; width: number };
  glyph: { translate: Vec2; scale: number; strokes: GlyphStroke[] };
}

const attrs = (tag: string): Record<string, string> =>
  Object.fromEntries([...tag.matchAll(/([\w:-]+)="([^"]*)"/g)].map((m) => [m[1], m[2]]));

export function parsePathData(d: string): SubPath[] {
  const tokens = d.match(/[A-Za-z]|-?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?/g) ?? [];
  const out: SubPath[] = [];
  let i = 0;
  let cmd = "";
  let cur: Vec2 = [0, 0];
  let path: SubPath | null = null;
  const num = (): number => {
    const v = Number(tokens[i++]);
    if (Number.isNaN(v)) throw new Error(`logo path: expected a number in "${d}"`);
    return v;
  };
  // Relative points (lower-case commands) are offsets from the point the segment starts at.
  const point = (relative: boolean): Vec2 => {
    const x = num();
    const y = num();
    return relative ? [cur[0] + x, cur[1] + y] : [x, y];
  };
  const current = (): SubPath => {
    if (!path) throw new Error(`logo path: drawing before a move in "${d}"`);
    return path;
  };

  while (i < tokens.length) {
    if (/[A-Za-z]/.test(tokens[i])) cmd = tokens[i++];
    else if (!cmd) throw new Error(`logo path: number before any command in "${d}"`);
    const relative = cmd === cmd.toLowerCase();
    switch (cmd.toUpperCase()) {
      case "M":
        cur = point(relative);
        path = { start: cur, segments: [], closed: false };
        out.push(path);
        cmd = relative ? "l" : "L"; // further pairs after a move are line-tos
        break;
      case "L": {
        const to = point(relative);
        current().segments.push({ kind: "L", to });
        cur = to;
        break;
      }
      case "C": {
        const c1 = point(relative);
        const c2 = point(relative);
        const to = point(relative);
        current().segments.push({ kind: "C", c1, c2, to });
        cur = to;
        break;
      }
      case "Z":
        current().closed = true;
        cur = current().start;
        cmd = "";
        break;
      default:
        throw new Error(`logo path: unsupported command "${cmd}" in "${d}"`);
    }
  }
  return out;
}

export function parseLogoSvg(svg: string): LogoSpec {
  const viewBox = Number(/viewBox="0 0 ([\d.]+) [\d.]+"/.exec(svg)?.[1]);
  const circles = [...svg.matchAll(/<circle\b[^>]*>/g)].map((m) => attrs(m[0]));
  const ring = circles.find((c) => (c.class ?? "").includes("orbit")) ?? circles[0];
  const glyph = [...svg.matchAll(/<g\b([^>]*)>([\s\S]*?)<\/g>/g)].find((g) => (attrs(g[1]).class ?? "").includes("glyph"));
  if (!viewBox || !ring || !glyph) throw new Error("logo-mark.svg: viewBox, ring or glyph group not found");
  const transform = /translate\(([-\d.]+)[ ,]+([-\d.]+)\)\s*scale\(([-\d.]+)\)/.exec(attrs(glyph[1]).transform ?? "");
  if (!transform) throw new Error("logo-mark.svg: glyph transform is not translate(...) scale(...)");
  const strokes = [...glyph[2].matchAll(/<path\b[^>]*>/g)].map((m) => {
    const a = attrs(m[0]);
    return { width: Number(a["stroke-width"]), subpaths: parsePathData(a.d) };
  });
  return {
    viewBox,
    ring: { cx: Number(ring.cx), cy: Number(ring.cy), r: Number(ring.r), width: Number(ring["stroke-width"]) },
    glyph: { translate: [Number(transform[1]), Number(transform[2])], scale: Number(transform[3]), strokes },
  };
}

/** A glyph point (path units) in logo space: centred, y up, the viewBox mapped to [-1, 1]. */
export function toLogoSpace([x, y]: Vec2, spec: LogoSpec): Vec2 {
  const half = spec.viewBox / 2;
  const [tx, ty] = spec.glyph.translate;
  return [(tx + spec.glyph.scale * x - half) / half, -(ty + spec.glyph.scale * y - half) / half];
}
