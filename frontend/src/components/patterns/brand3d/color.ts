/**
 * Brand colour helpers. `untone` is the fix measured in the skill's BRAND.md:
 * three's ACES tone mapping shifts a scene background off its swatch, so the
 * background and fog use the colour ACES maps back onto #071F43 exactly.
 * Pure, so the round trip is tested without WebGL.
 */
import { clamp01, lerp, type Vec3 } from "./math";

/** "#F5A900" -> [r, g, b] in 0..1, sRGB as the brand tokens are written. */
export function hexToRgb(hex: string): Vec3 {
  const h = hex.replace("#", "");
  const full = h.length === 3 ? h.split("").map((c) => c + c).join("") : h;
  return [0, 2, 4].map((i) => parseInt(full.slice(i, i + 2), 16) / 255) as Vec3;
}

export const srgbToLinear = (c: number): number => (c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4));
export const linearToSrgb = (c: number): number => (c <= 0.0031308 ? c * 12.92 : 1.055 * Math.pow(c, 1 / 2.4) - 0.055);

/** Mix two brand hexes (the kit's PF.mix): u = 0 gives `a`, 1 gives `b`. */
export function mixHex(a: string, b: string, u: number): string {
  const x = hexToRgb(a);
  const y = hexToRgb(b);
  return "#" + x.map((v, i) => Math.round(lerp(v, y[i], clamp01(u)) * 255).toString(16).padStart(2, "0")).join("");
}

// three.js ACESFilmicToneMapping (tonemapping_pars_fragment), written row-major.
const ACES_IN = [0.59719, 0.35458, 0.04823, 0.076, 0.90834, 0.01566, 0.0284, 0.13383, 0.83777];
const ACES_OUT = [1.60475, -0.53108, -0.07367, -0.10208, 1.10813, -0.00605, -0.00327, -0.07276, 1.07602];

function mul(m: readonly number[], v: Vec3): Vec3 {
  return [
    m[0] * v[0] + m[1] * v[1] + m[2] * v[2],
    m[3] * v[0] + m[4] * v[1] + m[5] * v[2],
    m[6] * v[0] + m[7] * v[1] + m[8] * v[2],
  ];
}

function inverse(m: readonly number[]): number[] {
  const [a, b, c, d, e, f, g, h, i] = m;
  const A = e * i - f * h;
  const B = -(d * i - f * g);
  const C = d * h - e * g;
  const det = a * A + b * B + c * C;
  return [
    A / det, -(b * i - c * h) / det, (b * f - c * e) / det,
    B / det, (a * i - c * g) / det, -(a * f - c * d) / det,
    C / det, -(a * h - b * g) / det, (a * e - b * d) / det,
  ];
}

const fit = (x: number) => (x * (x + 0.0245786) - 0.000090537) / (x * (0.983729 * x + 0.432951) + 0.238081);

function unfit(y: number): number {
  const a = 1 - 0.983729 * y;
  const b = 0.0245786 - 0.432951 * y;
  const c = -0.000090537 - 0.238081 * y;
  return (-b + Math.sqrt(b * b - 4 * a * c)) / (2 * a);
}

/** What three's ACES filmic tone mapping at `exposure` does to a linear colour (linear out, before the sRGB encode). */
export function acesFilmic(linear: Vec3, exposure: number): Vec3 {
  const v = mul(ACES_IN, linear.map((c) => (c * exposure) / 0.6) as Vec3);
  return mul(ACES_OUT, v.map(fit) as Vec3).map(clamp01) as Vec3;
}

/** The linear colour that ACES at `exposure` turns back into exactly `hex`. */
export function untone(hex: string, exposure: number): Vec3 {
  const target = hexToRgb(hex).map(srgbToLinear) as Vec3;
  const v = mul(inverse(ACES_OUT), target).map(unfit) as Vec3;
  return mul(inverse(ACES_IN), v).map((c) => (c * 0.6) / exposure) as Vec3;
}
