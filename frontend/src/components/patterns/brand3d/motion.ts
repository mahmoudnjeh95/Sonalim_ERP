/**
 * Where every pasta piece and semolina grain is at a given time. Pure, so the
 * layout's promises are tested: pasta never covers the 3D logo (spec §1–3).
 *
 * Pieces run on two tracks. "orbit" pieces circle behind the logo's plane
 * (z ≤ -1.4, so even a spaghetti's tip stays behind it). "side" pieces drift
 * up the edges of the frame, nearer the camera but never across the logo.
 */
import { brandEase, clamp01, lerp, progress, random, type Vec3 } from "./math";
import { INTRO, type IntroState } from "./timeline";

export type PastaShape = "spaghetti" | "coquillette" | "torsade" | "vermicelle";
export const SHAPES: readonly PastaShape[] = ["spaghetti", "coquillette", "torsade", "vermicelle"];

/** 20-piece pattern with the plant's mix (4 spaghetti, 7 coquillettes, 6 torsadés, 3 vermicelles); any prefix keeps it. */
const PATTERN: readonly PastaShape[] = [
  "coquillette", "torsade", "spaghetti", "coquillette", "vermicelle",
  "torsade", "coquillette", "spaghetti", "torsade", "coquillette",
  "torsade", "spaghetti", "coquillette", "vermicelle", "torsade",
  "coquillette", "spaghetti", "torsade", "coquillette", "vermicelle",
];

/** Half the longest piece (spaghetti 1.8 long, scaled up to 1.3). */
export const PIECE_EXTENT = 1.2;
const SIDE_SPAN = 14; // side pieces wrap over y in [-7, 7]: off screen at every framing

export interface PieceSeed {
  index: number;
  shape: PastaShape;
  track: "orbit" | "side";
  /** orbit: ellipse semi-axes, centre depth, height, phase (rad), angular speed (rad/s). */
  ax: number;
  az: number;
  centerZ: number;
  height: number;
  phase: number;
  speed: number;
  /** side: fixed x and z, rise speed (units/s); `phase` sets the starting height. */
  x: number;
  z: number;
  rise: number;
  size: number;
  /** rad/s per axis: one dominant axis, a full tumble every 20–40 s. */
  spin: Vec3;
  tilt: Vec3;
  /** 0..1 along the gold ramp. */
  tone: number;
  /** 0..1 stagger of the moment it forms. */
  formDelay: number;
}

export interface Pose {
  position: Vec3;
  rotation: Vec3;
  scale: number;
}

export function pieceSeeds(count: number, seed: number): PieceSeed[] {
  return Array.from({ length: count }, (_, index) => {
    const r = random(seed + index * 7919);
    const spin: Vec3 = [lerp(-0.08, 0.08, r()), lerp(-0.08, 0.08, r()), lerp(-0.08, 0.08, r())];
    spin[Math.floor(r() * 3)] = (r() < 0.5 ? -1 : 1) * lerp(0.16, 0.31, r());
    return {
      index,
      shape: PATTERN[index % PATTERN.length],
      track: r() < 0.7 ? "orbit" : "side",
      ax: lerp(2.0, 5.0, r()),
      az: lerp(0.6, 1.4, r()),
      centerZ: lerp(-2.8, -4.5, r()),
      height: lerp(-3, 3, r()), // fills a portrait frame too; orbit pieces stay behind the logo whatever their height
      phase: r() * Math.PI * 2,
      speed: lerp(0.04, 0.09, r()),
      x: (r() < 0.5 ? -1 : 1) * lerp(2.6, 4.2, r()),
      z: lerp(-1, 2, r()),
      rise: lerp(0.05, 0.12, r()),
      size: lerp(0.8, 1.3, r()),
      spin,
      tilt: [r() * Math.PI * 2, r() * Math.PI * 2, r() * Math.PI * 2],
      tone: r(),
      formDelay: r(),
    };
  });
}

function home(p: PieceSeed, time: number): Vec3 {
  if (p.track === "orbit") {
    const a = p.phase + p.speed * time;
    return [p.ax * Math.cos(a), p.height + 0.2 * Math.sin(time * 0.3 + p.phase), p.centerZ + p.az * Math.sin(a)];
  }
  const y = ((((p.phase / (Math.PI * 2)) * SIDE_SPAN + p.rise * time) % SIDE_SPAN) + SIDE_SPAN) % SIDE_SPAN - SIDE_SPAN / 2;
  return [p.x, y, p.z];
}

/**
 * A piece's pose at stage `time`. During the intro it forms out of the grains
 * nearer the centre (x and y pulled in, depth kept, so orbit pieces stay behind
 * the logo) and tumbles out onto its track, arriving exactly on the login pose.
 */
export function piecePose(p: PieceSeed, time: number, intro: IntroState | null): Pose {
  const position = home(p, time);
  const rotation: Vec3 = [p.tilt[0] + p.spin[0] * time, p.tilt[1] + p.spin[1] * time, p.tilt[2] + p.spin[2] * time];
  if (!intro) return { position, rotation, scale: p.size };
  const formed = brandEase(progress(intro.condense, 0.35 + p.formDelay * 0.4, 0.25));
  if (formed >= 1 && intro.orbit >= 1) return { position, rotation, scale: p.size };
  const pull = lerp(0.55, 1, intro.orbit);
  const turn = Math.PI * (1 - intro.orbit); // the last half tumble settles as it reaches its track
  return {
    position: [position[0] * pull, position[1] * pull, position[2]],
    rotation: [rotation[0] + turn, rotation[1], rotation[2] + turn * 0.5],
    scale: p.size * formed,
  };
}

export interface GrainSeed {
  index: number;
  /** The piece it condenses into (modulo the live piece count). */
  piece: number;
  /** 0..0.35: how far behind the stream's head it travels. */
  lag: number;
  angle: number;
  radial: number;
  offset: Vec3;
  dust: Vec3;
  rise: number;
  /** A spark: drawn brighter than white so it alone blooms. */
  glow: boolean;
  tone: number;
}

/** The volume the login's floating dust fills. */
export const DUST = { x: 9, y: 7, zNear: 1.5, zFar: -12 } as const;

export function grainSeeds(count: number, seed: number): GrainSeed[] {
  return Array.from({ length: count }, (_, index) => {
    const r = random(seed + index * 104729);
    return {
      index,
      piece: index,
      lag: r() * 0.35,
      angle: r() * Math.PI * 2,
      radial: r(),
      offset: [lerp(-0.22, 0.22, r()), lerp(-0.22, 0.22, r()), lerp(-0.22, 0.22, r())],
      dust: [lerp(-DUST.x, DUST.x, r()), lerp(-DUST.y, DUST.y, r()), lerp(DUST.zFar, DUST.zNear, r())],
      rise: lerp(0.03, 0.1, r()),
      glow: r() < 0.04,
      tone: r(),
    };
  });
}

/** The semolina stream: a spiral from the depth (v = 0) to the centre (v = 1), the splash art's wave in 3D. */
function streamPoint(g: GrainSeed, v: number, out: Vec3): void {
  const a = g.angle + v * Math.PI * 3;
  const radius = lerp(3.2, 0.5, v) + g.radial * 0.4;
  out[0] = radius * Math.cos(a);
  out[1] = radius * Math.sin(a) * 0.6 + 0.3 * Math.sin(v * 6 + g.angle);
  out[2] = lerp(-14, 0, v);
}

/** Writes a grain's position into `out` and returns its opacity (0..1). */
export function grainPosition(
  g: GrainSeed,
  time: number,
  intro: { t: number; state: IntroState } | null,
  pieces: readonly Pose[],
  pieceCount: number,
  out: Vec3,
): number {
  if (intro && intro.t < INTRO.pastaEnd) {
    const v = clamp01(intro.state.stream * 1.35 - g.lag);
    streamPoint(g, v, out);
    const c = brandEase(progress(intro.state.condense, g.lag, 0.55));
    if (c > 0) {
      const target = pieces[g.piece % pieceCount].position;
      out[0] = lerp(out[0], target[0] + g.offset[0], c);
      out[1] = lerp(out[1], target[1] + g.offset[1], c);
      out[2] = lerp(out[2], target[2] + g.offset[2], c);
    }
    return v > 0 ? lerp(0.3, 1, v) * (1 - progress(c, 0.75, 0.25)) : 0;
  }
  // Dust: the same grains float up through the volume, fading in once the pasta has formed.
  const span = DUST.y * 2;
  out[0] = g.dust[0];
  out[1] = ((((g.dust[1] + DUST.y + g.rise * time) % span) + span) % span) - DUST.y;
  out[2] = g.dust[2];
  const fade = intro ? progress(intro.t, INTRO.pastaEnd, 1) : 1;
  return lerp(0.35, 0.85, g.tone) * fade;
}
